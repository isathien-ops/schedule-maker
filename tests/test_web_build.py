"""Фоновое составление (`src/web/build.py`) без настоящего solve.exe.

Решатель подменяется поддельным процессом (``FakeSolver`` из `tests/real_project.py`): он запоминает,
с какими файлами его запустили, «печатает» строки и пишет заданный ответ в output.json. Нить сборки
``runJob`` в большинстве тестов вызывается прямо в тесте, поэтому всё детерминировано и быстро.
Через настоящую фоновую нить (действие «run» и ожидание ``waitJob``) идут только
``test_run_action_builds_in_background`` и ``test_keep_switch_does_not_count_copies``.

* ``RunJobTests`` — в варианты попадают только курсы этапа, зафиксированные курсы остаются как
  в расписании, сборка запоминает, какие курсы уже шли (started.json), прежние варианты не пропадают при ошибке или остановке, журнал сборки пишется
  и закрывается, строки хода сборки получают уровень; остановленная сборка заканчивается
  сообщением об остановке, даже если Windows ещё держит файлы решателя во временной папке,
  а без прежних вариантов — «Остановлено, вариантов нет», а не «прежние варианты остались»;
* ``BuildJournalTests`` — строки сервера перед выводом решателя: прогноз закреплений и идущие
  курсы без преподавателя, которые переходят в варианты как есть;
* ``RepeatedVariantTests`` — вариант, совпавший с уже сохранённым вариантом этой сборки, не
  сохраняется, номера сохранённых идут подряд, итог сборки это называет; сборка заканчивается
  как обычно, даже если строки «Шаг N из M» оборвались раньше M или их не было вовсе;
* ``TempFolderTests`` — удаление временной папки сборки: повтор, «папки уже нет», отказ;
* ``StopJobTests``, ``ForgetJobTests`` — ``stopJob``, ``jobState`` и ``forget`` без проекта;
* ``CloseWithProgramTests`` — решатель закрывается вместе с программой (Windows Job Object).
* ``JointBuildTests`` — «Линейка присоединяется к Потоку N»: курсы-копии не уходят в решатель
  (и в «оставить принятое»), а переносятся в каждый вариант с уроками источника.
* ``TeacherVariantsBuildTests`` — смена преподавателя в подборе (.spec/teacher-swap, AC-15): варианты,
  которые различаются только преподавателем курса, сохраняются оба, и «Предпросмотр» получает, кто
  ведёт курс в каждом из них.

Сборка через действие «Составить варианты» — `test_web_tab_run.py`.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from src.modules.translate import tr, translate
from src.modules.functions.solver_input import buildStageSettings
from src.modules.functions.stages import stageCourses, startedCourses
from src.modules.functions.variants import buildStarted, clearVariants, loadVariants, saveVariant
from src.web import build, ranking
from src.web.core import app
from tests.builders import JOINT_LINE, LEVEL_LINE, OWN_LINE, courseWeek, jointCourse, jointProject, markJoint
from tests.engine import NOTHING_TO_SOLVE
from tests.real_project import CHEM_OGE_2, RUS_8_2, FakeSolver, RealProjectCase, emptied, forecastText, relocated, unstaffed


def texts(job):
    """Тексты строк хода сборки (строки job["log"] — {"text", "level"})."""
    return [line["text"] for line in job["log"]]


class BuildCase(RealProjectCase):
    """База: задание сборки через startJob и нить runJob в этой же нити с поддельным решателем."""
    NAME = "__test_build__"

    def prepare(self, stage, total, keep=False):
        """Заводит задание через startJob, но без фоновой нити; возвращает job."""
        with mock.patch.object(build.threading, "Thread") as thread:
            build.startJob(self.NAME, stage, keep, total)

        self.assertIs(thread.call_args.kwargs["target"], build.runJob)
        thread.return_value.start.assert_called_once()
        job = build.JOBS[self.NAME]
        self.assertEqual((job["running"], job["stage"], job["total"], job["saved"], job["keep"]), (True, stage, total, 0, keep))
        return job

    def runSync(self, job, solver, journal=True):
        """Выполняет runJob в этой же нити с поддельным решателем; возвращает открытые журналы сборки."""
        opened = []
        real = build.openBuildLog

        def spy(project, stage):
            file = real(project, stage) if journal else None
            opened.append(file)
            return file

        with mock.patch.object(build.subprocess, "Popen", solver), mock.patch.object(build, "closeWithProgram") as bind, \
                mock.patch.object(build, "openBuildLog", spy):
            build.runJob(self.NAME, job)

        self.assertEqual(bind.call_count, len(solver.calls))
        self.assertFalse(job["running"])
        self.assertIsNotNone(job["finished"])
        self.assertIsNone(job.get("journal"))
        return opened


class RunJobTests(BuildCase):
    """Нить сборки runJob с поддельным решателем на копии реального проекта."""

    def test_variants_contain_only_stage_courses_and_replace_old_ones(self):
        """Два варианта потока 2: в каждом — уроки курсов этапа из ответа решателя (чужой курс
        отброшен), старые варианты удалены, в журнале — заголовки вариантов, вывод решателя и итог.
        """
        answer = self.load("answer.json")
        settings = self.load("settings.json")
        courses = stageCourses(settings, "2")
        output = {name: answer[name] for name in courses if name in answer}
        output["Чужой курс"] = answer["Поток 1 — ОГЭ — Химия"]
        saveVariant(self.folder, "2", 7, {"старый": []})

        # Варианты различаются уроком химии ОГЭ (одинаковые сохранились бы один раз)
        def variant(number):
            return {**output, CHEM_OGE_2: relocated(answer[CHEM_OGE_2], number - 1, 2)}

        job = self.prepare("2", 2)
        opened = self.runSync(job, FakeSolver(output=variant, lines=["шаг 1", "шаг 2"]))

        expected = [(number, {name: week for name, week in variant(number).items() if name in courses}) for number in (1, 2)]
        self.assertEqual(loadVariants(self.folder, "2"), expected)
        self.assertEqual((job["saved"], job["number"], job["stopped"]), (2, 2, False))

        header = f"{translate('menu.main.tab.run.variant')} 2 / 2"
        self.assertTrue(any(header in line for line in texts(job)), job["log"])
        self.assertIn("шаг 2", texts(job))
        self.assertEqual(texts(job).count("=== " + translate("web.run.solver_done") + " ==="), 2)
        self.assertEqual(job["log"][-1], {"text": "=== " + tr("menu.main.tab.run.variants_ready", count=2) + " ===", "level": "done"})

        # Журнал сборки: настройки, вывод решателя и итоговая строка; файл закрыт
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].closed)
        with open(opened[0].name, encoding="utf-8") as file:
            journal = file.read()
        self.assertIn(f"Проект: {self.NAME}; этап: 2; оставить принятые уроки: нет", journal)
        self.assertIn("шаг 1", journal)
        self.assertTrue(journal.rstrip("\n").endswith(job["log"][-1]["text"]))

    def test_log_lines_carry_their_level(self):
        """Уровень каждой строки хода сборки определяет сервер: заголовок варианта и итог запуска —
        head, предупреждения решателя — warn, «Шаг N из M» — progress, прочий вывод — text,
        итог удачной сборки — done.
        """
        lines = ["[Внимание] нет преподавателя", "[WARNING] unknown subject", "Шаг 1 из 2 | штраф 10", "обычная строка"]
        job = self.prepare("2", 1)
        self.runSync(job, FakeSolver(output={}, lines=lines))

        levels = {line["text"]: line["level"] for line in job["log"]}
        self.assertEqual([levels[line] for line in lines], ["warn", "warn", "progress", "text"])
        header = next(line for line in job["log"] if translate("menu.main.tab.run.variant") in line["text"])
        self.assertEqual(header["level"], "head")
        self.assertEqual(levels["=== " + translate("web.run.solver_done") + " ==="], "head")
        self.assertEqual(job["log"][-1]["level"], "done")
        self.assertTrue(all(line["level"] in build.LOG_LEVELS for line in job["log"]))

    def test_all_variants_use_the_input_taken_at_start(self):
        """Решатель получает настройки этапа (buildStageSettings), веса и число шагов проекта. Во время
        сборки страница их менять не даёт (отказ «идёт сборка»); даже если файлы проекта всё же
        изменились, следующие варианты строятся по прежним данным.
        """
        settings = self.load("settings.json")
        settings["iterations"] = 250000
        self.save("settings.json", settings)
        answer = self.load("answer.json")
        weights = self.load("weights.json")

        def change(process):
            # Пока строится первый вариант, тщательность и веса пытаются поменять: страница — отказ,
            # файлы — меняются в обход действий
            if process is solver.calls[0]["process"]:
                self.assertEqual(self.refused("setNumber", key="iterations", value=999999), translate("web.error.busy"))
                self.assertEqual(self.refused("setWeight", key="softSubjectPair", value=1), translate("web.error.busy"))
                self.save("settings.json", {**self.load("settings.json"), "iterations": 999999})
                self.save("weights.json", {**self.load("weights.json"), "softSubjectPair": 1})

        solver = FakeSolver(output={}, on_wait=change)
        job = self.prepare("2", 2)
        self.runSync(job, solver)

        self.assertEqual(len(solver.calls), 2)
        expected = json.loads(json.dumps(buildStageSettings(settings, answer, "2", ())))
        for call in solver.calls:
            self.assertEqual(call["args"][0], build.SOLVER)
            self.assertEqual(call["options"]["--iterations"], "250000")
            self.assertEqual(call["input"], expected)
            self.assertEqual(call["weights"], weights)
            self.assertEqual(call["kwargs"]["stderr"], subprocess.STDOUT)

        # А в проекте новые значения сохранились — для следующей сборки
        self.assertEqual(self.load("settings.json")["iterations"], 999999)

    def test_keep_mode_passes_accepted_lessons_to_solver(self):
        """Режим «оставить принятое»: решатель получает уроки курсов этапа, которые уже стоят в расписании."""
        settings = self.load("settings.json")
        answer = self.load("answer.json")
        keep = [name for name in stageCourses(settings, "2") if name in answer]
        solver = FakeSolver(output={})

        self.runSync(self.prepare("2", 1, keep=True), solver)

        self.assertEqual(solver.calls[0]["input"], json.loads(json.dumps(buildStageSettings(settings, answer, "2", keep))))
        self.assertNotEqual(solver.calls[0]["input"], json.loads(json.dumps(buildStageSettings(settings, answer, "2", ()))))

    def test_locked_courses_look_exactly_as_accepted(self):
        """Поток 1 уже идёт: что бы ни вернул решатель, зафиксированные курсы в варианте такие же,
        как в принятом расписании.
        """
        answer = self.load("answer.json")
        courses = stageCourses(self.load("settings.json"), "1")
        output = {name: emptied(answer[name]) for name in courses if name in answer}

        self.runSync(self.prepare("1", 1), FakeSolver(output=output))

        self.assertEqual(loadVariants(self.folder, "1"), [(1, {name: answer[name] for name in courses if name in answer})])

    def test_started_course_missing_lessons_keeps_its_lessons_unless_solver_placed_it(self):
        """Курс идёт, но ему не хватает уроков (не зафиксирован): если решатель его не вернул, вариант
        берёт его уроки из расписания; если вернул — его новую неделю.
        """
        name = "Поток 1 — ОГЭ — Химия"
        settings = self.load("settings.json")
        settings["classes"]["lessons"][name]["Химия"] = 3
        self.save("settings.json", settings)
        answer = self.load("answer.json")
        moved = copy.deepcopy(answer[name])
        week = emptied(moved)
        week[6][1] = {"subject": "Химия", "teachers": ["Баранникова Анна"]}

        self.runSync(self.prepare("1", 1), FakeSolver(output={}))
        self.assertEqual(loadVariants(self.folder, "1")[0][1][name], answer[name])

        self.runSync(self.prepare("1", 1), FakeSolver(output={name: week}))
        self.assertEqual(loadVariants(self.folder, "1")[0][1][name], week)

    def test_build_remembers_started_courses(self):
        """Сборка запоминает, какие курсы этапа уже шли (started.json, variants.buildStarted). Решатель
        сдвинул закреплённый урок идущего курса (закрепление не встало: например, преподаватель отметил
        «не может»): вариант не «собран до начала» (staleStarted пуст), но курс шёл при сборке —
        он в movedStarted (stages.movedStarted), и принять вариант нельзя. Итог сборки так и говорит
        (menu.main.tab.run.variants_unacceptable, строкой-предупреждением), а не зовёт выбрать вариант;
        job.unacceptable — True.
        """
        name = "Поток 1 — ОГЭ — Химия"
        settings = self.load("settings.json")
        settings["classes"]["lessons"][name]["Химия"] = 3
        self.save("settings.json", settings)
        answer = self.load("answer.json")
        week = emptied(answer[name])
        week[6][1] = {"subject": "Химия", "teachers": ["Баранникова Анна"]}

        job = self.prepare("1", 1)
        self.runSync(job, FakeSolver(output={name: week}))

        self.assertEqual(job["log"][-1], {"text": "=== " + tr("menu.main.tab.run.variants_unacceptable", count=1) + " ===", "level": "warn"})
        self.assertTrue(build.jobState(self.NAME)["unacceptable"])
        self.assertIn(name, buildStarted(self.folder, "1"))
        self.assertEqual(buildStarted(self.folder, "1"), startedCourses(settings, answer, stageCourses(settings, "1"), complete=False))
        with build.LOCK:
            item = ranking.rankedVariants(self.NAME, "1")[1][0]
        self.assertGreater(item["moved"], 0)
        self.assertEqual(item["staleStarted"], [])
        self.assertEqual([entry["course"] for entry in item["movedStarted"]], [name])

    def test_failed_solver_keeps_previous_variants(self):
        """Решатель завершился с ошибкой: новых вариантов нет, прежние остаются, в журнале — код ошибки."""
        saveVariant(self.folder, "2", 1, {"старый": []})
        job = self.prepare("2", 2)

        self.runSync(job, FakeSolver(output={"x": []}, code=3))

        self.assertEqual(loadVariants(self.folder, "2"), [(1, {"старый": []})])
        self.assertEqual(job["saved"], 0)
        self.assertEqual(texts(job).count("=== " + tr("web.run.solver_failed", code=3) + " ==="), 2)
        self.assertEqual(job["log"][-1], {"text": "=== " + translate("menu.main.tab.run.no_variants") + " ===", "level": "head"})

    def test_stop_pressed_while_solver_starts(self):
        """«Остановить» нажали, пока решатель запускался: процесс сразу прерывается, следующие
        варианты не строятся, прежние варианты остаются.
        """
        saveVariant(self.folder, "2", 1, {"старый": []})
        job = self.prepare("2", 3)
        solver = FakeSolver(output={}, on_start=lambda process: job.update(stopped=True))

        self.runSync(job, solver)

        self.assertEqual(len(solver.calls), 1)
        self.assertTrue(solver.calls[0]["process"].killed)
        self.assertIn("=== " + translate("web.run.solver_stopped") + " ===", texts(job))
        self.assertEqual(texts(job)[-1], "=== " + translate("web.run.stopped_kept") + " ===")
        self.assertEqual(loadVariants(self.folder, "2"), [(1, {"старый": []})])

    def test_stop_without_previous_variants(self):
        """У этапа вариантов не было, «Остановить» нажали сразу: итог «Остановлено, вариантов нет»
        (web.run.stopped_none), а не «прежние варианты остались».
        """
        clearVariants(self.folder, "2")
        job = self.prepare("2", 3)
        solver = FakeSolver(output={}, on_start=lambda process: job.update(stopped=True))

        self.runSync(job, solver)

        self.assertEqual(texts(job)[-1], "=== " + translate("web.run.stopped_none") + " ===")

    def test_stop_while_windows_still_holds_solver_files(self):
        """Ошибка, которая была: «Остановить» примерно в одном случае из десяти давало «Не получилось
        составить вариант (код ошибки ?)». Сразу после снятия решателя Windows ещё держит его файлы,
        и первая попытка удалить временную папку падает с PermissionError. Теперь удаление
        повторяется: сборка заканчивается сообщением об остановке, ошибок в журнале нет, папка удалена.
        """
        saveVariant(self.folder, "2", 1, {"старый": []})
        job = self.prepare("2", 3)
        solver = FakeSolver(output={}, on_start=lambda process: job.update(stopped=True))
        real = shutil.rmtree
        attempts = []

        def busyOnce(path, *args, **kwargs):
            """Первая попытка — как у Windows с занятым input.json, следующие — настоящее удаление."""
            attempts.append(path)

            if len(attempts) == 1:
                raise PermissionError(32, "Процесс не может получить доступ к файлу", os.path.join(path, "input.json"))

            return real(path, *args, **kwargs)

        with mock.patch.object(build.shutil, "rmtree", busyOnce), mock.patch.object(build.time, "sleep") as sleep, \
                self.assertNoLogs(app.logger, "ERROR"):
            self.runSync(job, solver)

        folder = os.path.dirname(solver.calls[0]["options"]["--input"])
        self.assertEqual(attempts, [folder, folder])
        sleep.assert_called_once_with(build.CLEANUP_PAUSE)
        self.assertFalse(os.path.exists(folder))
        self.assertEqual(job["log"][-1]["text"], "=== " + translate("web.run.stopped_kept") + " ===")
        self.assertNotIn("=== " + tr("web.run.solver_failed", code="?") + " ===", texts(job))
        self.assertEqual(loadVariants(self.folder, "2"), [(1, {"старый": []})])

    def test_stage_deleted_during_build_saves_nothing(self):
        """Поток удалили, пока строился вариант: вариант не сохраняется, папка этапа не трогается."""
        saveVariant(self.folder, "2", 1, {"старый": []})

        def removeStream(process):
            settings = self.load("settings.json")
            settings["classes"]["custom_groups"] = [group for group in settings["classes"]["custom_groups"] if group.get("stream_id") != 2]
            self.save("settings.json", settings)

        job = self.prepare("2", 1)
        self.runSync(job, FakeSolver(output={}, on_wait=removeStream))

        self.assertEqual(job["saved"], 0)
        self.assertEqual(loadVariants(self.folder, "2"), [(1, {"старый": []})])
        self.assertEqual(texts(job)[-1], "=== " + translate("menu.main.tab.run.no_variants") + " ===")

    def test_solver_that_cannot_start_ends_the_job_with_a_message(self):
        """Решатель не запустился (ошибка ОС): сборка не «висит», ошибка в журнале программы,
        последняя строка хода сборки — «ошибка», журнал сборки закрыт с этой строкой.
        """
        job = self.prepare("2", 1)
        opened = []
        real = build.openBuildLog

        def spy(project, stage):
            opened.append(real(project, stage))
            return opened[-1]

        with mock.patch.object(build.subprocess, "Popen", side_effect=OSError("нет решателя")), mock.patch.object(build, "openBuildLog", spy), \
                self.assertLogs(app.logger, "ERROR"):
            build.runJob(self.NAME, job)

        self.assertFalse(job["running"])
        self.assertEqual(job["log"][-1], {"text": "=== " + tr("web.run.solver_failed", code="?") + " ===", "level": "head"})
        self.assertTrue(opened[0].closed)
        with open(opened[0].name, encoding="utf-8") as file:
            self.assertTrue(file.read().rstrip("\n").endswith(job["log"][-1]["text"]))

    def test_build_works_without_journal_file(self):
        """Файл журнала сборки создать не удалось: варианты всё равно строятся и сохраняются."""
        job = self.prepare("2", 1)
        self.runSync(job, FakeSolver(output={}), journal=False)

        self.assertEqual(job["saved"], 1)
        self.assertEqual(len(loadVariants(self.folder, "2")), 1)

    def test_long_output_keeps_only_last_lines(self):
        """Вывод решателя в памяти — не больше 2000 последних строк; странице уходят последние 400."""
        job = self.prepare("2", 1)
        self.runSync(job, FakeSolver(output={}, lines=[f"строка {index}" for index in range(2500)]))

        self.assertLessEqual(len(job["log"]), 2002)
        self.assertNotIn("строка 0", texts(job))
        self.assertIn("строка 2499", texts(job))

        shown = build.jobState(self.NAME)
        self.assertEqual(shown["log"], job["log"][-400:])
        self.assertEqual((shown["running"], shown["saved"], shown["total"], shown["stage"]), (False, 1, 1, "2"))
        self.assertGreaterEqual(shown["seconds"], 0)

    def test_run_action_builds_in_background(self):
        """Действие run запускает сборку в фоне; по /job видно, что она закончилась и сколько вариантов
        готово; в состоянии проекта у этапа появляются варианты.
        """
        self.ok("setNumber", key="variants", value=2)
        answer = self.load("answer.json")
        solver = FakeSolver(output=lambda number: {CHEM_OGE_2: relocated(answer[CHEM_OGE_2], number - 1, 2)})

        with mock.patch.object(build, "SOLVER", os.path.abspath(__file__)), mock.patch.object(build.subprocess, "Popen", solver), \
                mock.patch.object(build, "closeWithProgram"):
            body = self.ok("run", stage="2")
            self.assertEqual(body["state"]["job"]["stage"], "2")
            self.waitJob(20)

        job = self.client.get(f"/api/project/{self.NAME}/job").get_json()
        self.assertEqual((job["running"], job["saved"], job["total"], job["stopped"]), (False, 2, 2, False))
        stage = next(item for item in self.state()["stages"] if item["key"] == "2")
        self.assertEqual(stage["variants"], 2)
        self.assertEqual(solver.calls[0]["args"][0], os.path.abspath(__file__))


def journalText(opened):
    """Текст журнала сборки — первого файла из открытых за сборку (см. BuildCase.runSync)."""
    with open(opened[0].name, encoding="utf-8") as file:
        return file.read()


def headerIndex(lines):
    """Номер первой строки хода сборки с заголовком варианта «=== …: Вариант N / M ===»."""
    return next(index for index, line in enumerate(lines) if translate("menu.main.tab.run.variant") in line)


class BuildJournalTests(BuildCase):
    """Строки сервера в ходе и журнале сборки до вывода решателя."""

    def test_forecast_line_comes_before_solver_output(self):
        """Перед первым вариантом сервер один раз пишет прогноз (solver_input.pinForecast): поток 2
        с галочкой «Оставить уже принятые уроки на месте» — 41 из 62, без неё — 0 из 62; строка
        есть и в журнале сборки. Идущих курсов без преподавателя в потоке 2 нет — о них ни слова.
        """
        for keep, pinned in ((True, 41), (False, 0)):
            forecast = tr("web.run.pin_forecast", pinned=pinned, total=62, free=62 - pinned)
            job = self.prepare("2", 2, keep=keep)
            opened = self.runSync(job, FakeSolver(output={}, lines=["вывод решателя"]))

            lines = texts(job)
            self.assertEqual(lines.count(forecast), 1, lines[:5])
            self.assertLess(lines.index(forecast), headerIndex(lines))
            self.assertFalse([line for line in lines if translate("web.run.carried_no_teacher").split("{count}")[0] in line])

            journal = journalText(opened)
            self.assertIn(forecast, journal)
            self.assertLess(journal.index(forecast), journal.index("вывод решателя"))

    def test_forecast_names_lessons_without_teacher(self):
        """Курс потока 2 (1 урок) никто не может вести: прогноз не обещает его подобрать — «подберёт
        программа» 20, а не 21, и хвост «без преподавателя (не ставятся): 1», как в строке решателя.
        """
        self.save("settings.json", unstaffed(self.load("settings.json"), RUS_8_2, "Русский язык"))
        job = self.prepare("2", 1, keep=True)
        self.runSync(job, FakeSolver(output={}))

        forecast = tr("web.run.pin_forecast_no_teacher", pinned=41, total=62, free=20, noTeacher=1)
        self.assertEqual(forecast, forecastText({"pinned": 41, "total": 62, "free": 20, "noTeacher": 1}))
        self.assertEqual(texts(job).count(forecast), 1, texts(job)[:5])
        self.assertLess(texts(job).index(forecast), headerIndex(texts(job)))

    def test_started_courses_without_teacher_are_named(self):
        """Поток 1: идущий курс без преподавателя (физика ЕГЭ продвинутый, 2 урока) решатель не
        получает — сервер переносит его уроки в варианты как есть и пишет об этом до первого
        варианта; в прогнозе этих уроков нет (60 из 60).
        """
        job = self.prepare("1", 1)
        opened = self.runSync(job, FakeSolver(output={}))

        lines = texts(job)
        carried = tr("web.run.carried_no_teacher", count=2)
        forecast = tr("web.run.pin_forecast", pinned=60, total=60, free=0)

        for line in (carried, forecast):
            self.assertEqual(lines.count(line), 1, lines[:5])
            self.assertLess(lines.index(line), headerIndex(lines))
            self.assertIn(line, journalText(opened))


class RepeatedVariantTests(BuildCase):
    """Совпавшие варианты одной сборки и конец сборки, когда решатель закончил подбор раньше."""

    def outputs(self):
        """Три разных ответа решателя для потока 2: принятое расписание (a) и оно же с уроком
        химии ОГЭ в другом месте (b, c).
        """
        base = self.stageVariant("2")

        def moved(day):
            return {**base, CHEM_OGE_2: relocated(base[CHEM_OGE_2], day, 2)}

        return base, moved(0), moved(1)

    def build(self, runs, lines=("решатель работает",)):
        """Сборка потока 2, где запуск номер n возвращает runs[n - 1]; возвращает (job, открытые журналы)."""
        job = self.prepare("2", len(runs))
        opened = self.runSync(job, FakeSolver(output=lambda number: runs[number - 1], lines=lines))

        return job, opened

    def repeatedLines(self, job):
        """Строки хода сборки «Вариант N совпал с сохранённым вариантом M — не сохранён»: [(N, M)] по порядку."""
        return [(number, same) for number in range(1, job["total"] + 1) for same in range(1, number)
                if any(tr("web.run.variant_repeated", number=number, same=same) in line for line in texts(job))]

    def savedAsLines(self, job):
        """Строки «Сохранён как вариант M» с номером запуска N из заголовка «Вариант N / …» над ними: [(N, M)]."""
        found, number = [], None

        for line in texts(job):
            header = re.search(rf"{translate('menu.main.tab.run.variant')} (\d+) / ", line)
            number = int(header.group(1)) if header else number
            found += [(number, saved) for saved in range(1, job["total"] + 1) if line == "=== " + tr("web.run.variant_saved_as", number=saved) + " ==="]

        return found

    def test_repeated_variant_is_not_saved(self):
        """Запуски дали a, a, b, b, c: сохранены a, b, c под номерами 1, 2, 3 (подряд); о втором и
        четвёртом запуске — строка «совпал» с номером сохранённого варианта (его видно на
        «Предпросмотре»). После первого совпадения номер запуска в заголовке «Вариант N / 5» и номер
        на «Предпросмотре» расходятся — у третьего и пятого запуска строка «Сохранён как вариант 2»
        («… 3»), у первого её нет. Итог называет и разные варианты, и совпавшие; ход сборки для
        страницы отдаёт их число (repeats).
        """
        a, b, c = self.outputs()
        job, opened = self.build([a, a, b, b, c])

        self.assertEqual(loadVariants(self.folder, "2"), [(1, a), (2, b), (3, c)])
        self.assertEqual((job["saved"], job["repeats"], job["number"], job["total"]), (3, 2, 5, 5))
        self.assertEqual(self.repeatedLines(job), [(2, 1), (4, 2)])
        self.assertEqual(self.savedAsLines(job), [(3, 2), (5, 3)])
        self.assertIn(tr("web.run.variant_repeated", number=4, same=2), journalText(opened))
        self.assertIn(tr("web.run.variant_saved_as", number=3), journalText(opened))

        summary = tr("menu.main.tab.run.variants_ready_repeated", count=3, repeats=2)
        self.assertEqual(job["log"][-1], {"text": f"=== {summary} ===", "level": "done"})
        state = build.jobState(self.NAME)
        self.assertEqual((state["saved"], state["repeats"]), (3, 2))

    def test_all_variants_alike(self):
        """Все три запуска дали одно и то же (например, подбирать было нечего): сохранён один
        вариант, два совпавших названы в ходе сборки и в итоге.
        """
        a, _, _ = self.outputs()
        job, _ = self.build([a, a, a])

        self.assertEqual(loadVariants(self.folder, "2"), [(1, a)])
        self.assertEqual((job["saved"], job["repeats"]), (1, 2))
        self.assertEqual(self.repeatedLines(job), [(2, 1), (3, 1)])
        self.assertEqual(self.savedAsLines(job), [])
        self.assertEqual(texts(job)[-1], "=== " + translate("menu.main.tab.run.variants_all_same") + " ===")

    def test_variants_of_previous_build_do_not_count(self):
        """Прежние варианты этапа (прошлой сборки) не в счёт: новый вариант, совпавший с прежним,
        сохраняется, прежние заменяются; итог — обычный «Готово вариантов».
        """
        a, b, c = self.outputs()
        saveVariant(self.folder, "2", 1, a)
        saveVariant(self.folder, "2", 2, b)

        job, _ = self.build([a, c])

        self.assertEqual(loadVariants(self.folder, "2"), [(1, a), (2, c)])
        self.assertEqual((job["saved"], job["repeats"]), (2, 0))
        self.assertEqual(self.repeatedLines(job), [])
        self.assertEqual(texts(job)[-1], "=== " + tr("menu.main.tab.run.variants_ready", count=2) + " ===")

    def test_build_ends_when_steps_stop_early_or_are_missing(self):
        """Решатель остановил подбор раньше (строки «Шаг N из M» оборвались до M) или не подбирал
        вовсе (строк «Шаг» нет): сборка всё равно доходит до конца — все варианты построены
        (number = total), задание закончено, итог — последней строкой.
        """
        early = [
            "Закреплено 61 из 62 уроков, подбирается 1",
            "Шаг 1000000 из 100000000 | 0.9 с | неудобства: 12786 (лучшее пока 12786)",
            "Шаг 2000000 из 100000000 | 1.8 с | неудобства: 12786 (лучшее пока 12786)",
            "Остановлено на шаге 2000000 из 100000000: подбирается только 1 урок, лучшее не менялось 1 млн шагов",
        ]
        nothing = ["Закреплено 62 из 62 уроков, подбирается 0", NOTHING_TO_SOLVE]
        a, b, _ = self.outputs()

        job, _ = self.build([a, b], lines=early)
        state = build.jobState(self.NAME)
        self.assertEqual((state["running"], state["number"], state["total"], state["saved"], state["stopped"]), (False, 2, 2, 2, False))
        self.assertEqual([line["level"] for line in job["log"] if line["text"].startswith("Шаг ")], ["progress"] * 4)
        self.assertEqual(job["log"][-1], {"text": "=== " + tr("menu.main.tab.run.variants_ready", count=2) + " ===", "level": "done"})

        job, _ = self.build([a, a], lines=nothing)
        state = build.jobState(self.NAME)
        self.assertEqual((state["running"], state["number"], state["total"], state["saved"], state["repeats"]), (False, 2, 2, 1, 1))
        self.assertEqual(job["log"][-1]["level"], "done")


class TempFolderTests(unittest.TestCase):
    """Временная папка сборки (build._tempFolder / build._removeFolder) без решателя."""
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="schedule-test-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def test_folder_is_created_and_removed(self):
        """Папка есть внутри with и исчезает после него, даже если внутри была ошибка."""
        with self.assertRaises(RuntimeError), build._tempFolder() as folder:
            self.assertTrue(os.path.isdir(folder))
            raise RuntimeError("ошибка сборки")

        self.assertFalse(os.path.exists(folder))

    def test_already_removed_folder_is_not_an_error(self):
        """Папки уже нет: удалять нечего — ни повторов, ни предупреждений."""
        os.rmdir(self.folder)

        with mock.patch.object(build.time, "sleep") as sleep, self.assertNoLogs(build.log, "WARNING"):
            build._removeFolder(self.folder)

        sleep.assert_not_called()

    def test_folder_that_stays_busy_is_left_with_a_warning(self):
        """Файлы так и не отпустили: CLEANUP_ATTEMPTS попыток, затем предупреждение в журнале
        программы; исключения нет, папка остаётся.
        """
        with mock.patch.object(build.shutil, "rmtree", side_effect=PermissionError("занято")) as rmtree, \
                mock.patch.object(build.time, "sleep") as sleep, self.assertLogs(build.log, "WARNING"):
            build._removeFolder(self.folder)

        self.assertEqual(rmtree.call_count, build.CLEANUP_ATTEMPTS)
        self.assertEqual(sleep.call_count, build.CLEANUP_ATTEMPTS - 1)
        self.assertTrue(os.path.isdir(self.folder))


class StopJobTests(unittest.TestCase):
    """stopJob и jobState без проекта: задания в памяти."""
    NAME = "__test_stop__"

    def job(self, running, process):
        """Задание в JOBS с данным процессом; удаляется после теста."""
        build.JOBS[self.NAME] = {"stage": "2", "keep": False, "number": 1, "total": 2, "saved": 1, "repeats": 0, "stopped": False, "running": running,
                                 "started": 100.0, "finished": None if running else 112.9, "log": ["a"], "process": process}
        self.addCleanup(build.forget, self.NAME)
        return build.JOBS[self.NAME]

    def test_stop_kills_running_solver(self):
        """Идёт сборка и решатель работает: задание помечается остановленным, процесс прерывается."""
        process = mock.Mock()
        process.poll.return_value = None
        job = self.job(True, process)

        build.stopJob(self.NAME)

        self.assertTrue(job["stopped"])
        process.kill.assert_called_once()

    def test_stop_does_not_kill_finished_solver(self):
        """Решатель уже завершился (между вариантами): задание помечается, процесс не трогается."""
        process = mock.Mock()
        process.poll.return_value = 0
        job = self.job(True, process)

        build.stopJob(self.NAME)

        self.assertTrue(job["stopped"])
        process.kill.assert_not_called()

    def test_stop_without_running_job_changes_nothing(self):
        """Сборка уже закончилась или её не было: «Остановить» ничего не меняет."""
        process = mock.Mock()
        job = self.job(False, process)

        build.stopJob(self.NAME)
        build.stopJob("__test_no_such_job__")

        self.assertFalse(job["stopped"])
        process.kill.assert_not_called()
        self.assertNotIn("__test_no_such_job__", build.JOBS)

    def test_job_state(self):
        """Ход сборки для страницы: время считается до окончания сборки, repeats — сколько вариантов
        совпали с уже сохранёнными; unacceptable — пока итог не сказал, что принять нельзя ни один, False;
        без сборок — None.
        """
        self.job(False, None)
        self.assertEqual(build.jobState(self.NAME), {"running": False, "stage": "2", "number": 1, "total": 2, "saved": 1, "repeats": 0,
                                                     "stopped": False, "seconds": 12, "unacceptable": False, "log": ["a"]})
        self.assertFalse(build.running(self.NAME))
        self.assertIsNone(build.jobState("__test_no_such_job__"))


class ForgetJobTests(unittest.TestCase):
    """build.forget: задание сборки удалённого проекта забывается."""
    def test_forget(self):
        """Задание проекта пропадает из JOBS, чужие остаются; забыть несуществующее — не ошибка."""
        with mock.patch.dict(build.JOBS, {"__test_a__": {"running": False}, "__test_b__": {"running": False}}, clear=True):
            build.forget("__test_a__")
            build.forget("__test_none__")

            self.assertEqual(list(build.JOBS), ["__test_b__"])


class CloseWithProgramTests(unittest.TestCase):
    """Привязка процесса решателя к программе (Windows Job Object)."""
    def fakeKernel(self, job=123, configured=1):
        """Поддельная kernel32: CreateJobObjectW возвращает `job`, SetInformationJobObject — `configured`."""
        kernel = mock.MagicMock()
        kernel.CreateJobObjectW.return_value = job
        kernel.SetInformationJobObject.return_value = configured
        return kernel

    def test_not_windows_does_nothing(self):
        """Не Windows: функция ничего не делает и не пишет ошибок."""
        with mock.patch.object(build.os, "name", "posix"), mock.patch("ctypes.WinDLL") as windll, self.assertNoLogs(build.log, "ERROR"):
            build.closeWithProgram(object())
        windll.assert_not_called()

    def test_job_object_is_created_once_and_process_assigned(self):
        """Объект задания создаётся один раз; процесс решателя добавляется в него."""
        kernel = self.fakeKernel()
        process = mock.Mock(_handle=77)

        with mock.patch.object(build.os, "name", "nt"), mock.patch.object(build, "_SOLVER_JOB", None), mock.patch("ctypes.WinDLL", return_value=kernel):
            build.closeWithProgram(process)
            build.closeWithProgram(process)
            self.assertEqual(build._SOLVER_JOB, 123)

        kernel.CreateJobObjectW.assert_called_once()
        self.assertEqual([call.args for call in kernel.AssignProcessToJobObject.call_args_list], [(123, 77), (123, 77)])

    def test_failed_job_object_leaves_process_alone(self):
        """Объект задания не создался или не настроился: процесс не привязывается, ошибок нет."""
        for job, configured in ((0, 1), (123, 0)):
            kernel = self.fakeKernel(job, configured)

            with mock.patch.object(build.os, "name", "nt"), mock.patch.object(build, "_SOLVER_JOB", None), mock.patch("ctypes.WinDLL", return_value=kernel), \
                    self.assertNoLogs(build.log, "ERROR"):
                build.closeWithProgram(mock.Mock(_handle=77))
                self.assertIsNone(build._SOLVER_JOB)

            kernel.AssignProcessToJobObject.assert_not_called()

    def test_error_is_logged_not_raised(self):
        """Ошибка привязки (например, у процесса нет описателя) записывается в журнал, сборке не мешает."""
        with mock.patch.object(build.os, "name", "nt"), mock.patch.object(build, "_SOLVER_JOB", None), \
                mock.patch("ctypes.WinDLL", return_value=self.fakeKernel()), self.assertLogs(build.log, "ERROR"):
            build.closeWithProgram(object())

    @unittest.skipUnless(os.name == "nt", "Job Object есть только в Windows")
    def test_real_process_is_put_into_job_object(self):
        """Настоящий дочерний процесс попадает в объект задания программы (Windows проверяет это сама)."""
        import ctypes
        from ctypes import wintypes

        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)

        build.closeWithProgram(process)
        self.assertIsNotNone(build._SOLVER_JOB)

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        result = wintypes.BOOL()
        self.assertTrue(kernel32.IsProcessInJob(int(process._handle), build._SOLVER_JOB, ctypes.byref(result)))
        self.assertTrue(result.value)


class JointBuildTests(BuildCase):
    """Сборка потока-копии («Линейка присоединяется к Потоку N», AC-21, AC-24) на проекте
    ``builders.jointProject``: «ЕГЭ основной» Потока 2 отмечена «вместе с Потоком 1» (``markJoint``).
    Копии в решатель не уходят, а в каждый вариант переносятся с уроками источника.
    """
    NAME = "__test_build_joint__"

    def useJoint(self, accepted=True, own=None):
        """Подменяет проект на jointProject (Поток 1 принят, если ``accepted``) с отметкой «ЕГЭ основной»
        Потока 2 «вместе с Потоком 1»; ``own`` — уроки обычных курсов Потока 2 {курс: неделя}.
        Сборка строит по одному варианту за запуск. Возвращает (settings, answer, {копия: источник}).
        """
        settings, answer = jointProject(accepted=accepted)
        copies = markJoint(settings, 2, JOINT_LINE, 1, answer)
        answer.update(own or {})
        settings["variants"] = 1
        self.useProject(settings, answer)

        return settings, answer, copies

    def test_copies_are_carried_into_every_variant_as_accepted_at_start(self):
        """AC-21: копий нет во входе решателя, но каждый вариант этапа «2» содержит их с уроками
        источника на момент начала сборки — даже если решатель их не вернул, а расписание Потока 1
        изменилось, пока шла сборка.
        """
        _, answer, copies = self.useJoint()
        informatics = jointCourse(2, "Информатика")

        def moveSources(process):
            # Пока строится первый вариант, уроки «ЕГЭ основной» Потока 1 (и его копий) сдвигаются в файле
            if process is solver.calls[0]["process"]:
                changed = self.load("answer.json")

                for course in list(copies) + list(copies.values()):
                    changed[course] = relocated(changed[course], 4, 2)

                self.save("answer.json", changed)

        solver = FakeSolver(output=lambda number: {informatics: courseWeek("Информатика", "Информатика #1", (number - 1, 2))}, on_wait=moveSources)
        job = self.prepare("2", 2)
        self.runSync(job, solver)

        for call in solver.calls:
            self.assertFalse(set(copies) & {group["name"] for group in call["input"]["classes"]["custom_groups"]})

        variants = loadVariants(self.folder, "2")
        self.assertEqual(len(variants), 2)

        for number, variant in variants:
            self.assertEqual(variant[informatics], courseWeek("Информатика", "Информатика #1", (number - 1, 2)))

            for course, source in copies.items():
                self.assertEqual(variant.get(course), answer[source], (number, course))

    def test_keep_build_leaves_copies_out_and_carries_them(self):
        """AC-24: «оставить принятое» (keep) в потоке-копии: копий нет ни в закреплениях, ни в курсах
        входа решателя; принятые обычные курсы Потока 2 закреплены; прогноз до первого варианта — без
        часов копий (3 из 6); копии перенесены в каждый вариант с уроками источника.
        """
        level_math, informatics = jointCourse(2, "Математика", LEVEL_LINE), jointCourse(2, "Информатика")
        own = {level_math: courseWeek("Математика", "Математика #2", (1, 0), (3, 0)), informatics: courseWeek("Информатика", "Информатика #1", (4, 1))}
        _, answer, copies = self.useJoint(own=own)

        solver = FakeSolver(output=lambda number: {**own, jointCourse(2, "Математика", OWN_LINE): courseWeek("Математика", "Математика #3", (number, 1))})
        job = self.prepare("2", 2, keep=True)
        self.runSync(job, solver)

        for call in solver.calls:
            self.assertEqual(call["input"]["constants"], {level_math: {"1-0": "Математика", "3-0": "Математика"}, informatics: {"4-1": "Информатика"}})
            self.assertFalse(set(copies) & {group["name"] for group in call["input"]["classes"]["custom_groups"]})

        self.assertIn(tr("web.run.pin_forecast", pinned=3, total=6, free=3), texts(job))

        variants = loadVariants(self.folder, "2")
        self.assertEqual(len(variants), 2)

        for number, variant in variants:
            for course, source in copies.items():
                self.assertEqual(variant.get(course), answer[source], (number, course))

    def test_keep_switch_does_not_count_copies(self):
        """AC-24: решение «оставить принятое» действием run принимается по ``expected`` и ``placed``
        без копий. Стоят только копии — keep остаётся (своим курсам ещё не хватает уроков).
        Все обычные курсы Потока 2 стоят, а копии ждут Поток 1 — keep выключается: добавлять
        Потоку 2 самому нечего, недостающие уроки копий встанут из Потока 1.
        """
        own = {
            jointCourse(2, "Информатика"): courseWeek("Информатика", "Информатика #1", (4, 1)),
            jointCourse(2, "Математика", LEVEL_LINE): courseWeek("Математика", "Математика #2", (1, 0), (3, 0)),
            jointCourse(2, "Русский язык", LEVEL_LINE): courseWeek("Русский язык", "Русский язык #2", (0, 2), (2, 2)),
            jointCourse(2, "Математика", OWN_LINE): courseWeek("Математика", "Математика #3", (4, 0)),
        }

        for accepted, mine, keep in ((True, {}, True), (False, own, False)):
            self.useJoint(accepted=accepted, own=mine)

            with mock.patch.object(build, "SOLVER", os.path.abspath(__file__)), mock.patch.object(build.subprocess, "Popen", FakeSolver(output={})), \
                    mock.patch.object(build, "closeWithProgram"):
                self.ok("run", stage="2", keep=True)
                self.waitJob(20)

            self.assertIs(build.JOBS[self.NAME]["keep"], keep, accepted)


class TeacherVariantsBuildTests(BuildCase):
    """Варианты, которые различаются только преподавателем (.spec/teacher-swap, AC-15), на проекте
    ``builders.jointProject`` без отметок «вместе с»: Поток 1 принят, у Потока 2 уроков нет.

    «ОГЭ — Математика» Потока 2 (1 урок) могут вести «Математика #1» … «#3» — равноценные кандидаты.
    Поддельный решатель в запуске 1 ставит её урок (3, 2) «Математике #2», в запуске 2 — тот же урок
    «Математике #3»; «Информатика» Потока 2 в обоих запусках одна и та же.
    """
    NAME = "__test_build_teachers__"
    # Кто ведёт «ОГЭ — Математика» Потока 2 в запуске 1 и 2
    BY_RUN = {1: "Математика #2", 2: "Математика #3"}

    def setUp(self):
        super().setUp()
        settings, answer = jointProject()
        self.useProject(settings, answer)
        self.math, self.informatics = jointCourse(2, "Математика", OWN_LINE), jointCourse(2, "Информатика")

    def output(self, number):
        """Ответ решателя в запуске ``number``: одни и те же слоты, у математики свой преподаватель."""
        return {self.math: courseWeek("Математика", self.BY_RUN[number], (3, 2)), self.informatics: courseWeek("Информатика", "Информатика #1", (4, 1))}

    def build(self):
        """Сборка этапа «2» без «оставить принятое» на два запуска; возвращает (job, решатель)."""
        solver = FakeSolver(output=self.output)
        job = self.prepare("2", 2)
        self.runSync(job, solver)

        return job, solver

    def test_variants_differing_only_by_teacher_are_both_saved(self):
        """AC-15: вариант, где курс ведёт другой преподаватель при тех же слотах, — не «совпал»:
        сохранены оба (1 и 2), строк «совпал» нет, итог — обычный «Готово вариантов: 2». И на «Предпросмотре»
        они различимы: /variants называет у каждого своего преподавателя курса (``teachers``), а сам
        курс — в ``teacherCourses``; иначе завуч видел бы два одинаковых варианта.
        """
        job, _ = self.build()

        self.assertEqual(loadVariants(self.folder, "2"), [(1, self.output(1)), (2, self.output(2))])
        self.assertEqual((job["saved"], job["repeats"]), (2, 0))
        # Середина строки «Вариант N совпал с сохранённым вариантом M — …» — без номеров
        repeated = translate("web.run.variant_repeated").split("{number}")[1].split("{same}")[0]
        self.assertFalse([line for line in texts(job) if repeated in line])
        self.assertEqual(job["log"][-1], {"text": "=== " + tr("menu.main.tab.run.variants_ready", count=2) + " ===", "level": "done"})

        body = self.variants("2")
        self.assertIn(self.math, body.get("teacherCourses", []))
        self.assertEqual({item["number"]: item.get("teachers", {}).get(self.math) for item in body["variants"]},
                         {number: [name] for number, name in self.BY_RUN.items()})

    def test_preview_names_teacher_of_each_variant(self):
        """AC-15: в ответе /variants курс, у которого преподаватель различается между вариантами,
        есть в ``teacherCourses``, а у каждого варианта ``teachers[курс]`` — свой преподаватель
        («Математика #2» у варианта 1, «Математика #3» у варианта 2). «Информатика» (в обоих вариантах
        «Информатика #1», в расписании её нет) в ``teacherCourses`` не попадает, хотя в ``teachers``
        вариантов она есть. Лимит курсов ни один вариант не превышает (AC-20, ``variants.teacherOverLimit``).
        """
        self.build()
        body = self.variants("2")

        self.assertIn(self.math, body.get("teacherCourses", []))
        self.assertNotIn(self.informatics, body.get("teacherCourses", []))
        self.assertEqual(sorted(item["number"] for item in body["variants"]), [1, 2])

        for item in body["variants"]:
            teachers = item.get("teachers", {})
            self.assertEqual(teachers.get(self.math), [self.BY_RUN[item["number"]]], item["number"])
            self.assertEqual(teachers.get(self.informatics), ["Информатика #1"], item["number"])

        from src.modules.functions.variants import teacherOverLimit

        settings, answer = self.load("settings.json"), self.load("answer.json")

        for number, variant in loadVariants(self.folder, "2"):
            self.assertEqual(list(teacherOverLimit(settings, answer, "2", variant)), [], number)
