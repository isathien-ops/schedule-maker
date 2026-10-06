"""Разбор книги расписания 2026/27 скриптом `tools/import_26_27.py` (функция ``parse``).

* ``SeminarRowsTests`` — семинар, записанный на листе потока в двух блоках (например, в блоке ЕГЭ и в
  блоке «10 класс») одной и той же строкой, — это один урок, а не два: число уроков в неделю
  считается по различным слотам курса.

Книга собирается здесь же, в памяти, из нескольких строк (openpyxl): настоящая выгрузка таблицы для
теста не нужна.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
import shutil
import sys
import tempfile
import unittest

import openpyxl

# Скрипты tools импортируют друг друга по имени модуля (папка tools в пути импорта) — так же,
# как их видит запуск из командной строки
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import import_26_27  # noqa: E402

# Ячейки строки семинара в блоке листа: предмет, день, часы, отметка «ДОП» (дополнительный курс), преподаватель
SEMINAR_SATURDAY = ("Химия", "СБ", "10:00 - 11:30", "ДОП", "Иванова Анна")
SEMINAR_SUNDAY = ("Химия", "ВС", "10:00 - 11:30", "ДОП", "Иванова Анна")
# Два блока листа потока: столбцы A–E и G–K
BLOCKS = ("ABCDE", "GHIJK")


class SeminarRowsTests(unittest.TestCase):
    """Один и тот же семинар в двух блоках листа — один урок."""
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def book(self, rows):
        """Сохраняет книгу с листами обоих потоков и возвращает путь к ней. ``rows`` — {номер строки
        листа Потока 1: [(столбцы блока, ячейки строки)]}; лист Потока 2 пуст.
        """
        book = openpyxl.Workbook()
        first = book.active
        first.title = import_26_27.SHEETS[1]
        book.create_sheet(import_26_27.SHEETS[2])

        for row, blocks in rows.items():
            for columns, values in blocks:
                for column, value in zip(columns, values):
                    first[f"{column}{row}"] = value

        path = os.path.join(self.folder, "book.xlsx")
        book.save(path)

        return path

    def test_same_seminar_in_two_blocks_is_one_lesson(self):
        """Семинар «Химия» в субботу 10:00 записан в обоих блоках листа (строка 6), ещё один его урок —
        в воскресенье (строка 7, только первый блок). Курс один, уроков в неделю 2, а не 3
        (раньше повтор строки во втором блоке считался ещё одним уроком).
        """
        path = self.book({
            6: [(columns, SEMINAR_SATURDAY) for columns in BLOCKS],
            7: [(BLOCKS[0], SEMINAR_SUNDAY)],
        })

        self.assertEqual(import_26_27.parse(path)["courses"], [{
            "stream": None, "line": "Семинар ЕГЭ продвинутый", "subject": "Химия",
            "slots": [[5, 0], [6, 0]], "teachers": ["Иванова Анна"], "hours": 2,
        }])


if __name__ == "__main__":
    unittest.main()
