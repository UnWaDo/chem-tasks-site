"""Прототип разбора PDF олимпиадных заданий: PDF -> черновик в блоках формата olymp-bundle (этап A).

Офлайн-инструмент для компьютера учителя или разработчика, на сервер не ставится.
Нужен PyMuPDF (pip install pymupdf, лицензия AGPL) — в requirements.txt сайта его нет и не должно быть.

Запуск из корня проекта:
    python -I tools/olympiad/parse_pdf.py <файл.pdf> <папка_результата> --project .
Результат: <имя>.json (черновик), <имя>.html (предпросмотр), assets/*.png (вырезки рисунков).
Что умеет и чего нет — docs/olympiad/README.md, раздел «Прототип».
"""
import argparse
import collections
import hashlib
import html
import json
import os
import re
import sys
import unicodedata

import pymupdf

PARSER_VERSION = "proto-0.3"

# ---------------------------------------------------------------- метаданные из имени файла
STAGES = {"sch": "school", "mun": "municipal", "reg": "regional", "region": "regional",
          "final": "final", "prigl": "invitational"}
KINDS = {"tasks": "tasks", "sol": "solutions", "ans": "solutions", "krit": "criteria",
         "taskskrit": "tasks+criteria"}
TOURS = {"teor": "theory", "prak": "practice", "teor1": "theory1", "teor2": "theory2"}


def meta_from_filename(fn):
    base = os.path.basename(fn)[:-4]
    parts = base.split("-")
    m = {"file": os.path.basename(fn), "kind": KINDS.get(parts[0]), "subject": parts[1] if len(parts) > 1 else None}
    grades = re.search(r"-chem-(\d+)(?:-(\d+))?-", base)
    if grades:
        lo, hi = int(grades.group(1)), int(grades.group(2) or grades.group(1))
        m["grades"] = list(range(lo, hi + 1))
    for p in parts:
        if p in STAGES:
            m["stage"] = STAGES[p]
        if p in TOURS:
            m["tour"] = TOURS[p]
    yy = re.search(r"-(\d\d)-(\d{1,2})$", base)
    if yy:
        m["season"] = f"20{yy.group(1)}/{int(yy.group(1)) + 1:02d}"
    known = set(STAGES) | set(TOURS) | set(KINDS) | {"chem"}
    rest = [p for p in parts[2:] if not p.isdigit() and p not in known]
    if rest:
        m["region"] = rest[0]
    return m


# ---------------------------------------------------------------- символы
# Кодировка шрифта Symbol (Adobe): код -> Unicode. В PDF из Word такие символы попадают в PUA U+F0xx.
SYMBOL = {
    0x22: "∀", 0x24: "∃", 0x27: "∋", 0x2D: "−", 0x40: "≅", 0x41: "Α", 0x42: "Β", 0x43: "Χ", 0x44: "Δ", 0x45: "Ε",
    0x46: "Φ", 0x47: "Γ", 0x48: "Η", 0x4C: "Λ", 0x4D: "Μ", 0x4E: "Ν", 0x50: "Π", 0x51: "Θ", 0x52: "Ρ", 0x53: "Σ",
    0x54: "Τ", 0x57: "Ω", 0x58: "Ξ", 0x59: "Ψ", 0x5E: "⊥", 0x61: "α", 0x62: "β", 0x63: "χ", 0x64: "δ", 0x65: "ε",
    0x66: "φ", 0x67: "γ", 0x68: "η", 0x69: "ι", 0x6A: "ϕ", 0x6B: "κ", 0x6C: "λ", 0x6D: "μ", 0x6E: "ν", 0x6F: "ο",
    0x70: "π", 0x71: "θ", 0x72: "ρ", 0x73: "σ", 0x74: "τ", 0x75: "υ", 0x76: "ϖ", 0x77: "ω", 0x78: "ξ", 0x79: "ψ",
    0x7A: "ζ", 0x7E: "∼", 0xA2: "′", 0xA3: "≤", 0xA5: "∞", 0xAB: "↔", 0xAC: "←", 0xAD: "↑", 0xAE: "→", 0xAF: "↓",
    0xB0: "°", 0xB1: "±", 0xB2: "″", 0xB3: "≥", 0xB4: "×", 0xB5: "∝", 0xB6: "∂", 0xB7: "•", 0xB8: "÷", 0xB9: "≠",
    0xBA: "≡", 0xBB: "≈", 0xBC: "…", 0xC5: "⊕", 0xD6: "√", 0xD7: "⋅", 0xDB: "⇔", 0xDC: "⇐", 0xDE: "⇒", 0xE5: "∑",
    0xF2: "∫",
}


def fix_chars(text, font):
    out = []
    sym_font = "Symbol" in font
    for ch in text:
        o = ord(ch)
        if 0xF000 <= o <= 0xF0FF:
            out.append(SYMBOL.get(o - 0xF000, chr(o - 0xF000) if 0x20 <= o - 0xF000 < 0x7F else "�"))
        elif sym_font and o < 0x100 and o in SYMBOL:
            out.append(SYMBOL[o])
        elif 0x1D400 <= o <= 0x1D7FF:  # математический курсив (Cambria Math)
            out.append(unicodedata.normalize("NFKC", ch))
        else:
            out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------- геометрия
def inside(b, r, tol=1.0):
    return b[0] >= r[0] - tol and b[1] >= r[1] - tol and b[2] <= r[2] + tol and b[3] <= r[3] + tol


