"""Файлы открытого проекта на сервере (`src/web/project.py`).

* ``ProjectPathTests`` — имя проекта из адреса не может увести за пределы папки projects;
* ``HiddenFolderTests`` — скрытая папка «.имя» — не проект;
* ``LoadAnswerTests`` — чтение принятого расписания: ``loadAnswer`` и ``loadAnswerOrEmpty``;
* ``LessonsTextTests`` — «1 урок / 2 урока / 5 уроков»;
* ``JointSyncTests`` — запись settings.json и answer.json согласует курсы-копии «линейки, которая
  присоединяется к Потоку N» с источниками (.spec/joint-lines/SPEC.md, Р-2);
* ``ConflictStagesTests`` — ``conflictStages``: урок-помеха сам может быть уроком копии — составить
  заново советуют этап её источника, а не поток копии (его сборка уроки копии не двигает).
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import json
import os
import shutil
import unittest
from unittest import mock

from src.variables import PATH_TO_FOLDER
from src.modules.translate import translate
from src.modules.functions.courses import removeCourses, setSectionEnd
from src.web.project import conflictStages, lessonsText, loadAnswer, loadAnswerOrEmpty, saveAnswer, saveSettings
from src.web.server import UserError, app, projectPath
from tests.builders import (
    JOINT_LINE, JOINT_PIN_TEACHER, LEVEL_LINE, PROJECTS, courseWeek, jointCourse, jointProject, markJoint, readJson, shiftStream, writeText
)
from tests.real_project import FrozenDate, RealProjectCase


class ProjectPathTests(unittest.TestCase):
    """Имя проекта из адреса не может увести за пределы папки projects."""
    def test_drive_and_parent_names_are_refused(self):
        """«C:», «..», разделители и пустое имя — «проект не найден», а не папка диска или projects."""
        for name in ("C:", "D:", "..", ".", "a/b", "a\\b", "", "a:b"):
            with self.assertRaises(UserError, msg=name):
                projectPath(name)

    def test_drive_name_in_address(self):
        """Запросы к проекту «C:» — отказ 400 «проект не найден» (раньше отвечали 200, и удаление
        «проекта C:» могло стереть все проекты); папка проектов на месте.
        """
        client = app.test_client()
        projects = f"{PATH_TO_FOLDER}/projects"
        before = sorted(os.listdir(projects))

        for method, address in (("get", "/api/project/C:/job"), ("get", "/api/project/C:"), ("delete", "/api/project/C:")):
            response = getattr(client, method)(address)
            self.assertEqual((response.status_code, response.get_json()), (400, {"error": translate("web.error.no_project"), "code": "no_project"}), address)
            response.close()

        self.assertEqual(sorted(os.listdir(projects)), before)


class HiddenFolderTests(RealProjectCase):
    """Скрытая папка «.имя» с настоящим проектом внутри — не проект."""
    NAME = "__test_hidden_folder__"
    HIDDEN = ".__test_hidden__"

    def test_hidden_folder_is_not_a_project(self):
        """Скрытая папка «.имя» с настоящим проектом внутри не открывается и не удаляется: «Проект не найден»."""
        hidden = f"{PROJECTS}/{self.HIDDEN}"
        shutil.copytree(self.folder, hidden)
        self.addCleanup(shutil.rmtree, hidden, ignore_errors=True)
        missing = translate("web.error.no_project")

        response = self.client.get(f"/api/project/{self.HIDDEN}")
        self.assertEqual((response.status_code, response.get_json().get("error")), (400, missing))

        response = self.client.post(f"/api/project/{self.HIDDEN}/open")
        self.assertEqual((response.status_code, response.get_json().get("error")), (400, missing))

        response = self.client.delete(f"/api/project/{self.HIDDEN}")
        self.assertEqual((response.status_code, response.get_json().get("error")), (400, missing))
        self.assertTrue(os.path.isfile(f"{hidden}/settings.json"))


class LoadAnswerTests(unittest.TestCase):
    """Чтение answer.json открытого проекта."""
    def test_load_answer_or_empty(self):
        """Испорченный answer.json: loadAnswer — ошибка, loadAnswerOrEmpty — пустое расписание,
        файл при этом не меняется; целый файл оба читают одинаково; проекта нет — «не найден».
        """
        name = "__test_answer_helpers__"
        path = os.path.join(PATH_TO_FOLDER, "projects", name, "answer.json")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), ignore_errors=True)

        for text in ("{broken", "[1]"):
            writeText(path, text)

            with self.assertRaises(ValueError):
                loadAnswer(name)

            self.assertEqual(loadAnswerOrEmpty(name), {})

            with open(path, encoding="utf-8") as file:
                self.assertEqual(file.read(), text)

        writeText(path, '{"курс": []}')
        self.assertEqual(loadAnswerOrEmpty(name), loadAnswer(name))
        self.assertEqual(loadAnswerOrEmpty(name), {"курс": []})

        with self.assertRaises(UserError):
            loadAnswerOrEmpty("__test_no_such_project__")


class LessonsTextTests(unittest.TestCase):
    """Окончания «урок / урока / уроков»."""
    def test_lessons_text_endings(self):
        """Окончания по таблице, включая границы 11–14 и 111–114 («уроков»)."""
        table = {1: "1 урок", 2: "2 урока", 4: "4 урока", 5: "5 уроков", 11: "11 уроков", 12: "12 уроков", 13: "13 уроков",
                 14: "14 уроков", 15: "15 уроков", 21: "21 урок", 22: "22 урока", 24: "24 урока", 111: "111 уроков",
                 114: "114 уроков", 121: "121 урок", 0: "0 уроков"}
        for count, text in table.items():
            self.assertEqual(lessonsText(count), text, count)


class JointSyncTests(unittest.TestCase):
    """saveSettings и saveAnswer приводят курсы-копии к источникам (проект builders.jointProject)."""
    NAME = "__test_joint_sync__"
    MATH_1, MATH_2 = jointCourse(1, "Математика"), jointCourse(2, "Математика")
    RUS_1, RUS_2 = jointCourse(1, "Русский язык"), jointCourse(2, "Русский язык")

    def setUp(self):
        self.folder = f"{PROJECTS}/{self.NAME}"
        shutil.rmtree(self.folder, ignore_errors=True)
        os.makedirs(self.folder)
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def write(self, settings, answer):
        """Записывает settings.json и answer.json проекта как есть, мимо программы."""
        for name, data in (("settings.json", settings), ("answer.json", answer)):
            with open(os.path.join(self.folder, name), "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False)

    def read(self, name):
        """JSON-файл ``name`` проекта."""
        return readJson(os.path.join(self.folder, name))

    def raw(self, name):
        """Файл ``name`` проекта байтами."""
        with open(os.path.join(self.folder, name), "rb") as file:
            return file.read()

    def test_first_save_aligns_copies_then_files_stay_the_same(self):
        """AC-34: проект рассогласован (копию правили руками в файле: у копий только поле
        together_with, часы русского 1 вместо 2, у математики свои уроки). Первая же запись
        saveSettings / saveAnswer приводит копии к источникам: часы и уроки как у источника.
        Повторная запись согласованного проекта содержимое файлов не меняет.
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, sync=False)
        answer[self.MATH_2] = courseWeek("Математика", JOINT_PIN_TEACHER, (1, 0), (4, 0))
        self.write(settings, answer)

        saveSettings(self.NAME, settings)

        saved = self.read("settings.json")
        self.assertEqual(saved["classes"]["lessons"][self.RUS_2], saved["classes"]["lessons"][self.RUS_1])
        marks = {group["name"]: group.get("together_with") for group in saved["classes"]["custom_groups"]}
        self.assertEqual((marks[self.MATH_2], marks[self.RUS_2]), (1, 1))

        saveAnswer(self.NAME, answer)

        saved = self.read("answer.json")
        self.assertEqual(saved[self.MATH_2], saved[self.MATH_1])
        self.assertEqual(saved[self.RUS_2], saved[self.RUS_1])

        files = (self.raw("settings.json"), self.raw("answer.json"))
        saveSettings(self.NAME, self.read("settings.json"))
        saveAnswer(self.NAME, self.read("answer.json"))
        self.assertEqual((self.raw("settings.json"), self.raw("answer.json")), files)

    def test_save_drops_mark_without_source_and_keeps_lessons(self):
        """AC-19 (Р-2, исключение): источник удалён из настроек мимо действий — запись настроек
        убирает отметку у его бывшей копии (у копии с живым источником она остаётся), а запись
        расписания оставляет уроки бывшей копии как есть.
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        removeCourses(settings, [self.MATH_1])
        answer.pop(self.MATH_1)
        kept = answer[self.MATH_2]
        self.write(settings, answer)

        saveSettings(self.NAME, settings)

        groups = {group["name"]: group for group in self.read("settings.json")["classes"]["custom_groups"]}
        self.assertNotIn("together_with", groups[self.MATH_2])
        self.assertEqual(groups[self.RUS_2].get("together_with"), 1)

        saveAnswer(self.NAME, answer)
        self.assertEqual(self.read("answer.json")[self.MATH_2], kept)


class ConflictStagesTests(unittest.TestCase):
    """«Сегодня» 04.10.2026, Поток 1 ещё не начался. «ЕГЭ основной» Потока 3 присоединяется к Потоку 1,
    «ЕГЭ продвинутый» Потока 3 — к Потоку 2; Поток 2 кончается до начала Потока 3.
    """

    def test_copy_blocker_names_its_source_stage(self):
        """Помеха — урок копии «Математики» «ЕГЭ продвинутый» Потока 3: этап для новой сборки — Поток 2 (её источник)."""
        settings, answer = jointProject()
        shiftStream(settings, 1, "2026-10-12")
        setSectionEnd(settings, 2, "2027-01-10")
        answer[jointCourse(2, "Математика", LEVEL_LINE)] = courseWeek("Математика", "Математика #1", (1, 0), (4, 1))
        markJoint(settings, 3, JOINT_LINE, 1, answer)
        markJoint(settings, 3, LEVEL_LINE, 2, answer)

        with mock.patch("datetime.date", FrozenDate):
            stages = conflictStages(settings, [(1, 0, "busy", jointCourse(3, "Математика", LEVEL_LINE))])

        self.assertEqual(stages, "Поток 2")
