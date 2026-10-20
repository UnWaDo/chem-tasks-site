"""Проверка баланса и подбор коэффициентов (точная арифметика на дробях)."""
from __future__ import annotations

import itertools
from fractions import Fraction
from functools import reduce
from math import gcd

from .formula import Formula


def composition_matrix(left: list[Formula], right: list[Formula]) -> tuple[list[str], list[list[int]]]:
    """Строки — элементы (и заряд), столбцы — вещества; продукты с минусом."""
    species = list(left) + list(right)
    keys = sorted({el for f in species for el in f.atoms})
    if any(f.charge for f in species):
        keys.append("заряд")
    rows = []
    for key in keys:
        row = []
        for idx, f in enumerate(species):
            v = f.charge if key == "заряд" else f.atoms.get(key, 0)
            row.append(v if idx < len(left) else -v)
        rows.append(row)
    return keys, rows


def imbalance(left: list[Formula], right: list[Formula], coefs: list[int]) -> dict[str, int]:
    """Разность (реагенты − продукты) по каждому элементу и заряду; пусто, если уравнено."""
    keys, rows = composition_matrix(left, right)
    out = {}
    for key, row in zip(keys, rows):
        d = sum(a * c for a, c in zip(row, coefs))
        if d:
            out[key] = d
    return out


def is_balanced(left: list[Formula], right: list[Formula], coefs: list[int]) -> bool:
    return not imbalance(left, right, coefs)


def _nullspace(rows: list[list[int]], n: int) -> list[list[Fraction]]:
    m = [[Fraction(x) for x in row] for row in rows]
    pivots = []
    r = 0
    for c in range(n):
        p = next((i for i in range(r, len(m)) if m[i][c] != 0), None)
        if p is None:
            continue
        m[r], m[p] = m[p], m[r]
        pv = m[r][c]
        m[r] = [x / pv for x in m[r]]
        for i in range(len(m)):
            if i != r and m[i][c] != 0:
                f = m[i][c]
                m[i] = [a - f * b for a, b in zip(m[i], m[r])]
        pivots.append(c)
        r += 1
        if r == len(m):
            break
    free = [c for c in range(n) if c not in pivots]
    basis = []
    for f in free:
        v = [Fraction(0)] * n
        v[f] = Fraction(1)
        for row_idx, pc in enumerate(pivots):
            v[pc] = -m[row_idx][f]
        basis.append(v)
    return basis


def _to_integers(v: list[Fraction]) -> list[int]:
    den = reduce(lambda a, b: a * b // gcd(a, b), (x.denominator for x in v), 1)
    ints = [int(x * den) for x in v]
    g = reduce(gcd, (abs(x) for x in ints), 0) or 1
    return [x // g for x in ints]


def reduce_coefs(coefs: list[int]) -> list[int]:
    g = reduce(gcd, coefs, 0) or 1
    return [c // g for c in coefs]


def balance_options(left: list[Formula], right: list[Formula], limit: int = 6) -> tuple[list[list[int]], int]:
    """Варианты наименьших целых положительных коэффициентов.

    Возвращает (варианты, размерность пространства решений). Размерность 1 — решение
    единственно; больше 1 — уравнение можно уравнять разными независимыми способами
    (обычно это «сумма» нескольких процессов), варианты перечисляются перебором.
    """
    n = len(left) + len(right)
    _, rows = composition_matrix(left, right)
    basis = _nullspace(rows, n)
    dim = len(basis)
    if dim == 0:
        return [], 0
    if dim == 1:
        v = _to_integers(basis[0])
        if all(x < 0 for x in v):
            v = [-x for x in v]
        return ([v] if all(x > 0 for x in v) else []), 1

    bound = {2: 12, 3: 6, 4: 4}.get(dim, 3)
    found = set()
    for ts in itertools.product(range(1, bound + 1), repeat=min(dim, 5)):
        if reduce(gcd, ts) != 1:
            continue
        ts = list(ts) + [1] * (dim - len(ts))
        v = [sum(t * b[i] for t, b in zip(ts, basis)) for i in range(n)]
        if all(x > 0 for x in v):
            found.add(tuple(_to_integers(v)))
    options = sorted(found, key=lambda c: (max(c), sum(c)))
    return [list(c) for c in options[:limit]], dim
