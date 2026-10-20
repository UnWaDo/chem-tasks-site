"""Проверка образцов олимпиадных задач (docs/olympiad/samples/*.json) на соответствие схеме.

Без Django и сторонних библиотек, использует только ядро chem/ и render.py:
  - структура пакета: известные типы блоков, ссылки на ассеты, вопросы, узлы схем, бланки ответов;
  - разметка: парные **…**, скобки в _(…) и ^(…), «подозрительные» индексы в готовом HTML (буквы с цифрами);
  - уравнения: разбор parse_equation и проверка баланса, шаблоны с {А};
  - ключи ответов: эталонный ответ даёт полный балл, неверный — меньше;
  - у каждого вопроса с автопроверкой есть поле в бланке; сумма баллов против max_score.
Пишет docs/olympiad/samples/preview.html (страница с полями ввода) и print.html (сборник для печати).

Запуск из корня проекта: python tools/olympiad/check_samples.py
"""
import collections
import glob
import html
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from render import CSS, PRINT_CSS, ROOT, Renderer, eq_html  # noqa: E402

from chem.equation import parse_equation  # noqa: E402
from chem.formula import FormulaError, normalize_formula, parse_formula  # noqa: E402
from chem.grading import grade as grade_equation  # noqa: E402

SAMPLES = os.path.join(ROOT, "docs", "olympiad", "samples")

BLOCKS = {"p", "h", "list", "figure", "table", "eq", "scheme", "math", "choices", "match", "answer", "q", "note", "raw"}
ANSWER_KINDS = {"choice", "match", "fields", "number", "equations", "expression", "structures", "manual"}
AUTO_KINDS = ANSWER_KINDS - {"structures", "manual"}
FIELD_TYPES = {"formula", "element", "number", "text"}
FORM_TYPES = {"table", "line", "lines", "space", "structures", "equations"}
STAGES = {"school", "municipal", "regional", "final", "invitational", "other"}

log = []


def report(level, where, msg):
    log.append((level, where, msg))


# ---------------------------------------------------------------- разметка
def check_markup(text, where):
    if text.count("**") % 2:
        report("ошибка", where, f"непарные ** в «{text[:60]}»")
    for m in re.finditer(r"[_^]\(", text):
        depth = 0
        for ch in text[m.end() - 1:]:
            depth += ch == "("
            depth -= ch == ")"
            if depth == 0:
                break
        if depth:
            report("ошибка", where, f"незакрытая скобка после {m.group(0)} в «{text[:60]}»")


RE_INDEX = re.compile(r"<(sub|sup)>([^<]*)</\1>")


def check_indices(html_text, where):
    """Индекс, где цифры соседствуют с буквами или тире («2O», «1−X») или за строчной идёт заглавная («nY»),
    — почти всегда ошибка разметки."""
    for m in RE_INDEX.finditer(html_text):
        s = html.unescape(m.group(2))
        if re.search(r"\d[A-Za-zА-Яа-я]|[A-Za-zА-Яа-я]\d|\d\s*[−–]\s*[A-Za-zА-Яа-я]|[a-zа-яё][A-ZА-ЯЁ]", s):
            ctx = html.unescape(re.sub(r"<[^>]+>", "", html_text[max(0, m.start() - 60):m.end() + 30]))
            report("ошибка", where, f"подозрительный индекс <{m.group(1)}>{s}</{m.group(1)}> в «…{ctx.strip()}…»")


# ---------------------------------------------------------------- проверки блоков
def walk(blocks):
    for b in blocks:
        yield b
        if b.get("t") == "note" and b.get("blocks"):
            yield from walk(b["blocks"])
        if b.get("t") == "list":
            for x in b["items"]:
                if isinstance(x, dict):
                    yield from walk(x["blocks"])


