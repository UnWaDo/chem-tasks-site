"""Разбор строки уравнения реакции.

Формат строки:
    [коэф]вещество[(пояснение)] + ... <стрелка>[условия] [коэф]вещество + ...

Стрелка: =, →, ->, ⟶ (обратимые: ⇄, ⇌, <=>).
Условия идут сразу после стрелки в скобках: (t) или ^(t) — над стрелкой,
_(cat) — под стрелкой. Пример: 2KClO3 =^(t°)_(MnO2) 2KCl + 3O2↑
Пояснения к веществу — скобки после формулы: HNO3(конц.), H2O(г), Fe(OH)3(тв).
Строки, начинающиеся с #, считаются комментариями.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .balance import balance_options, imbalance, reduce_coefs
from .formula import Formula, FormulaError, formula_html, parse_formula


class EquationError(ValueError):
    pass


ARROWS = [  # (запись, обратимая)
    ("<=>", True), ("<->", True), ("⇌", True), ("⇄", True),
    ("-->", False), ("->", False), ("⟶", False), ("→", False), ("=", False),
]
_OPEN, _CLOSE = "([{", ")]}"
MARKS = "↑↓"


@dataclass
class Term:
    coef: int | None
    formula: Formula
    note: str = ""
    mark: str = ""

    def key(self) -> str:
        return self.formula.text + "|" + normalize_note(self.note)


@dataclass
class Equation:
    left: list[Term]
    right: list[Term]
    above: str = ""
    below: str = ""
    reversible: bool = False
    raw: str = ""

    @property
    def terms(self) -> list[Term]:
        return self.left + self.right

    @property
    def has_coefficients(self) -> bool:
        return any(t.coef is not None for t in self.terms)

    @property
    def coefficients(self) -> list[int]:
        return [t.coef if t.coef is not None else 1 for t in self.terms]

    def with_coefficients(self, coefs: list[int]) -> "Equation":
        terms = [Term(c, t.formula, t.note, t.mark) for c, t in zip(coefs, self.terms)]
        n = len(self.left)
        return Equation(terms[:n], terms[n:], self.above, self.below, self.reversible, self.raw)

    def signature(self) -> str:
        return reaction_signature(
            [t.key() for t in self.left], [t.key() for t in self.right],
            self.above, self.below, self.reversible)

    def to_text(self) -> str:
        return equation_text(
            [(t.coef, t.formula.text, t.note, t.mark) for t in self.left],
            [(t.coef, t.formula.text, t.note, t.mark) for t in self.right],
            self.above, self.below, self.reversible)

    def analyze(self) -> "Analysis":
        lf = [t.formula for t in self.left]
        rf = [t.formula for t in self.right]
        coefs = self.coefficients
        diff = imbalance(lf, rf, coefs)
        balanced = not diff
        options, dim = balance_options(lf, rf)
        reduced = reduce_coefs(coefs)
        if balanced:
            options = [] if reduced == coefs else [reduced]
        return Analysis(
            balanced=balanced,
            had_coefficients=self.has_coefficients,
            reducible=balanced and reduced != coefs,
            reduced=reduced,
            imbalance=diff,
            options=options,
            dim=dim,
        )


@dataclass
class Analysis:
    balanced: bool
    had_coefficients: bool
    reducible: bool
    reduced: list[int]
    imbalance: dict = field(default_factory=dict)
    options: list[list[int]] = field(default_factory=list)
    dim: int = 1

    @property
    def ambiguous(self) -> bool:
        return self.dim > 1

    @property
    def impossible(self) -> bool:
        return not self.balanced and not self.options

    @property
    def ok(self) -> bool:
        return self.balanced and not self.reducible


# ---------------------------------------------------------------- нормализация

def normalize_note(note: str) -> str:
    return re.sub(r"[\s.]+", "", note.lower())


# Градус: ^\circ, ^(\circ), ^o, ^(o) (латинская или кириллическая «о»), \circ -> настоящий знак «°»
_DEGREE_RE = re.compile(r"\^\s*(?:\(\s*(?:\\circ|[oо°])\s*\)|\\circ|[oо°](?![a-zа-яё0-9]))|\\circ")


def canonical_degrees(text: str) -> str:
    """t^o, t^(o), t^\\circ -> t° (градус — отдельный символ, а не надстрочная буква «o»)."""
    return _DEGREE_RE.sub("°", text)


def normalize_conditions(text: str) -> str:
    parts = [normalize_note(p) for p in re.split(r"[,;]", canonical_degrees(text))]
    return ",".join(sorted(p for p in parts if p))


def reaction_signature(left_keys, right_keys, above="", below="", reversible=False) -> str:
    """Ключ для поиска дубликатов: порядок веществ не важен, пояснения и условия важны."""
    return "{}={}{}|^{}|_{}".format(
        "+".join(sorted(left_keys)), "+".join(sorted(right_keys)),
        "~" if reversible else "", normalize_conditions(above), normalize_conditions(below))


def equation_text(left, right, above="", below="", reversible=False) -> str:
    """Собирает строку уравнения из кортежей (коэф, формула, пояснение, знак)."""
    def side(items):
        out = []
        for coef, formula, note, mark in items:
            s = ("" if coef in (None, 1) else str(coef)) + formula + (mark or "")
            if note:
                s += f"({note})"
            out.append(s)
        return " + ".join(out)

    arrow = "⇄" if reversible else "→"
    if above:
        arrow += f"^({above})"
    if below:
        arrow += f"_({below})"
    return f"{side(left)} {arrow} {side(right)}"


# ---------------------------------------------------------------- разбор

def _find_arrow(line: str) -> tuple[int, str, bool]:
    depth = 0
    found = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
        elif depth == 0:
            for sym, rev in ARROWS:
                if line.startswith(sym, i):
                    found.append((i, sym, rev))
                    i += len(sym) - 1
                    break
        i += 1
    if not found:
        raise EquationError("не найдена стрелка (= или →)")
    if len(found) > 1:
        raise EquationError("в строке больше одной стрелки")
    return found[0]


def _match_close(s: str, i: int) -> int:
    """Индекс закрывающей скобки для открывающей s[i]."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] in _OPEN:
            depth += 1
        elif s[j] in _CLOSE:
            depth -= 1
            if depth == 0:
                return j
    raise EquationError("не закрыта скобка")


