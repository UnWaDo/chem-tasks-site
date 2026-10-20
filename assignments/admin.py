from django.contrib import admin

from .models import Answer, Appeal, Assignment, AssignmentItem, Submission


class ItemInline(admin.TabularInline):
    model = AssignmentItem
    extra = 0
    raw_id_fields = ["reaction"]
    filter_horizontal = ["alternatives", "dismissed"]


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ["title", "is_published", "due_at", "results_mode"]
    inlines = [ItemInline]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["assignment", "student", "status", "score", "submitted_at"]
    list_filter = ["assignment", "status"]


admin.site.register(Answer)
admin.site.register(Appeal)
