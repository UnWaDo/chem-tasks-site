from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from accounts.views import teacher_required
from chem.equation import EquationError, equation_html, parse_equation, parse_lines

from .models import Reaction, Tag
from .tags import filter_reactions, find_tag, get_or_create_tags, split_tag_names, tags_from_post

EXAMPLE = """# строки с # — комментарии
2H2 + O2 = 2H2O
Al + O2 → Al2O3
KClO3 =^(t)_(MnO2) KCl + O2↑
Cu + HNO3(конц.) → Cu(NO3)2 + NO2↑ + H2O
Cu + HNO3(разб.) → Cu(NO3)2 + NO↑ + H2O
Fe3+ + 3OH- = Fe(OH)3↓"""


def decode_upload(f) -> str:
    raw = f.read()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def analyze_row(n, line, result, exclude_pk=None) -> dict:
    row = {"n": n, "line": line, "include": False, "choice": "asis", "options": [], "db_dups": []}
    if isinstance(result, Exception):
        row["error"] = str(result)
        return row
    eq = result
    a = eq.analyze()
    row.update(eq=eq, analysis=a, html=mark_safe(equation_html(eq)), sig=eq.signature())
    row["options"] = [{"value": f"opt{i}", "coefs": c, "html": mark_safe(equation_html(eq, c))}
                      for i, c in enumerate(a.options)]
    dups = Reaction.objects.filter(signature=row["sig"]).prefetch_related("components", "tags")
    if exclude_pk:
        dups = dups.exclude(pk=exclude_pk)
    row["db_dups"] = list(dups[:5])
    if a.ok or not a.options:
        row["choice"] = "asis"
    else:
        row["choice"] = "opt0"
    # несколько независимых решений: учитель должен выбрать вариант сам
    row["include"] = not row["db_dups"] and not a.impossible and not (a.ambiguous and not a.balanced)
    return row


def chosen_coefs(row, choice):
    if choice.startswith("opt"):
        try:
            return row["options"][int(choice[3:])]["coefs"]
        except (ValueError, IndexError):
            return None
    return None


def _selected_tags_context(data=None, selected=()):
    """Контекст для выбора тэгов: все тэги, отмеченные id и введённые новые тэги."""
    if data is not None:
        selected = {int(i) for i in data.getlist("tags") if str(i).isdigit()}
    return {"all_tags": Tag.objects.all(), "selected_tags": set(selected),
            "new_tags": data.get("new_tags", "") if data is not None else ""}


@teacher_required
def reaction_list(request):
    if request.method == "POST":
        ids = request.POST.getlist("ids")
        action = request.POST.get("action")
        qs = Reaction.objects.filter(pk__in=ids)
        names = split_tag_names(request.POST.get("tag_name", ""))
        if action in ("add_tag", "remove_tag") and not (ids and names):
            messages.error(request, "Отметьте реакции и укажите тэг.")
        elif action == "add_tag":
            tags = get_or_create_tags(names)
            for r in qs:
                r.tags.add(*tags)
            messages.success(request, f"Тэги «{', '.join(t.name for t in tags)}» добавлены к реакциям: {qs.count()}.")
        elif action == "remove_tag":
            tags = [t for t in Tag.objects.all() if t.name.lower() in {n.lower() for n in names}]
            for r in qs:
                r.tags.remove(*tags)
            messages.success(request, f"Тэги убраны у реакций: {qs.count()}.")
        elif action == "delete":
            used = set(qs.filter(assignment_items__isnull=False).values_list("pk", flat=True))
            deletable = qs.exclude(pk__in=used)
            n = deletable.count()
            deletable.delete()
            messages.success(request, f"Удалено реакций: {n}.")
            if used:
                messages.warning(request, f"Не удалено реакций: {len(used)} — они используются в заданиях.")
        return redirect(request.get_full_path())

    q = request.GET.get("q", "").strip()
    tag = request.GET.get("tag", "")
    qs = filter_reactions(Reaction.objects.prefetch_related("components", "tags"), q, tag)
    qs = qs.annotate(n_used=Count("assignment_items", distinct=True)).order_by("-id")
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "teacher/reaction_list.html", {
        "page": page, "q": q, "tag": tag, "all_tags": Tag.objects.all(), "total": qs.count()})


