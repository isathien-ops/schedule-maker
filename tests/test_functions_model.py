"""Тесты модели данных проекта (`src/modules/functions/model.py`): разделы и этапы курса,
курсы по имени, даты курсов, уроки в расписании и отметки времени преподавателя.

Это нижний модуль предметного слоя: на его функциях стоят все остальные, поэтому здесь
проверяются пограничные случаи — курс без предметов, без потока, без дат, пустые ячейки.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import unittest

from src.modules.functions.model import (
    EXTRA_BLOCK, allLessons, cannotSlots, courseGroups, courseNames, courseSlots, courseSubject, coursesOverlap, emptyCell, groupsByName,
    hasLessons, inSection, isBlock, isBlockStage, isLesson, lessonEntries, possibleSlots, sectionOf, stageGroups, stageKey,
    teacherAvailability, teacherLessons
)

STREAM = {"name": "Поток 2 — ОГЭ — Химия", "subjects": ["Химия"], "stream_id": 2, "start_date": "2026-11-23", "end_date": "2027-05-31"}
SEMINAR = {"name": "Семинар ОГЭ: Химия", "subjects": ["Химия"], "stream_id": None, "block": EXTRA_BLOCK, "start_date": "2026-10-05"}
SUMMER = {"name": "Летняя школа — ОГЭ — Химия", "subjects": [], "stream_id": None, "block": "summer",
          "start_date": "2027-06-01", "end_date": "2027-08-31"}


def week(*lessons):
    """Неделя из двух дней по два урока; ``lessons`` — (день, урок, предмет, [преподаватели])."""
    result = [[emptyCell() for _ in range(2)] for _ in range(2)]

    for day, lesson, subject, teachers in lessons:
        result[day][lesson] = {"subject": subject, "teachers": list(teachers)}

    return result


class SectionAndStageTests(unittest.TestCase):
    """Раздел курса (поток или блок) и ключ этапа — одно понятие: ключ этапа — раздел строкой."""
    def test_sections_and_stage_keys(self):
        """Поток — число и этап «2»; доп. курсы без блока — "extra"; блок — своё слово."""
        self.assertEqual((sectionOf(STREAM), stageKey(STREAM)), (2, "2"))
        self.assertEqual((sectionOf(SEMINAR), stageKey(SEMINAR)), (EXTRA_BLOCK, EXTRA_BLOCK))
        self.assertEqual(sectionOf({"name": "Без блока"}), EXTRA_BLOCK)
        self.assertEqual(stageKey(SUMMER), "summer")

        self.assertTrue(inSection(SEMINAR, None))
        self.assertFalse(inSection(STREAM, "2"))
        self.assertEqual((isBlock(None), isBlock("may"), isBlock(3)), (True, True, False))
        self.assertEqual((isBlockStage("summer"), isBlockStage("3"), isBlockStage(3)), (True, False, False))

    def test_courses_by_name_and_stage(self):
        """Курсы проекта — список, по имени, по этапу; у проекта без курсов — пусто, ничего не создаётся."""
        settings = {"classes": {"custom_groups": [STREAM, SEMINAR, SUMMER]}}

        self.assertEqual(courseNames(settings), [STREAM["name"], SEMINAR["name"], SUMMER["name"]])
        self.assertIs(groupsByName(settings)[SEMINAR["name"]], SEMINAR)
        self.assertEqual(stageGroups(settings, "2"), [STREAM])
        self.assertEqual(stageGroups(settings, "9"), [])

        empty = {}
        self.assertEqual((courseGroups(empty), courseNames(empty), groupsByName(empty)), ([], [], {}))
        self.assertEqual(empty, {})

    def test_subject_of_course(self):
        """Предмет курса — первый (и единственный) из его списка; у курса без предметов — пустая строка."""
        self.assertEqual(courseSubject(STREAM), "Химия")
        self.assertEqual(courseSubject(SUMMER), "")
        self.assertEqual(courseSubject({"name": "Без поля subjects"}), "")


class DatesTests(unittest.TestCase):
    """Пересечение курсов по датам: курсы в разные месяцы не делят ни учеников, ни преподавателей."""
    def test_courses_overlap(self):
        """Поток 2 (ноябрь–май) и семинары (с октября, до конца календаря) идут вместе; летняя школа —
        после потока 2; курс без дат идёт всегда.
        """
        settings = {"calendar_end_date": "2027-06-30"}

        self.assertTrue(coursesOverlap(settings, STREAM, SEMINAR))
        self.assertFalse(coursesOverlap(settings, STREAM, SUMMER))
        self.assertTrue(coursesOverlap(settings, SEMINAR, SUMMER))
        self.assertTrue(coursesOverlap({}, {"name": "Без дат"}, SUMMER))


class LessonsTests(unittest.TestCase):
    """Уроки в расписании: пустые ячейки пропускаются везде."""
    def test_lessons_of_course_and_teacher(self):
        """Уроки курса по порядку, слоты предмета, уроки преподавателя (с пропуском предметов)."""
        answer = {
            "Химия": week((0, 1, "Химия", ["Иванова"]), (1, 0, "Химия", ["Иванова", "Петров"])),
            "Физика": week((1, 1, "Физика", ["Иванова"])),
            "Пусто": week(),
        }

        self.assertEqual([(day, lesson) for day, lesson, _ in lessonEntries(answer, "Химия")], [(0, 1), (1, 0)])
        self.assertEqual(courseSlots(answer, "Химия", "Химия"), [(0, 1), (1, 0)])
        self.assertEqual(courseSlots(answer, "Химия", "Физика"), [])
        self.assertEqual((hasLessons(answer, "Химия"), hasLessons(answer, "Пусто"), hasLessons(answer, "Нет")), (True, False, False))

        self.assertEqual([(course, day, lesson) for course, day, lesson, _ in teacherLessons(answer, "Иванова")],
                         [("Химия", 0, 1), ("Химия", 1, 0), ("Физика", 1, 1)])
        self.assertEqual([course for course, *_ in teacherLessons(answer, "Иванова", except_subjects=["Химия"])], ["Физика"])
        self.assertEqual(list(teacherLessons(answer, "Петров", except_subjects=["Химия"])), [])

        self.assertEqual([(course, day, lesson) for course, day, lesson, _ in allLessons(answer)],
                         [("Химия", 0, 1), ("Химия", 1, 0), ("Физика", 1, 1)])

    def test_empty_cell(self):
        """Пустая ячейка — каждый раз новый словарь, и уроком она не считается."""
        first, second = emptyCell(), emptyCell()

        self.assertIsNot(first, second)
        self.assertFalse(isLesson(first))
        self.assertFalse(isLesson({}))
        self.assertTrue(isLesson({"subject": "Химия"}))


class AvailabilityTests(unittest.TestCase):
    """Отметки «может / не может» преподавателя по этапам."""
    def test_marks_are_read_without_creating(self):
        """Чтение отметок ничего не создаёт; teacherAvailability создаёт пустые отметки этапа."""
        settings = {"teachers": {"Иванова": {"availability": {"1": {"free": [[0, 0]], "possible": [[1, 1]]}}}}}

        self.assertEqual((cannotSlots(settings, "Иванова", "1"), possibleSlots(settings, "Иванова", "1")), ([[0, 0]], [[1, 1]]))
        self.assertEqual((cannotSlots(settings, "Иванова", "2"), possibleSlots(settings, "Нет", "1")), ([], []))
        self.assertNotIn("2", settings["teachers"]["Иванова"]["availability"])

        marks = teacherAvailability(settings["teachers"]["Иванова"], "2")
        self.assertEqual(marks, {"free": [], "possible": []})
        self.assertIs(settings["teachers"]["Иванова"]["availability"]["2"], marks)
