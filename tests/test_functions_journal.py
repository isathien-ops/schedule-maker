"""Журнал программы app.log и журналы сборок (`src/modules/functions/journal.py`)."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import logging.handlers
import os
import shutil
import tempfile
import unittest
from unittest import mock

from src.modules.functions import journal
from tests.builders import TempFolderCase


class LoggingTests(TempFolderCase):
    """Подключение файла журнала программы app.log."""
    def setUp(self):
        """Журнал «schedule» временно без обработчиков; прежние возвращаются после теста."""
        super().setUp()
        saved = list(journal.logger.handlers)
        journal.logger.handlers = []

        def restore():
            for handler in journal.logger.handlers:
                handler.close()

            journal.logger.handlers = saved

        self.addCleanup(restore)

    def test_setup_once_and_writes_to_file(self):
        """Повторное подключение не добавляет второй файл; запись попадает в logs/app.log."""
        logs = os.path.join(self.folder, "logs")

        with mock.patch.object(journal, "LOG_DIR", logs):
            first = journal.setupLogging()
            second = journal.setupLogging()

        self.assertIs(first, second)
        handlers = [handler for handler in journal.logger.handlers if isinstance(handler, logging.handlers.RotatingFileHandler)]
        self.assertEqual(len(handlers), 1)

        journal.logger.info("проверка журнала")
        handlers[0].flush()

        with open(os.path.join(logs, "app.log"), "r", encoding="utf-8") as file:
            self.assertIn("проверка журнала", file.read())

    def test_no_access_to_folder(self):
        """Папку журнала создать нельзя — программа работает без журнала (без ошибки)."""
        with mock.patch.object(journal.os, "makedirs", side_effect=OSError):
            logger = journal.setupLogging()

        self.assertIs(logger, journal.logger)
        self.assertEqual(logger.handlers, [])


class JournalTests(unittest.TestCase):
    """Журналы сборок и короткий текст для журнала."""
    def test_short(self):
        """Значение для журнала — одной строкой и не длиннее предела (с «…» в конце)."""
        self.assertEqual(journal.short({"a": "x\ny"}), "{'a': 'x\\ny'}")
        self.assertEqual(journal.short("строка\n  с   пробелами"), "'строка\\n с пробелами'")
        self.assertEqual(journal.short(["a b", "c"], 5), "['a b…")
        self.assertEqual(journal.short("abc " * 200, 400)[-1], "…")

    def test_build_logs_keep_last_ones_and_safe_names(self):
        """Журналов сборок остаётся не больше KEEP_BUILDS (старые удаляются), а в имени файла нет
        символов, запрещённых в Windows.
        """
        folder = tempfile.mkdtemp(prefix="builds-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)

        for number in range(5):
            open(os.path.join(folder, f"2026-01-0{number + 1} 00-00-00 old.log"), "w").close()

        with mock.patch.object(journal, "BUILDS_DIR", folder), mock.patch.object(journal, "KEEP_BUILDS", 3):
            log = journal.openBuildLog('проект: "а/б"', "extra")
            log.write("строка\n")
            log.close()

        names = sorted(os.listdir(folder))
        self.assertEqual(len(names), 3)
        self.assertNotIn("2026-01-01 00-00-00 old.log", names)
        new = [name for name in names if "old" not in name][0]
        self.assertFalse(set(new) & set('\\/:*?"<>|'))
        self.assertTrue(new.endswith(" extra.log"))

    def test_build_log_unavailable(self):
        """Если журнал сборки создать нельзя, сборка всё равно идёт (возвращается None)."""
        with mock.patch.object(journal, "BUILDS_DIR", os.path.join(__file__, "нельзя")):
            self.assertIsNone(journal.openBuildLog("p", "1"))

    def test_short_keeps_text_at_limit(self):
        """Текст длиной ровно в предел не обрезается, на символ длиннее — обрезается с «…»."""
        self.assertEqual(journal.short("abc", 5), "'abc'")
        self.assertEqual(journal.short("abcd", 5), "'abcd…")
