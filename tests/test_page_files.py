"""Сторож раскладки страницы: скрипты src/web/static/*.js и tabs/*.js подключены правильно.

Сборщика и ES-модулей нет: index.html подключает обычные <script> по порядку, и все файлы
делят одну глобальную область (правила — в шапке src/web/static/core.js). Ошибки такой
раскладки Python-тесты иначе не заметили бы, а в браузере они роняют страницу целиком:

* список и порядок <script> в index.html — ровно прежние, каждый адрес отдаётся сервером,
  а лишних или забытых .js в папке нет;
* каждый файл начинается с "use strict"; (строгий режим действует на один скрипт),
  окончания строк — CRLF, без BOM;
* имя верхнего уровня объявлено ровно в одном файле (повторный let/const — SyntaxError,
  и файл не загрузится);
* верхнеуровневый let присваивается только в своём файле; кеши и черновики вкладок
  сбрасываются по событиям HOOKS из core.js (afterAction, projectClosed), а не вызовами из ядра;
* общие файлы (ядро, блоки интерфейса, предметная область, оболочка, стартовый экран, запуск)
  не зовут функции вкладок: зависимость только «вкладка → общее»; о событиях (например,
  «проект открыт» — HOOKS.projectOpened) вкладки узнают по подписке.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
import re
import unittest

from src.web.server import app

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "web", "static")

# Точный порядок загрузки: ядро → блоки интерфейса → предметная область → оболочка →
# стартовый экран → вкладки → запуск страницы (app.js — последним)
SCRIPTS = [
    "/static/core.js",
    "/static/ui.js",
    "/static/domain.js",
    "/static/shell.js",
    "/static/projects.js",
    "/static/tabs/settings.js",
    "/static/tabs/classes.js",
    "/static/tabs/teachers.js",
    "/static/tabs/run.js",
    "/static/tabs/preview.js",
    "/static/tabs/view.js",
    "/static/tabs/save.js",
    "/static/tabs/export.js",
    "/static/app.js",
]

# Объявление верхнего уровня: с начала строки, без отступа
DECLARATION = re.compile(r"^(?:async )?function (\w+)|^(?:const|let) (\w+)", re.M)
TOP_LET = re.compile(r"^let (\w+)", re.M)


# Общие файлы страницы: всё, что не вкладка
SHARED = [address for address in SCRIPTS if not address.startswith("/static/tabs/")]


def read(address):
    """Содержимое скрипта по адресу /static/… как байты."""
    with open(os.path.join(STATIC, *address.removeprefix("/static/").split("/")), "rb") as file:
        return file.read()


def code(text):
    """Текст скрипта без комментариев: шапки и пояснения не считаются присваиваниями."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", " ", text)


