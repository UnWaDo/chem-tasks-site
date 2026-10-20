import csv

from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Student, StudentGroup
from accounts.views import teacher_required
from chem.equation import EquationError, equation_text, parse_equation
from chem.grading import collect_side
from reactions.models import Reaction, Tag
from reactions.tags import filter_reactions

from .render import answer_html, preview_html
from .logic import _items_qs, assignment_ambiguities, grade_submission, item_view, regrade_assignment
from .models import Answer, Appeal, Assignment, AssignmentItem, Submission

ITEM_FLAGS = ["show_reactants", "show_products", "show_count", "hide_water"]


class DateTimeLocal(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kw):
        super().__init__(format="%Y-%m-%dT%H:%M", **kw)


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ["title", "description", "groups", "opens_at", "due_at", "allow_late",
                  "show_reactants", "show_products", "show_count", "hide_water",
                  "results_mode", "results_date", "show_correct_answers", "partial_credit", "allow_appeals"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "groups": forms.CheckboxSelectMultiple,
            "opens_at": DateTimeLocal(),
            "due_at": DateTimeLocal(),
            "results_date": DateTimeLocal(),
            "results_mode": forms.RadioSelect,
        }

    def clean(self):
        data = super().clean()
        if data.get("results_mode") == Assignment.RESULTS_DATE and not data.get("results_date"):
            self.add_error("results_date", "Укажите дату показа результатов.")
        return data


# ------------------------------------------------------------------ вспомогательное

def recompute_total(sub: Submission):
    sub.score = sum(a.score for a in sub.answers.all())
    sub.max_score = sub.assignment.items.count()
    sub.save(update_fields=["score", "max_score"])


def group_students(assignment):
    return (Student.objects.filter(group__in=assignment.groups.all())
            .select_related("user", "group").order_by("group__name", "full_name"))


# ------------------------------------------------------------------ обзор

@teacher_required
def dashboard(request):
    open_appeals = (Appeal.objects.filter(status=Appeal.OPEN)
                    .select_related("answer__submission__student__student", "answer__submission__assignment")[:10])
    recent = (Submission.objects.filter(status=Submission.SUBMITTED)
              .select_related("student__student", "assignment").order_by("-submitted_at")[:10])
    waiting = (Assignment.objects.filter(results_mode=Assignment.RESULTS_MANUAL, results_released=False)
               .annotate(n=Count("submissions", filter=Q(submissions__status="submitted", submissions__released=False)))
               .filter(n__gt=0))
    stats = {
        "groups": StudentGroup.objects.count(), "students": Student.objects.count(),
        "reactions": Reaction.objects.count(), "assignments": Assignment.objects.count(),
    }
    return render(request, "teacher/dashboard.html", {
        "open_appeals": open_appeals, "recent": recent, "waiting": waiting, "stats": stats})


@teacher_required
def assignment_list(request):
    qs = Assignment.objects.prefetch_related("groups").annotate(
        n_items=Count("items", distinct=True),
        n_sub=Count("submissions", filter=Q(submissions__status="submitted"), distinct=True),
    )
    return render(request, "teacher/assignment_list.html", {"assignments": qs})


@teacher_required
def assignment_edit(request, pk=None):
    assignment = get_object_or_404(Assignment, pk=pk) if pk else None
    form = AssignmentForm(request.POST or None, instance=assignment)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not assignment:
            obj.created_by = request.user
        obj.save()
        form.save_m2m()
        messages.success(request, "Задание сохранено.")
        if not assignment:
            return redirect("assignment_add", obj.pk)
        return redirect("assignment_detail", obj.pk)
    return render(request, "teacher/assignment_form.html", {"form": form, "assignment": assignment})


