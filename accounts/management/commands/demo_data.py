"""Демо-данные для локальной проверки: python manage.py demo_data

Создаёт учителя (логин teacher, пароль demo-teacher-2026), класс «Демо» с двумя учениками
(логины demo.a / demo.b, пароль demo-student-2026), несколько реакций и задание.
Только для разработки — на сервере не запускайте.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from accounts.models import Student, StudentGroup
from assignments.models import Assignment, AssignmentItem
from chem.equation import parse_lines
from reactions.models import Reaction, Tag

TEACHER_PASSWORD = "demo-teacher-2026"
STUDENT_PASSWORD = "demo-student-2026"

REACTIONS = """2H2 + O2 = 2H2O
4Al + 3O2 =(t) 2Al2O3
2KClO3 =^(t)_(MnO2) 2KCl + 3O2↑
Cu + 4HNO3(конц.) → Cu(NO3)2 + 2NO2↑ + 2H2O
3Cu + 8HNO3(разб.) → 3Cu(NO3)2 + 2NO↑ + 4H2O
NaOH + HCl = NaCl + H2O
BaCl2 + H2SO4 = BaSO4↓ + 2HCl
Fe3+ + 3OH- = Fe(OH)3↓
CuSO4·5H2O =(t) CuSO4 + 5H2O"""


class Command(BaseCommand):
    help = "Создать демо-данные для локальной проверки"

    def handle(self, *args, **opts):
        t, _ = User.objects.get_or_create(username="teacher", defaults={"is_staff": True, "is_superuser": True,
                                                                         "first_name": "Учитель"})
        t.set_password(TEACHER_PASSWORD)
        t.save()
        group, _ = StudentGroup.objects.get_or_create(name="Демо")
        for login, name in [("demo.a", "Алексеев Алексей"), ("demo.b", "Борисова Анна")]:
            u, created = User.objects.get_or_create(username=login)
            u.set_password(STUDENT_PASSWORD)
            u.save()
            Student.objects.get_or_create(user=u, defaults={"group": group, "full_name": name})
        tag, _ = Tag.objects.get_or_create(name="Демо")
        for _, _, eq in parse_lines(REACTIONS):
            if not Reaction.objects.filter(signature=eq.signature()).exists():
                Reaction().set_equation(eq).tags.add(tag)
        a, created = Assignment.objects.get_or_create(
            title="Демо: допишите продукты",
            defaults={"is_published": True, "show_reactants": True, "show_products": False, "hide_water": True,
                      "description": "Допишите продукты реакций и расставьте коэффициенты."})
        if created:
            a.groups.add(group)
            for i, r in enumerate(tag.reactions.order_by("id")):
                AssignmentItem.objects.create(assignment=a, reaction=r, position=i)
        self.stdout.write(self.style.SUCCESS("Демо-данные созданы (логины и пароли — в начале файла команды)."))
