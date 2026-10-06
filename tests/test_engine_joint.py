"""«Линейка присоединяется к Потоку N» на настоящем движке solve.exe (AC-22, пункт 7 «Готово»).

Проект — ``builders.jointProject(streams=2)`` на сервере (``RealProjectCase.useProject``): в Потоке 1
приняты «ЕГЭ основной» и «ЕГЭ продвинутый», в Потоке 2 те же линейки и «ОГЭ». «ЕГЭ основной» Потока 2
отмечен «вместе с Потоком 1» (``builders.markJoint``: поле ``together_with``, часы и уроки копий как
у источников). Поток 2 составляется действием «Составить варианты» настоящим решателем, лучший
вариант принимается — и проверяется принятое расписание.

Проект построен так, что выровненная расстановка точно есть:

* общие уроки стоят у «Математика #1» (пн и ср, 1-й урок) и «Русский язык #1» (вт и чт, 2-й урок);
  в эти часы свободны «Математика #3» и «Русский язык #3», поэтому «ЕГЭ продвинутый» Потока 2 может
  встать урок в урок с копией (уровни вместе, ``levelsApart == 0``);
* лимит курсов на преподавателя — 2, а «ОГЭ» Потока 2 может вести только «Математика #1»: он
  получает «ОГЭ», только если общий курс (источник + копия) считается за один курс.

Тесты пропускаются, если solve.exe не собран или нет архива проекта 2026/27 (основа ``RealProjectCase``).
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
import unittest
from unittest import mock

from src.modules.functions.courses import setTeacherCourseState
from src.web import build
from tests.builders import JOINT_ACCEPTED, JOINT_LINE, LEVEL_LINE, OWN_LINE, SOLVER, jointCourse, jointProject, markJoint
from tests.real_project import RealProjectCase, lessons as lessonsOf

# Сборка: шагов на вариант и вариантов (подбирается всего 6 уроков — этого хватает с запасом)
ITERATIONS = 2000000
VARIANTS = 2

# Лимит курсов на преподавателя и единственный, кто может вести «ОГЭ» Потока 2
LIMIT = 2
OGE_TEACHER = "Математика #1"
OGE_2 = jointCourse(2, "Математика", OWN_LINE)


def cells(week):
    """Уроки недели: {(день, урок): (предмет, преподаватели)}."""
    return {(day, lesson): (cell["subject"], tuple(cell.get("teachers", []))) for day, lesson, cell in lessonsOf(week)}


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class JointStreamBuildTests(RealProjectCase):
    """Поток 2 с линейкой «ЕГЭ основной», которая идёт вместе с Потоком 1: составить и принять."""
    NAME = "__test_engine_joint__"

    def setUp(self):
        """Проект jointProject (2 потока) с отметкой «ЕГЭ основной» Потока 2 «вместе с Потоком 1»."""
        super().setUp()
        solver = mock.patch.object(build, "SOLVER", SOLVER)
        solver.start()
        self.addCleanup(solver.stop)

        settings, answer = jointProject(streams=2)
        settings["max_courses_per_teacher"] = LIMIT
        settings["iterations"], settings["variants"] = ITERATIONS, VARIANTS

        for number in (2, 3):
            setTeacherCourseState(settings, f"Математика #{number}", "Математика", OGE_2, "no")

        self.copies = markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.assertEqual(set(self.copies), {jointCourse(2, "Математика"), jointCourse(2, "Русский язык")})
        self.openProject(settings, answer)

    def buildAndAccept(self):
        """«Составить варианты» Потока 2 настоящим решателем и принять лучший вариант.

        Возвращает (лучший вариант так, как его видел «Предпросмотр», принятое расписание).
        """
        self.ok("run", stage="2", keep=False)
        self.waitJob(180)

        job = self.client.get(f"/api/project/{self.NAME}/job").get_json()
        self.assertFalse(job["running"])
        self.assertGreaterEqual(job["saved"], 1, job["log"][-10:])

        data = self.variants("2")
        best = data["variants"][0]
        self.ok("accept", stage="2", number=best["number"], force=True, build=data["build"])

        return best, self.load("answer.json")

    def test_copies_stay_in_source_hours_and_nothing_clashes(self):
        """AC-22: после составления и принятия Потока 2 уроки «ЕГЭ основной» Потока 2 стоят в тех же
        слотах и с теми же преподавателями, что в Потоке 1, а в принятом расписании нет ни одной
        накладки (``state.clashes`` пуст).
        """
        _, answer = self.buildAndAccept()

        for copy, source in self.copies.items():
            self.assertEqual(cells(answer.get(copy, [])), cells(answer[source]), copy)

        for (line, subject), (teacher, slots) in JOINT_ACCEPTED.items():
            if line == JOINT_LINE and jointCourse(2, subject) in self.copies:
                expected = {slot: (subject, (teacher,)) for slot in slots}
                self.assertEqual(cells(answer.get(jointCourse(2, subject), [])), expected, subject)

        self.assertEqual(self.state()["clashes"], [])

    def test_shared_course_counts_once_toward_teacher_limit(self):
        """AC-22: лимит курсов не превышен, общий курс считается один раз. «Математика #1» ведёт
        источник и копию (один курс) и при лимите 2 получает ещё «ОГЭ» Потока 2 — его единственного
        возможного преподавателя; урок «ОГЭ» поставлен.
        """
        _, answer = self.buildAndAccept()
        taught = {course for course, week in answer.items() for _, _, cell in lessonsOf(week) if OGE_TEACHER in cell.get("teachers", [])}

        self.assertEqual(taught, {jointCourse(1, "Математика"), jointCourse(2, "Математика"), OGE_2})
        self.assertLessEqual(len({self.copies.get(course, course) for course in taught}), LIMIT)
        self.assertEqual([cell["subject"] for _, _, cell in lessonsOf(answer[OGE_2])], ["Математика"])

    def test_level_line_stands_in_copy_hours(self):
        """AC-22: расстановка «ЕГЭ продвинутый» Потока 2 в те же часы, что у копии, есть (её
        преподаватели свободны) — предмет стоит ровно в часы копии, у принятого варианта
        ``levelsApart == 0``.
        """
        best, answer = self.buildAndAccept()

        for subject in ("Математика", "Русский язык"):
            level = {slot for slot in cells(answer.get(jointCourse(2, subject, LEVEL_LINE), []))}
            _, slots = JOINT_ACCEPTED[(JOINT_LINE, subject)]
            self.assertEqual(level, set(slots), subject)
            self.assertEqual(level, set(cells(answer.get(jointCourse(2, subject), []))), subject)

        self.assertEqual(best["metrics"]["levelsApart"], 0)
