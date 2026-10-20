"""Отрисовка задач формата olymp-bundle/1 в HTML: для веб-страницы (поля ввода) и для печати сборника.

Только stdlib и chem/. Когда блок появится на сайте, это переедет в шаблоны и templatetags,
а правила разметки — в chem/ с тестами.
"""
import html
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from chem.equation import equation_html, markup_html, parse_equation  # noqa: E402
from chem.formula import formula_html, normalize_formula  # noqa: E402

PT_TO_MM = 25.4 / 72

# ---------------------------------------------------------------- разметка текста
RE_INLINE = re.compile(r"(\*\*.+?\*\*|\*[^*\s][^*]*?\*|\{[^{}]+\}|\$[^$]+\$)")
# Короткая запись индексов в тексте задач: _2 — только цифры; _C, _Br, _a, _n — одна буква и следующие
# за ней строчные (X_nY -> X<sub>n</sub>Y); ^2+ / ^+ / ^3 — цифры со знаком.
# Всё остальное — в скобках: S_(N)2, t_(1/2), P_(4)O_(10).
RE_SHORT_SUB = re.compile(r"_(\d+|[A-Za-zА-Яа-яЁё][a-zа-яё]*)")
RE_SHORT_SUP = re.compile(r"\^(\d*[+\-−]|\d+)")


def olymp_markup(text):
    """Текст с _2/^2+ -> HTML. В отличие от markup_html, короткая запись не захватывает лишнее: P_2O_5, X_nY."""
    text = RE_SHORT_SUB.sub(r"_(\1)", text)
    text = RE_SHORT_SUP.sub(r"^(\1)", text)
    return markup_html(text, auto_sub=False)


def inline_html(text):
    """**жирный**, *курсив*, {X} — обозначение вещества, $…$ — формула, _( ) ^( ) — индексы."""
    out = []
    for part in RE_INLINE.split(text or ""):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append(f"<b>{inline_html(part[2:-2])}</b>")
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append(f"<i>{inline_html(part[1:-1])}</i>")
        elif part.startswith("{") and part.endswith("}"):
            out.append(f"<b class=ref>{olymp_markup(part[1:-1])}</b>")
        elif part.startswith("$") and part.endswith("$"):
            out.append(math_html(part[1:-1]))
        else:
            out.append(olymp_markup(part))
    return "".join(out)


# ---------------------------------------------------------------- формулы (подмножество TeX)
SYMBOLS = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "Delta": "Δ", "nu": "ν", "omega": "ω", "rho": "ρ",
           "lambda": "λ", "mu": "μ", "pi": "π", "sigma": "σ", "tau": "τ", "chi": "χ", "varphi": "φ", "cdot": "·",
           "times": "×", "approx": "≈", "le": "≤", "ge": "≥", "pm": "±", "to": "→", "infty": "∞"}
FUNCS = {"ln", "lg", "log", "exp", "sin", "cos"}


def _group(s, i):
    """Аргумент команды: {…} или один символ -> (текст, новый индекс)."""
    while i < len(s) and s[i] == " ":
        i += 1
    if i < len(s) and s[i] == "{":
        depth = 0
        for j in range(i, len(s)):
            depth += s[j] == "{"
            depth -= s[j] == "}"
            if depth == 0:
                return s[i + 1:j], j + 1
        raise ValueError("незакрытая {")
    return s[i:i + 1], i + 1


def _closing(s, i, opener):
    """Позиция \\right для \\left, начиная с i."""
    depth = 0
    for m in re.finditer(r"\\(left|right)", s[i:]):
        depth += 1 if m.group(1) == "left" else -1
        if depth < 0:
            return i + m.start()
    raise ValueError(f"нет \\right для \\left{opener}")


