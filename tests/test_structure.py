"""Сторож раскладки сервера: при переносе кода по модулям ничего не потерялось и не запуталось.

* Адреса, методы и имена обработчиков (endpoint) Flask — ровно прежние: забытый импорт
  модуля с маршрутами дал бы 404, переименованная функция — другой endpoint.
* Реестр действий — ровно прежние 35 имён, а список «запрещено во время сборки» — прежние 31:
  забытый модуль вкладки дал бы «что-то пошло не так» на любое его действие.
* Модули src/web импортируют друг друга только «вниз» по слоям из шапки src/web/server.py,
  поэтому циклов импорта нет; build берётся только как модуль; вкладки не импортируют друг друга.
* Модули предметного слоя src/modules/functions тоже импортируют друг друга только «вниз» по слоям
  из шапки src/modules/functions/__init__.py и ничего не берут из src.web.
* Импортов внутри функций нет нигде в src и web.py (кроме перечисленных в LOCAL_IMPORTS с причиной).
* Имена с «_» — внутренние шаги своего модуля: другие модули src и web.py их не импортируют и не
  вызывают (правило — в шапке src/web/server.py; тестам можно).
* Каждый модуль тестов начинается с ``import tests`` и ``tests.requireIsolation()``: так папка
  данных подменяется до импорта src при любом способе запуска (см. tests/__init__.py). Модули
  тестов не импортируют друг друга: общее лежит в заготовках (builders, engine, real_project…).
* Имя каждого модуля тестов есть в раскладке ``tests.LAYOUT``: тесты лежат в модуле того, что
  проверяют, а не в модулях «по кругу проверки» (``test_review4_fixes.py`` и подобных).
* Скрипты tools запускаются (в отдельном процессе) и не импортируют пакет tests; их логика
  (create_school_project.buildAnswer и mayTeachAll, pack_release.isStale) проверяется на данных.
* Имена весов совпадают везде, где они перечислены: шаблон src/files/weights.json, порядок
  ползунков и строки «Предпросмотра» (variants.py) и чтение весов в движке (solve.cpp).
* DATA_CONTRACT.md описывает данные «линейка присоединяется к Потоку N» (AC-38) и «смену преподавателя
  в подборе» (.spec/teacher-swap/SPEC.md, AC-22): ключ входа движка, ход 4, поля /variants, вопрос
  при принятии; шапка solve.cpp описывает ход 4, тексты функции — в ru.hjson, а не на странице.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import ast
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from src.modules.functions.courses import courseName
from src.modules.functions.model import lessonEntries
from src.modules.functions.variants import METRICS, WEIGHT_ORDER
from src.modules.translate import translate
from src.web import actions
from src.web.server import app
from tests.fixture_26_27 import buildSettings, loadFixture
# Скрипты tools — после import tests: папка данных уже подменена; create_school_project сам
# добавляет папку tools в путь импорта для своих import_26_27 и school_26_27
from tools import create_school_project, pack_release

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "src", "web")
FUNCTIONS = os.path.join(ROOT, "src", "modules", "functions")
TESTS = os.path.join(ROOT, "tests")

ROUTES = {
    ("/", ("GET",), "index"),
    ("/static/<path:name>", ("GET",), "static_files"),
    ("/api/i18n", ("GET",), "i18n"),
    ("/api/meta", ("GET",), "meta"),
    ("/api/projects", ("GET",), "projects"),
    ("/api/projects", ("POST",), "createProject"),
    ("/api/projects/import", ("POST",), "importProject"),
    ("/api/project/<project>", ("GET",), "projectState"),
    ("/api/project/<project>", ("DELETE",), "deleteProject"),
    ("/api/project/<project>/open", ("POST",), "openProject"),
    ("/api/project/<project>/action", ("POST",), "doAction"),
    ("/api/project/<project>/teacher", ("GET",), "teacherDetails"),
    ("/api/project/<project>/job", ("GET",), "jobStatus"),
    ("/api/project/<project>/variants", ("GET",), "variants"),
    ("/api/project/<project>/export/<kind>", ("GET",), "export"),
}

ACTION_NAMES = {
    "accept", "copyAvailability", "copyLine", "copyMonday", "cycleAvailability", "cycleCourse", "cyclePair",
    "deleteCourse", "deleteLine", "deletePenalty", "deleteStream", "deleteTeacher", "newCourse", "newLine",
    "newStream", "newTeacher", "newVersion", "rejectVariant", "removeVersion", "resetStage", "restore", "run",
    "savePenalty", "setDates", "setGrid", "setHours", "setJoint", "setLimit", "setNumber", "setPenaltyWeight", "setPins",
    "setTeacher", "setWeight", "stop", "teacherSubjects",
}

BLOCKED = {
    "setGrid", "copyMonday", "newStream", "deleteStream", "setDates", "newLine", "deleteLine", "newCourse", "deleteCourse",
    "copyLine", "setHours", "setTeacher", "setPins", "newTeacher", "teacherSubjects", "deleteTeacher", "cycleCourse",
    "cycleAvailability", "copyAvailability", "resetStage", "accept", "restore", "rejectVariant",
    "setWeight", "setNumber", "savePenalty", "setPenaltyWeight", "deletePenalty", "setLimit", "cyclePair", "setJoint",
}

# Слои (см. шапку src/web/server.py): кому из src.web какие модули можно импортировать.
# Вкладки (tabs.*) — общий список TAB_ALLOWED; server — всем.
TAB_ALLOWED = {"core", "project", "actions", "state", "ranking", "build"}
ALLOWED = {
    "core": set(),
    "project": {"core"},
    "build": {"core", "project"},
    "state": {"core", "project", "build"},
    "ranking": {"core", "project"},
    "actions": {"core", "build", "state"},
    "projects": {"core", "project", "build", "state"},
    "tabs": set(),
}


def webModules():
    """Модули сервера: {"core": путь, …, "tabs.run": путь} (без src/web/__init__.py)."""
    result = {}

    for folder, prefix in ((WEB, ""), (os.path.join(WEB, "tabs"), "tabs.")):
        for name in sorted(os.listdir(folder)):
            if name.endswith(".py"):
                key = prefix + name[:-3] if name != "__init__.py" else prefix.rstrip(".")

                if key:
                    result[key] = os.path.join(folder, name)

    return result


def webImports(path):
    """Что модуль берёт из src.web: [(модуль, как импортирован)]; модуль — "core", "tabs.run" и т. п.

    «Как» — "module" (`from src.web import build`, `import src.web.build`) или "names"
    (`from src.web.build import …`).
    """
    with open(path, encoding="utf-8") as file:
        tree = ast.parse(file.read())

    result = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src.web."):
                    result.append((alias.name[len("src.web."):], "module"))

        elif isinstance(node, ast.ImportFrom) and node.module and (node.module == "src.web" or node.module.startswith("src.web.")):
            base = node.module[len("src.web."):] if node.module != "src.web" else ""

            if base in ("", "tabs"):
                # from src.web import build / from src.web.tabs import run — импорт модулей
                result += [((base + "." if base else "") + alias.name, "module") for alias in node.names]

            else:
                result.append((base, "names"))

    return result


# Слои предметного слоя (см. шапку src/modules/functions/__init__.py): модуль импортирует из
# src.modules.functions только модули с меньшим номером слоя. joint («линейка идёт вместе
# с Потоком N», SPEC Р-2) — над model и courses, под stages: его берут stages и всё, что выше
DOMAIN_LAYERS = {
    "model": 0, "files": 0, "journal": 0,
    "grid": 1, "pairs": 1,
    "courses": 2,
    "joint": 3,
    "stages": 4, "penalties": 4, "school_defaults": 4,
    "solver_input": 5,
    "variants": 6,
    "staffing": 7, "teacher_card": 7, "export": 7, "tree": 7, "versions": 7,
}

# Разрешённые импорты внутри функций: (файл от корня, импортируемый модуль); причина — в комментарии над каждым
LOCAL_IMPORTS = {
    # Второй запуск exe только открывает браузер: серверу незачем загружаться (см. web.main)
    ("web.py", "src.web.server"),
}


def domainImports(path):
    """Модули предметного слоя, которые импортирует файл: ["model", "courses", …]."""
    with open(path, encoding="utf-8") as file:
        tree = ast.parse(file.read())

    prefix = "src.modules.functions"
    result = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result += [alias.name[len(prefix) + 1:] for alias in node.names if alias.name.startswith(prefix + ".")]

        elif isinstance(node, ast.ImportFrom) and node.module == prefix:
            result += [alias.name for alias in node.names]

        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(prefix + "."):
            result.append(node.module[len(prefix) + 1:])

    return result


def sourceFiles():
    """Все модули программы на Python: src/**/*.py (без страницы static/) и web.py — пути от корня."""
    result = ["web.py"]

    for folder, _, names in os.walk(os.path.join(ROOT, "src")):
        result += [os.path.relpath(os.path.join(folder, name), ROOT).replace(os.sep, "/") for name in sorted(names) if name.endswith(".py")]

    return result


def localImports(path):
    """Импорты внутри функций файла: [имя импортируемого модуля]."""
    with open(os.path.join(ROOT, path), encoding="utf-8") as file:
        tree = ast.parse(file.read())

    result = []

    for function in ast.walk(tree):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(function):
                if isinstance(node, ast.Import):
                    result += [alias.name for alias in node.names]

                elif isinstance(node, ast.ImportFrom):
                    result.append(node.module)

    return result


# Пакеты, из которых `from <пакет> import <имя>` берёт модуль (а не функцию)
PACKAGES = {"src", "src.modules", "src.modules.functions", "src.web", "src.web.tabs"}


def privateUses(path):
    """Чужие имена с «_», которые берёт файл: [(откуда, имя)].

    Это `from src.… import _имя` и обращение `модуль._имя`, где модуль — модуль программы,
    взятый импортом (`from src.web import build` → `build._SOLVER_JOB`). Служебные имена вида
    `__имя__` не считаются.
    """
    with open(os.path.join(ROOT, path), encoding="utf-8") as file:
        tree = ast.parse(file.read())

    modules = set()
    result = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "src":
            result += [(node.module, alias.name) for alias in node.names if alias.name.startswith("_")]
            modules |= {alias.asname or alias.name for alias in node.names if node.module in PACKAGES}

        elif isinstance(node, ast.Import):
            modules |= {alias.asname or alias.name for alias in node.names if alias.name.split(".")[0] == "src"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("_") and not node.attr.startswith("__"):
            base = ast.unparse(node.value)

            if base in modules or base.startswith("src."):
                result.append((base, node.attr))

    return result


class StructureTests(unittest.TestCase):
    """Маршруты и действия сервера после любой перестановки кода остаются прежними, слои — чистыми."""

    def test_routes_unchanged(self):
        """Набор (адрес, методы, endpoint) в app.url_map ровно равен снимку."""
        routes = {
            (rule.rule, tuple(sorted(rule.methods - {"HEAD", "OPTIONS"})), rule.endpoint)
            for rule in app.url_map.iter_rules()
        }

        self.assertEqual(routes, ROUTES)

    def test_actions_unchanged(self):
        """Реестр действий — 35 имён (прежние 34 и setJoint — «линейка присоединяется к Потоку N», AC-38);
        «запрещено во время сборки» — 31 из них: setJoint меняет курсы и расписание, поэтому тоже запрещён.

        Во время сборки запрещено всё, что меняет курсы, преподавателей, сетку, расписание и то, что сборка
        взяла в работу (веса, правила, тщательность и число вариантов, лимит, пары); разрешены только версии,
        запуск (он сам отвечает «идёт сборка») и остановка. Новое действие придётся вписать в ACTION_NAMES и явно решить, входит ли
        оно в BLOCKED; имена в BLOCKED — только существующие действия (опечатка молча сняла бы запрет).
        """
        self.assertEqual(set(actions.ACTIONS), ACTION_NAMES)
        self.assertEqual(set(actions.BLOCKED_WHILE_RUNNING), BLOCKED)
        self.assertLessEqual(BLOCKED, ACTION_NAMES)

    def test_teacher_swap_adds_no_actions(self):
        """AC-14 («Смена преподавателя в подборе»): нового действия нет — действий по-прежнему 35,
        «ведёт» ставит завуч прежними действиями (setTeacher, cycleCourse), принятие — прежнее accept.
        """
        self.assertEqual(len(actions.ACTIONS), 35)
        self.assertEqual(len(ACTION_NAMES), 35)
        self.assertLessEqual({"accept", "setTeacher", "cycleCourse"}, set(actions.ACTIONS))

    def test_import_layers(self):
        """Каждый модуль src/web импортирует из src.web только разрешённое его слою."""
        modules = webModules()
        self.assertIn("server", modules)
        self.assertIn("tabs.run", modules)

        for key, path in modules.items():
            if key == "server":
                continue

            allowed = TAB_ALLOWED if key.startswith("tabs.") else ALLOWED[key]

            for target, _ in webImports(path):
                self.assertIn(target, allowed, f"{key} импортирует {target}")

    def test_build_only_as_module(self):
        """build нигде не импортируется по именам (`from src.web.build import …`)."""
        for key, path in webModules().items():
            self.assertNotIn(("build", "names"), webImports(path), key)

    def test_nobody_imports_server_or_other_tabs(self):
        """server не импортирует никто из src/web; вкладки не импортируют вкладки."""
        for key, path in webModules().items():
            targets = [target for target, _ in webImports(path)]
            self.assertNotIn("server", targets, key)

            if key.startswith("tabs"):
                self.assertFalse([target for target in targets if target.startswith("tabs")], key)


class DomainLayerTests(unittest.TestCase):
    """Предметный слой: импорт только вниз по слоям, без src.web и без импортов внутри функций."""
    def domainModules(self):
        """Модули предметного слоя: {имя: путь} (без __init__.py)."""
        return {name[:-3]: os.path.join(FUNCTIONS, name) for name in os.listdir(FUNCTIONS) if name.endswith(".py") and name != "__init__.py"}

    def test_every_module_has_a_layer(self):
        """У каждого модуля есть слой в DOMAIN_LAYERS, и каждый упомянут в шапке пакета."""
        modules = self.domainModules()
        self.assertEqual(set(modules), set(DOMAIN_LAYERS))

        with open(os.path.join(FUNCTIONS, "__init__.py"), encoding="utf-8") as file:
            header = file.read()

        for name in modules:
            self.assertIn(f"{name}.py", header, name)

    def test_imports_go_down(self):
        """Модуль импортирует из предметного слоя только модули нижних слоёв — циклов нет."""
        for name, path in self.domainModules().items():
            for target in domainImports(path):
                self.assertLess(DOMAIN_LAYERS[target], DOMAIN_LAYERS[name], f"{name} импортирует {target}")

    def test_domain_does_not_import_web(self):
        """Предметный слой ничего не знает о сервере: импортов src.web и flask в нём нет."""
        for name, path in self.domainModules().items():
            with open(path, encoding="utf-8") as file:
                tree = ast.parse(file.read())

            modules = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            modules += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]

            self.assertFalse([module for module in modules if module.startswith(("src.web", "flask"))], name)

    def test_no_imports_inside_functions(self):
        """Импорты стоят в начале модулей: внутри функций — только перечисленные в LOCAL_IMPORTS."""
        files = sourceFiles()
        self.assertIn("src/modules/functions/variants.py", files)

        for path in files:
            for module in localImports(path):
                self.assertIn((path, module), LOCAL_IMPORTS, path)


class PrivateNameTests(unittest.TestCase):
    """Правило имён с «_» (шапка src/web/server.py): внутреннее одного модуля не берут другие."""
    def test_private_names_stay_inside_their_module(self):
        """Ни один модуль src и web.py не берёт чужие «_»-имена; проверка их видит (в тестах они есть)."""
        for path in sourceFiles():
            self.assertEqual(privateUses(path), [], path)

        self.assertIn(("build", "_SOLVER_JOB"), privateUses("tests/test_web_build.py"))


def inLayout(path, layout=tests.LAYOUT):
    """Модуль тестов ``path`` (путь от папки tests через «/», например ``ui/test_joint.py``) подходит
    под шаблон раскладки ``layout``: на месте «{}» — имя из перечня или модуль папки исходников.
    """
    for pattern, names in layout:
        prefix, suffix = pattern.split("{}")

        if not (path.startswith(prefix) and path.endswith(suffix)) or len(path) <= len(prefix) + len(suffix):
            continue

        name = path[len(prefix):-len(suffix)]

        if isinstance(names, str):
            if "/" not in name and name != "__init__" and os.path.isfile(os.path.join(ROOT, names, f"{name}.py")):
                return True
        elif name in names:
            return True

    return False


class LayoutTests(unittest.TestCase):
    """Модули тестов названы по тому, что проверяют (tests.LAYOUT, см. tests/__init__.py)."""
    def test_every_test_module_is_in_layout(self):
        """Каждый test*.py в tests и во всех её подпапках (``discover`` заходит в любую подпапку-пакет)
        подходит под ``tests.LAYOUT``: модуль в новой папке (например, ``review5/test_x.py``) тоже роняет прогон."""
        found = sorted(
            os.path.relpath(os.path.join(folder, name), TESTS).replace(os.sep, "/")
            for folder, dirs, files in os.walk(TESTS) if "__pycache__" not in folder
            for name in files if name.startswith("test") and name.endswith(".py")
        )

        self.assertEqual([path for path in found if not inLayout(path)], [])
        self.assertTrue({"test_web_tab_classes.py", "test_structure.py", "ui/test_joint.py"} <= set(found))

    def test_layout_names_are_used(self):
        """Перечни в ``tests.LAYOUT`` не устарели: у каждого имени из перечня есть свой модуль."""
        for pattern, names in tests.LAYOUT:
            if not isinstance(names, str):
                for name in names:
                    self.assertTrue(os.path.isfile(os.path.join(TESTS, *pattern.format(name).split("/"))), pattern.format(name))

    def test_round_modules_are_rejected(self):
        """Модуль «по кругу проверки» или с выдуманным модулем исходников под раскладку не подходит."""
        for path in ("test_review4_fixes.py", "test_review5_joint.py", "ui/test_review4_page.py", "test_functions_review4.py",
                     "test_web_review4.py", "test_web_tab_review4.py", "test_engine_review4.py", "test_functions_.py",
                     "test_functions___init__.py", "test_web_tabs/classes.py", "ui/test_classes_fixes.py", "test_classes.py"):
            self.assertFalse(inLayout(path), path)

        for path in ("test_functions_joint.py", "test_web_state.py", "test_web_tab_preview.py", "test_engine_swap_check.py",
                     "test_translate.py", "ui/test_joint_edges.py"):
            self.assertTrue(inLayout(path), path)


class ImportOrderTests(unittest.TestCase):
    """Модули тестов подменяют папку данных раньше, чем загрузится src."""
    def modules(self):
        """Все модули тестов (tests/**/*.py, кроме __init__.py): (путь от корня, разобранный текст)."""
        for folder, _, names in os.walk(TESTS):
            for name in sorted(names):
                if name.endswith(".py") and name != "__init__.py":
                    path = os.path.join(folder, name)

                    with open(path, encoding="utf-8") as file:
                        yield os.path.relpath(path, ROOT), ast.parse(file.read())

    def test_every_module_starts_with_import_tests(self):
        """Первые операторы после шапки — ``import tests`` и ``tests.requireIsolation()``."""
        paths = set()

        for path, tree in self.modules():
            body = tree.body[1:] if ast.get_docstring(tree) is not None else tree.body
            paths.add(path.replace(os.sep, "/"))

            self.assertEqual([ast.unparse(node) for node in body[:2]], ["import tests", "tests.requireIsolation()"], path)

        # Проверка видит и обычные, и браузерные тесты, и общие заготовки
        self.assertTrue({"tests/test_web_tab_classes.py", "tests/real_project.py", "tests/ui/base.py", "tests/ui/test_start.py"} <= paths)

    def test_test_modules_do_not_import_each_other(self):
        """Модуль тестов не импортирует другой модуль тестов (``test_*``), только общие заготовки.

        Иначе при ``discover tests`` импортированный модуль загружается второй раз под другим именем
        (``tests.test_x`` рядом с ``test_x``): его классы-тесты видны дважды, а состояние модуля
        (например, словари заданий сборки) раздваивается. Общее для нескольких модулей кладётся
        в заготовки (builders.py, engine.py, real_project.py), см. tests/__init__.py.
        """
        for path, tree in self.modules():
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or ""] + [f"{node.module}.{alias.name}" for alias in node.names]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    continue

                # Последняя часть имени: «tests.test_web_build» и «test_web_build» — один и тот же модуль
                imported = [name.rsplit(".", 1)[-1] for name in names]
                self.assertFalse([name for name in imported if name.startswith("test_")], path)


class ToolsTests(unittest.TestCase):
    """Скрипты tools работают: ошибку импорта в них обычный тест не поймал бы.

    Внутри процесса тестов пакет tests уже импортирован раньше src, и путь импорта другой,
    поэтому скрипты проверяются запуском в отдельном процессе — так же, как их запускает
    человек из корня проекта. Папка данных у процесса — новая временная папка внутри папки
    тестов (SCHEDULE_DATA_DIR), так что настоящие проекты пользователя не затрагиваются.
    """
    def runPython(self, *args):
        """Запускает интерпретатор тестов из корня проекта с временной папкой данных.

        Возвращает (результат subprocess.run, папка данных этого запуска).
        """
        folder = tempfile.mkdtemp(dir=tests.DATA_DIR)
        env = dict(os.environ, SCHEDULE_DATA_DIR=folder, APPDATA=folder, PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True, timeout=120)

        return result, folder

    def test_create_test_project_runs(self):
        """`tools/create_test_project.py Дымок` завершается без ошибки и пишет settings.json и weights.json
        в папку проекта внутри временной папки данных."""
        result, folder = self.runPython(os.path.join("tools", "create_test_project.py"), "Дымок")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))

        project = os.path.join(folder, "Schedule-Maker-1", "projects", "Дымок")

        for name in ("settings.json", "weights.json"):
            self.assertTrue(os.path.isfile(os.path.join(project, name)), name)

    def test_tools_modules_import(self):
        """Все модули tools импортируются так, как их видят скрипты (папка tools в пути импорта).

        Без выгрузки .xlsx create_school_project.py запустить нельзя, но импорт проверяет его
        зависимости: import_26_27 (openpyxl), school_26_27 и функции src, которые он берёт.
        """
        names = sorted(name[:-3] for name in os.listdir(os.path.join(ROOT, "tools")) if name.endswith(".py"))
        self.assertIn("create_school_project", names)

        code = "import sys; sys.path.insert(0, 'tools'); " + "; ".join(f"import {name}" for name in names)
        result, _ = self.runPython("-c", code)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))

    def test_tools_do_not_import_tests(self):
        """Ни один скрипт tools не импортирует пакет tests: тот подменил бы папку данных на временную
        (и удалил бы её при выходе), и созданный скриптом проект сразу пропал бы."""
        folder = os.path.join(ROOT, "tools")

        for name in sorted(os.listdir(folder)):
            if not name.endswith(".py"):
                continue

            with open(os.path.join(folder, name), encoding="utf-8") as file:
                tree = ast.parse(file.read())

            modules = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            modules += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]

            self.assertFalse([module for module in modules if module.split(".")[0] == "tests"], name)


class ToolsLogicTests(unittest.TestCase):
    """Логика скриптов tools на данных, без запуска самих скриптов.

    * ``create_school_project.buildAnswer`` на выгрузке 26/27 (tests/fixtures/school_26_27.json):
      курсы Потока 2, которые урок в урок повторяют Поток 1, не ставятся (на это опирается
      .spec/joint-lines/SPEC.md: в проекте 2026/27 у «ЕГЭ основной» Потока 2 уроков нет);
    * ``create_school_project.mayTeachAll``: «может вести» все курсы своего предмета, «ведёт» не меняется;
    * ``pack_release.isStale``: файла в сборке нет, он отличается или совпадает с исходником.

    Модули tools импортируются как ``tools.…`` уже после ``import tests`` (папка данных подменена);
    create_school_project сам добавляет папку tools в путь импорта для своих ``import_26_27``
    и ``school_26_27``.
    """
    def test_build_answer_drops_stream_copies_of_stream_1(self):
        """buildAnswer: ровно 12 предупреждений «копия потока 1», и каждый такой курс Потока 2 убран
        из расписания, а курс Потока 1 с той же линейкой и предметом остаётся и совпадает с ним урок
        в урок (дни, уроки и учителя — как сравнивает сам buildAnswer). Остальные курсы на месте,
        и ни у одного курса уроков не больше, чем ``hours``.
        """
        data = loadFixture()
        answer, notes = create_school_project.buildAnswer(data)

        def lessons(week):
            """Уроки недели (день, урок, учителя) по порядку — как ``lessons`` внутри buildAnswer."""
            return sorted((day, lesson, tuple(cell["teachers"])) for day, lesson, cell in lessonEntries({"x": week}, "x"))

        # Уроки каждого курса из таблицы, ещё до того как buildAnswer убрал копии: по ним
        # проверяется, что убранный курс Потока 2 действительно повторял курс Потока 1.
        # Как в buildAnswer: не больше hours первых слотов, у урока — только первый учитель курса
        # (у курса без учителя — никого)
        full = {}

        for item in data["courses"]:
            course = courseName(item["stream"], item["line"], item["subject"])
            full.setdefault(course, set()).update((day, lesson, tuple(item["teachers"][:1])) for day, lesson in item["slots"][:item["hours"]])

        copies = [note for note in notes if "копия потока 1" in note]
        self.assertEqual(len(copies), 12)

        removed = set(full) - set(answer)
        self.assertEqual(len(removed), 12)

        for course in removed:
            item = next(item for item in data["courses"] if courseName(item["stream"], item["line"], item["subject"]) == course)
            first = courseName(1, item["line"], item["subject"])

            self.assertEqual(item["stream"], 2, course)
            self.assertTrue(any(note.startswith(f"{course}:") for note in copies), course)
            self.assertIn(first, answer, course)
            self.assertEqual(sorted(full[course]), lessons(answer[first]), course)

        for item in data["courses"]:
            course = courseName(item["stream"], item["line"], item["subject"])

            if course in answer:
                self.assertLessEqual(len(lessons(answer[course])), item["hours"], course)

    def test_may_teach_all_keeps_assigned(self):
        """mayTeachAll: у каждого учителя в «может вести» (classes) — все курсы его предмета, «ведёт»
        (assigned) не меняется, повторный вызов ничего не добавляет (повторов нет)."""
        settings = copy.deepcopy(buildSettings())
        before = copy.deepcopy(settings)
        create_school_project.mayTeachAll(settings)

        courses = {}

        for group in settings["classes"]["custom_groups"]:
            for subject in group.get("subjects", []):
                courses.setdefault(subject, set()).add(group["name"])

        for name, teacher in settings["teachers"].items():
            for entry, old in zip(teacher["subjects"], before["teachers"][name]["subjects"]):
                self.assertEqual(entry["assigned"], old["assigned"], name)
                self.assertEqual(set(entry["classes"]), set(old["classes"]) | courses.get(entry["subject"], set()), name)
                self.assertEqual(len(entry["classes"]), len(set(entry["classes"])), name)

        self.assertNotEqual(settings, before)

        once = copy.deepcopy(settings)
        create_school_project.mayTeachAll(settings)
        self.assertEqual(settings, once)

    def test_is_stale(self):
        """isStale: файла в папке сборки нет — устарел; копия изменена — устарел; точная копия — нет.

        Папка сборки — временная папка внутри папки данных тестов, настоящая dist не трогается.
        """
        path = "src/files/bundles/ru.hjson"
        inside = tempfile.mkdtemp(dir=tests.DATA_DIR)
        built = os.path.join(inside, path)

        self.assertTrue(pack_release.isStale(path, inside))

        os.makedirs(os.path.dirname(built))
        shutil.copy(os.path.join(ROOT, path), built)
        self.assertFalse(pack_release.isStale(path, inside))

        with open(built, "ab") as file:
            file.write(b"\n")

        self.assertTrue(pack_release.isStale(path, inside))


class WeightNamesTests(unittest.TestCase):
    """Имена весов одни и те же в шаблоне weights.json, в variants.py и в движке.

    Новый вес, вписанный не везде, иначе молча не работал бы: движок не прочитал бы его из файла,
    на «Запуске» не было бы ползунка или в «Предпросмотре» — строки.
    """
    def setUp(self):
        with open(os.path.join(ROOT, "src", "files", "weights.json"), encoding="utf-8") as file:
            self.weights = set(json.load(file))

        self.assertTrue(self.weights)

    def test_weight_order(self):
        """Порядок ползунков «Что важно в расписании» — ровно имена из weights.json, без повторов."""
        self.assertEqual(set(WEIGHT_ORDER), self.weights)
        self.assertEqual(len(WEIGHT_ORDER), len(self.weights))

    def test_preview_metrics(self):
        """Строки «Предпросмотра», входящие в итог, ссылаются ровно на веса из weights.json."""
        self.assertEqual({weight for _, weight in METRICS if weight}, self.weights)

    def test_engine_reads_every_weight(self):
        """Weights::init в solve.cpp читает из файла весов ровно те же имена."""
        with open(os.path.join(ROOT, "src", "modules", "solve.cpp"), encoding="utf-8") as file:
            cpp = file.read()

        body = re.search(r"static void init\(const json& data\) \{(.*?)\n    \}", cpp, re.S)
        self.assertIsNotNone(body)
        self.assertEqual(set(re.findall(r'data\.value\("([^"]+)"', body.group(1))), self.weights)


class DataContractTests(unittest.TestCase):
    """DATA_CONTRACT.md описывает всё, что видят другие части программы и другие версии."""
    def test_joint_lines_are_described(self):
        """AC-38: в DATA_CONTRACT.md описаны поле курса ``together_with``, ``courseInfo.joint`` и ``jointWith``,
        ``sections.joint`` и ``jointOptions``, действие ``setJoint``, вид занятости ``"joint"`` в карточке
        преподавателя и причина ``joint_waiting`` в «Предпросмотре».
        """
        with open(os.path.join(ROOT, "DATA_CONTRACT.md"), encoding="utf-8") as file:
            contract = file.read()

        for word in ("`together_with`", "`setJoint`", "`jointOptions`", "`jointWith`", "`joint_waiting`", '`"joint"`'):
            self.assertTrue(word in contract, f"в DATA_CONTRACT.md нет {word}")

    @staticmethod
    def section(text, heading):
        """Раздел markdown-текста ``text`` от заголовка, который начинается с ``heading`` («### 6.2.»),
        до следующего заголовка того же или более высокого уровня; нет заголовка — пустая строка.
        """
        level = len(heading) - len(heading.lstrip("#"))
        lines = text.splitlines()
        start = next((index for index, line in enumerate(lines) if line.startswith(heading)), None)

        if start is None:
            return ""

        end = next((index for index in range(start + 1, len(lines))
                    if re.match(r"#{1,%d} " % level, lines[index])), len(lines))

        return "\n".join(lines[start:end])

    def test_teacher_swap_is_described(self):
        """AC-22: DATA_CONTRACT.md описывает «смену преподавателя в подборе»: §6.2 — ключ входа
        ``keep_teacher_courses``; §6.4 — смена преподавателя (ход 4) в описании отжига и в N строки «Готово»;
        §7.6 — поля ``teachers``, ``teacherChanges`` и ``teacherCourses``; §4 — вопрос о смене преподавателя
        при принятии варианта.
        """
        with open(os.path.join(ROOT, "DATA_CONTRACT.md"), encoding="utf-8") as file:
            contract = file.read()

        swap = re.compile(r"смен\w*\s+преподавател", re.I)
        sections = {heading: self.section(contract, heading) for heading in ("## 4.", "### 6.2.", "### 6.4.", "### 7.6.")}

        for heading, text in sections.items():
            self.assertTrue(text, f"в DATA_CONTRACT.md нет раздела {heading}")

        self.assertTrue("`keep_teacher_courses`" in sections["### 6.2."], "в §6.2 нет ключа `keep_teacher_courses`")
        self.assertTrue(swap.search(sections["### 6.4."]), "в §6.4 нет смены преподавателя (ход 4)")

        for word in ("`teachers`", "`teacherChanges`", "`teacherCourses`"):
            self.assertTrue(word in sections["### 7.6."], f"в §7.6 нет {word}")

        self.assertTrue("confirm_teacher" in sections["## 4."] or swap.search(sections["## 4."]), "в §4 нет вопроса о смене преподавателя")

    def test_engine_header_describes_teacher_swap(self):
        """AC-22: шапка-карта solve.cpp (комментарий до первого #include) описывает ход 4 — смену преподавателя."""
        with open(os.path.join(ROOT, "src", "modules", "solve.cpp"), encoding="utf-8") as file:
            header = file.read().split("#include", 1)[0]

        self.assertTrue(re.search(r"смен\w*\s+преподавател", header, re.I), "в шапке solve.cpp нет смены преподавателя (ход 4)")

    def test_teacher_swap_texts(self):
        """AC-22: тексты «смены преподавателя» — в ru.hjson (``translate`` возвращает не сам ключ), а на странице
        «Предпросмотра» (tabs/preview.js) строк по-русски нет: кириллица только в комментариях.
        """
        keys = ("web.preview.teachers_head", "web.preview.teacher_now", "web.preview.teacher_changes", "web.preview.teacher_new",
                "web.preview.confirm_teacher", "web.preview.confirm_teacher_joint", "web.preview.confirm_over_limit")

        self.assertEqual([key for key in keys if translate(key) == key], [])

        with open(os.path.join(WEB, "static", "tabs", "preview.js"), encoding="utf-8") as file:
            code = re.sub(r"/\*.*?\*/", "", file.read(), flags=re.S)

        lines = [line for line in code.splitlines() if re.search("[А-Яа-яЁё]", re.sub(r"(^|\s)//.*$", "", line))]
        self.assertEqual(lines, [])
