"""Работа с тэгами реакций: разбор ввода, создание новых, фильтрация."""
import re

from django.db.models import Q

from .models import Tag


def split_tag_names(text: str) -> list[str]:
    """«Окисление, 9 класс; ОВР» -> ["Окисление", "9 класс", "ОВР"] (без повторов, без учёта регистра)."""
    out, seen = [], set()
    for part in re.split(r"[,;\n]", text or ""):
        name = " ".join(part.split())[:60]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def find_tag(name: str, exclude_pk=None):
    """Тэг с таким названием без учёта регистра (для кириллицы нужна база с локалью ICU, см. README)."""
    return Tag.objects.filter(name__iexact=name).exclude(pk=exclude_pk).first()


def get_or_create_tags(names) -> list[Tag]:
    tags = []
    for name in names:
        tags.append(find_tag(name) or Tag.objects.create(name=name))
    return tags


def tags_from_post(data, field="tags", new_field="new_tags") -> list[Tag]:
    """Отмеченные существующие тэги + новые тэги, введённые через запятую."""
    ids = [i for i in data.getlist(field) if str(i).isdigit()]
    tags = list(Tag.objects.filter(pk__in=ids))
    known = {t.name.lower() for t in tags}
    tags += [t for t in get_or_create_tags(split_tag_names(data.get(new_field, ""))) if t.name.lower() not in known]
    return tags


def filter_reactions(qs, q: str = "", tag: str = ""):
    """Фильтр списка реакций по строке поиска и тэгу ("-" — реакции без тэгов)."""
    if q:
        qs = qs.filter(Q(components__formula__icontains=q) | Q(tags__name__icontains=q)
                       | Q(comment__icontains=q)).distinct()
    if tag == "-":
        qs = qs.filter(tags__isnull=True)
    elif tag.isdigit():
        qs = qs.filter(tags__pk=tag)
    return qs