def check_blocks(blocks, ctx, where, stats):
    for i, b in enumerate(walk(blocks)):
        w = f"{where} блок {i + 1} ({b.get('t')})"
        t = b.get("t")
        if t not in BLOCKS:
            report("ошибка", w, f"неизвестный тип блока {t}")
            continue
        stats["blocks"] += 1
        for key in ("text", "title", "caption"):
            if isinstance(b.get(key), str):
                check_markup(b[key], w)
        if t in ("q", "answer") and b.get("q") not in ctx["questions"]:
            report("ошибка", w, f"вопрос {b.get('q')} не описан в questions")
        if t == "q":
            ctx["mentioned"].add(b["q"])
        if t == "choices":
            if b.get("q"):
                ctx["inputs"][b["q"]].add(None)
                ctx["options"]["q:" + b["q"]] = [o["k"] for o in b["options"]]
            if b.get("id"):
                ctx["options"][b["id"]] = [o["k"] for o in b["options"]]
        if t == "match":
            ctx["options"]["match:" + b["q"]] = ([o["k"] for o in b["left"]], [o["k"] for o in b["right"]])
        if t == "answer":
            check_form(b, ctx, w, stats)
        if t == "eq":
            check_eq(b, w, stats)
        if t == "scheme":
            check_scheme(b, w)
        if t == "raw":
            stats["raw_blocks"] += 1
            report("предупр.", w, f"неразобранный фрагмент: {b.get('reason')}")


def check_form(b, ctx, w, stats):
    f = b.get("form") or {}
    if f.get("type") not in FORM_TYPES:
        report("ошибка", w, f"неизвестный тип бланка {f.get('type')}")
        return
    stats[f"form_{f['type']}"] += 1
    q = b.get("q")
    ctx["mentioned"].add(q)
    if f["type"] == "table":
        for row in f["rows"]:
            for c in row:
                if "input" in c:
                    qq = c["input"].get("q", q)
                    if qq not in ctx["questions"]:
                        report("ошибка", w, f"поле бланка ссылается на неизвестный вопрос {qq}")
                    ctx["mentioned"].add(qq)
                    ctx["inputs"][qq].add(c["input"].get("k"))
                else:
                    check_markup(c.get("text", ""), w)
    elif f["type"] == "structures":
        for c in f["cells"]:
            ctx["inputs"][q].add(c["k"])
    else:
        ctx["inputs"][q].add(None)


def check_eq(b, w, stats):
    text = b["text"]
    template = b.get("template", False)
    if not template and "{" in text:
        report("ошибка", w, f"в уравнении есть {{…}}, но нет template: true: {text}")
    try:
        _, eq = eq_html(text, template)
    except Exception as e:  # noqa: BLE001
        report("ошибка", w, f"уравнение не разобрано: «{text}»: {e}")
        stats["eq_failed"] += 1
        return
    stats["eq_template" if template else "eq_ok"] += 1
    if template:
        return
    an = eq.analyze()
    if an.balanced:
        stats["eq_balanced"] += 1
        if b.get("review"):
            report("ошибка", w, f"отмечено review, но уравнение уравнено: «{text}»")
        return
    diff = ", ".join(f"{k}: {v:+d}" for k, v in an.imbalance.items())
    if b.get("review"):
        report("найдено", w, f"не уравнено, как и в источнике: «{text}» ({diff})")
        stats["eq_source_errors"] += 1
    else:
        report("ошибка", w, f"не уравнено: «{text}» ({diff})")


def check_scheme(b, w):
    nodes = {n["id"]: n for n in b["nodes"]}
    if len(nodes) != len(b["nodes"]):
        report("ошибка", w, "повторяющиеся id узлов схемы")
    for n in b["nodes"]:
        for f in n.get("answer", []):
            try:
                parse_formula(f)
            except FormulaError as e:
                report("ошибка", w, f"узел {n['id']}: ответ «{f}» не разбирается: {e}")
    for e in b["edges"]:
        for side in ("from", "to", "reagent_nodes"):
            for nid in e.get(side, []):
                if nid not in nodes:
                    report("ошибка", w, f"стрелка ссылается на несуществующий узел {nid}")
        texts = [e.get("above", ""), e.get("below", "")] + [s.get(k, "") for s in e.get("steps", []) for k in ("above", "below")]
        for txt in texts:
            check_markup(txt, w)
            for ref in re.findall(r"\{([^{}]+)\}", txt):
                if ref not in nodes:
                    report("ошибка", w, f"условие ссылается на несуществующий узел {{{ref}}}")


