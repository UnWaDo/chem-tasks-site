from django.contrib import admin

from .models import Student, StudentGroup


@admin.register(StudentGroup)
class StudentGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "created_at"]


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ["full_name", "group", "user"]
    list_filter = ["group"]
    search_fields = ["full_name", "user__username"]
