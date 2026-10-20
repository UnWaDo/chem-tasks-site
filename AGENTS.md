# AGENTS.md

Инструкции для ИИ-агентов, работающих с этим репозиторием. Описание для людей — в [README.md](README.md).

## О проекте

Сайт для учеников, где они дополняют уравнения химических реакций. Учитель загружает реакции текстом,
собирает из них задания и настраивает, что показывать. Ученики дописывают вещества и коэффициенты,
сайт проверяет ответы автоматически, есть апелляции и перепроверка.

- Python 3.10+ (локально 3.11), Django 5.2, PostgreSQL 16 (psycopg 3), WhiteNoise. Других зависимостей нет — не добавляйте их без необходимости.
- На фронтенде Django-шаблоны и чистый JS/CSS без сборки. Внешние CDN, шрифты и библиотеки запрещены: сайт должен работать в школьной сети с ограничениями.
- Хостинг — недорогой VPS (1 vCPU / 1–2 ГБ RAM, Linux, gunicorn + nginx + PostgreSQL на том же сервере). Не добавляйте ничего, что требует Redis, Celery или фоновых процессов.
- Весь интерфейс, сообщения и комментарии в коде — на русском.

## Команды

Разработка ведётся на Windows, виртуальное окружение лежит в `.venv`, PostgreSQL — в Docker.

```bash
docker compose up -d                                           # локальная база (контейнер tasks-site-postgres-1)
.venv/Scripts/python manage.py test chem.tests assignments     # все тесты (~5 с, нужна запущенная база)
python -m unittest chem.tests                                  # только ядро, без Django (быстро)
.venv/Scripts/python manage.py makemigrations accounts reactions assignments
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py check
.venv/Scripts/python manage.py demo_data                       # демо-данные, только локально
```

- В Git Bash для вывода кириллицы и символов `→` ставьте `PYTHONUTF8=1` (или `PYTHONIOENCODING=utf-8`), иначе будет `UnicodeEncodeError` (cp1251); для `dumpdata -o` — обязательно `PYTHONUTF8=1`.
- Подключайтесь к базе по `127.0.0.1`, не `localhost`: на Windows `localhost` сначала пробует IPv6 и соединение висит ~2 минуты.
- В Docker на этой машине есть и чужие контейнеры (например, `analyst-agent-*`) — не трогайте их.
- Dev-сервер описан в `.claude/launch.json` (порт 8765, `--noreload`): после изменений Python-кода его нужно перезапустить. Порт 8000 занят Docker.
- Логины и пароли демо-данных — в начале `accounts/management/commands/demo_data.py`. Не повторяйте их в чатах и документации.
- Проверка настроек для продакшена: `DJANGO_DEBUG=0 DJANGO_SECRET_KEY=... manage.py check --deploy`.

## Структура

```
chem/                 чистый Python без Django: разбор формул и уравнений, уравнивание, проверка ответов
  formula.py          parse_formula, normalize_formula, formula_html; заряды, гидраты, эвристики Fe3+/SO42-
  equation.py         parse_equation/parse_lines, Equation.analyze(), signature (дубликаты), *_html,
                      markup_html — разметка индексов _(…)/^(…) в условиях и пояснениях
  balance.py          баланс и подбор коэффициентов (дроби, ядро матрицы, перебор при dim > 1)
  grading.py          grade(answer, references) -> GradeResult (correct / partial / wrong / empty)
  tests.py            unittest для ядра
accounts/             классы (StudentGroup), ученики (Student ↔ User), генерация логинов и паролей
reactions/            Reaction + Component + Tag, импорт с предпросмотром, правка, тэги (tags.py); templatetags/chem_tags.py
assignments/
  models.py           Assignment, AssignmentItem, Submission, Answer, Appeal
  logic.py            item_view (что видит ученик), answer_form, проверка и перепроверка, find_ambiguities
  render.py           preview_html, answer_html
  views_teacher.py    страницы учителя (/t/...)
  views_student.py    страницы ученика (/s/...)
  tests.py            сквозные тесты всего сценария
config/               settings.py (читает .env), urls.py — все маршруты в одном файле
templates/            base.html, teacher/, student/, registration/
static/               css/site.css, js/site.js (общее + formulaHtml), answer.js, builder.js, symbols.js
deploy/               systemd, nginx, backup.sh, update.sh
docs/olympiad/        проект блока олимпиадных задач (README.md); samples/ — образцы, только локально, не в Git
tools/olympiad/       офлайн-инструменты для олимпиадного блока: render.py, check_samples.py, parse_pdf.py (PyMuPDF)
.claude/launch.json   dev-сервер Django (8765) и статический сервер образцов олимпиад (8790)
```

## Ключевые инварианты