# ---------------------------------------------------------------- автопроверка
def safe_eval(expr, variables):
    """Выражение из ключа: только числа, переменные и exp/ln/sqrt."""
    if not re.fullmatch(r"[\d\s.+\-*/()A-Za-z_,]*", expr):
        raise ValueError("недопустимые символы в выражении")
    names = set(re.findall(r"[A-Za-z_]+", expr)) - {"exp", "ln", "sqrt", "log10"}
    if names - set(variables):
        raise ValueError(f"неизвестные имена {names - set(variables)}")
    env = {"exp": math.exp, "ln": math.log, "sqrt": math.sqrt, "log10": math.log10, **variables}
    return eval(expr, {"__builtins__": {}}, env)  # noqa: S307 — выражение проверено регуляркой выше


def num_ok(value, accept, tol=None, tol_rel=None):
    for a in accept:
        if tol is not None and abs(value - a) <= tol:
            return True
        if tol_rel is not None and abs(value - a) <= abs(a) * tol_rel:
            return True
        if tol is None and tol_rel is None and value == a:
            return True
    return False


def grade_answer(spec, resp, points):
    """Балл за ответ resp по ключу spec. None — проверяет учитель."""
    k = spec["kind"]
    if k == "choice":
        key, got = set(spec["key"]), set(resp)
        sc = spec.get("scoring")
        if sc:
            return max(sc.get("min", 0), sc["per_correct"] * len(got & key) + sc["per_wrong"] * len(got - key))
        return points if got == key else 0
    if k == "match":
        per = spec.get("scoring", {}).get("per_item", points / len(spec["key"]))
        return per * sum(resp.get(a) == b for a, b in spec["key"].items())
    if k == "number":
        try:
            v = float(str(resp).replace(",", "."))
        except ValueError:
            return 0
        if spec.get("integer") and v != int(v):
            return 0
        return points if num_ok(v, [spec["value"]], spec.get("tol"), spec.get("tol_rel")) else 0
    if k == "fields":
        total = 0
        for f in spec["fields"]:
            got = resp.get(f["k"], "")
            pts = f.get("points", points / len(spec["fields"]))
            if f["type"] in ("formula", "element"):
                ok = normalize_formula(got) in {normalize_formula(a) for a in f["accept"]}
            elif f["type"] == "number":
                try:
                    ok = num_ok(float(str(got).replace(",", ".")), f["accept"], f.get("tol"), f.get("tol_rel"))
                except ValueError:
                    ok = False
            else:
                ok = got.strip().lower() in {a.lower() for a in f["accept"]}
            total += pts if ok else 0
        return total
    if k == "equations":
        refs = []
        for text in spec["accept"]:
            eq = parse_equation(text)
            refs.append(({t.formula.text: t.coef or 1 for t in eq.left}, {t.formula.text: t.coef or 1 for t in eq.right}))
        total = 0
        for text in resp:
            eq = parse_equation(text)
            ans = {"L": [{"c": str(t.coef or ""), "f": t.formula.text} for t in eq.left],
                   "R": [{"c": str(t.coef or ""), "f": t.formula.text} for t in eq.right]}
            total += spec["per_item"] * grade_equation(ans, refs).score
        return total
    if k == "expression":
        variables = {i["k"]: resp[i["k"]] for i in spec["inputs"]}
        for i in spec["inputs"]:
            lo, hi = i["range"]
            if not lo <= variables[i["k"]] <= hi:
                return 0
        expected = safe_eval(spec["expr"], variables)
        return points if num_ok(float(resp[spec["output"]["k"]]), [expected], tol_rel=spec.get("tol_rel", 0.02)) else 0
    return None


def ideal_and_wrong(spec, ctx, q):
    """Эталонный и заведомо неверный ответы по ключу — для самопроверки ключа."""
    k = spec["kind"]
    if k == "choice":
        opts = ctx["options"].get(spec.get("options")) or ctx["options"].get("q:" + q, [])
        return list(spec["key"]), [o for o in opts if o not in spec["key"]][:2]
    if k == "match":
        _, rights = ctx["options"]["match:" + q]
        wrong = dict(spec["key"])
        first = next(iter(wrong))
        wrong[first] = next(r for r in rights if r != wrong[first])
        return dict(spec["key"]), wrong
    if k == "number":
        return str(spec["value"]).replace(".", ","), str(spec["value"] + 1000)
    if k == "fields":
        return ({f["k"]: str(f["accept"][-1]) for f in spec["fields"]},
                {f["k"]: ("H2O" if f["type"] != "number" else "1") for f in spec["fields"]})
    if k == "equations":
        stripped = [re.sub(r"(^|\s)\d+(?=[A-Z(\[])", r"\g<1>", e) for e in spec["accept"]]  # без коэффициентов
        return list(spec["accept"]), stripped
    if k == "expression":
        i = spec["inputs"][0]
        t = (i["range"][0] + i["range"][1]) // 2
        v = safe_eval(spec["expr"], {i["k"]: t})
        return {i["k"]: t, spec["output"]["k"]: round(v, 1)}, {i["k"]: t, spec["output"]["k"]: round(v * 2, 1)}
    return None, None


