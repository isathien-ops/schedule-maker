"""Папка проекта (`src/modules/functions/tree.py`): создание, открытие, формат, импорт и экспорт архива.

* ``NewProjectTests`` — новый проект сразу в текущем формате и его повторное открытие;
* ``ProjectFormatTests`` — номер формата проекта на неожиданных данных;
* ``OpenProjectTests``, ``ProjectFilesTests`` — открытие проекта с недостающими и испорченными
  файлами (``prepareProject``), свободное имя проекта;
* ``ImportProjectTests``, ``ProjectArchiveTests`` — импорт и экспорт .zip-архива проекта; архивы,
  которые не являются проектом или пишут файлы вне папки проекта, отвергаются.

Проекты создаются во временной папке проектов (папка данных подменена в `tests/__init__.py`)
под служебными именами `__test_…__` и удаляются после каждого теста.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import glob
import json
import os
import re
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

from src.variables import PATH_TO_FOLDER
from src.modules.functions.pairs import subjectPairState
from src.modules.functions.tree import (
    PROJECT_FORMAT, UNNUMBERED_LEFTOVERS, exportProjectArchive, freeProjectName, importProjectArchive, isCurrentFormat,
    newProjectSettings, numberFormat, prepareProject
)
from tests.builders import FOLDER, FORMAT_PROJECT, WEEKDAY_GRID, readJson, readProject, unnumbered, writeProject, writeText

IMPORT_PROJECT = "__test_import_test__"


class NewProjectTests(unittest.TestCase):
    """Создание проекта и повторное открытие."""
    def setUp(self):
        """Новый проект со стандартной программой (так его создаёт страница)."""
        shutil.rmtree(FOLDER, ignore_errors=True)
        os.makedirs(FOLDER)
        self.settings = prepareProject(FORMAT_PROJECT)

    def tearDown(self):
        shutil.rmtree(FOLDER, ignore_errors=True)

    def test_new_project_is_in_current_format(self):
        """Новый проект: номер формата, программа с «Математикой база», будни с уроками, веса из
        шаблона; лишних ключей нет; повторное открытие ничего не меняет."""
        self.assertEqual(self.settings["format"], PROJECT_FORMAT)
        self.assertFalse(set(UNNUMBERED_LEFTOVERS) & set(self.settings))
        self.assertIn("Математика база", [name for name, _ in self.settings["subjects"]])
        self.assertIn("Поток 1 — ЕГЭ основной — Математика база", [group["name"] for group in self.settings["classes"]["custom_groups"]])
        self.assertFalse([group for group in self.settings["classes"]["custom_groups"] if "parallel" in group])
        self.assertEqual([bool(day) for day in self.settings["day_grid"]], [True] * 5 + [False] * 2)

        with open("src/files/weights.json", encoding="utf-8") as file:
            self.assertEqual(readProject("weights.json"), json.load(file))

        self.assertEqual(prepareProject(FORMAT_PROJECT), readProject("settings.json"))
        self.assertEqual(readProject("settings.json"), self.settings)

    def test_new_project_has_default_soft_pairs(self):
        """Пары «нежелательно» по умолчанию есть сразу; пара «нельзя» во второй список не попадает."""
        self.assertEqual(subjectPairState(self.settings, "Химия", "Русский язык"), "soft")
        self.assertEqual(subjectPairState(self.settings, "Физика", "Математика"), "hard")
        self.assertEqual(subjectPairState(self.settings, "Химия", "Физика"), "allowed")

        soft = {tuple(sorted(pair)) for pair in self.settings["soft_subject_pairs"]}
        hard = {tuple(sorted(pair)) for pair in self.settings["joint_subject_pairs"]}
        self.assertFalse(soft & hard)

    def test_missing_weights_come_from_template(self):
        """Веса, которых нет в проекте, дописываются из шаблона; свои значения остаются."""
        writeProject("weights.json", {"softSubjectPair": 7})

        prepareProject(FORMAT_PROJECT)
        weights = readProject("weights.json")

        self.assertEqual(weights["softSubjectPair"], 7)
        self.assertIn("levelsApart", weights)

    def test_broken_settings_are_kept_and_refused(self):
        """Нечитаемый settings.json не заменяется пустым проектом: откладывается копия и бросается ошибка."""
        with open(os.path.join(FOLDER, "settings.json"), "w", encoding="utf-8") as file:
            file.write("{broken")

        with self.assertRaises(ValueError) as error:
            prepareProject(FORMAT_PROJECT)

        self.assertEqual(str(error.exception), "web.error.broken_settings")
        with open(os.path.join(FOLDER, "settings.json"), encoding="utf-8") as file:
            self.assertEqual(file.read(), "{broken")

        self.assertTrue([name for name in os.listdir(FOLDER) if name.startswith("settings.json.broken-")])

    def test_old_project_is_refused_untouched(self):
        """Проект без номера формата (и без отметок 04.10.2026) или с другим номером не открывается:
        ошибка «web.error.old_project», файлы проекта не меняются."""
        os.remove(os.path.join(FOLDER, "weights.json"))

        for settings in ({"classes": {"custom_groups": [], "lessons": {}}, "pair_rules_version": 2},
                         dict(self.settings, format=PROJECT_FORMAT + 1)):
            writeProject("settings.json", settings)

            with self.assertRaises(ValueError) as error:
                prepareProject(FORMAT_PROJECT)

            self.assertEqual(str(error.exception), "web.error.old_project")
            self.assertEqual(readProject("settings.json"), settings)
            self.assertFalse(os.path.exists(os.path.join(FOLDER, "weights.json")))

    def test_unnumbered_project_of_current_content_opens(self):
        """Временное правило: проект без "format" с pair_rules_version == 2 и base_math_version == 2
        открывается, получает номер формата, а неиспользуемые ключи (и "parallel" у курсов) убираются."""
        writeProject("settings.json", unnumbered(self.settings))

        settings = prepareProject(FORMAT_PROJECT)

        self.assertEqual(settings, self.settings)
        self.assertEqual(readProject("settings.json"), self.settings)


class ProjectFormatTests(unittest.TestCase):
    """Номер формата проекта на неожиданных данных и у проекта, где он уже есть."""
    def test_not_a_dict_is_not_current(self):
        """Не словарь (список, None, строка) — не настройки текущего формата."""
        for value in ([], None, "format", 1):
            self.assertFalse(isCurrentFormat(value))

        self.assertTrue(isCurrentFormat({"format": PROJECT_FORMAT}))
        self.assertFalse(isCurrentFormat({"format": PROJECT_FORMAT + 1}))
        self.assertTrue(isCurrentFormat({"pair_rules_version": 2, "base_math_version": 2}))
        self.assertFalse(isCurrentFormat({"pair_rules_version": 2}))

    def test_number_format_keeps_numbered_project(self):
        """Проект, у которого уже есть номер формата, не меняется (поля display и parallel остаются)."""
        settings = {"format": 1, "display": 1, "classes": {"custom_groups": [{"parallel": 1}]}}

        result = numberFormat(settings)

        self.assertEqual(result, {"format": 1, "display": 1, "classes": {"custom_groups": [{"parallel": 1}]}})


class OpenProjectTests(unittest.TestCase):
    """Открытие проекта: недостающие параметры и размер сетки; архив, который пишет в соседнюю папку."""
    NAME = "__mut_functions__"

    def tearDown(self):
        for name in (self.NAME, f"{self.NAME}_evil"):
            shutil.rmtree(f"{PATH_TO_FOLDER}/projects/{name}", ignore_errors=True)

    def readSettings(self):
        """Записанный на диск settings.json проекта."""
        with open(f"{PATH_TO_FOLDER}/projects/{self.NAME}/settings.json", encoding="utf-8") as file:
            return json.load(file)

    def writeProject(self, settings):
        """Папка проекта с settings.json ``settings``; возвращает путь к ней."""
        path = f"{PATH_TO_FOLDER}/projects/{self.NAME}"
        os.makedirs(path)

        with open(f"{path}/settings.json", "w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False)

        return path

    def test_zip_slip_into_neighbour_folder(self):
        """Файл архива ведёт в соседнюю папку, имя которой начинается с имени проекта: архив
        отклоняется, и ни проект, ни соседняя папка не появляются.
        """
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "evil.zip")

            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("settings.json", json.dumps({"format": 1}))
                archive.writestr(f"../{self.NAME}_evil/x.txt", "x")

            with self.assertRaises(ValueError) as error:
                importProjectArchive(path, self.NAME)

        self.assertEqual(str(error.exception), "web.error.not_project_archive")
        self.assertFalse(os.path.exists(f"{PATH_TO_FOLDER}/projects/{self.NAME}"))
        self.assertFalse(os.path.exists(f"{PATH_TO_FOLDER}/projects/{self.NAME}_evil"))

    def test_missing_settings_are_added(self):
        """Недостающие параметры дописываются значениями нового проекта (и в файл), имеющиеся не меняются."""
        self.writeProject({"format": 1, "max_courses_per_teacher": 7, "day_grid": [list(day) for day in WEEKDAY_GRID],
                           "classes": {"custom_groups": [], "lessons": {}}, "teachers": {}, "constants": {}})
        defaults = newProjectSettings()

        settings = prepareProject(self.NAME)
        saved = self.readSettings()

        for result in (settings, saved):
            self.assertEqual(result["non_overlapping_programs"], defaults["non_overlapping_programs"])
            self.assertEqual(result["calendar_end_date"], defaults["calendar_end_date"])
            self.assertEqual(result["max_courses_per_teacher"], 7)
            self.assertEqual(result["classes"], {"custom_groups": [], "lessons": {}})

    def test_day_numbers_follow_grid(self):
        """Число рабочих дней и уроков в день при открытии пересчитываются по сетке и записываются."""
        grid = [["16:20 - 17:50", "18:00 - 19:30", "19:40 - 21:10", "21:20 - 22:00"]] + [list(WEEKDAY_GRID[0])] * 5 + [[]]
        self.writeProject({"format": 1, "working_days_per_week": 5, "max_lesson_count_per_day": 3, "day_grid": grid,
                           "classes": {"custom_groups": [], "lessons": {}}, "teachers": {}, "constants": {}})

        settings = prepareProject(self.NAME)
        saved = self.readSettings()

        for result in (settings, saved):
            self.assertEqual((result["working_days_per_week"], result["max_lesson_count_per_day"]), (6, 4))


class ProjectFilesTests(unittest.TestCase):
    """Открытие проекта с испорченными файлами и импорт архивов."""
    NAME = "__test_functions_tree__"

    def setUp(self):
        """Чистая папка тестового проекта и папка для архивов."""
        self.path = f"{PATH_TO_FOLDER}/projects/{self.NAME}"
        shutil.rmtree(self.path, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.path, ignore_errors=True)
        self.temp = tempfile.mkdtemp(prefix="cov-archives-")
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)

    def archive(self, members):
        """Новый zip-архив с файлами ``members`` {имя в архиве: текст}; возвращает путь."""
        path = os.path.join(self.temp, f"project-{len(os.listdir(self.temp))}.zip")

        with zipfile.ZipFile(path, "w") as archive:
            for name, text in members.items():
                archive.writestr(name, text)

        return path

    def test_settings_not_an_object(self):
        """settings.json — JSON, но не объект: проект не открывается, файл не меняется,
        а его копия откладывается в settings.json.broken-*.
        """
        os.makedirs(self.path)
        writeText(f"{self.path}/settings.json", "[1, 2]")

        with self.assertRaisesRegex(ValueError, "^web.error.broken_settings$"):
            prepareProject(self.NAME)

        self.assertEqual(readJson(f"{self.path}/settings.json"), [1, 2])
        self.assertEqual(len(glob.glob(f"{self.path}/settings.json.broken-*")), 1)

    def test_weights_and_answer_not_objects(self):
        """weights.json и answer.json — списки: проект открывается, веса берутся из шаблона,
        расписание сбрасывается с меткой answer.json.repaired, испорченные файлы откладываются.
        """
        os.makedirs(self.path)
        prepareProject(self.NAME)
        writeText(f"{self.path}/weights.json", "[]")
        writeText(f"{self.path}/answer.json", "[]")

        settings = prepareProject(self.NAME)

        self.assertEqual(settings["format"], PROJECT_FORMAT)
        self.assertEqual(readJson(f"{self.path}/weights.json"), readJson("src/files/weights.json"))
        self.assertEqual(readJson(f"{self.path}/answer.json"), {})
        self.assertTrue(os.path.exists(f"{self.path}/answer.json.repaired"))
        self.assertEqual(len(glob.glob(f"{self.path}/weights.json.broken-*")), 1)
        self.assertEqual(len(glob.glob(f"{self.path}/answer.json.broken-*")), 1)

    def test_archive_with_path_outside_project(self):
        """Архив с файлом «../…» (zip slip) отклоняется целиком: ничего не распаковывается."""
        path = self.archive({"settings.json": json.dumps({"format": PROJECT_FORMAT}), "../evil.txt": "x"})

        with self.assertRaisesRegex(ValueError, "^web.error.not_project_archive$"):
            importProjectArchive(path, self.NAME)

        self.assertFalse(os.path.exists(self.path))
        self.assertFalse(os.path.exists(f"{PATH_TO_FOLDER}/projects/evil.txt"))

    def test_archive_that_fails_to_unpack(self):
        """Распаковка оборвалась — наполовину распакованный проект удаляется, ошибка понятная."""
        path = self.archive({"settings.json": json.dumps({"format": PROJECT_FORMAT}), "answer.json": "{}"})

        with mock.patch.object(zipfile.ZipFile, "extractall", side_effect=OSError("диск переполнен")):
            with self.assertRaisesRegex(ValueError, "^web.error.not_project_archive$"):
                importProjectArchive(path, self.NAME)

        self.assertFalse(os.path.exists(self.path))

    def test_archive_of_other_kinds(self):
        """Не zip, архив без settings.json, settings.json не объект — «не архив проекта»;
        проект старого формата — «старый архив»; ни в одном случае папка проекта не появляется.
        """
        not_zip = os.path.join(self.temp, "a.zip")
        writeText(not_zip, "это не архив")
        cases = [
            (not_zip, "web.error.not_project_archive"),
            (self.archive({"answer.json": "{}"}), "web.error.not_project_archive"),
            (self.archive({"settings.json": "[1]"}), "web.error.not_project_archive"),
            (self.archive({"settings.json": json.dumps({"format": PROJECT_FORMAT + 1})}), "web.error.old_archive"),
        ]

        for path, key in cases:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, f"^{re.escape(key)}$"):
                importProjectArchive(path, self.NAME)

            self.assertFalse(os.path.exists(self.path))

    def test_free_name(self):
        """Пробелы — «_», запрещённые символы убираются, пустое имя — «Проект», занятое — с номером."""
        os.makedirs(self.path)

        self.assertEqual(freeProjectName(" __test functions tree__ "), f"{self.NAME}_2")
        self.assertEqual(freeProjectName('__test_<functions>?_tree__'), f"{self.NAME}_2")
        self.assertTrue(freeProjectName(' :*?"<>| ').startswith("Проект"))


class ImportProjectTests(unittest.TestCase):
    """Импорт проекта из .zip."""
    def tearDown(self):
        """Удаляет тестовые проекты из (временной) папки проектов."""
        for name in (IMPORT_PROJECT, f"{IMPORT_PROJECT}_2"):
            shutil.rmtree(f"{PATH_TO_FOLDER}/projects/{name}", ignore_errors=True)

    def test_export_then_import(self):
        """Проект, выгруженный в .zip, импортируется целиком (вместе с подпапками); повторный импорт
        под занятым именем отклоняется, а для него предлагается свободное имя «…_2».
        """
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "project")
            os.makedirs(os.path.join(source, "stages"))

            with open(os.path.join(source, "settings.json"), "w", encoding="utf-8") as file:
                json.dump({"format": PROJECT_FORMAT, "iterations": 7}, file)

            with open(os.path.join(source, "stages", "1.json"), "w", encoding="utf-8") as file:
                file.write("{}")

            archive = os.path.join(folder, "project.zip")
            exportProjectArchive(source, archive)

            self.assertEqual(importProjectArchive(archive, IMPORT_PROJECT), IMPORT_PROJECT)

            target = f"{PATH_TO_FOLDER}/projects/{IMPORT_PROJECT}"
            with open(os.path.join(target, "settings.json"), encoding="utf-8") as file:
                self.assertEqual(json.load(file), {"format": PROJECT_FORMAT, "iterations": 7})

            self.assertTrue(os.path.exists(os.path.join(target, "stages", "1.json")))

            # Имя теперь занято: предлагается свободное, импорт под занятым именем отклоняется
            self.assertEqual(freeProjectName(IMPORT_PROJECT), f"{IMPORT_PROJECT}_2")

            with self.assertRaises(ValueError) as error:
                importProjectArchive(archive, IMPORT_PROJECT)

            self.assertEqual(str(error.exception), "web.error.project_name_exists")

    def test_refuses_what_is_not_a_project(self):
        """Не-zip, архив без settings.json и «злой» архив с путём «../» отклоняются,
        и ничего не появляется ни в папке проектов, ни рядом с ней.
        """
        with tempfile.TemporaryDirectory() as folder:
            text = os.path.join(folder, "notes.zip")

            with open(text, "w", encoding="utf-8") as file:
                file.write("not a zip")

            with self.assertRaises(ValueError):
                importProjectArchive(text, IMPORT_PROJECT)

            # Zip без settings.json
            other = os.path.join(folder, "other.zip")
            with zipfile.ZipFile(other, "w") as archive:
                archive.writestr("readme.txt", "hello")

            with self.assertRaises(ValueError):
                importProjectArchive(other, IMPORT_PROJECT)

            # Zip, который записал бы файл вне папки проекта
            evil = os.path.join(folder, "evil.zip")
            with zipfile.ZipFile(evil, "w") as archive:
                archive.writestr("settings.json", "{}")
                archive.writestr("../escaped.txt", "x")

            with self.assertRaises(ValueError):
                importProjectArchive(evil, IMPORT_PROJECT)

            self.assertFalse(os.path.exists(f"{PATH_TO_FOLDER}/projects/{IMPORT_PROJECT}"))
            self.assertFalse(os.path.exists(f"{PATH_TO_FOLDER}/projects/escaped.txt"))


class ProjectArchiveTests(unittest.TestCase):
    """Содержимое архива проекта."""
    def test_archives_project_files_with_relative_paths(self):
        """В архив попадают все файлы проекта (включая подпапки) с путями относительно папки
        проекта, без абсолютных путей компьютера, — иначе архив не откроется на другом компьютере.
        """
        with tempfile.TemporaryDirectory() as project:
            os.mkdir(os.path.join(project, "backups"))

            for name in ("settings.json", "weights.json", os.path.join("backups", "old.json")):
                with open(os.path.join(project, name), "w", encoding="utf-8") as file:
                    file.write("{}")

            archive_path = os.path.join(project, "project.zip")
            exportProjectArchive(project, archive_path)

            with zipfile.ZipFile(archive_path) as archive:
                names = sorted(name.replace("\\", "/") for name in archive.namelist())

        self.assertEqual(names, ["backups/old.json", "settings.json", "weights.json"])
