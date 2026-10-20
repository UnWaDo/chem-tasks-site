"""Логика заданий: что видит ученик, проверка работ, поиск неоднозначностей."""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from chem.equation import normalize_conditions, normalize_note
from chem.grading import grade
from reactions.models import Component, Reaction

from .models import Answer, Assignment, AssignmentItem, Submission

WATER = "H2O"


@dataclass
class Slot:
    key: str
    side: str
    formula: str
    note: str
    mark: str
    coef: int
    visible: bool
    source: str           # "override" — задано вручную, "water" — спрятана вода, "auto" — по настройке стороны
    component: Component | None = None
    auto_visible: bool = True   # видимость без ручной настройки вещества

    @property
    def hidden_by_water(self):
        return not self.visible and self.source == "water"


@dataclass
class ItemView:
    item: AssignmentItem
    left: list[Slot] = field(default_factory=list)
    right: list[Slot] = field(default_factory=list)
    show_count: bool = False
    hide_water: bool = False
    show_reactants: bool = True
    show_products: bool = False

    @property
    def reaction(self):
        return self.item.reaction

    def side(self, side):
        return self.left if side == "L" else self.right

    def visible(self, side):
        return [s for s in self.side(side) if s.visible]

    def hidden_count(self, side):
        """Сколько скрыто веществ (без воды, спрятанной опцией «прятать воду»)."""
        return sum(1 for s in self.side(side) if not s.visible and not s.hidden_by_water)

    def fully_visible(self, side):
        return self.hidden_count(side) == 0


def item_view(item: AssignmentItem) -> ItemView:
    v = ItemView(
        item=item,
        show_count=item.effective("show_count"),
        hide_water=item.effective("hide_water"),
        show_reactants=item.effective("show_reactants"),
        show_products=item.effective("show_products"),
    )
    overrides = item.overrides or {}
    for c in item.reaction.components.all():
        if v.hide_water and c.is_water:
            auto, source = False, "water"
        else:
            auto, source = (v.show_reactants if c.side == "L" else v.show_products), "auto"
        visible = auto
        if c.key in overrides:
            visible, source = bool(overrides[c.key]), "override"
        slot = Slot(c.key, c.side, c.formula, c.note, c.mark, c.coef, visible, source, c, auto)
        v.side(c.side).append(slot)
    return v


# ------------------------------------------------------------------ форма ученика

def answer_form(view: ItemView, data: dict | None) -> dict:
    """Строки формы ответа для каждой стороны.

    Строка: {"t": fixed|slot|extra, "f": формула, "c": коэффициент, "note": ..., "mark": ...}
    """
    data = data or {}
    result = {}
    for side in ("L", "R"):
        saved = data.get(side) or []
        saved_fixed = {r.get("f"): r.get("c", "") for r in saved if r.get("t") == "fixed"}
        saved_free = [r for r in saved if r.get("t") in ("slot", "extra") or not r.get("t")]
        rows = []
        for s in view.visible(side):
            rows.append({"t": "fixed", "f": s.formula, "c": saved_fixed.get(s.formula, ""),
                         "note": s.note, "mark": s.mark})
        n_slots = view.hidden_count(side) if view.show_count else 0
        for i in range(n_slots):
            r = saved_free.pop(0) if saved_free else {}
            rows.append({"t": "slot", "f": r.get("f", ""), "c": r.get("c", "")})
        for r in saved_free:
            if r.get("f") or r.get("c"):
                rows.append({"t": "extra", "f": r.get("f", ""), "c": r.get("c", "")})
        if not view.show_count and not rows:
            rows.append({"t": "extra", "f": "", "c": ""})
        result[side] = {
            "rows": rows,
            "can_add": (not view.show_count) or view.hide_water,
        }
    return result


def clean_answer(raw_rows: dict) -> dict:
    """Нормализует присланный ответ: обрезает строки и ограничивает размер."""
    out = {}
    for side in ("L", "R"):
        rows = []
        for r in (raw_rows.get(side) or [])[:20]:
            t = r.get("t") if r.get("t") in ("fixed", "slot", "extra") else "extra"
            rows.append({"t": t, "f": str(r.get("f", ""))[:60].strip(), "c": str(r.get("c", ""))[:4].strip()})
        out[side] = rows
    return out


