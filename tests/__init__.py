"""Пакет автотестов программы «Расписание занятий».

Запуск
------
Из корня проекта (папка с web.py), интерпретатором из .venv:

    .venv\\Scripts\\python -m unittest discover tests                  — весь набор (с браузерными тестами)
    .venv\\Scripts\\python -m unittest discover tests/ui               — только браузерные тесты
    .venv\\Scripts\\python -m unittest tests.test_web_tab_classes      — один модуль
    .venv\\Scripts\\python -m unittest tests.test_web_tab_classes.HoursAndPinsTests.test_pins_validation
                                                                       — один тест

Покрытие src (должно оставаться 100% строк и веток):

    .venv\\Scripts\\python -m coverage run --branch --source=src -m unittest discover tests
    .venv\\Scripts\\python -m coverage report

Прямой запуск файла (``python tests\\test_x.py``) не работает: модулю нужен пакет ``tests``,
а при таком запуске он не находится. Тесты, которым нужен solve.exe, архив
Расписание_2026-27.zip, Playwright или Microsoft Edge, без них пропускаются (skip).

Раскладка
---------
Модули названы по тому, что проверяют:

* ``test_engine_*.py`` — движок solve.exe по его выходу: жёсткие правила (``test_engine_rules``),
  мягкие правила и ходы (``test_engine_soft_rules``), целые программы школы (``test_engine_programs``),
  сколько подбирать и как идёт отжиг — закрепления, ранняя остановка, циклы (``test_engine_annealing``),
  линейка, которая идёт вместе с другим потоком, при составлении потока-копии (``test_engine_joint``),
  смена преподавателя в подборе — ход 4, что он не трогает, совместимость с прежним движком
  (``test_engine_swap``) и отладочная сборка ``-DCHECK_ENERGY``, которую тест собирает сам
  (``test_engine_swap_check``); эталоны прежнего движка — ``fixtures/engine_compat/``;
* ``test_functions_<модуль>.py`` — предметный слой, модуль ``src/modules/functions/<модуль>.py``
  (``test_functions_joint`` — «линейка присоединяется к Потоку N»: отметка, копии, синхронизация);
* ``test_translate.py`` — тексты интерфейса (``src/modules/translate.py``, ru.hjson);
* ``test_web_<модуль>.py`` — сервер, модуль ``src/web/<модуль>.py``; ``test_web_tab_<вкладка>.py`` —
  действия и маршруты вкладки ``src/web/tabs/<вкладка>.py``;
* ``test_launcher.py`` — запуск программы (``web.py``): второй экземпляр и выбор порта;
* ``test_tools_import.py`` — разбор книги расписания скриптом ``tools/import_26_27.py``;
* ``test_structure.py`` и ``test_page_files.py`` — сторожа раскладки сервера и страницы
  (``test_structure.py`` заодно запускает скрипты tools, проверяет их логику и сверяет имена весов);
* ``ui/`` — браузерные тесты страницы (``src/web/static``), см. ``tests/ui/__init__.py``;
  ``ui/test_joint`` — «линейка присоединяется к Потоку N» на всех вкладках, ``ui/test_joint_edges`` —
  её стыки с другими вкладками (общая база обоих — заготовка ``ui/joint_base.py``).

Смена преподавателя в подборе (.spec/teacher-swap/SPEC.md) проверяется там же, где её код: кроме
``test_engine_swap*`` — вход движка (``test_functions_solver_input``), сборка вариантов
(``test_web_build``), поля /variants и принятие (``test_web_tab_preview``), сторож лимита
(``test_functions_variants``), строки «Кто ведёт» в Excel (``test_functions_export``), подсказка
«оставить принятое» (``test_web_tab_run``), контракт и тексты (``test_structure``), страница
(``ui/test_preview``).

Вариант, составленный до начала курса, который уже идёт, — тоже рядом с кодом: поиск таких курсов
(``test_functions_stages``, StaleStartedTests), порядок вариантов и «лучший» (``test_functions_variants``),
накладка внутри этапа после подмены зафиксированных курсов (``test_functions_variants``, StageClashTests),
отказ и вопросы при принятии (``test_web_tab_preview``), этап для новой сборки при помехе-копии
(``test_web_project``, ConflictStagesTests), пометка в Excel (``test_functions_export``), страница
(``ui/test_preview``, StaleStartedVariantTest). Общие заготовки — ``builders.setHours`` и ``builders.stageVariant``.

Уточнения «линейки, которая присоединяется к Потоку N» после проверки — тоже рядом с кодом: помехи общих
уроков из других этапов (``test_functions_joint``, CopyConflictsTests) и поток без единого такого же
предмета (JointDisjointLineTests), зафиксированные курсы варианта из расписания (``test_functions_stages``,
LockedFromAnswerTests), вопрос setJoint (``test_web_tab_classes``, JointQuestionTests), источник, который
идёт только через копию (``test_web_state``, StartedSourceStateTests; ``test_web_tab_classes``,
StartedSourceTests; ``ui/test_joint``), «Кто ведёт» и лимит у зафиксированного курса
(``test_web_tab_preview``, LockedVariantTests).

Новый тест кладётся в модуль того, что он проверяет (отдельных модулей «по кругу проверки» нет).
Допустимые имена модулей тестов перечислены в ``LAYOUT`` (ниже); новый модуль сначала вносится туда.
Сторож — ``test_structure`` (LayoutTests): модуль с другим именем (например, ``test_review5_fixes.py``)
роняет прогон.
Модули тестов друг друга не импортируют — иначе при ``discover tests`` импортированный модуль
загружается второй раз под другим именем; сторож — ``test_structure`` (ImportOrderTests).
Общее для нескольких модулей лежит в заготовках (сами тестов не содержат):
``builders.py`` — данные для предметного слоя, ``engine.py`` — запуск solve.exe и проверка его
выхода, ``real_project.py`` — копия реального проекта 2026/27, запросы к серверу и поддельный
решатель для сборки через сервер (``FakeSolver``),
``fixture_26_27.py`` — проект из реальных данных школы (обёртка над tools/school_26_27.py,
общим для тестов и скриптов tools).

Папка данных
------------
Главное: тесты никогда не трогают настоящую папку проектов пользователя.

Программа хранит проекты в ``<папка данных>/Schedule-Maker-1/projects``, где папка данных —
переменная окружения SCHEDULE_DATA_DIR, а без неё %APPDATA% (см. ``src.variables.getAppDataDir``).
При импорте этого пакета обе переменные указывают на новую временную папку, поэтому все
тестовые проекты и журналы создаются в ней. Папка удаляется после прогона.

Путь вычисляется один раз, при первом импорте ``src.variables``, поэтому пакет ``tests`` должен
быть импортирован раньше ``src``. Для этого каждый модуль тестов начинается со строк

    import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)

    tests.requireIsolation()

Так подмена срабатывает при любом запуске: всего набора (``discover tests``, где модули
импортируются как ``test_web_core``, без пакета) и одного модуля (``tests.test_web_core``).
Правило проверяет tests/test_structure.py (ImportOrderTests).
Вызов ``requireIsolation`` нужен не только для проверки: без него имя ``tests`` в модуле
не использовалось бы, и pyflakes считал бы импорт лишним.
"""