def overlap_frac(b, r):
    x0, y0, x1, y1 = max(b[0], r[0]), max(b[1], r[1]), min(b[2], r[2]), min(b[3], r[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    area = max((b[2] - b[0]) * (b[3] - b[1]), 1e-6)
    return (x1 - x0) * (y1 - y0) / area


def union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def grow(b, d):
    return (b[0] - d, b[1] - d, b[2] + d, b[3] + d)


def intersects(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def cluster(boxes, pad):
    boxes = [tuple(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        out = []
        for b in boxes:
            for i, o in enumerate(out):
                if intersects(grow(b, pad), o):
                    out[i] = union(o, b)
                    changed = True
                    break
            else:
                out.append(b)
        boxes = out
    return boxes


# ---------------------------------------------------------------- разметка строк
def span_markup(spans):
    """Строка PDF -> текст с разметкой: _(…) / ^(…) по кеглю и базовой линии, **жирный**."""
    sized = [s for s in spans if s["text"].strip()]
    if not sized:
        return ""
    dom = max(s["size"] for s in sized)
    base_spans = [s for s in sized if s["size"] >= dom * 0.9]
    base = collections.Counter(round(s["origin"][1], 1) for s in base_spans).most_common(1)[0][0]
    parts = []
    for s in spans:
        t = fix_chars(s["text"], s["font"])
        if not t:
            continue
        small = s["size"] < dom * 0.85
        dy = s["origin"][1] - base
        if small and t.strip() and dy > dom * 0.08:
            t = t.strip()
            parts.append(("sub", t))
        elif small and t.strip() and (dy < -dom * 0.15 or s["flags"] & 1):
            t = t.strip()
            parts.append(("sup", t))
        else:
            bold = bool(s["flags"] & 16) or "Bold" in s["font"]
            parts.append(("b" if bold and t.strip() else "n", t))
    # склеиваем соседние одинаковые
    merged = []
    for kind, t in parts:
        if merged and merged[-1][0] == kind:
            merged[-1] = (kind, merged[-1][1] + t)
        else:
            merged.append((kind, t))
    out = []
    for kind, t in merged:
        if kind == "sub":
            out.append("_" + t if re.fullmatch(r"[0-9]+", t) else f"_({t})")
        elif kind == "sup":
            out.append("^" + t if re.fullmatch(r"[0-9]*[+\-−]?|[+\-−]", t) else f"^({t})")
        elif kind == "b":
            lead = t[:len(t) - len(t.lstrip())]
            trail = t[len(t.rstrip()):]
            out.append(f"{lead}**{t.strip()}**{trail}")
        else:
            out.append(t)
    s = "".join(out)
    return re.sub(r"\*\*(\s*)\*\*", r"\1", s)


def plain(text):
    """Текст без разметки — для поиска и регулярных выражений."""
    t = text.replace("**", "")
    t = re.sub(r"[_^]\(([^()]*)\)", r"\1", t)
    t = re.sub(r"[_^]([0-9+\-−]+)", r"\1", t)
    return t


# ---------------------------------------------------------------- шаблоны разметки задач
RE_PROBLEM = re.compile(
    r"^(?:Решение\s+(?:задачи|задания)\s+|[Зз]адача\s+|ЗАДАЧА\s+|Задание\s+|№\s*)(\d+(?:\s*[-–]\s*\d+)?)\.?\s*(.*)$")
RE_NUMBERED = re.compile(r"^(\d{1,2})\.\s+(.*)$")
RE_GRADES = re.compile(r"\((?:только\s+)?для\s+([\d,\s и]+?)\s*класс", re.I)
RE_EXTNUM = re.compile(r"\(\s*№?\s*(\d+(?:\s*[-–]\s*\d+)?)\s*\)")
RE_AUTHOR = re.compile(r"\(\s*автор[ыа]?:?\s*([^)]*)\)", re.I)
RE_VARIANT = re.compile(r"(\d+)\s*класс\s+([IVX]+)\s*вариант", re.I)
RE_SUBQ = re.compile(r"^(\d{1,2})(?:[.)]|\s*[-–]\s*\d+\.)\s*(?=[^\d\s])")
RE_LIST = re.compile(r"^(?:\d{1,2}\)|[а-еА-Е]\))\s")
RE_TOTAL = re.compile(r"^(?:ИТОГО|Итого)[^0-9]*([\d.,]+)\s*балл", re.I)
RE_POINTS = re.compile(r"(?:За\s+(?:верный|каждый верный)\s+ответ[^0-9]*)([\d.,]+)\s*балл", re.I)
RE_RUBRIC = re.compile(r"^(Система оценивания|Разбалловка|Рекомендации к оцениванию|Критерии оценивания)", re.I)
RE_ANSWER = re.compile(r"^Ответ\b[.:]?\s*(.*)$")
SECTION_WORDS = re.compile(r"^(Неорганическая|Органическая|Физическая|Аналитическая)\s+химия$|^Химия\s+(и\s+[Жж]изнь|в\s+.+)$")
GRADE_WORDS = {"Седьмой": 7, "Восьмой": 8, "Девятый": 9, "Десятый": 10, "Одиннадцатый": 11}


def parse_grades(s):
    return sorted({int(x) for x in re.findall(r"\d+", s) if 5 <= int(x) <= 11})


# ---------------------------------------------------------------- уравнения
def load_chem(project):
    if not project:
        return None
    sys.path.insert(0, project)
    try:
        from chem.equation import parse_equation
        return parse_equation
    except Exception:
        return None


HOMO = str.maketrans("АВСЕНКМОРТХ", "ABCEHKMOPTX")
RE_EQ_LINE = re.compile(r"[=→⇄⇌]|\s->\s")


def try_equation(parse_equation, text):
    """Возвращает (статус, данные): equation / template / None."""
    p = plain(text).strip()
    if not RE_EQ_LINE.search(p) or len(p) > 160 or "+" not in p:
        return None
    # отрезаем подписи вида «Реакция 2:», «1)», хвосты «;» «.», номера «(1)»
    core = re.sub(r"^(?:Реакция\s*\d+\s*[:.]|р-ция\s*\d+\s*[:.]|\d+\)|\d+\.)\s*", "", p)
    core = re.sub(r"\s*\(\d+\)\s*$", "", core).rstrip(" ;.,")
    core = re.split(r"\s+или", core)[0]
    core = re.sub(r"^(?:\(\d+\)|\[\d+\]|Р-ция\s*\d+\s*:|р-ция\s*\d+\s*:)\s*", "", core)
    # кириллические двойники латинских букв в формулах (СН3, Н2О, О2)
    core = re.sub(r"[А-ЯЁа-яё0-9A-Za-z()\[\]]+", lambda m: m.group(0).translate(HOMO)
                  if not re.search(r"[а-яё]", m.group(0)) and re.search(r"[A-Z0-9]", m.group(0).translate(HOMO)) else m.group(0), core)
    core = core.replace("  ", " ")
    if re.search(r"[А-ЯЁ]\s*\(|\bX\d|\bХ\d|(?:^|[\s+])[A-ZА-ЯЁ](?:[\s+]|$)", core) and re.search(r"[А-ЯЁ]", core):
        return ("template", core)
    if parse_equation is None:
        return ("equation?", core)
    try:
        eq = parse_equation(core)
        an = eq.analyze()
        return ("equation", {"text": core, "balanced": bool(an.ok) if hasattr(an, "ok") else None})
    except Exception as e:  # noqa: BLE001
        if re.search(r"[a-zа-я]{4,}", core.replace("конц", "").replace("разб", "")):
            return None  # это обычная фраза со знаком «=»
        return ("equation-failed", {"text": core, "error": str(e)[:80]})


# ---------------------------------------------------------------- основной разбор
class Parser:
    def __init__(self, path, out_dir, parse_equation=None, dpi=170):
        self.path = path
        self.doc = pymupdf.open(path)
        self.out = out_dir
        self.dpi = dpi
        self.parse_equation = parse_equation
        self.meta = meta_from_filename(path)
        self.assets = []
        self.warnings = collections.Counter()
        self.stats = collections.Counter()
        os.makedirs(os.path.join(out_dir, "assets"), exist_ok=True)

    # -- колонтитулы: строки, повторяющиеся на многих страницах у верхнего/нижнего края
    def find_running(self):
        cnt = collections.Counter()
        for pg in self.doc:
            h = pg.rect.height
            seen = set()
            for b in pg.get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    y = l["bbox"][1]
                    if y < h * 0.09 or y > h * 0.92:
                        t = re.sub(r"\d+", "#", "".join(s["text"] for s in l["spans"]).strip())
                        if t and not RE_PROBLEM.match(t.replace("#", "1")):
                            seen.add((t, round(y / 8)))
            cnt.update(seen)
        n = len(self.doc)
        return {t for (t, _y), c in cnt.items() if n >= 2 and c >= max(2, n * 0.5)} | {"#"}

    def save_crop(self, pg, rect, kind, trim=False):
        clip = pymupdf.Rect(rect) & pg.rect
        if trim:
            clip = self.trim_white(pg, clip)
        pix = pg.get_pixmap(dpi=self.dpi, clip=clip)
        data = pix.tobytes("png")
        h = hashlib.sha256(data).hexdigest()[:16]
        fn = f"{h}.png"
        with open(os.path.join(self.out, "assets", fn), "wb") as f:
            f.write(data)
        aid = f"a{len(self.assets) + 1}"
        self.assets.append({"id": aid, "file": f"assets/{fn}", "sha256_16": h, "kind": kind, "page": pg.number + 1,
                            "bbox": [round(v, 1) for v in clip], "px": [pix.width, pix.height]})
        return aid

    @staticmethod
    def trim_white(pg, clip, pad=2.0):
        """Обрезает белые поля вокруг содержимого (картинка в широкой ячейке таблицы)."""
        pix = pg.get_pixmap(dpi=72, clip=clip, colorspace=pymupdf.csGRAY)
        w, h, data = pix.width, pix.height, pix.samples
        rows = [y for y in range(h) if min(data[y * pix.stride:y * pix.stride + w]) < 200]
        cols = [x for x in range(w) if any(data[y * pix.stride + x] < 200 for y in range(h))]
        if not rows or not cols:
            return clip
        return pymupdf.Rect(clip.x0 + cols[0] - pad, clip.y0 + rows[0] - pad,
                            clip.x0 + cols[-1] + 1 + pad, clip.y0 + rows[-1] + 1 + pad) & clip

    @staticmethod
    def attach_labels(region, lines, col_width, left_margin, body_font):
        """Присоединяет к рисунку короткие подписи рядом (буквы, формулы, условия над стрелками)."""
        labels = []
        changed = True
        while changed:
            changed = False
            for l in lines:
                if l in labels:
                    continue
                b = l["bbox"]
                short = len(plain(span_markup(l["spans"])).strip()) <= 30 and (b[2] - b[0]) < col_width * 0.45
                at_margin = b[0] < left_margin + 8 and not inside(b, region, 2)   # слово обтекающего текста
                font, size = body_font
                other_font = all(sp["font"].split(",")[0].split("-")[0] != font or sp["size"] < size * 0.92
                                 for sp in l["spans"] if sp["text"].strip())
                if short and not at_margin and (other_font or inside(b, region, 2)) and intersects(b, grow(region, 14)):
                    labels.append(l)
                    region = union(region, b)
                    changed = True
        return region, labels

    @staticmethod
    def refine_crop(region, body, pad=4.0):
        """Рамка вырезки с полями, но без строк основного текста сверху, снизу и сбоку (обтекание)."""
        x0, y0, x1, y1 = grow(region, pad)
        cx, cy = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2
        for b in body:
            if not intersects(b, (x0, y0, x1, y1)):
                continue
            if b[3] <= region[1] + 2:          # строка над рисунком
                y0 = max(y0, b[3] + 0.5)
            elif b[1] >= region[3] - 2:        # под рисунком
                y1 = min(y1, b[1] - 0.5)
            elif (b[0] + b[2]) / 2 < cx:       # текст слева (обтекание)
                x0 = max(x0, b[2] + 1)
            else:
                x1 = min(x1, b[0] - 1)
        return (x0, y0, x1, y1)

    def figure_regions(self, pg, tables):
        """Рисунки: растровые картинки и кластеры векторной графики (кроме линеек таблиц и подчёркиваний)."""
        boxes = []
        weight = []
        for im in self.page_images:
            b = im["bbox"]
            if (b[2] - b[0]) * (b[3] - b[1]) > 30:
                boxes.append(b)
                weight.append((b, 100))
        for d in self.page_drawings:
            r = d["rect"]
            w, h = r.width, r.height
            if (w < 1.6 or h < 1.6) and len(d["items"]) <= 2:
                # линейки таблиц и длинные подчёркивания — не рисунок; короткие линии вне таблиц — стрелки схем
                if any(intersects(tuple(r), t.bbox) for t in tables) or max(w, h) > pg.rect.width * 0.3:
                    continue
            if w * h > pg.rect.width * pg.rect.height * 0.5:  # рамка страницы
                continue
            if any(inside(r, t.bbox, 2) for t in tables) and d.get("fill") in (None, (1, 1, 1)) and len(d["items"]) <= 4:
                continue  # заливка/рамки ячеек
            boxes.append(tuple(r))
            weight.append((tuple(r), len(d["items"])))
        regs = [r for r in cluster(boxes, 8) if (r[2] - r[0]) > 12 and (r[3] - r[1]) > 8]
        # подложки заголовков и рамки (1–4 элемента без картинок) — не рисунки
        regs = [r for r in regs if sum(w for b, w in weight if inside(b, r, 1)) > 4]
        # прямоугольник‑рамка ответа («Ответ» в рамке) — не рисунок; отбрасываем пустые рамки без графики внутри
        return regs

    def parse(self):
        running = self.find_running()
        flow = []  # (page, y, kind, payload)
        for pg in self.doc:
            self.page_drawings = pg.get_drawings()   # дорогой вызов — один раз на страницу
            rulings = sum(1 for d in self.page_drawings if min(d["rect"].width, d["rect"].height) < 1.6
                          or any(it[0] == "re" for it in d["items"]))
            try:   # find_tables — около секунды на страницу; без линеек таблиц не бывает
                tables = pg.find_tables().tables if rulings >= 4 else []
            except Exception:  # noqa: BLE001
                tables = []
            self.page_images = pg.get_image_info()
            figs = self.figure_regions(pg, tables)
            d = pg.get_text("dict")
            lines = []
            for b in d["blocks"]:
                for l in b.get("lines", []):
                    raw = "".join(s["text"] for s in l["spans"]).strip()
                    if not raw:
                        continue
                    yb = l["bbox"][1]
                    if (yb < pg.rect.height * 0.09 or yb > pg.rect.height * 0.92) and re.sub(r"\d+", "#", raw) in running:
                        continue
                    lines.append(l)
            # колонки: альбомная страница с двумя полосами текста (СПб)
            two_col = pg.rect.width > pg.rect.height
            mid = pg.rect.width / 2

            def col(bb):
                return 0 if not two_col or bb[0] < mid - 5 else 1

            used = set()
            # таблицы
            for t in tables:
                tb = t.bbox
                fig_in = [f for f in figs if overlap_frac(f, tb) > 0.5]
                rows = []
                for r in t.rows:
                    row = []
                    for c in r.cells:
                        if c is None:
                            row.append(None)
                            continue
                        parts = []
                        for l in lines:
                            if not intersects(l["bbox"], c):
                                continue
                            sp = [s_ for s_ in l["spans"] if inside(((s_["bbox"][0] + s_["bbox"][2]) / 2, (s_["bbox"][1] + s_["bbox"][3]) / 2) * 2, c, 0)]
                            if sp:
                                parts.append((l["bbox"][1], sp[0]["bbox"][0], span_markup(sp)))
                            if overlap_frac(l["bbox"], tb) > 0.6:
                                used.add(id(l))
                        text = " ".join(t_ for _, _, t_ in sorted(parts)).strip()
                        cell = {"text": text}
                        cf = [f for f in fig_in if overlap_frac(f, c) > 0.5]
                        if cf:
                            # вся ячейка: у электронных формул буквы — текст, а черточки — графика
                            x0 = c[0]
                            for l in lines:
                                for s_ in l["spans"]:
                                    if inside(s_["bbox"], c, 1) and re.fullmatch(r"\s*\d{1,2}\)\s*", s_["text"]):
                                        x0 = max(x0, s_["bbox"][2])   # метку «1)» рисует сайт, в картинку не берём
                            cell["asset"] = self.save_crop(pg, (x0 + 1, c[1] + 1.5, c[2] - 1.5, c[3] - 1.5), "cell-figure", trim=True)
                            cell["text"] = re.sub(r"^\s*\d{1,2}\)\s*", "", cell["text"]) if x0 > c[0] else ""
                            self.stats["figures_in_tables"] += 1
                        row.append(cell)
                    rows.append(row)
                for f in fig_in:
                    figs.remove(f)
                self.stats["tables"] += 1
                flow.append((pg.number, col(tb), tb[1], "table", {"rows": rows}))
            # рисунки
            col_width = (pg.rect.width / 2 if two_col else pg.rect.width) * 0.75
            fonts = collections.Counter()
            for l in lines:
                for sp in l["spans"]:
                    fonts[(sp["font"].split(",")[0].split("-")[0], round(sp["size"]))] += len(sp["text"])
            body_font = fonts.most_common(1)[0][0] if fonts else ("", 12)
            free = [l for l in lines if id(l) not in used and not any(overlap_frac(l["bbox"], t.bbox) > 0.6 for t in tables)]
            grown = []
            for f in figs:
                same_col = [l for l in free if col(l["bbox"]) == col(f)]
                left = min((l["bbox"][0] for l in same_col), default=f[0])
                g, labels = self.attach_labels(f, same_col, col_width, left, body_font)
                grown.append((f, g, labels))
            # куски одной схемы, соединённые подписями, — один рисунок
            merged = [[f, g, list(labels)] for f, g, labels in grown]
            changed = True
            while changed:   # сливаем, пока есть пересечения: куски цепочки идут через промежуточные
                changed = False
                for i in range(len(merged)):
                    for j in range(i + 1, len(merged)):
                        if intersects(grow(merged[i][1], 4), merged[j][1]) or same_band(merged[i][1], merged[j][1]):
                            a_, b_ = merged[i], merged.pop(j)
                            a_[0], a_[1], a_[2] = union(a_[0], b_[0]), union(a_[1], b_[1]), a_[2] + b_[2]
                            changed = True
                            break
                    if changed:
                        break
            for f0, f, labels in merged:
                for l in labels:
                    used.add(id(l))
                body = [l["bbox"] for l in free if id(l) not in used]
                crop = self.refine_crop(f, body)
                if crop[2] - crop[0] < 8 or crop[3] - crop[1] < 8:
                    crop = grow(f, 2)
                text_inside = " ".join(plain(span_markup(l["spans"])) for l in labels)
                drawings = [dd for dd in self.page_drawings if inside(dd["rect"], f0, 2)]
                fills = sum(1 for dd in drawings if dd.get("fill") is not None)
                images = [im for im in self.page_images if overlap_frac(im["bbox"], f) > 0.5]
                kind = "raster" if images and not drawings else ("vector" if drawings and not images else "mixed")
                if kind == "vector" and fills > 60 and not labels:
                    self.warnings["figure-text-outlined"] += 1  # подписи схемы — кривые, текст не извлечь
                aid = self.save_crop(pg, crop, kind)
                self.stats[f"figures_{kind}"] += 1
                # обтекаемый рисунок часто начинается выше заголовка своей задачи — привязываем ниже верхнего края
                narrow = (f[2] - f[0]) < col_width * 0.8
                y_key = f[1] + min(20, (f[3] - f[1]) / 3) if narrow else f[1]
                flow.append((pg.number, col(f), y_key, "figure", {"asset": aid, "labels": text_inside[:500]}))
            # текст
            for l in lines:
                if id(l) in used:
                    continue
                if any(overlap_frac(l["bbox"], t.bbox) > 0.6 for t in tables):
                    continue
                m = span_markup(l["spans"])
                if m.strip():
                    flow.append((pg.number, col(l["bbox"]), l["bbox"][1], "line",
                                 {"text": m.strip(), "x0": l["bbox"][0], "x1": l["bbox"][2], "y1": l["bbox"][3],
                                  "bold": all((s["flags"] & 16 or "Bold" in s["font"]) for s in l["spans"] if s["text"].strip()),
                                  "pua": sum(1 for ch in "".join(s["text"] for s in l["spans"]) if 0xF000 <= ord(ch) <= 0xF0FF)}))
        for pg in self.doc:
            t = pg.get_text()
            letters = [ch for ch in t if ch.isalpha()]
            cyr = sum(1 for ch in letters if "а" <= ch.lower() <= "я")
            junk = sum(1 for ch in t if ch in "@>=:;<?")
            if len(t.strip()) < 200 and sum((i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]) for i in pg.get_image_info()) > pg.rect.width * pg.rect.height * 0.4:
                self.warnings["scanned-page"] += 1
            elif len(t) > 300 and junk > 0.05 * len(t) and cyr < 0.5 * len(letters):
                self.warnings["broken-encoding-page"] += 1
            if any("CambriaMath" in f[3] or "MT-Extra" in f[3] or "MTMI" in f[3] for f in pg.get_fonts()):
                self.warnings["math-objects-page"] += 1
        flow.sort(key=lambda x: (x[0], x[1], x[2]))
        return self.assemble(flow)

    # -- строки -> абзацы -> задачи
    def assemble(self, flow):
        # словарь слов документа: по нему решаем, был ли дефис в конце строки настоящим («брутто-формула»)
        self.words = collections.Counter(w.lower() for *_, kind, p in flow if kind == "line"
                                         for w in re.findall(r"[\w-]+", plain(p["text"])))
        # обычный межстрочный зазор для каждой страницы/колонки (медиана)
        gaps = collections.defaultdict(list)
        last = {}
        for pno, colno, y, kind, p in flow:
            if kind == "line":
                k = (pno, colno)
                if k in last and 0 < y - last[k] < 30:
                    gaps[k].append(y - last[k])
                last[k] = p["y1"]
        norm = {k: sorted(v)[len(v) // 2] for k, v in gaps.items() if v}
        xs = collections.defaultdict(list)
        for pno, colno, y, kind, p in flow:
            if kind == "line":
                xs[(pno, colno)].append(p["x1"])
        rights = {k: sorted(v)[int(len(v) * 0.8)] for k, v in xs.items()}
        blocks = []
        para = None
        prev = None
        for pno, colno, y, kind, p in flow:
            if kind != "line":
                para = None
                blocks.append({"type": kind, **p, "page": pno + 1})
                prev = None
                continue
            t = p["text"]
            pt = plain(t)
            same_line = prev is not None and prev["page"] == pno and prev["col"] == colno and abs(y - prev["y0"]) < 2
            new = not same_line and (para is None or prev is None or prev["page"] != pno or prev["col"] != colno
                   or y - prev["y1"] > norm.get((pno, colno), 3.0) + max(2.0, 0.3 * prev["h"]) or RE_LIST.match(pt) or RE_SUBQ.match(pt) or RE_PROBLEM.match(pt) or RE_ANSWER.match(pt)
                   or p["bold"] != prev["bold"] or (p["x0"] - prev["x0"] > 12) or RE_RUBRIC.match(pt)
                   or RE_TOTAL.match(pt) or prev["x1"] < rights[(pno, colno)] - 60 or re.match(r"^[а-еА-Е]\)|^[−\-–•o]\s", pt))
            # абзац, разорванный границей страницы: предыдущий не закончен, новый начинается со строчной или тире
            if (new and para is not None and prev is not None and prev["page"] != pno and blocks and blocks[-1] is para and not para.get("bold")
                    and not re.search(r"[.:;!?]\**$", para["text"].rstrip()) and re.match(r"^[а-яёa-z–—]", pt)):
                new = False
            if new:
                para = {"type": "p", "text": t, "page": pno + 1, "bold": p["bold"]}
                blocks.append(para)
            else:
                para["text"] = join_hyphen(para["text"], t, self.words)
            prev = {"page": pno, "col": colno, "y0": y, "y1": p["y1"], "h": p["y1"] - y, "x0": p["x0"], "x1": p["x1"], "bold": p["bold"]}
            if p["pua"]:
                self.stats["pua_fixed"] += p["pua"]
        # уравнения
        for b in blocks:
            if b["type"] == "p":
                r = try_equation(self.parse_equation, b["text"])
                if r:
                    st, data = r
                    self.stats[f"eq_{st}"] += 1
                    if st == "equation":
                        self.stats["eq_balanced" if data["balanced"] else "eq_unbalanced"] += 1
                    b["eq"] = {"status": st, **(data if isinstance(data, dict) else {"text": data})}
        return self.segment(blocks)

    def segment(self, blocks):
        has_headings = any(b["type"] == "p" and RE_PROBLEM.match(plain(b["text"])) for b in blocks)
        problems, cur = [], None
        preamble = []
        section = variant = None
        grade_ctx = None
        for b in blocks:
            if b["type"] == "p":
                pt = plain(b["text"]).strip()
                mv = RE_VARIANT.search(pt)
                if mv and len(pt) < 40:
                    variant, grade_ctx = mv.group(2), [int(mv.group(1))]
                    cur = None
                    continue
                if pt.rstrip(" .") in GRADE_WORDS or pt.split(" ")[0] in GRADE_WORDS and pt.endswith("класс"):
                    grade_ctx = [GRADE_WORDS[pt.split(" ")[0]]]
                    continue
                if SECTION_WORDS.match(pt):
                    section = pt
                    continue
                m = RE_PROBLEM.match(pt)
                mnum = None if has_headings else RE_NUMBERED.match(pt)
                if mnum and not b.get("bold") and not b["text"].startswith("**"):
                    mnum = None
                if m or mnum:
                    label = (m.group(1) if m else mnum.group(1)).replace(" ", "").replace("–", "-")
                    tail = m.group(2) if m else ""
                    cur = {"label": label, "section": section, "variant": variant,
                           "grades": parse_grades(RE_GRADES.search(tail).group(1)) if RE_GRADES.search(tail)
                           else (grade_ctx or self.meta.get("grades")),
                           "ext_numbers": RE_EXTNUM.search(tail).group(1) if RE_EXTNUM.search(tail) else None,
                           "authors": RE_AUTHOR.search(tail).group(1).strip() if RE_AUTHOR.search(tail) else None,
                           "title": None, "max_score": None, "questions": [], "blocks": [], "pages": [b["page"]]}
                    problems.append(cur)
                    if mnum:  # номер и текст в одном абзаце
                        b = {**b, "text": re.sub(r"^\*\*\d{1,2}\.\*\*\s*|^\d{1,2}\.\s*", "", b["text"])}
                    else:
                        continue
                if cur is not None:
                    if not cur["blocks"] and not cur["title"] and b.get("bold") and len(pt) < 80 and not pt.endswith(".") and not RE_SUBQ.match(pt):
                        cur["title"] = pt
                        continue
                    mq = RE_SUBQ.match(pt)
                    if mq and pt[len(mq.group(1))] == ")" and not b["text"].startswith("**"):
                        mq = None  # «1) S» — вариант ответа или пункт условия, а не вопрос
                    if mq:
                        cur["questions"].append({"label": mq.group(1), "block_index": len(cur["blocks"])})
                        b["question"] = mq.group(1)
                    mt = RE_TOTAL.match(pt)
                    if mt:
                        cur["max_score"] = float(mt.group(1).replace(",", "."))
                    mp = RE_POINTS.search(pt)
                    if mp:
                        b["points"] = float(mp.group(1).replace(",", "."))
                    if RE_RUBRIC.match(pt):
                        b["role"] = "rubric-start"
                    ma = RE_ANSWER.match(pt)
                    if ma:
                        b["role"] = "answer"
            if cur is None:
                preamble.append(b)
            else:
                cur["blocks"].append(b)
                if b.get("page") and b["page"] not in cur["pages"]:
                    cur["pages"].append(b["page"])
        for pr in problems:
            self.answer_forms(pr)
        if not problems:
            self.warnings["no-problems-found"] += 1
        return {"parser": PARSER_VERSION, "source": self.meta, "pages": len(self.doc), "preamble": preamble,
                "problems": problems, "assets": self.assets, "stats": dict(self.stats), "warnings": dict(self.warnings)}


def join_hyphen(left, right, words):
    """Склейка строк. «смешива-» + «ющуюся» -> «смешивающуюся»; «брутто-» + «формулу» -> «брутто-формулу»,
    если такое слово с дефисом встречается в документе; «Гелля-» + «Фольгарда» и «1,2-» + «…» — дефис остаётся."""
    lt = left.rstrip()
    if not lt.endswith("-"):
        return left + " " + right
    head = re.search(r"([\w,]+)-$", plain(lt))
    first = re.match(r"[\w]+", plain(right))
    if not head or not first:
        return lt + right
    h, f = head.group(1), first.group(0)
    if f[:1].isupper() or h[-1:].isdigit():
        return lt + right                      # имя собственное или «1,2-»: дефис настоящий
    hyphenated = (h + "-" + f).lower()
    if any(w.startswith(hyphenated[:len(h) + 4]) for w in words if "-" in w):
        return lt + right                      # слово с дефисом есть в документе
    return lt[:-1] + right


def same_band(a, b, gap=16):
    """Куски одной строки схемы: перекрываются по вертикали и стоят рядом по горизонтали."""
    ov = min(a[3], b[3]) - max(a[1], b[1])
    hgap = max(a[0], b[0]) - min(a[2], b[2])
    return ov > 0.5 * min(a[3] - a[1], b[3] - b[1]) and hgap <= gap


# ---------------------------------------------------------------- бланки ответов
RE_OPTION = re.compile(r"^(\d{1,2}|[а-еА-Е])\)\s*(.+)$")
RE_BLANK = re.compile(r"_{5,}")


def _label(text):
    return re.sub(r"[\s–—:=-]+$", "", plain(text)).strip()


def table_form(rows, default_q):
    """Таблица после «Ответ» -> бланк: ячейки-подписи и ячейки-поля {q, k}.

    k — подпись строки (слева) или столбца (сверху); подпись «10.» / «5. Формула …» задаёт номер вопроса."""
    grid = [[c for c in r] for r in rows]
    if not any(c is not None and not c.get("text") and not c.get("asset") for r in grid for c in r):
        return None
    out = []
    for i, r in enumerate(grid):
        row = []
        for j, c in enumerate(r):
            if c is None:
                continue
            span = 1
            while j + span < len(r) and r[j + span] is None:
                span += 1
            cell = {"colspan": span} if span > 1 else {}
            if c.get("text") or c.get("asset"):
                cell.update({"text": c.get("text", "")})
                if c.get("asset"):
                    cell["asset"] = c["asset"]
            else:
                lefts = [_label(r[x]["text"]) for x in range(j) if r[x] and r[x].get("text")]
                top = next((grid[y][j]["text"] for y in range(i - 1, -1, -1) if grid[y][j] and grid[y][j].get("text")), "")
                # полей в столбце несколько — заголовок общий, ключ даёт подпись строки; поле одно — заголовок столбца
                inputs_in_col = sum(1 for y in range(len(grid)) if j < len(grid[y]) and grid[y][j] is not None
                                    and not grid[y][j].get("text") and not grid[y][j].get("asset"))
                q = default_q
                for x, lab in enumerate(lefts):
                    m = re.match(r"^(\d{1,2})[.)]\s*(.*)$", lab)
                    if m:
                        q, lefts[x] = m.group(1), m.group(2)
                lefts = [x for x in lefts if x]
                if top and (inputs_in_col == 1 or not lefts):
                    k = _label(top)
                else:
                    k = lefts[-1] if lefts else None
                cell["input"] = {"q": q, "k": k}
            row.append(cell)
        out.append(row)
    return {"type": "table", "rows": out}


def _option_runs(blocks):
    """Подряд идущие короткие пункты «1) …»/«а) …» (не меньше трёх) — варианты ответа."""
    runs, cur = [], []
    for i, b in enumerate(blocks):
        m = RE_OPTION.match(plain(b.get("text", ""))) if b["type"] == "p" else None
        if m and len(plain(b["text"])) < 70:
            cur.append(i)
        else:
            if len(cur) >= 3:
                runs.append(cur)
            cur = []
    if len(cur) >= 3:
        runs.append(cur)
    return runs


def _answer_forms(self, pr):
    blocks = pr["blocks"]
    has_answers = any(b.get("role") == "answer" for b in blocks)
    q = pr.get("ext_numbers") if pr.get("ext_numbers") and re.fullmatch(r"\d+", pr["ext_numbers"]) else pr["label"]
    out, i = [], 0
    runs = {r[0]: r for r in _option_runs(blocks)} if has_answers else {}
    while i < len(blocks):
        b = blocks[i]
        if b.get("question"):
            q = b["question"]
        if i in runs:  # варианты ответа
            opts = []
            for j in runs[i]:
                m = RE_OPTION.match(plain(blocks[j]["text"]))
                opts.append({"k": m.group(1), "text": re.sub(r"^\s*\**\s*\w{1,2}\)\s*\**\s*", "", blocks[j]["text"])})
            out.append({"type": "choices", "q": q, "options": opts, "page": b.get("page")})
            self.stats["forms_choices"] += 1
            i = runs[i][-1] + 1
            continue
        if b.get("role") == "answer":
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            label = _label(re.sub(r"_+.*$", "", b["text"])) or "Ответ"
            if RE_BLANK.search(b["text"]):
                out.append({"type": "answer", "q": q, "form": {"type": "line", "label": label}, "page": b.get("page")})
                self.stats["forms_line"] += 1
                i += 1
                continue
            if nxt and nxt["type"] == "table":
                form = table_form(nxt["rows"], q)
                if form:
                    out.append({"type": "answer", "q": q, "form": {**form, "label": label}, "page": b.get("page")})
                    self.stats["forms_table"] += 1
                    i += 2
                    continue
            self.warnings["answer-without-form"] += 1
        if b["type"] == "p" and re.fullmatch(r"[_\s]{10,}", b.get("text", "")):  # строки для записи ответа
            n = 1
            while i + n < len(blocks) and blocks[i + n]["type"] == "p" and re.fullmatch(r"[_\s]{10,}", blocks[i + n].get("text", "")):
                n += 1
            out.append({"type": "answer", "q": q, "form": {"type": "lines", "n": n}, "page": b.get("page")})
            self.stats["forms_lines"] += 1
            i += n
            continue
        out.append(b)
        i += 1
    pr["blocks"] = out


Parser.answer_forms = _answer_forms


# ---------------------------------------------------------------- предпросмотр
def render_html(res, markup_html=None):
    def tx(t):
        t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        if markup_html:
            return markup_html(html.unescape(t).replace("<b>", "\x01").replace("</b>", "\x02"), auto_sub=False) \
                .replace("\x01", "<b>").replace("\x02", "</b>")
        t = re.sub(r"_\(([^()]*)\)", r"<sub>\1</sub>", t)
        t = re.sub(r"\^\(([^()]*)\)", r"<sup>\1</sup>", t)
        t = re.sub(r"_([0-9]+)", r"<sub>\1</sub>", t)
        t = re.sub(r"\^([0-9]*[+\-−])", r"<sup>\1</sup>", t)
        return t

    def blocks(bs):
        out = []
        for b in bs:
            if b["type"] == "p":
                cls = " class=eq" if b.get("eq") else ""
                badge = f' <span class=badge>{b["eq"]["status"]}{"" if b["eq"].get("balanced") in (None, True) else " ✗баланс"}</span>' if b.get("eq") else ""
                if b.get("question"):
                    badge += f' <span class=q>вопрос {b["question"]}</span>'
                if b.get("points"):
                    badge += f' <span class=q>{b["points"]} б.</span>'
                out.append(f"<p{cls}>{tx(b['text'])}{badge}</p>")
            elif b["type"] == "figure":
                a = next(a for a in res["assets"] if a["id"] == b["asset"])
                out.append(f"<figure><img src='{a['file']}' style='max-width:{min(100, a['px'][0] / 3.4):.0f}%'>"
                           f"<figcaption>{html.escape(a['kind'])}; подписи: {html.escape(b['labels'][:120])}</figcaption></figure>")
            elif b["type"] == "table":
                rows = []
                for r in b["rows"]:
                    cells = []
                    for c in r:
                        if c is None:
                            continue
                        img = ""
                        if c.get("asset"):
                            a = next(a for a in res["assets"] if a["id"] == c["asset"])
                            img = f"<img src='{a['file']}' style='max-width:160px'>"
                        cells.append(f"<td>{img}{tx(c['text'])}</td>")
                    rows.append("<tr>" + "".join(cells) + "</tr>")
                out.append("<table>" + "".join(rows) + "</table>")
        return "\n".join(out)

    parts = [f"<!doctype html><meta charset=utf-8><title>{html.escape(res['source']['file'])}</title>",
             "<style>body{font:15px/1.45 'Times New Roman',serif;max-width:820px;margin:20px auto;padding:0 16px}"
             "table{border-collapse:collapse;margin:6px 0}td{border:1px solid #999;padding:2px 6px}"
             ".badge{font:11px sans-serif;background:#def;padding:0 4px;border-radius:3px}"
             ".q{font:11px sans-serif;background:#fed;padding:0 4px;border-radius:3px}"
             "h2{font-size:18px;border-top:2px solid #444;padding-top:8px}figure{margin:6px 0}"
             "figcaption{font:11px sans-serif;color:#666}p.eq{background:#f4fbf4}</style>",
             f"<h1>{html.escape(res['source']['file'])}</h1><pre>{html.escape(json.dumps(res['source'], ensure_ascii=False))}\n"
             f"stats={html.escape(json.dumps(res['stats'], ensure_ascii=False))}\nwarnings={html.escape(json.dumps(res['warnings'], ensure_ascii=False))}</pre>"]
    for pr in res["problems"]:
        head = f"Задача {pr['label']}"
        extra = {k: pr[k] for k in ("section", "variant", "grades", "ext_numbers", "authors", "max_score") if pr.get(k)}
        parts.append(f"<h2>{html.escape(head)} {html.escape(pr['title'] or '')}</h2><pre>{html.escape(json.dumps(extra, ensure_ascii=False))}</pre>")
        parts.append(blocks(pr["blocks"]))
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out")
    ap.add_argument("--project")
    a = ap.parse_args()
    pe = load_chem(a.project)
    markup = None
    if a.project:
        try:
            from chem.equation import markup_html as markup
        except Exception:  # noqa: BLE001
            markup = None
    res = Parser(a.pdf, a.out, pe).parse()
    base = os.path.basename(a.pdf)[:-4]
    with open(os.path.join(a.out, base + ".json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, base + ".html"), "w", encoding="utf-8") as f:
        f.write(render_html(res, markup))
    print(json.dumps({"file": base, "problems": len(res["problems"]), "stats": res["stats"],
                      "warnings": res["warnings"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
