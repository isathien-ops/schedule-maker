"""Выгрузки в Excel (`src/modules/functions/export.py`).

* ``ExportWeekTests`` — недельные таблицы: по курсам, по преподавателям, по датам;
* ``CalendarEventsTests`` — разворачивание недели курса в календарь между датами курса;
* ``ExportVariantsTests`` — варианты этапа: лист сравнения (пометки «лучший» и «одинаково»)
  и листы вариантов (красные проблемы, жёлтые некритичные подписи — как на странице);
* ``ExportTeacherListTests`` — список преподавателей и их отметки времени;
* ``ExportEdgeTests`` — курсы, которых нет в настройках; столбца «без преподавателя» нет, если у всех
  уроков есть преподаватель; курсы «не ведёт»;
* ``ExportJointTests`` — «Линейка присоединяется к Потоку N»: пометка «вместе с Потоком N» у уроков
  копии и источника, общий урок и общий курс преподавателя — один раз;
* ``ExportTeacherRowsTests`` — «Смена преподавателя в подборе» (.spec/teacher-swap/SPEC.md): строки
  «Кто ведёт» на листе сравнения вариантов (AC-17);
* ``ExportTeacherRowsReviewTests`` — замечания проверки этого блока: курс без преподавателя, ширина столбцов.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import datetime
import unittest

from src.modules.translate import tr, translate
from src.modules.functions.courses import addCourse, setTeacherCourseState
from src.modules.functions.export import (
    PROBLEM_COLOR, WARNING_COLOR, CourseDatesError, calendarWorkbook, coursesWorkbook, generateCalendarEvents,
    teacherListWorkbook, teachersWorkbook, variantsWorkbook
)
from src.modules.functions.variants import rankVariants
from tests.builders import (
    JOINT_LINE, WEEKDAY_GRID, chemist, emptySettings, emptyWeek, jointCourse, jointProject, lesson, markJoint, place, teacher,
    weekdaySettings
)

GRID = [["16:20 - 17:50", "18:00 - 19:30", "19:40 - 21:10"]] * 5 + [["10:00 - 11:30", "11:40 - 13:10"]] * 2


def columnValues(page, column):
    """Значения столбца ``column`` (буква) листа, кроме пустых."""
    return [cell.value for cell in page[column] if cell.value is not None]


class ExportWeekTests(unittest.TestCase):
    """Недельные выгрузки: по курсам, по преподавателям, по датам."""
    COURSE = "Поток 1 — ОГЭ — Химия"

    def settings(self):
        """Один курс химии с датами одного понедельника."""
        return weekdaySettings(classes={"custom_groups": [{"name": self.COURSE, "program": "ОГЭ", "subjects": ["Химия"], "stream_id": 1,
                                                         "start_date": "2026-09-07", "end_date": "2026-09-07"}],
                                      "lessons": {self.COURSE: {"Химия": 2}}},
                             calendar_start_date="2026-09-01", calendar_end_date="2027-06-30")

    def test_lesson_outside_grid_is_skipped(self):
        """Урок с номером больше, чем в сетке дня (5-й при трёх), не выгружается и не ломает книгу —
        ни по курсам, ни по преподавателям (там у его преподавателя только заголовок столбца).
        """
        answer = {self.COURSE: emptyWeek(5, 5)}
        answer[self.COURSE][0][0] = lesson("Химия", "Иванова")
        answer[self.COURSE][0][4] = lesson("Химия", "Лишний")

        page = coursesWorkbook(self.settings(), answer, translate).active
        values = columnValues(page, "D")

        self.assertEqual(values, [self.COURSE, "Химия — Иванова"])
        self.assertFalse(any("Лишний" in str(cell.value) for row in page.iter_rows() for cell in row))

        page = teachersWorkbook(self.settings(), answer, translate).active

        self.assertEqual(columnValues(page, "D"), ["Иванова", "Поток 1 (с 07.09), ОГЭ, Химия"])
        self.assertEqual(columnValues(page, "E"), ["Лишний"])

    def test_lesson_without_teacher(self):
        """Урок без преподавателя подписан «Химия — без преподавателя», а не «Химия — »."""
        answer = {self.COURSE: emptyWeek(5)}
        answer[self.COURSE][0][0] = lesson("Химия")

        page = coursesWorkbook(self.settings(), answer, translate).active

        self.assertEqual(page["D2"].value, f"Химия — {translate('web.classes.no_teacher')}")
        self.assertNotEqual(translate("web.classes.no_teacher"), "web.classes.no_teacher")

    def test_column_width_is_limited(self):
        """Ширина столбца — по самому длинному тексту + 2, но не больше 60."""
        answer = {self.COURSE: emptyWeek(5)}
        answer[self.COURSE][0][0] = lesson("Химия", "И" * 200)

        page = coursesWorkbook(self.settings(), answer, translate).active

        self.assertEqual(page.column_dimensions["D"].width, 60)
        # Столбец «#»: «#» и номера уроков 1–3 — по одному символу
        self.assertEqual(page.column_dimensions["B"].width, 3)

    def test_teacher_column_marks_start_date(self):
        """В столбце преподавателя у курса с датой старта — «(с дд.мм)» после потока, у курса без даты
        пометки нет. Подпись собирается из полей курса: у доп. курса она одна часть («Семинар ОГЭ:
        Химия (с 01.10)»), а курс, которого уже нет в настройках, подписан своим названием.
        """
        settings = weekdaySettings(classes={"custom_groups": [
            {"name": "Поток 2 — 10 класс — Химия", "program": "10 класс", "subjects": ["Химия"], "stream_id": 2, "start_date": "2026-11-23"},
            {"name": "Поток 1 — ОГЭ — Химия", "program": "ОГЭ", "subjects": ["Химия"], "stream_id": 1},
            {"name": "Семинар ОГЭ: Химия", "program": "Семинары", "line": "Семинар ОГЭ", "subjects": ["Химия"], "stream_id": None,
             "start_date": "2026-10-01"},
        ], "lessons": {}})
        answer = {name: emptyWeek(5) for name in ("Поток 2 — 10 класс — Химия", "Поток 1 — ОГЭ — Химия", "Семинар ОГЭ: Химия", "Удалённый курс")}
        answer["Поток 2 — 10 класс — Химия"][0][0] = lesson("Химия", "Иванова")
        answer["Поток 1 — ОГЭ — Химия"][1][0] = lesson("Химия", "Иванова")
        answer["Семинар ОГЭ: Химия"][2][0] = lesson("Химия", "Иванова")
        answer["Удалённый курс"][3][0] = lesson("Химия", "Иванова")

        page = teachersWorkbook(settings, answer, translate).active

        self.assertEqual(columnValues(page, "D"), [
            "Иванова", "Поток 2 (с 23.11), 10 класс, Химия", "Поток 1, ОГЭ, Химия", "Семинар ОГЭ: Химия (с 01.10)", "Удалённый курс"
        ])

    def test_calendar_row(self):
        """Первый урок дня в календаре: дата, день, время, урок № 1, курс, предмет, преподаватель;
        закреплена только строка заголовков, включён автофильтр.
        """
        answer = {self.COURSE: emptyWeek(5)}
        answer[self.COURSE][0][0] = lesson("Химия", "Иванова")

        page = calendarWorkbook(self.settings(), answer, translate).active
        rows = list(page.iter_rows(min_row=2, values_only=True))

        self.assertEqual(len(rows), 1)
        value = rows[0][0]
        self.assertEqual(value.date() if isinstance(value, datetime.datetime) else value, datetime.date(2026, 9, 7))
        self.assertEqual(rows[0][1:], (translate("day.0"), "16:20 - 17:50", 1, self.COURSE, "Химия", "Иванова"))
        self.assertEqual(page.freeze_panes, "A2")
        self.assertEqual(page.auto_filter.ref, "A1:G2")


class CalendarEventsTests(unittest.TestCase):
    """Разворачивание недели курса по датам."""
    COURSE = "Поток 1 — ОГЭ — Химия"

    def events(self, start, end, days=5):
        """События курса с уроком каждый день недели (из ``days`` дней) между ``start`` и ``end``."""
        schedule = [[lesson("Химия", "Иванова")] for _ in range(days)]
        groups = [{"name": self.COURSE, "start_date": start, "end_date": end}]

        return generateCalendarEvents({self.COURSE: schedule}, groups, WEEKDAY_GRID, "2026-09-01", "2027-06-30")

    def test_one_day_course(self):
        """Курс, который начинается и кончается в один понедельник, даёт ровно один урок в эту дату;
        курс с концом раньше начала — ни одного.
        """
        events = self.events("2026-09-07", "2026-09-07")

        self.assertEqual(events, [(datetime.date(2026, 9, 7), 0, self.COURSE, "Химия", "Иванова", "16:20 - 17:50")])
        self.assertEqual(self.events("2026-09-07", "2026-09-06"), [])

    def test_days_outside_the_course_week_are_skipped(self):
        """Неделя курса из 5 дней: в субботу и воскресенье событий нет; неделя из 7 дней — уроки
        и в выходные (они есть, только если в сетке у выходных есть уроки).
        """
        events = self.events("2026-09-07", "2026-09-13", days=5)

        self.assertEqual([event[0].weekday() for event in events], [0, 1, 2, 3, 4])
        self.assertEqual([event[0].weekday() for event in self.events("2026-09-07", "2026-09-13", days=7)], [0, 1, 2, 3, 4, 5, 6])

    def test_wrong_date_is_course_dates_error(self):
        """Дату курса или календаря нельзя разобрать — CourseDatesError (её сервер показывает понятным
        текстом), в том числе когда дата записана не строкой.
        """
        with self.assertRaises(CourseDatesError):
            self.events("2026-13-01", "2026-09-13")

        with self.assertRaises(CourseDatesError):
            generateCalendarEvents({}, [], WEEKDAY_GRID, 20260901, "2027-06-30")

    def test_calendar_expansion_obeys_group_start_and_end_dates(self):
        """При выгрузке в календарь урок повторяется каждую неделю только между датами начала
        и конца курса; если курс закончился до начала, событий нет.
        """
        empty = {"subject": "#", "teachers": []}
        scheduled = {"subject": "Математика", "teachers": ["Teacher"]}
        week = [[scheduled], [empty], [empty], [empty], [empty]]
        group = {
            "name": "Поток 1 — ОГЭ — Математика",
            "start_date": "2026-10-05",
            "end_date": "2026-10-12"
        }

        events = generateCalendarEvents(
            {group["name"]: week},
            [group],
            [["16:20 - 17:50"], [], [], [], [], [], []],
            "2026-09-07",
            "2027-06-30"
        )

        self.assertEqual([event[0].isoformat() for event in events], ["2026-10-05", "2026-10-12"])
        self.assertTrue(all(event[5] == "16:20 - 17:50" for event in events))

        group["end_date"] = "2026-10-04"
        self.assertEqual(generateCalendarEvents(
            {group["name"]: week}, [group], [["16:20 - 17:50"], [], [], [], [], [], []],
            "2026-09-07", "2027-06-30"
        ), [])


class ExportVariantsTests(unittest.TestCase):
    """Выгрузка вариантов этапа: лист сравнения и листы вариантов."""
    COURSE = "Поток 1 — ОГЭ — Химия"

    def book(self, ranked, columns=(("total", "Итог"),), settings=None):
        """Книга вариантов по ``ranked`` (порядок и пометки «лучший» / «ничья» — как у сервера, rankVariants)."""
        settings = settings or weekdaySettings(classes={"custom_groups": [{"name": self.COURSE, "program": "ОГЭ", "subjects": ["Химия"], "stream_id": 1}], "lessons": {}})

        return variantsWorkbook(settings, rankVariants(list(ranked)), list(columns), translate, "Поток 1")

    def item(self, number, total=5, rejected=False, answer=None, issues=None, custom=None):
        """Вариант для выгрузки с метриками без жёстких нарушений."""
        metrics = {"missing": 0, "equalLessons": 0, "teacherClash": 0, "total": total, "custom": custom or {}}

        return {"number": number, "metrics": metrics, "answer": answer or {}, "issues": issues or {}, "accepted": False, "rejected": rejected}

    def test_best_mark_only_without_tie(self):
        """При равной оценке двух вариантов «лучший» не ставится никому; при разной — только первому."""
        best = translate("menu.main.tab.preview.best")

        page = self.book([self.item(1), self.item(2)]).active
        self.assertFalse(any(best in page.cell(row=1, column=col).value for col in (2, 3)))

        page = self.book([self.item(1, 5), self.item(2, 7)]).active
        self.assertIn(best, page["B1"].value)
        self.assertNotIn(best, page["C1"].value)

    def test_stale_variant_marked(self):
        """Вариант, собранный до начала идущих курсов (staleStarted), помечен «нельзя принять»
        (web.export_variants.stale) и не «лучший» даже с лучшей оценкой; «лучший» — принимаемый.
        """
        stale, best = translate("web.export_variants.stale"), translate("menu.main.tab.preview.best")
        page = self.book([{**self.item(1, 3), "staleStarted": [self.COURSE]}, self.item(2, 7)]).active

        self.assertIn(best, page["B1"].value)
        self.assertNotIn(stale, page["B1"].value)
        self.assertIn(f"{translate('menu.main.tab.run.variant')} 1", page["C1"].value)
        self.assertIn(stale, page["C1"].value)
        self.assertNotIn(best, page["C1"].value)

        # Вариант, сдвинувший урок курса, который шёл уже при сборке (movedStarted), — та же пометка
        moved = [{"course": self.COURSE, "lines": ["…"]}]
        page = self.book([{**self.item(1, 3), "movedStarted": moved}, self.item(2, 7)]).active
        self.assertIn(stale, page["C1"].value)
        self.assertNotIn(stale, page["B1"].value)

    def test_same_variant_marked(self):
        """Вариант, равный принятому расписанию (поле ``same``, ranking.rankedVariants), помечен
        «как сейчас» (web.preview.same), как на странице; другой вариант — нет.
        """
        same = translate("web.preview.same")
        page = self.book([{**self.item(1), "same": True}, self.item(2, 7)]).active

        self.assertIn(same, page["B1"].value)
        self.assertNotIn(same, page["C1"].value)

    def test_rejected_variant_is_grey(self):
        """Столбец отклонённого варианта залит серым, в заголовке «отклонён», лист назван с пометкой;
        «лучший» — первый неотклонённый.
        """
        book = self.book([self.item(1, rejected=True), self.item(2, 7)])
        page = book.active
        rejected = translate("web.preview.rejected")

        for row in (1, 2):
            self.assertTrue(page.cell(row=row, column=2).fill.start_color.rgb.endswith("EEEEEE"))
            self.assertFalse(str(page.cell(row=row, column=3).fill.start_color.rgb).endswith("EEEEEE"))

        self.assertIn(rejected, page["B1"].value)
        self.assertIn(translate("menu.main.tab.preview.best"), page["C1"].value)
        self.assertIn(f"{translate('menu.main.tab.run.variant')} 1 ({rejected})"[:31], book.sheetnames)

    def test_custom_rule_value(self):
        """Строка своего правила показывает число его нарушений в варианте."""
        page = self.book([self.item(1, custom={"abc": 7})], columns=[("custom:abc", "Моё правило")]).active

        self.assertEqual(page["A2"].value, "Моё правило")
        self.assertEqual(page["B2"].value, 7)

    def test_times_sorted_as_numbers(self):
        """«9:00» идёт раньше «18:00», хотя как текст наоборот."""
        settings = weekdaySettings(day_grid=[["18:00", "9:00"]] + [[]] * 6)
        sheet = self.book([self.item(1)], settings=settings).worksheets[1]

        self.assertEqual((sheet["A2"].value, sheet["A3"].value), ("9:00", "18:00"))

    def test_variant_lesson_outside_grid_is_skipped(self):
        """Урок варианта вне сетки дня (5-й при трёх) на лист варианта не попадает."""
        answer = {self.COURSE: emptyWeek(5, 5)}
        answer[self.COURSE][0][0] = lesson("Химия", "Иванова")
        answer[self.COURSE][0][4] = lesson("Химия", "Лишний")

        sheet = self.book([self.item(1, answer=answer)]).worksheets[1]

        self.assertEqual(sheet["B2"].value, "ОГЭ, Химия — Иванова")
        self.assertFalse(any("Лишний" in str(cell.value) for row in sheet.iter_rows() for cell in row))

    def test_problem_cell_is_red(self):
        """Урок с проблемой: текст проблемы под уроком и красный шрифт; урок без проблем — не красный."""
        answer = {self.COURSE: emptyWeek(5)}
        answer[self.COURSE][0][0] = lesson("Химия", "Иванова")
        answer[self.COURSE][0][1] = lesson("Химия", "Петров")
        issues = {self.COURSE: {"0-0": [{"text": "Преподаватель занят"}]}}

        sheet = self.book([self.item(1, answer=answer, issues=issues)]).worksheets[1]

        self.assertEqual(sheet["B2"].value, "ОГЭ, Химия — Иванова\n  — Преподаватель занят")
        self.assertTrue(sheet["B2"].font.color.rgb.endswith("B42318"))
        self.assertEqual(sheet["B3"].value, "ОГЭ, Химия — Петров")
        self.assertFalse(sheet["B3"].font.color is not None and str(sheet["B3"].font.color.rgb).endswith("B42318"))

    def test_tie_is_marked_equal(self):
        """При равной оценке у обоих вариантов «одинаково» (и нет «лучший»); при разной «одинаково» нет."""
        equal, best = translate("menu.main.tab.preview.equal"), translate("menu.main.tab.preview.best")

        page = self.book([self.item(1), self.item(2)]).active
        for col in (2, 3):
            self.assertIn(equal, page.cell(row=1, column=col).value)
            self.assertNotIn(best, page.cell(row=1, column=col).value)

        page = self.book([self.item(1, 5), self.item(2, 7)]).active
        self.assertFalse(any(equal in page.cell(row=1, column=col).value for col in (2, 3)))

    def test_warning_only_cell_is_yellow(self):
        """Только некритичная подпись («В тот же день: …») — ячейка жёлтая, не красная;
        вместе с проблемой — красная.
        """
        answer = {self.COURSE: emptyWeek(5)}
        answer[self.COURSE][0][0] = lesson("Химия", "Иванова")
        warn = {"text": "В тот же день: Физика", "level": "warn"}

        sheet = self.book([self.item(1, answer=answer, issues={self.COURSE: {"0-0": [warn]}})]).worksheets[1]
        self.assertTrue(sheet["B2"].font.color.rgb.endswith(WARNING_COLOR))

        sheet = self.book([self.item(1, answer=answer, issues={self.COURSE: {"0-0": [warn, "Преподаватель занят"]}})]).worksheets[1]
        self.assertTrue(sheet["B2"].font.color.rgb.endswith(PROBLEM_COLOR))

    def test_seminars_of_one_subject_are_told_apart(self):
        """Два семинара по одному предмету подписаны своими линейками («Семинар ОГЭ» и «Семинар ЕГЭ
        продвинутый»), а не общей программой «Семинары».
        """
        oge, ege = "Семинар ОГЭ: Химия", "Семинар ЕГЭ продвинутый: Химия"
        groups = [{"name": name, "program": "Семинары", "line": name.split(": ")[0], "subjects": ["Химия"], "stream_id": None, "block": "extra"}
                  for name in (oge, ege)]
        settings = weekdaySettings(classes={"custom_groups": groups, "lessons": {}})
        answer = {oge: emptyWeek(5), ege: emptyWeek(5)}
        answer[oge][0][0] = lesson("Химия", "Иванова")
        answer[ege][0][1] = lesson("Химия", "Петров")

        sheet = self.book([self.item(1, answer=answer)], settings=settings).worksheets[1]

        self.assertEqual(sheet["B2"].value, "Семинар ОГЭ, Химия — Иванова")
        self.assertEqual(sheet["B3"].value, "Семинар ЕГЭ продвинутый, Химия — Петров")


class ExportTeacherListTests(unittest.TestCase):
    """Выгрузка списка преподавателей и их отметок времени."""
    def setUp(self):
        """Три курса химии и курс физики; Иванова ведёт первый курс химии, может вести два других;
        курс физики остался у неё в «запрещено» с тех пор, как она вела физику.
        """
        names = ["Поток 1 — ОГЭ — Химия", "Поток 1 — ЕГЭ основной — Химия", "Поток 1 — 10 класс — Химия"]
        self.chemistry = names
        self.physics = "Поток 1 — ОГЭ — Физика"
        groups = [{"name": name, "subjects": ["Химия"], "stream_id": 1} for name in names]
        groups.append({"name": self.physics, "subjects": ["Физика"], "stream_id": 1})

        teacher = chemist(*names, assigned=names[:1], forbidden=[self.physics])
        teacher["availability"] = {"1": {"free": [[0, 0]], "possible": [[0, 1]]}}
        self.settings = weekdaySettings(classes={"custom_groups": groups, "lessons": {}}, teachers={"Иванова": teacher})

    def test_teacher_row(self):
        """Строка преподавателя: «ведёт» — один курс, «может» — два, число курсов = 1; курса чужого
        предмета нет ни в одном списке.
        """
        page = teacherListWorkbook(self.settings, {}, translate, []).active
        row = [cell.value for cell in page[2]]

        self.assertEqual(row[:4], ["Иванова", "Химия", self.chemistry[0], "\n".join(self.chemistry[1:])])
        self.assertIn(row[4], (None, ""))
        self.assertEqual(row[5:7], [1, 0])
        self.assertFalse(any(self.physics in str(value) for value in row))

    def test_time_marks(self):
        """Лист времени: «не может», «может» и «удобно» со своими цветами."""
        sheet = teacherListWorkbook(self.settings, {}, translate, [("1", "Поток 1")]).worksheets[1]

        expected = {
            "D2": ("menu.main.tab.teachers.busy", "FEE4E2"),      # пн, урок 1
            "D3": ("menu.main.tab.teachers.possible", "FEF0C7"),  # пн, урок 2
            "D4": ("menu.main.tab.teachers.free", "D1FADF"),      # пн, урок 3
            "D6": ("menu.main.tab.teachers.free", "D1FADF")       # вт, урок 1
        }

        for address, (key, fill) in expected.items():
            self.assertEqual(sheet[address].value, translate(key), address)
            self.assertTrue(sheet[address].fill.start_color.rgb.endswith(fill), address)


class ExportEdgeTests(unittest.TestCase):
    """Выгрузка в Excel: курсы, которых нет в настройках; столбца «без преподавателя» нет, если у всех уроков
    есть преподаватель; курсы «не ведёт».
    """
    def setUp(self):
        """Три курса химии и курс физики потока 1; Иванова ведёт первый, может второй, третий убран."""
        self.settings = emptySettings(teachers={"Иванова": teacher("Химия")}, day_grid=GRID)
        self.first = addCourse(self.settings, 1, "ОГЭ", "Химия", 1, "2026-09-07")
        self.second = addCourse(self.settings, 1, "ЕГЭ основной", "Химия", 1, "2026-09-07")
        self.third = addCourse(self.settings, 1, "10 класс", "Химия", 1, "2026-09-07")
        self.physics = addCourse(self.settings, 1, "ОГЭ", "Физика", 1, "2026-09-07")

        setTeacherCourseState(self.settings, "Иванова", "Химия", self.first, "assigned")
        setTeacherCourseState(self.settings, "Иванова", "Химия", self.third, "no")

        self.answer = {
            self.first: place(emptyWeek(), 0, 0, "Химия", "Иванова"),
            self.second: place(emptyWeek(), 1, 0, "Химия", "Иванова"),
            "Удалённый курс": place(emptyWeek(), 2, 0, "Химия", "Иванова"),
        }

    @staticmethod
    def texts(page):
        """Все непустые значения листа одной строкой."""
        return "\n".join(str(cell.value) for row in page.iter_rows() for cell in row if cell.value is not None)

    def test_courses_sheet_skips_removed_course(self):
        """Курс расписания, которого нет в настройках, не выгружается: ни столбца, ни уроков."""
        page = coursesWorkbook(self.settings, self.answer, translate).active

        self.assertEqual([page.cell(row=1, column=col).value for col in range(4, 8)], [self.first, self.second, self.third, self.physics])
        self.assertNotIn("Удалённый курс", self.texts(page))
        self.assertEqual(self.texts(page).count("Химия — Иванова"), 2)

    def test_teachers_sheet_without_unassigned_lessons(self):
        """Если у каждого урока есть преподаватель, отдельного столбца «без преподавателя» нет."""
        page = teachersWorkbook(self.settings, self.answer, translate).active

        self.assertEqual(page.cell(row=1, column=4).value, "Иванова")
        self.assertIsNone(page.cell(row=1, column=5).value)
        self.assertNotIn(translate("web.classes.no_teacher"), self.texts(page))

    def test_teacher_list_skips_courses_she_does_not_teach(self):
        """В списке преподавателей курс со состоянием «не ведёт» не попадает ни в одну графу."""
        self.answer.pop("Удалённый курс")
        page = teacherListWorkbook(self.settings, self.answer, translate, []).active
        row = [page.cell(row=2, column=col).value for col in range(1, 8)]

        # Преподаватель, предметы, «ведёт», «может вести», «запрещено», курсов, уроков в неделю
        self.assertEqual(row[0], "Иванова")
        self.assertEqual(row[1], "Химия")
        self.assertEqual(row[2], self.first)
        self.assertEqual(row[3], self.second)
        self.assertFalse(row[4])
        self.assertEqual(row[5], 1)
        self.assertEqual(row[6], 2)
        self.assertNotIn(self.third, self.texts(page))


class ExportJointTests(unittest.TestCase):
    """«ЕГЭ основной» Потока 2 идёт вместе с Потоком 1 (проект ``jointProject``): у «Математика #1»
    источник (Поток 1, с 07.09) и копия (Поток 2, с 23.11) — пн и ср первым уроком. Пометка у урока —
    текст ``web.lesson.joint`` («вместе с Потоком {number}»).
    """
    NAME = "Математика #1"

    def setUp(self):
        self.settings, self.answer = jointProject()
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        self.source, self.copy = jointCourse(1, "Математика"), jointCourse(2, "Математика")

    @staticmethod
    def note(number):
        """Пометка «вместе с Потоком ``number``»."""
        return tr("web.lesson.joint", number=number)

    @staticmethod
    def column(page, title):
        """Номер столбца с заголовком ``title`` в первой строке листа."""
        return next(cell.column for cell in page[1] if cell.value == title)

    def test_courses_sheet_marks_copy_lessons(self):
        """AC-32, книга «Курсы»: в столбце копии у каждого урока « (вместе с Потоком 1)»."""
        page = coursesWorkbook(self.settings, self.answer, translate).active
        col = self.column(page, self.copy)
        cells = [page.cell(row=row, column=col).value for row in range(2, page.max_row + 1) if page.cell(row=row, column=col).value]

        self.assertEqual(cells, [f"Математика — {self.NAME} ({self.note(1)})"] * 2)

    def test_teachers_sheet_shows_shared_lesson_once(self):
        """AC-32, книга «Преподаватели»: общий урок источника и копии — одна строка в ячейке
        преподавателя, а не две.
        """
        page = teachersWorkbook(self.settings, self.answer, translate).active
        value = page.cell(row=2, column=self.column(page, self.NAME)).value

        self.assertTrue(value)
        self.assertNotIn("\n", value)

    def test_calendar_notes_copy_and_source(self):
        """AC-32, книга «Календарь»: события копии — со своими датами (с 23.11.2026, начала Потока 2)
        и с примечанием «вместе с Потоком 1»; у событий источника — «вместе с Потоком 2».
        """
        page = calendarWorkbook(self.settings, self.answer, translate).active
        rows = list(page.iter_rows(min_row=2, values_only=True))
        day = lambda value: value.date() if isinstance(value, datetime.datetime) else value

        copy_rows = [row for row in rows if row[4] == self.copy]
        source_rows = [row for row in rows if row[4] == self.source]

        self.assertEqual(day(copy_rows[0][0]), datetime.date(2026, 11, 23))
        self.assertTrue(source_rows)
        self.assertTrue(all(any(self.note(1) in str(value) for value in row) for row in copy_rows))
        self.assertTrue(all(any(self.note(2) in str(value) for value in row) for row in source_rows))

    def test_teacher_list_counts_shared_course_once(self):
        """AC-28 и AC-32, «Список преподавателей»: преподаватель ведёт источник (и вместе с ним копию) —
        у него 1 курс и 2 урока в неделю, а не 4.
        """
        setTeacherCourseState(self.settings, self.NAME, "Математика", self.source, "assigned")

        page = teacherListWorkbook(self.settings, self.answer, translate, []).active
        row = next([cell.value for cell in line] for line in page.iter_rows(min_row=2) if line[0].value == self.NAME)

        self.assertEqual(row[5:7], [1, 2])

    def test_variant_sheet_marks_copy_lessons(self):
        """AC-32, листы вариантов: урок копии в варианте Потока 2 подписан «вместе с Потоком 1»."""
        variant = {self.copy: copy.deepcopy(self.answer[self.copy])}
        metrics = {"missing": 0, "equalLessons": 0, "teacherClash": 0, "total": 0, "custom": {}}
        item = {"number": 1, "metrics": metrics, "answer": variant, "issues": {}, "accepted": False, "rejected": False}

        sheet = variantsWorkbook(self.settings, rankVariants([item]), [("total", "Итог")], translate, "Поток 2").worksheets[1]

        self.assertTrue(sheet["B2"].value.startswith(f"{JOINT_LINE}, Математика — {self.NAME}"))
        self.assertIn(self.note(1), sheet["B2"].value)


class ExportTeacherRowsTests(unittest.TestCase):
    """Лист сравнения вариантов: под правилами — строки «Кто ведёт» (заголовок web.preview.teachers_head
    и строка на курс), те же, что блок таблицы на «Предпросмотре». Варианты — как их отдаёт сервер
    (ranking.rankedVariants): у каждого ``teachers`` ({курс: [имена]}) и ``teacherChanges``. Строка
    курса есть, если преподаватель различается между не отклонёнными вариантами или с принятым
    расписанием (у варианта есть запись ``teacherChanges`` по курсу); в ячейке — кто ведёт в варианте.
    """
    CHEMISTRY, PHYSICS = "Поток 1 — ОГЭ — Химия", "Поток 1 — ОГЭ — Физика"
    OLD, NEW, PHYSICIST = "Иванова Анна", "Петрова Мария", "Сидоров Иван"

    def item(self, number, chemist, changed=False):
        """Вариант номер ``number``: Химию ведёт ``chemist``, Физику — всегда ``PHYSICIST``; ``changed`` —
        в принятом расписании Химию ведёт ``OLD`` (запись в ``teacherChanges``).
        """
        answer = {self.CHEMISTRY: place(emptyWeek(5), 0, 0, "Химия", chemist), self.PHYSICS: place(emptyWeek(5), 1, 0, "Физика", self.PHYSICIST)}
        changes = [{"course": self.CHEMISTRY, "subject": "Химия", "before": [self.OLD], "after": [chemist]}] if changed else []
        metrics = {"missing": 0, "equalLessons": 0, "teacherClash": 0, "total": 0, "custom": {}}

        return {"number": number, "metrics": metrics, "answer": answer, "issues": {}, "accepted": False, "rejected": False,
                "teachers": {self.CHEMISTRY: [chemist], self.PHYSICS: [self.PHYSICIST]}, "teacherChanges": changes}

    def compare(self, *items):
        """Лист сравнения книги вариантов ``items`` (порядок — rankVariants: при равной оценке по номеру)."""
        groups = [{"name": name, "program": "ОГЭ", "subjects": [subject], "stream_id": 1} for name, subject in ((self.CHEMISTRY, "Химия"), (self.PHYSICS, "Физика"))]
        settings = weekdaySettings(classes={"custom_groups": groups, "lessons": {}})

        return variantsWorkbook(settings, rankVariants(list(items)), [("total", "Итог")], translate, "Поток 1").active

    def labels(self, page):
        """{номер строки: подпись в столбце A} листа сравнения, без пустых."""
        return {row: str(page.cell(row=row, column=1).value) for row in range(1, page.max_row + 1) if page.cell(row=row, column=1).value is not None}

    def courseRow(self, page, course):
        """Номер строки, в подписи которой есть ``course`` (None — такой строки нет)."""
        return next((row for row, label in self.labels(page).items() if course in label), None)

    def test_rows_when_variants_differ(self):
        """AC-17: вариант 1 даёт Химию ``NEW`` (в расписании — ``OLD``), вариант 2 — ``OLD``. После строк правил —
        заголовок «Кто ведёт» и строка Химии: у варианта 1 ``NEW``, у варианта 2 ``OLD``. Физику во всех
        вариантах ведёт один преподаватель — её строки нет.
        """
        self.assertNotEqual(translate("web.preview.teachers_head"), "web.preview.teachers_head", "в ru.hjson нет текста web.preview.teachers_head")
        page = self.compare(self.item(1, self.NEW, changed=True), self.item(2, self.OLD))
        labels = self.labels(page)

        head = next((row for row, label in labels.items() if translate("web.preview.teachers_head") in label), None)
        row = self.courseRow(page, self.CHEMISTRY)

        self.assertIsNotNone(head)
        self.assertIsNotNone(row)
        self.assertGreater(head, 2)
        self.assertGreater(row, head)
        self.assertIn(self.NEW.split()[0], str(page.cell(row=row, column=2).value))
        self.assertIn(self.OLD.split()[0], str(page.cell(row=row, column=3).value))
        self.assertIsNone(self.courseRow(page, self.PHYSICS))

    def test_row_for_change_against_schedule(self):
        """AC-17: один вариант, Химию в нём ведёт ``NEW``, а в расписании — ``OLD`` (``teacherChanges``):
        строка Химии есть и тогда, когда сравнивать варианты не с чем.
        """
        page = self.compare(self.item(1, self.NEW, changed=True))
        row = self.courseRow(page, self.CHEMISTRY)

        self.assertIsNotNone(row)
        self.assertIn(self.NEW.split()[0], str(page.cell(row=row, column=2).value))

    def test_no_rows_without_teacher_differences(self):
        """AC-17: у обоих вариантов и в расписании преподаватели те же — блока «Кто ведёт» нет: под итогом
        только строки правил.
        """
        self.assertNotEqual(translate("web.preview.teachers_head"), "web.preview.teachers_head", "в ru.hjson нет текста web.preview.teachers_head")
        page = self.compare(self.item(1, self.OLD), self.item(2, self.OLD))

        self.assertFalse([label for label in self.labels(page).values() if translate("web.preview.teachers_head") in label])
        self.assertIsNone(self.courseRow(page, self.CHEMISTRY))
        self.assertEqual(page.max_row, 2)


class ExportTeacherRowsReviewTests(unittest.TestCase):
    """Замечания проверки блока «Кто ведёт» листа сравнения: вариант снимает преподавателя принятого
    курса (его удалили или запретили ему курс после сборки), полные имена не рвутся в узком столбце.
    Варианты — как в ``ExportTeacherRowsTests``.
    """
    CHEMISTRY, PHYSICS = ExportTeacherRowsTests.CHEMISTRY, ExportTeacherRowsTests.PHYSICS
    OLD, NEW, PHYSICIST = ExportTeacherRowsTests.OLD, ExportTeacherRowsTests.NEW, ExportTeacherRowsTests.PHYSICIST
    item, compare, labels, courseRow = (ExportTeacherRowsTests.item, ExportTeacherRowsTests.compare,
                                        ExportTeacherRowsTests.labels, ExportTeacherRowsTests.courseRow)

    def test_course_left_without_teacher(self):
        """Вариант снимает ``OLD`` с Химии, нового преподавателя нет: в ячейке «без преподавателя»
        (web.classes.no_teacher) и «Сейчас ведёт: ``OLD``», а не пустая строка.
        """
        item = self.item(1, self.NEW, changed=True)
        item["teachers"].pop(self.CHEMISTRY)
        item["teacherChanges"][0]["after"] = []

        page = self.compare(item)
        value = str(page.cell(row=self.courseRow(page, self.CHEMISTRY), column=2).value)

        self.assertTrue(value.startswith(translate("web.classes.no_teacher")), value)
        self.assertIn(tr("web.preview.teacher_now", teacher=self.OLD), value)

    def test_teacher_block_widens_variant_columns(self):
        """С блоком «Кто ведёт» столбцы вариантов шире, чем без него: в ячейке полные имена."""
        widths = [self.compare(*items).column_dimensions["B"].width
                  for items in ((self.item(1, self.NEW, changed=True),), (self.item(1, self.OLD),))]

        self.assertGreater(widths[0], widths[1])
        self.assertGreaterEqual(widths[0], len(self.NEW) + 2)
