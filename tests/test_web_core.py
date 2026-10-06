"""Каркас сервера (`src/web/core.py`): страница, справочники, защита и ответы на ошибки.

* ``HostTests`` — сервер отвечает только на адреса этого компьютера (защита от DNS rebinding);
  ошибки без проекта;
* ``PageAndReferenceTests`` — страница, её файлы, тексты интерфейса и справочник /api/meta;
* ``RouteErrorTests`` — непредвиденные ошибки маршрутов: понятный текст, код и запись в журнал.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
import unittest
from unittest import mock

from src.modules.translate import translate
from src.web import projects
from src.web.server import app
from tests.builders import GENERIC, PROJECTS
from tests.real_project import RealProjectCase


class HostTests(unittest.TestCase):
    """Защита «только этот компьютер» и ответы на ошибки без проекта."""
    def setUp(self):
        self.client = app.test_client()

    def test_local_addresses_work(self):
        """Адреса этого компьютера (127.0.0.1, localhost, [::1], с портом и без) — сервер отвечает."""
        for host in ("127.0.0.1:8765", "localhost:8765", "localhost", "[::1]:8765"):
            response = self.client.get("/api/meta", headers={"Host": host})
            self.assertEqual(response.status_code, 200, host)
            response.close()

    def test_foreign_host_is_refused(self):
        """Чужое имя в Host (в том числе «127.0.0.1.evil.example») — 403 с понятным текстом ошибки."""
        for host in ("evil.example:8765", "evil.example", "127.0.0.1.evil.example"):
            response = self.client.get("/api/meta", headers={"Host": host})
            self.assertEqual(response.status_code, 403, host)
            self.assertEqual(response.get_json()["error"], translate("web.error.wrong_host"))
            response.close()

    def test_foreign_host_cannot_open_page_or_change_projects(self):
        """С чужим Host нельзя ни открыть страницу, ни создать проект; IPv6-адрес не этого компьютера — тоже чужой."""
        for host in ("evil.example:8765", "[fe80::1]:8765", "localhost.evil.example", "127.0.0.2:8765"):
            for method, address in (("get", "/"), ("get", "/static/app.js"), ("post", "/api/projects")):
                response = getattr(self.client, method)(address, headers={"Host": host}, json={"name": "__test_evil__"})
                self.assertEqual(response.status_code, 403, (host, address))
                self.assertEqual(response.get_json()["error"], translate("web.error.wrong_host"))
                response.close()

        self.assertFalse(os.path.exists(f"{PROJECTS}/__test_evil__"))

    def test_non_api_address_gets_ordinary_404_page(self):
        """Неизвестный адрес вне API — обычная страница 404 (не JSON); файл вне папки страницы не отдаётся."""
        response = self.client.get("/nothing")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.content_type.startswith("text/html"))

        response = self.client.get("/static/../core.py")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"import", response.data)

    def test_unknown_project_everywhere_is_explained(self):
        """Несуществующий проект в любом адресе — 400 «Проект не найден», а не падение."""
        missing = translate("web.error.no_project")
        for address in ("/api/project/__test_none__", "/api/project/__test_none__/job", "/api/project/__test_none__/variants?stage=1",
                        "/api/project/__test_none__/teacher?name=a&stage=1", "/api/project/__test_none__/export/project"):
            response = self.client.get(address)
            self.assertEqual((response.status_code, response.get_json()["error"]), (400, missing), address)

        response = self.client.post("/api/project/__test_none__/open")
        self.assertEqual((response.status_code, response.get_json()["error"]), (400, missing))


class PageAndReferenceTests(unittest.TestCase):
    """Страница, тексты интерфейса и справочник."""
    def setUp(self):
        self.client = app.test_client()

    def test_page_and_static_files(self):
        """Главная страница и её скрипт отдаются; несуществующий файл — 404."""
        for address, code in (("/", 200), ("/static/app.js", 200), ("/static/nothing.js", 404)):
            response = self.client.get(address)
            self.assertEqual(response.status_code, code, address)
            if address == "/":
                self.assertIn(b"<html", response.data.lower())

            response.close()

    def test_texts_and_meta(self):
        """Тексты интерфейса — словарь переводов; справочник — виды правил, их цели, число дней."""
        texts = self.client.get("/api/i18n").get_json()
        self.assertEqual(texts["web.issue.weekend"], "Урок в выходной")

        meta = self.client.get("/api/meta").get_json()
        self.assertEqual(meta["templates"], ["time", "daily_limit", "adjacent", "same_day"])
        self.assertNotIn("pairStates", meta)
        self.assertEqual(meta["days"], 7)
        self.assertIn("teacher", meta["targets"]["daily_limit"])

        # Постоянные значения сервера, которые страница раньше держала своими копиями
        self.assertEqual(meta["extraBlock"], "extra")
        self.assertEqual(meta["shortLines"]["ЕГЭ продвинутый"], "ЕГЭ продв.")
        self.assertEqual(meta["weightOrder"][:2], ["softSubjectPair", "pairsSameDay"])
        self.assertEqual(meta["mediumWeight"], 300)

    def test_unknown_api_address_answers_json_in_russian(self):
        """Неизвестный адрес API — JSON с русским текстом ошибки, а не английская страница Flask."""
        response = self.client.get("/api/nothing")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], translate("web.error.generic"))

        response = self.client.put("/api/projects")
        self.assertEqual(response.status_code, 405)
        self.assertIn("error", response.get_json())


class RouteErrorTests(RealProjectCase):
    """Ошибки внутри маршрутов на настоящем проекте: повреждённый файл, непредвиденная ошибка."""
    NAME = "__test_route_errors__"

    def test_damaged_file_error_in_route_is_translated(self):
        """ValueError с ключом перевода «web.…» в любом маршруте — понятный текст и код 400."""
        with mock.patch.object(projects, "state", side_effect=ValueError("web.error.broken_settings")):
            response = self.client.get(f"/api/project/{self.NAME}")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], translate("web.error.broken_settings"))

    def test_unexpected_error_in_route_is_logged_and_explained(self):
        """Любая другая ошибка маршрута — код 500, общий русский текст, подробности в журнале."""
        with mock.patch.object(projects, "state", side_effect=RuntimeError("сломалось")), self.assertLogs(app.logger, "ERROR") as logs:
            response = self.client.get(f"/api/project/{self.NAME}")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"], GENERIC)
        self.assertIn("сломалось", "\n".join(logs.output))

    def test_plain_value_error_in_route_is_500(self):
        """Обычный ValueError (не ключ «web.…») в маршруте — 500, общий текст и запись в журнал."""
        with mock.patch.object(projects, "state", side_effect=ValueError("boom")), self.assertLogs(app.logger, "ERROR") as logs:
            response = self.client.get(f"/api/project/{self.NAME}")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"], GENERIC)
        self.assertIn("boom", "\n".join(logs.output))