def check_questions(p, ctx, where, stats):
    total = 0
    implicit_ok = len(p["questions"]) == 1
    for q in p["questions"]:
        w = f"{where} вопрос {q['label']}"
        spec = q["answer"]
        if spec["kind"] not in ANSWER_KINDS:
            report("ошибка", w, f"неизвестный вид ответа {spec['kind']}")
            continue
        pts = q.get("points", 0)
        total += pts
        if q["label"] not in ctx["mentioned"] and not (implicit_ok and q["label"] == p["number"]):
            report("предупр.", w, "вопрос не упомянут в условии (нет блока q/answer)")
        if spec["kind"] in AUTO_KINDS and not ctx["inputs"].get(q["label"]):
            report("ошибка", w, "у вопроса с автопроверкой нет поля в бланке ответа")
        if spec["kind"] in ("fields", "structures"):
            keys = {f["k"] for f in spec["fields"]} if spec["kind"] == "fields" else set(spec["nodes"])
            got = ctx["inputs"].get(q["label"], set())
            if got and got != keys:
                report("ошибка", w, f"поля бланка {sorted(map(str, got))} не совпадают с ключом {sorted(keys)}")
        if q.get("rubric"):
            rs = sum(r["points"] for r in q["rubric"])
            if abs(rs - pts) > 1e-9:
                report("предупр.", w, f"сумма критериев {rs:g} ≠ баллу вопроса {pts:g}")
        if spec["kind"] == "fields":
            for f in spec["fields"]:
                if f["type"] not in FIELD_TYPES:
                    report("ошибка", w, f"неизвестный тип поля {f['type']}")
                if f["type"] in ("formula", "element"):
                    for a in f["accept"]:
                        try:
                            parse_formula(a)
                        except FormulaError as e:
                            report("ошибка", w, f"ключ «{a}» не разбирается: {e}")
            fp = sum(f.get("points", 0) for f in spec["fields"])
            if fp and abs(fp - pts) > 1e-9:
                report("предупр.", w, f"сумма баллов полей {fp:g} ≠ {pts:g}")
        ideal, wrong = ideal_and_wrong(spec, ctx, q["label"])
        if ideal is None:
            stats["q_manual"] += 1
            continue
        try:
            got_ideal = grade_answer(spec, ideal, pts)
            got_wrong = grade_answer(spec, wrong, pts)
        except Exception as e:  # noqa: BLE001
            report("ошибка", w, f"автопроверка не выполнилась: {e}")
            continue
        if abs(got_ideal - pts) > 1e-9:
            report("ошибка", w, f"эталонный ответ получил {got_ideal:g} из {pts:g}")
        elif got_wrong >= pts:
            report("ошибка", w, "неверный ответ получил полный балл")
        else:
            stats["q_auto_ok"] += 1
    if p.get("max_score") is not None and abs(total - p["max_score"]) > 1e-9:
        report("инфо" if p.get("truncated") else "предупр.", where, f"сумма баллов вопросов {total:g} ≠ max_score {p['max_score']:g}")


# ---------------------------------------------------------------- пакет
STAGE_RU = {"school": "Школьный этап", "municipal": "Муниципальный этап", "regional": "Региональный этап",
            "final": "Заключительный этап", "invitational": "Пригласительный этап", "other": "Этап"}
TOUR_RU = {"theory": "теоретический тур", "practice": "практический тур", "theory1": "I теоретический тур",
           "theory2": "II теоретический тур"}


def contest_title(c):
    parts = [STAGE_RU[c["stage"]]]
    if c.get("region"):
        parts.append(c["region"])
    if c.get("tour"):
        parts.append(TOUR_RU.get(c["tour"], c["tour"]))
    g = c["grades"]
    parts.append(f"{g[0]} класс" if len(g) == 1 else f"{g[0]}–{g[-1]} классы")
    return f"{c['season']}. " + ", ".join(parts)


