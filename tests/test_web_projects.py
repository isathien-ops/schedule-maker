"""Стартовый экран (`src/web/projects.py`): список, создание, импорт, удаление и открытие проектов.

* ``ProjectListTests``, ``StartScreenTests`` — создание с проверкой имени, список со сводкой
  (в том числе повреждённые и посторонние папки), удаление;
* ``ProjectSummaryTests`` — сводка проекта (``projects.projectSummary``) при settings.json, который
  читается, но с полями не того вида: нули вместо ошибки 500 у всего списка;
* ``ProjectNameTests`` — имена, занятые Windows, и невидимые символы в имени;
* ``ImportTests`` — «Импорт проекта» (POST /api/projects/import);
* ``OpenProjectTests`` — открытие проекта с повреждёнными файлами: что откладывается в копию,
  что восстанавливается и о чём говорится один раз;
* ``ServerFormatTests`` — проект, архив и версия другого формата через сервер;
* ``JointProjectTests`` — «линейка присоединяется к Потоку N» (.spec/joint-lines/SPEC.md): отметка
  и общие уроки после восстановления версии и после выгрузки и импорта архива проекта.

Проекты создаются во временной папке проектов (папка данных подменена в `tests/__init__.py`)
под служебными именами `__test_…__` и удаляются после каждого теста.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

from src.variables import PATH_TO_FOLDER
from src.modules.translate import translate
from src.modules.functions.tree import PROJECT_FORMAT, exportProjectArchive, importProjectArchive
from src.modules.functions.versions import saveVersion
from src.web import projects
from src.web.core import UserError
from src.web.projects import checkProjectName
from src.web.server import app
from tests.builders import (
    FOLDER, FORMAT_PROJECT, JOINT_LINE, PROJECTS, jointCourse, jointProject, markJoint, readJson, readProject, unnumbered, writeProject
)
from tests.real_project import ARCHIVE, RealProjectCase

NEW = "__test_new__"
IMPORTED = "__test_imported__"
FORMAT_IMPORTED = "__test_format_imported__"
JOINT_IMPORTED = "__test_joint_imported__"

# Курсы-копии «ЕГЭ основной» Потока 2 и их источники в Потоке 1 (проект builders.jointProject)
JOINT_COPIES = {jointCourse(2, "Математика"): jointCourse(1, "Математика"), jointCourse(2, "Русский язык"): jointCourse(1, "Русский язык")}


class ProjectListTests(unittest.TestCase):
    """Создание, список и удаление проектов."""
    def setUp(self):
        self.client = app.test_client()

    def tearDown(self):
        for name in (NEW, "__test_broken__"):
            shutil.rmtree(f"{PROJECTS}/{name}", ignore_errors=True)

    def test_create_project_validates_names(self):
        """Имя проекта: без пробелов, без запрещённых в Windows символов и имён, не с точки, не длиннее
        80 знаков, не занятое; новый проект получает стандартную программу школы.
        """
        for name in ("", "  ", "два слова", "a/b", "a:b", "..", ".hidden", "CON", "lpt1.txt", "name.", "x" * 81, "tab\there"):
            response = self.client.post("/api/projects", json={"name": name})
            self.assertEqual(response.status_code, 400, name)
            self.assertTrue(response.get_json()["error"], name)

        response = self.client.post("/api/projects", json={"name": NEW})
        self.assertEqual(response.get_json(), {"project": NEW})
        self.assertEqual(self.client.post("/api/projects", json={"name": NEW}).status_code, 400)

        state = self.client.post(f"/api/project/{NEW}/open").get_json()
        self.assertTrue(state["courses"])
        self.assertIn("Математика", state["subjects"])
        self.assertEqual(state["answer"], {})
        self.assertEqual(state["lessons"], 0)

        listed = {item["name"]: item for item in self.client.get("/api/projects").get_json()}
        self.assertEqual(listed[NEW]["courses"], len(state["courses"]))
        self.assertEqual(listed[NEW]["built"], 0)
        self.assertTrue(listed[NEW]["modified"])

    def test_broken_project_is_still_listed_and_can_be_deleted(self):
        """Проект с нечитаемыми файлами всё равно показывается в списке (с нулями) и удаляется."""
        os.makedirs(f"{PROJECTS}/__test_broken__")
        with open(f"{PROJECTS}/__test_broken__/settings.json", "w", encoding="utf-8") as file:
            file.write("[1, 2")

        listed = {item["name"]: item for item in self.client.get("/api/projects").get_json()}
        self.assertEqual(listed["__test_broken__"]["courses"], 0)

        self.assertEqual(self.client.delete("/api/project/__test_broken__").status_code, 200)
        self.assertFalse(os.path.exists(f"{PROJECTS}/__test_broken__"))
        self.assertEqual(self.client.delete("/api/project/__test_broken__").status_code, 400)

    def test_project_name_cannot_leave_projects_folder(self):
        """Имя проекта в адресе не может указывать за пределы папки проектов."""
        for name in ("..", ".", "...", "%2e%2e"):
            self.assertEqual(self.client.get(f"/api/project/{name}").status_code in (400, 404), True, name)

        self.assertEqual(self.client.post("/api/project/__test_none__/action", json={"action": "setLimit", "args": {"key": "max_courses_per_teacher", "value": 3}}).status_code, 400)


class ProjectSummaryTests(unittest.TestCase):
    """Сводка проекта для стартового экрана (``projects.projectSummary``), когда settings.json читается
    как JSON, но его поля не того вида (испорчен вручную или другой программой).
    """
    def summary(self, settings):
        """Сводка проекта, в папке которого лежит settings.json с содержимым ``settings``."""
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "settings.json"), "w", encoding="utf-8") as file:
                json.dump(settings, file)

            return projects.projectSummary("x", folder)

    def test_wrong_types_give_zeros(self):
        """«classes» списком, «custom_groups» или «teachers» числом, весь файл списком — сводка с нулями,
        без исключения (иначе AttributeError / TypeError давали бы ошибку 500 у всего списка проектов).
        """
        for settings in ({"classes": []}, {"teachers": 5}, {"classes": {"custom_groups": 5}}, [1, 2]):
            with self.subTest(settings=settings):
                item = self.summary(settings)
                self.assertEqual((item["courses"], item["teachers"], item["stages"], item["built"]), (0, 0, 0, 0))

    def test_readable_counts_kept(self):
        """Читаемое число курсов и преподавателей показывается, даже если этапы не разобрать."""
        item = self.summary({"classes": {"custom_groups": [1, 2]}, "teachers": {"А": {}}})

        self.assertEqual((item["courses"], item["teachers"], item["stages"], item["built"]), (2, 1, 0, 0))


class StartScreenTests(RealProjectCase):
    """Стартовый экран: сводка проектов, посторонние папки, импорт, время изменения."""
    NAME = "__test_start_screen__"
    EXTRA = ("__test_file__.txt", ".__test_hidden__", "__test_odd__", "__test_import__")

    def tearDown(self):
        for name in self.EXTRA:
            path = f"{PROJECTS}/{name}"
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.remove(path)

        super().tearDown()

    def listed(self):
        """Список проектов стартового экрана: имя -> сводка."""
        return {item["name"]: item for item in self.client.get("/api/projects").get_json()}

    def test_summary_of_real_project(self):
        """Сводка реального проекта: 99 курсов, 25 преподавателей, 3 этапа, из них построены целиком 2
        (поток 1 и семинары); время изменения — по самому свежему из двух файлов.
        """
        item = self.listed()[self.NAME]
        self.assertEqual((item["courses"], item["teachers"], item["stages"], item["built"]), (99, 25, 3, 2))
        self.assertRegex(item["modified"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d$")

    def test_files_hidden_folders_and_odd_projects(self):
        """Файлы и скрытые папки в папке проектов не показываются; проект, курсы которого не читаются,
        показывается с нулями.
        """
        with open(f"{PROJECTS}/__test_file__.txt", "w", encoding="utf-8") as file:
            file.write("x")

        os.makedirs(f"{PROJECTS}/.__test_hidden__")
        os.makedirs(f"{PROJECTS}/__test_odd__")
        with open(f"{PROJECTS}/__test_odd__/settings.json", "w", encoding="utf-8") as file:
            json.dump({"classes": {"custom_groups": [1, 2]}, "teachers": {"А": {}}}, file)

        listed = self.listed()

        self.assertNotIn("__test_file__.txt", listed)
        self.assertNotIn(".__test_hidden__", listed)
        odd = listed["__test_odd__"]
        self.assertEqual((odd["courses"], odd["teachers"], odd["stages"], odd["built"]), (2, 1, 0, 0))
        self.assertIsNotNone(odd["modified"])

    def test_import_that_cannot_be_opened_leaves_nothing(self):
        """Архив распаковался, но проект не открывается: папка удаляется, понятная ошибка."""
        with open(ARCHIVE, "rb") as file:
            data = file.read()

        with mock.patch.object(projects, "prepareProject", side_effect=RuntimeError("не открывается")):
            response = self.client.post("/api/projects/import", data={"file": (io.BytesIO(data), "a.zip"), "name": "__test_import__"},
                                        content_type="multipart/form-data")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], translate("web.error.not_project_archive"))
        self.assertFalse(os.path.exists(f"{PROJECTS}/__test_import__"))

    def test_import_needs_file_and_free_name(self):
        """Импорт без файла и под занятым именем — понятная ошибка, существующий проект не меняется."""
        response = self.client.post("/api/projects/import", data={}, content_type="multipart/form-data")
        self.assertEqual((response.status_code, response.get_json()["error"]), (400, translate("web.error.not_project_archive")))

        before = self.raw("settings.json")
        with open(ARCHIVE, "rb") as file:
            response = self.client.post("/api/projects/import", data={"file": (io.BytesIO(file.read()), "a.zip"), "name": self.NAME},
                                        content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.raw("settings.json"), before)

    def test_modified_is_latest_of_two_files(self):
        """«Изменён» на стартовом экране — более позднее время из settings.json и answer.json."""
        old = datetime.datetime(2020, 1, 1, 10, 0).timestamp()
        new = datetime.datetime(2025, 5, 5, 12, 34).timestamp()

        def modified():
            return next(item for item in self.client.get("/api/projects").get_json() if item["name"] == self.NAME)["modified"]

        os.utime(f"{self.folder}/settings.json", (old, old))
        os.utime(f"{self.folder}/answer.json", (new, new))
        self.assertEqual(modified(), "2025-05-05T12:34")

        os.utime(f"{self.folder}/settings.json", (new, new))
        os.utime(f"{self.folder}/answer.json", (old, old))
        self.assertEqual(modified(), "2025-05-05T12:34")


class ProjectNameTests(unittest.TestCase):
    """Проверка имени нового проекта."""
    def test_reserved_windows_names_with_extension(self):
        """Имена устройств Windows, в том числе с расширением («lpt1.txt»), — точный текст «занято Windows»."""
        for name in ("lpt1.txt", "com3.log", "NUL", "con", "Aux.json"):
            with self.assertRaises(UserError) as caught:
                checkProjectName(name)

            self.assertEqual(str(caught.exception), translate("web.error.project_name_reserved"), name)

        # Похожие, но обычные имена проходят
        for name in ("lpt10", "com3x.log", "console", "nul_project"):
            checkProjectName(name)

    def test_control_characters_have_own_text(self):
        """Табуляция или перевод строки в середине имени — «невидимые знаки, наберите заново»,
        а не «занято Windows»; зарезервированные имена по-прежнему «занято Windows».
        """
        for name in ("tab\there", "две\nстроки", "звонок\x07"):
            with self.assertRaises(UserError) as caught:
                checkProjectName(name)

            self.assertEqual(str(caught.exception), translate("web.error.project_name_control"), repr(name))

        with self.assertRaises(UserError) as caught:
            checkProjectName("lpt1.txt")

        self.assertEqual(str(caught.exception), translate("web.error.project_name_reserved"))


@unittest.skipUnless(os.path.exists(ARCHIVE), "the 2026/27 project archive is not here")
class ImportTests(unittest.TestCase):
    """«Импорт проекта» через страницу (POST /api/projects/import)."""
    def setUp(self):
        self.client = app.test_client()

    def tearDown(self):
        for name in os.listdir(PROJECTS):
            if name.startswith("__test_imported") or name.startswith("Расписание_2026-27"):
                shutil.rmtree(f"{PROJECTS}/{name}", ignore_errors=True)

    def upload(self, data, filename, name=None):
        """Отправляет файл `data` как архив проекта; возвращает ответ."""
        form = {"file": (io.BytesIO(data), filename)}
        if name is not None:
            form["name"] = name

        return self.client.post("/api/projects/import", data=form, content_type="multipart/form-data")

    def test_import_archive(self):
        """Архив импортируется под указанным именем и открывается; без имени берётся имя файла,
        а если оно занято — «…_2»; имя с пробелом и пустой запрос отклоняются.
        """
        with open(ARCHIVE, "rb") as file:
            data = file.read()

        response = self.upload(data, "x.zip", IMPORTED)
        self.assertEqual(response.get_json(), {"project": IMPORTED})
        self.assertEqual(self.client.post(f"/api/project/{IMPORTED}/open").status_code, 200)
        self.assertEqual(self.upload(data, "x.zip", IMPORTED).status_code, 400)

        self.assertEqual(self.upload(data, "__test_imported x.zip").get_json(), {"project": "__test_imported_x"})
        self.assertEqual(self.upload(data, "__test_imported x.zip").get_json(), {"project": "__test_imported_x_2"})

        self.assertEqual(self.upload(data, "x.zip", "два слова").status_code, 400)
        self.assertEqual(self.client.post("/api/projects/import", data={}, content_type="multipart/form-data").status_code, 400)

    def test_import_refuses_junk_and_leaves_nothing(self):
        """Не архив, архив без настроек и архив с настройками-не-словарём отклоняются; папка не остаётся."""
        archives = [b"not a zip"]
        for content in ({"readme.txt": "x"}, {"settings.json": "[1, 2]"}, {"settings.json": "{\"classes\": 5}"}):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                for name, text in content.items():
                    archive.writestr(name, text)

            archives.append(buffer.getvalue())

        for data in archives:
            response = self.upload(data, "x.zip", IMPORTED)
            self.assertEqual(response.status_code, 400, data[:40])
            self.assertFalse(os.path.exists(f"{PROJECTS}/{IMPORTED}"), data[:40])


class OpenProjectTests(RealProjectCase):
    """Открытие проекта с повреждёнными файлами."""
    NAME = "__test_open__"

    def test_broken_answer_is_set_aside_with_one_message(self):
        """Повреждённое расписание откладывается в копию, проект открывается с пустым расписанием,
        а сообщение об этом показывается один раз.
        """
        with open(f"{self.folder}/answer.json", "w", encoding="utf-8") as file:
            file.write("{oops")

        first = self.client.post(f"/api/project/{self.NAME}/open").get_json()
        self.assertIn("Версии", first["message"])
        self.assertEqual(first["answer"], {})
        self.assertTrue([name for name in os.listdir(self.folder) if name.startswith("answer.json.broken-")])
        self.assertNotIn("message", self.client.post(f"/api/project/{self.NAME}/open").get_json())

    def test_broken_weights_are_replaced_by_defaults(self):
        """Повреждённые веса откладываются в копию, а проект открывается с весами по умолчанию."""
        with open(f"{self.folder}/weights.json", "w", encoding="utf-8") as file:
            file.write("[")

        state = self.client.post(f"/api/project/{self.NAME}/open").get_json()
        self.assertEqual(set(state["weights"]), set(state["weightDefaults"]))
        self.assertTrue([name for name in os.listdir(self.folder) if name.startswith("weights.json.broken-")])

    def test_broken_settings_are_not_replaced(self):
        """Повреждённый settings.json не перезаписывается при открытии проекта: сервер отвечает ошибкой,
        а файл остаётся как был, чтобы данные можно было спасти.
        """
        with open(f"{self.folder}/settings.json", "w", encoding="utf-8") as file:
            file.write("{broken")

        self.assertEqual(self.client.post(f"/api/project/{self.NAME}/open").status_code, 400)

        with open(f"{self.folder}/settings.json", encoding="utf-8") as file:
            self.assertEqual(file.read(), "{broken")


class ServerFormatTests(unittest.TestCase):
    """Открытие, импорт и восстановление версии другого формата через сервер."""
    def setUp(self):
        self.client = app.test_client()
        shutil.rmtree(FOLDER, ignore_errors=True)
        self.assertEqual(self.client.post("/api/projects", json={"name": FORMAT_PROJECT}).status_code, 200)

    def tearDown(self):
        for name in (FORMAT_PROJECT, FORMAT_IMPORTED):
            shutil.rmtree(f"{PATH_TO_FOLDER}/projects/{name}", ignore_errors=True)

    def test_open_old_project_explains(self):
        """Открытие проекта старого формата — понятная ошибка, файл не меняется."""
        old = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}}
        writeProject("settings.json", old)

        response = self.client.post(f"/api/project/{FORMAT_PROJECT}/open")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], translate("web.error.old_project"))
        self.assertEqual(readProject("settings.json"), old)

    def test_import_old_archive_explains(self):
        """Архив проекта старого формата не импортируется: понятная ошибка, папка не появляется."""
        writeProject("settings.json", {"classes": {"custom_groups": [], "lessons": {}}, "base_math_version": 2})

        with tempfile.TemporaryDirectory() as folder:
            archive = os.path.join(folder, "old.zip")
            exportProjectArchive(FOLDER, archive)

            with self.assertRaises(ValueError) as error:
                importProjectArchive(archive, FORMAT_IMPORTED)

            self.assertEqual(str(error.exception), "web.error.old_archive")

            with open(archive, "rb") as file:
                response = self.client.post("/api/projects/import", data={"file": (io.BytesIO(file.read()), "old.zip"), "name": FORMAT_IMPORTED},
                                            content_type="multipart/form-data")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], translate("web.error.old_archive"))
        self.assertFalse(os.path.exists(f"{PATH_TO_FOLDER}/projects/{FORMAT_IMPORTED}"))

    def test_import_unnumbered_archive_of_current_content(self):
        """Архив без "format", но с отметками 04.10.2026 импортируется и получает номер формата."""
        writeProject("settings.json", unnumbered(readProject("settings.json")))

        with tempfile.TemporaryDirectory() as folder:
            archive = os.path.join(folder, "project.zip")
            exportProjectArchive(FOLDER, archive)

            with open(archive, "rb") as file:
                response = self.client.post("/api/projects/import", data={"file": (io.BytesIO(file.read()), "project.zip"), "name": FORMAT_IMPORTED},
                                            content_type="multipart/form-data")

        self.assertEqual(response.get_json(), {"project": FORMAT_IMPORTED})

        with open(f"{PATH_TO_FOLDER}/projects/{FORMAT_IMPORTED}/settings.json", encoding="utf-8") as file:
            self.assertEqual(json.load(file)["format"], PROJECT_FORMAT)

    def test_restore_old_version_explains(self):
        """Версия, сохранённая до номера формата и без отметок 04.10.2026, не восстанавливается:
        понятная ошибка, проект и список версий не меняются. Версия с отметками восстанавливается."""
        current = readProject("settings.json")
        old = {key: value for key, value in current.items() if key != "format"}
        old["iterations"] = 123456
        writeProject("settings.json", old)
        version = saveVersion(FOLDER, "старая")
        writeProject("settings.json", current)

        response = self.client.post(f"/api/project/{FORMAT_PROJECT}/action", json={"action": "restore", "args": {"version": version}})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], translate("web.error.old_version"))
        self.assertEqual(readProject("settings.json"), current)
        self.assertEqual(len(os.listdir(os.path.join(FOLDER, "versions"))), 1)

        # Та же версия с отметками 04.10.2026 — восстанавливается и получает номер формата
        marked = dict(old, pair_rules_version=2, base_math_version=2)

        with open(os.path.join(FOLDER, "versions", version, "settings.json"), "w", encoding="utf-8") as file:
            json.dump(marked, file, ensure_ascii=False)

        response = self.client.post(f"/api/project/{FORMAT_PROJECT}/action", json={"action": "restore", "args": {"version": version}})

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(readProject("settings.json")["iterations"], 123456)
        self.assertEqual(readProject("settings.json")["format"], PROJECT_FORMAT)

    def test_only_one_teacher_limit(self):
        """В состоянии проекта одно ограничение — курсов на преподавателя; других ключей setLimit не принимает."""
        self.client.post(f"/api/project/{FORMAT_PROJECT}/open")
        state = self.client.get(f"/api/project/{FORMAT_PROJECT}").get_json()

        self.assertEqual(state["limits"], {"max_courses_per_teacher": 5})

        for key in ("max_teachers_per_course", "max_teachers_per_stream"):
            response = self.client.post(f"/api/project/{FORMAT_PROJECT}/action", json={"action": "setLimit", "args": {"key": key, "value": 3}})
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(key, readProject("settings.json"))

        response = self.client.post(f"/api/project/{FORMAT_PROJECT}/action", json={"action": "setLimit", "args": {"key": "max_courses_per_teacher", "value": 4}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(readProject("settings.json")["max_courses_per_teacher"], 4)


class JointProjectTests(RealProjectCase):
    """Отметка «вместе с Потоком N» в версиях и в архиве проекта (проект builders.jointProject)."""
    NAME = "__test_joint_projects__"

    def assertJoint(self, project):
        """В проекте ``project`` копии отмечены «вместе с Потоком 1», их уроки равны урокам
        источников, накладок по общим урокам нет, а часы копии не меняются (отказ web.error.joint_locked «Курс присоединён к Потоку 1: …»).
        """
        folder = f"{PROJECTS}/{project}"
        groups = {group["name"]: group for group in readJson(f"{folder}/settings.json")["classes"]["custom_groups"]}
        answer = readJson(f"{folder}/answer.json")

        for copy_, source in JOINT_COPIES.items():
            self.assertEqual(groups[copy_].get("together_with"), 1, copy_)
            self.assertEqual(answer[copy_], answer[source], copy_)

        self.assertEqual(self.client.get(f"/api/project/{project}").get_json()["clashes"], [])

        response = self.client.post(f"/api/project/{project}/action",
                                    json={"action": "setHours", "args": {"course": jointCourse(2, "Математика"), "subject": "Математика", "hours": 1}})
        key = "web.error.joint_locked"
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertText(key, response.get_json()["error"])

    def test_restored_versions_bring_back_marks(self):
        """AC-35: версия до отметки возвращает обычные курсы (без отметки и без уроков копий),
        версия с отметкой — отметку и общие уроки; после восстановления накладок по общим урокам нет.
        """
        settings, answer = jointProject()
        self.openProject(settings, answer)
        plain = saveVersion(self.folder, "без отметки", "", ["1"])
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.useProject(settings, answer)
        marked = saveVersion(self.folder, "с отметкой", "", ["1"])

        self.ok("restore", version=plain)

        self.assertFalse([group["name"] for group in self.load("settings.json")["classes"]["custom_groups"] if "together_with" in group])
        self.assertFalse(set(JOINT_COPIES) & set(self.load("answer.json")))

        self.ok("restore", version=marked)

        self.assertJoint(self.NAME)

    def test_project_archive_keeps_marks(self):
        """AC-36: «Экспорт → Весь проект» → «Импорт проекта»: у копий together_with на месте, их уроки
        равны урокам источников, поведение как до выгрузки (накладок нет, часы копии закрыты).
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        self.addCleanup(shutil.rmtree, f"{PROJECTS}/{JOINT_IMPORTED}", ignore_errors=True)

        data = self.client.get(f"/api/project/{self.NAME}/export/project").data
        response = self.client.post("/api/projects/import", data={"file": (io.BytesIO(data), "joint.zip"), "name": JOINT_IMPORTED},
                                    content_type="multipart/form-data")

        self.assertEqual(response.get_json(), {"project": JOINT_IMPORTED})
        self.assertEqual(self.client.post(f"/api/project/{JOINT_IMPORTED}/open").status_code, 200)
        self.assertJoint(JOINT_IMPORTED)