def math_html(tex):
    """Минимальный TeX без внешних библиотек: \\frac, индексы, \\left( \\right), \\mathrm/\\text, греческие, функции."""
    out, i = [], 0
    while i < len(tex):
        ch = tex[i]
        if ch == "\\":
            m = re.match(r"\\([A-Za-z]+|.)", tex[i:])
            cmd = m.group(1)
            i += len(m.group(0))
            if cmd == "frac":
                a, i = _group(tex, i)
                b, i = _group(tex, i)
                out.append(f'<span class=frac><span>{math_html(a)}</span><span>{math_html(b)}</span></span>')
            elif cmd == "left":
                opener = tex[i]
                j = _closing(tex, i + 1, opener)
                closer = tex[j + len("\\right")]
                out.append(f'<span class=fence><span class=br>{html.escape(opener)}</span>{math_html(tex[i + 1:j])}'
                           f'<span class=br>{html.escape(closer)}</span></span>')
                i = j + len("\\right") + 1
            elif cmd in ("mathrm", "text"):
                a, i = _group(tex, i)
                out.append(f'<span class=rm>{html.escape(a)}</span>')
            elif cmd in FUNCS:
                out.append(f'<span class=rm>{cmd}</span>')
            elif cmd in SYMBOLS:
                out.append(SYMBOLS[cmd])
            elif cmd in (" ", ","):
                out.append(" ")
            else:
                raise ValueError(f"неизвестная команда \\{cmd}")
        elif ch in "_^":
            a, i = _group(tex, i + 1)
            tag = "sub" if ch == "_" else "sup"
            out.append(f"<{tag}>{math_html(a)}</{tag}>")
        elif ch.isalpha() and ch.isascii():
            out.append(f"<i>{html.escape(ch)}</i>")
            i += 1
        elif ch == "-":
            unary = not tex[:i].strip() or tex[:i].rstrip()[-1] in "([{=,"
            out.append("−" if unary else " − ")   # унарный минус (10^{-24}, (-1)) — без пробелов
            i += 1
        elif ch in "=+":
            out.append(f" {ch} ")
            i += 1
        else:
            out.append(html.escape(ch))
            i += 1
    return f'<span class=math>{"".join(out)}</span>'


# ---------------------------------------------------------------- уравнения
DUMMIES = ["Og", "Ts", "Lv", "Mc", "Nh", "Fl", "Cn", "Ds", "Rg", "Mt"]


def eq_html(text, template=False):
    """Строка реакции -> (html, Equation). В шаблонах {А} временно заменяется редким элементом."""
    subst = {}
    src = text
    if template:
        def put(m):
            d = DUMMIES[len(subst)]
            subst[d] = m.group(1)
            return d
        src = re.sub(r"\{([^{}]+)\}", put, text)
    eq = parse_equation(src)
    h = equation_html(eq)
    for d, label in subst.items():
        h = h.replace(d, f'<b class=ref>{olymp_markup(label)}</b>')
    return h, eq


