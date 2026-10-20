from django.contrib import admin

from .models import Component, Reaction, Tag


class ComponentInline(admin.TabularInline):
    model = Component
    extra = 0


@admin.register(Reaction)
class ReactionAdmin(admin.ModelAdmin):
    list_display = ["id", "__str__"]
    list_filter = ["tags"]
    filter_horizontal = ["tags"]
    inlines = [ComponentInline]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    search_fields = ["name"]
