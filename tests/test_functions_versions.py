"""Сохранённые версии проекта (`src/modules/functions/versions.py`).

Версия — снимок файлов проекта (settings.json, weights.json, answer.json) с именем и комментарием.
Перед опасными действиями программа сохраняет версию «Перед: …», и пользователь может к ней вернуться.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import datetime
import json
import os
import tempfile
import unittest

from src.modules.functions import files
from src.modules.functions.versions import deleteVersion, listVersions, restoreVersion, saveVersion
from tests.builders import TempFolderCase, readJson, writeText


def write(path, data):
    """Записывает `data` в JSON-файл `path`."""
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file)


class VersionTests(unittest.TestCase):
    """Сохранение, восстановление и удаление версий."""
    def test_save_restore_delete(self):
        """Две версии, сохранённые в одну секунду, не затирают друг друга; версия без имени получает
        имя по дате; восстановление возвращает файлы и убирает появившиеся позже (варианты этапов);
        удалённую версию восстановить нельзя.
        """
        with tempfile.TemporaryDirectory() as project:
            answer = {"Курс": [[{"subject": "Химия", "teachers": ["А"]}, {"subject": "#", "teachers": []}]]}

            write(os.path.join(project, "settings.json"), {"iterations": 1})
            write(os.path.join(project, "weights.json"), {"softSubjectPair": 500})
            write(os.path.join(project, "answer.json"), answer)

            first = saveVersion(project, "Черновик", " согласовать ", ["1"], now=datetime.datetime(2026, 10, 3, 12, 0))
            same_second = saveVersion(project, "", "", [], now=datetime.datetime(2026, 10, 3, 12, 0))

            self.assertNotEqual(first, same_second)

            versions = listVersions(project)
            self.assertEqual(len(versions), 2)

            meta = dict(versions)[first]
            self.assertEqual((meta["name"], meta["comment"], meta["lessons"], meta["stages"]), ("Черновик", "согласовать", 1, ["1"]))
            self.assertEqual(dict(versions)[same_second]["name"], "03.10.2026 12:00")

            # Проект меняется, затем возвращается к первой версии
            write(os.path.join(project, "settings.json"), {"iterations": 2})
            os.remove(os.path.join(project, "answer.json"))
            os.makedirs(os.path.join(project, "stages", "1.variants"))

            restoreVersion(project, first)

            self.assertEqual(readJson(os.path.join(project, "settings.json")), {"iterations": 1})
            self.assertEqual(readJson(os.path.join(project, "answer.json")), answer)
            self.assertFalse(os.path.exists(os.path.join(project, "stages")))

            deleteVersion(project, first)
            self.assertEqual([version for version, _ in listVersions(project)], [same_second])

            with self.assertRaises(FileNotFoundError):
                restoreVersion(project, first)


class VersionEdgeTests(TempFolderCase):
    """Версии проекта: испорченные описания и восстановление версии без расписания."""
    def test_broken_meta_is_skipped(self):
        """Папка версии без meta.json или с meta.json не-объектом в список не попадает."""
        good = saveVersion(self.folder, "Хорошая")
        os.makedirs(os.path.join(self.folder, "versions", "без-описания"))
        os.makedirs(os.path.join(self.folder, "versions", "список"))
        writeText(os.path.join(self.folder, "versions", "список", "meta.json"), "[1]")

        self.assertEqual([version for version, _ in listVersions(self.folder)], [good])

    def test_restore_version_without_schedule(self):
        """Версия, сохранённая до первого расписания: восстановление убирает answer.json и варианты;
        неизвестная версия — FileNotFoundError, файлы не трогаются.
        """
        files.writeJson(os.path.join(self.folder, "settings.json"), {"format": 1})
        version = saveVersion(self.folder, "До расписания")

        files.writeJson(os.path.join(self.folder, "answer.json"), {"Курс": []})
        os.makedirs(os.path.join(self.folder, "stages", "1.variants"))

        with self.assertRaises(FileNotFoundError):
            restoreVersion(self.folder, "нет-такой")

        self.assertTrue(os.path.exists(os.path.join(self.folder, "answer.json")))

        restoreVersion(self.folder, version)

        self.assertFalse(os.path.exists(os.path.join(self.folder, "answer.json")))
        self.assertFalse(os.path.exists(os.path.join(self.folder, "stages")))
        self.assertEqual(readJson(os.path.join(self.folder, "settings.json")), {"format": 1})


class VersionIdTests(unittest.TestCase):
    """Имена папок версий, сохранённых в одну секунду."""
    def test_version_ids_in_one_second(self):
        """Версии в одну секунду: «20261003-120000», затем «-2», «-3»."""
        now = datetime.datetime(2026, 10, 3, 12, 0, 0)

        with tempfile.TemporaryDirectory() as project:
            ids = [saveVersion(project, "v", now=now) for _ in range(3)]

        self.assertEqual(ids, ["20261003-120000", "20261003-120000-2", "20261003-120000-3"])
