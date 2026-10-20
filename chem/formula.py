"""Разбор химических формул: состав, заряд, нормализация записи и HTML-отображение.

Поддерживается:
  * элементы, индексы, скобки () и [] любой вложенности: K4[Fe(CN)6], (NH4)2SO4;
  * кристаллогидраты: CuSO4·5H2O, CuSO4*5H2O, CuSO4.5H2O;
  * заряды: SO4^2-, SO4{2-}, SO4^{2-}, SO₄²⁻, NH4+, Fe3+ (одноатомный ион),
    SO42- (последняя цифра перед знаком считается зарядом, если цифр две и больше);
  * электрон: e, e-, ē;
  * подстрочные символы Unicode (H₂O).
"""
from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass, field

ELEMENTS = frozenset(
    """H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn
    Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce
    Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn
    Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl
    Mc Lv Ts Og D""".split()
)

ELECTRON = "e"


class FormulaError(ValueError):
    """Ошибка разбора формулы (сообщение пригодно для показа пользователю)."""


_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_SUP = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6",
        "⁷": "7", "⁸": "8", "⁹": "9", "⁺": "+", "⁻": "-"}
_HYDRATE_DOTS = "·•∙⋅*×"
_DASHES = "−–—"


@dataclass(frozen=True)
class Formula:
    text: str                      # нормализованная запись, например "SO4^2-"
    atoms: dict = field(default_factory=dict, hash=False, compare=False)
    charge: int = 0

    @property
    def is_electron(self) -> bool:
        return self.text.split("^")[0] == ELECTRON

    @property
    def is_water(self) -> bool:
        return self.text == "H2O"

    def html(self) -> str:
        return formula_html(self.text)

    def __str__(self) -> str:
        return self.text


def _prepare(raw: str) -> str:
    s = "".join(raw.split())                      # убираем все пробелы
    s = s.translate(_SUB)
    for ch in _DASHES:
        s = s.replace(ch, "-")
    s = s.replace("ē", "e-")
    # надстрочные символы -> ^<цифры><знак>
    s = re.sub("[⁰¹²³⁴⁵⁶⁷⁸⁹]*[⁺⁻]",
               lambda m: "^" + "".join(_SUP[c] for c in m.group(0)), s)
    for ch in _HYDRATE_DOTS:
        s = s.replace(ch, "·")
    s = re.sub(r"(?<=[A-Za-z0-9)\]])\.(?=[0-9A-Z(\[])", "·", s)
    # варианты записи заряда в скобках: {2-}, ^{2-}, ^(2-)
    s = re.sub(r"\^?\{([0-9]*[+-]|[+-][0-9]*)\}$", r"^\1", s)
    s = re.sub(r"\^\(([0-9]*[+-]|[+-][0-9]*)\)$", r"^\1", s)
    return s


def _split_charge(s: str) -> tuple[str, int]:
    """Отделяет заряд от тела формулы. Возвращает (тело, заряд)."""
    m = re.search(r"\^([0-9]*)([+-])$", s) or re.search(r"\^([+-])([0-9]+)$", s)
    if m:
        a, b = m.groups()
        digits, sign = (a, b) if b in "+-" else (b, a)
        n = int(digits) if digits else 1
        if n == 0:
            raise FormulaError(f"нулевой заряд в «{s}»")
        return s[:m.start()], n if sign == "+" else -n
    if "^" in s:
        raise FormulaError(f"не удалось разобрать заряд в «{s}»")

    m = re.search(r"([+-]+)$", s)
    if not m:
        return s, 0
    signs = m.group(1)
    if len(set(signs)) != 1:
        raise FormulaError(f"не удалось разобрать заряд в «{s}»")
    body = s[:m.start()]
    sign = 1 if signs[0] == "+" else -1
    if len(signs) > 1:                             # Fe+++
        return body, sign * len(signs)
    d = re.search(r"([0-9]+)$", body)
    if not d:
        return body, sign
    digits = d.group(1)
    head = body[:d.start()]
    if head in ELEMENTS:                           # Fe3+, S2-, Al3+
        return head, sign * int(digits)
    if len(digits) >= 2:                           # SO42-, PO43-, Cr2O72-
        rest = digits[:-1]
        return head + ("" if rest == "1" else rest), sign * int(digits[-1])
    return body, sign                              # NH4+, NO3-


