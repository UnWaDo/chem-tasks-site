from django.conf import settings
from django.db import models


class StudentGroup(models.Model):
    name = models.CharField("название", max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "класс"
        verbose_name_plural = "классы"

    def __str__(self):
        return self.name


class Student(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student")
    group = models.ForeignKey(StudentGroup, on_delete=models.CASCADE, related_name="students", verbose_name="класс")
    full_name = models.CharField("ФИО", max_length=200)

    class Meta:
        ordering = ["full_name"]
        verbose_name = "ученик"
        verbose_name_plural = "ученики"

    def __str__(self):
        return self.full_name
