import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .logic import _items_qs, answer_form, clean_answer, grade_submission, item_view
from .models import Answer, Appeal, Assignment, Submission
from .render import answer_html

_FIELD = re.compile(r"^a_(\d+)_([LR])_(\d+)_([fct])$")


def _student(request):
    st = getattr(request.user, "student", None)
    if st is None:
        raise Http404("Страница доступна только ученикам")
    return st


def build_items(assignment, submission):
    saved = {a.item_id: a.data for a in submission.answers.all()} if submission else {}
    out = []
    for n, item in enumerate(_items_qs(assignment), 1):
        view = item_view(item)
        out.append({"n": n, "item": item, "view": view, "form": answer_form(view, saved.get(item.id))})
    return out


def water_mode(items) -> str:
    """Общее уведомление о спрятанной воде: "all" — во всех уравнениях, "some" — в части, "" — нигде."""
    flags = [it["view"].hide_water for it in items]
    if flags and all(flags):
        return "all"
    return "some" if any(flags) else ""


def _parse_post(post) -> dict[int, dict]:
    raw: dict[int, dict] = {}
    for key, value in post.items():
        m = _FIELD.match(key)
        if not m:
            continue
        item_id, side, idx, part = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        raw.setdefault(item_id, {}).setdefault(side, {}).setdefault(idx, {})[part] = value
    out = {}
    for item_id, sides in raw.items():
        out[item_id] = clean_answer({side: [rows[i] for i in sorted(rows)] for side, rows in sides.items()})
    return out


@login_required
def student_home(request):
    if request.user.is_staff and not hasattr(request.user, "student"):
        return redirect("teacher_dashboard")
    st = _student(request)
    now = timezone.now()
    subs = {s.assignment_id: s for s in request.user.submissions.select_related("assignment")}
    rows = []
    for a in Assignment.objects.filter(groups=st.group, is_published=True).distinct().order_by("due_at", "-created_at"):
        sub = subs.get(a.pk)
        rows.append({"a": a, "sub": sub, "open": a.is_open(now), "accepts": a.accepts_submissions(now),
                     "visible": sub.results_visible(now) if sub else False})
    todo = [r for r in rows if not (r["sub"] and r["sub"].is_submitted)]
    done = [r for r in rows if r["sub"] and r["sub"].is_submitted]
    return render(request, "student/home.html", {"student": st, "todo": todo, "done": done})


def _get_assignment(request, pk):
    st = _student(request)
    a = get_object_or_404(Assignment, pk=pk, is_published=True, groups=st.group)
    if not a.is_open():
        raise Http404("Задание ещё не открыто")
    return a


@login_required
def assignment_view(request, pk):
    assignment = _get_assignment(request, pk)
    sub = Submission.objects.filter(assignment=assignment, student=request.user).first()

    if sub and sub.is_submitted:
        return _result_page(request, assignment, sub)

    if request.method == "POST":
        if not assignment.accepts_submissions():
            messages.error(request, "Срок сдачи истёк — работа не принимается.")
            return redirect("student_assignment", pk)
        answers = _parse_post(request.POST)
        with transaction.atomic():
            if sub is None:
                sub, _ = Submission.objects.get_or_create(assignment=assignment, student=request.user)
            item_ids = set(assignment.items.values_list("id", flat=True))
            for item_id, data in answers.items():
                if item_id in item_ids:
                    Answer.objects.update_or_create(submission=sub, item_id=item_id, defaults={"data": data})
            if request.POST.get("action") == "submit":
                sub.status = Submission.SUBMITTED
                sub.submitted_at = timezone.now()
                sub.save(update_fields=["status", "submitted_at"])
                grade_submission(sub)
                messages.success(request, "Работа сдана.")
            else:
                messages.success(request, "Черновик сохранён.")
        return redirect("student_assignment", pk)

    items = build_items(assignment, sub)
    return render(request, "student/assignment_form.html", {
        "assignment": assignment, "sub": sub, "items": items, "water_mode": water_mode(items),
        "accepts": assignment.accepts_submissions(), "late": assignment.is_late()})


def _result_page(request, assignment, sub):
    visible = sub.results_visible()
    rows = []
    if visible:
        answers = {a.item_id: a for a in sub.answers.prefetch_related("appeals")}
        for n, item in enumerate(_items_qs(assignment), 1):
            a = answers.get(item.id)
            rows.append({
                "n": n, "item": item, "answer": a,
                "student_html": answer_html(a.data if a else {}, item.reaction),
                "appeals": list(a.appeals.all()) if a else [],
                "can_appeal": bool(a and assignment.allow_appeals
                                   and not any(ap.status == Appeal.OPEN for ap in a.appeals.all())),
            })
    return render(request, "student/assignment_result.html", {
        "assignment": assignment, "sub": sub, "visible": visible, "rows": rows})


@login_required
@require_POST
def appeal_create(request, pk):
    assignment = _get_assignment(request, pk)
    sub = get_object_or_404(Submission, assignment=assignment, student=request.user, status=Submission.SUBMITTED)
    answer = get_object_or_404(Answer, pk=request.POST.get("answer"), submission=sub)
    text = request.POST.get("text", "").strip()
    if not (assignment.allow_appeals and sub.results_visible()):
        messages.error(request, "Апелляции по этому заданию не принимаются.")
    elif answer.appeals.filter(status=Appeal.OPEN).exists():
        messages.error(request, "По этой реакции уже есть апелляция на рассмотрении.")
    elif not text:
        messages.error(request, "Опишите, почему вы не согласны с оценкой.")
    else:
        Appeal.objects.create(answer=answer, text=text[:2000])
        messages.success(request, "Апелляция отправлена учителю.")
    return redirect("student_assignment", pk)
