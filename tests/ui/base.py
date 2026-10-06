"""Общая заготовка браузерных тестов (сам тестов не содержит — имя не начинается с test_).

UICase — база классов тестов:
* setUpClass: запускает Edge без окна (нет Playwright или Edge — SkipTest), замораживает
  «сегодня» на сервере (04.10.2026), готовит шаблон проекта из Расписание_2026-27.zip
  (тщательность 1 000 000, 2 варианта; при PREPARE — файлы, подправленные этой функцией; при
  VARIANTS_STAGE — уже составленные варианты этого этапа)
  и держит его во временной папке вне папки проектов;
* setUp: свежая копия шаблона под именем NAME в папке проектов, новый контекст браузера
  (чистый localStorage), сбор ошибок страницы и консоли;
* tearDown: останавливает сборку, удаляет копию и проверяет, что ошибок JS не было.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import atexit
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import unittest
import urllib.parse
from unittest import mock

from src.modules.functions.tree import importProjectArchive
from src.modules.translate import translate
from src.web import build
from src.web.server import app
from tests.builders import PROJECTS, SOLVER
from tests.real_project import ARCHIVE, FrozenDate

try:
    from playwright.sync_api import Error as PlaywrightError, expect, sync_playwright
except ImportError:  # Playwright не установлен — тесты пропускаются
    sync_playwright = None  # type: ignore[assignment]
    expect = None  # type: ignore[assignment]
    PlaywrightError = Exception  # type: ignore[assignment,misc]

# Все вкладки проекта в порядке бокового меню (ключи menu.main.tab.<вкладка>, см. UICase.tab)
TABS = ["settings", "classes", "teachers", "run", "preview", "view", "save", "export"]

# Таймаут ожиданий Playwright (мс): действия сервера быстрые, но первая загрузка вкладки бывает дольше
TIMEOUT = 15000

# Сервер запросов в журнал не пишет — иначе вывод тестов тонет в строках «GET /api/…»
logging.getLogger("werkzeug").setLevel(logging.ERROR)

_SERVER = None


def serverUrl():
    """Адрес сервера Flask, поднятого один раз на весь прогон в фоновой нити (свободный порт)."""
    global _SERVER

    if _SERVER is None:
        from werkzeug.serving import make_server

        _SERVER = make_server("127.0.0.1", 0, app, threaded=True)
        threading.Thread(target=_SERVER.serve_forever, daemon=True).start()
        atexit.register(_SERVER.shutdown)

    return f"http://127.0.0.1:{_SERVER.server_port}"


def t(key):
    """Текст интерфейса по ключу (как t() на странице)."""
    return translate(key)


def plain(text):
    """Текст без мягких переносов (страница расставляет их в длинных словах) и крайних пробелов."""
    return text.replace("\u00ad", "").strip()


@unittest.skipUnless(os.path.exists(ARCHIVE), "the 2026/27 project archive is not here")
class UICase(unittest.TestCase):
    """База браузерных тестов: сервер, Edge, копия реального проекта и сбор ошибок JS."""
    # Этап, варианты которого составить заранее (в шаблоне); None — без вариантов
    VARIANTS_STAGE: str | None = None
    # Подготовка шаблона до составления вариантов: функция от папки проекта (staticmethod), которая
    # правит его файлы, — например, отметка «линейка присоединяется к Потоку N» (builders.markJoint);
    # None — без подготовки
    PREPARE = None
    # Размер окна браузера
    VIEWPORT = {"width": 1400, "height": 900}

    @classmethod
    def projectName(cls):
        """Служебное имя тестового проекта этого класса."""
        return f"__test_ui_{cls.__name__.lower()}__"

    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")

        cls.NAME = cls.projectName()
        cls.url = serverUrl()
        cls.client = app.test_client()

        # «Сегодня» на сервере — 04.10.2026 (как в tests/real_project.py); решатель — по полному пути
        cls._patches = [mock.patch("datetime.date", FrozenDate), mock.patch.object(build, "SOLVER", SOLVER)]
        for patch in cls._patches:
            patch.start()

        try:
            cls._playwright = sync_playwright().start()
        except Exception as error:
            cls._stopPatches()
            raise unittest.SkipTest(f"playwright does not start: {error}")

        try:
            cls.browser = cls._playwright.chromium.launch(channel="msedge", headless=True)
        except Exception as error:
            cls._playwright.stop()
            cls._stopPatches()
            raise unittest.SkipTest(f"Microsoft Edge does not start: {error}")

        try:
            cls._makeTemplate()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def _stopPatches(cls):
        for patch in reversed(cls._patches):
            patch.stop()

    @classmethod
    def _makeTemplate(cls):
        """Шаблон проекта во временной папке: импорт архива, быстрые настройки, варианты этапа."""
        name = f"__test_ui_tpl_{cls.__name__.lower()}__"
        folder = f"{PROJECTS}/{name}"
        shutil.rmtree(folder, ignore_errors=True)
        importProjectArchive(ARCHIVE, name)

        def act(action, **args):
            response = cls.client.post(f"/api/project/{name}/action", json={"action": action, "args": args})
            assert response.status_code == 200, response.get_json()
            return response.get_json()

        assert cls.client.post(f"/api/project/{name}/open").status_code == 200
        act("setNumber", key="iterations", value=1000000)
        act("setNumber", key="variants", value=2)

        if cls.PREPARE:
            cls.PREPARE(folder)
            # Открытие заново: проект с подправленными файлами проходит обычную подготовку при открытии
            assert cls.client.post(f"/api/project/{name}/open").status_code == 200

        if cls.VARIANTS_STAGE:
            act("run", stage=cls.VARIANTS_STAGE, keep=False)
            deadline = time.time() + 120

            while build.JOBS[name]["running"] and time.time() < deadline:
                time.sleep(0.1)

            job = build.JOBS.pop(name)
            assert job["saved"] == 2, job["log"][-10:]

        cls._templateDir = tempfile.mkdtemp(prefix="schedule-ui-")
        cls.template = os.path.join(cls._templateDir, "project")
        shutil.move(folder, cls.template)

    @classmethod
    def tearDownClass(cls):
        for name in ("browser", "_playwright"):
            item = getattr(cls, name, None)

            try:
                if item is not None:
                    item.close() if name == "browser" else item.stop()
            except Exception:
                pass

        if getattr(cls, "_templateDir", None):
            shutil.rmtree(cls._templateDir, ignore_errors=True)

        cls._stopPatches()

    # ------------------------------------------------------------------ каждый тест

    @property
    def folder(self):
        """Папка тестового проекта."""
        return f"{PROJECTS}/{self.NAME}"

    def setUp(self):
        shutil.rmtree(self.folder, ignore_errors=True)
        shutil.copytree(self.template, self.folder)
        self.errors = []
        self.allowed = []
        self.extra = []  # другие проекты, созданные тестом (удаляются в tearDown)
        self.newContext(self.VIEWPORT)

    def newContext(self, viewport, **options):
        """Новый контекст браузера (чистое хранилище) и страница с журналом ошибок JS.

        options — другие настройки контекста Playwright (например, color_scheme="dark").
        """
        if getattr(self, "context", None):
            self.context.close()

        self.context = self.browser.new_context(viewport=viewport, accept_downloads=True, locale="ru-RU", **options)
        self.context.set_default_timeout(TIMEOUT)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(f"pageerror: {error}"))
        self.page.on("console", lambda message: message.type == "error" and self.errors.append(f"console: {message.text}"))

    def tearDown(self):
        job = build.JOBS.get(self.NAME)

        # Поддельное задание (fake: тест сам положил его в build.JOBS) не остановить через stopJob:
        # процесса у него нет, и running само не сбросится — ожидание длилось бы все 30 секунд.
        # Так же делает RealProjectCase.tearDown (tests/real_project.py).
        if job and job["running"] and not job.get("fake"):
            build.stopJob(self.NAME)
            deadline = time.time() + 30

            while job["running"] and time.time() < deadline:
                time.sleep(0.1)

        build.forget(self.NAME)

        try:
            # Ответы, которые ещё в пути, успевают дойти и записать свои ошибки
            self.page.wait_for_timeout(150)
        except PlaywrightError:
            pass

        self.context.close()
        self.context = None
        shutil.rmtree(self.folder, ignore_errors=True)

        for name in self.extra:
            shutil.rmtree(f"{PROJECTS}/{name}", ignore_errors=True)

        errors = [error for error in self.errors if not any(re.search(pattern, error) for pattern in self.allowed)]
        self.assertEqual(errors, [], "JS errors on the page")

    def allowRefusals(self):
        """Тест сам вызывает отказ сервера (400/404): строка браузера «Failed to load resource» — не ошибка."""
        self.allowed.append(r"Failed to load resource: the server responded with a status of 40[04]")

    # ------------------------------------------------------------------ помощники

    def open(self, tab=None):
        """Открывает тестовый проект по адресу #имя и (если задано) вкладку tab (ключ из NAV)."""
        # Смена только «#…» страницу не перезагружает (проект открывается при загрузке) — сначала пустая
        self.page.goto("about:blank")
        self.page.goto(f"{self.url}/#{urllib.parse.quote(self.NAME)}")
        expect(self.page.locator(".project-switch .name")).to_have_text(self.NAME)

        if tab:
            self.tab(tab)

    def tab(self, key):
        """Переключает вкладку кликом в боковом меню и ждёт её заголовок."""
        title = t(f"menu.main.tab.{key}")
        self.page.locator(".nav-item", has_text=title).first.click()
        expect(self.page.locator(".page-head h1")).to_contain_text(title)

    def idle(self):
        """Ждёт, пока очередь действий страницы (act) опустеет."""
        self.page.wait_for_function("() => pendingActs === 0")

    def act(self, click, idle=True):
        """Выполняет click() и ждёт ответ сервера на действие (POST …/action) и пустую очередь.

        idle=False — ответ откроет окно (вопрос «точно?», пояснение): очередь ждёт, пока его закроют.
        """
        with self.page.expect_response(lambda response: "/action" in response.url) as info:
            click()

        if idle:
            self.idle()

        return info.value

    def state(self, name=None):
        """Состояние проекта прямо с диска (как его отдаёт сервер странице)."""
        response = self.client.get(f"/api/project/{urllib.parse.quote(name or self.NAME)}")
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def course(self, name):
        """Курс из состояния проекта по имени."""
        return next(item for item in self.state()["courses"] if item["name"] == name)

    def load(self, name):
        """JSON-файл из папки тестового проекта (None, если его нет)."""
        path = f"{self.folder}/{name}"

        if not os.path.exists(path):
            return None

        with open(path, encoding="utf-8") as file:
            return json.load(file)

    def save(self, name, data):
        """Записывает JSON-файл в папку тестового проекта (подготовка данных теста)."""
        with open(f"{self.folder}/{name}", "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False)

    def apiAct(self, action, **args):
        """Действие на сервере мимо страницы (подготовка данных теста)."""
        response = self.client.post(f"/api/project/{self.NAME}/action", json={"action": action, "args": args})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def toast(self, text):
        """Всплывающее сообщение с текстом text появилось."""
        expect(self.page.locator("#toast")).to_be_visible()
        expect(self.page.locator("#toast")).to_contain_text(text)

    def dialogButton(self, label):
        """Кнопка label в открытом модальном окне."""
        return self.page.locator(".dialog .dialog-foot button", has_text=label)

    def variants(self, stage):
        """Варианты этапа так, как их получает «Предпросмотр» (от лучшего к худшему)."""
        return self.client.get(f"/api/project/{self.NAME}/variants?stage={stage}").get_json()

    # ------------------------------------------------------------------ «Курсы»

    def pick(self, section, line):
        """Выбирает на «Курсах» поток или блок (по названию) и линейку и ждёт заголовок карточки
        «<поток> — <линейка>». Названия экранируются (re.escape): в них бывают скобки и точки.
        """
        self.page.locator(".chip-row .stage-pill", has_text=section).click()
        self.page.locator(".chip-row .chip", has_text=line).click()
        # «i» в конце заголовка — кнопка-пояснение
        expect(self.page.locator(".sticky-card > .card-head h2")).to_have_text(re.compile(rf"{re.escape(section)} — {re.escape(line)}i?$"))

    def row(self, subject):
        """Строка таблицы курсов на «Курсах» с предметом ``subject`` (имя предмета — целиком)."""
        return self.page.locator("table.data tbody tr", has=self.page.locator("td b", has_text=re.compile(rf"^{re.escape(subject)}$")))