def check_bundle(path, stats, pages):
    with open(path, encoding="utf-8") as f:
        b = json.load(f)
    name = os.path.basename(path)
    if b.get("format") != "olymp-bundle/1":
        report("ошибка", name, "неизвестный формат")
    c = b["contest"]
    if c["stage"] not in STAGES:
        report("ошибка", name, f"неизвестный этап {c['stage']}")
    sources = {s["id"] for s in b.get("sources", [])}
    for a in b.get("assets", []):
        if a.get("src", {}).get("source") not in sources:
            report("ошибка", name, f"ассет {a['id']} ссылается на неизвестный источник")
        if not os.path.exists(os.path.join(SAMPLES, a["file"])):
            report("ошибка", name, f"нет файла {a['file']}")
    web, prn = Renderer(b, "web"), Renderer(b, "print")
    for r in (web, prn):
        r.on_error = lambda where, msg: report("ошибка", where, msg)
    title = html.escape(contest_title(c))
    web_parts = [f"<h2>{title}</h2><p class=hint>{html.escape(name)}</p>"]
    prn_tasks, prn_sol = [f"<h2>{title}</h2>"], [f"<h2>{title}</h2>"]
    for p in b["problems"]:
        stats["problems"] += 1
        where = f"{name} задача {p['number']}{' вар. ' + p['variant'] if p.get('variant') else ''}"
        ctx = {"questions": {q["label"]: q for q in p["questions"]}, "mentioned": set(),
               "inputs": collections.defaultdict(set), "options": {}}
        if not set(p["grades"]) <= set(c["grades"]):
            report("ошибка", where, "классы задачи не входят в классы тура")
        check_blocks(p["statement"]["blocks"], ctx, where + " условие", stats)
        check_blocks(p.get("solution", {}).get("blocks", []), ctx, where + " решение", stats)
        check_questions(p, ctx, where, stats)
        w_html = web.problem(p)
        sol = web.solution(p)
        check_indices(w_html + sol, where)
        web_parts.append(w_html + f"<details class=ui><summary>Ответы и решение</summary><div class=solution>{sol}</div></details>")
        prn_tasks.append(prn.problem(p))
        variant = f" (вариант {html.escape(p['variant'])})" if p.get("variant") else ""
        prn_sol.append(f"<article class=problem><h3 class=ptitle>Задача {html.escape(p['number'])}{variant}</h3>{prn.solution(p)}</article>")
    pages["web"].append("<section>" + "\n".join(web_parts) + "</section>")
    pages["print"].append("<section class=contest>" + "\n".join(prn_tasks) + "</section>")
    pages["print_sol"].append("\n".join(prn_sol))


def page(title, body, printing=False):
    cls = ' class="print"' if printing else ""
    return (f"<!doctype html><html lang=ru{cls}><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
            f"<style>{CSS}{PRINT_CSS if printing else ''}</style></head><body><div class=page>{body}</div></body></html>")


def main():
    stats = collections.Counter()
    pages = {"web": [], "print": [], "print_sol": []}
    for path in sorted(glob.glob(os.path.join(SAMPLES, "*.json"))):
        check_bundle(path, stats, pages)
    head = "<h1>Олимпиада по химии: образцы задач</h1>"
    with open(os.path.join(SAMPLES, "preview.html"), "w", encoding="utf-8") as f:
        f.write(page("Образцы задач", head + "\n".join(pages["web"])))
    with open(os.path.join(SAMPLES, "print.html"), "w", encoding="utf-8") as f:
        f.write(page("Сборник задач", head + "\n".join(pages["print"])
                     + "<div class=pagebreak><h1>Ответы и решения</h1>" + "\n".join(pages["print_sol"]) + "</div>", True))
    sys.stdout.reconfigure(encoding="utf-8")
    for level, where, msg in log:
        print(f"[{level}] {where}: {msg}")
    print("\nИтого:", dict(sorted(stats.items())))
    errors = sum(1 for lvl, *_ in log if lvl == "ошибка")
    print(f"Ошибок: {errors}, предупреждений: {sum(1 for lvl, *_ in log if lvl == 'предупр.')}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