# ---------------------------------------------------------------- отрисовка задачи
class Renderer:
    """mode: "web" — страница с полями ввода; "print" — сборник для печати (пустые бланки)."""

    def __init__(self, bundle, mode="web", base=""):
        self.b = bundle
        self.mode = mode
        self.base = base
        self.assets = {a["id"]: a for a in bundle.get("assets", [])}
        self.on_error = None   # (место, сообщение) -> None; задаёт проверщик

    def err(self, where, msg):
        if self.on_error:
            self.on_error(where, msg)

    # -- картинки: размер как в оригинале (по рамке в PDF)
    def img(self, aid, where="", max_mm=None):
        if not aid:
            return ""
        a = self.assets.get(aid)
        if a is None:
            self.err(where, f"нет ассета {aid}")
            return ""
        bbox = a.get("src", {}).get("bbox")
        style = ""
        if bbox:
            w = (bbox[2] - bbox[0]) * PT_TO_MM
            if max_mm:
                w = min(w, max_mm)
            style = f' style="width:{w:.1f}mm"'
        return f'<img src="{html.escape(self.base + a["file"])}" alt="{html.escape(a.get("alt", ""))}"{style}>'

    def problem(self, p):
        self.p = p
        self.questions = {q["label"]: q for q in p["questions"]}
        self.options = {}
        num = f"Задача {html.escape(p['number'])}"
        if p.get("ext_numbers"):
            num += f" (№{html.escape(p['ext_numbers'])})"
        meta = []
        if p.get("variant"):
            meta.append(f"вариант {p['variant']}")
        if p.get("section"):
            meta.append(p["section"])
        if p.get("grades") and self.b["contest"]["grades"] != p["grades"]:
            meta.append("для " + ", ".join(map(str, p["grades"])) + " класса" + ("" if len(p["grades"]) == 1 else "ов"))
        head = f'<h3 class=ptitle>{num}</h3>'
        if p.get("title"):
            head += f'<p class=pname>{inline_html(p["title"])}</p>'
        if meta:
            head += f'<p class=pmeta>({html.escape("; ".join(meta))})</p>'
        body = self.blocks(p["statement"]["blocks"], "условие")
        return f'<article class=problem>{head}{body}</article>'

    def solution(self, p):
        self.p = p
        self.questions = {q["label"]: q for q in p["questions"]}
        parts = [self.blocks(p.get("solution", {}).get("blocks", []), "решение")]
        keys = [f"<li>{self.key_html(q)}</li>" for q in p["questions"]]
        parts.append(f'<div class=keys><b>Ответы и баллы</b><ul>{"".join(keys)}</ul></div>')
        return "".join(parts)

    def key_html(self, q):
        a = q["answer"]
        k = a["kind"]
        pts = f' — {q["points"]:g} б.' if q.get("points") is not None else ""
        lab = f"<b>{html.escape(q['label'])}.</b> "
        if k == "choice":
            return lab + ", ".join(html.escape(x) for x in a["key"]) + pts
        if k == "match":
            return lab + ", ".join(f"{html.escape(x)} – {html.escape(y)}" for x, y in a["key"].items()) + pts
        if k == "number":
            return lab + f'{a["value"]:g}'.replace(".", ",") + (f' {html.escape(a["unit"])}' if a.get("unit") else "") + pts
        if k == "fields":
            parts = []
            for f in a["fields"]:
                vals = [formula_html(normalize_formula(v)) if f["type"] in ("formula", "element") else f"{v:g}".replace(".", ",")
                        if isinstance(v, (int, float)) else html.escape(str(v)) for v in f["accept"]]
                parts.append(f'{olymp_markup(f["k"])} – {" или ".join(vals)}')
            return lab + "; ".join(parts) + pts
        if k == "equations":
            return lab + "; ".join(eq_html(e)[0] for e in a["accept"]) + pts
        if k == "structures":
            return lab + "структуры " + ", ".join(a["nodes"]) + " (см. решение)" + pts
        rub = "; ".join(f'{inline_html(r["text"])} – {r["points"]:g}' for r in q.get("rubric", []))
        return lab + (rub or "по критериям") + pts

    def blocks(self, blocks, where):
        return "\n".join(self.block(b, f"{where} блок {i + 1} ({b.get('t')})") for i, b in enumerate(blocks))

    def block(self, b, w):
        t = b.get("t")
        if t == "p":
            return f"<p>{inline_html(b['text'])}</p>"
        if t == "h":
            return f"<h4>{inline_html(b['text'])}</h4>"
        if t == "q":
            sep = b.get("sep", ".")
            return f'<p class=q><b>{html.escape(b["q"])}{html.escape(sep)}</b> {inline_html(b["text"])}</p>'
        if t == "list":
            style = b.get("style", "1)")
            items = []
            for n, x in enumerate(b["items"], b.get("start", 1)):
                mark = f"{n})" if style == "1)" else (f"{'абвгдежзик'[n - 1]})" if style == "а)" else "•")
                body = inline_html(x) if isinstance(x, str) else self.blocks(x["blocks"], w)
                items.append(f"<li><span class=mark>{mark}</span> {body}</li>")
            return f"<ul class=list>{''.join(items)}</ul>"
        if t == "figure":
            cls = " float" if b.get("float") == "right" else ""
            cap = f"<figcaption>{inline_html(b['caption'])}</figcaption>" if b.get("caption") else ""
            return f"<figure class='fig{cls}'>{self.img(b['asset'], w)}{cap}</figure>"
        if t == "table":
            return self.table(b, w)
        if t == "eq":
            return self.eq(b, w)
        if t == "scheme":
            return self.scheme(b, w)
        if t == "math":
            lab = f' <span class=mlabel>{html.escape(b["label"])}</span>' if b.get("label") else ""
            try:
                return f"<p class=display>{math_html(b['tex'])}{lab}</p>"
            except ValueError as e:
                self.err(w, f"формула: {e}")
                return ""
        if t == "choices":
            return self.choices(b, w)
        if t == "match":
            return self.match(b, w)
        if t == "answer":
            return self.answer(b, w)
        if t == "note":
            if b.get("kind") == "review" and self.mode == "print":
                return ""   # заметка для проверяющего, не для участника
            inner = self.blocks(b["blocks"], w) if b.get("blocks") else f"<p>{inline_html(b.get('text', ''))}</p>"
            title = f"<p><b>{inline_html(b['title'])}</b></p>" if b.get("title") else ""
            cls = "review" if b.get("kind") == "review" else "info"
            return f"<div class={cls}>{title}{inner}</div>"
        if t == "raw":
            img = self.img(b.get("asset"), w)
            return f'<div class=raw>{img}<p>Требует доводки ({html.escape(b.get("reason", ""))}): {inline_html(b.get("text", ""))}</p></div>'
        self.err(w, f"неизвестный тип блока {t}")
        return ""

    def table(self, b, w):
        rows = []
        for r in b["rows"]:
            cells = []
            for c in r:
                tag = "th" if c.get("h") else "td"
                span = "".join(f' {k}="{c[k]}"' for k in ("colspan", "rowspan") if c.get(k))
                body = self.img(c.get("asset"), w, 45) + inline_html(c.get("text", ""))
                cells.append(f"<{tag}{span}>{body}</{tag}>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        notes = "".join(f"<p class=tnote>{inline_html(n)}</p>" for n in b.get("notes", []))
        return f"<table class=data>{''.join(rows)}</table>{notes}"

    def eq(self, b, w):
        try:
            h, _ = eq_html(b["text"], b.get("template", False))
        except Exception as e:  # noqa: BLE001
            self.err(w, f"уравнение не разобрано: «{b['text']}»: {e}")
            return f"<p>{html.escape(b['text'])}</p>"
        n = f'<span class=eqn>{html.escape(b["n"])})</span> ' if b.get("n") else ""
        comment = f' <span class=eqc>({inline_html(b["comment"])})</span>' if b.get("comment") and self.mode == "web" else ""
        review = ""
        if b.get("review") and self.mode == "web":
            src = b.get("src", {})
            where = f' (источник: стр. {src["page"]})' if src.get("page") else ""
            review = f'<span class="review eqreview">Ошибка в источнике{where}: {html.escape(b["review"])}</span>'
        return f"<p class=eqline>{n}{h}{comment}</p>{review}"

    def scheme(self, b, w):
        img = self.img(b.get("asset"), w)
        cls = " float" if b.get("float") == "right" else ""
        if self.mode == "print":
            return f"<figure class='fig{cls}'>{img}</figure>"
        nodes = {n["id"]: n for n in b["nodes"]}

        def label(n):
            if "ref" in n:
                return f'<b class=ref>{olymp_markup(n["ref"])}</b>'
            if "f" in n:
                return formula_html(n["f"])
            return html.escape(n.get("text") or n.get("given") or n["id"])
        lines = []
        for e in b["edges"]:
            if e.get("steps"):
                cond = "; ".join(f"{i}) " + ", ".join(inline_html(s[k]) for k in ("above", "below") if s.get(k))
                                 for i, s in enumerate(e["steps"], 1))
            else:
                cond = "; ".join(inline_html(e[k]) for k in ("above", "below") if e.get(k))
            n = f'{e["n"]}) ' if e.get("n") else ""
            lines.append(f'<li>{n}{" + ".join(label(nodes[i]) for i in e["from"])} → '
                         f'{" + ".join(label(nodes[i]) for i in e["to"])}{f" <span class=cond-text>[{cond}]</span>" if cond else ""}</li>')
        return (f"<figure class='fig{cls}'>{img}<details class=ui><summary>Схема текстом</summary>"
                f"<ul class=edges>{''.join(lines)}</ul></details></figure>")

    # -- варианты, соответствие, бланки
    def choices(self, b, w):
        opts = b["options"]
        if b.get("id"):
            self.options[b["id"]] = opts
        q = self.questions.get(b.get("q")) if b.get("q") else None
        if self.mode == "web" and q and q["answer"]["kind"] == "choice":
            typ = "checkbox" if q["answer"].get("multi") else "radio"
            items = "".join(f'<li><label><input type={typ} name="q{html.escape(q["label"])}" value="{html.escape(o["k"])}"> '
                            f'{html.escape(o["k"])}) {inline_html(o["text"])}</label></li>' for o in opts)
            return f"<ul class='choices web'>{items}</ul>"
        items = "".join(f'<li>{html.escape(o["k"])}) {self.img(o.get("asset"), w, 60)}{inline_html(o.get("text", ""))}</li>' for o in opts)
        return f"<ul class=choices>{items}</ul>"

    def match(self, b, w):
        self.options["match:" + b["q"]] = b["right"]

        def cell(o):
            return f'<td class=mk>{html.escape(o["k"])})</td><td>{self.img(o.get("asset"), w, 70)}{inline_html(o.get("text", ""))}</td>'
        rows = []
        for i in range(max(len(b["left"]), len(b["right"]))):
            left = cell(b["left"][i]) if i < len(b["left"]) else "<td></td><td></td>"
            right = cell(b["right"][i]) if i < len(b["right"]) else "<td></td><td></td>"
            rows.append(f"<tr>{left}{right}</tr>")
        return f"<table class=match>{''.join(rows)}</table>"

    def field(self, inp, w):
        """Поле ввода (веб) или пустая клетка (печать) для {q, k}."""
        q = self.questions.get(inp.get("q"))
        if q is None:
            self.err(w, f"поле бланка для неизвестного вопроса {inp.get('q')}")
            return ""
        if self.mode == "print":
            return ""
        a = q["answer"]
        name = f'a_{q["label"]}' + (f'_{inp["k"]}' if inp.get("k") else "")
        k = a["kind"]
        if k == "choice":
            opts = self.options.get(a.get("options")) or []
            typ = "checkbox" if a.get("multi") else "radio"
            return "".join(f'<label class=tog><input type={typ} name="{html.escape(name)}" value="{html.escape(o["k"])}">{html.escape(o["k"])})</label>' for o in opts)
        if k == "match":
            right = self.options.get("match:" + q["label"], [])
            return (f'<select name="{html.escape(name)}"><option></option>'
                    + "".join(f'<option>{html.escape(o["k"])}</option>' for o in right) + "</select>")
        ftype = "number" if k in ("number", "expression") else "text"
        if k == "fields":
            f = next((f for f in a["fields"] if f["k"] == inp.get("k")), None)
            if f is None:
                self.err(w, f"в ключе вопроса {q['label']} нет поля «{inp.get('k')}»")
                return ""
            ftype = f["type"]
        cls = {"formula": "inp formula", "element": "inp short", "number": "inp num"}.get(ftype, "inp")
        mode = ' inputmode="decimal"' if ftype == "number" else ""
        hint = {"formula": "формула", "element": "символ", "number": "число"}.get(ftype, "")
        return f'<input class="{cls}" name="{html.escape(name)}"{mode} placeholder="{hint}" autocomplete="off">'

    @staticmethod
    def column_form(rows):
        """Две строки: сверху только подписи, снизу поля (возможно, с подписью строки в первой клетке)."""
        if len(rows) != 2 or any("input" in c for c in rows[0]):
            return False
        inputs = [c for c in rows[1] if "input" in c]
        return len(inputs) >= 3 and all("input" in c for c in rows[1][len(rows[1]) - len(inputs):])

    def answer(self, b, w):
        f = b["form"]
        typ = f["type"]
        if self.mode == "print" and f.get("print") is False:
            return ""   # бланк только для сайта: в оригинале места для ответа нет
        label = f'<p class=anslabel><b>{inline_html(f.get("label", "Ответ"))}</b></p>' if f.get("label", "Ответ") else ""
        if typ == "table" and self.mode == "web" and self.column_form(f["rows"]):
            # «подписи сверху, поля снизу»: на странице — плитка «подпись — поле», переносится на узком экране
            head, inputs = f["rows"]
            off = len(inputs) - len(head)
            row_label = inline_html(inputs[0].get("text", "")) if off == 0 and "input" not in inputs[0] else ""
            pairs = [(h, c) for h, c in zip(head, inputs) if "input" in c]
            items = "".join(f'<label class=fg><span>{inline_html(h.get("text", ""))}</span>'
                            f'{self.field({"q": b.get("q"), **c["input"]}, w)}</label>' for h, c in pairs)
            cap = f'<p class=hint>{row_label}</p>' if row_label else ""
            return f'<div class=answer>{label}{cap}<div class=fieldgrid>{items}</div></div>'
        if typ == "table":
            rows = []
            for r in f["rows"]:
                cells = []
                for c in r:
                    span = f' colspan="{c["colspan"]}"' if c.get("colspan") else ""
                    if "input" in c:
                        inp = {"q": b.get("q"), **c["input"]}
                        cells.append(f'<td class=cellinp{span}>{self.field(inp, w)}</td>')
                    else:
                        cells.append(f'<td{span}>{self.img(c.get("asset"), w, 40)}{inline_html(c.get("text", ""))}</td>')
                rows.append("<tr>" + "".join(cells) + "</tr>")
            cls = "form cols" if self.column_form(f["rows"]) else "form"
            return f'<div class=answer>{label}<div class=formwrap><table class="{cls}">{"".join(rows)}</table></div></div>'
        if typ == "line":
            q = self.questions.get(b.get("q"))
            if self.mode == "web" and q and q["answer"]["kind"] == "choice" and any(
                    x.get("q") == b.get("q") for x in self.p["statement"]["blocks"] if x.get("t") == "choices"):
                return ""   # на странице ответ выбирается в самом списке вариантов
            inp = self.field({"q": b.get("q"), **f.get("input", {})}, w) if self.mode == "web" else '<span class=blank></span>'
            unit = f' {inline_html(f["unit"])}' if f.get("unit") else ""
            return f'<p class=answer><b>{inline_html(f.get("label", "Ответ."))}</b> {inp}{unit}</p>'
        if typ == "lines":
            if self.mode == "web":
                return f'<div class=answer>{label}<textarea rows="{f["n"]}" name="a_{html.escape(str(b.get("q")))}"></textarea></div>'
            return f'<div class=answer>{label}' + "<div class=rule></div>" * f["n"] + "</div>"
        if typ == "space":
            if self.mode == "web":
                return (f'<div class=answer>{label}<textarea rows="6" name="a_{html.escape(str(b.get("q")))}" '
                        f'placeholder="Решение"></textarea><p class=hint>{inline_html(f.get("note", ""))}</p></div>')
            if f.get("height_mm"):
                return f'<div class="answer space" style="height:{f["height_mm"]}mm">{label}</div>'
            return ""
        if typ == "structures":
            wmm, hmm = f.get("box_mm", [42, 32])
            boxes = []
            for c in f["cells"]:
                inner = ("" if self.mode == "print" else
                         f'<button type=button class=draw disabled title="Редактор структур (OpenChemLib CanvasEditor)">Нарисовать</button>')
                boxes.append(f'<div class=sbox style="width:{wmm}mm;height:{hmm}mm"><b>{olymp_markup(c["k"])}</b>{inner}</div>')
            return f'<div class=answer>{label}<div class=sboxes>{"".join(boxes)}</div></div>'
        if typ == "equations":
            if self.mode == "web":
                rows = "".join(f'<li><input class="inp eqinp" name="a_{html.escape(str(b.get("q")))}_{i}" placeholder="уравнение реакции"></li>'
                               for i in range(1, f["n"] + 1))
                return f'<div class=answer>{label}<ol class=eqs>{rows}</ol></div>'
            return f'<div class=answer>{label}' + "".join(f"<div class=rule><span>{i})</span></div>" for i in range(1, f["n"] + 1)) + "</div>"
        self.err(w, f"неизвестный тип бланка {typ}")
        return ""


CSS = """
:root{--bg:#fff;--fg:#111;--muted:#666;--line:#999;--soft:#f3f4f6;--accent:#2457c5}
@media (prefers-color-scheme:dark){:root:not(.print){--bg:#1b1c1e;--fg:#e8e8e8;--muted:#a0a0a0;--line:#555;--soft:#26282c;--accent:#7aa2ff}}
body{background:var(--bg);color:var(--fg);margin:0}
.page{font:17px/1.45 "Times New Roman",Times,serif;max-width:820px;margin:0 auto;padding:16px}
.problem{margin:28px 0 36px}
.ptitle{font:bold 1.05em "Times New Roman",Times,serif;text-align:center;margin:0 0 4px}
.pname{text-align:center;font-style:italic;margin:0}.pmeta{text-align:center;color:var(--muted);margin:0 0 6px;font-size:.9em}
p{margin:.35em 0;text-align:justify}
.q b,.anslabel b,.answer b{font-weight:bold}
.ref{font-weight:bold}
table{border-collapse:collapse}
table.data,table.form{margin:6px 0}
table.data td,table.data th,table.form td{border:1px solid var(--fg);padding:3px 8px;vertical-align:middle}
table.data th{font-weight:bold}
table.form td{min-width:2.2em;height:2em}
table.form td.cellinp{min-width:4.5em;padding:2px 4px}
.formwrap{max-width:100%;overflow-x:auto}
table.form.cols td{text-align:center}
.fieldgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(7.5em,1fr));gap:6px 10px;max-width:100%}
.fg{display:flex;flex-direction:column;gap:2px}.fg>span{min-height:1.2em}
table.match td{padding:2px 6px;vertical-align:top}.match .mk{font-weight:normal;white-space:nowrap}
.tnote{font-size:.85em}
img{max-width:100%;vertical-align:middle;background:#fff}
figure{margin:6px 0;text-align:center}figure.float{float:right;margin:0 0 6px 12px}
.list,.choices{list-style:none;padding-left:0;margin:.3em 0}.list li,.choices li{margin:.15em 0}
.display{text-align:center}.mlabel{margin-left:2em}
.math i{font-family:"Times New Roman",Times,serif}.rm{font-style:normal}
.frac{display:inline-flex;flex-direction:column;vertical-align:middle;text-align:center;margin:0 .15em;font-size:.95em}
.frac>span:first-child{border-bottom:1px solid currentColor;padding:0 .15em}
.fence{display:inline-flex;align-items:center}.fence>.br{font-size:1.9em;line-height:1;font-weight:200}
.eqline{text-align:left}.eqn{margin-right:.4em}.eqc{color:var(--muted);font-size:.85em}
.eq{display:inline-flex;flex-wrap:wrap;align-items:center;gap:0 .1rem;line-height:1.3}
.term{white-space:nowrap}.note{font-size:.78em;margin-left:.05em}.plus{padding:0 .15rem}
.arrow{display:inline-flex;flex-direction:column;align-items:center;margin:0 .45rem;min-width:2.4em;vertical-align:middle}
.arrow .cond{font-size:.7em;line-height:1.1;min-height:1.1em;white-space:nowrap}.arrow .arrow-sym{font-size:1.3em;line-height:.9}
.info{border:1px solid var(--line);padding:4px 12px;margin:8px 0}
.review{border-left:4px solid #e0a000;background:var(--soft);padding:4px 10px;font-size:.92em}
.eqreview{display:block;margin:2px 0 8px}
.raw{border-left:4px solid #c62828;background:var(--soft);padding:4px 10px}
.answer{margin:8px 0}.anslabel{margin:.2em 0}
.blank{display:inline-block;border-bottom:1px solid var(--fg);width:75mm;height:1em}
.rule{border-bottom:1px solid var(--fg);height:9mm}.rule span{font-size:.9em}
.sboxes{display:flex;flex-wrap:wrap;gap:4mm}.sbox{border:1px solid var(--fg);position:relative;padding:2px 5px;box-sizing:border-box}
.sbox .draw{position:absolute;right:6px;bottom:6px;font:13px sans-serif}
.space{border:1px solid var(--line)}
.hint{color:var(--muted);font-size:.9em}
.inp{font:inherit;border:1px solid var(--line);border-radius:4px;padding:2px 6px;width:100%;box-sizing:border-box;background:var(--bg);color:var(--fg)}
.inp{min-width:3.5em}.inp.short{width:4em}.inp.num{max-width:8em}
textarea{width:100%;font:inherit;box-sizing:border-box}
.tog{display:inline-block;margin:0 .5em .2em 0;white-space:nowrap}
.choices.web label{cursor:pointer}
.keys{border-top:1px solid var(--line);margin-top:8px;padding-top:4px}
.ui>summary{font:13px/1.4 system-ui,sans-serif;color:var(--muted);cursor:pointer}
.edges{text-align:left;font:15px/1.5 "Times New Roman",serif;color:var(--fg)}.cond-text{color:var(--muted)}
.solution{border-left:3px solid var(--line);padding-left:12px;margin-top:10px}
h1,h2{font-family:"Times New Roman",Times,serif}
@media (max-width:600px){figure.float{float:none;margin:6px 0}.page{font-size:16px}}
@media print{.ui{display:none}}
"""

PRINT_CSS = """
@page{size:A4;margin:18mm 18mm 20mm 22mm}
html.print{--fg:#000;--bg:#fff;--line:#000}
.print .page{max-width:none;padding:0;font-size:12pt;line-height:1.35}
.print .problem{margin:0 0 9mm}
.print table.form td{height:9mm;min-width:10mm}
.print table.form td.cellinp{min-width:20mm}
.print .pagebreak{break-before:page}
.print h1{font-size:15pt;text-align:center}.print h2{font-size:13pt;text-align:center}
.print .contest{break-before:page}
"""