# ------------------------------------------------------------------ проверка

def _items_qs(assignment):
    comps = Prefetch("components", queryset=Component.objects.order_by("side", "position"))
    return (assignment.items.select_related("reaction", "assignment")
            .prefetch_related(Prefetch("reaction__components", queryset=Component.objects.all()),
                              Prefetch("alternatives", queryset=Reaction.objects.prefetch_related(comps))))


def grade_answer(answer: Answer, item: AssignmentItem) -> None:
    refs = [item.reaction] + list(item.alternatives.all())
    partial = 0.5 if item.assignment.partial_credit else 0.0
    res = grade(answer.data or {}, [r.reference() for r in refs], partial=partial)
    answer.auto_score = res.score
    answer.verdict = res.verdict
    answer.feedback = res.feedback
    answer.matched_reaction = refs[res.ref_index] if res.verdict != "empty" else None


@transaction.atomic
def grade_submission(sub: Submission, items=None) -> Submission:
    items = items if items is not None else list(_items_qs(sub.assignment))
    answers = {a.item_id: a for a in sub.answers.all()}
    total = 0.0
    for item in items:
        ans = answers.get(item.id) or Answer(submission=sub, item=item, data={})
        grade_answer(ans, item)
        ans.save()
        total += ans.score
    sub.score = total
    sub.max_score = len(items)
    sub.graded_at = timezone.now()
    sub.save(update_fields=["score", "max_score", "graded_at"])
    return sub


def regrade_assignment(assignment: Assignment) -> int:
    items = list(_items_qs(assignment))
    subs = assignment.submissions.filter(status=Submission.SUBMITTED).prefetch_related("answers")
    n = 0
    for sub in subs:
        grade_submission(sub, items)
        n += 1
    return n


# ------------------------------------------------------------------ неоднозначности

def _pairs(components, drop_water=False):
    return [(c.formula, normalize_note(c.note)) for c in components if not (drop_water and c.formula == WATER)]


def _contains(candidates, needed) -> bool:
    """Все видимые вещества есть среди веществ другой реакции (пояснение совпадает или не указано)."""
    pool = list(candidates)
    for f, n in needed:
        hit = next((p for p in pool if p[0] == f and (p[1] == n or not p[1] or not n)), None)
        if hit is None:
            return False
        pool.remove(hit)
    return True


def find_ambiguities(item: AssignmentItem, reactions=None) -> list[Reaction]:
    """Реакции из базы, которые подходят под то, что видит ученик в этом пункте задания."""
    view = item_view(item)
    cond = (normalize_conditions(item.reaction.above), normalize_conditions(item.reaction.below),
            item.reaction.reversible)
    if reactions is None:
        reactions = Reaction.objects.exclude(pk=item.reaction_id).prefetch_related("components")
    found = []
    for r in reactions:
        if r.pk == item.reaction_id:
            continue
        if (normalize_conditions(r.above), normalize_conditions(r.below), r.reversible) != cond:
            continue
        ok = True
        for side in ("L", "R"):
            vis = [(s.formula, normalize_note(s.note)) for s in view.visible(side)]
            shown_water = any(f == WATER for f, _ in vis)
            other = _pairs(r.side(side), drop_water=view.hide_water and not shown_water)
            if not _contains(other, vis):
                ok = False
                break
            extra = len(other) - len(vis)
            if view.fully_visible(side) and extra != 0:
                ok = False
                break
            if view.show_count and extra != view.hidden_count(side):
                ok = False
                break
        if ok:
            found.append(r)
    return found


def assignment_ambiguities(assignment: Assignment) -> list[dict]:
    """Для каждого пункта: найденные реакции, ещё не подтверждённые и не отклонённые учителем."""
    reactions = list(Reaction.objects.prefetch_related("components"))
    out = []
    for item in _items_qs(assignment).prefetch_related("dismissed"):
        found = find_ambiguities(item, reactions)
        accepted = {r.pk for r in item.alternatives.all()}
        dismissed = {r.pk for r in item.dismissed.all()}
        pending = [r for r in found if r.pk not in accepted and r.pk not in dismissed]
        out.append({"item": item, "view": item_view(item), "found": found, "pending": pending,
                    "accepted": accepted, "dismissed": dismissed})
    return out