def _match_open(s: str, j: int) -> int:
    depth = 0
    for i in range(j, -1, -1):
        if s[i] in _CLOSE:
            depth += 1
        elif s[i] in _OPEN:
            depth -= 1
            if depth == 0:
                return i
    raise EquationError("лишняя закрывающая скобка")


def _parse_conditions(rest: str) -> tuple[list[str], list[str], str]:
    above, below = [], []
    i = 0
    while True:
        while i < len(rest) and rest[i].isspace():
            i += 1
        if i >= len(rest):
            break
        ch = rest[i]
        if ch in "^_":
            j = i + 1
            while j < len(rest) and rest[j].isspace():
                j += 1
            if j >= len(rest) or rest[j] != "(":
                raise EquationError(f"после «{ch}» ожидаются условия в скобках")
            end = _match_close(rest, j)
            (above if ch == "^" else below).append(rest[j + 1:end].strip())
            i = end + 1
        elif ch == "(":
            end = _match_close(rest, i)
            nxt = rest[end + 1] if end + 1 < len(rest) else ""
            if nxt and (nxt.isalnum() or nxt in "([·*.") and not _is_note(rest[i + 1:end]):
                break  # это формула вида (NH4)2SO4
            above.append(rest[i + 1:end].strip())
            i = end + 1
        else:
            break
    return [a for a in above if a], [b for b in below if b], rest[i:]


def _split_terms(side: str) -> list[str]:
    terms, buf, depth = [], [], 0
    for i, ch in enumerate(side):
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
        if ch == "+" and depth == 0:
            prev = side[i - 1] if i else ""
            rest = side[i + 1:].lstrip()
            is_charge = prev == "^" or (prev != "" and not prev.isspace()
                                        and (rest == "" or rest.startswith("+")))
            if not is_charge:
                terms.append("".join(buf))
                buf = []
                continue
        buf.append(ch)
    terms.append("".join(buf))
    return terms


def _is_note(content: str) -> bool:
    c = content.strip()
    if not c:
        return True
    if not (c[0].isupper() or c[0] in "(["):
        return True
    try:
        parse_formula(c)
    except FormulaError:
        return True
    return " " in c


def parse_term(raw: str) -> Term:
    t = raw.strip()
    if not t:
        raise EquationError("пустое слагаемое (лишний «+»?)")
    mark = "".join(dict.fromkeys(ch for ch in t if ch in MARKS))
    for ch in MARKS:
        t = t.replace(ch, "")
    t = t.strip()

    coef = None
    m = re.match(r"^(\d+)\s*/\s*\d+", t)
    if m:
        raise EquationError(f"дробные коэффициенты не поддерживаются: «{raw.strip()}»")
    m = re.match(r"^(\d+)\s*", t)
    if m:
        coef = int(m.group(1))
        if coef == 0:
            raise EquationError(f"нулевой коэффициент: «{raw.strip()}»")
        t = t[m.end():]

    notes = []
    while t.endswith(")"):
        j = _match_open(t, len(t) - 1)
        before = t[:j].rstrip()
        content = t[j + 1:-1]
        if not before or not _is_note(content):
            break
        notes.insert(0, content.strip())
        t = before
    try:
        formula = parse_formula(t)
    except FormulaError as e:
        raise EquationError(f"«{raw.strip()}»: {e}") from None
    return Term(coef=coef, formula=formula, note=", ".join(n for n in notes if n), mark=mark)


