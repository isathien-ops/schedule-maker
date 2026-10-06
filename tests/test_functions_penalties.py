"""Свои правила пользователя (`src/modules/functions/penalties.py`, вкладка «Запуск», блок «Свои правила»).

Пользователь задаёт правила с весом: «Не ставить уроки в выбранное время» (time), «Не больше N уроков
в день» (daily_limit), «Уроки курса — не в соседние дни» (adjacent), «Два предмета — в разные дни» (same_day).

* ``PenaltyTests`` — подсчёт нарушений в готовом варианте (``countPenalties``), перевод правил
  во вход решателя (``compilePenalties``) и то, что решатель действительно им следует;
* ``PenaltyEdgeTests`` — неизвестные цели и шаблоны, «каждый преподаватель», сложение штрафов;
* ``DailyLimitTests`` — «не больше N уроков в день»: день ниже лимита не гасит превышение;
* ``PenaltyTextTests`` — описание правила (``describePenalty``) и уроки, которые его нарушают
  (``penaltyLessons``).
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import json
import os
import subprocess
import tempfile
import unittest

from src.modules.translate import translate
from src.modules.functions.courses import addCourse
from src.modules.functions.grid import setDayGrid
from src.modules.functions.penalties import (
    compilePenalties, countPenalties, courseMatches, customId, customKey, describePenalty, dropTargeted, newPenalty, penaltyLessons,
    penaltySlots, penaltyTeachers, sameDayCoursePairs
)
from src.modules.functions.solver_input import buildStageSettings
from src.modules.functions.variants import lessonIssues
from tests.builders import SOLVER, emptySettings, emptyWeek, lesson, place
from tests.fixture_26_27 import buildSettings

GRID = [["16:20 - 17:50", "18:00 - 19:30", "19:40 - 21:10"]] * 5 + [["10:00 - 11:30", "11:40 - 13:10"]] * 2
START = "2026-09-07"


class PenaltyTests(unittest.TestCase):
    """Подсчёт и компиляция пользовательских штрафов на маленьком примере из трёх курсов."""
    def setUp(self):
        """Три курса потока 1 и готовый вариант расписания с известными нарушениями."""
        self.settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {"Иванова Анна": {}, "Петров Пётр": {}}, "day_grid": GRID}

        self.math = addCourse(self.settings, 1, "ЕГЭ основной", "Математика", 2, "2026-09-07")
        self.physics = addCourse(self.settings, 1, "ЕГЭ основной", "Физика", 1, "2026-09-07")
        self.oge = addCourse(self.settings, 1, "ОГЭ", "Физика", 1, "2026-09-07")

        self.variant = {
            # Математика: пн 16:20 и вт 18:00 (соседние дни); Физика ЕГЭ: пн 19:40; Физика ОГЭ: сб 10:00
            self.math: place(place(emptyWeek(), 0, 0, "Математика", "Иванова Анна"), 1, 1, "Математика", "Иванова Анна"),
            self.physics: place(emptyWeek(), 0, 2, "Физика", "Иванова Анна"),
            self.oge: place(emptyWeek(), 5, 0, "Физика", "Петров Пётр"),
        }

    def add(self, *items):
        """Записывает правила `items` в настройки (заменяя прежние) и возвращает их же."""
        self.settings["custom_penalties"] = list(items)

        return items

    def test_counting(self):
        """Каждый вид правила считает нарушения в варианте ровно так, как его понимает пользователь
        (время, лимит в день для учителя и линейки, соседние дни, два предмета в один день).
        """
        weekend = newPenalty("Выходные", "time", 100, {"target": "all", "value": "", "days": [5, 6], "times": ["10:00 - 11:30", "11:40 - 13:10"]})
        evening = newPenalty("ЕГЭ поздно", "time", 50, {"target": "line", "value": "ЕГЭ основной", "days": [0, 1, 2, 3, 4], "times": ["19:40 - 21:10"]})
        teacher = newPenalty("Иванова в пн", "time", 10, {"target": "teacher", "value": "Иванова Анна", "days": [0], "times": ["16:20 - 17:50", "19:40 - 21:10"]})
        limit = newPenalty("Не больше 1 в день", "daily_limit", 20, {"target": "teacher", "value": "", "limit": 1})
        line = newPenalty("Линейка 1 в день", "daily_limit", 30, {"target": "line", "value": "", "limit": 1})
        adjacent = newPenalty("Соседние дни", "adjacent", 40, {"target": "subject", "value": "Математика"})
        same_day = newPenalty("Мат и физ", "same_day", 60, {"first": "Физика", "second": "Математика"})

        self.add(weekend, evening, teacher, limit, line, adjacent, same_day)
        counts = countPenalties(self.settings, "1", self.variant)

        self.assertEqual(counts[weekend["id"]], 1)    # физика ОГЭ в субботу утром
        self.assertEqual(counts[evening["id"]], 1)    # физика ЕГЭ в понедельник 19:40
        self.assertEqual(counts[teacher["id"]], 2)    # Иванова: понедельник 16:20 и 19:40
        self.assertEqual(counts[limit["id"]], 1)      # у Ивановой 2 урока в понедельник
        self.assertEqual(counts[line["id"]], 1)       # у ЕГЭ основного 2 урока в понедельник
        self.assertEqual(counts[adjacent["id"]], 1)   # Математика в понедельник и вторник
        self.assertEqual(counts[same_day["id"]], 1)   # Математика и Физика ЕГЭ в понедельник; ОГЭ — другая линейка

    def test_compiling(self):
        """Правила превращаются во входные данные решателя: учитываются только существующие уроки
        сетки, линейка раскрывается в её курсы, а правило с весом 0 выключено.
        """
        weekend, limit, same_day = self.add(
            newPenalty("Выходные", "time", 100, {"target": "subject", "value": "Физика", "days": [5], "times": ["10:00 - 11:30", "19:40 - 21:10"]}),
            newPenalty("Линейка", "daily_limit", 30, {"target": "line", "value": "ЕГЭ основной", "limit": 2}),
            newPenalty("Мат и физ", "same_day", 60, {"first": "Физика", "second": "Математика"}),
        )

        compiled = compilePenalties(self.settings, "1")

        # В субботу в сетке нет урока 19:40, поэтому считается только 10:00
        self.assertEqual(compiled["class_slots"], {self.physics: [[5, 0, 100]], self.oge: [[5, 0, 100]]})
        self.assertEqual(compiled["group_daily"], [{"classes": [self.math, self.physics], "limit": 2, "weight": 30}])
        self.assertEqual(compiled["same_day"], [{"a": self.math, "b": self.physics, "weight": 60}])

        # Правило с весом 0 выключено
        weekend["weight"] = 0
        self.assertEqual(compilePenalties(self.settings, "1")["class_slots"], {})

    def test_course_without_subjects_does_not_break_same_day(self):
        """Курс без предметов в линейке (испорченные данные) не роняет правило «два предмета в один день»:
        он просто не входит ни в одну пару — и в цены решателя, и в подсчёт, и в подписи уроков.
        """
        same_day = newPenalty("Мат и физ", "same_day", 60, {"first": "Физика", "second": "Математика"})
        self.add(same_day)
        self.settings["classes"]["custom_groups"].append({"name": "Поток 1 — ЕГЭ основной — ?", "program": "ЕГЭ основной", "line": "ЕГЭ",
                                                         "subjects": [], "stream_id": 1, "start_date": "2026-09-07"})

        self.assertEqual(compilePenalties(self.settings, "1")["same_day"], [{"a": self.math, "b": self.physics, "weight": 60}])
        self.assertEqual(countPenalties(self.settings, "1", self.variant), {same_day["id"]: 1})
        self.assertEqual(set(penaltyLessons(self.settings, "1", self.variant)), {(self.math, 0, 0), (self.physics, 0, 2)})

    def test_same_day_pairs_and_teachers(self):
        """Пары курсов для правила «Два предмета — в разные дни» — только внутри линейки потока, каждая один раз;
        цель «преподаватель» без имени — каждый преподаватель.
        """
        groups = self.settings["classes"]["custom_groups"]

        self.assertEqual(list(sameDayCoursePairs(groups, "Физика", "Математика")), [(self.math, self.physics)])
        self.assertEqual(list(sameDayCoursePairs(groups, "Химия", "Математика")), [])
        self.assertEqual(penaltyTeachers({"value": "Иванова Анна"}, ["Петров Пётр"]), ["Иванова Анна"])
        self.assertEqual(penaltyTeachers({"value": ""}, {"Петров Пётр": {}, "Иванова Анна": {}}), ["Петров Пётр", "Иванова Анна"])

    def test_drop_targeted(self):
        """Правила, нацеленные на удалённые курсы или преподавателей, убираются; остальные остаются."""
        course = newPenalty("Курс", "time", 1, {"target": "course", "value": self.math, "days": [0], "times": ["16:20 - 17:50"]})
        teacher = newPenalty("Иванова", "daily_limit", 1, {"target": "teacher", "value": "Иванова Анна", "limit": 1})
        line = newPenalty("Линейка", "adjacent", 1, {"target": "line", "value": self.math})
        self.add(course, teacher, line)

        self.assertFalse(dropTargeted(self.settings, "course", ["Нет такого"]))
        self.assertTrue(dropTargeted(self.settings, "course", [self.math]))
        self.assertEqual(self.settings["custom_penalties"], [teacher, line])
        self.assertTrue(dropTargeted(self.settings, "teacher", {"Иванова Анна"}))
        self.assertEqual(self.settings["custom_penalties"], [line])

    def test_custom_row_keys(self):
        """Ключ строки своего правила собирает customKey и разбирает только customId; у строки
        встроенного правила id нет.
        """
        self.assertEqual(customKey("ab12cd34"), "custom:ab12cd34")
        self.assertEqual(customId(customKey("ab12cd34")), "ab12cd34")
        self.assertIsNone(customId("teacherClash"))

    def test_description_substitutes_values_once(self):
        """Значение с фигурными скобками (имя курса «{days}») подставляется как есть, не как новое место."""
        rule = newPenalty("Курс", "adjacent", 1, {"target": "course", "value": "{days} {target}"})
        translate = {"penalty.describe.adjacent": "Не в соседние дни: {target}", "penalty.target.course": "курс"}.get

        self.assertEqual(describePenalty(rule, translate), "Не в соседние дни: курс «{days} {target}»")

    @unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
    def test_solver_follows_a_custom_penalty(self):
        """Реальный запуск solve.exe: со своим правилом «не ставить уроки в понедельник» с большим весом
        уроков в понедельник становится меньше, чем без него. Пропускается, если решатель не собран.
        """
        def mondayLessons(custom):
            """Строит этап 1 с правилами `custom` и возвращает число уроков, попавших на понедельник."""
            settings = buildSettings()
            settings["custom_penalties"] = custom

            with tempfile.TemporaryDirectory() as folder:
                source, output, weights = (os.path.join(folder, name) for name in ("in.json", "out.json", "weights.json"))

                with open("src/files/weights.json", "r", encoding="utf-8") as file, open(weights, "w", encoding="utf-8") as target:
                    target.write(file.read())

                with open(source, "w", encoding="utf-8") as file:
                    json.dump(buildStageSettings(settings, {}, "1"), file, ensure_ascii=False)

                subprocess.run([SOLVER, "--weights", weights, "--input", source, "--output", output, "--iterations", "2000000"],
                               check=True, capture_output=True, timeout=300)

                with open(output, "r", encoding="utf-8") as file:
                    answer = json.load(file)

            return sum(1 for week in answer.values() for cell in week[0] if cell.get("subject", "#") != "#")

        times = sorted(buildSettings()["day_grid"][0])
        monday = newPenalty("Понедельник", "time", 5000, {"target": "all", "value": "", "days": [0], "times": times})

        self.assertLess(mondayLessons([monday]), mondayLessons([]))


class PenaltyEdgeTests(unittest.TestCase):
    """Свои правила: неизвестные цели и шаблоны, «каждый преподаватель», сложение штрафов, подписи уроков."""
    def setUp(self):
        """Математика и физика ЕГЭ основной потока 1, два преподавателя, сетка будни + выходные."""
        self.settings = emptySettings(teachers={"Иванова": {}, "Петров": {}}, day_grid=GRID)
        self.math = addCourse(self.settings, 1, "ЕГЭ основной", "Математика", 2, "2026-09-07")
        self.physics = addCourse(self.settings, 1, "ЕГЭ основной", "Физика", 2, "2026-09-07")
        self.group = self.settings["classes"]["custom_groups"][0]

    def test_course_matches(self):
        """Цель «курс» подходит только курсу с этим именем; цель «преподаватель» и неизвестная — никакому."""
        self.assertTrue(courseMatches(self.group, "course", self.math))
        self.assertFalse(courseMatches(self.group, "course", self.physics))
        self.assertFalse(courseMatches(self.group, "teacher", "Иванова"))
        self.assertFalse(courseMatches(self.group, "что-то", ""))

    def test_slots_outside_grid_are_dropped(self):
        """Дни вне недели и времена, которых нет в сетке, в слоты правила не попадают."""
        params = {"days": [0, 7, -1], "times": ["16:20 - 17:50", "23:00 - 23:30"]}

        self.assertEqual(penaltySlots(self.settings, params), [(0, 0)])
        self.assertEqual(penaltySlots(self.settings, {}), [])

    def test_compile_teacher_rules_and_sums(self):
        """«Каждый преподаватель» раскрывается во всех преподавателей проекта; правила одного курса
        «не в соседние дни» складываются; выключенные (вес 0) и неизвестные правила пропускаются.
        """
        self.settings["custom_penalties"] = [
            newPenalty("Выходные", "time", 5, {"target": "teacher", "value": "", "days": [5], "times": ["10:00 - 11:30"]}),
            newPenalty("Петров утром", "time", 3, {"target": "teacher", "value": "Петров", "days": [0], "times": ["16:20 - 17:50"]}),
            newPenalty("Два в день", "daily_limit", 4, {"target": "teacher", "value": "", "limit": 2}),
            newPenalty("Иванова без лимита", "daily_limit", 1, {"target": "teacher", "value": "Иванова", "limit": ""}),
            newPenalty("Мат не подряд", "adjacent", 10, {"target": "subject", "value": "Математика"}),
            newPenalty("Курс не подряд", "adjacent", 7, {"target": "course", "value": self.math}),
            newPenalty("Выключено", "time", 0, {"target": "all", "value": "", "days": [0], "times": ["16:20 - 17:50"]}),
            newPenalty("Неизвестное", "mystery", 9, {}),
        ]

        compiled = compilePenalties(self.settings, "1")

        self.assertEqual(compiled["teacher_slots"], {"Иванова": [[5, 0, 5]], "Петров": [[5, 0, 5], [0, 0, 3]]})
        self.assertEqual(compiled["teacher_daily"], {"Иванова": [[2, 4], [0, 1]], "Петров": [[2, 4]]})
        self.assertEqual(compiled["adjacent"], {self.math: 17})
        self.assertEqual(compiled["class_slots"], {})
        self.assertEqual(compiled["group_daily"], [])
        self.assertEqual(compiled["same_day"], [])

    def test_unknown_rule_counts_nothing(self):
        """Правило неизвестного вида не ломает подсчёт: у него 0 нарушений, текста описания нет."""
        rule = newPenalty("Неизвестное", "mystery", 9, {})
        self.settings["custom_penalties"] = [rule]
        variant = {self.math: place(emptyWeek(), 0, 0, "Математика", "Иванова")}

        self.assertEqual(countPenalties(self.settings, "1", variant), {rule["id"]: 0})
        self.assertEqual(describePenalty(rule, translate), "")
        self.assertEqual(penaltyLessons(self.settings, "1", variant), {})

    def test_lesson_marks(self):
        """Подписи уроков: правило по времени для курса отмечает только этот курс (не физику в том же
        слоте); два правила с одним именем дают одну подпись; «соседние дни» — только уроки в соседние дни.
        """
        self.settings["custom_penalties"] = [
            newPenalty("Вечер", "time", 1, {"target": "course", "value": self.math, "days": [0], "times": ["16:20 - 17:50", "18:00 - 19:30"]}),
            newPenalty("Вечер", "time", 1, {"target": "subject", "value": "Математика", "days": [0], "times": ["16:20 - 17:50"]}),
            newPenalty("Соседние", "adjacent", 1, {"target": "all", "value": ""}),
        ]
        variant = {
            # Математика: пн и ср (не соседние); физика: пн и вт (соседние)
            self.math: place(place(emptyWeek(), 0, 0, "Математика", "Иванова"), 2, 0, "Математика", "Иванова"),
            self.physics: place(place(emptyWeek(), 0, 1, "Физика", "Петров"), 1, 0, "Физика", "Петров"),
        }

        self.assertEqual(penaltyLessons(self.settings, "1", variant), {
            (self.math, 0, 0): ["Вечер"],
            (self.physics, 0, 1): ["Соседние"],
            (self.physics, 1, 0): ["Соседние"],
        })


class DailyLimitTests(unittest.TestCase):
    """Своё правило «не больше N уроков в день»."""
    def test_day_below_limit_does_not_cancel_excess(self):
        """В линейке день с 3 уроками при лимите 2 — одно нарушение; день с одним уроком его не гасит.
        То же для преподавателя.
        """
        settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}}
        chemistry = addCourse(settings, 1, "ОГЭ", "Химия", 2, "2026-09-07")
        physics = addCourse(settings, 1, "ОГЭ", "Физика", 2, "2026-09-07")
        line = newPenalty("Линейка", "daily_limit", 10, {"target": "line", "value": "ОГЭ", "limit": 2})
        teacher = newPenalty("Преподаватель", "daily_limit", 10, {"target": "teacher", "value": "Иванова", "limit": 2})
        settings["custom_penalties"] = [line, teacher]

        variant = {chemistry: emptyWeek(5), physics: emptyWeek(5)}
        variant[chemistry][0][0] = lesson("Химия", "Иванова")
        variant[chemistry][0][1] = lesson("Химия", "Иванова")
        variant[physics][0][2] = lesson("Физика", "Иванова")
        variant[physics][1][0] = lesson("Физика", "Иванова")

        self.assertEqual(countPenalties(settings, "1", variant), {line["id"]: 1, teacher["id"]: 1})


class PenaltyTextTests(unittest.TestCase):
    """Описание своих правил и уроки, которые их нарушают."""
    def setUp(self):
        self.settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {"Иванова": {}}}
        setDayGrid(self.settings, [["16:20 - 17:50", "18:00 - 19:30"]] * 5 + [[], []])
        self.math = addCourse(self.settings, 1, "ЕГЭ основной", "Математика", 2, START)
        self.physics = addCourse(self.settings, 1, "ЕГЭ основной", "Физика", 1, START)
        self.oge = addCourse(self.settings, 1, "ОГЭ", "Физика", 1, START)

    def test_descriptions(self):
        """Каждый вид правила описывается понятной фразой с целью, днями и временем."""
        time = newPenalty("a", "time", 1, {"target": "line", "value": "ОГЭ", "days": [4, 0], "times": ["18:00 - 19:30"]})
        limit = newPenalty("b", "daily_limit", 1, {"target": "teacher", "value": "Иванова", "limit": 2})
        every = newPenalty("c", "daily_limit", 1, {"target": "line", "value": "", "limit": 3})
        adjacent = newPenalty("d", "adjacent", 1, {"target": "all"})
        same_day = newPenalty("e", "same_day", 1, {"first": "Химия", "second": "Биология"})

        self.assertEqual(describePenalty(time, translate), "Не ставить уроки: линейка «ОГЭ», дни: Пн, Пт, часы: 18:00 - 19:30")
        self.assertEqual(describePenalty(limit, translate), "Уроков в день — не больше 2: преподаватель «Иванова»")
        self.assertEqual(describePenalty(every, translate), "Уроков в день — не больше 3: каждая линейка потока")
        self.assertEqual(describePenalty(adjacent, translate), "Не в соседние дни: все курсы")
        self.assertIn("«Химия» и «Биология»", describePenalty(same_day, translate))
        self.assertEqual(describePenalty({"template": "unknown"}, translate), "")

    def test_lessons_breaking_rules(self):
        """На карточках отмечаются уроки, нарушающие правила «время», «соседние дни», «в один день»;
        «не больше N в день» — нет (виноват весь день, а не урок).
        """
        evening = newPenalty("Вечер", "time", 1, {"target": "teacher", "value": "Иванова", "days": [0], "times": ["18:00 - 19:30"]})
        adjacent = newPenalty("Подряд", "adjacent", 1, {"target": "subject", "value": "Математика"})
        same_day = newPenalty("Мат и физ", "same_day", 1, {"first": "Математика", "second": "Физика"})
        limit = newPenalty("Лимит", "daily_limit", 1, {"target": "teacher", "value": "", "limit": 0})
        self.settings["custom_penalties"] = [evening, adjacent, same_day, limit]

        variant = {
            self.math: place(place(emptyWeek(), 0, 1, "Математика", "Иванова"), 1, 0, "Математика", "Иванова"),
            self.physics: place(emptyWeek(), 1, 1, "Физика", "Петров"),
            self.oge: place(emptyWeek(), 0, 0, "Физика", "Петров"),
        }
        marks = penaltyLessons(self.settings, "1", variant)

        self.assertEqual(marks[(self.math, 0, 1)], ["Вечер", "Подряд"])
        self.assertEqual(marks[(self.math, 1, 0)], ["Подряд", "Мат и физ"])
        self.assertEqual(marks[(self.physics, 1, 1)], ["Мат и физ"])
        self.assertNotIn((self.oge, 0, 0), marks)  # ОГЭ — другая линейка, лимит не подписывается

        issues = lessonIssues(self.settings, "1", variant)
        self.assertIn("Против правила «Вечер»", issues[self.math]["0-1"])
