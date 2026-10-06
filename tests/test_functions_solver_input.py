"""Вход решателя одного этапа (`src/modules/functions/solver_input.py`, ``buildStageSettings``).

* ``StageInputTests`` — вход этапа и вставка варианта этапа в общее расписание;
* ``StartedCoursesInputTests`` — этап с курсами, которые уже идут (в том числе без преподавателя:
  такой курс в решатель не идёт, но его уроки остаются ценами слотов мягких правил у соседей;
  ручных закреплений вместе с уроками из расписания — не больше часов курса, и первыми отбрасываются
  те, которые решатель всё равно не поставит, а закрепление на месте урока другого идущего курса — всегда);
* ``SameDayPairsTests`` — пары курсов «сдают вместе» (``same_day_pairs``), которые решатель
  старается развести по разным дням;
* ``BlockStageInputTests`` — вход этапа блока (летняя школа, майский марафон): уроки потоков,
  которые к блоку закончились, не занимают время преподавателей;
* ``PinForecastTests`` — прогноз у галочки «Оставить уже принятые уроки на месте» (``pinForecast``):
  сколько уроков закрепится, сколько подберёт программа и у скольких нет преподавателя; ровно
  столько закрепляет вход решателя, и те же числа печатает solve.exe («Закреплено N из M уроков,
  подбирается K, без преподавателя (не ставятся): X») — и тогда, когда закрепления идущего курса
  встают не все.
* ``JointCopiesInputTests`` — «Линейка присоединяется к Потоку N»: курсы-копии в вход этапа не
  входят, их уроки доходят до движка занятостью преподавателя, запретами соседей
  (``blocked_slots``) и ценами слотов мягких правил (``custom_penalties_compiled.class_slots``);
  «оставить принятое» (keep) и прогноз закреплений копий не считают.
* ``TeacherSwapInputTests`` — смена преподавателя в подборе (.spec/teacher-swap, AC-4, AC-6):
  идущие курсы и курсы из «оставить принятое» приходят с «ведёт» и сохраняют преподавателя из
  расписания, хотя есть кандидат лучше; источники общих уроков — в ``keep_teacher_courses``.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
import unittest
from unittest import mock

from src.variables import DEFAULT_WEIGHTS
from src.modules.functions.courses import addCourse, setSectionEnd, setSectionStart, setTeacherCourseState, setTeacherSubjects
from src.modules.functions.files import readJson
from src.modules.functions.model import teacherAvailability
from src.modules.functions.solver_input import buildStageSettings, keepCourses, pinForecast
from src.modules.functions.stages import mergeStageAnswer, stageCourses, teacherCommitments
from tests.builders import (
    JOINT_LINE, JOINT_STARTS, LEVEL_LINE, OWN_LINE, SOLVER, baseSettings, chemist, courseWeek, emptyWeek, jointCourse, jointProject, lesson,
    makeSettings, markCannot, markJoint, place, setDates, teacher, weekdaySettings
)
from tests.engine import TEACHER_A, TEACHER_B, SWAP_SUBJECT, courseTeachers, pinSummary, ruleViolations, runSolver, solved
from tests.real_project import FrozenDate

# Дата начала в прошлом: такой курс с уроками в расписании «уже идёт» при любой сегодняшней дате
PAST = "2020-01-01"
START = "2026-09-07"
# Дата начала в будущем: такой курс ещё не идёт, даже если его уроки уже стоят в расписании
FUTURE = "2999-01-01"


class StageInputTests(unittest.TestCase):
    """Вход решателя одного этапа и вставка варианта в расписание."""
    def setUp(self):
        """Курсы химии ОГЭ потоков 1 и 2; Иванова ведёт оба."""
        self.settings = weekdaySettings()
        self.first = addCourse(self.settings, 1, "ОГЭ", "Химия", 1, "2026-09-07")
        self.second = addCourse(self.settings, 2, "ОГЭ", "Химия", 1, "2026-11-01")
        self.settings["teachers"]["Иванова"] = chemist(self.first, self.second, assigned=[self.first, self.second])

    def test_assigned_keeps_only_stage_courses(self):
        """В «ведёт» во входе этапа 2 остаётся только курс потока 2: решатель не получает чужих курсов."""
        result = buildStageSettings(self.settings, {}, "2")
        item = result["teachers"]["Иванова"]["subjects"][0]

        self.assertEqual(item["assigned"], [self.second])
        self.assertEqual(item["classes"], [self.second])
        self.assertEqual([group["name"] for group in result["classes"]["custom_groups"]], [self.second])
        # Исходные настройки не меняются
        self.assertEqual(self.settings["teachers"]["Иванова"]["subjects"][0]["assigned"], [self.first, self.second])

    def test_pinned_lesson_of_other_stage_shown_once(self):
        """Закреплённый урок курса потока 1 уже стоит в расписании: на этапе 2 слот занят этим курсом
        один раз («busy», курс), а не «курс и курс».
        """
        self.settings["constants"] = {self.first: {"0-0": "Химия"}}
        answer = {self.first: emptyWeek(5)}
        answer[self.first][0][0] = lesson("Химия", "Иванова")

        self.assertEqual(teacherCommitments(self.settings, answer, "Иванова", "2"), {(0, 0): ("busy", self.first)})
        self.assertEqual(teacherCommitments(self.settings, answer, "Иванова", "1"), {(0, 0): ("pinned", self.first)})

    def test_merge_takes_only_stage_courses(self):
        """В расписание попадают только курсы этапа из варианта; курс другого этапа в варианте не
        добавляется и не затирает принятое.
        """
        wa, wb, wc = [[lesson("А")]], [[lesson("Б")]], [[lesson("В")]]

        self.assertEqual(mergeStageAnswer({"A": wa}, {"B": wb, "C": wc}, ["B"]), {"A": wa, "B": wb})
        self.assertEqual(mergeStageAnswer({"A": wa}, {"B": wb, "A": wc}, ["B"]), {"A": wa, "B": wb})


class StartedCoursesInputTests(unittest.TestCase):
    """Вход решателя для этапа с начавшимися курсами."""
    def test_dropped_started_course_prices_neighbours(self):
        """Мягкие правила с выброшенным идущим курсом без преподавателя — цены слотов соседей.

        Химия идёт (дата в прошлом), её урок (0, 0) без преподавателя: решатель её не получает.
        Биология той же линейки — пара «нежелательно одновременно» с химией: в слоте (0, 0) у биологии
        цена softSubjectPair, так же как с курсом-копией (не только копии дают такие цены).
        """
        settings = baseSettings(soft_subject_pairs=[["Химия", "Биология"]], teachers={"Иванова": teacher("Биология")})
        chemistry = addCourse(settings, 1, "ЕГЭ основной", "Химия", 1, PAST)
        biology = addCourse(settings, 1, "ЕГЭ основной", "Биология", 1, START)
        week = emptyWeek(5)
        week[0][0] = {"subject": "Химия", "teachers": []}

        stage = buildStageSettings(settings, {chemistry: week}, "1", weights={"softSubjectPair": 7})

        self.assertNotIn(chemistry, [group["name"] for group in stage["classes"]["custom_groups"]])
        self.assertIn([0, 0, 7], stage["custom_penalties_compiled"]["class_slots"].get(biology, []))

    def test_own_busy_time_is_not_doubled(self):
        """Слот, где преподаватель и сам «не может», и занят уроком другого этапа, в «не может» один раз."""
        settings = baseSettings(teachers={"Иванова": teacher("Химия")})
        first = addCourse(settings, 1, "ОГЭ", "Химия", 1, "2026-09-01")
        second = addCourse(settings, 2, "ОГЭ", "Химия", 1, "2026-09-01")
        teacherAvailability(settings["teachers"]["Иванова"], "1")["free"].append([0, 0])

        answer = {second: place(emptyWeek(5), 0, 0, "Химия", "Иванова")}
        stage = buildStageSettings(settings, answer, "1")

        self.assertEqual(stage["teachers"]["Иванова"]["free"], [[0, 0]])
        self.assertEqual([group["name"] for group in stage["classes"]["custom_groups"]], [first])

    def test_started_course_without_teacher_is_dropped(self):
        """Начавшийся курс, у уроков которого нет преподавателя, решателю не передаётся; его уроки
        запрещены курсам той же линейки с парой «нельзя одновременно» и курсам непересекающейся
        программы с тем же предметом. Курс, который только «оставлен» и ещё не начался, остаётся.
        """
        settings = baseSettings(joint_subject_pairs=[["Химия", "Биология"]], non_overlapping_programs=[["ЕГЭ основной", "ОГЭ"]])
        chemistry = addCourse(settings, 1, "ЕГЭ основной", "Химия", 2, PAST)
        biology = addCourse(settings, 1, "ЕГЭ основной", "Биология", 1, PAST)
        oge_biology = addCourse(settings, 1, "ОГЭ", "Биология", 1, PAST)
        oge_chemistry = addCourse(settings, 1, "ОГЭ", "Химия", 1, PAST)
        physics = addCourse(settings, 1, "ОГЭ", "Физика", 1, "2999-01-01")

        week = emptyWeek(5)
        week[0][0] = week[2][1] = {"subject": "Химия", "teachers": []}
        answer = {chemistry: week, physics: place(emptyWeek(5), 4, 2, "Физика", "Уволен")}
        answer[physics][4][2]["teachers"] = []

        stage = buildStageSettings(settings, answer, "1", keep=[physics])

        self.assertEqual([group["name"] for group in stage["classes"]["custom_groups"]], [biology, oge_biology, oge_chemistry, physics])
        self.assertNotIn(chemistry, stage["classes"]["lessons"])
        self.assertNotIn(chemistry, stage["constants"])
        self.assertEqual(stage["constants"][physics], {"4-2": "Физика"})
        self.assertEqual(stage["blocked_slots"], {biology: [[0, 0], [2, 1]], oge_chemistry: [[0, 0], [2, 1]]})
        # Выброшенный курс не участвует и в парах «в разные дни»
        self.assertFalse(any(chemistry in pair for pair in stage["custom_penalties_compiled"]["same_day_pairs"]))

    def test_started_course_keeps_its_teacher(self):
        """Начавшийся курс закрепляется за преподавателем с его уроков (и попадает в его «может вести»,
        даже если его там не было), а закрепление у другого преподавателя снимается.
        """
        settings = baseSettings(teachers={"Сидоров": teacher("Химия"), "Кузнецов": teacher("Химия")})
        course = addCourse(settings, 1, "ОГЭ", "Химия", 1, PAST)
        settings["teachers"]["Кузнецов"]["subjects"][0]["assigned"] = [course]
        settings["teachers"]["Сидоров"]["subjects"][0]["classes"] = []
        answer = {course: place(emptyWeek(5), 1, 1, "Химия", "Сидоров")}

        stage = buildStageSettings(settings, answer, "1")

        self.assertEqual(stage["teachers"]["Сидоров"]["subjects"][0]["classes"], [course])
        self.assertEqual(stage["teachers"]["Сидоров"]["subjects"][0]["assigned"], [course])
        self.assertEqual(stage["teachers"]["Кузнецов"]["subjects"][0]["assigned"], [])
        self.assertEqual(stage["teachers"]["Кузнецов"]["subjects"][0]["classes"], [course])
        self.assertEqual(stage["constants"], {course: {"1-1": "Химия"}})
        # Исходные настройки не меняются
        self.assertEqual(settings["teachers"]["Кузнецов"]["subjects"][0]["assigned"], [course])

    def test_answer_pins_win_over_extra_manual_pins(self):
        """Уроки идущего курса из расписания и его ручные закрепления вместе — не больше его часов:
        лишние ручные отбрасываются (по порядку мест, как их перебирает решатель), а уроки из расписания
        остаются все. Иначе решатель отверг бы урок из расписания («закреплено больше уроков, чем часов»),
        и каждый вариант сдвинул бы урок идущего курса — принять его было бы нельзя (stages.movedStarted).

        Химия: 3 урока, в расписании 0-1 и 4-2, вручную закреплены 1-0, 2-3 и 4-2 (совпадает с уроком
        из расписания — это одно место).
        """
        settings = baseSettings(teachers={"Сидоров": teacher("Химия")})
        course = addCourse(settings, 1, "ОГЭ", "Химия", 3, PAST)
        settings["constants"] = {course: {"1-0": "Химия", "2-3": "Химия", "4-2": "Химия"}}
        answer = {course: place(place(emptyWeek(5), 0, 1, "Химия", "Сидоров"), 4, 2, "Химия", "Сидоров")}

        stage = buildStageSettings(settings, answer, "1")

        self.assertEqual(stage["constants"], {course: {"0-1": "Химия", "1-0": "Химия", "4-2": "Химия"}})
        self.assertEqual(pinForecast(settings, answer, "1")["pinned"], 3)

    def test_possible_manual_pin_wins_over_impossible(self):
        """Из лишних ручных закреплений идущего курса первыми отбрасываются те, которые решатель всё равно
        не поставит (stages.pinConflicts): иначе осталось бы невозможное, а возможное пропало бы.

        Химия: 3 урока, в расписании 0-1 и 4-2, вручную закреплены 1-0 (у Сидорова там «не может») и 3-0 —
        остаётся 3-0, и прогноз закрепляет все три урока.
        """
        settings = baseSettings(teachers={"Сидоров": teacher("Химия")})
        course = addCourse(settings, 1, "ОГЭ", "Химия", 3, PAST)
        settings["constants"] = {course: {"1-0": "Химия", "3-0": "Химия"}}
        markCannot(settings, "Сидоров", "1", (1, 0))
        answer = {course: place(place(emptyWeek(5), 0, 1, "Химия", "Сидоров"), 4, 2, "Химия", "Сидоров")}

        stage = buildStageSettings(settings, answer, "1")

        self.assertEqual(stage["constants"], {course: {"0-1": "Химия", "3-0": "Химия", "4-2": "Химия"}})
        self.assertEqual(pinForecast(settings, answer, "1")["pinned"], 3)

    def laterStartedProject(self):
        """Идущие биология (2 урока, в расписании 0-1) и химия (1 урок, в расписании 2-2) одного Сидорова;
        биология вручную закреплена на 2-2 (её имя раньше): (настройки, расписание, биология, химия).
        """
        settings = baseSettings(subjects=[["Химия", 1], ["Биология", 1]], teachers={"Сидоров": teacher("Химия", "Биология")})
        biology = addCourse(settings, 1, "ОГЭ", "Биология", 2, PAST)
        chemistry = addCourse(settings, 1, "ОГЭ", "Химия", 1, PAST)
        settings["constants"] = {biology: {"2-2": "Биология"}}
        answer = {biology: place(emptyWeek(5), 0, 1, "Биология", "Сидоров"), chemistry: place(emptyWeek(5), 2, 2, "Химия", "Сидоров")}

        return settings, answer, biology, chemistry

    def test_manual_pin_does_not_push_out_later_started_lesson(self):
        """Ручное закрепление идущего курса на месте урока другого идущего курса с тем же преподавателем
        во вход не попадает, даже если имя другого курса позже: решатель ставит закрепления по именам курсов,
        поставил бы ручное первым и отверг бы урок из расписания — идущая химия сдвинулась бы в каждом варианте.
        """
        settings, answer, biology, chemistry = self.laterStartedProject()

        stage = buildStageSettings(settings, answer, "1")

        self.assertEqual(stage["constants"], {biology: {"0-1": "Биология"}, chemistry: {"2-2": "Химия"}})
        self.assertEqual(pinForecast(settings, answer, "1"), {"pinned": 2, "total": 3, "free": 1, "noTeacher": 0})

    @unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
    def test_solver_keeps_later_started_lesson(self):
        """solve.exe на том же входе ставит оба урока из расписания и печатает те же числа, что прогноз."""
        settings, answer, _, _ = self.laterStartedProject()
        code, _, log, errors = runSolver(buildStageSettings(settings, answer, "1"), iterations=20000)

        self.assertEqual(code, 0, errors)
        self.assertEqual(pinSummary(log), (2, 3, 1, 0), log)
        self.assertNotIn("не поставлен", log)


class SameDayPairsTests(unittest.TestCase):
    """Какие пары курсов решатель старается развести по разным дням."""
    def test_pairs_taken_together(self):
        """Пара курсов попадает в список, если это одна линейка одного потока (оба уровня ЕГЭ — одна
        линейка «ЕГЭ») и их предметы отмечены «нежелательно» или «нельзя»; русский / математика,
        ОГЭ, другой поток, уровни одного предмета и пары «можно» — нет.
        """
        settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {},
                    "soft_subject_pairs": [["Обществознание", "История"], ["Русский язык", "Физика"]],
                    "joint_subject_pairs": [["Химия", "Биология"]]}
        society = addCourse(settings, 1, "ЕГЭ основной", "Обществознание", 2, START)
        history = addCourse(settings, 1, "ЕГЭ основной", "История", 2, START)
        chemistry = addCourse(settings, 1, "ЕГЭ основной", "Химия", 2, START)
        biology = addCourse(settings, 1, "ЕГЭ основной", "Биология", 2, START)
        addCourse(settings, 1, "ЕГЭ основной", "Русский язык", 2, START)
        addCourse(settings, 1, "ЕГЭ основной", "Физика", 2, START)
        advanced = addCourse(settings, 1, "ЕГЭ продвинутый", "История", 2, START)  # другой уровень той же линейки «ЕГЭ»
        addCourse(settings, 1, "ОГЭ", "Обществознание", 1, START)
        addCourse(settings, 2, "ЕГЭ основной", "История", 2, "2026-11-23")  # другой поток

        pairs = buildStageSettings(settings, {}, "1")["custom_penalties_compiled"]["same_day_pairs"]

        self.assertEqual(sorted(tuple(sorted(pair)) for pair in pairs), sorted([tuple(sorted([society, history])), tuple(sorted([society, advanced])), tuple(sorted([chemistry, biology]))]))
        self.assertEqual(buildStageSettings(settings, {}, "2")["custom_penalties_compiled"]["same_day_pairs"], [])


class BlockStageInputTests(unittest.TestCase):
    """Вход решателя для этапов майского марафона и летней школы."""
    def test_finished_streams_do_not_block_teachers(self):
        """Поток идёт до 30.06.2027: в летней школе (июль) его урок не занимает время учителя,
        в майском марафоне — занимает (это «не может» во входе решателя).
        """
        settings = makeSettings()
        settings["calendar_end_date"] = "2027-06-30"

        for group in settings["classes"]["custom_groups"]:
            group["end_date"] = "2027-06-30"

        setSectionStart(settings, "summer", "2027-07-01")
        setSectionEnd(settings, "summer", "2027-08-31")
        setSectionStart(settings, "may", "2027-05-01")
        setSectionEnd(settings, "may", "2027-05-31")
        addCourse(settings, "summer", "ОГЭ", "Математика", 1)
        addCourse(settings, "may", "ОГЭ", "Математика", 1)

        stream_course = stageCourses(settings, "1")[0]
        answer = {stream_course: emptyWeek(5)}
        answer[stream_course][0][0] = lesson("Математика", "Математика #1")

        self.assertNotIn([0, 0], buildStageSettings(settings, answer, "summer")["teachers"]["Математика #1"]["free"])
        self.assertIn([0, 0], buildStageSettings(settings, answer, "may")["teachers"]["Математика #1"]["free"])


class PinForecastTests(unittest.TestCase):
    """Прогноз закреплений этапа (pinForecast) и то, что на самом деле закрепляет вход решателя."""
    def setUp(self):
        """Поток 1: химия уже идёт (2 урока стоят), физика ещё не началась (1 урок из 2 стоит),
        биологии (1 урок) в расписании нет. Курс потока 2 с уроком в расписании — чужой этап.
        """
        self.settings = baseSettings(subjects=[["Химия", 1], ["Физика", 1], ["Биология", 1]],
                                     teachers={"Иванова": teacher("Химия"), "Петров": teacher("Физика"), "Сидорова": teacher("Биология")})
        self.started = addCourse(self.settings, 1, "ОГЭ", "Химия", 2, PAST)
        self.future = addCourse(self.settings, 1, "ОГЭ", "Физика", 2, FUTURE)
        self.absent = addCourse(self.settings, 1, "ОГЭ", "Биология", 1, FUTURE)
        self.other = addCourse(self.settings, 2, "ОГЭ", "Химия", 3, PAST)

        self.answer = {
            self.started: place(place(emptyWeek(5), 0, 0, "Химия", "Иванова"), 2, 0, "Химия", "Иванова"),
            self.future: place(emptyWeek(5), 1, 1, "Физика", "Петров"),
            self.other: place(emptyWeek(5), 4, 2, "Химия", "Иванова"),
        }
        # Галочка «Оставить уже принятые уроки на месте»: курсы этапа, которые есть в расписании
        # (так их выбирает сборка, build._prepareInput)
        self.keep = [self.started, self.future]

    def inputCount(self, keep):
        """Что закрепляет сам вход решателя (buildStageSettings): уроков всего — часы курсов во входе;
        без преподавателя — часы курсов, которых во входе нет в «может вести» ни у кого (так их ищет
        solve.exe); закреплено — у остальных по каждому курсу и предмету не больше его часов.
        """
        stage = buildStageSettings(self.settings, self.answer, "1", keep)
        total = pinned = nobody = 0

        for course, load in stage["classes"]["lessons"].items():
            for subject, hours in load.items():
                fixed = [slot for slot, value in stage.get("constants", {}).get(course, {}).items() if value == subject]
                staffed = any(
                    item["subject"] == subject and course in item["classes"] for data in stage["teachers"].values() for item in data["subjects"]
                )
                total += int(hours)
                pinned += min(int(hours), len(fixed)) if staffed else 0
                nobody += 0 if staffed else int(hours)

        return {"pinned": pinned, "total": total, "free": total - pinned - nobody, "noTeacher": nobody}

    def assertForecast(self, keep, pinned, total, nobody=0):
        """Прогноз этапа 1 — pinned из total, без преподавателя nobody (свободно total − pinned − nobody),
        и вход решателя закрепляет ровно столько же."""
        expected = {"pinned": pinned, "total": total, "free": total - pinned - nobody, "noTeacher": nobody}

        self.assertEqual(pinForecast(self.settings, self.answer, "1", keep), expected)
        self.assertEqual(self.inputCount(keep), expected)

    def test_keep_and_fresh(self):
        """Без галочки закрепляются только уроки идущего курса (2 из 5); с галочкой — и уже стоящий
        урок курса, который ещё не начался (3 из 5). Курс другого этапа не считается.
        """
        self.assertForecast((), 2, 5)
        self.assertForecast(self.keep, 3, 5)
        # Без keep — то же, что пустой keep (так зовут функцию state.stagesInfo и сборка без галочки)
        self.assertEqual(pinForecast(self.settings, self.answer, "1"), pinForecast(self.settings, self.answer, "1", ()))

    def test_manual_pins(self):
        """Ручные закрепления («День и время» на вкладке «Курсы») считаются и без галочки; урок,
        который и закреплён вручную, и стоит в расписании, — один раз; у курса закрепляется не
        больше его часов; закрепления курса другого этапа не считаются.
        """
        self.settings["classes"]["lessons"][self.future]["Физика"] = 3
        self.settings["constants"] = {
            self.future: {"3-1": "Физика"},
            self.absent: {"0-2": "Биология", "4-2": "Биология"},
            self.other: {"0-1": "Химия"},
        }

        # химия 2 + физика 1 (ручное) + биология 1 (из двух ручных — часов 1) из 6
        self.assertForecast((), 4, 6)
        # С галочкой у физики ещё и урок из расписания [1, 1]
        self.assertForecast(self.keep, 5, 6)

        # Урок [1, 1] закреплён и вручную: с галочкой он всё равно один
        self.settings["constants"][self.future]["1-1"] = "Физика"
        self.assertForecast((), 5, 6)
        self.assertForecast(self.keep, 5, 6)

    def test_blocked_started_pin(self):
        """Идущей химии не хватает урока (часов 3); у Ивановой в пн 1-й урок — под уроком химии — «не может».
        Решатель это закрепление не поставит (stages.pinConflicts), урок подберёт программа: закреплено
        на один меньше, чем во входе решателя (там закреплений по-прежнему два).
        """
        self.settings["classes"]["lessons"][self.started]["Химия"] = 3
        markCannot(self.settings, "Иванова", "1", (0, 0))

        self.assertEqual(pinForecast(self.settings, self.answer, "1"), {"pinned": 1, "total": 6, "free": 5, "noTeacher": 0})
        self.assertEqual(self.inputCount(())["pinned"], 2)

    def test_trimmed_pins_and_blocked_lesson(self):
        """Идущей химии (часов 3) вручную закреплены вт и чт 1-й урок сверх её уроков в расписании (пн и ср
        1-й урок), а в пн у Ивановой «не может». Во входе решателя остаются пн, вт и ср (сверх расписания —
        одно закрепление); пн решатель не поставит — закрепится два урока, и прогноз говорит то же.
        """
        self.settings["classes"]["lessons"][self.started]["Химия"] = 3
        self.settings["constants"] = {self.started: {"1-0": "Химия", "3-0": "Химия"}}
        markCannot(self.settings, "Иванова", "1", (0, 0))

        self.assertEqual(sorted(buildStageSettings(self.settings, self.answer, "1")["constants"][self.started]), ["0-0", "1-0", "2-0"])
        self.assertEqual(pinForecast(self.settings, self.answer, "1"), {"pinned": 2, "total": 6, "free": 4, "noTeacher": 0})

    def test_locked_course_blocked_pin(self):
        """Зафиксированная химия (часов 2, оба урока стоят) тоже приходит в решатель с закреплениями: урок
        под «не может» он не поставит — в прогнозе закреплён один её урок из двух.
        """
        markCannot(self.settings, "Иванова", "1", (0, 0))

        self.assertEqual(pinForecast(self.settings, self.answer, "1"), {"pinned": 1, "total": 5, "free": 4, "noTeacher": 0})

    @unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
    def test_solver_counts_rejected_pins(self):
        """solve.exe печатает те же числа, что прогноз, когда закрепления идущей химии встают не все:
        зафиксированная химия с уроком под «не может»; химии не хватает урока, урок под «не может» и
        лишние ручные закрепления; «не может» под ручным закреплением (оно отбрасывается, остаётся другое).
        """
        cases = (
            (2, {}, (0, 0)),
            (3, {"1-0": "Химия", "3-0": "Химия"}, (0, 0)),
            (3, {"1-0": "Химия", "3-0": "Химия"}, (1, 0)),
        )

        for hours, pins, cannot in cases:
            self.setUp()
            self.settings["classes"]["lessons"][self.started]["Химия"] = hours
            self.settings["constants"] = {self.started: dict(pins)}
            markCannot(self.settings, "Иванова", "1", cannot)
            forecast = pinForecast(self.settings, self.answer, "1")
            code, _, log, errors = runSolver(buildStageSettings(self.settings, self.answer, "1"), iterations=100000)

            self.assertEqual(code, 0, errors)
            expected = (forecast["pinned"], forecast["total"], forecast["free"], forecast["noTeacher"])
            self.assertEqual(pinSummary(log), expected, (hours, pins, cannot, log))

    def test_more_lessons_than_hours(self):
        """В расписании у курса уроков больше, чем часов (часы уменьшили после составления):
        закрепляется не больше его часов.
        """
        self.settings["classes"]["lessons"][self.started]["Химия"] = 1
        place(place(self.answer[self.future], 3, 1, "Физика", "Петров"), 4, 1, "Физика", "Петров")

        # химия 1 (из 2 уроков) из 4
        self.assertForecast((), 1, 4)
        # с галочкой у физики 2 (из 3 уроков)
        self.assertForecast(self.keep, 3, 4)

    def test_started_course_without_teacher_is_not_counted(self):
        """Идущий курс, у уроков которого нет преподавателя (или он удалён из проекта), решатель не
        получает (его уроки сервер переносит как есть): его часов нет ни в «всего», ни в «закрепится».
        """
        for teachers in ([], ["Уволена"]):
            for day, number in ((0, 0), (2, 0)):
                self.answer[self.started][day][number]["teachers"] = list(teachers)

            self.assertForecast((), 0, 3)
            self.assertForecast(self.keep, 1, 3)

    def test_course_nobody_can_teach(self):
        """Курс, которого нет в «может вести» и «ведёт» ни у кого: решатель не ставит его уроки, в том
        числе закреплённые, — они идут в «без преподавателя», а не в «подберёт программа». Преподаватель
        из расписания (курс в keep) во входе решателя «ведёт» курс, поэтому с галочкой у курса есть
        преподаватель — если у того ещё есть этот предмет.
        """
        setTeacherCourseState(self.settings, "Сидорова", "Биология", self.absent, "no")
        self.settings["constants"] = {self.absent: {"0-2": "Биология"}}
        # химия 2 из 5, биология (1 час, закреплён вручную) — без преподавателя
        self.assertForecast((), 2, 5, 1)
        self.assertForecast(self.keep, 3, 5, 1)

        # Физику Петрову запретили: без галочки у неё 2 часа без преподавателя, с галочкой Петров
        # стоит на её уроке и «ведёт» её во входе решателя — запрет этого не меняет
        setTeacherCourseState(self.settings, "Петров", "Физика", self.future, "forbidden")
        self.assertForecast((), 2, 5, 3)
        self.assertForecast(self.keep, 3, 5, 1)

        # У Петрова больше нет физики: вести курс некому и с галочкой
        self.settings["teachers"]["Петров"]["subjects"] = []
        self.assertForecast(self.keep, 2, 5, 3)

    def test_other_stage_forecast(self):
        """Этап 2: его единственный курс уже идёт и стоит одним уроком из трёх — закрепится 1 из 3."""
        expected = {"pinned": 1, "total": 3, "free": 2, "noTeacher": 0}
        self.assertEqual(pinForecast(self.settings, self.answer, "2"), expected)
        self.assertEqual(pinForecast(self.settings, self.answer, "2", [self.other]), expected)

    @unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
    def test_solver_prints_the_same_numbers(self):
        """solve.exe на входе этапа печатает «Закреплено N из M уроков, подбирается K[, без преподавателя
        (не ставятся): X]» с теми же числами, что прогноз, — с галочкой и без, с ручными закреплениями
        и без, со всеми преподавателями и когда курсы физики и биологии никто не «может вести»
        (закрепления курсов, у которых есть преподаватель, здесь встают).
        """
        for unstaffed in (False, True):
            if unstaffed:
                setTeacherCourseState(self.settings, "Сидорова", "Биология", self.absent, "no")
                setTeacherCourseState(self.settings, "Петров", "Физика", self.future, "no")

            for pins in ({}, {self.future: {"3-1": "Физика"}, self.absent: {"0-2": "Биология"}}):
                self.settings["constants"] = pins

                for keep in ((), self.keep):
                    forecast = pinForecast(self.settings, self.answer, "1", keep)
                    code, _, log, errors = runSolver(buildStageSettings(self.settings, self.answer, "1", keep), iterations=100000)

                    self.assertEqual(code, 0, errors)
                    expected = (forecast["pinned"], forecast["total"], forecast["free"], forecast["noTeacher"])
                    self.assertEqual(pinSummary(log), expected, (unstaffed, pins, keep, log))

        # Последний прогон — с галочкой: у физики преподаватель из расписания, у биологии — никого
        self.assertEqual(forecast["noTeacher"], 1)


# Будни сетки jointProject (5 дней по 3 урока): цены слотов проверяются только в них
WEEKDAY_SLOTS = [(day, number) for day in range(5) for number in range(3)]


def slotPrices(stage, course):
    """{(день, урок): цена} урока курса ``course`` во входе этапа ``stage`` — сумма всех записей
    ``custom_penalties_compiled.class_slots`` в этом слоте; только будни и только ненулевые цены.
    """
    prices = {}

    for day, number, price in stage["custom_penalties_compiled"]["class_slots"].get(course, []):
        prices[(day, number)] = prices.get((day, number), 0) + price

    return {slot: price for slot, price in prices.items() if slot in WEEKDAY_SLOTS and price}


def blockedSlots(stage):
    """``blocked_slots`` входа этапа без учёта порядка слотов: {курс: [(день, урок)] по порядку}."""
    return {course: sorted(tuple(slot) for slot in slots) for course, slots in stage["blocked_slots"].items()}


class JointCopiesInputTests(unittest.TestCase):
    """Вход движка для потока-копии («Линейка присоединяется к потоку», AC-20, AC-24).

    Проект ``jointProject``: Поток 1 принят, «ЕГЭ основной» Потока 2 присоединена к Потоку 1
    (``markJoint``) — копии Математики (уроки (0, 0), (2, 0) у «Математика #1») и
    Русского языка ((1, 1), (3, 1) у «Русский язык #1») стоят в расписании с уроками источников.
    «Информатика» Потока 2 — обычный курс (в Потоке 1 её нет).
    """
    def setUp(self):
        # «Сегодня» заморожено на 04.10.2026 (``FrozenDate``), как в тестах сервера: Поток 2 начинается
        # 23.11.2026 и ещё не идёт. Без заморозки после 23.11.2026 принятые курсы Потока 2 «уже идут»
        # (courses.py берёт `datetime.date.today()`), закрепляются сами, и прогноз без keep перестаёт быть 0.
        frozen = mock.patch("datetime.date", FrozenDate)
        frozen.start()
        self.addCleanup(frozen.stop)

        self.settings, self.answer = jointProject()
        self.copies = markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        self.math, self.russian = jointCourse(2, "Математика"), jointCourse(2, "Русский язык")
        self.informatics = jointCourse(2, "Информатика")
        self.level_math = jointCourse(2, "Математика", LEVEL_LINE)
        self.level_russian = jointCourse(2, "Русский язык", LEVEL_LINE)
        self.own_math = jointCourse(2, "Математика", OWN_LINE)
        self.weights = readJson(DEFAULT_WEIGHTS, {})

    def separateStreams(self):
        """Поток 1 заканчивается 01.11.2026, до начала Потока 2 (23.11.2026): даты потоков не пересекаются,
        поэтому сами уроки Потока 1 время в Потоке 2 не занимают.
        """
        for course in stageCourses(self.settings, "1"):
            setDates(self.settings, course, JOINT_STARTS[1], "2026-11-01")

    def addHistory(self):
        """«История» в «ЕГЭ основной» Потоков 1 и 2 (в Потоке 1 принята: (4, 1) у «История #1») и
        «Обществознание» только в Потоке 2; отметка ставится заново — «История» Потока 2 тоже копия.
        Возвращает (копия «Истории», «Обществознание» Потока 2).
        """
        source = addCourse(self.settings, 1, JOINT_LINE, "История", 1, JOINT_STARTS[1])
        history = addCourse(self.settings, 2, JOINT_LINE, "История", 1, JOINT_STARTS[2])
        society = addCourse(self.settings, 2, JOINT_LINE, "Обществознание", 1, JOINT_STARTS[2])
        setTeacherSubjects(self.settings, "История #1", ["История"])
        self.answer[source] = courseWeek("История", "История #1", (4, 1))
        self.copies = markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        self.assertEqual(self.copies[history], source)

        return history, society

    def test_copies_are_not_in_solver_input(self):
        """AC-20, AC-24: копий нет во входе движка этапа «2» — ни в курсах, ни в нагрузке, ни в
        закреплениях (даже если они переданы как «оставить принятое»), ни в «может вести» и «ведёт»
        преподавателей. Остальные курсы Потока 2 на месте.
        """
        stage = buildStageSettings(self.settings, self.answer, "2", keep=list(self.answer))

        self.assertCountEqual([group["name"] for group in stage["classes"]["custom_groups"]],
                              [self.informatics, self.level_math, self.level_russian, self.own_math])

        for course in self.copies:
            self.assertNotIn(course, stage["classes"]["lessons"])
            self.assertNotIn(course, stage["constants"])

            for name, data in stage["teachers"].items():
                for item in data["subjects"]:
                    self.assertNotIn(course, item["classes"], name)
                    self.assertNotIn(course, item["assigned"], name)

    def test_copy_lessons_keep_teacher_busy_even_without_date_overlap(self):
        """AC-20: у преподавателя копии слоты её уроков «заняты» в этапе «2» и считаются днями,
        когда он уже приходит, даже если даты Потоков 1 и 2 не пересекаются. Преподаватель курса
        Потока 1 без копии («ЕГЭ продвинутый — Математика») при этом свободен.
        """
        self.separateStreams()
        stage = buildStageSettings(self.settings, self.answer, "2")

        for name, slots, days in (("Математика #1", [[0, 0], [2, 0]], [0, 2]), ("Русский язык #1", [[1, 1], [3, 1]], [1, 3])):
            for slot in slots:
                self.assertIn(slot, stage["teachers"][name]["free"], name)

            self.assertEqual(stage["teacher_busy_days"].get(name), days, name)

        self.assertNotIn([0, 0], stage["teachers"]["Математика #2"]["free"])

    def test_source_and_copy_count_as_one_course_in_teacher_limit(self):
        """AC-20 (и AC-26): в ``existing_courses_by_teacher`` группа «источник + копия» — один курс:
        у «Математика #1» и «Русский язык #1» по одному курсу и при составлении Потока 2, и при
        составлении Потока 3 (где уже стоят и источник, и копия).
        """
        for key in ("2", "3"):
            existing = buildStageSettings(self.settings, self.answer, key)["existing_courses_by_teacher"]

            self.assertEqual(existing.get("Математика #1"), 1, key)
            self.assertEqual(existing.get("Русский язык #1"), 1, key)

    def test_hard_neighbours_of_copy_are_blocked_in_copy_slots(self):
        """AC-20: соседям копии по жёстким правилам слоты копии закрыты (``blocked_slots``), даже если
        даты потоков не пересекаются: «Обществознание» Потока 2 — пара «нельзя» с копией «Истории»
        в той же линейке, «ОГЭ — Математика» — непересекающаяся программа с копией «Математики».
        Другим курсам ничего не закрыто.
        """
        self.settings["non_overlapping_programs"] = [[JOINT_LINE, OWN_LINE]]
        _, society = self.addHistory()
        self.separateStreams()

        stage = buildStageSettings(self.settings, self.answer, "2")

        self.assertEqual(blockedSlots(stage), {society: [(4, 1)], self.own_math: [(0, 0), (2, 0)]})

    def test_soft_rules_with_copy_become_slot_prices(self):
        """AC-20: мягкие правила с копией — цены в ``class_slots`` курсов Потока 2 (веса из weights.json):
        «нежелательно» (softSubjectPair) — в слотах копии для соседа по линейке («Информатика» с обеими
        копиями, второй уровень с копией другого предмета); «уровни врозь» (levelsApart) — курсу-паре
        уровней во всех слотах, кроме слотов копии того же предмета. У «ОГЭ» (другая линейка) цен нет.
        """
        stage = buildStageSettings(self.settings, self.answer, "2", weights=self.weights)
        soft, level = self.weights["softSubjectPair"], self.weights["levelsApart"]
        math, russian = {(0, 0), (2, 0)}, {(1, 1), (3, 1)}

        def levelPrices(own, other):
            """Цены курса-пары уровней: levelsApart вне слотов копии своего предмета (own) и
            softSubjectPair в слотах копии другого предмета (other)."""
            prices = {slot: (0 if slot in own else level) + (soft if slot in other else 0) for slot in WEEKDAY_SLOTS}
            return {slot: price for slot, price in prices.items() if price}

        self.assertEqual(slotPrices(stage, self.informatics), {slot: soft for slot in math | russian})
        self.assertEqual(slotPrices(stage, self.level_math), levelPrices(math, russian))
        self.assertEqual(slotPrices(stage, self.level_russian), levelPrices(russian, math))
        self.assertEqual(slotPrices(stage, self.own_math), {})

    def test_same_day_pair_with_copy_priced_in_copy_days(self):
        """AC-20: «пары не в один день» (pairsSameDay) с копией — цена в днях копии: «Обществознание»
        и «История» отмечены «нежелательно», копия «Истории» стоит в пятницу (4, 1), поэтому у
        «Обществознания» Потока 2 цена pairsSameDay за каждый урок пятницы, а в самом слоте копии
        ещё и softSubjectPair. В другие дни цен нет.
        """
        self.settings["joint_subject_pairs"] = [pair for pair in self.settings["joint_subject_pairs"] if sorted(pair) != ["История", "Обществознание"]]
        self.settings["soft_subject_pairs"].append(["Обществознание", "История"])
        _, society = self.addHistory()

        stage = buildStageSettings(self.settings, self.answer, "2", weights=self.weights)
        soft, same_day = self.weights["softSubjectPair"], self.weights["pairsSameDay"]

        self.assertEqual(slotPrices(stage, society), {(4, 0): same_day, (4, 1): same_day + soft, (4, 2): same_day})

    def test_keep_and_forecast_leave_copies_out(self):
        """AC-24: «оставить принятое» (keep) в потоке-копии: копий нет ни в списке keep, ни в
        закреплениях входа; принятые курсы Потока 2 («ЕГЭ продвинутый — Математика» и «Информатика»)
        закрепляются. Прогноз закреплений этапа тоже без копий: 3 из 6 (часы копий не в счёт).
        """
        self.answer[self.level_math] = courseWeek("Математика", "Математика #2", (1, 0), (3, 0))
        self.answer[self.informatics] = courseWeek("Информатика", "Информатика #1", (4, 1))

        keep = keepCourses(self.settings, self.answer, "2")
        self.assertCountEqual(keep, [self.level_math, self.informatics])

        stage = buildStageSettings(self.settings, self.answer, "2", keep)
        self.assertEqual(stage["constants"], {self.level_math: {"1-0": "Математика", "3-0": "Математика"}, self.informatics: {"4-1": "Информатика"}})

        self.assertEqual(pinForecast(self.settings, self.answer, "2", keep), {"pinned": 3, "total": 6, "free": 3, "noTeacher": 0})
        self.assertEqual(pinForecast(self.settings, self.answer, "2"), {"pinned": 0, "total": 6, "free": 6, "noTeacher": 0})


# Веса прогонов TeacherSwapInputTests: урок Ивановой в часы «может» стоит 300, у Петровой «может» нет
SWAP_WEIGHTS = {"teacherPossibleSlot": 300}
# Прогоны TeacherSwapInputTests: зёрна 1…5, шагов на прогон (маленький вход — доли секунды)
SWAP_SEEDS = range(1, 6)
SWAP_STEPS = 100000


class TeacherSwapInputTests(unittest.TestCase):
    """Смена преподавателя в подборе (.spec/teacher-swap): вход движка этапа и прогон solve.exe.

    Проект ``setUp``: Поток 1, предмет «Математика», кандидаты «может вести» Иванова и Петрова.
    У Ивановой на этапе «1» все часы «может» (каждый её урок — 300), у Петровой «может» нет, поэтому
    с Петровой энергия меньше. Петрова уже ведёт два курса Потока 2 (принятые и идущие), Иванова —
    ни одного, поэтому до отжига курсы этапа «1» достаются Ивановой (у неё меньше курсов).

    * ``started`` (ОГЭ) — идёт, урок (0, 0) у Ивановой;
    * ``kept`` (10 класс) — принят, но не идёт, урок (1, 0) у Ивановой;
    * ``fresh`` (8 класс) — в расписании его нет: его ход вправе отдать Петровой.
    """
    def setUp(self):
        self.settings = baseSettings(subjects=[[SWAP_SUBJECT, 1]], teachers={TEACHER_A: teacher(SWAP_SUBJECT), TEACHER_B: teacher(SWAP_SUBJECT)})
        self.started = addCourse(self.settings, 1, "ОГЭ", SWAP_SUBJECT, 1, PAST)
        self.kept = addCourse(self.settings, 1, "10 класс", SWAP_SUBJECT, 1, FUTURE)
        self.fresh = addCourse(self.settings, 1, "8 класс", SWAP_SUBJECT, 1, FUTURE)
        others = [addCourse(self.settings, 2, line, SWAP_SUBJECT, 1, PAST) for line in ("ОГЭ", "10 класс")]

        teacherAvailability(self.settings["teachers"][TEACHER_A], "1")["possible"] = [[day, number] for day in range(5) for number in range(3)]
        # Пятница у Петровой занята: свободных часов у неё меньше, чем у Ивановой
        teacherAvailability(self.settings["teachers"][TEACHER_B], "1")["free"] = [[4, number] for number in range(3)]

        self.answer = {
            self.started: place(emptyWeek(5), 0, 0, SWAP_SUBJECT, TEACHER_A),
            self.kept: place(emptyWeek(5), 1, 0, SWAP_SUBJECT, TEACHER_A),
            others[0]: place(emptyWeek(5), 2, 1, SWAP_SUBJECT, TEACHER_B),
            others[1]: place(emptyWeek(5), 3, 1, SWAP_SUBJECT, TEACHER_B),
        }

    def runs(self, stage):
        """Ответы solve.exe на входе ``stage`` с весами SWAP_WEIGHTS: [(зерно, ответ)] по SWAP_SEEDS;
        в каждом ответе нет нарушений жёстких правил."""
        result = []

        for seed in SWAP_SEEDS:
            answer, log = solved(self, stage, seed, SWAP_STEPS, SWAP_WEIGHTS)
            self.assertEqual(ruleViolations(stage, answer, log), [], seed)
            result.append((seed, answer))

        return result

    @unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
    def test_started_and_kept_courses_keep_their_teacher(self):
        """AC-4: сборка с галочкой «оставить принятое» (``keepCourses``): у идущего курса и у принятого,
        но не идущего курса во входе непустой «ведёт» — Иванова из расписания; на 5 зёрнах оба курса
        ведёт Иванова, хотя с Петровой энергия меньше (ход 4 их не трогает). В тех же прогонах курс
        ``fresh`` (его нет в расписании) ведёт Петрова: ход 4 есть и на этом входе работает — иначе
        «не тронул» проходило бы и у прежнего движка, где хода нет вовсе.
        """
        keep = keepCourses(self.settings, self.answer, "1")
        self.assertCountEqual(keep, [self.started, self.kept])
        stage = buildStageSettings(self.settings, self.answer, "1", keep)

        self.assertEqual(stage["teachers"][TEACHER_A]["subjects"][0]["assigned"], [self.started, self.kept])
        self.assertEqual(stage["teachers"][TEACHER_B]["subjects"][0]["assigned"], [])

        for seed, answer in self.runs(stage):
            teachers = courseTeachers(answer)

            for course in (self.started, self.kept):
                self.assertEqual(teachers[(course, SWAP_SUBJECT)], {TEACHER_A}, (seed, course))

            self.assertEqual(teachers[(self.fresh, SWAP_SUBJECT)], {TEACHER_B}, ("контроль: ход 4 не сменил Иванову у fresh", seed))

    @unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
    def test_better_teacher_wins_where_move_is_allowed(self):
        """AC-4 (контроль: кандидат Петрова на этом входе и правда лучше). Без галочки «оставить принятое»
        курс ``kept`` на 5 зёрнах ведёт Петрова: он не идёт, «ведёт» у него во входе нет; идущий ``started``
        по-прежнему ведёт Иванова. Прежний движок (без хода 4) оставляет все курсы у Ивановой, выбранной
        до отжига.
        """
        stage = buildStageSettings(self.settings, self.answer, "1")
        self.assertEqual(stage["teachers"][TEACHER_A]["subjects"][0]["assigned"], [self.started])

        for seed, answer in self.runs(stage):
            teachers = courseTeachers(answer)
            self.assertEqual(teachers[(self.started, SWAP_SUBJECT)], {TEACHER_A}, seed)
            self.assertEqual(teachers[(self.kept, SWAP_SUBJECT)], {TEACHER_B}, ("no keep", seed))

    def test_sources_of_joint_lessons_keep_their_teacher(self):
        """AC-6: «ЕГЭ основной» Потока 2 идёт вместе с Потоком 1 — во входе этапа «1» источники копий
        («Математика» и «Русский язык» этой линейки) перечислены в ``keep_teacher_courses``, и только они:
        с принятым Потоком 1 и без него, с галочкой «оставить принятое» и без неё. Все они есть во входе.
        """
        for accepted in (True, False):
            settings, answer = jointProject(accepted=accepted)
            copies = markJoint(settings, 2, JOINT_LINE, 1, answer)
            sources = set(copies.values())
            self.assertEqual(sources, {jointCourse(1, "Математика"), jointCourse(1, "Русский язык")})

            for keep in ((), keepCourses(settings, answer, "1")):
                stage = buildStageSettings(settings, answer, "1", keep)
                courses = {group["name"] for group in stage["classes"]["custom_groups"]}

                self.assertCountEqual(stage.get("keep_teacher_courses", []), sources, (accepted, keep))
                self.assertLessEqual(sources, courses)

    def test_no_joint_lessons_no_keep_teacher_courses(self):
        """AC-6: без потоков-копий в ``keep_teacher_courses`` нет курсов (ключ пустой или его нет) ни на
        одном этапе. После отметки «ЕГЭ основной Потока 2 идёт вместе с Потоком 1» ключ заполнен только
        у этапа источников («1»); у потока-копии (этап «2») и у этапа «3» он по-прежнему пуст — источники
        в другом этапе, копий во входе нет.
        """
        settings, answer = jointProject()

        for key in ("1", "2", "3"):
            self.assertEqual(buildStageSettings(settings, answer, key).get("keep_teacher_courses", []), [], key)

        sources = set(markJoint(settings, 2, JOINT_LINE, 1, answer).values())

        self.assertCountEqual(buildStageSettings(settings, answer, "1").get("keep_teacher_courses", []), sources)

        for key in ("2", "3"):
            self.assertEqual(buildStageSettings(settings, answer, key).get("keep_teacher_courses", []), [], key)
