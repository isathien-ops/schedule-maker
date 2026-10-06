"""Предупреждение «Нужен ещё преподаватель» над «Расписанием» (`src/modules/functions/staffing.py`).

Когда программа говорит, что преподавателей предмета не хватает, а когда молчит; чьи отметки
«не может» при этом учитываются и в каком порядке идут предупреждения. ``JointStaffingTests`` —
курсы-копии («Линейка присоединяется к Потоку N») преподавателя не требуют.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import unittest

from src.modules.functions.courses import addCourse
from src.modules.functions.grid import setDayGrid
from src.modules.functions.model import teacherAvailability
from src.modules.functions.staffing import staffing
from tests.builders import JOINT_LINE, emptyWeek, jointProject, markJoint, place, teacherWithCourses

START = "2026-09-07"


def physicsSettings():
    """Сетка: 3 урока в понедельник и вторник (6 часов в неделю); два потока физики по 2 урока."""
    settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}}
    setDayGrid(settings, [["16:20-17:50", "18:00-19:30", "19:40-21:10"]] * 2 + [[]] * 5)
    first = addCourse(settings, 1, "ЕГЭ основной", "Физика", 2, "2026-09-07")
    second = addCourse(settings, 2, "ЕГЭ основной", "Физика", 2, "2026-11-23")
    settings["teachers"]["Передерин Дмитрий"] = {"subjects": [{"subject": "Физика", "classes": [first, second], "assigned": []}], "availability": {}}

    return settings, first, second


def week(*slots):
    """Неделя курса с уроками физики Передерина в слотах (день, урок)."""
    result = [[{"subject": "#", "teachers": []} for _ in range(3)] for _ in range(7)]

    for day, lesson in slots:
        result[day][lesson] = {"subject": "Физика", "teachers": ["Передерин Дмитрий"]}

    return result


class StaffingTests(unittest.TestCase):
    """Когда программа говорит «нужен ещё преподаватель», чьи отметки учитывает и в каком порядке."""
    def test_enough_time_no_warning(self):
        """Поток 1 стоит (2 часа из 6), потоку 2 нужно 2 — свободно 4, и ещё на один поток хватает: молчим."""
        settings, first, _ = physicsSettings()

        self.assertEqual(staffing(settings, {first: week((0, 0), (1, 0))}), [])

    def test_next_stream_will_not_fit(self):
        """Всё поставлено, но свободен только 1 час, а потоку нужно 2: «следующий поток не поместится»."""
        settings, first, second = physicsSettings()
        settings["teachers"]["Передерин Дмитрий"]["availability"] = {"2": {"free": [[0, 2]], "possible": []}}

        result = staffing(settings, {first: week((0, 0), (1, 0)), second: week((0, 1), (1, 1))})

        self.assertEqual([(item["subject"], item["level"], item["free"], item["next"]) for item in result], [("Физика", "tight", 1, 2)])

    def test_lessons_do_not_fit(self):
        """Потоку 2 нужно 2 урока, а без «не может» и уроков потока 1 у преподавателя свободен 1: «не помещается»."""
        settings, first, _ = physicsSettings()
        settings["teachers"]["Передерин Дмитрий"]["availability"] = {"2": {"free": [[0, 1], [0, 2], [1, 1]], "possible": []}}

        result = staffing(settings, {first: week((0, 0), (1, 0))})

        self.assertEqual([(item["level"], item["needed"], item["free"]) for item in result], [("short", 2, 1)])

    def test_subject_without_teachers(self):
        """У предмета нет ни одного преподавателя — сразу «не помещается»."""
        settings, _, _ = physicsSettings()
        settings["teachers"] = {}

        result = staffing(settings, {})

        self.assertEqual([(item["level"], item["teachers"]) for item in result], [("short", [])])

    def test_marks_of_open_stage_count(self):
        """Учитываются отметки потока, где ещё есть непоставленные уроки, а отметки других потоков — нет."""
        settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}}
        setDayGrid(settings, [["16:20 - 17:50", "18:00 - 19:30"]] + [[]] * 6)
        first = addCourse(settings, 1, "ЕГЭ основной", "Физика", 1, START)
        second = addCourse(settings, 2, "ЕГЭ основной", "Физика", 1, "2026-11-23")
        settings["teachers"]["Передерин"] = teacherWithCourses(("Физика", [first, second], []), availability={
            "1": {"free": [[0, 0], [0, 1]], "possible": []},  # «не может» в потоке 1 — поток 1 уже поставлен
            "2": {"free": [], "possible": []},
        })
        answer = {first: place(emptyWeek(), 0, 0, "Физика", "Передерин")}

        # Потоку 2 нужен 1 урок, свободен 1 час (второй урок понедельника): хватает впритык -> «tight»
        result = staffing(settings, answer)
        self.assertEqual([(item["level"], item["needed"], item["free"]) for item in result], [("tight", 1, 1)])

        settings["teachers"]["Передерин"]["availability"]["2"]["free"] = [[0, 1]]
        self.assertEqual(staffing(settings, answer)[0]["level"], "short")

    def test_short_goes_before_tight(self):
        """«Не хватает» (физика) идёт раньше «впритык» (биология), хотя по алфавиту биология первая."""
        settings = {
            "day_grid": [["16:20 - 17:50", "18:00 - 19:30", "19:40 - 21:10"]] + [[]] * 6,
            "classes": {
                "custom_groups": [
                    {"name": "Поток 1 — ОГЭ — Биология", "subjects": ["Биология"], "stream_id": 1, "start_date": "2026-09-07"},
                    {"name": "Поток 1 — ОГЭ — Физика", "subjects": ["Физика"], "stream_id": 1, "start_date": "2026-09-07"}
                ],
                "lessons": {"Поток 1 — ОГЭ — Биология": {"Биология": 2}, "Поток 1 — ОГЭ — Физика": {"Физика": 2}}
            },
            # У биологии 3 свободных урока на 2 нужных: поставить можно, но запаса на поток нет
            "teachers": {"Иванова": {"subjects": [{"subject": "Биология", "classes": []}], "availability": {}}}
        }

        result = staffing(settings, {})

        self.assertEqual([(item["subject"], item["level"]) for item in result], [("Физика", "short"), ("Биология", "tight")])
        self.assertEqual((result[1]["needed"], result[1]["free"], result[1]["next"]), (2, 3, 2))


class JointStaffingTests(unittest.TestCase):
    """«ЕГЭ основной» Потоков 2 и 3 идёт вместе с Потоком 1 (проект ``jointProject``), Поток 1 ещё
    не принят: копии Математики ждут его и стоять сами не будут.
    """
    def test_waiting_copies_are_not_lacking(self):
        """AC-33: копии не входят ни в «нужно поставить» (``unplacedLessons``), ни в «уроков на поток»
        (``streamLoad``). Единственный преподаватель Математики свободен 11 часов из 15; без копий нужно
        10 уроков (Поток 1 — 4, Потоки 2 и 3 — по 3), на поток — 4: «впритык», а не «не хватает».
        """
        settings, answer = jointProject(accepted=False)
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        markJoint(settings, 3, JOINT_LINE, 1, answer)

        for name in ("Математика #2", "Математика #3"):
            del settings["teachers"][name]

        teacherAvailability(settings["teachers"]["Математика #1"], "1")["free"].extend([[4, 0], [4, 1], [4, 2], [3, 2]])

        result = {item["subject"]: item for item in staffing(settings, answer)}
        math = result["Математика"]

        self.assertEqual((math["level"], math["needed"], math["free"], math["next"]), ("tight", 10, 11, 4))
