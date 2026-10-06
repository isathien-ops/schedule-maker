"""Файлы программы: JSON-файлы проекта (`src/modules/functions/files.py`) и папка данных (`src/variables.py`).

Главное — испорченные и неожиданные файлы: они не должны ни ронять программу, ни молча стирать
данные пользователя.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
import runpy
import shutil
import tempfile
import unittest
from unittest import mock

import tests
from src.variables import DATA_DIR_VARIABLE, PATH_TO_FOLDER
from src.modules.functions import files
from src.modules.functions.files import readAnswer
from tests.builders import TempFolderCase, readJson, writeText


class JsonFileTests(TempFolderCase):
    """Чтение и атомарная запись JSON-файлов."""
    def test_read_missing_or_broken_gives_default(self):
        """Нет файла или он испорчен (не JSON, не UTF-8) — значение по умолчанию, без ошибки."""
        path = os.path.join(self.folder, "a.json")
        self.assertEqual(files.readJson(path, {"нет": 1}), {"нет": 1})

        writeText(path, "{испорчено")
        self.assertIsNone(files.readJson(path, None))

        with open(path, "wb") as file:
            file.write(b"\xff\xfe\x00")

        self.assertEqual(files.readJson(path, []), [])

    def test_write_keeps_cyrillic_and_leaves_no_temp(self):
        """Кириллица пишется как есть, компактная запись — в одну строку, временного файла не остаётся."""
        path = os.path.join(self.folder, "a.json")

        files.writeJson(path, {"курс": [1, 2]}, indent=None)

        with open(path, "r", encoding="utf-8") as file:
            self.assertEqual(file.read(), '{"курс": [1, 2]}')

        self.assertEqual(os.listdir(self.folder), ["a.json"])

    def test_write_retries_when_file_is_busy(self):
        """Файл ненадолго занят (антивирус, читатель) — запись повторяется и в итоге проходит."""
        path = os.path.join(self.folder, "a.json")
        files.writeJson(path, {"старое": True})
        real = os.replace
        failures = [PermissionError, PermissionError]

        def busy(source, target):
            """Первые две попытки — «файл занят», третья — настоящая замена."""
            if failures:
                raise failures.pop()

            real(source, target)

        with mock.patch.object(files.os, "replace", side_effect=busy) as replace, \
                mock.patch.object(files.time, "sleep") as sleep:
            files.writeJson(path, {"новое": True})

        self.assertEqual(readJson(path), {"новое": True})
        self.assertEqual(replace.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_write_gives_up_and_keeps_old_file(self):
        """Файл занят постоянно — после 10 попыток ошибка PermissionError, старый файл цел."""
        path = os.path.join(self.folder, "a.json")
        files.writeJson(path, {"старое": True})

        with mock.patch.object(files.os, "replace", side_effect=PermissionError) as replace, mock.patch.object(files.time, "sleep"):
            with self.assertRaises(PermissionError):
                files.writeJson(path, {"новое": True})

        self.assertEqual(replace.call_count, 10)
        self.assertEqual(readJson(path), {"старое": True})


class ReadAnswerTests(unittest.TestCase):
    """Чтение принятого расписания answer.json (``files.readAnswer``)."""
    NAME = "__test_functions_files__"

    def setUp(self):
        """Чистая папка тестового проекта и папка для архивов."""
        self.path = f"{PATH_TO_FOLDER}/projects/{self.NAME}"
        shutil.rmtree(self.path, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.path, ignore_errors=True)
        self.temp = tempfile.mkdtemp(prefix="cov-archives-")
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)

    def test_load_answer(self):
        """Принятое расписание: нет файла — пусто; испорчен или не объект — ошибка, а не пустое
        расписание (иначе следующее сохранение его бы стёрло).
        """
        os.makedirs(self.path)
        path = f"{self.path}/answer.json"
        self.assertEqual(files.readAnswer(path), {})

        for text in ("{испорчено", "[]", "null"):
            writeText(path, text)

            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "^web.error.broken_answer$"):
                files.readAnswer(path)

        writeText(path, '{"Курс": []}')
        self.assertEqual(files.readAnswer(path), {"Курс": []})

    def test_read_answer(self):
        """Нет файла — {}; словарь — он сам; испорчен или не словарь — ValueError с ключом перевода."""
        folder = tempfile.mkdtemp(prefix="schedule-answer-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "answer.json")

        self.assertEqual(readAnswer(path), {})

        writeText(path, '{"курс": []}')
        self.assertEqual(readAnswer(path), {"курс": []})

        for text in ("{broken", "[]", "null"):
            writeText(path, text)

            with self.assertRaises(ValueError) as caught:
                readAnswer(path)

            self.assertEqual(str(caught.exception), "web.error.broken_answer", text)


class DataFolderTests(TempFolderCase):
    """Папка данных программы (src/variables.py) — выполняется заново, не меняя загруженный модуль.

    Автотесты сами задают SCHEDULE_DATA_DIR (tests/__init__.py), поэтому каждый тест собирает
    окружение заново: без неё, если проверяется %APPDATA% или рабочая папка.
    """
    def environ(self, **values):
        """Окружение процесса без SCHEDULE_DATA_DIR и APPDATA, плюс `values`."""
        environ = {key: value for key, value in os.environ.items() if key not in (DATA_DIR_VARIABLE, "APPDATA")}
        return mock.patch.dict(os.environ, {**environ, **values}, clear=True)

    def test_variable_name(self):
        """Переменная, которую задают автотесты, — та, что читает программа."""
        self.assertEqual(DATA_DIR_VARIABLE, "SCHEDULE_DATA_DIR")
        self.assertEqual(os.environ[DATA_DIR_VARIABLE], tests.DATA_DIR)

    def test_data_dir_variable_wins_over_appdata(self):
        """SCHEDULE_DATA_DIR задана — данные в ней, даже если есть APPDATA; пустая — не в счёт."""
        appdata = os.path.join(self.folder, "appdata")

        with self.environ(**{DATA_DIR_VARIABLE: self.folder, "APPDATA": appdata}):
            values = runpy.run_path(os.path.join("src", "variables.py"))

        self.assertEqual(values["PATH_TO_FOLDER"], f"{self.folder}/Schedule-Maker-1")
        self.assertTrue(os.path.isdir(os.path.join(self.folder, "Schedule-Maker-1", "projects")))
        self.assertFalse(os.path.exists(appdata))

        with self.environ(**{DATA_DIR_VARIABLE: "", "APPDATA": appdata}):
            self.assertEqual(runpy.run_path(os.path.join("src", "variables.py"))["getAppDataDir"](), appdata)

    def test_folder_in_appdata(self):
        """При APPDATA (без SCHEDULE_DATA_DIR) данные лежат в %APPDATA%/Schedule-Maker-1,
        папка projects создаётся сразу.
        """
        with self.environ(APPDATA=self.folder):
            values = runpy.run_path(os.path.join("src", "variables.py"))

        self.assertEqual(values["PATH_TO_FOLDER"], f"{self.folder}/Schedule-Maker-1")
        self.assertTrue(os.path.isdir(os.path.join(self.folder, "Schedule-Maker-1", "projects")))

    def test_folder_without_appdata(self):
        """Без SCHEDULE_DATA_DIR и APPDATA (не Windows) — папка программы в текущей рабочей папке."""
        with self.environ(), mock.patch("os.getcwd", return_value=self.folder):
            values = runpy.run_path(os.path.join("src", "variables.py"))
            folder = values["getAppDataDir"]()

        self.assertEqual(folder, self.folder)
        self.assertEqual(values["PATH_TO_FOLDER"], f"{self.folder}/Schedule-Maker-1")
        self.assertTrue(os.path.isdir(os.path.join(self.folder, "Schedule-Maker-1", "projects")))
