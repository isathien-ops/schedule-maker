"""Движок solve.exe на целых программах школы — по его выходу.

* ``StandardProgramTests`` — стандартная программа онлайн-школы одним большим входом (без деления
  на этапы): 5 преподавателей на предмет, закрепление «ведёт», отметки «не может» и закреплённый
  урок; проверяются все жёсткие правила результата.
* ``RealData2627Tests`` — реальные данные школы 2026/27 (`tests/fixtures/school_26_27.json`;
  настройки собирает `tools/school_26_27.py`, тесты берут их через `tests/fixture_26_27.py`):
  структура собранного проекта и составление всех этапов по очереди.

Тесты пропускаются, если solve.exe не собран. Жёсткие правила на маленьких входах —
`test_engine_rules.py`, мягкие — `test_engine_soft_rules.py`.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import collections
import json
import os
import subprocess
import tempfile
import unittest

from src.modules.functions.grid import lessonExists
from src.modules.functions.school_defaults import (
    DEFAULT_JOINT_SUBJECT_PAIRS, DEFAULT_NON_OVERLAPPING_PROGRAMS, createOnlineCourseProgram
)
from src.modules.functions.solver_input import buildStageSettings
from src.modules.functions.stages import getStages, mergeStageAnswer, builtStages
from tests.builders import SOLVER
from tests.fixture_26_27 import buildSettings, loadFixture

# Зерно случайных чисел для прогонов solve.exe в этом модуле. Без --seed движок берёт зерно 0, то есть
# случайное (DATA_CONTRACT §6.3): каждый прогон шёл бы по-своему, и упавший тест («все уроки поставлены»
# зависит от хода отжига) нельзя было бы повторить. Значение — как по умолчанию в tests/engine.py (runSolver).
SEED = "1"


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class StandardProgramTests(unittest.TestCase):
    """Стандартная программа онлайн-школы: все жёсткие правила на результате настоящего запуска решателя."""
    def solverInput(self):
        """Собирает входные данные решателя и возвращает пару (settings, имя курса с закреплённым уроком).

        Попутно запоминает в `self.fixed` курс, который «ведёт» Математика #1.
        """
        subjects, groups, lessons = createOnlineCourseProgram()
        teachers = {}

        for subject in subjects:
            courses = [group["name"] for group in groups if lessons[group["name"]].get(subject, 0) > 0]

            for number in range(5):
                teachers[f"{subject} #{number + 1}"] = {
                    "subjects": [{"subject": subject, "classes": courses}],
                    "free": []
                }

        pinned = next(group["name"] for group in groups if lessons[group["name"]].get("Математика"))

        # "ведёт": Математика #1 закреплена за одним курсом ЕГЭ продвинутый
        fixed = next(group["name"] for group in groups if group["program"] == "ЕГЭ продвинутый" and lessons[group["name"]].get("Математика"))
        teachers["Математика #1"]["subjects"][0]["assigned"] = [fixed]
        # Закреплённый урок (constants) ведёт тот, кто закреплён за курсом: Математика #2
        teachers["Математика #2"]["subjects"][0]["assigned"] = [pinned]

        # Физика #1: понедельник — только "может", первый урок вторника — "не может"
        teachers["Физика #1"]["possible"] = [[0, lesson] for lesson in range(3)]
        teachers["Физика #1"]["free"] = [[1, 0]]
        self.fixed = fixed

        return {
            "working_days_per_week": 5,
            "max_lesson_count_per_day": 3,
            "max_courses_per_teacher": 5,
            "joint_subject_pairs": DEFAULT_JOINT_SUBJECT_PAIRS,
            "non_overlapping_programs": DEFAULT_NON_OVERLAPPING_PROGRAMS,
            "soft_subject_pairs": [["Английский язык", "Информатика"]],
            "subjects": [[subject, 1] for subject in subjects],
            "classes": {"custom_groups": groups, "lessons": lessons},
            "teachers": teachers,
            "constants": {pinned: {"0-0": "Математика"}}
        }, pinned

    def test_places_every_lesson_and_keeps_constraints(self):
        """Решатель ставит все уроки и соблюдает правила: запрещённые пары и непересекающиеся
        программы не встречаются, нежелательная пара — почти никогда, учитель ведёт один урок за раз,
        «ведёт» и «не может» соблюдаются, «может» используется редко, закреплённый урок на своём месте.
        """
        settings, pinned = self.solverInput()

        with tempfile.TemporaryDirectory() as folder:
            paths = {name: os.path.join(folder, f"{name}.json") for name in ("settings", "weights", "answer")}

            with open(paths["settings"], "w", encoding="utf-8") as file:
                json.dump(settings, file, ensure_ascii=False)

            with open(paths["weights"], "w", encoding="utf-8") as file:
                file.write("{}")

            # Итераций достаточно, чтобы до исправления отклонённые ходы между курсами успели потерять уроки
            subprocess.run([
                SOLVER,
                "--weights", paths["weights"],
                "--input", paths["settings"],
                "--output", paths["answer"],
                "--iterations", "300000",
                "--seed", SEED
            ], check=True, capture_output=True, timeout=120)

            with open(paths["answer"], "r", encoding="utf-8") as file:
                answer = json.load(file)

        groups = {group["name"]: group for group in settings["classes"]["custom_groups"]}
        placed = collections.Counter()
        subjects_by_line = collections.defaultdict(set)
        programs_by_slot = collections.defaultdict(set)
        program_subjects = collections.defaultdict(set)
        teacher_load = collections.Counter()

        for course, week in answer.items():
            for day, lessons in enumerate(week):
                self.assertLessEqual(len(lessons), 3)

                for lesson, cell in enumerate(lessons):
                    if cell.get("subject", "#") == "#":
                        continue

                    group = groups[course]
                    placed[(course, cell["subject"])] += 1
                    programs_by_slot[(day, lesson)].add(group["program"])
                    program_subjects[(day, lesson)].add((group["program"], cell["subject"]))

                    if group["stream_id"] is not None:
                        subjects_by_line[(group["line"], group["stream_id"], day, lesson)].add(cell["subject"])

                    for teacher in cell["teachers"]:
                        teacher_load[(teacher, day, lesson)] += 1

        expected = {
            (course, subject): hours
            for course, load in settings["classes"]["lessons"].items()
            for subject, hours in load.items()
            if hours > 0
        }
        self.assertEqual(dict(placed), expected)

        # Пары запрещены только внутри одной линейки (ОГЭ / ЕГЭ / ...) и потока
        for first, second in settings["joint_subject_pairs"]:
            self.assertFalse([key for key, names in subjects_by_line.items() if first in names and second in names])

        # Непересекающиеся программы не встречаются по одному и тому же предмету
        for first, second in settings["non_overlapping_programs"]:
            self.assertFalse([
                slot for slot, items in program_subjects.items()
                for program, subject in items
                if program == first and (second, subject) in items
            ])

        # "Нежелательно": мягкая пара практически не встречается внутри одной линейки и потока
        soft = [key for key, names in subjects_by_line.items() if {"Английский язык", "Информатика"} <= names]
        self.assertLessEqual(len(soft), 1)

        # Учитель ведёт один урок за раз
        self.assertEqual(max(teacher_load.values()), 1)

        fixed_teachers = {
            teacher
            for day in answer[self.fixed]
            for cell in day
            if cell.get("subject") == "Математика"
            for teacher in cell["teachers"]
        }
        self.assertEqual(fixed_teachers, {"Математика #1"})

        physics = settings["teachers"]["Физика #1"]
        self.assertFalse([slot for slot in physics["free"] if teacher_load[("Физика #1", *slot)]])
        # "может" — мягкое условие: используется, только когда больше ничего не подходит, здесь это редкость
        self.assertLessEqual(len([slot for slot in physics["possible"] if teacher_load[("Физика #1", *slot)]]), 1)

        pinned_cell = answer[pinned][0][0]
        self.assertEqual((pinned_cell["subject"], pinned_cell["teachers"]), ("Математика", ["Математика #2"]))


class RealData2627Tests(unittest.TestCase):
    """Потоки 1 и 2 учебного года 2026/27 из реальной таблицы."""
    def test_fixture_structure(self):
        """Проект из реальной таблицы собран правильно: все курсы на месте, этапы идут в порядке
        «поток 1, семинары, поток 2», сетка с субботой на 6 уроков, учителя из таблицы закреплены.
        """
        data = loadFixture()
        settings = buildSettings()

        self.assertEqual(len(settings["classes"]["custom_groups"]), len(data["courses"]))
        self.assertEqual([stage["key"] for stage in getStages(settings)], ["1", "extra", "2"])
        self.assertEqual(settings["day_grid"][5][0], "10:00 - 11:30")
        self.assertEqual(settings["max_lesson_count_per_day"], 6)

        fixed = {
            course for teacher in settings["teachers"].values()
            for entry in teacher["subjects"] for course in entry["assigned"]
        }
        self.assertEqual(len(fixed), sum(1 for item in data["courses"] if item["teachers"]))

    @unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
    def test_building_both_streams_and_extra_courses(self):
        """Реальный запуск solve.exe по всем этапам: поставлены все уроки, у курса не больше урока
        в день, учитель не ведёт два урока сразу, закреплённые учителя на своих местах, запрещённые
        пары не встречаются, семинар не совпадает с ЕГЭ продвинутым по тому же предмету.
        """
        settings = buildSettings()
        answer = {}

        with tempfile.TemporaryDirectory() as folder:
            weights = os.path.join(folder, "weights.json")

            with open("src/files/weights.json", "r", encoding="utf-8") as source, open(weights, "w", encoding="utf-8") as file:
                file.write(source.read())

            for stage in getStages(settings):
                source = os.path.join(folder, f"{stage['key']}.json")
                output = os.path.join(folder, f"{stage['key']}.answer.json")

                with open(source, "w", encoding="utf-8") as file:
                    json.dump(buildStageSettings(settings, answer, stage["key"]), file, ensure_ascii=False)

                subprocess.run([SOLVER, "--weights", weights, "--input", source, "--output", output, "--iterations", "1000000",
                                "--seed", SEED], check=True, capture_output=True, timeout=300)

                with open(output, "r", encoding="utf-8") as file:
                    answer = mergeStageAnswer(answer, json.load(file), stage["courses"])

        self.assertEqual(builtStages(settings, answer), ["1", "extra", "2"])

        groups = {group["name"]: group for group in settings["classes"]["custom_groups"]}
        fixed = {
            course: name for name, teacher in settings["teachers"].items()
            for entry in teacher["subjects"] for course in entry["assigned"]
        }
        pairs = {tuple(sorted(pair)) for pair in settings["joint_subject_pairs"]}

        placed = collections.Counter()
        per_day = collections.Counter()
        teacher_slots = collections.Counter()
        by_slot = collections.defaultdict(list)

        for course, week in answer.items():
            for day, cells in enumerate(week):
                for lesson, cell in enumerate(cells):
                    if cell.get("subject", "#") == "#":
                        continue

                    self.assertTrue(lessonExists(settings, day, lesson), (course, day, lesson))

                    placed[course] += 1
                    per_day[(course, day)] += 1
                    by_slot[(day, lesson)].append((groups[course], cell["subject"]))

                    for teacher in cell["teachers"]:
                        teacher_slots[(teacher, day, lesson)] += 1

                    if course in fixed:
                        self.assertEqual(cell["teachers"], [fixed[course]], course)

        # Все уроки обоих потоков и семинаров есть в расписании
        expected = {name: sum(load.values()) for name, load in settings["classes"]["lessons"].items()}
        self.assertEqual(dict(placed), expected)

        # Никогда два урока одного курса в один день
        self.assertEqual(max(per_day.values()), 1, [key for key, value in per_day.items() if value > 1])

        # По всем этапам вместе: у учителя один урок в одно время
        self.assertEqual(max(teacher_slots.values()), 1)

        for slot, items in by_slot.items():
            for first, subject_a in items:
                for second, subject_b in items:
                    if first is second:
                        continue

                    same_line = first.get("stream_id") is not None and first.get("stream_id") == second.get("stream_id") and first.get("line") == second.get("line")

                    # Пары «нельзя» не встречаются внутри одной линейки и потока
                    if same_line:
                        self.assertNotIn(tuple(sorted([subject_a, subject_b])), pairs, (slot, first["name"], second["name"]))

                    # Семинар не совпадает по времени с ЕГЭ продвинутым по своему предмету
                    if first["program"] == "Семинары" and second["program"] == "ЕГЭ продвинутый":
                        self.assertNotEqual(subject_a, subject_b, (slot, first["name"], second["name"]))
