from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import StudentGroup
from accounts.utils import create_students
from reactions.models import Reaction, Tag

from .logic import answer_form, find_ambiguities, item_view
from .models import Answer, Appeal, Assignment, AssignmentItem, Submission


class FlowTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user("teacher", password="pass12345", is_staff=True)
        self.group = StudentGroup.objects.create(name="10А")
        self.creds = create_students(self.group, ["Иванов Иван", "Иванов Илья", "Петрова Мария"])
        self.client.force_login(self.teacher)

    def import_text(self, text, new_tags=""):
        r = self.client.post(reverse("reaction_import"), {"text": text, "new_tags": new_tags, "step": "preview"})
        self.assertEqual(r.status_code, 200)
        rows = r.context["rows"]
        data = {"text": text, "new_tags": new_tags, "step": "save"}
        for row in rows:
            if row["include"]:
                data[f"include_{row['n']}"] = "1"
                data[f"choice_{row['n']}"] = row["choice"]
        self.client.post(reverse("reaction_import"), data)
        return rows

    def test_logins(self):
        logins = [c["login"] for c in self.creds]
        self.assertEqual(logins, ["ivanov.i", "ivanov.i2", "petrova.m"])
        self.client.logout()
        ok = self.client.login(username=self.creds[0]["login"], password=self.creds[0]["password"])
        self.assertTrue(ok)

    def test_credentials_shown_once(self):
        r = self.client.post(reverse("group_detail", args=[self.group.pk]), {"names": "Сидоров Пётр", "prefix": ""}, follow=True)
        self.assertContains(r, "sidorov.p")
        self.assertEqual(len(r.context["creds"][0]["password"]), 8)
        r = self.client.get(reverse("group_credentials", args=[self.group.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.group.students.count(), 4)

    def test_import_balances_and_dedupes(self):
        rows = self.import_text("Al + O2 = Al2O3\nO2 + Al → Al2O3\nH2 + O2 = H2O\nNa + Cl2 = KCl\nbad line")
        self.assertEqual(rows[0]["choice"], "opt0")
        self.assertEqual(rows[1].get("batch_dup"), 1)
        self.assertIn("error", rows[4])
        self.assertEqual(Reaction.objects.count(), 2)  # Al+O2 и H2+O2; KCl не уравнивается
        al = Reaction.objects.get(components__formula="Al2O3")
        self.assertEqual([c.coef for c in al.components.all()], [4, 3, 2])
        rows = self.import_text("4Al + 3O2 = 2Al2O3")
        self.assertTrue(rows[0]["db_dups"])
        self.assertEqual(Reaction.objects.count(), 2)
        # другие условия — другая реакция
        self.import_text("4Al + 3O2 =(t) 2Al2O3")
        self.assertEqual(Reaction.objects.count(), 3)

    def make_assignment(self, **kw):
        self.import_text("Cu + HNO3(конц.) → Cu(NO3)2 + NO2 + H2O\n"
                         "Cu + HNO3 → Cu(NO3)2 + NO + H2O\n"
                         "NaOH + HCl = NaCl + H2O")
        a = Assignment.objects.create(title="Тест", created_by=self.teacher, **kw)
        a.groups.add(self.group)
        for i, r in enumerate(Reaction.objects.order_by("id")):
            AssignmentItem.objects.create(assignment=a, reaction=r, position=i)
        return a

    def test_visibility_and_ambiguity(self):
        a = self.make_assignment(show_reactants=True, show_products=False)
        conc, dil, neut = list(a.items.all())
        # «Cu + HNO3» (без пояснения) совпадает с обоими вариантами азотной кислоты
        self.assertEqual([r.pk for r in find_ambiguities(dil)], [conc.reaction_id])
        self.assertEqual(find_ambiguities(neut), [])
        # если показано число продуктов — всё равно совпадает (по 3 продукта)
        dil.show_count = True
        self.assertEqual(len(find_ambiguities(dil)), 1)
        # показали продукт NO — неоднозначность пропадает
        dil.overrides = {"R:NO": True}
        self.assertEqual(find_ambiguities(dil), [])

        neut.hide_water = True
        neut.show_products = True
        v = item_view(neut)
        self.assertEqual([s.formula for s in v.visible("R")], ["NaCl"])
        form = answer_form(v, None)
        self.assertTrue(form["L"]["can_add"] and form["R"]["can_add"])

        # публикация требует решения по неоднозначности
        r = self.client.post(reverse("assignment_publish", args=[a.pk]), {"action": "publish"})
        self.assertIn("check", r["Location"])
        a.refresh_from_db()
        self.assertFalse(a.is_published)
        r = self.client.post(reverse("assignment_check", args=[a.pk]),
                             {f"dec_{dil.pk}_{conc.reaction_id}": "alt",
                              f"dec_{conc.pk}_{dil.reaction_id}": "no", "publish": "1"})
        a.refresh_from_db()
        self.assertTrue(a.is_published)
        self.assertIn(conc.reaction, dil.alternatives.all())

    def student_client(self, idx=0):
        from django.test import Client
        c = Client()
        self.assertTrue(c.login(username=self.creds[idx]["login"], password=self.creds[idx]["password"]))
        return c

    def test_student_flow_grading_appeal_regrade(self):
        a = self.make_assignment(is_published=True, results_mode=Assignment.RESULTS_MANUAL)
        conc, dil, neut = list(a.items.all())
        s = self.student_client()
        r = s.get(reverse("student_assignment", args=[a.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "a_%d_R_0_f" % neut.pk)

        post = {
            "action": "save",
            # концентрированная: верно
            f"a_{conc.pk}_L_0_c": "", f"a_{conc.pk}_L_0_f": "Cu", f"a_{conc.pk}_L_0_t": "fixed",
            f"a_{conc.pk}_L_1_c": "4", f"a_{conc.pk}_L_1_f": "HNO3", f"a_{conc.pk}_L_1_t": "fixed",
            f"a_{conc.pk}_R_0_c": "", f"a_{conc.pk}_R_0_f": "Cu(NO3)2", f"a_{conc.pk}_R_0_t": "extra",
            f"a_{conc.pk}_R_1_c": "2", f"a_{conc.pk}_R_1_f": "NO2", f"a_{conc.pk}_R_1_t": "extra",
            f"a_{conc.pk}_R_5_c": "2", f"a_{conc.pk}_R_5_f": "H2O", f"a_{conc.pk}_R_5_t": "extra",
            # разбавленная: ученик написал продукты концентрированной (уравнено, но не эталон)
            f"a_{dil.pk}_L_0_c": "", f"a_{dil.pk}_L_0_f": "Cu", f"a_{dil.pk}_L_0_t": "fixed",
            f"a_{dil.pk}_L_1_c": "4", f"a_{dil.pk}_L_1_f": "HNO3", f"a_{dil.pk}_L_1_t": "fixed",
            f"a_{dil.pk}_R_0_c": "", f"a_{dil.pk}_R_0_f": "Cu(NO3)2", f"a_{dil.pk}_R_0_t": "extra",
            f"a_{dil.pk}_R_1_c": "2", f"a_{dil.pk}_R_1_f": "NO2", f"a_{dil.pk}_R_1_t": "extra",
            f"a_{dil.pk}_R_2_c": "2", f"a_{dil.pk}_R_2_f": "H2O", f"a_{dil.pk}_R_2_t": "extra",
            # нейтрализация: коэффициенты неверные
            f"a_{neut.pk}_L_0_c": "2", f"a_{neut.pk}_L_0_f": "NaOH", f"a_{neut.pk}_L_0_t": "fixed",
            f"a_{neut.pk}_L_1_c": "", f"a_{neut.pk}_L_1_f": "HCl", f"a_{neut.pk}_L_1_t": "fixed",
            f"a_{neut.pk}_R_0_c": "", f"a_{neut.pk}_R_0_f": "NaCl", f"a_{neut.pk}_R_0_t": "extra",
            f"a_{neut.pk}_R_1_c": "", f"a_{neut.pk}_R_1_f": "H2O", f"a_{neut.pk}_R_1_t": "extra",
        }
        s.post(reverse("student_assignment", args=[a.pk]), post)
        sub = Submission.objects.get(assignment=a)
        self.assertEqual(sub.status, Submission.DRAFT)
        r = s.get(reverse("student_assignment", args=[a.pk]))
        self.assertContains(r, 'value="NO2"')

        post["action"] = "submit"
        s.post(reverse("student_assignment", args=[a.pk]), post)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Submission.SUBMITTED)
        verdicts = {ans.item_id: ans.verdict for ans in sub.answers.all()}
        self.assertEqual(verdicts, {conc.pk: "correct", dil.pk: "wrong", neut.pk: "partial"})
        self.assertEqual(sub.score, 1.5)

        # результаты скрыты до подтверждения учителем
        r = s.get(reverse("student_assignment", args=[a.pk]))
        self.assertFalse(r.context["visible"])
        self.client.post(reverse("assignment_release", args=[a.pk]), {"action": "show"})
        r = s.get(reverse("student_assignment", args=[a.pk]))
        self.assertTrue(r.context["visible"])

        # апелляция по разбавленной кислоте
        ans = sub.answers.get(item=dil)
        s.post(reverse("appeal_create", args=[a.pk]), {"answer": ans.pk, "text": "Я считаю, что так тоже верно"})
        ap = Appeal.objects.get()
        self.assertEqual(ap.status, Appeal.OPEN)
        r = self.client.get(reverse("submission_detail", args=[sub.pk]))
        self.assertEqual(r.status_code, 200)

        # учитель добавляет концентрированный вариант как допустимый -> перепроверка
        dil.alternatives.add(conc.reaction)
        self.client.post(reverse("assignment_regrade", args=[a.pk]))
        sub.refresh_from_db()
        self.assertEqual(sub.score, 2.5)

        # ручная оценка сохраняется при перепроверке
        nans = sub.answers.get(item=neut)
        self.client.post(reverse("submission_detail", args=[sub.pk]),
                         {"action": "score", "answer": nans.pk, "manual_score": "1", "manual_comment": "ок"})
        self.client.post(reverse("assignment_regrade", args=[a.pk]))
        sub.refresh_from_db()
        self.assertEqual(sub.score, 3)

        self.client.post(reverse("submission_detail", args=[sub.pk]),
                         {"action": "appeal", "appeal": ap.pk, "decision": "reject", "response": "уже учтено", "score": ""})
        ap.refresh_from_db()
        self.assertEqual(ap.status, Appeal.REJECTED)

    def test_add_student_answer_as_alternative(self):
        self.import_text("2H2O2 = 2H2O + O2")
        a = Assignment.objects.create(title="Т", is_published=True, show_reactants=True, show_products=False)
        a.groups.add(self.group)
        item = AssignmentItem.objects.create(assignment=a, reaction=Reaction.objects.get())
        s = self.student_client(2)
        s.post(reverse("student_assignment", args=[a.pk]), {
            "action": "submit",
            f"a_{item.pk}_L_0_c": "1", f"a_{item.pk}_L_0_f": "H2O2", f"a_{item.pk}_L_0_t": "fixed",
            f"a_{item.pk}_R_0_c": "1", f"a_{item.pk}_R_0_f": "H2", f"a_{item.pk}_R_0_t": "extra",
            f"a_{item.pk}_R_1_c": "1", f"a_{item.pk}_R_1_f": "O2", f"a_{item.pk}_R_1_t": "extra",
        })
        ans = Answer.objects.get()
        self.assertEqual(ans.verdict, "wrong")
        self.client.post(reverse("submission_detail", args=[ans.submission_id]),
                         {"action": "add_alternative", "answer": ans.pk})
        ans.refresh_from_db()
        self.assertEqual(ans.verdict, "correct")
        self.assertEqual(Reaction.objects.count(), 2)

    def test_deadline_and_date_results(self):
        a = self.make_assignment(is_published=True, due_at=timezone.now() - timedelta(hours=1),
                                 results_mode=Assignment.RESULTS_DATE,
                                 results_date=timezone.now() + timedelta(days=1))
        s = self.student_client()
        s.post(reverse("student_assignment", args=[a.pk]), {"action": "submit"})
        self.assertFalse(Submission.objects.filter(status=Submission.SUBMITTED).exists())
        a.allow_late = True
        a.save()
        s.post(reverse("student_assignment", args=[a.pk]), {"action": "submit"})
        sub = Submission.objects.get()
        self.assertTrue(sub.is_late)
        self.assertFalse(sub.results_visible())
        a.results_date = timezone.now() - timedelta(minutes=1)
        a.save()
        sub.refresh_from_db()
        self.assertTrue(sub.results_visible())

    def test_pages_render(self):
        a = self.make_assignment()
        for name, args in [("teacher_dashboard", []), ("group_list", []), ("group_detail", [self.group.pk]),
                           ("reaction_list", []), ("reaction_import", []), ("reaction_new", []),
                           ("reaction_edit", [Reaction.objects.first().pk]), ("assignment_list", []),
                           ("assignment_new", []), ("assignment_detail", [a.pk]), ("assignment_edit", [a.pk]),
                           ("assignment_add", [a.pk]), ("assignment_check", [a.pk]), ("assignment_preview", [a.pk]),
                           ("assignment_results", [a.pk]), ("appeal_list", []), ("tag_list", [])]:
            r = self.client.get(reverse(name, args=args))
            self.assertEqual(r.status_code, 200, name)
        r = self.client.get(reverse("assignment_results", args=[a.pk]) + "?format=csv")
        self.assertEqual(r.status_code, 200)

    def test_builder_save(self):
        a = self.make_assignment()
        item = a.items.first()
        self.client.post(reverse("assignment_detail", args=[a.pk]), {
            f"show_products_{item.pk}": "1", f"hide_water_{item.pk}": "0", f"ov_{item.pk}_R:NO2": "0"})
        item.refresh_from_db()
        self.assertEqual((item.show_products, item.hide_water, item.show_count), (True, False, None))
        self.assertEqual(item.overrides, {"R:NO2": False})
        v = item_view(item)
        self.assertEqual(v.hidden_count("R"), 1)

    def test_teacher_sets_password(self):
        st = self.group.students.get(user__username="petrova.m")
        url = reverse("student_action", args=[st.pk])
        self.client.post(url, {"action": "set_password", "password": "123"})
        self.assertTrue(st.user.check_password(self.creds[2]["password"]))  # слишком короткий — не изменён
        self.client.post(url, {"action": "set_password", "password": "himiya-2026"})
        st.user.refresh_from_db()
        self.assertTrue(st.user.check_password("himiya-2026"))

    def test_single_water_notice(self):
        a = self.make_assignment(is_published=True)
        s = self.student_client()
        r = s.get(reverse("student_assignment", args=[a.pk]))
        self.assertEqual(r.context["water_mode"], "")
        item = a.items.first()
        item.hide_water = True
        item.save()
        r = s.get(reverse("student_assignment", args=[a.pk]))
        self.assertEqual(r.context["water_mode"], "some")
        self.assertContains(r, "вода не показана", count=1)
        a.hide_water = True
        a.save()
        r = s.get(reverse("student_assignment", args=[a.pk]))
        self.assertEqual(r.context["water_mode"], "all")

    def test_tags(self):
        Tag.objects.create(name="ОВР")
        ovr = Tag.objects.get()
        text = "Al + O2 = Al2O3"
        self.client.post(reverse("reaction_import"), {"text": text, "step": "save", "include_1": "1",
                                                      "choice_1": "opt0", "tags": [ovr.pk], "new_tags": "9 класс, овр"})
        r = Reaction.objects.get()
        self.assertEqual(sorted(t.name for t in r.tags.all()), ["9 класс", "ОВР"])
        self.assertEqual(Tag.objects.count(), 2)
        # поиск без учёта регистра работает и для кириллицы
        resp = self.client.get(reverse("reaction_list") + "?q=овр")
        self.assertEqual(resp.context["total"], 1)
        self.assertEqual(Tag.objects.filter(name__iexact="овр").count(), 1)
        self.assertEqual([t.name for t in Tag.objects.all()], ["9 класс", "ОВР"])
        # фильтр по тэгу
        resp = self.client.get(reverse("reaction_list") + f"?tag={ovr.pk}")
        self.assertEqual(resp.context["total"], 1)
        resp = self.client.get(reverse("reaction_list") + "?tag=-")
        self.assertEqual(resp.context["total"], 0)
        # правка реакции: снять тэг, добавить новый
        self.client.post(reverse("reaction_edit", args=[r.pk]),
                         {"text": r.text(), "comment": "", "tags": [ovr.pk], "new_tags": "оксиды"})
        self.assertEqual(sorted(t.name for t in r.tags.all()), ["ОВР", "оксиды"])
        # переименование в существующее имя объединяет тэги
        ox = Tag.objects.get(name="оксиды")
        self.client.post(reverse("tag_list"), {"action": "rename", "tag": ox.pk, "name": "овр"})
        self.assertEqual([t.name for t in r.tags.all()], ["ОВР"])
        self.client.post(reverse("tag_list"), {"action": "delete", "tag": ovr.pk})
        self.assertEqual(r.tags.count(), 0)
        self.assertEqual(Reaction.objects.count(), 1)

    def test_live_preview(self):
        r = self.client.get(reverse("reaction_live_preview"), {"text": "Zn + HCl →_(HCl_((aq.))) ZnCl2 + H2"})
        self.assertContains(r, "<sub>(aq.)</sub>")
        self.assertContains(r, "Коэффициенты не указаны")
        r = self.client.get(reverse("reaction_live_preview"), {"text": "H2 + O2"})
        self.assertContains(r, "стрелка")

    def test_builder_preview_saves_first(self):
        a = self.make_assignment()
        item = a.items.first()
        r = self.client.post(reverse("assignment_detail", args=[a.pk]),
                             {f"show_reactants_{item.pk}": "", f"show_products_{item.pk}": "1", "action": "preview"})
        self.assertEqual(r["Location"], reverse("assignment_preview", args=[a.pk]))
        item.refresh_from_db()
        self.assertTrue(item.show_products)
        # перемещение пункта тоже сохраняет несохранённые настройки
        second = a.items.all()[1]
        self.client.post(reverse("item_action", args=[a.pk, second.pk]),
                         {"action": "up", f"show_reactants_{second.pk}": "0"})
        second.refresh_from_db()
        self.assertEqual((second.position, second.show_reactants), (0, False))

    def test_student_cannot_see_teacher_pages(self):
        s = self.student_client()
        r = s.get(reverse("assignment_list"))
        self.assertEqual(r.status_code, 302)