def _read_num(s: str, i: int) -> tuple[int, int]:
    j = i
    while j < len(s) and s[j].isdigit():
        j += 1
    if j == i:
        return 1, i
    n = int(s[i:j])
    if n == 0:
        raise FormulaError("нулевой индекс")
    return n, j


def _parse_seq(s: str, i: int, closer: str | None) -> tuple[Counter, int]:
    counts: Counter = Counter()
    start = i
    while i < len(s):
        ch = s[i]
        if ch in "([":
            sub, i = _parse_seq(s, i + 1, ")" if ch == "(" else "]")
            n, i = _read_num(s, i)
            for el, k in sub.items():
                counts[el] += k * n
        elif ch in ")]":
            if ch != closer:
                raise FormulaError(f"лишняя закрывающая скобка «{ch}»")
            if i == start:
                raise FormulaError("пустые скобки")
            return counts, i + 1
        elif ch.isupper():
            two = s[i:i + 2]
            if len(two) == 2 and two[1].islower() and two in ELEMENTS:
                sym, i = two, i + 2
            elif ch in ELEMENTS:
                sym, i = ch, i + 1
            else:
                bad = two if len(two) == 2 and two[1].islower() else ch
                raise FormulaError(f"неизвестный элемент «{bad}»")
            n, i = _read_num(s, i)
            counts[sym] += n
        elif ch.islower():
            raise FormulaError(f"неожиданная строчная буква «{ch}» (символ элемента начинается с заглавной)")
        else:
            raise FormulaError(f"недопустимый символ «{ch}»")
    if closer:
        raise FormulaError("не закрыта скобка")
    return counts, i


def parse_formula(raw: str) -> Formula:
    s = _prepare(raw)
    if not s:
        raise FormulaError("пустая формула")
    body, charge = _split_charge(s)
    if body == ELECTRON:
        if charge not in (0, -1):
            raise FormulaError("заряд электрона должен быть −1")
        return Formula(text="e^-", atoms={}, charge=-1)
    if not body:
        raise FormulaError(f"нет формулы в «{raw}»")

    atoms: Counter = Counter()
    for part in body.split("·"):
        if not part:
            raise FormulaError("пустая часть кристаллогидрата")
        mult, j = _read_num(part, 0)
        if j == len(part):
            raise FormulaError(f"нет формулы после числа «{part}»")
        sub, _ = _parse_seq(part[j:], 0, None)
        for el, k in sub.items():
            atoms[el] += k * mult

    text = body + _charge_suffix(charge)
    return Formula(text=text, atoms=dict(atoms), charge=charge)


def _charge_suffix(charge: int) -> str:
    if charge == 0:
        return ""
    sign = "+" if charge > 0 else "-"
    n = abs(charge)
    return "^" + ("" if n == 1 else str(n)) + sign


def normalize_formula(raw: str) -> str:
    """Нормализованная запись формулы; если формула не разбирается — очищенная строка."""
    try:
        return parse_formula(raw).text
    except FormulaError:
        return _prepare(raw)


def is_valid_formula(raw: str) -> bool:
    try:
        parse_formula(raw)
        return True
    except FormulaError:
        return False


def formula_html(text: str) -> str:
    """HTML с индексами и зарядом. Принимает нормализованную (или произвольную) запись."""
    if "^" in text:
        body, charge = text.split("^", 1)
    else:
        body, charge = text, ""
    out = []
    sub_mode = False
    digits = ""

    def flush():
        nonlocal digits
        if digits:
            out.append(f"<sub>{digits}</sub>" if sub_mode else digits)
            digits = ""

    for ch in body:
        if ch.isdigit():
            digits += ch
            continue
        flush()
        sub_mode = ch.isalpha() or ch in ")]"
        out.append(html.escape(ch))
    flush()
    if charge:
        out.append("<sup>" + html.escape(charge.replace("-", "−")) + "</sup>")
    return "".join(out)
