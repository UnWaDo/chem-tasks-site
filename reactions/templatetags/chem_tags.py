from django import template
from django.utils.safestring import mark_safe

from chem.equation import term_html
from chem.formula import formula_html as _formula_html

register = template.Library()


@register.filter
def formula(text):
    return mark_safe(_formula_html(text or ""))


@register.simple_tag
def term(coef, formula, note="", mark="", show_coef=True):
    return mark_safe(term_html(coef, formula, note, mark, show_coef))


@register.filter
def get(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def score(v):
    """0.5 -> «0,5», 1.0 -> «1»."""
    if v is None:
        return "—"
    v = round(float(v), 2)
    return (str(int(v)) if v == int(v) else str(v)).replace(".", ",")


@register.filter
def attr(obj, name):
    return getattr(obj, name, None)


@register.filter
def tristate(v):
    """None/True/False -> ""/"1"/"0" для полей формы."""
    return "" if v is None else ("1" if v else "0")


@register.filter
def markup(text):
    """Подпись с разметкой индексов _(…) / ^(…) -> HTML."""
    from chem.equation import markup_html
    return mark_safe(markup_html(text or "", auto_sub=False))