import atexit
import os
import shutil
import sys
import tempfile

# Раскладка модулей тестов (tests/*.py и tests/ui/*.py с именем test*.py): шаблон имени и что может стоять
# на месте «{}» — перечень имён или папка исходников (тогда имя — модуль этой папки). Сторож —
# test_structure (LayoutTests).
LAYOUT = (
    ("test_engine_{}.py", ("annealing", "joint", "programs", "rules", "soft_rules", "swap", "swap_check")),
    ("test_functions_{}.py", "src/modules/functions"),
    ("test_web_tab_{}.py", "src/web/tabs"),
    ("test_web_{}.py", "src/web"),
    ("test_{}.py", ("launcher", "page_files", "structure", "tools_import", "translate")),
    ("ui/test_{}.py", ("classes", "dialogs", "export", "joint", "joint_edges", "layout", "preview", "run", "save",
                       "settings", "start", "tabs", "teachers", "view")),
)

# Если src.variables уже загружен, папка данных уже выбрана — подменять поздно
if "src.variables" in sys.modules:
    raise RuntimeError("tests импортирован после src: тесты писали бы в настоящую папку проектов пользователя")

DATA_DIR = tempfile.mkdtemp(prefix="schedule-tests-")

os.environ["SCHEDULE_DATA_DIR"] = DATA_DIR
os.environ["APPDATA"] = DATA_DIR

# Временная папка удаляется после прогона, чтобы в %TEMP% не копились папки schedule-tests-*
atexit.register(shutil.rmtree, DATA_DIR, ignore_errors=True)


def requireIsolation():
    """Проверяет, что программа (если она уже загружена) хранит данные во временной папке тестов.

    Вызывается в начале каждого модуля тестов сразу после ``import tests``. Ошибка значит,
    что ``src`` успел загрузиться с настоящей папкой пользователя, — тогда тесты не запускаются.
    """
    variables = sys.modules.get("src.variables")

    if variables is not None and not os.path.normpath(variables.PATH_TO_FOLDER).startswith(os.path.normpath(DATA_DIR)):
        raise RuntimeError(f"Папка данных программы не временная: {variables.PATH_TO_FOLDER}")
