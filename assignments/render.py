"""HTML-представления пунктов задания и ответов."""
from django.utils.safestring import mark_safe

from chem.equation import term_html
from chem.formula import normalize_formula


def preview_html(view) -> str:
    """Как пункт задания выглядит для ученика (видимые вещества и «пустые места»)."""
    def side(s):
        parts = []
        for slot in view.side(s):
            if slot.visible:
                parts.append(f'<span class="term">{term_html(None, slot.formula, slot.note, slot.mark)}</span>')
            elif view.show_count and not slot.hidden_by_water:
                parts.append('<span class="term blank">?</span>')
        if not view.show_count and view.hidden_count(s):
            parts.append('<span class="term blank">…</span>')
        return '<span class="plus"> + </span>'.join(parts) or '<span class="term blank">…</span>'
    # data-pv-* — точки, которые обновляет builder.js при переключении веществ без сохранения
    water = f'<span class="hint" data-pv-water{"" if view.hide_water else " hidden"}>вода скрыта</span>'
    return mark_safe(f'<span class="eq"><span data-pv="L">{side("L")}</span>{view.reaction.arrow_html()}'
                     f'<span data-pv="R">{side("R")}</span></span>{water}')


def answer_html(data, reaction) -> str:
    def side(rows):
        terms = []
        for r in rows or []:
            if not (r.get("f") or "").strip():
                continue
            c = (r.get("c") or "").strip()
            terms.append(f'<span class="term">{term_html(c or None, normalize_formula(r["f"]))}</span>')
        return '<span class="plus"> + </span>'.join(terms) or '<span class="term blank">—</span>'
    data = data or {}
    return mark_safe(f'<span class="eq">{side(data.get("L"))}{reaction.arrow_html()}{side(data.get("R"))}</span>')
