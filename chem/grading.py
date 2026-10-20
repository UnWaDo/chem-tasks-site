"""Автоматическая проверка ответа ученика."""
from __future__ import annotations

from dataclasses import dataclass

from .balance import is_balanced, reduce_coefs
from .formula import FormulaError, normalize_formula, parse_formula

WATER = "H2O"


@dataclass
class GradeResult:
    score: float          # доля от максимума: 1, partial или 0
    verdict: str          # correct / partial / wrong / empty
    feedback: str
    ref_index: int = 0    # какой из допустимых ответов оказался ближайшим


def collect_side(rows) -> tuple[dict[str, int], list[str]]:
    """Строки ответа [{"c": "2", "f": "H2"}] -> {формула: коэф}. Пустые строки пропускаются."""
    out: dict[str, int] = {}
    problems = []
    for row in rows or []:
        f = (row.get("f") or "").strip()
        c = str(row.get("c") or "").strip()
        if not f:
            continue
        try:
            parse_formula(f)
        except FormulaError as e:
            problems.append(f"«{f}»: {e}")
        key = normalize_formula(f)
        if c == "":
            n = 1
        elif c.isdigit() and int(c) > 0:
            n = int(c)
        else:
            problems.append(f"неверный коэффициент «{c}» у {f}")
            n = 0
        out[key] = out.get(key, 0) + n
    return out, problems


def grade(answer: dict, references: list[tuple[dict[str, int], dict[str, int]]],
          partial: float = 0.5) -> GradeResult:
    """answer = {"L": [...], "R": [...]}; references — список (реагенты, продукты) {формула: коэф}."""
    left, p1 = collect_side(answer.get("L"))
    right, p2 = collect_side(answer.get("R"))
    problems = p1 + p2
    if not left and not right:
        return GradeResult(0, "empty", "Ответ не дан.")

    best = None
    for idx, (ref_l, ref_r) in enumerate(references):
        res = _grade_one(left, right, ref_l, ref_r, partial)
        res.ref_index = idx
        if best is None or res.score > best.score:
            best = res
    if problems:
        best.feedback += " Замечания: " + "; ".join(problems) + "."
    return best


def _grade_one(left, right, ref_l, ref_r, partial) -> GradeResult:
    if set(left) == set(ref_l) and set(right) == set(ref_r):
        keys = [("L", k) for k in sorted(ref_l)] + [("R", k) for k in sorted(ref_r)]
        mine = [(left if s == "L" else right)[k] for s, k in keys]
        ref = [(ref_l if s == "L" else ref_r)[k] for s, k in keys]
        if mine == ref:
            return GradeResult(1.0, "correct", "Верно.")
        if all(mine) and reduce_coefs(mine) == reduce_coefs(ref):
            return GradeResult(partial, "partial",
                               "Вещества верны, уравнение уравнено, но коэффициенты не наименьшие.")
        if all(mine) and _balanced(keys, mine):
            return GradeResult(partial, "partial",
                               "Вещества верны, уравнение уравнено, но коэффициенты отличаются от ожидаемых.")
        return GradeResult(partial, "partial", "Вещества верны, но коэффициенты расставлены неверно.")

    def no_water(d):
        return {k for k in d if k != WATER}

    if no_water(left) == no_water(ref_l) and no_water(right) == no_water(ref_r):
        return GradeResult(0, "wrong", "Набор веществ верен, но ошибка с водой (наличие или сторона уравнения).")
    return GradeResult(0, "wrong", "Набор веществ не совпадает с ожидаемым.")


def _balanced(keys, coefs) -> bool:
    try:
        lf = [parse_formula(k) for s, k in keys if s == "L"]
        rf = [parse_formula(k) for s, k in keys if s == "R"]
    except FormulaError:
        return False
    n = len(lf)
    return is_balanced(lf, rf, coefs[:n] + coefs[n:])