def names(text):
    """Текст скрипта, где остались только обращения к именам: без строк в кавычках и без ключей
    объектов. Иначе иконка "download" или ключ `download:` в ICONS сошли бы за вызов функции
    download из вкладки «Экспорт».
    """
    text = re.sub(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`', '""', text)
    return re.sub(r"(?m)([{,]|^)(\s*)[\w$]+\s*:(?!:)", r"\1\2", text)


class PageFilesTests(unittest.TestCase):
    def setUp(self):
        self.texts = {address: read(address).decode("utf-8") for address in SCRIPTS}

    def test_script_order(self):
        """index.html подключает ровно эти скрипты в этом порядке; встроенный скрипт темы не в счёт."""
        with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as file:
            html = re.sub(r"<!--.*?-->", "", file.read(), flags=re.S)

        self.assertEqual(re.findall(r'<script\s+src="([^"]+)"\s*>\s*</script>', html), SCRIPTS)
        # Только классические синхронные скрипты: defer, async и модули меняют порядок и область имён
        self.assertNotRegex(html, r"<script[^>]*\b(defer|async|type=)")

    def test_scripts_are_served(self):
        """Каждый скрипт отдаётся сервером (подпапка tabs/ — тем же маршрутом /static/…)."""
        client = app.test_client()

        for address in SCRIPTS:
            response = client.get(address)
            self.assertEqual(response.status_code, 200, address)
            self.assertEqual(response.data, read(address), address)
            response.close()

    def test_no_forgotten_files(self):
        """Все .js в папке страницы подключены, и подключено только то, что есть."""
        found = {"/static/" + os.path.relpath(os.path.join(folder, name), STATIC).replace("\\", "/")
                 for folder, _, names in os.walk(STATIC) for name in names if name.endswith(".js")}

        self.assertEqual(found, set(SCRIPTS))

    def test_strict_mode_and_line_endings(self):
        """Каждый файл: первая строка "use strict";, окончания CRLF, без BOM."""
        for address in SCRIPTS:
            data = read(address)

            self.assertFalse(data.startswith(b"\xef\xbb\xbf"), f"{address}: BOM")
            self.assertTrue(data.startswith(b'"use strict";\r\n'), f"{address}: нет \"use strict\";")
            self.assertNotRegex(data, rb"(?<!\r)\n", f"{address}: есть окончания строк без CR")

    def test_top_level_names_are_unique(self):
        """Имя верхнего уровня объявлено ровно в одном файле."""
        owner = {}

        for address, text in self.texts.items():
            for match in DECLARATION.finditer(text):
                name = match.group(1) or match.group(2)
                self.assertNotIn(name, owner, f"{name}: и в {owner.get(name)}, и в {address}")
                owner[name] = address

        # Проверка видит объявления: главные имена на своих местах
        self.assertEqual(owner["S"], "/static/core.js")
        self.assertEqual(owner["h"], "/static/ui.js")
        self.assertEqual(owner["RENDERERS"], "/static/shell.js")
        self.assertEqual(owner["gridDraft"], "/static/tabs/settings.js")

    def test_top_level_let_changes_only_in_own_file(self):
        """Верхнеуровневый let присваивается (=, +=, -=, ||= …) только в файле, где объявлен."""
        lets = {name: address for address, text in self.texts.items() for name in TOP_LET.findall(text)}
        self.assertIn("pendingActs", lets)

        for name, home in lets.items():
            assignment = re.compile(rf"(?<![\w.$]){name}\s*(?:[-+*/%]|\|\||&&|\?\?)?=(?!=)|(?<![\w.$]){name}\s*(?:\+\+|--)|(?:\+\+|--){name}\b")

            for address, text in self.texts.items():
                if address != home:
                    self.assertIsNone(assignment.search(code(text)), f"{name} (из {home}) меняется в {address}")

    def test_shared_files_do_not_use_tab_names(self):
        """Общие файлы не обращаются к именам из файлов вкладок: вкладки сами подписываются
        на события HOOKS и регистрируют отрисовщики в RENDERERS.
        """
        tabNames = {match.group(1) or match.group(2): address
                    for address, text in self.texts.items() if address.startswith("/static/tabs/")
                    for match in DECLARATION.finditer(text)}
        self.assertIn("pollJob", tabNames)

        for address in SHARED:
            text = names(code(self.texts[address]))

            for name, home in tabNames.items():
                self.assertNotRegex(text, rf"(?<![\w.$]){re.escape(name)}\b", f"{address} зовёт {name} из {home}")

        # Проверка видит обращения: вкладка «Предпросмотр» зовёт функцию вкладки «Экспорт»
        # (download); «Запуск» подписывается на открытие проекта сам и о конце сборки сообщает
        # событием HOOKS.buildFinished, а не вызовом функции «Предпросмотра»
        self.assertRegex(names(code(self.texts["/static/tabs/preview.js"])), r"(?<![\w.$])download\(")
        runTab = names(code(self.texts["/static/tabs/run.js"]))
        self.assertRegex(runTab, r"HOOKS\.projectOpened\.push\(pollJob\)")
        self.assertRegex(runTab, r"HOOKS\.buildFinished\.forEach\(")
