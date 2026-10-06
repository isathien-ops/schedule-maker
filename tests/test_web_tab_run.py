"""Действия вкладки «Запуск» (`src/web/tabs/run.py`) и сборка вариантов через сервер.

* ``RunTabTests`` — веса правил, тщательность и число вариантов, свои правила, сброс этапа
  (в том числе «убирать нечего», когда у курсов только пустые недели), отказы запуска;
* ``RunBuildTests`` — запуск и остановка сборки: настоящим solve.exe на малом числе шагов
  (если он собран) и с решателем, который не запускается; режим «оставить уже принятые уроки»;
  прогноз закреплений сервера совпадает со строкой решателя «Закреплено N из M уроков»;
* ``JointRunTests`` — «линейка присоединяется к Потоку N» (.spec/joint-lines/SPEC.md): сброс этапа
  источника спрашивает про уроки копий, этап из одних копий составлять нечего, а убирать из
  расписания у этапа, где стоят только копии, нечего — с понятным текстом про общие уроки (AC-41);
  вопрос «Убрать?» страница получает от сервера (``ask``) — один, со всеми сведениями (AC-40);
* ``KeepHintTests`` — подсказка галочки «Оставить уже принятые уроки на месте» говорит и о преподавателях
  («Смена преподавателя в подборе», .spec/teacher-swap/SPEC.md, AC-21).

Нить сборки без настоящего решателя — `test_web_build.py`.

Основа — `RealProjectCase` из `tests/real_project.py`: копия реального проекта 2026/27, «сегодня»
04.10.2026, действия идут через сервер, как со страницы (POST /api/project/<имя>/action).
Проверяется, что сервер защищает курсы, которые уже идут, переспрашивает (ответ с "confirm")
перед опасными действиями, сохраняет версии «Перед: …» и при отказе не портит файлы проекта.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
import re
import time
import unittest
from unittest import mock

from src.modules.translate import tr, translate
from src.modules.functions.courses import removeCourses
from src.modules.functions.journal import BUILDS_DIR
from src.modules.functions.model import hasLessons
from src.modules.functions.stages import stageCourses
from src.modules.functions.variants import loadVariants, saveVariant
from src.web import build
from src.web.core import app
from src.web.tabs import run as run_tab
from tests.builders import JOINT_LINE, courseWeek, jointCourse, jointProject, markJoint, shiftStream
from tests.engine import pinSummary
from tests.real_project import RUS_8_2, RealProjectCase, emptied, forecastText, lessons, unstaffed


class RunTabTests(RealProjectCase):
    """Вкладка «Запуск»: веса, параметры, свои правила, сброс этапа."""
    NAME = "__test_run__"

    def test_weights_and_numbers(self):
        """Вес правила и параметры сборки читаются терпимо и ограничиваются; неизвестный ключ — отказ."""
        self.ok("setWeight", key="softSubjectPair", value="2 000")
        self.assertEqual(self.load("weights.json")["softSubjectPair"], 2000)
        self.refused("setWeight", key="newWeight", value="5")
        self.refused("setWeight", key="softSubjectPair", value="много")

        self.ok("setNumber", key="iterations", value="5")
        self.assertEqual(self.state()["iterations"], 100000)
        self.ok("setNumber", key="variants", value="1000")
        self.assertEqual(self.state()["variants"], 50)
        self.ok("setNumber", key="variants", value="3,7")
        self.assertEqual(self.state()["variants"], 3)
        self.refused("setNumber", key="max_courses_per_teacher", value="5")

    def test_custom_rules(self):
        """Свои правила: проверка формы, создание, правка с тем же id, вес, удаление; в состоянии —
        понятное описание правила.
        """
        bad = [
            {"name": "", "template": "adjacent", "weight": 1, "params": {"target": "all"}},
            {"name": "x", "template": "unknown", "weight": 1, "params": {}},
            {"name": "x", "template": "adjacent", "weight": 1, "params": {"target": "course", "value": ""}},
            {"name": "x", "template": "time", "weight": 1, "params": {"target": "all", "days": [], "times": ["16:20 - 17:50"]}},
            {"name": "x", "template": "same_day", "weight": 1, "params": {"first": "Химия", "second": "Химия"}},
            # Ручные и устаревшие запросы: цель не того вида правила, дни не номера дней, часы не строки,
            # параметры не словарь
            {"name": "x", "template": "daily_limit", "weight": 1, "params": {"target": "all", "limit": 2}},
            {"name": "x", "template": "adjacent", "weight": 1, "params": {}},
            {"name": "x", "template": "time", "weight": 1, "params": {"target": "all", "days": ["пн"], "times": ["16:20 - 17:50"]}},
            {"name": "x", "template": "time", "weight": 1, "params": {"target": "all", "days": [7], "times": ["16:20 - 17:50"]}},
            {"name": "x", "template": "time", "weight": 1, "params": {"target": "all", "days": [0], "times": [1620]}},
            {"name": "x", "template": "time", "weight": 1, "params": {"target": "all", "days": 0, "times": ["16:20 - 17:50"]}},
            {"name": "x", "template": "same_day", "weight": 1, "params": {"first": "Химия", "second": None}},
            {"name": "x", "template": "same_day", "weight": 1, "params": None},
        ]
        for penalty in bad:
            self.refused("savePenalty", penalty=penalty)

        # Лимит «Не больше N уроков в день» завуч вписывает сам: пустое поле (null), дробное или
        # отрицательное число — понятная ошибка про число; строка и true (ручной запрос) — тоже
        for limit in (None, 2.5, -1, "2", True):
            penalty = {"name": "x", "template": "daily_limit", "weight": 1, "params": {"target": "teacher", "value": "", "limit": limit}}
            self.assertEqual(self.refused("savePenalty", penalty=penalty), translate("penalty.dialog.error_limit"), limit)

        self.assertEqual(self.state()["penalties"], [])

        self.ok("savePenalty", penalty={"name": "Время", "template": "time", "weight": 1, "params": {"target": "all", "days": [0, 6], "times": ["16:20 - 17:50"]}})
        self.ok("deletePenalty", id=self.state()["penalties"][0]["id"])

        self.ok("savePenalty", penalty={"name": " Химия и биология ", "template": "same_day", "weight": "50", "params": {"first": "Химия", "second": "Биология"}})
        item = self.state()["penalties"][0]
        self.assertEqual((item["name"], item["weight"]), ("Химия и биология", 50))
        self.assertIn("«Химия» и «Биология»", item["description"])

        self.ok("savePenalty", penalty={"id": item["id"], "name": "Новое имя", "template": "daily_limit", "weight": 7, "params": {"target": "teacher", "value": "", "limit": 2}})
        items = self.state()["penalties"]
        self.assertEqual([(entry["id"], entry["name"], entry["template"]) for entry in items], [(item["id"], "Новое имя", "daily_limit")])
        self.assertIn("каждый преподаватель", items[0]["description"])

        self.ok("setPenaltyWeight", id=item["id"], weight="300")
        self.assertEqual(self.state()["penalties"][0]["weight"], 300)
        self.ok("deletePenalty", id=item["id"])
        self.assertEqual(self.state()["penalties"], [])

    def test_reset_stage(self):
        """«Убрать из расписания» (сброс этапа): у этапа, где все курсы уже идут, убирать нечего; у потока 2 уроки уходят
        из расписания (версия «Перед: …» сохраняется), а варианты остаются для повторного принятия.
        """
        self.refused("resetStage", stage="1")
        self.assertEqual(self.refused("resetStage", stage="9"), translate("web.error.generic"))

        saveVariant(self.folder, "2", 1, {})
        self.ok("resetStage", stage="2")
        answer = self.load("answer.json")
        self.assertFalse(set(stageCourses(self.load("settings.json"), "2")) & set(answer))
        self.assertTrue(set(stageCourses(self.load("settings.json"), "1")) <= set(answer))
        self.assertTrue(any(name.startswith("Перед:") for name in self.versions()))
        self.assertEqual(len(loadVariants(self.folder, "2")), 1)

        self.refused("resetStage", stage="2")

    def test_run_refusals(self):
        """Сборка не начинается: для неизвестного этапа, для этапа, где все курсы уже идут, и без solve.exe."""
        self.refused("run", stage="9")
        self.assertIn("уже идут", self.refused("run", stage="1"))

        with mock.patch.object(build, "SOLVER", os.path.join(self.folder, "нет-решателя.exe")):
            self.refused("run", stage="2")

        self.assertIsNone(self.client.get(f"/api/project/{self.NAME}/job").get_json())

    def test_rule_weight_of_unknown_rule_changes_nothing(self):
        """Вес правила с неизвестным id — существующие правила не меняются."""
        self.ok("savePenalty", penalty={"name": "Химия и биология", "template": "same_day", "weight": 5, "params": {"first": "Химия", "second": "Биология"}})
        before = self.state()["penalties"]

        self.ok("setPenaltyWeight", id="нет-такого", weight=999)
        self.ok("deletePenalty", id="нет-такого")

        self.assertEqual(self.state()["penalties"], before)

    def test_reset_with_only_empty_weeks_has_nothing_to_remove(self):
        """«Убрать из расписания»: у курсов этапа в answer.json только пустые недели — отказ
        «уроков этих курсов в расписании нет» (web.run.nothing_to_reset_empty), answer.json и версии
        не меняются.
        """
        answer = self.load("answer.json")

        for name in stageCourses(self.load("settings.json"), "2"):
            if name in answer:
                answer[name] = emptied(answer[name])

        self.save("answer.json", answer)
        before, versions = self.raw("answer.json"), self.versions()

        self.assertEqual(self.refused("resetStage", stage="2"), translate("web.run.nothing_to_reset_empty"))
        self.assertEqual(self.raw("answer.json"), before)
        self.assertEqual(self.versions(), versions)


class RunBuildTests(RealProjectCase):
    """Запуск и остановка сборки через действия вкладки."""
    NAME = "__test_run_build__"

    def noSolver(self):
        """Подмены «решатель не запускается»: файл решателя есть (подойдёт любой файл), но запуск
        падает с OSError. Сборка записывает трассировку в журнал сервера — её ловит assertLogs,
        чтобы она не засоряла вывод тестов.
        """
        return (mock.patch.object(build, "SOLVER", os.path.abspath(__file__)),
                mock.patch.object(build.subprocess, "Popen", side_effect=OSError("no solver")),
                self.assertLogs(app.logger, "ERROR"))

    @unittest.skipUnless(os.path.exists(build.SOLVER), "solve.exe is not built")
    def test_stop_keeps_previous_variants(self):
        """«Остановить» прерывает solve.exe; если новых вариантов ещё нет, прежние варианты остаются."""
        settings = self.load("settings.json")
        settings["iterations"], settings["variants"] = 2000000000, 2
        self.save("settings.json", settings)
        saveVariant(self.folder, "2", 1, {"старый": []})

        self.ok("run", stage="2")
        deadline = time.time() + 20
        while build.JOBS[self.NAME]["process"] is None and time.time() < deadline:
            time.sleep(0.05)

        self.assertIsNotNone(build.JOBS[self.NAME]["process"])

        self.ok("stop")
        self.waitJob(20)

        job = self.client.get(f"/api/project/{self.NAME}/job").get_json()
        self.assertEqual((job["running"], job["stopped"], job["saved"]), (False, True, 0))
        self.assertEqual(loadVariants(self.folder, "2"), [(1, {"старый": []})])

    @unittest.skipUnless(os.path.exists(build.SOLVER), "solve.exe is not built")
    def test_short_build_view_and_accept(self):
        """Короткая настоящая сборка доп. курсов (1 вариант, 100 000 шагов): вариант сохраняется с оценками
        и подписями к урокам, пишется журнал сборки, вариант принимается в расписание и отмечается
        «принят»; уроки других этапов не меняются.
        """
        settings = self.load("settings.json")
        settings["iterations"], settings["variants"] = 100000, 1
        self.save("settings.json", settings)
        before = self.load("answer.json")
        builds = set(os.listdir(BUILDS_DIR)) if os.path.isdir(BUILDS_DIR) else set()

        self.ok("run", stage="extra")
        self.waitJob(120)

        job = self.client.get(f"/api/project/{self.NAME}/job").get_json()
        self.assertEqual((job["running"], job["saved"], job["total"]), (False, 1, 1), job["log"][-5:])
        self.assertTrue(set(os.listdir(BUILDS_DIR)) - builds)

        data = self.client.get(f"/api/project/{self.NAME}/variants", query_string={"stage": "extra"}).get_json()
        self.assertEqual(len(data["variants"]), 1)
        variant = data["variants"][0]
        self.assertEqual(set(data["metrics"]) | {"custom", "total"}, set(variant["metrics"]))
        self.assertEqual(set(variant["answer"]), set(stageCourses(settings, "extra")))
        self.assertIsInstance(variant["issues"], dict)

        body = self.ok("accept", stage="extra", number=1, build=data["build"])
        if "confirm" in body:
            self.ok("accept", stage="extra", number=1, build=data["build"], force=True)

        answer = self.load("answer.json")
        for name in stageCourses(settings, "extra"):
            self.assertEqual(answer.get(name), variant["answer"].get(name), name)

        for name in stageCourses(settings, "1") + stageCourses(settings, "2"):
            self.assertEqual(answer.get(name), before.get(name), name)

        data = self.client.get(f"/api/project/{self.NAME}/variants", query_string={"stage": "extra"}).get_json()
        self.assertTrue(data["variants"][0]["accepted"])

    def test_failed_build_does_not_stay_running(self):
        """Если решатель не запустился, задача составления не «висит» в состоянии «идёт» — страница
        не будет бесконечно ждать; в ходе сборки — строка об ошибке, в журнале — причина.
        """
        solver, popen, logs = self.noSolver()

        with solver, popen, logs as captured:
            self.act("run", stage="2")
            self.waitJob(5)

        # waitJob по истечении времени выходит молча, поэтому «не идёт» проверяется отдельно
        job = build.JOBS[self.NAME]
        self.assertFalse(job["running"])
        self.assertEqual(job["saved"], 0)
        self.assertIn(tr("web.run.solver_failed", code="?"), job["log"][-1]["text"])
        self.assertEqual(str(captured.records[0].exc_info[1]), "no solver")

    def test_keep_only_while_stream_misses_lessons(self):
        """«Оставить уже принятые уроки на месте» работает, пока потоку не хватает уроков. Если поток принят целиком,
        с этой галочкой программе нечего менять (все варианты были бы копией расписания) — она составляет заново.
        """
        for totals, expected in (((62, 50), True), ((62, 62), False)):
            solver, popen, logs = self.noSolver()

            with solver, popen, logs, mock.patch.object(run_tab, "stageTotals", return_value=totals):
                self.act("run", stage="2", keep=True)
                self.waitJob(5)

            self.assertEqual(build.JOBS[self.NAME]["keep"], expected)

    @unittest.skipUnless(os.path.exists(build.SOLVER), "solve.exe is not built")
    def test_forecast_matches_solver_line(self):
        """Настоящая сборка потока 2 (1 вариант, 100 000 шагов) с галочкой «Оставить уже принятые уроки
        на месте» и без неё, со всеми преподавателями и когда курс «8 класс — Русский язык» никто не
        может вести: прогноз сервера в ходе сборки — тот же, что в состоянии этапа (forecast), и решатель
        печатает «Закреплено N из M уроков, подбирается K[, без преподавателя (не ставятся): X]» с теми
        же числами.
        """
        settings = self.load("settings.json")
        settings["iterations"], settings["variants"] = 100000, 1

        for nobody in (0, 1):
            self.save("settings.json", unstaffed(settings, RUS_8_2, "Русский язык") if nobody else settings)
            forecast = next(item["forecast"] for item in self.state()["stages"] if item["key"] == "2")

            for keep, expected in ((True, forecast["keep"]), (False, forecast["fresh"])):
                self.ok("run", stage="2", keep=keep)
                self.waitJob(120)

                log = [line["text"] for line in build.JOBS[self.NAME]["log"]]
                self.assertEqual(expected["noTeacher"], nobody)
                self.assertIn(forecastText(expected), log)
                summary = (expected["pinned"], expected["total"], expected["free"], expected["noTeacher"])
                self.assertEqual(pinSummary("\n".join(log)), summary, log[:10])

    @unittest.skipUnless(os.path.exists(build.SOLVER), "solve.exe is not built")
    def test_one_teacher_per_course_in_every_variant(self):
        """Реальный запуск составления потока 2: в каждом варианте у курса один учитель на все его
        уроки недели. Пропускается, если решатель не собран.
        """
        settings = self.load("settings.json")
        settings["iterations"], settings["variants"] = 300000, 2

        self.save("settings.json", settings)

        self.act("run", stage="2", keep=False)
        # Настоящий запуск решателя: ждём с большим запасом, а не 60 секунд по умолчанию
        self.waitJob(600)

        variants = loadVariants(self.folder, "2")
        self.assertTrue(variants)

        # Оба недельных урока курса (например, два семинара ЕГЭ) ведёт один и тот же человек
        for _, variant in variants:
            for name, week in variant.items():
                teachers = {tuple(cell.get("teachers", [])) for _, _, cell in lessons(week)}
                self.assertLessEqual(len(teachers), 1, name)

    @unittest.skipUnless(os.path.exists(build.SOLVER), "solve.exe is not built")
    def test_keep_accepted_lessons_adds_only_missing_ones(self):
        """Режим «Оставить уже принятые уроки на месте» (keep): решатель ставит только недостающие уроки,
        а все принятые остаются ровно на своих местах.
        """
        settings = self.load("settings.json")
        settings["iterations"], settings["variants"] = 300000, 2

        self.save("settings.json", settings)

        before = self.load("answer.json")
        self.act("run", stage="2", keep=True)
        # Настоящий запуск решателя: ждём с большим запасом, а не 60 секунд по умолчанию
        self.waitJob(600)

        expected = sum(int(hours) for name in stageCourses(settings, "2") for hours in settings["classes"]["lessons"][name].values())

        for _, variant in loadVariants(self.folder, "2"):
            # Все уроки поставлены, а каждый принятый урок — ровно там, где был
            self.assertEqual(sum(len(lessons(week)) for name, week in variant.items() if name in stageCourses(settings, "2")), expected)

            for name, week in before.items():
                if name in variant:
                    self.assertEqual([(d, l) for d, l, _ in lessons(week)], [(d, l) for d, l, _ in lessons(variant[name])], name)


class JointRunTests(RealProjectCase):
    """«Запуск», когда «ЕГЭ основной» Потока 2 идёт вместе с Потоком 1 (проект builders.jointProject)."""
    NAME = "__test_joint_run__"

    COPIES = {jointCourse(2, "Математика"): jointCourse(1, "Математика"), jointCourse(2, "Русский язык"): jointCourse(1, "Русский язык")}

    def test_reset_source_stage_asks_about_copies(self):
        """AC-17: «Убрать из расписания» Потока 1 (ещё не начался), с которым идёт «ЕГЭ основной»
        Потока 2: без force вопрос со строкой web.run.confirm_reset_joint, файлы не меняются;
        с force у источников и у копий уроков нет.
        """
        settings, answer = jointProject()

        shiftStream(settings, 1, "2026-10-12")

        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        before = (self.raw("settings.json"), self.raw("answer.json"))

        body = self.ok("resetStage", stage="1")

        key = "web.run.confirm_reset_joint"
        self.assertIn("confirm", body)
        self.assertText(key, body["confirm"])
        self.assertIn(JOINT_LINE, body["confirm"])
        self.assertEqual((self.raw("settings.json"), self.raw("answer.json")), before)

        self.ok("resetStage", stage="1", force=True)

        answer = self.load("answer.json")
        self.assertFalse([name for pair in self.COPIES.items() for name in pair if hasLessons(answer, name)])

    def test_stage_of_only_copies_has_nothing_to_build(self):
        """AC-25: в Потоке 2 только курсы-копии — «Запуск» отвечает web.run.all_joint
        («Составлять нечего: все курсы этого потока присоединены к другому потоку»), сборка не начинается.
        """
        settings, answer = jointProject(streams=2)
        removeCourses(settings, [group["name"] for group in settings["classes"]["custom_groups"]
                                 if group.get("stream_id") == 2 and group["name"] not in self.COPIES])
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)

        with mock.patch.object(build, "SOLVER", os.path.abspath(__file__)), mock.patch.object(build, "startJob") as start:
            self.assertEqual(self.refused("run", stage="2"), translate("web.run.all_joint"))

        start.assert_not_called()

    def test_reset_stage_of_only_copies_names_shared_lessons(self):
        """AC-41: «Убрать из расписания» (ручной вызов, например с устаревшей страницы) у Потока 2, где в
        расписании стоят только копии: отказ web.run.nothing_to_reset_joint (про общие уроки — тот же
        текст, что подсказка у закрытой кнопки), а не «…только курсы, которые уже идут»
        (web.run.nothing_to_reset_any). answer.json и версии не меняются. Два случая: в Потоке 2
        только курсы-копии; у Потока 2 есть и свои курсы, но в расписании их уроков нет.
        """
        key = "web.run.nothing_to_reset_joint"
        self.assertNotEqual(translate(key), key, f"в ru.hjson нет текста {key}")

        for only_copies in (True, False):
            with self.subTest(only_copies=only_copies):
                settings, answer = jointProject(streams=2)

                if only_copies:
                    removeCourses(settings, [group["name"] for group in settings["classes"]["custom_groups"]
                                             if group.get("stream_id") == 2 and group["name"] not in self.COPIES])

                markJoint(settings, 2, JOINT_LINE, 1, answer)
                self.openProject(settings, answer)
                before, versions = self.raw("answer.json"), self.versions()

                self.assertEqual(self.refused("resetStage", stage="2"), translate(key))
                self.assertEqual(self.raw("answer.json"), before)
                self.assertEqual(self.versions(), versions)

    def test_reset_with_ask_is_one_question(self):
        """AC-40: страница спрашивает «Убрать?» через сервер (``ask``). У Потока 1 (ещё не начался), с которым
        идёт «ЕГЭ основной» Потока 2, — один вопрос: общий текст web.confirm_reset и строка
        web.run.confirm_reset_joint. У Потока 2, за которым никто не идёт, — вопрос только с общим текстом.
        Без force файлы не меняются; с force уроки убраны. У Потока 2 есть свой урок «Информатики» — иначе
        там убирать нечего.
        """
        settings, answer = jointProject()
        answer[jointCourse(2, "Информатика")] = courseWeek("Информатика", "Информатика #1", (4, 2))

        shiftStream(settings, 1, "2026-10-12")

        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        before = (self.raw("settings.json"), self.raw("answer.json"))

        for stage, joint in (("1", True), ("2", False)):
            with self.subTest(stage=stage):
                body = self.ok("resetStage", stage=stage, ask=True)

                self.assertTrue(body.get("danger"))
                self.assertEqual(body.get("yes"), translate("web.reset_yes"))
                self.assertIn(tr("web.confirm_reset", name=f"Поток {stage}"), body["confirm"])
                self.assertEqual(tr("web.run.confirm_reset_joint", line=JOINT_LINE, number=2) in body["confirm"], joint)
                self.assertEqual((self.raw("settings.json"), self.raw("answer.json")), before)

        self.ok("resetStage", stage="1", ask=True, force=True)

        answer = self.load("answer.json")
        self.assertFalse([name for pair in self.COPIES.items() for name in pair if hasLessons(answer, name)])


class KeepHintTests(unittest.TestCase):
    """Подсказка у галочки «Оставить уже принятые уроки на месте» (``web.run.keep_hint``) —
    «Смена преподавателя в подборе» (.spec/teacher-swap/SPEC.md, Р-8).
    """
    def test_keep_hint_mentions_teachers(self):
        """AC-21: подсказка говорит, что при включённой галочке не меняются ни уроки, ни преподаватели
        принятых курсов, и что для подбора преподавателей галочку нужно снять.
        """
        hint = translate("web.run.keep_hint")

        self.assertNotEqual(hint, "web.run.keep_hint")
        self.assertRegex(hint, re.compile(r"урок", re.I))
        self.assertRegex(hint, re.compile(r"преподавател", re.I))
        # «Снимите галочку…» — в одном предложении с подбором преподавателей
        sentences = re.split(r"(?<=[.!?])\s+", hint)
        self.assertTrue([text for text in sentences if re.search(r"сн(ими|ять)", text, re.I) and re.search(r"преподавател", text, re.I)], hint)