- Учитель — это `user.is_staff` (`accounts.utils.is_teacher`). Представления учителя оборачиваются в `@teacher_required`, ученика — в `@login_required`, а доступ к заданию проверяется по классу ученика (`_get_assignment`).
- Вещество в реакции хранится нормализованной формулой: `Component.formula` = `parse_formula(...).text`, например `SO4^2-` или `CuSO4·5H2O`. Ответы ученика сравниваются через `normalize_formula`. Пояснения (`note`) и знаки `↑↓` (`mark`) в проверке ответа не участвуют.
- Ключ дубликата — `reaction_signature`: порядок веществ не важен, пояснения и условия важны, знаки `↑↓` и коэффициенты не учитываются. Хранится в `Reaction.signature`. При изменении правил нормализации пересчитайте сигнатуры существующих реакций (миграцией данных).
- `Reaction.set_equation()` пересоздаёт все `Component`. Поэтому настройки показа отдельных веществ (`AssignmentItem.overrides`) привязаны к ключу `"L:формула"` / `"R:формула"` (`Component.key`), а не к id.
- Видимость вещества считается только в `logic.item_view`, в таком порядке приоритета: ручная настройка вещества → «прятать воду» → настройка стороны (пункт задания → задание). Настройки пункта со значением `None` означают «как в задании» (`AssignmentItem.effective`).
- Перепроверка (`regrade_assignment`, `grade_submission`) пересчитывает только `auto_score`, ручная оценка `manual_score` всегда сохраняется. Итог работы — сумма `Answer.score`.
- Допустимые ответы пункта: эталонная реакция + `AssignmentItem.alternatives`. Отклонённые варианты (`dismissed`) больше не показываются в проверке неоднозначностей. Публикация (`_publish`) запрещена, пока есть нерассмотренные варианты.
- Пароли учеников нигде не хранятся в открытом виде. Сгенерированные пароли показываются один раз: их кладут в сессию и перенаправляют на `group_credentials`, который их забирает. Сохраняйте эту схему (POST → redirect → GET), чтобы обновление страницы не создавало учеников повторно.
- Формат ответа (`Answer.data`): `{"L": [{"t": "fixed|slot|extra", "f": "...", "c": "..."}], "R": [...]}`. Поля формы называются `a_<item>_<L|R>_<idx>_<f|c|t>`. Входные данные ограничивает `clean_answer`.
- JS-функция `formulaHtml` в `static/js/site.js` — упрощённая копия `chem.formula.formula_html`. Ею `answer.js` рисует уравнение под строкой ввода (`.eq-render`). Меняя правила отображения, правьте обе.
- Условия и пояснения хранятся как введены, с разметкой `_(…)` / `^(…)`; в HTML их превращает только `markup_html` (фильтр `|markup` в шаблонах). Сигнатуры дубликатов разметку не разбирают.
- База PostgreSQL создаётся с локалью ICU `ru-RU` (см. `docker-compose.yml` и README): на ней `icontains`, `iexact`, `Lower()` и сортировка правильно работают с кириллицей. Не обходите это сравнением в Python.
- Настройки базы — переменные `POSTGRES_*` в `.env`; значения по умолчанию в `settings.py` совпадают с `docker-compose.yml` и годятся только для локальной разработки. `DJANGO_LEGACY_SQLITE` подключает старую базу SQLite как `legacy` — только для переноса данных.
- Градус в подписях всегда выводится символом «°»: `canonical_degrees` превращает `^o`, `^(o)`, `^\circ` в «°» и при отображении, и в сигнатурах дубликатов.
- `builder.js` повторяет логику `logic.item_view` и `render.preview_html` для живой строки «Ученик видит»; меняя правила видимости, правьте все три места.
- Пользовательский текст в HTML, который собирается в Python (`term_html`, `markup_html`, `formula_html`), обязательно экранируется. Коэффициенты и формулы от учеников — недоверенные данные.

## Как вносить изменения

- Логику разбора и проверки держите в `chem/` без импорта Django и покрывайте тестами в `chem/tests.py`. Новое поведение сайта покрывайте тестом в `assignments/tests.py`.
- После изменения моделей создайте миграцию и закоммитьте её вместе с кодом.
- Стиль кода: как в соседних файлах. Комментарии короткие и по-русски, docstring у неочевидных функций, без лишних абстракций.
- CSS: используйте переменные из `:root` (есть тёмная тема через `prefers-color-scheme`), вёрстка должна работать на телефоне от 375 px. Кнопки добавления и удаления вещества (`button.add` / `button.rm`) оформлены в одном стиле — сохраняйте это.
- В текстах интерфейса и сообщениях не указывайте пол ученика: не «он», «согласен(на)», «переведён(а)». Перестраивайте фразу нейтрально («Не согласны с оценкой?», «перевод выполнен»).
- Репозиторий публичный: https://github.com/UnWaDo/chem-tasks-site (ветка `main`). Тексты, решения и рисунки олимпиадных
  задач (`docs/olympiad/samples/`) в Git не попадают — правообладатели запрещают публикацию; не добавляйте их и не
  копируйте фрагменты задач в код, тесты и документацию.
- `tools/olympiad/` на сервер не ставится; PyMuPDF (`parse_pdf.py`, лицензия AGPL) в `requirements.txt` не добавляйте.
- Не запускайте `demo_data` и не меняйте `.env` на сервере. Секреты не коммитьте (`.env`, `db.sqlite3`, `backups/` и выгрузки `dumpdata` в `.gitignore`).
- Изменения формата загрузки реакций или функциональности для учителя отражайте в `README.md` и в подсказке на странице импорта (`templates/teacher/reaction_import.html`).
