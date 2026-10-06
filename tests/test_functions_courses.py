"""Потоки, линейки, курсы и преподаватели курсов (`src/modules/functions/courses.py`).

Курс называется «Поток N — <линейка> — <предмет>»; доп. курсы — «<линейка>: <предмет>», где
линейка уже содержит слово «Семинар» (например, «Семинар ОГЭ: Математика»); курсы других
блоков — «<блок> — <линейка> — <предмет>» (см. ``courseName``).

* ``CourseNameTests`` — название и подпись курса из одних и тех же частей (``nameParts``);
* ``CourseHoursTests``, ``CourseStructureTests`` — часы курса, добавление и удаление потоков,
  линеек и курсов с очисткой всех ссылок, закрепление преподавателя («ведёт») и его замена
  в готовом расписании, закреплённые уроки, первый поток проекта;
* ``BlockCoursesTests`` — курсы майских марафонов и летней школы: названия, линейки и даты блока;
* ``AssignTeacherTests`` — правило «курс ведёт только один преподаватель» (``assignTeacher``);
* ``ForbiddenTeacherTests``, ``TeacherCourseStateTests``, ``TeacherCourseListsTests`` — состояния
  «преподаватель — курс» (может вести / ведёт / запрещено / не ведёт) и проверка конфликтов;
* ``TeacherSubjectsTests`` — выбор предметов преподавателя;
* ``LockedCourseTests`` — курс, который уже идёт, сохраняет преподавателя и время;
* ``SlotConflictTests``, ``SlotConflictEdgeTests``, ``PlannedMovesTests`` — перенос уроков в готовом
  расписании: почему нельзя и как уроки уступают место новым закреплениям;
* ``JointConflictTests`` — «Линейка присоединяется к Потоку N»: копия не мешает своему источнику
  ни как «занят», ни в лимите курсов преподавателя.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import datetime
import unittest

from src.modules.functions.courses import (
    addCourse, addLine, addStream, assignTeacher, copyLineToStreams, courseHours, courseLabel, courseLoad, courseLocked, courseName,
    courseTeachers, lineCourses, moveLessons, nameParts, nextTeacherCourseState, pinnedSlots, plannedMoves, removeCourses,
    removeLine, removeStream, replaceTeacherInAnswer, sectionEnd, sectionLines, sectionStart, setCourseTeacher, setPinnedSlots,
    setSectionEnd, setSectionStart, setTeacherCourseState, setTeacherSubjects, slotConflicts, streamIds, subjectTeachers,
    teacherConflicts, teacherCourseState
)
from src.modules.functions.grid import DEFAULT_DAY, setDayGrid
from src.modules.functions.model import courseNames, courseSlots
from src.modules.functions.school_defaults import DEFAULT_JOINT_SUBJECT_PAIRS, createOnlineCourseProgram
from src.modules.functions.solver_input import buildStageSettings
from tests.builders import (
    JOINT_LINE, LEVEL_LINE, OWN_LINE, chemist, courseWeek, emptySettings, emptyWeek, jointCourse, jointProject, lesson, makeSettings,
    markJoint, oneLessonWeek, place, setDates, teacher, weekdaySettings
)



def programSettings():
    """Минимальные настройки со стандартной программой онлайн-школы (4 потока + семинары).

    Учителей и закреплённых уроков нет. Возвращает новый словарь `settings`.
    """
    _, groups, lessons = createOnlineCourseProgram()

    return {
        "classes": {"custom_groups": groups, "lessons": lessons},
        "teachers": {},
        "constants": {}
    }


class CourseHoursTests(unittest.TestCase):
    """Уроки курса в неделю: по предмету или по всем предметам вместе."""
    def test_hours(self):
        """Пустое значение — ноль; курса или предмета нет — значение по умолчанию (обычно 0)."""
        settings = {"classes": {"lessons": {"А": {"Химия": 2, "Биология": "3", "Физика": None}}}}

        self.assertEqual(courseHours(settings, "А"), 5)
        self.assertEqual(courseHours(settings, "А", "Биология"), 3)
        self.assertEqual(courseHours(settings, "А", "Физика", default=1), 0)
        self.assertEqual((courseHours(settings, "Б"), courseHours(settings, "А", "Химия база")), (0, 0))
        self.assertEqual(courseHours(settings, "Б", "Химия", default=1), 1)
        self.assertEqual(courseHours({}, "А"), 0)

    def test_load(self):
        """Нагрузка курса для чтения — целыми числами (пустое значение — 0); курса нет — пустой
        словарь, и настройки при этом не меняются.
        """
        settings = {"classes": {"lessons": {"А": {"Химия": 2, "Биология": "3", "Физика": None}}}}

        self.assertEqual(courseLoad(settings, "А"), {"Химия": 2, "Биология": 3, "Физика": 0})
        self.assertEqual(courseLoad(settings, "Б"), {})
        self.assertEqual(courseLoad({}, "А"), {})
        self.assertEqual(settings, {"classes": {"lessons": {"А": {"Химия": 2, "Биология": "3", "Физика": None}}}})


class CourseNameTests(unittest.TestCase):
    """Название и подпись курса строятся из одних частей (nameParts) и никогда — разбором названия."""
    def test_parts_name_and_label(self):
        """Поток: «Поток 1 — ОГЭ — Литература» и «Поток 1, ОГЭ, Литература»; блок: «Летняя школа — …»;
        доп. курсы (и раздел None): «Семинар ОГЭ: Математика» — и название, и подпись одной частью.
        """
        self.assertEqual(nameParts(1, "ОГЭ", "Литература"), ["Поток 1", "ОГЭ", "Литература"])
        self.assertEqual(courseName("summer", "ЕГЭ основной", "Математика"), "Летняя школа — ЕГЭ основной — Математика")
        self.assertEqual(courseName(None, "Семинар ОГЭ", "Математика"), "Семинар ОГЭ: Математика")
        self.assertEqual(nameParts("extra", "Семинар ОГЭ", "Математика"), ["Семинар ОГЭ: Математика"])

        settings = emptySettings()
        stream = addCourse(settings, 2, "ЕГЭ основной", "Математика")
        summer = addCourse(settings, "summer", "ОГЭ", "Физика")
        seminar = addCourse(settings, None, "Семинар ОГЭ", "Химия")
        groups = {group["name"]: group for group in settings["classes"]["custom_groups"]}

        self.assertEqual(courseLabel(groups[stream]), "Поток 2, ЕГЭ основной, Математика")
        self.assertEqual(courseLabel(groups[stream], " (с 23.11)"), "Поток 2 (с 23.11), ЕГЭ основной, Математика")
        self.assertEqual(courseLabel(groups[summer]), "Летняя школа, ОГЭ, Физика")
        self.assertEqual(courseLabel(groups[seminar], " (с 01.10)"), "Семинар ОГЭ: Химия (с 01.10)")


class CourseStructureTests(unittest.TestCase):
    """Операции над потоками, линейками и курсами на вкладке «Курсы»; список курсов и первый поток
    на пустых данных."""
    def test_streams_lines_and_subjects(self):
        """Стандартная программа даёт 4 потока с пятью линейками, две линейки семинаров
        и по одному курсу на предмет в линейке (например, у 8 класса — русский и математика).
        """
        settings = programSettings()

        self.assertEqual(streamIds(settings), [1, 2, 3, 4])
        self.assertEqual(sectionLines(settings, 1), ["ОГЭ", "ЕГЭ основной", "ЕГЭ продвинутый", "10 класс", "8 класс"])
        self.assertEqual(sectionLines(settings, None), ["Семинар ЕГЭ продвинутый", "Семинар ОГЭ"])
        self.assertEqual([group["name"] for group in lineCourses(settings, 1, "8 класс")], [
            "Поток 1 — 8 класс — Русский язык",
            "Поток 1 — 8 класс — Математика"
        ])

    def test_add_stream_copies_the_last_one(self):
        """Новый поток копирует все курсы и часы последнего потока и получает свою дату начала,
        которую потом можно изменить, — пользователю не нужно заводить курсы заново.
        """
        settings = programSettings()
        settings["classes"]["lessons"]["Поток 4 — ЕГЭ основной — Физика"]["Физика"] = 3

        stream = addStream(settings, "2027-04-05")

        self.assertEqual(stream, 5)
        self.assertEqual(sectionStart(settings, 5), "2027-04-05")
        self.assertEqual(len([group for group in settings["classes"]["custom_groups"] if group["stream_id"] == 5]), 45)
        self.assertEqual(settings["classes"]["lessons"]["Поток 5 — ЕГЭ основной — Физика"], {"Физика": 3})

        new = next(group for group in settings["classes"]["custom_groups"] if group["name"] == "Поток 5 — ЕГЭ продвинутый — Химия")
        self.assertEqual((new["program"], new["line"], new["subjects"]), ("ЕГЭ продвинутый", "ЕГЭ", ["Химия"]))

        setSectionStart(settings, 5, "2027-04-12")
        self.assertEqual(sectionStart(settings, 5), "2027-04-12")

    def test_removing_courses_cleans_references(self):
        """Удаление линейки, потока или курса убирает его отовсюду: часы, закреплённые уроки,
        курсы учителей, «ведёт» и доступность по этапу; добавление линейки семинаров и курса тоже работает.
        """
        settings = programSettings()
        course = "Поток 2 — ОГЭ — Физика"
        settings["teachers"]["T"] = {
            "subjects": [{"subject": "Физика", "classes": [course, "Поток 1 — ОГЭ — Физика"], "assigned": [course]}],
            "availability": {"2": {"free": [], "possible": []}, "1": {"free": [], "possible": []}}
        }
        settings["constants"][course] = {"0-0": "Физика"}

        removeLine(settings, 2, "ОГЭ")

        self.assertNotIn("ОГЭ", sectionLines(settings, 2))
        self.assertNotIn(course, settings["classes"]["lessons"])
        self.assertNotIn(course, settings["constants"])
        self.assertEqual(settings["teachers"]["T"]["subjects"][0]["classes"], ["Поток 1 — ОГЭ — Физика"])
        self.assertEqual(settings["teachers"]["T"]["subjects"][0]["assigned"], [])

        removeStream(settings, 2)
        self.assertEqual(streamIds(settings), [1, 3, 4])
        self.assertNotIn("2", settings["teachers"]["T"]["availability"])

        addLine(settings, None, "Семинар 10 класс", ["Физика", "Химия"])
        self.assertEqual(sectionLines(settings, None)[-1], "Семинар 10 класс")
        self.assertIn("Семинар 10 класс: Химия", settings["classes"]["lessons"])

        name = addCourse(settings, 1, "ОГЭ", "География")
        self.assertEqual(name, "Поток 1 — ОГЭ — География")
        removeCourses(settings, [name])
        self.assertNotIn(name, settings["classes"]["lessons"])

    def test_copy_line_and_stream_dates(self):
        """«Скопировать в другие потоки» (линейку) переносит часы (и восстанавливает удалённый курс),
        конец потока можно изменить, а курс, добавленный в поток позже, получает даты потока.
        """
        settings = programSettings()
        settings["calendar_end_date"] = "2027-06-30"
        lessons = settings["classes"]["lessons"]

        removeCourses(settings, ["Поток 3 — ЕГЭ основной — Физика"])
        lessons["Поток 1 — ЕГЭ основной — Физика"]["Физика"] = 3

        copyLineToStreams(settings, 1, "ЕГЭ основной")

        self.assertEqual(lessons["Поток 2 — ЕГЭ основной — Физика"], {"Физика": 3})
        self.assertEqual(lessons["Поток 3 — ЕГЭ основной — Физика"], {"Физика": 3})
        self.assertEqual(lessons["Поток 1 — ЕГЭ основной — Физика"], {"Физика": 3})

        self.assertEqual(sectionEnd(settings, 2), "2027-06-30")
        setSectionEnd(settings, 2, "2027-05-31")
        self.assertEqual(sectionEnd(settings, 2), "2027-05-31")

        # Курс, добавленный в поток позже, получает даты потока
        addCourse(settings, 2, "ОГЭ", "Литература")
        group = next(group for group in settings["classes"]["custom_groups"] if group["name"] == "Поток 2 — ОГЭ — Литература")
        self.assertEqual((group["start_date"], group["end_date"]), ("2026-11-23", "2027-05-31"))

    def test_course_teachers(self):
        """Для курса правильно делятся учителя: кто «ведёт», кто стоит в расписании, кто может взять
        (кандидаты по предмету), кому запрещено; учитель другого предмета не попадает никуда.
        """
        settings = programSettings()
        course = "Поток 1 — ОГЭ — Физика"
        settings["teachers"] = {
            "Б": {"subjects": [{"subject": "Физика", "classes": [course], "assigned": [course]}]},
            "А": {"subjects": [{"subject": "Физика", "classes": [course], "assigned": []}]},
            "В": {"subjects": [{"subject": "Химия", "classes": [course], "assigned": []}]}
        }
        answer = {course: [[{"subject": "Физика", "teachers": ["А"]}], [{"subject": "#", "teachers": []}]]}

        self.assertEqual(courseTeachers(settings, answer, course, "Физика"), {"assigned": ["Б"], "scheduled": ["А"], "candidates": ["А"], "forbidden": []})
        self.assertEqual(courseTeachers(settings, {}, course, "Физика")["scheduled"], [])

    def test_fix_teacher_and_replace_in_built_schedule(self):
        """Закрепление учителя за курсом («ведёт») снимает закрепление с прежнего; замена учителя
        в готовом расписании проходит, если он свободен, а иначе сообщаются конфликты: занят в другом
        курсе, недоступен в это время, превышен лимит курсов на учителя.
        """
        settings = programSettings()
        settings["max_courses_per_teacher"] = 2
        course, other = "Поток 1 — ОГЭ — Физика", "Поток 1 — ЕГЭ основной — Физика"
        settings["teachers"] = {
            "А": {"subjects": [{"subject": "Физика", "classes": [course], "assigned": [course]}], "availability": {}},
            "Б": {"subjects": [{"subject": "Физика", "classes": [], "assigned": []}], "availability": {"1": {"free": [[2, 0]], "possible": []}}},
            "В": {"subjects": [{"subject": "Химия", "classes": [], "assigned": []}]}
        }

        self.assertEqual(subjectTeachers(settings, "Физика"), ["А", "Б"])

        setCourseTeacher(settings, course, "Физика", "Б")
        self.assertEqual(settings["teachers"]["Б"]["subjects"][0], {"subject": "Физика", "classes": [course], "assigned": [course]})
        self.assertEqual(settings["teachers"]["А"]["subjects"][0]["assigned"], [])
        self.assertEqual(settings["teachers"]["А"]["subjects"][0]["classes"], [course])

        empty = {"subject": "#", "teachers": []}
        lesson = lambda teacher: {"subject": "Физика", "teachers": [teacher]}
        answer = {
            course: [[lesson("А"), empty, empty], [empty] * 3, [empty] * 3],
            other: [[empty, empty, empty], [empty] * 3, [empty] * 3]
        }

        # Учитель везде свободен: его можно поставить вместо прежнего прямо в расписании
        self.assertEqual(teacherConflicts(settings, answer, course, "Физика", "Б"), [])
        replaceTeacherInAnswer(answer, course, "Физика", "Б")
        self.assertEqual(answer[course][0][0]["teachers"], ["Б"])

        # Занят в другом курсе в это время, недоступен, превышен лимит курсов
        answer[course][2][0] = lesson("Б")
        answer[other][0][0] = lesson("А")
        answer["Поток 2 — ОГЭ — Физика"] = [[empty, lesson("А")]]
        answer["Поток 3 — ОГЭ — Физика"] = [[empty, empty, lesson("А")]]

        conflicts = teacherConflicts(settings, answer, course, "Физика", "А")
        self.assertIn((0, 0, "busy", other), conflicts)
        self.assertIn((None, None, "limit", 3), conflicts)
        self.assertIn((2, 0, "unavailable", ""), teacherConflicts(settings, answer, course, "Физика", "Б"))

        setCourseTeacher(settings, course, "Физика", None)
        self.assertEqual(settings["teachers"]["Б"]["subjects"][0]["assigned"], [])

    def test_pin_and_move_lessons_in_built_schedule(self):
        """Закрепление урока на время и перенос уроков в готовом расписании: переносится только то,
        что нужно, учитель переезжает вместе с уроком, а конфликты (запрещённая пара предметов, учитель
        занят или недоступен, такого урока нет в сетке) обнаруживаются до переноса.
        """
        settings = programSettings()
        settings["joint_subject_pairs"] = [["Математика", "Физика"]]
        settings["day_grid"] = [["16:20 - 17:50", "18:00 - 19:30", "19:40 - 21:10"]] * 5 + [[], []]
        course, peer = "Поток 1 — ЕГЭ основной — Физика", "Поток 1 — ЕГЭ продвинутый — Математика"
        settings["teachers"] = {
            "Ф": {"subjects": [{"subject": "Физика", "classes": [course]}], "availability": {"1": {"free": [[4, 2]], "possible": []}}},
            "М": {"subjects": [{"subject": "Математика", "classes": [peer]}], "availability": {}}
        }

        week = lambda: emptyWeek(5)
        answer = {course: week(), peer: week(), "Поток 1 — ОГЭ — Химия": week()}
        answer[course][0][0] = {"subject": "Физика", "teachers": ["Ф"]}
        answer[course][2][1] = {"subject": "Физика", "teachers": ["Ф"]}
        answer[peer][1][0] = {"subject": "Математика", "teachers": ["М"]}
        answer["Поток 1 — ОГЭ — Химия"][3][0] = {"subject": "Химия", "teachers": ["Ф"]}

        self.assertEqual(courseSlots(answer, course, "Физика"), [(0, 0), (2, 1)])

        setPinnedSlots(settings, course, "Физика", [(4, 0)])
        self.assertEqual(pinnedSlots(settings, course, "Физика"), [(4, 0)])
        self.assertEqual(settings["constants"][course], {"4-0": "Физика"})

        # Один урок переезжает на закреплённое время, второй остаётся на месте
        moves, final = plannedMoves([(0, 0), (2, 1)], [(4, 0)], 2)
        self.assertEqual((moves, final), ([((2, 1), (4, 0))], [(0, 0), (4, 0)]))
        self.assertEqual(slotConflicts(settings, answer, course, "Физика", moves), [])

        moveLessons(answer, course, moves)
        self.assertEqual(courseSlots(answer, course, "Физика"), [(0, 0), (4, 0)])
        self.assertEqual(answer[course][4][0]["teachers"], ["Ф"])

        # Запрещённая пара в той же линейке и потоке, учитель занят, учитель недоступен, такого урока нет
        conflicts = slotConflicts(settings, answer, course, "Физика", [((0, 0), (1, 0)), ((4, 0), (3, 0)), ((0, 0), (4, 2))])
        self.assertIn((1, 0, "pair", peer), conflicts)
        self.assertIn((3, 0, "busy", "Поток 1 — ОГЭ — Химия"), conflicts)
        self.assertIn((4, 2, "unavailable", "Ф"), conflicts)

        settings["day_grid"] = [["16:20 - 17:50"]] * 5 + [[], []]
        self.assertEqual(slotConflicts(settings, answer, course, "Физика", [((0, 0), (1, 2))]), [(1, 2, "missing", "")])

        setPinnedSlots(settings, course, "Физика", [])
        self.assertNotIn(course, settings["constants"])

    def test_class_names_of_empty_settings(self):
        """Нет курсов — пустой список, а не ошибка; иначе — имена по порядку."""
        self.assertEqual(courseNames({}), [])
        self.assertEqual(courseNames({"classes": {}}), [])
        self.assertEqual(courseNames({"classes": {"custom_groups": []}}), [])
        self.assertEqual(courseNames({"classes": {"custom_groups": [{"name": "Б"}, {"name": "А"}]}}), ["Б", "А"])

    def test_first_stream_starts_empty(self):
        """Без потоков (даже если есть доп. курсы) новый поток получает номер 1 и курсов не копирует."""
        settings = emptySettings()
        addCourse(settings, None, "Семинар ОГЭ", "Химия", 1, "2026-09-01")

        self.assertEqual(addStream(settings, "2026-09-07"), 1)
        self.assertEqual([group["name"] for group in settings["classes"]["custom_groups"]], ["Семинар ОГЭ: Химия"])


class BlockCoursesTests(unittest.TestCase):
    """Майские марафоны и летняя школа: курсы без потока, как доп. курсы (семинары), но со своими
    названиями, линейками и датами блока.
    """
    def test_block_courses_get_names_lines_and_season_dates(self):
        """Курсы майского марафона и летней школы получают свои имена и сроки по умолчанию (в последнем
        календарном году учебного года); у блока свои линейки, семинары не затрагиваются.
        """
        settings = makeSettings()
        settings["calendar_end_date"] = "2027-06-30"

        may = addCourse(settings, "may", "ЕГЭ основной", "Математика", 3)
        summer = addCourse(settings, "summer", "ОГЭ", "Математика", 2)

        self.assertEqual(may, "Майские марафоны — ЕГЭ основной — Математика")
        self.assertEqual(summer, "Летняя школа — ОГЭ — Математика")
        self.assertEqual((sectionStart(settings, "may"), sectionEnd(settings, "may")), ("2027-05-01", "2027-05-31"))
        self.assertEqual((sectionStart(settings, "summer"), sectionEnd(settings, "summer")), ("2027-06-01", "2027-08-31"))

        self.assertEqual(sectionLines(settings, "may"), ["ЕГЭ основной"])
        self.assertEqual([group["name"] for group in lineCourses(settings, "summer", "ОГЭ")], [summer])

        # Правило семинаров касается только семинаров: у курса блока поток None, но своя программа и block
        group = next(group for group in settings["classes"]["custom_groups"] if group["name"] == may)
        self.assertEqual((group["stream_id"], group["block"], group["program"]), (None, "may", "Майские марафоны"))

    def test_block_dates_are_kept_without_courses(self):
        """Даты блока, заданные до появления в нём курсов, не теряются: новый курс
        блока получает именно эти даты начала и конца.
        """
        settings = makeSettings()

        setSectionStart(settings, "summer", "2027-07-01")
        setSectionEnd(settings, "summer", "2027-07-31")
        name = addCourse(settings, "summer", "ОГЭ", "Физика", 1)

        group = next(group for group in settings["classes"]["custom_groups"] if group["name"] == name)
        self.assertEqual((group["start_date"], group["end_date"]), ("2027-07-01", "2027-07-31"))


class AssignTeacherTests(unittest.TestCase):
    """Правило «курс ведёт только один преподаватель» — одна функция для вкладок и входа решателя."""
    def setUp(self):
        """Иванова и Петров ведут химию, Сидоров — физику; курс химии «ведёт» Петров."""
        self.teachers = {"Иванова": teacher("Химия"), "Петров": teacher("Химия"), "Сидоров": teacher("Физика")}
        self.teachers["Петров"]["subjects"][0].update(classes=["К"], assigned=["К"])

    def test_one_teacher_per_course(self):
        """Закреплённый получает курс и в «может вести», и в «ведёт»; прежний остаётся «может вести»;
        преподаватель другого предмета не затрагивается.
        """
        assignTeacher(self.teachers, "К", "Химия", "Иванова")

        self.assertEqual(self.teachers["Иванова"]["subjects"][0], {"subject": "Химия", "classes": ["К"], "assigned": ["К"]})
        self.assertEqual(self.teachers["Петров"]["subjects"][0], {"subject": "Химия", "classes": ["К"], "assigned": []})
        self.assertEqual(self.teachers["Сидоров"], teacher("Физика"))

    def test_none_leaves_the_choice_to_the_solver(self):
        """teacher=None снимает закрепление со всех; «может вести» остаётся. Преподаватель без списка
        «ведёт» его не получает.
        """
        del self.teachers["Иванова"]["subjects"][0]["assigned"]

        assignTeacher(self.teachers, "К", "Химия", None)

        self.assertEqual(self.teachers["Петров"]["subjects"][0], {"subject": "Химия", "classes": ["К"], "assigned": []})
        self.assertNotIn("assigned", self.teachers["Иванова"]["subjects"][0])

    def test_forbidden_is_checked_only_by_set_course_teacher(self):
        """setCourseTeacher — это проверка запрета плюс assignTeacher: запрещённого закрепить нельзя,
        а сам assignTeacher запрет не смотрит (его вызывают, когда выбор уже сделан).
        """
        self.teachers["Иванова"]["forbidden"] = ["К"]
        settings = {"teachers": self.teachers}

        with self.assertRaises(ValueError):
            setCourseTeacher(settings, "К", "Химия", "Иванова")

        self.assertEqual(self.teachers["Петров"]["subjects"][0]["assigned"], ["К"])

        assignTeacher(self.teachers, "К", "Химия", "Иванова")
        self.assertEqual(self.teachers["Иванова"]["subjects"][0]["assigned"], ["К"])


class ForbiddenTeacherTests(unittest.TestCase):
    """«Запрещено вести»: учитель никогда не ставится на курс, даже вручную."""
    def setUp(self):
        """Два курса физики потока 1 (ОГЭ и ЕГЭ основной) и два учителя физики."""
        self.settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}, "constants": {}}

        self.oge = addCourse(self.settings, 1, "ОГЭ", "Физика", 2, "2026-09-07")
        self.ege = addCourse(self.settings, 1, "ЕГЭ основной", "Физика", 2, "2026-09-07")

        setTeacherSubjects(self.settings, "Иванова Анна", ["Физика"])
        setTeacherSubjects(self.settings, "Петров Пётр", ["Физика"])

    def cycle(self, course, teacher="Иванова Анна"):
        """Один щелчок по ячейке «учитель — курс»: переводит состояние в следующее по кругу."""
        setTeacherCourseState(self.settings, teacher, "Физика", course, nextTeacherCourseState(self.state(course, teacher)))

    def state(self, course, teacher="Иванова Анна"):
        """Текущее состояние учителя `teacher` по физике на курсе `course` (may / assigned / forbidden / no)."""
        return teacherCourseState(self.settings, teacher, "Физика", course)

    def test_cycle_through_four_states(self):
        """Щелчки по ячейке проходят четыре состояния по кругу и возвращаются к «может вести» —
        так пользователь может выставить любое состояние без отдельного меню.
        """
        # Новый предмет учителя начинается с «может вести» на всех курсах этого предмета
        self.assertEqual(self.state(self.oge), "may")

        self.cycle(self.oge)
        self.assertEqual(self.state(self.oge), "assigned")
        self.cycle(self.oge)
        self.assertEqual(self.state(self.oge), "forbidden")
        self.cycle(self.oge)
        self.assertEqual(self.state(self.oge), "no")
        self.cycle(self.oge)
        self.assertEqual(self.state(self.oge), "may")

    def test_forbidden_teacher_is_kept_away(self):
        """Запрещённый учитель не попадает в кандидаты решателя, не предлагается на вкладке
        «Курсы» и не может быть закреплён вручную (ошибка), а на других курсах остаётся доступен.
        """
        setTeacherCourseState(self.settings, "Иванова Анна", "Физика", self.oge, "forbidden")

        # Не кандидат для решателя, не предлагается на вкладке «Курсы», закрепить нельзя
        stage = buildStageSettings(self.settings, {}, "1")
        physics = stage["teachers"]["Иванова Анна"]["subjects"][0]
        self.assertNotIn(self.oge, physics["classes"])
        self.assertIn(self.ege, physics["classes"])

        self.assertEqual(subjectTeachers(self.settings, "Физика", self.oge), ["Петров Пётр"])
        self.assertEqual(subjectTeachers(self.settings, "Физика"), ["Иванова Анна", "Петров Пётр"])
        self.assertEqual(courseTeachers(self.settings, {}, self.oge, "Физика")["forbidden"], ["Иванова Анна"])

        with self.assertRaises(ValueError):
            setCourseTeacher(self.settings, self.oge, "Физика", "Иванова Анна")

    def test_ban_survives_subject_changes_and_leaves_with_the_course(self):
        """Запрет переживает удаление и возврат предмета у учителя, а при удалении самого курса
        запись о запрете тоже удаляется, чтобы не копился мусор в настройках.
        """
        setTeacherCourseState(self.settings, "Иванова Анна", "Физика", self.oge, "forbidden")

        # Предмет убрали и вернули: возвращаются все курсы, кроме запрещённого
        setTeacherSubjects(self.settings, "Иванова Анна", ["Химия"])
        setTeacherSubjects(self.settings, "Иванова Анна", ["Физика"])
        self.assertEqual(self.state(self.oge), "forbidden")
        self.assertEqual(self.state(self.ege), "may")

        removeCourses(self.settings, [self.oge])
        self.assertEqual(self.settings["teachers"]["Иванова Анна"].get("forbidden"), [])

    def test_new_course_is_may_teach_by_default(self):
        """Новый курс по умолчанию «может вести» для всех учителей предмета; запрет, выставленный
        заранее на имя курса, при его создании сохраняется.
        """
        setTeacherCourseState(self.settings, "Петров Пётр", "Физика", "Поток 2 — ОГЭ — Физика", "forbidden")

        course = addCourse(self.settings, 2, "ОГЭ", "Физика", 2, "2026-11-23")

        self.assertEqual(self.state(course), "may")
        self.assertEqual(self.state(course, "Петров Пётр"), "forbidden")


class TeacherCourseStateTests(unittest.TestCase):
    """Кто ведёт курс: закрепление, запрет и проверка конфликтов в готовом расписании."""
    def setUp(self):
        """Два преподавателя химии и курс химии ОГЭ потока 1, который оба «могут вести»."""
        self.settings = emptySettings(teachers={"Иванова": teacher("Химия"), "Петров": teacher("Химия")})
        self.course = addCourse(self.settings, 1, "ОГЭ", "Химия", 1, "2026-09-01")

    def test_state_for_teacher_without_subject_changes_nothing(self):
        """Преподавателю без такого предмета состояние не задаётся: настройки не меняются."""
        self.settings["teachers"]["Сидоров"] = teacher("Физика")
        before = copy.deepcopy(self.settings)

        setTeacherCourseState(self.settings, "Сидоров", "Химия", self.course, "assigned")

        self.assertEqual(self.settings, before)

    def test_assigning_takes_course_from_other_teacher(self):
        """«Ведёт» у одного снимает закрепление у другого (он остаётся «может вести»);
        затем запрет убирает курс из списков, а «не ведёт» удаляет пустой список запретов.
        """
        setTeacherCourseState(self.settings, "Петров", "Химия", self.course, "assigned")
        setTeacherCourseState(self.settings, "Иванова", "Химия", self.course, "assigned")

        self.assertEqual(teacherCourseState(self.settings, "Иванова", "Химия", self.course), "assigned")
        self.assertEqual(teacherCourseState(self.settings, "Петров", "Химия", self.course), "may")

        setTeacherCourseState(self.settings, "Иванова", "Химия", self.course, "forbidden")
        self.assertEqual(self.settings["teachers"]["Иванова"]["forbidden"], [self.course])
        self.assertNotIn(self.course, self.settings["teachers"]["Иванова"]["subjects"][0]["classes"])

        setTeacherCourseState(self.settings, "Иванова", "Химия", self.course, "no")
        self.assertNotIn("forbidden", self.settings["teachers"]["Иванова"])
        self.assertEqual(teacherCourseState(self.settings, "Иванова", "Химия", self.course), "no")

    def test_repeated_course_teacher_has_no_duplicates(self):
        """Повторное закрепление того же преподавателя не дублирует курс в его списках."""
        setCourseTeacher(self.settings, self.course, "Химия", "Иванова")
        setCourseTeacher(self.settings, self.course, "Химия", "Иванова")

        item = self.settings["teachers"]["Иванова"]["subjects"][0]
        self.assertEqual(item["assigned"], [self.course])
        self.assertEqual(item["classes"].count(self.course), 1)

    def test_conflicts_ignore_courses_in_other_months(self):
        """Курс преподавателя, который идёт в другие месяцы, не мешает взять уроки в то же время
        и не считается в лимите курсов; если даты пересекаются — «занят» и «лимит».
        """
        self.settings["max_courses_per_teacher"] = 1
        setDates(self.settings, self.course, "2026-09-01", "2026-10-31")
        later = addCourse(self.settings, 2, "ОГЭ", "Химия", 1, "2026-11-01")
        setDates(self.settings, later, "2026-11-01", "2026-12-31")

        answer = {
            self.course: [[{"subject": "Химия", "teachers": ["Иванова"]}]],
            later: [[{"subject": "Химия", "teachers": []}]],
        }

        self.assertEqual(teacherConflicts(self.settings, answer, later, "Химия", "Иванова"), [])

        setDates(self.settings, self.course, "2026-09-01", "2026-12-31")
        self.assertEqual(teacherConflicts(self.settings, answer, later, "Химия", "Иванова"), [
            (0, 0, "busy", self.course),
            (None, None, "limit", 1),
        ])

    def test_pinned_slots_of_one_subject(self):
        """Закрепления других предметов курса не попадают в закреплённое время этого предмета."""
        self.settings["constants"] = {self.course: {"1-2": "Химия", "2-0": "Физика", "0-1": "Химия"}}

        self.assertEqual(pinnedSlots(self.settings, self.course, "Химия"), [(0, 1), (1, 2)])
        self.assertEqual(pinnedSlots(self.settings, "Нет такого курса", "Химия"), [])


class TeacherCourseListsTests(unittest.TestCase):
    """«Запрещено» у преподавателя не даёт курсу попасть в «может вести»."""
    def test_new_subject_skips_forbidden_courses(self):
        """Новый предмет получает все курсы химии, кроме запрещённого преподавателю."""
        subjects, groups, lessons = createOnlineCourseProgram()
        settings = {"classes": {"custom_groups": groups, "lessons": lessons}, "teachers": {"Иванова": {"subjects": [], "forbidden": ["Поток 1 — ОГЭ — Химия"]}}}

        data = setTeacherSubjects(settings, "Иванова", ["Химия"])
        classes = data["subjects"][0]["classes"]

        self.assertNotIn("Поток 1 — ОГЭ — Химия", classes)
        self.assertIn("Поток 1 — ЕГЭ основной — Химия", classes)
        self.assertIn("Поток 2 — ОГЭ — Химия", classes)
        self.assertTrue(all("Химия" in course for course in classes))
        self.assertEqual(len(classes), sum(1 for group in groups if group["subjects"] == ["Химия"]) - 1)

    def test_forbidden_survives_recreating_course(self):
        """Курс заново создан с тем же именем: у кого он был запрещён, тот его не получает, а другой
        преподаватель того же предмета получает.
        """
        name = "Поток 1 — ОГЭ — Химия"
        settings = weekdaySettings(teachers={"Иванова": chemist(forbidden=[name]), "Петров": chemist()})

        self.assertEqual(addCourse(settings, 1, "ОГЭ", "Химия", 1, "2026-09-07"), name)
        self.assertNotIn(name, settings["teachers"]["Иванова"]["subjects"][0]["classes"])
        self.assertEqual(settings["teachers"]["Иванова"]["forbidden"], [name])
        self.assertIn(name, settings["teachers"]["Петров"]["subjects"][0]["classes"])


class TeacherSubjectsTests(unittest.TestCase):
    """Предметы преподавателя и курсы, которые он может вести."""
    def test_teacher_subjects_keep_choices_and_default_to_all_courses(self):
        """Новый предмет учителя по умолчанию даёт все курсы этого предмета, а при изменении
        списка предметов уже сделанный выбор курсов по оставшимся предметам сохраняется.
        """
        subjects, groups, lessons = createOnlineCourseProgram()
        settings = {
            "classes": {"custom_groups": groups, "lessons": lessons},
            "teachers": {}
        }

        setTeacherSubjects(settings, "Teacher", ["Математика", "Физика"])
        teacher = settings["teachers"]["Teacher"]

        self.assertEqual([item["subject"] for item in teacher["subjects"]], ["Математика", "Физика"])
        math_courses = [name for name, load in lessons.items() if load.get("Математика", 0) > 0]
        self.assertEqual(teacher["subjects"][0]["classes"], [g["name"] for g in groups if g["name"] in math_courses])

        teacher["subjects"][0]["classes"] = [math_courses[0]]
        setTeacherSubjects(settings, "Teacher", ["Литература", "Математика"])

        self.assertEqual([item["subject"] for item in teacher["subjects"]], ["Литература", "Математика"])
        self.assertEqual(teacher["subjects"][1]["classes"], [math_courses[0]])

        literature = teacher["subjects"][0]["classes"]
        self.assertTrue(literature)
        self.assertTrue(all(lessons[name]["Литература"] > 0 for name in literature))


class LockedCourseTests(unittest.TestCase):
    """Курс, который начался и имеет принятое расписание, сохраняет учителя и время."""
    def test_locked_only_when_started_and_scheduled(self):
        """Курс фиксируется с первого дня занятий, но только если он есть в принятом расписании;
        до начала или без расписания его ещё можно настраивать.
        """
        settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}}
        course = addCourse(settings, 1, "ОГЭ", "Физика", 1, "2026-09-07")
        answer = {course: oneLessonWeek("Физика")}

        before, first_day, later = datetime.date(2026, 9, 6), datetime.date(2026, 9, 7), datetime.date(2026, 10, 3)

        self.assertFalse(courseLocked(settings, answer, course, "Физика", before))
        self.assertTrue(courseLocked(settings, answer, course, "Физика", first_day))
        self.assertTrue(courseLocked(settings, answer, course, "Физика", later))

        # Ещё нет в расписании: курс можно настраивать
        self.assertFalse(courseLocked(settings, {}, course, "Физика", later))


class SlotConflictTests(unittest.TestCase):
    """Почему нельзя перенести уроки в готовом расписании."""
    def test_swap_inside_course_is_not_a_conflict(self):
        """Два урока курса меняются местами — оба места освобождаются, конфликта «course» нет;
        перенос на место, которое не освобождается, — конфликт «course».
        """
        settings = weekdaySettings(teachers={"Иванова": chemist()})
        course = addCourse(settings, 1, "ОГЭ", "Химия", 2, "2026-09-07")
        answer = {course: emptyWeek(5)}
        answer[course][0][0] = lesson("Химия", "Иванова")
        answer[course][1][0] = lesson("Химия", "Иванова")

        conflicts = slotConflicts(settings, answer, course, "Химия", [((0, 0), (1, 0)), ((1, 0), (0, 0))])
        self.assertEqual([item for item in conflicts if item[2] == "course"], [])

        self.assertIn((1, 0, "course", "Химия"), slotConflicts(settings, answer, course, "Химия", [((0, 0), (1, 0))]))

    def test_pair_rule_works_only_inside_one_line(self):
        """Пара «История + Обществознание» запрещена только в одной линейке потока: на время
        обществознания 10 класса история ОГЭ встаёт, на время обществознания ОГЭ — нет.
        """
        settings = weekdaySettings(joint_subject_pairs=[list(pair) for pair in DEFAULT_JOINT_SUBJECT_PAIRS])
        history = addCourse(settings, 1, "ОГЭ", "История", 1, "2026-09-07")
        tenth = addCourse(settings, 1, "10 класс", "Обществознание", 1, "2026-09-07")
        social = addCourse(settings, 1, "ОГЭ", "Обществознание", 1, "2026-09-07")
        answer = {history: emptyWeek(5), tenth: emptyWeek(5), social: emptyWeek(5)}
        answer[history][0][0] = lesson("История", "Иванова")
        answer[tenth][1][0] = lesson("Обществознание", "Петров")
        answer[social][2][0] = lesson("Обществознание", "Сидоров")

        self.assertEqual(slotConflicts(settings, answer, history, "История", [((0, 0), (1, 0))]), [])
        self.assertEqual(slotConflicts(settings, answer, history, "История", [((0, 0), (2, 0))]), [(2, 0, "pair", social)])


class SlotConflictEdgeTests(unittest.TestCase):
    """Перенос урока семинара по химии на другое время в готовом расписании."""
    def setUp(self):
        """Семинар (сентябрь–октябрь) с уроками пн-1 и ср-1, химия ЕГЭ продвинутый потока 1 во вт-1
        (те же месяцы) и химия ОГЭ потока 2 в чт-1 (ноябрь–декабрь) у того же преподавателя.
        """
        self.settings = emptySettings(teachers={"Иванова": teacher("Химия"), "Петров": teacher("Химия")},
                                      non_overlapping_programs=[["Семинары", "ЕГЭ продвинутый"]])
        setDayGrid(self.settings, [list(DEFAULT_DAY)] * 5)

        self.seminar = addCourse(self.settings, None, "Семинар ЕГЭ продвинутый", "Химия", 2, "2026-09-01")
        self.advanced = addCourse(self.settings, 1, "ЕГЭ продвинутый", "Химия", 1, "2026-09-01")
        self.later = addCourse(self.settings, 2, "ОГЭ", "Химия", 1, "2026-11-01")

        setDates(self.settings, self.seminar, "2026-09-01", "2026-10-31")
        setDates(self.settings, self.advanced, "2026-09-01", "2026-10-31")
        setDates(self.settings, self.later, "2026-11-01", "2026-12-31")

        self.answer = {
            self.seminar: place(place(emptyWeek(5), 0, 0, "Химия", "Иванова"), 2, 0, "Химия", "Иванова"),
            self.advanced: place(emptyWeek(5), 1, 0, "Химия", "Петров"),
            self.later: place(emptyWeek(5), 3, 0, "Химия", "Иванова"),
        }

    def conflicts(self, new):
        """Конфликты переноса урока семинара из пн-1 в слот ``new``."""
        return slotConflicts(self.settings, self.answer, self.seminar, "Химия", [((0, 0), new)])

    def test_place_taken_by_own_lesson(self):
        """На место, где у курса уже стоит свой урок (и он не уезжает), перенести нельзя."""
        self.assertEqual(self.conflicts((2, 0)), [(2, 0, "course", "Химия")])

    def test_program_that_must_not_overlap(self):
        """Семинар нельзя ставить в одно время с тем же предметом «ЕГЭ продвинутый»."""
        self.assertEqual(self.conflicts((1, 0)), [(1, 0, "program", self.advanced)])

    def test_teacher_busy_only_in_overlapping_months(self):
        """Урок преподавателя в курсе других месяцев не мешает; с пересекающимися датами — «занят»."""
        self.assertEqual(self.conflicts((3, 0)), [])

        setDates(self.settings, self.later, "2026-10-01", "2026-12-31")
        self.assertEqual(self.conflicts((3, 0)), [(3, 0, "busy", self.later)])

    def test_slot_outside_grid(self):
        """Слот, которого нет в сетке дня, — «missing», остальные проверки для него не нужны."""
        self.assertEqual(self.conflicts((5, 0)), [(5, 0, "missing", "")])

    def test_move_extends_short_week(self):
        """Перенос за пределы короткой недели курса дополняет её пустыми днями и уроками."""
        cell = {"subject": "Химия", "teachers": ["Иванова"]}
        answer = {"К": [[cell]]}

        moveLessons(answer, "К", [((0, 0), (2, 1))])

        self.assertEqual(answer["К"], [
            [{"subject": "#", "teachers": []}],
            [],
            [{"subject": "#", "teachers": []}, cell],
        ])


class PlannedMovesTests(unittest.TestCase):
    """Перенос уроков курса под новые закрепления."""
    def test_lesson_on_pinned_day_moves_first(self):
        """Уроки Пн-1 и Ср-1, закрепили Пн-2: переезжает урок понедельника, среда остаётся —
        два урока в понедельник не получается.
        """
        moves, final = plannedMoves([(0, 0), (2, 0)], [(0, 1)], 2)
        self.assertEqual(moves, [((0, 0), (0, 1))])
        self.assertEqual(final, [(0, 1), (2, 0)])

    def test_other_lessons_stay(self):
        """Закрепление в свободный день: ни один урок другого дня не трогается без нужды."""
        moves, final = plannedMoves([(0, 0), (2, 0), (4, 0)], [(1, 0)], 3)
        self.assertEqual(len(moves), 1)
        self.assertEqual(len({day for day, _ in final}), 3)


class JointConflictTests(unittest.TestCase):
    """«ЕГЭ основной» Потока 2 идёт вместе с Потоком 1 (проект ``jointProject``): у «Математика #1»
    источник (Поток 1) и копия (Поток 2) — пн и ср первым уроком, даты потоков пересекаются.
    """
    def setUp(self):
        self.settings, self.answer = jointProject()
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        self.source, self.copy = jointCourse(1, "Математика"), jointCourse(2, "Математика")
        self.third = jointCourse(2, "Математика", OWN_LINE)

    def test_source_and_copy_are_one_course_in_limit(self):
        """AC-28: преподаватель с источником и копией ведёт 1 курс, а не 2. При лимите 2 он может взять
        ещё один курс; при лимите 1 — нет, и в помехе написано «уже ведёт 1».
        """
        other = jointCourse(2, "Математика", LEVEL_LINE)

        self.settings["max_courses_per_teacher"] = 2
        self.assertEqual(teacherConflicts(self.settings, self.answer, other, "Математика", "Математика #1"), [])

        self.settings["max_courses_per_teacher"] = 1
        self.assertIn((None, None, "limit", 1), teacherConflicts(self.settings, self.answer, other, "Математика", "Математика #1"))

    def test_copy_is_not_busy_for_its_source(self):
        """AC-27: уроки копии не мешают преподавателю её источника (``teacherConflicts``); урок третьего
        курса в то же время — «занят».
        """
        self.assertEqual(teacherConflicts(self.settings, self.answer, self.source, "Математика", "Математика #1"), [])

        self.answer[self.third] = courseWeek("Математика", "Математика #1", (0, 0))
        self.assertEqual(teacherConflicts(self.settings, self.answer, self.source, "Математика", "Математика #1"), [
            (0, 0, "busy", self.third),
        ])

    def test_moving_source_lessons_ignores_copy(self):
        """AC-27: уроки источника меняются местами (пн ↔ ср) — уроки копии в этих часах не помеха
        (``slotConflicts`` / ``peerSlotConflicts``); урок третьего курса того же преподавателя — помеха.
        """
        self.assertEqual(slotConflicts(self.settings, self.answer, self.source, "Математика", [((0, 0), (2, 0)), ((2, 0), (0, 0))]), [])

        self.answer[self.third] = courseWeek("Математика", "Математика #1", (4, 0))
        self.assertIn((4, 0, "busy", self.third), slotConflicts(self.settings, self.answer, self.source, "Математика", [((0, 0), (4, 0))]))