@teacher_required
def reaction_import(request):
    if request.method != "POST":
        return render(request, "teacher/reaction_import.html", {"example": EXAMPLE, **_selected_tags_context()})

    text = request.POST.get("text", "")
    if request.FILES.get("file"):
        text = decode_upload(request.FILES["file"])
    step = request.POST.get("step", "preview")

    rows = []
    seen = {}
    for n, line, res in parse_lines(text):
        row = analyze_row(n, line, res)
        if "sig" in row:
            if row["sig"] in seen:
                row["batch_dup"] = seen[row["sig"]]
                row["include"] = False
            else:
                seen[row["sig"]] = n
        rows.append(row)

    if step == "save":
        tags = tags_from_post(request.POST)
        created = skipped = 0
        for row in rows:
            if "eq" not in row or not request.POST.get(f"include_{row['n']}"):
                skipped += 1
                continue
            coefs = chosen_coefs(row, request.POST.get(f"choice_{row['n']}", row["choice"]))
            r = Reaction().set_equation(row["eq"], coefs)
            r.tags.add(*tags)
            created += 1
        messages.success(request, f"Добавлено реакций: {created}. Пропущено строк: {skipped}.")
        return redirect("reaction_list")

    tag_ctx = _selected_tags_context(request.POST)
    if not rows:
        messages.error(request, "Не найдено ни одной строки с реакцией.")
        return render(request, "teacher/reaction_import.html", {"example": EXAMPLE, "text": text, **tag_ctx})
    stats = {
        "total": len(rows),
        "errors": sum(1 for r in rows if "error" in r),
        "dups": sum(1 for r in rows if r["db_dups"] or r.get("batch_dup")),
        "attention": sum(1 for r in rows if "analysis" in r and not r["analysis"].ok),
    }
    tag_names = [t.name for t in tag_ctx["all_tags"] if t.pk in tag_ctx["selected_tags"]]
    tag_names += split_tag_names(tag_ctx["new_tags"])
    return render(request, "teacher/reaction_preview.html", {
        "rows": rows, "text": text, "stats": stats, "tag_names": tag_names, **tag_ctx})


class ReactionForm(forms.Form):
    text = forms.CharField(label="Уравнение", widget=forms.TextInput(attrs={"class": "mono wide", "id": "eq-text"}))
    comment = forms.CharField(label="Комментарий (виден только учителю)", required=False,
                              widget=forms.Textarea(attrs={"rows": 2}))


@teacher_required
def reaction_edit(request, pk=None):
    reaction = get_object_or_404(Reaction.objects.prefetch_related("components", "tags"), pk=pk) if pk else None
    initial = {"text": reaction.text(), "comment": reaction.comment} if reaction else {}
    form = ReactionForm(request.POST or None, initial=initial)
    row = None
    if request.method == "POST":
        tag_ctx = _selected_tags_context(request.POST)
    else:
        tag_ctx = _selected_tags_context(selected=[t.pk for t in reaction.tags.all()] if reaction else ())
    if request.method == "POST" and form.is_valid():
        text = form.cleaned_data["text"]
        try:
            res = parse_equation(text)
        except EquationError as e:
            res = e
        row = analyze_row(1, text, res, exclude_pk=reaction.pk if reaction else None)
        confirmed = request.POST.get("confirm") == "1" and request.POST.get("checked_text") == text
        if "eq" in row and ((row["analysis"].ok and not row["db_dups"]) or confirmed):
            obj = reaction or Reaction()
            obj.comment = form.cleaned_data["comment"]
            obj.set_equation(row["eq"], chosen_coefs(row, request.POST.get("choice_1", row["choice"])))
            obj.tags.set(tags_from_post(request.POST))
            messages.success(request, "Реакция сохранена.")
            if reaction:
                used = obj.assignment_items.filter(assignment__submissions__status="submitted").exists()
                if used:
                    messages.warning(request, "Реакция используется в заданиях со сданными работами — "
                                              "не забудьте нажать «Перепроверить работы» в этих заданиях.")
            return redirect(request.GET.get("next") or "reaction_list")
    usage = reaction.assignment_items.select_related("assignment") if reaction else []
    return render(request, "teacher/reaction_edit.html", {
        "form": form, "reaction": reaction, "row": row, "usage": usage, "example": EXAMPLE, **tag_ctx})


@teacher_required
@require_POST
def reaction_delete(request, pk):
    reaction = get_object_or_404(Reaction, pk=pk)
    try:
        reaction.delete()
        messages.success(request, "Реакция удалена.")
    except ProtectedError:
        messages.error(request, "Реакция используется в заданиях — сначала уберите её оттуда.")
    return redirect("reaction_list")


@teacher_required
def tag_list(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            tags = get_or_create_tags(split_tag_names(request.POST.get("names", "")))
            if tags:
                messages.success(request, f"Тэгов добавлено: {len(tags)}.")
            else:
                messages.error(request, "Введите название тэга.")
        else:
            tag = get_object_or_404(Tag, pk=request.POST.get("tag"))
            if action == "rename":
                name = " ".join(request.POST.get("name", "").split())[:60]
                other = find_tag(name, exclude_pk=tag.pk)
                if not name:
                    messages.error(request, "Название не может быть пустым.")
                elif other:
                    # такое название уже есть — объединяем тэги
                    for r in tag.reactions.all():
                        r.tags.add(other)
                    tag.delete()
                    messages.success(request, f"Тэг объединён с «{other.name}».")
                else:
                    tag.name = name
                    tag.save()
                    messages.success(request, "Тэг переименован.")
            elif action == "delete":
                tag.delete()
                messages.success(request, f"Тэг «{tag.name}» удалён (реакции остались в базе).")
        return redirect("tag_list")
    tags = Tag.objects.annotate(n=Count("reactions"))
    return render(request, "teacher/tag_list.html", {"tags": tags})


@teacher_required
def reaction_live_preview(request):
    """Фрагмент HTML с разбором уравнения — для предпросмотра при вводе."""
    text = request.GET.get("text", "")[:500]
    try:
        res = parse_equation(text)
    except EquationError as e:
        res = e
    exclude = request.GET.get("exclude", "")
    row = analyze_row(1, text, res, exclude_pk=int(exclude) if exclude.isdigit() else None)
    return render(request, "teacher/_live_preview.html", {"row": row})