def parse_equation(line: str) -> Equation:
    raw = line.strip()
    pos, sym, reversible = _find_arrow(raw)
    lhs = raw[:pos]
    above, below, rhs = _parse_conditions(raw[pos + len(sym):])

    left = [parse_term(x) for x in _split_terms(lhs)]
    right = [parse_term(x) for x in _split_terms(rhs)]

    for side_name, side in (("реагентов", left), ("продуктов", right)):
        seen = set()
        for t in side:
            if t.key() in seen:
                raise EquationError(f"вещество {t.formula.text} повторяется в списке {side_name}")
            seen.add(t.key())
    return Equation(left, right, ", ".join(above), ", ".join(below), reversible, raw)


def parse_lines(text: str):
    """Разбирает многострочный текст. Возвращает список (номер строки, строка, Equation | EquationError)."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            out.append((n, s, parse_equation(s)))
        except (EquationError, FormulaError) as e:
            out.append((n, s, EquationError(str(e))))
    return out


# ---------------------------------------------------------------- отображение

_MARKUP_RUN = re.compile(r"[0-9A-Za-zА-Яа-яЁё°+\-−]+")


def markup_html(text: str, auto_sub: bool = True) -> str:
    """Текст подписи (условия, пояснения) в HTML.

    _(…) — нижний индекс, ^(…) — верхний; внутри скобок разметка может быть вложенной:
    HCl_((aq.)) -> HCl<sub>(aq.)</sub>. Короткая форма без скобок: H_2, Fe^3+.
    Градус: t°, t^\\circ, t^o — всегда выводится знаком «°».
    Цифры сразу после латинской буквы или скобки — индексы автоматически (H2SO4, MnO2).
    """
    import html as _html
    text = canonical_degrees(text)
    out = []
    prev = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "_^" and i + 1 < len(text):
            tag = "sub" if ch == "_" else "sup"
            if text[i + 1] == "(":
                try:
                    end = _match_close(text, i + 1)
                except EquationError:
                    end = None
                if end is not None:
                    out.append(f"<{tag}>{markup_html(text[i + 2:end], auto_sub)}</{tag}>")
                    i, prev = end + 1, ""
                    continue
            else:
                m = _MARKUP_RUN.match(text, i + 1)
                if m:
                    out.append(f"<{tag}>{markup_html(m.group(0), False)}</{tag}>")
                    i, prev = m.end(), ""
                    continue
        if ch.isdigit():
            j = i
            while j < len(text) and text[j].isdigit():
                j += 1
            digits = text[i:j]
            sub = auto_sub and (prev.isascii() and prev.isalpha() or prev in (")", "]"))
            out.append(f"<sub>{digits}</sub>" if sub else digits)
            i, prev = j, digits[-1]
            continue
        out.append(_html.escape(ch))
        prev = ch
        i += 1
    return "".join(out)


def conditions_html(text: str) -> str:
    return markup_html(text)


def term_html(coef, formula: str, note: str = "", mark: str = "", show_coef: bool = True) -> str:
    import html as _html
    parts = []
    if show_coef and coef not in (None, 1, ""):
        parts.append(f'<span class="coef">{_html.escape(str(coef))}</span>')
    parts.append(f'<span class="formula">{formula_html(formula)}</span>')
    if mark:
        parts.append(f'<span class="mark">{mark}</span>')
    if note:
        parts.append(f'<span class="note">({markup_html(note, auto_sub=False)})</span>')
    return "".join(parts)


def arrow_html(above: str = "", below: str = "", reversible: bool = False) -> str:
    sym = "⇄" if reversible else "⟶"
    return (
        '<span class="arrow">'
        f'<span class="cond above">{conditions_html(above)}</span>'
        f'<span class="arrow-sym">{sym}</span>'
        f'<span class="cond below">{conditions_html(below)}</span>'
        "</span>"
    )


def equation_html(eq: Equation, coefs: list[int] | None = None, show_coefs: bool = True) -> str:
    """HTML уравнения; coefs — подставить другие коэффициенты (например, предложенные)."""
    if coefs is not None:
        eq = eq.with_coefficients(coefs)

    def side(terms):
        return '<span class="plus"> + </span>'.join(
            f'<span class="term">{term_html(t.coef, t.formula.text, t.note, t.mark, show_coefs)}</span>'
            for t in terms)

    return f'<span class="eq">{side(eq.left)}{arrow_html(eq.above, eq.below, eq.reversible)}{side(eq.right)}</span>'
