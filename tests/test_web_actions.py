"""Протокол действий (`src/web/actions.py`): POST /api/project/<p>/action с {"action", "args"}.

* ``ActionProtocolTests`` — тело запроса, неизвестное действие, лишние и недостающие аргументы,
  ошибки внутри действия, ответ всегда несёт новое состояние и пишется в журнал;
* ``BlockedWhileRunningTests`` — что можно и что нельзя делать, пока идёт сборка.

Работают на копии реального проекта 2026/27 (`tests/real_project.py`).
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
import time
from unittest import mock

from src.modules.translate import translate
from src.modules.functions.variants import saveVariant
from src.web import actions, build
from src.web.core import log
from src.web.server import app
from tests.builders import GENERIC
from tests.real_project import CHEMIST, RealProjectCase


class ActionProtocolTests(RealProjectCase):
    """Протокол действий на настоящем проекте: тело запроса, ошибки, ответ и журнал."""
    NAME = "__test_actions__"

    def test_errors_inside_action(self):
        """Ошибка внутри действия: ValueError «web.…» — его перевод; другой ValueError — общий текст и запись
        в журнал; ответ без состояния проекта.
        """
        def broken(project, key):
            raise ValueError(key)

        with mock.patch.dict(actions.ACTIONS, {"broken": broken}):
            code, body = self.act("broken", key="web.error.broken_settings")
            self.assertEqual((code, body), (400, {"error": translate("web.error.broken_settings")}))

            with self.assertLogs(app.logger, "ERROR"):
                code, body = self.act("broken", key="invalid literal for int()")

            self.assertEqual((code, body), (400, {"error": GENERIC}))

    def test_action_answers_carry_state_and_are_logged(self):
        """Ответ действия дополняется полным состоянием; в журнал программы пишется, что спросили
        или что сделано.
        """
        def asking(project):
            return {"confirm": "Точно?"}

        def noticing(project):
            return {"notice": "Выберите другое"}

        with mock.patch.dict(actions.ACTIONS, {"asking": asking, "noticing": noticing}), self.assertLogs(log, "INFO") as logs:
            body = self.ok("asking")
            self.assertEqual(body["confirm"], "Точно?")
            self.assertEqual(body["state"]["answer"], self.load("answer.json"))
            self.assertEqual(self.ok("noticing")["notice"], "Выберите другое")
            self.ok("setLimit", key="max_courses_per_teacher", value=4)

        text = "\n".join(logs.output)
        self.assertIn("вопрос: Точно?", text)
        self.assertIn("сообщение: Выберите другое", text)
        self.assertIn("setLimit", text)

    def test_bad_request_bodies(self):
        """Тело не JSON, испорченный JSON, args не словарь — понятная ошибка, проект не меняется."""
        before = self.raw("settings.json")
        address = f"/api/project/{self.NAME}/action"

        response = self.client.post(address, data="action=setLimit")
        self.assertEqual((response.status_code, response.get_json()["error"]), (415, GENERIC))

        response = self.client.post(address, data="{oops", content_type="application/json")
        self.assertEqual((response.status_code, response.get_json()["error"]), (400, GENERIC))

        with self.assertLogs(app.logger, "ERROR"):
            response = self.client.post(address, json={"action": "setLimit", "args": None})

        self.assertEqual((response.status_code, response.get_json()["error"]), (400, GENERIC))

        self.assertEqual(self.raw("settings.json"), before)

    def test_action_name_of_wrong_type_is_ordinary_refusal(self):
        """Имя действия не строкой или тело — JSON-список (ручной или испорченный запрос) — обычный отказ 400,
        как неизвестное действие: без трассировки в журнале, settings.json не меняется.

        Раньше такие запросы падали вне try (AttributeError у списка, TypeError у «unhashable» имени)
        и давали ответ 500 с трассировкой; теперь тело проверяет actions._request.
        """
        address = f"/api/project/{self.NAME}/action"
        before = self.raw("settings.json")

        with self.assertNoLogs(app.logger, "ERROR"):
            for body in ({"action": ["setLimit"]}, ["setLimit"], {"action": None}, "setLimit"):
                response = self.client.post(address, json=body)
                self.assertEqual((response.status_code, response.get_json()["error"]), (400, GENERIC), body)

        self.assertEqual(self.raw("settings.json"), before)

    def test_broken_settings_are_reported_by_actions(self):
        """settings.json — не словарь: действия отвечают «файл настроек повреждён, закройте и откройте
        проект снова» (копию здесь никто не делает, поэтому не текст про копию) и файл не трогают.
        """
        with open(f"{self.folder}/settings.json", "w", encoding="utf-8") as file:
            file.write("[1, 2]")

        self.assertEqual(self.refused("setLimit", key="max_courses_per_teacher", value=3), translate("web.error.settings_broken_open"))
        self.assertEqual(self.client.get(f"/api/project/{self.NAME}").status_code, 400)
        self.assertEqual(self.raw("settings.json"), b"[1, 2]")

    def test_unknown_action_and_wrong_arguments(self):
        """Неизвестное действие и лишние / недостающие аргументы — понятная общая ошибка, а не падение."""
        generic = translate("web.error.generic")
        self.assertEqual(self.refused("dropDatabase"), generic)

        # Такие ошибки записываются в журнал программы (здесь — перехватываются, чтобы не шуметь)
        with self.assertLogs(app.logger, "ERROR"):
            self.assertEqual(self.refused("setLimit", key="max_courses_per_teacher"), generic)
            self.assertEqual(self.refused("setLimit", key="max_courses_per_teacher", value=3, extra=1), generic)
            response = self.client.post(f"/api/project/{self.NAME}/action", json={"action": "setLimit", "args": [1]})
            self.assertEqual(response.status_code, 400)


class BlockedWhileRunningTests(RealProjectCase):
    """Что можно и что нельзя делать, пока идёт сборка."""
    NAME = "__test_busy__"

    def fakeJob(self):
        """Помечает проект как «идёт сборка» (без настоящего решателя)."""
        build.JOBS[self.NAME] = {"stage": "2", "keep": False, "number": 1, "total": 1, "saved": 0, "repeats": 0, "stopped": False,
                                  "running": True, "started": time.time(), "finished": None, "log": [], "process": None, "fake": True}

        self.addCleanup(build.forget, self.NAME)

    def test_every_blocked_action_is_refused_and_changes_nothing(self):
        """Во время сборки каждое запрещённое действие отклоняется ещё до проверки аргументов, файлы не меняются;
        после окончания сборки запрет снимается.
        """
        self.fakeJob()
        files = {name: self.raw(name) for name in ("settings.json", "answer.json", "weights.json")}
        busy = translate("web.error.busy")

        for name in sorted(actions.BLOCKED_WHILE_RUNNING):
            self.assertEqual(self.refused(name), busy, name)

        self.assertEqual({name: self.raw(name) for name in files}, files)

        build.JOBS[self.NAME]["running"] = False
        self.assertNotEqual(self.refused("setHours", course="нет", subject="нет", hours=1), busy)

    def test_deleting_finished_project_forgets_its_job(self):
        """Проект, сборка которого закончилась, удаляется вместе со сведениями о сборке."""
        build.JOBS[self.NAME] = {"stage": "2", "keep": False, "number": 1, "total": 1, "saved": 1, "repeats": 0, "stopped": False,
                                 "running": False, "started": 1.0, "finished": 2.0, "log": [], "process": None, "fake": True}

        self.assertEqual(self.client.delete(f"/api/project/{self.NAME}").status_code, 200)

        self.assertFalse(os.path.exists(self.folder))
        self.assertNotIn(self.NAME, build.JOBS)

    def test_blocked_while_running(self):
        """Пока идёт сборка, нельзя менять то, что она строит (сетку, курсы, преподавателей, версии,
        принимать варианты) и удалять проект; версии сохранять можно.
        """
        version = self.state()["versions"][0]["id"]
        saveVariant(self.folder, "2", 1, {})
        self.fakeJob()

        busy = [
            ("setGrid", {"days": self.state()["grid"]}), ("newStream", {}), ("setHours", {"course": "x", "subject": "x", "hours": 1}),
            ("deleteTeacher", {"name": CHEMIST}), ("cycleAvailability", {"name": CHEMIST, "stage": "2", "day": 0, "lesson": 0}),
            ("accept", {"stage": "2", "number": 1}), ("restore", {"version": version}), ("resetStage", {"stage": "2"}),
            ("rejectVariant", {"stage": "2", "number": 1}), ("run", {"stage": "2"}),
        ]
        for action, args in busy:
            self.assertIn("составляет варианты", self.refused(action, **args), action)

        self.ok("newVersion", name="Во время сборки")

        self.assertEqual(self.client.delete(f"/api/project/{self.NAME}").status_code, 400)
        self.assertTrue(os.path.isdir(self.folder))
        self.assertTrue(self.client.get(f"/api/project/{self.NAME}/job").get_json()["running"])

    def test_build_input_is_locked_while_running(self):
        """Пока идёт сборка, нельзя менять и то, что она взяла в работу: веса, тщательность и число
        вариантов, свои правила (добавить, изменить важность, удалить), ограничение курсов на
        преподавателя и пары предметов. Отказ — тот же текст «идёт сборка», файлы не меняются;
        после конца сборки те же правки проходят.
        """
        rule = {"name": "Не в субботу", "template": "time", "weight": 100,
                "params": {"target": "all", "value": "", "days": [5], "times": ["10:00 - 11:30"]}}
        self.ok("savePenalty", penalty=rule)
        rule_id = self.state()["penalties"][0]["id"]
        self.fakeJob()
        files = {name: self.raw(name) for name in ("settings.json", "weights.json")}
        busy = translate("web.error.busy")

        edits = [
            ("setWeight", {"key": "softSubjectPair", "value": 10}), ("setNumber", {"key": "iterations", "value": 3000000}),
            ("setNumber", {"key": "variants", "value": 2}), ("savePenalty", {"penalty": {**rule, "name": "Ещё одно"}}),
            ("setPenaltyWeight", {"id": rule_id, "weight": 300}), ("deletePenalty", {"id": rule_id}),
            ("setLimit", {"key": "max_courses_per_teacher", "value": 6}), ("cyclePair", {"first": "География", "second": "Информатика"}),
        ]
        for action, args in edits:
            self.assertEqual(self.refused(action, **args), busy, action)

        self.assertEqual({name: self.raw(name) for name in files}, files)

        build.JOBS[self.NAME]["running"] = False

        for action, args in edits:
            self.ok(action, **args)

        self.assertEqual(self.state()["weights"]["softSubjectPair"], 10)
        self.assertEqual(self.state()["penalties"][0]["name"], "Ещё одно")
