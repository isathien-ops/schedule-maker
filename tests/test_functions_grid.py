"""Сетка уроков недели (`src/modules/functions/grid.py`).

Сетка (``day_grid``) задаёт для каждого дня недели список времён уроков, например «16:20 - 17:50».
Проверяются:
* ``GridTests`` — разбор времени, введённого человеком (``parseTime``), число рабочих дней и уроков
  в день по сетке и то, что в «дырах» сетки решатель ничего не ставит;
* ``GridBoundaryTests`` — границы времени урока: час 24, урок нулевой длины, уроки встык;
* ``ParseGridTests`` — ``parseGrid``: сетка с «Настроек» в нормальной форме или ``GridError``;
* ``GridEditTests`` и ``GridRemapTests`` — перенос расписания, закреплений, отметок и своих
  правил на новую сетку (``remapAnswer``, ``lostPins``, ``remapSettings``, ``renamePenaltyTimes``).
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import json
import os
import subprocess
import tempfile
import unittest

from src.modules.functions.grid import (
    DAYS, GridError, MAX_LESSONS_PER_DAY, columnMapping, dayGrid, keepsColumns, lessonExists, lostPins, missingSlots,
    parseClock, parseGrid, parseTime, remapAnswer, remapSettings, remapWeek, renamedTimes, setDayGrid, timeOrderProblem
)
from src.modules.functions.penalties import renamePenaltyTimes
from src.modules.functions.solver_input import buildStageSettings
from src.modules.functions.stages import getStages, mergeStageAnswer
from tests.builders import SOLVER, chemistryWeek, makeSettings

A, B, C = "16:20 - 17:50", "18:00 - 19:30", "19:40 - 21:10"


def filled(answer_week):
    """Занятые ячейки недели: [(день, урок)]."""
    return [(day, lesson) for day, cells in enumerate(answer_week) for lesson, cell in enumerate(cells) if cell["subject"] != "#"]


class GridTests(unittest.TestCase):
    """Разбор времени, размер сетки и уроки только в существующих ячейках сетки."""
    def test_parse_time(self):
        """Время урока, набранное по-разному («16.20-17.50», «16ч20 - 17ч50» и т.п.), приводится
        к виду «16:20 - 17:50», а бессмыслица и неверные интервалы отвергаются (None).
        """
        self.assertEqual(parseTime(" 9:05-10:35 "), "09:05 - 10:35")

        # Обычные способы, которыми люди набирают время
        for text in ("16.20-17.50", "16,20 – 17,50", "16.20 - 17.50", "1620-1750", "16:20 до 17:50",
                     "16.20 17.50", "16-20-17-50", "16ч20 - 17ч50", "16 20 - 17 50", "16:20—17:50"):
            self.assertEqual(parseTime(text), "16:20 - 17:50", text)

        self.assertEqual(parseTime("16-18"), "16:00 - 18:00")
        self.assertEqual(parseTime("9.5-10.35"), None)
        self.assertIsNone(parseTime("abc"))
        self.assertIsNone(parseTime("16:20 - 17:50 - 19:00"))
        self.assertEqual(parseTime("16:20 – 17:50"), "16:20 - 17:50")
        self.assertEqual(parseTime(""), "")
        self.assertIsNone(parseTime("16:20"))
        self.assertIsNone(parseTime("18:00 - 17:00"))
        self.assertIsNone(parseTime("25:00 - 26:00"))

    def test_grid_derives_week_and_drops_gaps(self):
        """По сетке определяются число рабочих дней и максимум уроков в день; пустые времена
        выкидываются, а уроки после пустого сдвигаются вперёд; список несуществующих слотов верен.
        """
        settings = {}
        setDayGrid(settings, [
            ["16:20 - 17:50", "", "19:40 - 21:10"],
            ["16:20 - 17:50"],
            [], [], [],
            ["10:00 - 11:30", "11:40 - 13:10"],
            []
        ])

        self.assertEqual(settings["working_days_per_week"], 6)
        self.assertEqual(settings["max_lesson_count_per_day"], 2)
        self.assertEqual(dayGrid(settings)[0][1], "19:40 - 21:10")
        self.assertFalse(lessonExists(settings, 1, 1))
        self.assertEqual(missingSlots(settings), [[1, 1], [2, 0], [2, 1], [3, 0], [3, 1], [4, 0], [4, 1]])

    def test_missing_slots_are_closed_for_the_stage(self):
        """Слоты, которых нет в сетке (в пятницу только один урок), закрываются для всех учителей
        и курсов во входных данных этапа, чтобы решатель туда ничего не поставил.
        """
        settings = makeSettings()
        grid = [["16:20 - 17:50", "18:00 - 19:30", "19:40 - 21:10"]] * 5 + [[], []]
        grid[4] = ["16:20 - 17:50"]
        setDayGrid(settings, grid)

        stage = buildStageSettings(settings, {}, "1")

        self.assertTrue(all([4, 1] in teacher["free"] and [4, 2] in teacher["free"] for teacher in stage["teachers"].values()))
        self.assertTrue(all([4, 1] in slots for slots in stage["blocked_slots"].values()))

    @unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
    def test_no_lessons_in_missing_slots(self):
        """Реальный запуск solve.exe: все уроки этапа расставлены и ни один не попал в слот,
        которого нет в сетке. Пропускается, если решатель не собран.
        """
        settings = makeSettings()
        grid = [["16:20 - 17:50", "18:00 - 19:30", "19:40 - 21:10"]] * 5 + [[], []]
        grid[4] = ["16:20 - 17:50"]
        setDayGrid(settings, grid)

        stage = next(item for item in getStages(settings) if item["key"] == "1")

        with tempfile.TemporaryDirectory() as folder:
            paths = {name: os.path.join(folder, f"{name}.json") for name in ("settings", "weights", "answer")}

            with open(paths["settings"], "w", encoding="utf-8") as file:
                json.dump(buildStageSettings(settings, {}, "1"), file, ensure_ascii=False)

            with open(paths["weights"], "w", encoding="utf-8") as file:
                file.write("{}")

            subprocess.run([SOLVER, "--weights", paths["weights"], "--input", paths["settings"], "--output", paths["answer"], "--iterations", "200000"],
                           check=True, capture_output=True, timeout=120)

            with open(paths["answer"], "r", encoding="utf-8") as file:
                answer = mergeStageAnswer({}, json.load(file), stage["courses"])

        placed = 0

        for week in answer.values():
            for day, lessons in enumerate(week):
                for lesson, cell in enumerate(lessons):
                    if cell.get("subject", "#") != "#":
                        placed += 1
                        self.assertTrue(lessonExists(settings, day, lesson), (day, lesson))

        expected = sum(
            hours for name in stage["courses"]
            for hours in settings["classes"]["lessons"].get(name, {}).values()
        )
        self.assertEqual(placed, expected)


class GridBoundaryTests(unittest.TestCase):
    """Границы времени урока в сетке."""
    def test_hour_24_is_not_a_time(self):
        """Часа 24 нет: «24:00» не читается, «23:59» — последнее допустимое время."""
        self.assertIsNone(parseClock("24:00"))
        self.assertEqual(parseClock("23:59"), (23, 59))
        self.assertEqual(parseClock("0:00"), (0, 0))
        self.assertIsNone(parseTime("23:00 - 24:00"))
        self.assertEqual(parseTime("22:00 - 23:59"), "22:00 - 23:59")

    def test_zero_length_lesson_is_rejected(self):
        """Урок, который кончается в момент начала, — ошибка ввода (None)."""
        self.assertIsNone(parseTime("16:20 - 16:20"))
        self.assertIsNone(parseTime("16.20 16.20"))
        self.assertEqual(parseTime("16:20 - 16:21"), "16:20 - 16:21")

    def test_back_to_back_lessons_do_not_overlap(self):
        """Уроки встык (конец одного = начало другого) не пересекаются; на минуту раньше — пересекаются."""
        self.assertIsNone(timeOrderProblem(["16:20 - 17:50", "17:50 - 19:20"]))
        self.assertEqual(timeOrderProblem(["16:20 - 17:50", "17:49 - 19:20"]), ("16:20 - 17:50", "17:49 - 19:20"))


class ParseGridTests(unittest.TestCase):
    """parseGrid: сетка с «Настроек» в нормальной форме или GridError."""
    def test_normal_form_keeps_empty_cells_in_place(self):
        """Время приводится к «ЧЧ:ММ - ЧЧ:ММ», пустые ячейки остаются на своих местах как ""."""
        self.assertEqual(parseGrid([["16.20-17.50", " ", "19:40 до 21:10"], [], ["9-10"]]),
                         [[A, "", C], [], ["09:00 - 10:00"]])

    def test_extra_days_and_cells_are_dropped(self):
        """Дней больше семи и ячеек больше MAX_LESSONS_PER_DAY — лишнее отбрасывается."""
        cells = [f"{hour}:00 - {hour}:45" for hour in range(10, 10 + MAX_LESSONS_PER_DAY + 2)]
        grid = parseGrid([cells] * (DAYS + 2))

        self.assertEqual(len(grid), DAYS)
        self.assertEqual(grid[0], cells[:MAX_LESSONS_PER_DAY])

    def test_unreadable_time(self):
        """Время не читается — GridError("invalid") с текстом ячейки без пробелов по краям."""
        with self.assertRaises(GridError) as caught:
            parseGrid([[A], ["  когда-нибудь  "]])

        self.assertEqual((caught.exception.kind, caught.exception.details), ("invalid", {"text": "когда-нибудь"}))

    def test_times_out_of_order(self):
        """Времена дня пересекаются или идут назад — GridError("order") с номером дня и парой времён."""
        with self.assertRaises(GridError) as caught:
            parseGrid([[A, B], [B, "", A]])

        self.assertEqual((caught.exception.kind, caught.exception.details), ("order", {"day": 1, "first": B, "second": A}))


class GridEditTests(unittest.TestCase):
    """Перенос расписания, закреплений, отметок и правил на новую сетку."""
    OLD = [[A, B, C]] * 5 + [[], []]

    def test_remap_answer_moves_and_counts_lost_lessons(self):
        """Очищена вторая ячейка понедельника: третий урок сдвигается на её место (номер 1),
        урок из очищенной ячейки теряется; курсы без потерь получают 0.
        """
        columns = [[A, "", C]] + self.OLD[1:]
        mapping = columnMapping(self.OLD, columns)
        answer = {"первый": chemistryWeek((0, 1), (0, 2), (2, 0)), "второй": chemistryWeek((3, 2))}

        weeks, lost = remapAnswer(answer, mapping, columns)

        self.assertEqual(lost, {"первый": 1, "второй": 0})
        self.assertEqual(filled(weeks["первый"]), [(0, 1), (2, 0)])
        self.assertEqual(len(weeks["первый"][0]), 2)
        self.assertEqual(filled(weeks["второй"]), [(3, 2)])

    def test_lost_pins(self):
        """Закрепления в ячейках, которых нет в соответствии, считаются потерянными."""
        settings = {"constants": {"первый": {"0-1": "Химия", "0-2": "Химия"}, "второй": {"1-1": "Химия"}}}
        mapping = columnMapping(self.OLD, [[A, "", C]] + self.OLD[1:])

        self.assertEqual(lostPins(settings, mapping), 1)
        self.assertEqual(lostPins({}, mapping), 0)

    def test_keeps_columns(self):
        """Поменялось только время или добавилась ячейка в конце дня — столбцы те же; очищенная
        ячейка в середине дня сдвигает уроки.
        """
        retimed = [["16:00 - 17:30", B, C, "21:20 - 22:00"]] + self.OLD[1:]
        self.assertTrue(keepsColumns(self.OLD, columnMapping(self.OLD, retimed)))
        self.assertFalse(keepsColumns(self.OLD, columnMapping(self.OLD, [[A, "", C]] + self.OLD[1:])))

    def test_renamed_times(self):
        """Переписанное время попадает в словарь, только если старого текста нет ни в одном дне:
        16:20 переписали в понедельник, но во вторник оно осталось — не переименование.
        """
        later = "19:45 - 21:15"
        grid = [["16:00 - 17:30", B, later]] + [[A, B, later]] * 4 + [[], []]

        self.assertEqual(renamedTimes(self.OLD, grid), {C: later})
        self.assertEqual(renamedTimes(self.OLD, self.OLD), {})

    def test_remap_settings_moves_pins_and_marks(self):
        """Закрепления и отметки «может / не может» переезжают на новые номера уроков;
        стоявшие в очищенной ячейке — пропадают.
        """
        settings = {
            "constants": {"первый": {"0-1": "Химия", "0-2": "Химия", "1-0": "Химия"}},
            "teachers": {"Химия #1": {"availability": {"2": {"free": [[0, 1], [0, 2]], "possible": [[1, 2]]}}}},
        }
        mapping = columnMapping(self.OLD, [[A, "", C]] + self.OLD[1:])

        self.assertIs(remapSettings(settings, mapping), settings)
        self.assertEqual(settings["constants"], {"первый": {"0-1": "Химия", "1-0": "Химия"}})
        self.assertEqual(settings["teachers"]["Химия #1"]["availability"]["2"], {"free": [[0, 1]], "possible": [[1, 2]]})

    def test_rename_penalty_times(self):
        """В правилах «Не ставить уроки в выбранное время» старое время заменяется новым, слившиеся повторы
        убираются, порядок прежний; правила других видов не трогаются.
        """
        settings = {"custom_penalties": [
            {"template": "time", "params": {"times": [A, B, C]}},
            {"template": "adjacent", "params": {"times": [A]}},
        ]}
        before = copy.deepcopy(settings["custom_penalties"][1])

        renamePenaltyTimes(settings, {A: B, C: "20:00 - 21:30"})

        self.assertEqual(settings["custom_penalties"][0]["params"]["times"], [B, "20:00 - 21:30"])
        self.assertEqual(settings["custom_penalties"][1], before)


class GridRemapTests(unittest.TestCase):
    """Перенос уроков при изменении сетки времени."""
    def test_cleared_middle_time_keeps_later_lessons_in_place(self):
        """Если в сетке стереть среднее время, урок этого времени уходит, а более поздние уроки остаются
        в своё время (19:40 остаётся 19:40), а не сдвигаются на освободившееся место.
        """
        old = [["16:20 - 17:50", "18:00 - 19:30", "19:40 - 21:10"]] + [[] for _ in range(DAYS - 1)]
        columns = [["16:20 - 17:50", "", "19:40 - 21:10"]] + [[] for _ in range(DAYS - 1)]
        mapping = columnMapping(old, columns)

        self.assertEqual(mapping, {(0, 0): 0, (0, 2): 1})

        lesson = {"subject": "Химия", "teachers": ["А"]}
        empty = {"subject": "#", "teachers": []}
        week, lost = remapWeek([[empty, lesson, dict(lesson, subject="Физика")]] + [[] for _ in range(DAYS - 1)], mapping,
                               [["16:20 - 17:50", "19:40 - 21:10"]] + [[] for _ in range(DAYS - 1)])

        self.assertEqual(lost, 1)                      # урок 18:00 уходит
        self.assertEqual(week[0][1]["subject"], "Физика")  # 19:40 остаётся 19:40
