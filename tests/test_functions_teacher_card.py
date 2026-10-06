"""Карточка преподавателя на вкладке «Преподаватели» (`src/modules/functions/teacher_card.py`).

Сетка времени преподавателя на этапе: отметки «удобно / может / не может», занятость
в других этапах, закреплённые и собственные уроки, накладки. ``JointTeacherCardTests`` — общие
уроки двух потоков («Линейка присоединяется к Потоку N»): не накладка, а клетка «вместе».
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import unittest
from unittest import mock

from src.modules.functions.stages import stageCourses
from src.modules.functions.teacher_card import teacherCard
from tests.builders import (
    JOINT_LINE, OWN_LINE, chemistryWeek, courseWeek, emptyWeek, jointCourse, jointProject, makeSettings, markJoint, place
)
from tests.real_project import FrozenDate


class TeacherCardTests(unittest.TestCase):
    """teacherCard на стандартной программе: «Химия #1» на этапе потока 2, «сегодня» 04.10.2026
    (поток 1 идёт с 07.09, поток 2 начнётся 23.11).
    """
    NAME = "Химия #1"

    def setUp(self):
        frozen = mock.patch("datetime.date", FrozenDate)
        frozen.start()
        self.addCleanup(frozen.stop)

        self.settings = makeSettings()
        self.chem1 = [course for course in stageCourses(self.settings, "1") if course.endswith("Химия")]
        self.chem2 = [course for course in stageCourses(self.settings, "2") if course.endswith("Химия")]
        # Два курса потока 2 в одно время (накладка), курс идущего потока 1, урок коллеги
        # и курс с уроком без преподавателя
        self.answer = {
            self.chem2[0]: chemistryWeek((0, 0)), self.chem2[1]: chemistryWeek((0, 0)), self.chem1[0]: chemistryWeek((1, 0)),
            self.chem2[2]: place(emptyWeek(), 4, 2, "Химия", "Химия #2"),
            self.chem2[3]: emptyWeek(),
        }
        self.answer[self.chem2[3]][3][0] = {"subject": "Химия", "teachers": []}
        self.settings["teachers"][self.NAME]["availability"]["2"] = {"free": [[2, 0]], "possible": [[3, 1]]}

    def card(self):
        return teacherCard(self.settings, self.answer, self.NAME, "2")

    def test_marks_lessons_and_clashes_of_stage(self):
        """Отметки этапа, его уроки (курс ещё не идёт), накладка в его сетке и предел курсов."""
        card = self.card()

        self.assertEqual((card["busy"], card["possible"]), ([[2, 0]], [[3, 1]]))
        self.assertEqual(card["own"], [[0, 0, self.chem2[0], False], [0, 0, self.chem2[1], False]])
        self.assertEqual(card["clashes"], [[0, 0, [self.chem2[0], self.chem2[1]]]])
        self.assertEqual(card["limit"], self.settings["max_courses_per_teacher"])

    def test_lessons_of_other_stage_are_commitments(self):
        """Урок идущего потока 1 в сетке потока 2 — занятая клетка с именем курса, а не свой урок."""
        card = self.card()

        self.assertEqual([item for item in card["commitments"] if item[3] == self.chem1[0]], [[1, 0, "busy", self.chem1[0]]])
        self.assertNotIn(self.chem1[0], [item[2] for item in card["own"]])

    def test_courses_of_all_stages_by_subject(self):
        """Курсы — всех этапов в порядке этапов, с пометками «ведёт», «идёт» и «без преподавателя»."""
        card = self.card()

        self.assertEqual([item["subject"] for item in card["subjects"]], ["Химия"])
        courses = {item["name"]: item for item in card["subjects"][0]["courses"]}
        stages = [item["stage"] for item in card["subjects"][0]["courses"]]
        self.assertEqual(stages[:4], ["1"] * 4)
        self.assertEqual(stages, sorted(stages, key=["1", "extra", "2", "3", "4"].index))

        flags = lambda name: (courses[name]["scheduled"], courses[name]["started"], courses[name]["orphan"])
        self.assertEqual(flags(self.chem1[0]), (True, True, False))
        self.assertEqual(flags(self.chem2[0]), (True, False, False))
        self.assertEqual(flags(self.chem2[2]), (False, False, False))
        self.assertEqual(flags(self.chem2[3]), (False, False, True))
        self.assertEqual(courses[self.chem2[0]]["line"], "ОГЭ")

    def test_card_does_not_change_project(self):
        """Карточка только читает настройки и расписание."""
        settings, answer = copy.deepcopy(self.settings), copy.deepcopy(self.answer)
        self.card()

        self.assertEqual((self.settings, self.answer), (settings, answer))


class JointTeacherCardTests(unittest.TestCase):
    """«ЕГЭ основной» Потока 2 идёт вместе с Потоком 1 (проект ``jointProject``, «сегодня» 04.10.2026):
    у «Математика #1» источник (Поток 1) и копия (Поток 2) — пн и ср первым уроком.
    """
    NAME = "Математика #1"

    def setUp(self):
        frozen = mock.patch("datetime.date", FrozenDate)
        frozen.start()
        self.addCleanup(frozen.stop)

        self.settings, self.answer = jointProject()
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        self.source, self.copy = jointCourse(1, "Математика"), jointCourse(2, "Математика")

    def card(self, stage="2"):
        return teacherCard(self.settings, self.answer, self.NAME, stage)

    def test_shared_lessons_are_not_clashes(self):
        """AC-27: в карточке общий урок источника и копии — не накладка ни в сетке Потока 2, ни в сетке
        Потока 1; урок третьего курса в те же часы — накладка, в ней есть копия и этот курс.
        """
        self.assertEqual(self.card()["clashes"], [])
        self.assertEqual(self.card("1")["clashes"], [])

        third = jointCourse(2, "Математика", OWN_LINE)
        self.answer[third] = courseWeek("Математика", self.NAME, (0, 0))
        clashes = self.card()["clashes"]

        self.assertEqual([(day, lesson) for day, lesson, _ in clashes], [(0, 0)])
        self.assertIn(self.copy, clashes[0][2])
        self.assertIn(third, clashes[0][2])

    def test_shared_lessons_are_joint_cells(self):
        """AC-27 и AC-31 (данные): в сетке Потока 2 часы общего урока — клетки вида «joint», а не «занят»
        уроком Потока 1; у копии в списке курсов есть поле ``joint``, у обычного курса его нет.
        """
        card = self.card()
        kinds = {(day, lesson): kind for day, lesson, kind, _ in card["commitments"]}

        self.assertEqual((kinds.get((0, 0)), kinds.get((2, 0))), ("joint", "joint"))

        courses = {item["name"]: item for item in card["subjects"][0]["courses"]}
        self.assertTrue(courses[self.copy].get("joint"))
        self.assertFalse(courses[jointCourse(2, "Математика", OWN_LINE)].get("joint"))