@transaction.atomic
def _save_items(data, items):
    """Сохраняет настройки показа пунктов из формы конструктора задания (если они есть в запросе)."""
    for item in items:
        if not any(f"{f}_{item.id}" in data for f in ITEM_FLAGS):
            continue
        for f in ITEM_FLAGS:
            v = data.get(f"{f}_{item.id}", "")
            setattr(item, f, None if v == "" else v == "1")
        ov = {}
        for c in item.reaction.components.all():
            v = data.get(f"ov_{item.id}_{c.key}", "")
            if v in ("0", "1"):
                ov[c.key] = v == "1"
        item.overrides = ov
        item.save()


@teacher_required
def assignment_detail(request, pk):
    assignment = get_object_or_404(Assignment.objects.prefetch_related("groups"), pk=pk)
    items = list(_items_qs(assignment))

    if request.method == "POST":
        if request.POST.get("action") == "reset_items":
            for item in items:
                for f in ITEM_FLAGS:
                    setattr(item, f, None)
                item.overrides = {}
                item.save()
            messages.success(request, "Индивидуальные настройки всех реакций сброшены.")
            return redirect("assignment_detail", pk)
        _save_items(request.POST, items)
        if request.POST.get("action") == "preview":
            return redirect("assignment_preview", pk)
        messages.success(request, "Настройки показа сохранены.")
        return redirect("assignment_detail", pk)

    rows = []
    for item in items:
        view = item_view(item)
        rows.append({"item": item, "view": view, "preview": preview_html(view),
                     "alternatives": list(item.alternatives.all())})
    n_sub = assignment.submissions.filter(status=Submission.SUBMITTED).count()
    pending = sum(len(x["pending"]) for x in assignment_ambiguities(assignment)) if items else 0
    return render(request, "teacher/assignment_detail.html", {
        "assignment": assignment, "rows": rows, "n_sub": n_sub, "pending": pending,
        "flags": [("show_reactants", "Реагенты"), ("show_products", "Продукты"),
                  ("show_count", "Число веществ"), ("hide_water", "Прятать воду")]})


@teacher_required
def assignment_add(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    if request.method == "POST":
        ids = request.POST.getlist("ids")
        pos = (assignment.items.aggregate(m=Max("position"))["m"] or 0) + 1
        existing = set(assignment.items.values_list("reaction_id", flat=True))
        added = 0
        for rid in ids:
            if int(rid) in existing:
                continue
            AssignmentItem.objects.create(assignment=assignment, reaction_id=rid, position=pos)
            pos += 1
            added += 1
        messages.success(request, f"Добавлено реакций: {added}.")
        if request.POST.get("stay"):
            return redirect(request.get_full_path())
        return redirect("assignment_detail", pk)

    q = request.GET.get("q", "").strip()
    tag = request.GET.get("tag", "")
    qs = filter_reactions(Reaction.objects.prefetch_related("components", "tags"), q, tag).order_by("-id")
    existing = set(assignment.items.values_list("reaction_id", flat=True))
    return render(request, "teacher/assignment_add.html", {
        "assignment": assignment, "reactions": qs[:500], "q": q, "tag": tag, "all_tags": Tag.objects.all(),
        "existing": existing})


@teacher_required
@require_POST
def item_action(request, pk, item_id):
    item = get_object_or_404(AssignmentItem, pk=item_id, assignment_id=pk)
    action = request.POST.get("action")
    # кнопки ↑ ↓ ✕ отправляют всю форму конструктора — сначала сохраняем остальные настройки
    _save_items(request.POST, list(_items_qs(item.assignment)))
    if action == "remove":
        item.delete()
        messages.success(request, "Реакция убрана из задания.")
    elif action in ("up", "down"):
        items = list(item.assignment.items.all())
        i = items.index(item)
        j = i - 1 if action == "up" else i + 1
        if 0 <= j < len(items):
            items[i], items[j] = items[j], items[i]
            for n, it in enumerate(items):
                if it.position != n:
                    it.position = n
                    it.save(update_fields=["position"])
    return redirect("assignment_detail", pk)


@teacher_required
def assignment_check(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    if request.method == "POST":
        data = assignment_ambiguities(assignment)
        for entry in data:
            item = entry["item"]
            for r in entry["found"]:
                dec = request.POST.get(f"dec_{item.id}_{r.id}", "")
                if dec == "alt":
                    item.alternatives.add(r)
                    item.dismissed.remove(r)
                elif dec == "no":
                    item.dismissed.add(r)
                    item.alternatives.remove(r)
        data = assignment_ambiguities(assignment)
        left = sum(len(x["pending"]) for x in data)
        if left == 0:
            assignment.checked_at = timezone.now()
            assignment.save(update_fields=["checked_at"])
            messages.success(request, "Проверка пройдена: все найденные варианты рассмотрены.")
            if request.POST.get("publish"):
                return _publish(request, assignment)
            if assignment.submissions.filter(status=Submission.SUBMITTED).exists():
                messages.info(request, "Если вы добавили допустимые варианты, нажмите «Перепроверить работы».")
            return redirect("assignment_detail", pk)
        messages.warning(request, f"Осталось нерассмотренных вариантов: {left}.")
        return redirect("assignment_check", pk)

    data = assignment_ambiguities(assignment)
    for entry in data:
        entry["preview"] = preview_html(entry["view"])
    return render(request, "teacher/assignment_check.html", {
        "assignment": assignment, "data": [d for d in data if d["found"]],
        "pending": sum(len(x["pending"]) for x in data), "publish": request.GET.get("publish")})


def _publish(request, assignment):
    if not assignment.items.exists():
        messages.error(request, "В задании нет ни одной реакции.")
        return redirect("assignment_detail", assignment.pk)
    pending = sum(len(x["pending"]) for x in assignment_ambiguities(assignment))
    if pending:
        messages.warning(request, "Перед публикацией подтвердите, какие из похожих реакций тоже считать правильными.")
        return redirect(reverse("assignment_check", args=[assignment.pk]) + "?publish=1")
    assignment.is_published = True
    assignment.checked_at = timezone.now()
    assignment.save(update_fields=["is_published", "checked_at"])
    if not assignment.groups.exists():
        messages.warning(request, "Задание опубликовано, но не назначено ни одному классу.")
    else:
        messages.success(request, "Задание опубликовано.")
    return redirect("assignment_detail", assignment.pk)


@teacher_required
@require_POST
def assignment_publish(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    if request.POST.get("action") == "unpublish":
        assignment.is_published = False
        assignment.save(update_fields=["is_published"])
        messages.success(request, "Задание скрыто от учеников.")
        return redirect("assignment_detail", pk)
    return _publish(request, assignment)


@teacher_required
@require_POST
def assignment_regrade(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    n = regrade_assignment(assignment)
    messages.success(request, f"Перепроверено работ: {n}. Оценки учителя, выставленные вручную, сохранены.")
    return redirect(request.POST.get("next") or "assignment_results", pk)


@teacher_required
@require_POST
def assignment_release(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    assignment.results_released = request.POST.get("action") != "hide"
    assignment.save(update_fields=["results_released"])
    messages.success(request, "Результаты открыты ученикам." if assignment.results_released
                     else "Результаты скрыты.")
    return redirect("assignment_results", pk)


@teacher_required
@require_POST
def assignment_copy(request, pk):
    src = get_object_or_404(Assignment, pk=pk)
    with transaction.atomic():
        groups = list(src.groups.all())
        items = list(src.items.prefetch_related("alternatives", "dismissed"))
        src.pk = None
        src.id = None
        src.title = f"{src.title} (копия)"
        src.is_published = False
        src.results_released = False
        src.checked_at = None
        src.created_by = request.user
        src.save()
        src.groups.set(groups)
        for it in items:
            alts, dis = list(it.alternatives.all()), list(it.dismissed.all())
            it.pk = None
            it.id = None
            it.assignment = src
            it.save()
            it.alternatives.set(alts)
            it.dismissed.set(dis)
    messages.success(request, "Создана копия задания.")
    return redirect("assignment_edit", src.pk)


@teacher_required
@require_POST
def assignment_delete(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    assignment.delete()
    messages.success(request, f"Задание «{assignment.title}» удалено.")
    return redirect("assignment_list")


@teacher_required
def assignment_preview(request, pk):
    from .views_student import build_items, water_mode
    assignment = get_object_or_404(Assignment, pk=pk)
    items = build_items(assignment, None)
    return render(request, "student/assignment_form.html", {
        "assignment": assignment, "items": items, "water_mode": water_mode(items), "preview": True})


@teacher_required
def assignment_results(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    items = list(assignment.items.select_related("reaction"))
    subs = {s.student_id: s for s in assignment.submissions.prefetch_related("answers")}
    rows = []
    for st in group_students(assignment):
        sub = subs.pop(st.user_id, None)
        rows.append({"student": st, "sub": sub, "cells": _cells(sub, items)})
    for sub in subs.values():  # ученики, переведённые в другой класс
        st = getattr(sub.student, "student", None)
        rows.append({"student": st, "sub": sub, "cells": _cells(sub, items), "other": True})

    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="results_{assignment.pk}.csv"'
        resp.write("﻿")
        w = csv.writer(resp, delimiter=";")
        w.writerow(["Класс", "Ученик", "Логин", "Статус"] + [f"№{i + 1}" for i in range(len(items))]
                   + ["Баллы", "Максимум", "%"])
        for r in rows:
            st, sub = r["student"], r["sub"]
            status = "не начинал" if not sub else ("сдано" if sub.is_submitted else "черновик")
            w.writerow([st.group.name if st else "", st.full_name if st else sub.student.username,
                        st.user.username if st else sub.student.username, status]
                       + [("" if c is None else str(c).replace(".", ",")) for c in
                          [cell["score"] for cell in r["cells"]]]
                       + [str(sub.score).replace(".", ",") if sub and sub.score is not None else "",
                          len(items), sub.percent if sub and sub.percent is not None else ""])
        return resp

    n_open_appeals = Appeal.objects.filter(answer__submission__assignment=assignment, status=Appeal.OPEN).count()
    return render(request, "teacher/assignment_results.html", {
        "assignment": assignment, "items": items, "rows": rows, "n_open_appeals": n_open_appeals})


def _cells(sub, items):
    if not sub or not sub.is_submitted:
        return [{"score": None, "verdict": ""} for _ in items]
    answers = {a.item_id: a for a in sub.answers.all()}
    out = []
    for it in items:
        a = answers.get(it.id)
        out.append({"score": a.score if a else None, "verdict": a.final_verdict if a else "",
                    "manual": a is not None and a.manual_score is not None})
    return out


# ------------------------------------------------------------------ работа ученика

@teacher_required
def submission_detail(request, pk):
    sub = get_object_or_404(Submission.objects.select_related("assignment", "student__student"), pk=pk)
    assignment = sub.assignment

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "score":
            ans = get_object_or_404(Answer, pk=request.POST.get("answer"), submission=sub)
            v = request.POST.get("manual_score", "")
            ans.manual_score = None if v == "" else float(v.replace(",", "."))
            ans.manual_comment = request.POST.get("manual_comment", "").strip()
            ans.save(update_fields=["manual_score", "manual_comment"])
            recompute_total(sub)
            messages.success(request, "Оценка сохранена.")
        elif action == "appeal":
            ap = get_object_or_404(Appeal, pk=request.POST.get("appeal"), answer__submission=sub)
            ap.response = request.POST.get("response", "").strip()
            ap.status = Appeal.ACCEPTED if request.POST.get("decision") == "accept" else Appeal.REJECTED
            ap.resolved_at = timezone.now()
            ap.save()
            if ap.status == Appeal.ACCEPTED and request.POST.get("score", "") != "":
                ap.answer.manual_score = float(request.POST["score"].replace(",", "."))
                if ap.response and not ap.answer.manual_comment:
                    ap.answer.manual_comment = ap.response
                ap.answer.save(update_fields=["manual_score", "manual_comment"])
                recompute_total(sub)
            messages.success(request, "Апелляция рассмотрена.")
        elif action == "add_alternative":
            ans = get_object_or_404(Answer.objects.select_related("item__reaction"), pk=request.POST.get("answer"),
                                    submission=sub)
            _add_answer_as_alternative(request, ans)
        elif action == "reset":
            sub.status = Submission.DRAFT
            sub.submitted_at = None
            sub.score = None
            sub.released = False
            sub.save()
            messages.success(request, "Работа возвращена: её можно исправить и сдать снова.")
            return redirect("assignment_results", assignment.pk)
        elif action == "release":
            sub.released = not sub.released
            sub.save(update_fields=["released"])
            messages.success(request, "Результат открыт ученику." if sub.released else "Результат скрыт.")
        elif action == "regrade":
            grade_submission(sub)
            messages.success(request, "Работа перепроверена.")
        return redirect("submission_detail", pk)

    items = list(_items_qs(assignment))
    answers = {a.item_id: a for a in sub.answers.select_related("matched_reaction").prefetch_related("appeals")}
    rows = []
    for n, item in enumerate(items, 1):
        a = answers.get(item.id)
        rows.append({
            "n": n, "item": item, "answer": a,
            "student_html": answer_html(a.data if a else {}, item.reaction),
            "preview": preview_html(item_view(item)),
            "alternatives": list(item.alternatives.all()),
            "appeals": list(a.appeals.all()) if a else [],
        })
    return render(request, "teacher/submission_detail.html", {
        "sub": sub, "assignment": assignment, "rows": rows,
        "student": getattr(sub.student, "student", None)})


def _add_answer_as_alternative(request, ans: Answer):
    """Ответ ученика -> новая (или существующая) реакция в базе -> допустимый вариант пункта -> перепроверка."""
    ref = ans.item.reaction
    sides = {}
    for side in ("L", "R"):
        coefs, problems = collect_side(ans.data.get(side))
        if problems:
            messages.error(request, "В ответе есть ошибки: " + "; ".join(problems))
            return
        sides[side] = [(c, f, "", "") for f, c in coefs.items()]
    text = equation_text(sides["L"], sides["R"], ref.above, ref.below, ref.reversible)
    try:
        eq = parse_equation(text)
    except EquationError as e:
        messages.error(request, f"Не удалось разобрать ответ ученика: {e}")
        return
    a = eq.analyze()
    if not a.balanced:
        messages.error(request, "Ответ ученика не уравнен — его нельзя добавить как правильный вариант.")
        return
    reaction = Reaction.objects.filter(signature=eq.signature()).first()
    if reaction is None:
        reaction = Reaction(comment=f"добавлено из ответа ученика ({ans.submission.assignment})")
        reaction.set_equation(eq, a.reduced)
        reaction.tags.set(ref.tags.all())
    if reaction.pk == ref.pk:
        messages.info(request, "Эта реакция уже является эталоном.")
        return
    ans.item.alternatives.add(reaction)
    ans.item.dismissed.remove(reaction)
    n = regrade_assignment(ans.submission.assignment)
    messages.success(request, f"Вариант «{reaction.text()}» добавлен как правильный; перепроверено работ: {n}.")


@teacher_required
def appeal_list(request):
    qs = Appeal.objects.select_related("answer__submission__assignment", "answer__submission__student__student",
                                       "answer__item__reaction")
    return render(request, "teacher/appeal_list.html", {
        "open": qs.filter(status=Appeal.OPEN).order_by("created_at"),
        "resolved": qs.exclude(status=Appeal.OPEN).order_by("-resolved_at")[:30],
    })
