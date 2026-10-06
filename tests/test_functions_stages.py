"""Этапы составления расписания (`src/modules/functions/stages.py`).

Расписание строится по этапам в порядке дат начала: поток 1, семинары («extra»), поток 2 …
Каждый этап — отдельный запуск решателя; уже составленные этапы «заморожены»: их уроки
передаются как занятость преподавателей, и решатель их не меняет. Отметки времени
преподавателей задаются отдельно для каждого этапа.

* ``StageTests`` — порядок этапов, вход этапа (``buildStageSettings``), закреплённые уроки
  и полное составление всех этапов настоящим solve.exe;
* ``ChangeableCoursesTests``, ``AcceptedStagesTests``, ``StageLessonsTests`` — какие курсы этапа
  сборка ещё может менять, какие этапы приняты, есть ли этап и уроки курса;
* ``StageBuiltTests`` — сколько уроков этапа расставлено и «этап построен» (одно определение
  для стартового экрана и «Запуска»);
* ``BlockStageTests`` — майские марафоны и летняя школа как отдельные этапы: порядок, название,
  занятость преподавателей потоками, которые к блоку закончились;
* ``StageDatesTests`` — даты этапов и пересечение дат курсов;
* ``TeacherTimeTests``, ``TeacherClashTests`` — закреплённое время и накладки преподавателя
  с учётом дат курсов;
* ``PinnedSameStageTests`` — два курса одного этапа с закреплённым уроком в одном слоте:
  решатель не получает это время как «не может», показ склеивает имена через «и»;
* ``JointStageTests`` — «Линейка присоединяется к Потоку N»: общий урок источника и копии —
  не накладка, копии не занимают время в этапе источника, группа «источник + копия» — один
  курс для лимита, сборка не меняет копии;
* ``StaleStartedTests`` — ``staleStarted``: вариант, собранный до начала курса, не сдвигает уроки и не
  меняет преподавателя курсу, который уже идёт, но ещё не получил все уроки;
* ``MovedStartedTests`` — ``movedStarted``: курс шёл уже при сборке, а вариант всё равно сдвинул ему урок
  или сменил преподавателя — найден с причиной («не может», урок другого потока, закреплённый урок
  другого потока, у преподавателя больше нет предмета, смена преподавателя);
* ``BlockedStartedTests`` — ``blockedStarted``: ещё до сборки — какие уроки идущих курсов решатель не сможет
  оставить как в расписании (предупреждение на «Запуске»): так, как их видит решатель (``pinContext``) —
  закрепления по курсам в порядке имён, уроки других этапов в даты всего этапа;
* ``LockedFromAnswerTests`` — ``lockedFromAnswer``: зафиксированные курсы этапа в варианте показываются
  такими, какими их оставит принятие, — из принятого расписания.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import collections
import copy
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from src.modules.functions.courses import addCourse, setSectionEnd, setSectionStart, setTeacherCourseState, setTeacherSubjects
from src.modules.functions.model import EXTRA_BLOCK, datesOverlap, hasLessons, teacherAvailability
from src.modules.functions.solver_input import buildStageSettings
from src.modules.functions.stages import (
    acceptedStages, allStarted, blockedStarted, builtStages, changeableCourses, getStages, lockedFromAnswer, mergeStageAnswer, movedStarted,
    pinnedForTeacher,
    stageBuilt, stageCourses, stageDates, stageExists, stageLabel, stageTotals, staleStarted, teacherClashes, teacherCommitments
)
from tests.builders import (
    JOINT_LINE, LEVEL_LINE, OWN_LINE, SOLVER, baseSettings, chemist, chemistryWeek, courseWeek, emptyWeek, jointCourse, jointProject, lesson,
    makeSettings, markCannot, markJoint, oneLessonWeek, place, setDates, setHours, shiftStream, stageVariant, teacher, weekdaySettings
)
from tests.real_project import FrozenDate

# Курсы проекта builders.jointProject (LockedFromAnswerTests) и даты относительно «сегодня» 04.10.2026
MATH_1, RUS_1, MATH_LEVEL_1 = jointCourse(1, "Математика"), jointCourse(1, "Русский язык"), jointCourse(1, "Математика", LEVEL_LINE)
FUTURE, PAST = "2026-10-12", "2026-09-14"
NEW_TEACHER = "Математика #3"


class StageTests(unittest.TestCase):
    """Этапы составления и входные данные решателя для каждого этапа."""
    def test_stages_follow_start_dates(self):
        """Этапы идут по датам начала: поток 1, семинары, потоки 2–4; в этап семинаров попадают
        только семинары, в этап потока — только его курсы.
        """
        settings = makeSettings()

        self.assertEqual([stage["key"] for stage in getStages(settings)], ["1", EXTRA_BLOCK, "2", "3", "4"])
        self.assertTrue(all(name.startswith("Семинар") for name in stageCourses(settings, EXTRA_BLOCK)))
        self.assertTrue(all(name.startswith("Поток 2 ") for name in stageCourses(settings, "2")))

    def test_stage_input_freezes_other_stages(self):
        """Уроки уже составленного потока 1 становятся занятостью учителя в других этапах и
        блокируют время только для семинаров того же предмета; доступность этапа 2 не влияет на этап 3.
        """
        settings = makeSettings()
        teacherAvailability(settings["teachers"]["Математика #1"], "2")["free"].append([4, 2])

        answer = {name: [[{"subject": "#"}] * 3 for _ in range(5)] for name in stageCourses(settings, "1")}
        course = "Поток 1 — ЕГЭ продвинутый — Математика"
        answer[course] = [[{"subject": "#"}] * 3 for _ in range(5)]
        answer[course][0] = [{"subject": "Математика", "teachers": ["Математика #1"]}] + [{"subject": "#"}] * 2

        stage = buildStageSettings(settings, answer, EXTRA_BLOCK)

        self.assertTrue(all(group["stream_id"] is None for group in stage["classes"]["custom_groups"]))
        self.assertEqual(stage["teachers"]["Математика #1"]["free"], [[0, 0]])
        self.assertEqual(stage["existing_courses_by_teacher"], {"Математика #1": 1})
        # Только семинары по математике обходят время математики ЕГЭ продвинутый потока 1; остальные семинары могут его занять
        self.assertEqual(stage["blocked_slots"], {
            "Семинар ЕГЭ продвинутый: Математика": [[0, 0]],
            "Семинар ОГЭ: Математика": [[0, 0]]
        })

        stage_2 = buildStageSettings(settings, answer, "2")
        self.assertIn([4, 2], stage_2["teachers"]["Математика #1"]["free"])
        self.assertNotIn([4, 2], buildStageSettings(settings, answer, "3")["teachers"]["Математика #1"]["free"])

    def test_pinned_lessons_of_fixed_courses_are_taken(self):
        """Закреплённое время курса, который учитель «ведёт», считается занятым для других этапов
        ещё до составления этого курса; в его собственном этапе оно задаётся закреплением.
        """
        settings = makeSettings()
        course = "Поток 2 — ОГЭ — Физика"
        teacher = settings["teachers"]["Физика #1"]
        teacher["subjects"][0]["assigned"] = [course]
        settings["constants"] = {course: {"3-1": "Физика"}}

        answer = {"Поток 3 — ОГЭ — Физика": [[{"subject": "#"}] * 3, [{"subject": "Физика", "teachers": ["Физика #1"]}] + [{"subject": "#"}] * 2]}

        commitments = teacherCommitments(settings, answer, "Физика #1", "1")
        self.assertEqual(commitments, {(3, 1): ("pinned", course), (1, 0): ("busy", "Поток 3 — ОГЭ — Физика")})

        # Другие этапы учитывают закрепление ещё до составления потока 2; сам поток 2 задаёт его через constants
        self.assertIn([3, 1], buildStageSettings(settings, answer, "1")["teachers"]["Физика #1"]["free"])
        self.assertNotIn([3, 1], buildStageSettings(settings, answer, "2")["teachers"]["Физика #1"]["free"])

    @unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
    def test_generating_all_stages_in_order(self):
        """Реальный запуск solve.exe по всем этапам по очереди: все уроки поставлены, поток 1 не
        меняется последующими этапами, нет накладок учителей, учтена недоступность учителя в этапе 2
        и лимит курсов на учителя. Пропускается, если решатель не собран.
        """
        settings = makeSettings()
        teacherAvailability(settings["teachers"]["Физика #1"], "2")["free"].extend([[0, 0], [0, 1], [0, 2]])
        answer = {}

        with tempfile.TemporaryDirectory() as folder:
            weights = os.path.join(folder, "weights.json")

            with open(weights, "w", encoding="utf-8") as file:
                file.write("{}")

            for stage in getStages(settings):
                source = os.path.join(folder, f"{stage['key']}.json")
                output = os.path.join(folder, f"{stage['key']}.answer.json")

                with open(source, "w", encoding="utf-8") as file:
                    json.dump(buildStageSettings(settings, answer, stage["key"]), file, ensure_ascii=False)

                subprocess.run([
                    SOLVER, "--weights", weights, "--input", source, "--output", output, "--iterations", "200000"
                ], check=True, capture_output=True, timeout=120)

                with open(output, "r", encoding="utf-8") as file:
                    answer = mergeStageAnswer(answer, json.load(file), stage["courses"])

                if stage["key"] == "1":
                    stream_1 = json.loads(json.dumps({name: answer[name] for name in stage["courses"]}))

        self.assertEqual(builtStages(settings, answer), ["1", EXTRA_BLOCK, "2", "3", "4"])

        # Поток 1 учитывается последующими этапами, но никогда ими не меняется
        self.assertEqual({name: answer[name] for name in stream_1}, stream_1)

        groups = {group["name"]: group for group in settings["classes"]["custom_groups"]}
        placed = collections.Counter()
        teacher_slots = collections.Counter()
        programs = collections.defaultdict(set)
        program_subjects = collections.defaultdict(set)

        for course, week in answer.items():
            for day, lessons in enumerate(week):
                for number, cell in enumerate(lessons):
                    if cell.get("subject", "#") == "#":
                        continue

                    placed[(course, cell["subject"])] += 1
                    programs[(day, number)].add(groups[course]["program"])
                    program_subjects[(day, number)].add((groups[course]["program"], cell["subject"]))

                    for person in cell["teachers"]:
                        teacher_slots[(person, day, number)] += 1

                        if person == "Физика #1" and groups[course]["stream_id"] == 2:
                            self.assertNotEqual(day, 0)

        expected = {
            (course, subject): hours
            for course, load in settings["classes"]["lessons"].items()
            for subject, hours in load.items()
            if hours > 0
        }
        self.assertEqual(dict(placed), expected)

        # По всем этапам вместе: у учителя один урок на слот,
        # семинар не совпадает по времени с ЕГЭ продвинутым по своему предмету
        self.assertEqual(max(teacher_slots.values()), 1)
        self.assertFalse([
            slot for slot, items in program_subjects.items()
            for program, subject in items
            if program == "Семинары" and ("ЕГЭ продвинутый", subject) in items
        ])

        courses = collections.defaultdict(set)

        for course, week in answer.items():
            for day in week:
                for cell in day:
                    for person in cell.get("teachers", []):
                        courses[person].add(course)

        self.assertLessEqual(max(len(items) for items in courses.values()), settings["max_courses_per_teacher"])


class ChangeableCoursesTests(unittest.TestCase):
    """Какие курсы этапа сборка ещё может менять и когда менять нечего."""
    def setUp(self):
        """Этап 1 из трёх курсов: «Химия» идёт и все уроки на месте (зафиксирован), «Биология» идёт,
        но одного урока не хватает, «Физика» ещё не началась.
        """
        self.settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}}
        self.chemistry = addCourse(self.settings, 1, "ОГЭ", "Химия", 1, "2020-09-01")
        self.biology = addCourse(self.settings, 1, "ОГЭ", "Биология", 2, "2020-09-01")
        self.physics = addCourse(self.settings, 1, "ОГЭ", "Физика", 1, "2999-09-01")
        week = [[{"subject": "#", "teachers": []} for _ in range(3)] for _ in range(5)]
        self.answer = {name: json.loads(json.dumps(week)) for name in (self.chemistry, self.biology, self.physics)}
        self.answer[self.chemistry][0][0] = {"subject": "Химия", "teachers": ["X"]}
        self.answer[self.biology][1][0] = {"subject": "Биология", "teachers": ["Y"]}
        self.answer[self.physics][2][0] = {"subject": "Физика", "teachers": ["Z"]}

    def test_changeable_courses_keep_project_order(self):
        """Без зафиксированных — для принятия варианта; без всех идущих — для «Убрать из расписания»;
        порядок — как в проекте.
        """
        self.assertEqual(changeableCourses(self.settings, self.answer, "1"), [self.biology, self.physics])
        self.assertEqual(changeableCourses(self.settings, self.answer, "1", complete=False), [self.physics])
        self.assertEqual(changeableCourses(self.settings, self.answer, "9"), [])

    def test_all_started(self):
        """«Все курсы идут» — только когда зафиксирован каждый курс этапа; у пустого этапа — нет."""
        self.assertFalse(allStarted(self.settings, self.answer, "1"))
        self.assertFalse(allStarted(self.settings, self.answer, "9"))

        self.settings["classes"]["custom_groups"] = self.settings["classes"]["custom_groups"][:1]
        self.assertTrue(allStarted(self.settings, self.answer, "1"))


class AcceptedStagesTests(unittest.TestCase):
    """Какие этапы считаются «принятыми» (есть в answer.json)."""
    def test_partly_placed_stage_counts_as_accepted(self):
        """Этап, где поставлена хотя бы часть уроков, считается принятым (хотя и не «составленным
        полностью»), а пустое расписание не даёт ни одного принятого этапа.
        """
        settings = makeSettings()
        course = stageCourses(settings, "1")[0]
        week = [[{"subject": "#", "teachers": []} for _ in range(3)] for _ in range(5)]
        week[0][0] = {"subject": settings["classes"]["custom_groups"][0]["subjects"][0], "teachers": ["X"]}

        answer = {course: week}

        # Из всего этапа поставлен один урок: не «составлен», но принят
        self.assertNotIn("1", builtStages(settings, answer))
        self.assertEqual(acceptedStages(settings, answer), ["1"])
        self.assertEqual(acceptedStages(settings, {}), [])


class StageBuiltTests(unittest.TestCase):
    """stageTotals / stageBuilt / builtStages: «этап построен» считается одним способом."""
    def settings(self, hours_a=2, hours_b=1):
        """Этап «1» из курсов A (химия) и B (физика) с нагрузкой ``hours_a`` и ``hours_b``."""
        groups = [{"name": name, "program": "ОГЭ", "subjects": [subject], "stream_id": 1} for name, subject in (("A", "Химия"), ("B", "Физика"))]

        return {"classes": {"custom_groups": groups, "lessons": {"A": {"Химия": hours_a}, "B": {"Физика": hours_b}}}}

    def test_totals_do_not_count_extra_lessons(self):
        """Нужно 3 урока: у A стоит 3 из 2 (лишний не засчитывается), у B — 0 из 1: расставлено 2."""
        answer = {"A": chemistryWeek((0, 0), (1, 0), (2, 0))}

        self.assertEqual(stageTotals(self.settings(), answer, ["A", "B"]), (3, 2))
        self.assertFalse(stageBuilt(self.settings(), answer, "1"))

    def test_built_when_all_lessons_are_placed(self):
        """Все уроки на месте — этап построен; без расписания или с неизвестным этапом — нет."""
        answer = {"A": chemistryWeek((0, 0), (1, 0)), "B": chemistryWeek((2, 1))}

        self.assertTrue(stageBuilt(self.settings(), answer, "1"))
        self.assertEqual(builtStages(self.settings(), answer), ["1"])
        self.assertFalse(stageBuilt(self.settings(), {}, "1"))
        self.assertFalse(stageBuilt(self.settings(), answer, "2"))

    def test_zero_hour_stage_is_built_only_with_lessons(self):
        """У всех курсов 0 уроков: этап построен, только если его уроки всё же стоят в расписании —
        одинаково для стартового экрана и вкладки «Запуск» (раньше они расходились).
        """
        settings = self.settings(0, 0)

        self.assertFalse(stageBuilt(settings, {}, "1"))
        self.assertTrue(stageBuilt(settings, {"A": chemistryWeek((0, 0))}, "1"))


class BlockStageTests(unittest.TestCase):
    """Майские марафоны и летняя школа — отдельные этапы в конце учебного года."""
    def test_block_courses_form_their_own_stages(self):
        """Курсы марафона и летней школы — отдельные этапы после потоков и семинаров; название
        этапа блока — перевод его ключа.
        """
        settings = makeSettings()
        settings["calendar_end_date"] = "2027-06-30"

        may = addCourse(settings, "may", "ЕГЭ основной", "Математика", 3)
        addCourse(settings, "summer", "ОГЭ", "Математика", 2)

        self.assertEqual([stage["key"] for stage in getStages(settings)][-2:], ["may", "summer"])
        self.assertEqual(stageCourses(settings, "may"), [may])
        self.assertNotIn(may, stageCourses(settings, EXTRA_BLOCK))
        self.assertEqual(stageLabel("summer", lambda key: {"stage.summer": "Летняя школа"}.get(key, key)), "Летняя школа")

    def test_finished_streams_do_not_block_teachers(self):
        """Уроки потока, который закончился к началу летней школы, не занимают время учителя в ней;
        поток, который ещё идёт в мае, занимает его время в майском марафоне.
        """
        settings = blockSettings()
        stream_course = stageCourses(settings, "1")[0]
        answer = {stream_course: chemistryWeek((0, 0))}
        answer[stream_course][0][0] = {"subject": "Математика", "teachers": ["Математика #1"]}

        self.assertIn((0, 0), teacherCommitments(settings, answer, "Математика #1", "may"))
        self.assertNotIn((0, 0), teacherCommitments(settings, answer, "Математика #1", "summer"))


def blockSettings():
    """Стандартная программа, где все потоки идут до 30.06.2027, с курсом математики ОГЭ в майском
    марафоне (май 2027) и в летней школе (июль–август 2027).
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

    return settings


class StageLessonsTests(unittest.TestCase):
    """Есть ли в проекте этап и есть ли у курса уроки в расписании."""
    def test_stage_exists(self):
        """Этап есть, если в проекте есть хотя бы один курс этого потока или блока."""
        settings = makeSettings()

        for stage in ("1", "extra", "4"):
            self.assertTrue(stageExists(settings, stage), stage)

        for stage in ("99", "", None, 1):
            self.assertFalse(stageExists(settings, stage), stage)

    def test_has_lessons(self):
        """Курс с хотя бы одним уроком — да; пустая неделя или курса нет в расписании — нет."""
        answer = {"первый": chemistryWeek((4, 2)), "пустой": emptyWeek()}

        self.assertTrue(hasLessons(answer, "первый"))
        self.assertFalse(hasLessons(answer, "пустой"))
        self.assertFalse(hasLessons(answer, "нет такого"))


class StageDatesTests(unittest.TestCase):
    """Даты этапов и пересечение дат курсов."""
    def test_stage_starts_at_earliest_course(self):
        """Старт этапа — самая ранняя дата его курсов, и по ней этапы упорядочены."""
        settings = {"classes": {"custom_groups": [
            {"name": "А", "stream_id": 1, "start_date": "2026-09-07"},
            {"name": "Б", "stream_id": 1, "start_date": "2026-08-01"},
            {"name": "В", "stream_id": 2, "start_date": "2026-08-15"}
        ]}}

        stages = getStages(settings)

        self.assertEqual([stage["key"] for stage in stages], ["1", "2"])
        self.assertEqual(stages[0]["start"], "2026-08-01")
        self.assertEqual(stages[0]["courses"], ["А", "Б"])

    def test_dates_touching_on_one_day_overlap(self):
        """Курс начинается в день окончания другого: промежутки пересекаются (границы включительно),
        и уроки одного преподавателя в одно время у них — накладка; на день позже — нет.
        """
        self.assertTrue(datesOverlap(("2026-10-01", "2026-10-31"), ("2026-09-01", "2026-10-01")))
        self.assertTrue(datesOverlap(("2026-09-01", "2026-10-01"), ("2026-10-01", "2026-10-31")))
        self.assertFalse(datesOverlap(("2026-10-02", "2026-10-31"), ("2026-09-01", "2026-10-01")))

        settings = {"classes": {"custom_groups": [
            {"name": "А", "stream_id": 1, "start_date": "2026-09-01", "end_date": "2026-10-01"},
            {"name": "Б", "stream_id": 2, "start_date": "2026-10-01", "end_date": "2026-10-31"}
        ]}}
        answer = {"А": emptyWeek(5), "Б": emptyWeek(5)}
        answer["А"][0][0] = lesson("Химия", "Иванова")
        answer["Б"][0][0] = lesson("Химия", "Иванова")

        self.assertEqual(teacherClashes(settings, answer), [("Иванова", 0, 0, ["А", "Б"])])

        settings["classes"]["custom_groups"][1]["start_date"] = "2026-10-02"
        self.assertEqual(teacherClashes(settings, answer), [])


class TeacherTimeTests(unittest.TestCase):
    """Закреплённое время и накладки преподавателя с учётом дат курсов."""
    def setUp(self):
        """Курсы химии A и B потока 1 (сентябрь–октябрь) и C потока 2 (январь–март); Иванова ведёт все три."""
        self.settings = baseSettings(teachers={"Иванова": teacher("Химия")})
        self.a = addCourse(self.settings, 1, "ОГЭ", "Химия", 1, "2026-09-01")
        self.b = addCourse(self.settings, 1, "ЕГЭ основной", "Химия", 1, "2026-09-01")
        self.c = addCourse(self.settings, 2, "ОГЭ", "Химия", 1, "2027-01-01")

        setDates(self.settings, self.a, "2026-09-01", "2026-10-31")
        setDates(self.settings, self.b, "2026-09-01", "2026-10-31")
        setDates(self.settings, self.c, "2027-01-01", "2027-03-31")

        self.settings["teachers"]["Иванова"]["subjects"][0]["assigned"] = [self.a, self.b, self.c]
        self.settings["constants"] = {
            self.a: {"0-0": "Химия", "1-1": "Физика"},
            self.b: {"0-0": "Химия"},
            self.c: {"2-2": "Химия"},
        }

    def test_pinned_time_by_stage_dates(self):
        """Закреплённое время — только курсы с датами этапа и только по предмету преподавателя;
        два курса в одном слоте — список из обоих (склеивает их через «и» только показ).
        """
        self.assertEqual(pinnedForTeacher(self.settings, "Иванова", "1"), {(0, 0): [self.a, self.b]})
        self.assertEqual(pinnedForTeacher(self.settings, "Иванова", "2"), {(2, 2): [self.c]})
        self.assertEqual(pinnedForTeacher(self.settings, "Нет такого", "1"), {})

    def test_stage_without_courses_has_open_dates(self):
        """У этапа без курсов даты не ограничены."""
        self.assertEqual(stageDates(self.settings, "9"), ("0000-00-00", "9999-99-99"))
        self.assertEqual(stageDates(self.settings, "1"), ("2026-09-01", "2026-10-31"))

    def test_clashes_ignore_removed_courses(self):
        """Урок курса, которого уже нет в настройках, накладкой не считается; курс тех же дат — считается."""
        lesson = place(emptyWeek(5), 0, 0, "Химия", "Иванова")
        answer = {self.a: lesson, "Удалённый курс": place(emptyWeek(5), 0, 0, "Химия", "Иванова")}

        self.assertEqual(teacherClashes(self.settings, answer), [])

        answer[self.b] = place(emptyWeek(5), 0, 0, "Химия", "Иванова")
        self.assertEqual(teacherClashes(self.settings, answer), [("Иванова", 0, 0, [self.a, self.b])])


class PinnedSameStageTests(unittest.TestCase):
    """Два доп. курса одного этапа, оба за Ивановой, урок обоих закреплён на пн, 1-й урок."""
    def setUp(self):
        """Курсы сен–окт и ноя–дек: в одно время они не идут, поэтому закрепления не мешают друг другу."""
        self.settings = weekdaySettings()
        self.first = addCourse(self.settings, "extra", "Семинар ОГЭ", "Химия", 1)
        self.second = addCourse(self.settings, "extra", "Семинар ЕГЭ продвинутый", "Химия", 1)
        setDates(self.settings, self.first, "2026-09-01", "2026-10-31")
        setDates(self.settings, self.second, "2026-11-01", "2026-12-31")
        self.settings["teachers"]["Иванова"] = chemist(self.first, self.second, assigned=[self.first, self.second])
        self.settings["constants"] = {self.first: {"0-0": "Химия"}, self.second: {"0-0": "Химия"}}

    def test_own_stage_pins_are_not_cannot(self):
        """Закреплённое время своих курсов этапа решатель не получает как «не может»."""
        self.assertEqual(pinnedForTeacher(self.settings, "Иванова", "extra"), {(0, 0): [self.first, self.second]})

        result = buildStageSettings(self.settings, {}, "extra")
        self.assertNotIn([0, 0], result["teachers"]["Иванова"]["free"])

    def test_commitments_join_names_only_for_display(self):
        """На вкладке «Преподаватели» оба курса пишутся через «и»; урок другого этапа в том же
        слоте показывается «занят» один раз, без повтора своего имени.
        """
        self.assertEqual(teacherCommitments(self.settings, {}, "Иванова", "extra"), {(0, 0): ("pinned", f"{self.first} и {self.second}")})

        other = addCourse(self.settings, 1, "ОГЭ", "Химия", 1)
        setDates(self.settings, other, "2026-09-01", "2026-12-31")
        answer = {other: emptyWeek(5)}
        answer[other][0][0] = lesson("Химия", "Иванова")

        self.assertEqual(teacherCommitments(self.settings, answer, "Иванова", "extra"), {(0, 0): ("busy", f"{other} и {self.first} и {self.second}")})


class TeacherClashTests(unittest.TestCase):
    """Один учитель на двух уроках в одно время — накладка, только если даты курсов пересекаются."""
    def test_clash_needs_overlapping_dates(self):
        """Один учитель в одно время у потоков 1 и 2 — накладка, пока даты потоков пересекаются;
        если поток 1 заканчивается до начала потока 2, то же время допустимо.
        """
        settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}}
        first = addCourse(settings, 1, "ОГЭ", "Физика", 1, "2026-09-07")
        second = addCourse(settings, 2, "ОГЭ", "Физика", 1, "2026-11-23")
        answer = {first: oneLessonWeek("Физика"), second: oneLessonWeek("Физика")}

        self.assertEqual(teacherClashes(settings, answer), [("Иванова Анна", 0, 0, [first, second])])

        # Поток 1 заканчивается до начала потока 2: одно и то же время допустимо
        for group in settings["classes"]["custom_groups"]:
            if group["name"] == first:
                group["end_date"] = "2026-11-22"

        self.assertEqual(teacherClashes(settings, answer), [])


class JointStageTests(unittest.TestCase):
    """«ЕГЭ основной» Потока 2 идёт вместе с Потоком 1 (проект ``jointProject``, «сегодня» 04.10.2026):
    копии Математики и Русского языка стоят в тех же часах и у тех же преподавателей, что в
    принятом Потоке 1 («Математика #1» — пн и ср первым уроком).
    """
    def setUp(self):
        frozen = mock.patch("datetime.date", FrozenDate)
        frozen.start()
        self.addCleanup(frozen.stop)

        self.settings, self.answer = jointProject()
        self.copies = markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        self.source, self.copy = jointCourse(1, "Математика"), jointCourse(2, "Математика")

    def test_shared_lesson_is_not_a_clash(self):
        """AC-27: источник и копия у одного преподавателя в одном слоте при пересекающихся датах —
        не накладка; третий курс того же преподавателя в слоте копии — накладка у копии и у него.
        """
        self.assertEqual(teacherClashes(self.settings, self.answer), [])
        self.assertEqual(teacherClashes(self.settings, self.answer, "Математика #1"), [])

        third = jointCourse(2, "Математика", OWN_LINE)
        self.answer[third] = courseWeek("Математика", "Математика #1", (0, 0))
        clashes = teacherClashes(self.settings, self.answer)

        self.assertEqual([(name, day, lesson) for name, day, lesson, _ in clashes], [("Математика #1", 0, 0)])
        self.assertIn(self.copy, clashes[0][3])
        self.assertIn(third, clashes[0][3])

    def test_copies_do_not_occupy_source_stage(self):
        """AC-23: Поток 2 с копиями принят, составляется Поток 1 — уроки копий не дают преподавателю
        «занят» в сетке Потока 1, не попадают во вход движка как «не может» и как лишний курс:
        Поток 1 может оставить свои уроки на месте.
        """
        busy = [slot for slot, (kind, _) in teacherCommitments(self.settings, self.answer, "Математика #1", "1").items() if kind == "busy"]
        self.assertEqual(busy, [])

        stage = buildStageSettings(self.settings, self.answer, "1")

        for slot in ([0, 0], [2, 0]):
            self.assertNotIn(slot, stage["teachers"]["Математика #1"]["free"])

        for slot in ([1, 1], [3, 1]):
            self.assertNotIn(slot, stage["teachers"]["Русский язык #1"]["free"])

        self.assertEqual(stage["existing_courses_by_teacher"].get("Математика #1", 0), 0)
        self.assertEqual(stage["existing_courses_by_teacher"].get("Русский язык #1", 0), 0)

    def test_source_and_copy_are_one_course_for_third_stream(self):
        """AC-26: составляется Поток 3 — у преподавателя источника и копии в
        ``existing_courses_by_teacher`` один курс, а не два (лимит не съеден двойным счётом).
        """
        stage = buildStageSettings(self.settings, self.answer, "3")

        self.assertEqual(stage["existing_courses_by_teacher"], {
            "Математика #1": 1, "Математика #2": 1, "Русский язык #1": 1, "Русский язык #2": 1, "Биология #1": 1,
        })

    def test_copies_are_not_changeable(self):
        """AC-25: сборка Потока 2 не меняет копии — в ``changeableCourses`` их нет (ни для принятия
        варианта, ни для «Убрать из расписания»), обычные курсы этапа остаются в порядке проекта.
        """
        own = [course for course in stageCourses(self.settings, "2") if course not in self.copies]

        self.assertEqual(len(self.copies), 2)
        self.assertEqual(changeableCourses(self.settings, self.answer, "2"), own)
        self.assertEqual(changeableCourses(self.settings, self.answer, "2", complete=False), own)


class StartedCase(unittest.TestCase):
    """Проект ``jointProject``, «сегодня» 04.10.2026: Поток 1 идёт; у «Математики» Потока 1 (``MATH_1``,
    «Математика #1», пн и ср 1-й урок) нагрузку подняли до 3 — курс идёт, но ему не хватает урока,
    поэтому принятие берёт его из варианта. Общая подготовка ``StaleStartedTests`` и ``MovedStartedTests``.
    """
    MATH_1, MATH_2 = jointCourse(1, "Математика"), jointCourse(2, "Математика")
    OLD_TEACHER, NEW_TEACHER = "Математика #1", "Математика #3"

    def setUp(self):
        frozen = mock.patch("datetime.date", FrozenDate)
        frozen.start()
        self.addCleanup(frozen.stop)
        self.settings, self.answer = jointProject()
        setHours(self.settings, self.MATH_1, 3)

    def leaveWithoutTeacher(self):
        """У ``OLD_TEACHER`` больше нет математики, и «может вести» ``MATH_1`` никто: курс некому вести."""
        setTeacherSubjects(self.settings, self.OLD_TEACHER, [])

        for data in self.settings["teachers"].values():
            for item in data["subjects"]:
                item["classes"] = [name for name in item.get("classes", []) if name != self.MATH_1]


class StaleStartedTests(StartedCase):
    """``staleStarted`` на проекте ``StartedCase``."""
    def stale(self, **weeks):
        """``staleStarted`` Потока 1 для варианта, где у курсов ``weeks`` свои недели."""
        return staleStarted(self.settings, self.answer, "1", stageVariant(self.settings, self.answer, **weeks))

    def test_moved_lessons_are_stale(self):
        """Вариант собран до начала: у ``MATH_1`` другие часы — курс найден."""
        week = courseWeek("Математика", self.OLD_TEACHER, (1, 0), (3, 0), (4, 0))

        self.assertEqual(self.stale(**{self.MATH_1: week}), [self.MATH_1])

    def test_other_teacher_is_stale(self):
        """Часы те же, но у недостающего урока другой преподаватель — курс найден."""
        week = courseWeek("Математика", self.OLD_TEACHER, (0, 0), (2, 0))
        week[4][0] = {"subject": "Математика", "teachers": [self.NEW_TEACHER]}

        self.assertEqual(self.stale(**{self.MATH_1: week}), [self.MATH_1])

    def test_fresh_variant_passes(self):
        """Как собирает свежая сборка (pinPlan): уроки из расписания на месте, тот же преподаватель,
        недостающий урок добавлен — ничего не найдено.
        """
        week = courseWeek("Математика", self.OLD_TEACHER, (0, 0), (2, 0), (4, 0))

        self.assertEqual(self.stale(**{self.MATH_1: week}), [])

    def test_deleted_teacher_is_not_refused(self):
        """``OLD_TEACHER`` удалили после сборки: в расписании у курса не осталось преподавателя из
        проекта — сверяется только время, а оно то же.
        """
        del self.settings["teachers"][self.OLD_TEACHER]
        week = courseWeek("Математика", self.NEW_TEACHER, (0, 0), (2, 0), (4, 0))

        self.assertEqual(self.stale(**{self.MATH_1: week}), [])

    def test_joined_source_with_started_copy(self):
        """Поток 1 ещё не начался, его копия в Потоке 2 уже идёт, обоим не хватает урока: источник
        менять нельзя — вариант, который двигает ``MATH_1``, найден.
        """
        shiftStream(self.settings, 1, "2026-10-12")
        shiftStream(self.settings, 2, "2026-09-14")
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        setHours(self.settings, self.MATH_2, 3)
        week = courseWeek("Математика", self.NEW_TEACHER, (1, 0), (3, 0), (4, 0))

        self.assertEqual(self.stale(**{self.MATH_1: week}), [self.MATH_1])

    def test_course_started_at_build_is_not_stale(self):
        """``built`` — курсы, которые шли уже при сборке (variants.buildStarted): вариант для них не «собран
        до начала» (их сдвиг ищет ``movedStarted``). Другие идущие курсы проверяются.
        """
        week = courseWeek("Математика", self.NEW_TEACHER, (1, 0), (3, 0), (4, 0))
        variant = stageVariant(self.settings, self.answer, **{self.MATH_1: week})

        self.assertEqual(staleStarted(self.settings, self.answer, "1", variant, built={self.MATH_1}), [])
        self.assertEqual(staleStarted(self.settings, self.answer, "1", variant, built=set()), [self.MATH_1])


class MovedStartedTests(StartedCase):
    """``movedStarted``: тот же проект, но ``MATH_1`` шёл уже при сборке (``built``). Сборка закрепляла его
    уроки (пн и ср 1-й урок) и преподавателя ``OLD_TEACHER``; если вариант их всё же поменял, курс найден
    с причиной для каждого сдвинутого урока — такой вариант не принимается (решение заказчика 06.10.2026).
    """
    def moved(self, week, built=True):
        """``movedStarted`` Потока 1 для варианта, где у ``MATH_1`` неделя ``week``; ``built`` — шёл при сборке."""
        variant = stageVariant(self.settings, self.answer, **{self.MATH_1: week})

        return movedStarted(self.settings, self.answer, "1", variant, {self.MATH_1} if built is True else built)

    def test_cannot_is_named(self):
        """У ``OLD_TEACHER`` на этапе отмечено «не может» в пн 1-й урок, решатель увёл урок на вт: причина
        "unavailable" с преподавателем; урок ср на месте — не назван.
        """
        markCannot(self.settings, self.OLD_TEACHER, "1", (0, 0))
        week = courseWeek("Математика", self.OLD_TEACHER, (1, 0), (2, 0), (4, 0))

        self.assertEqual(self.moved(week), [(self.MATH_1, [(0, 0, "unavailable", self.OLD_TEACHER)])])

    def test_other_stage_lesson_is_named(self):
        """В пн 1-й урок у ``OLD_TEACHER`` урок Потока 2 (даты потоков пересекаются): причина "busy" с этим курсом.
        Урок там же и закреплён вручную — он уже назван "busy", второй раз ("elsewhere") не повторяется.
        """
        math_2 = jointCourse(2, "Математика")
        self.answer[math_2] = courseWeek("Математика", self.OLD_TEACHER, (0, 0))
        setTeacherCourseState(self.settings, self.OLD_TEACHER, "Математика", math_2, "assigned")
        self.settings["constants"][math_2] = {"0-0": "Математика"}
        week = courseWeek("Математика", self.OLD_TEACHER, (1, 0), (2, 0), (4, 0))

        self.assertEqual(self.moved(week), [(self.MATH_1, [(0, 0, "busy", math_2)])])

    def test_pin_of_other_stage_is_named(self):
        """В пн 1-й урок у ``OLD_TEACHER`` закреплён вручную урок Потока 2, которого в это время нет в расписании
        (решатель считает это время занятым): причина "elsewhere" с этим курсом.
        """
        setTeacherCourseState(self.settings, self.OLD_TEACHER, "Математика", self.MATH_2, "assigned")
        self.settings["constants"][self.MATH_2] = {"0-0": "Математика"}
        week = courseWeek("Математика", self.OLD_TEACHER, (1, 0), (2, 0), (4, 0))

        self.assertEqual(self.moved(week), [(self.MATH_1, [(0, 0, "elsewhere", self.MATH_2)])])

    def test_no_teacher_left_is_named(self):
        """Курс некому вести (решатель его уроки не ставит): одна строка "noteacher" на первом сдвинутом уроке."""
        self.leaveWithoutTeacher()

        self.assertEqual(self.moved(courseWeek("Математика", self.OLD_TEACHER)), [(self.MATH_1, [(0, 0, "noteacher", self.OLD_TEACHER)])])

    def test_lost_subject_is_named(self):
        """У ``OLD_TEACHER`` больше нет математики, а «может вести» курс другой: вариант с тем же временем
        у другого преподавателя — причина "lostsubject" с ``OLD_TEACHER`` на первом уроке, а не "teacher".
        """
        setTeacherSubjects(self.settings, self.OLD_TEACHER, [])
        week = courseWeek("Математика", self.NEW_TEACHER, (0, 0), (2, 0), (4, 0))

        self.assertEqual(self.moved(week), [(self.MATH_1, [(0, 0, "lostsubject", self.OLD_TEACHER)])])

    def test_lost_subject_names_first_answer_lesson(self):
        """Строка "lostsubject" — на первом уроке курса в расписании, как в предупреждении «Запуска»
        (``blockedStarted``), даже если вариант сдвинул только второй урок (ср → вт).
        """
        setTeacherSubjects(self.settings, self.OLD_TEACHER, [])
        week = courseWeek("Математика", self.NEW_TEACHER, (0, 0), (1, 0), (4, 0))

        self.assertEqual(self.moved(week), [(self.MATH_1, [(0, 0, "lostsubject", self.OLD_TEACHER)])])

    def test_rebuilt_course_is_not_an_obstacle(self):
        """Курс этапа, который ещё не начался, сборка расставляет заново: его урок в расписании на прежнем
        месте — не помеха ("unplaced", а не "busy").
        """
        level = jointCourse(1, "Математика", LEVEL_LINE)
        next(group for group in self.settings["classes"]["custom_groups"] if group["name"] == level)["start_date"] = FUTURE
        self.answer[level] = courseWeek("Математика", self.OLD_TEACHER, (0, 0))
        week = courseWeek("Математика", self.OLD_TEACHER, (1, 0), (2, 0), (4, 0))

        self.assertEqual(self.moved(week), [(self.MATH_1, [(0, 0, "unplaced", "")])])

    def test_unknown_reason(self):
        """Помехи на прежнем месте нет: причина "unplaced" (программа не смогла оставить урок)."""
        week = courseWeek("Математика", self.OLD_TEACHER, (1, 0), (3, 0), (4, 0))

        self.assertEqual(self.moved(week), [(self.MATH_1, [(0, 0, "unplaced", ""), (2, 0, "unplaced", "")])])

    def test_other_teacher_is_named(self):
        """Часы те же, недостающий урок у другого преподавателя: причина "teacher" с прежним преподавателем
        на первом таком уроке.
        """
        week = courseWeek("Математика", self.OLD_TEACHER, (0, 0), (2, 0))
        place(week, 4, 0, "Математика", self.NEW_TEACHER)

        self.assertEqual(self.moved(week), [(self.MATH_1, [(4, 0, "teacher", self.OLD_TEACHER)])])

    def test_fresh_or_not_built_passes(self):
        """Уроки и преподаватель на месте — ничего; курс не шёл при сборке (его проверяет staleStarted)
        или сборка старой программы (``built`` None) — тоже ничего.
        """
        moved = courseWeek("Математика", self.NEW_TEACHER, (1, 0), (3, 0), (4, 0))

        self.assertEqual(self.moved(courseWeek("Математика", self.OLD_TEACHER, (0, 0), (2, 0), (4, 0))), [])
        self.assertEqual(self.moved(moved, built=set()), [])
        self.assertEqual(self.moved(moved, built=None), [])


class BlockedStartedTests(StartedCase):
    """``blockedStarted`` на проекте ``StartedCase``: ещё до сборки — уроки идущих курсов, которые решатель
    не сможет оставить на месте; каждый вариант их сдвинет, и принять его будет нельзя (``movedStarted``).
    """
    def blocked(self):
        """``blockedStarted`` Потока 1."""
        return blockedStarted(self.settings, self.answer, "1")

    def test_cannot_is_named(self):
        """«Не может» у ``OLD_TEACHER`` в пн 1-й урок — под уроком ``MATH_1``: урок назван с причиной."""
        markCannot(self.settings, self.OLD_TEACHER, "1", (0, 0))

        self.assertEqual(self.blocked(), [(self.MATH_1, [(0, 0, "unavailable", self.OLD_TEACHER)])])

    def test_no_teacher_left(self):
        """Курс некому вести — одна строка "noteacher" на первом уроке."""
        self.leaveWithoutTeacher()

        self.assertEqual(self.blocked(), [(self.MATH_1, [(0, 0, "noteacher", self.OLD_TEACHER)])])

    def test_lost_subject_with_candidates(self):
        """У ``OLD_TEACHER`` больше нет математики, но «может вести» курс другой: решатель отдаст курс ему, и
        каждый вариант сменит преподавателя идущего курса — одна строка "lostsubject" на первом уроке.
        """
        setTeacherSubjects(self.settings, self.OLD_TEACHER, [])

        self.assertEqual(self.blocked(), [(self.MATH_1, [(0, 0, "lostsubject", self.OLD_TEACHER)])])

    def test_pin_of_earlier_course_of_stage(self):
        """Решатель ставит закрепления по курсам в порядке имён. Курс этапа, который ещё не начался, закреплён
        вручную в пн 1-й урок за ``OLD_TEACHER``: если его имя раньше (``BIO_1``), его закрепление встанет
        первым, и урок ``MATH_1`` не встанет — причина "elsewhere"; если позже (``MATH_LEVEL_1``) — не помеха.
        """
        bio = jointCourse(1, "Биология")
        setTeacherSubjects(self.settings, self.OLD_TEACHER, ["Математика", "Биология"])

        for course, subject in ((MATH_LEVEL_1, "Математика"), (bio, "Биология")):
            next(group for group in self.settings["classes"]["custom_groups"] if group["name"] == course)["start_date"] = FUTURE
            setTeacherCourseState(self.settings, self.OLD_TEACHER, subject, course, "assigned")
            self.settings["constants"][course] = {"0-0": subject}

            self.assertEqual(self.blocked(), [] if course == MATH_LEVEL_1 else [(self.MATH_1, [(0, 0, "elsewhere", bio)])])

    def test_earlier_started_course_wins(self):
        """Два идущих курса этапа с одним преподавателем в одно время (накладка в расписании): решатель
        закрепит урок курса, чьё имя раньше (``MATH_1``), — назван только урок второго.
        """
        self.answer[MATH_LEVEL_1] = courseWeek("Математика", self.OLD_TEACHER, (0, 0), (2, 0))
        setHours(self.settings, MATH_LEVEL_1, 3)

        self.assertEqual(self.blocked(), [(MATH_LEVEL_1, [(0, 0, "busy", self.MATH_1), (2, 0, "busy", self.MATH_1)])])

    def test_pair_and_program_are_named(self):
        """Пара «нельзя» с уроком курса той же линейки, который решатель поставит раньше (зафиксированная
        «Биология» Потока 1 в пн 1-й урок), — "pair"; урок Потока 2 программы, которая не должна
        пересекаться с нашей, по тому же предмету (в ср 1-й урок, у другого преподавателя) — "program".
        """
        bio = jointCourse(1, "Биология")
        self.settings["joint_subject_pairs"] = [["Математика", "Биология"]]
        self.answer[bio] = courseWeek("Биология", "Биология #1", (0, 0))
        self.settings["non_overlapping_programs"] = [["ЕГЭ основной", "Семинары"]]
        next(group for group in self.settings["classes"]["custom_groups"] if group["name"] == self.MATH_2)["program"] = "Семинары"
        self.answer[self.MATH_2] = courseWeek("Математика", self.NEW_TEACHER, (2, 0))

        self.assertEqual(self.blocked(), [(self.MATH_1, [(0, 0, "pair", bio), (2, 0, "program", self.MATH_2)])])

    def test_other_stage_course_in_stage_dates(self):
        """Решатель занимает время преподавателя уроками других этапов, чьи даты пересекаются с датами
        всего этапа, а не только курса: ``MATH_1`` кончается в октябре, урок Потока 2 у ``OLD_TEACHER`` в пн
        1-й урок идёт в декабре, а другие курсы Потока 1 идут и тогда — причина "busy".
        """
        setDates(self.settings, self.MATH_1, "2026-09-07", "2026-10-31")
        setDates(self.settings, self.MATH_2, "2026-12-01", "2026-12-20")
        self.answer[self.MATH_2] = courseWeek("Математика", self.OLD_TEACHER, (0, 0))

        self.assertEqual(self.blocked(), [(self.MATH_1, [(0, 0, "busy", self.MATH_2)])])

    def test_nothing_blocked(self):
        """Помех нет — пусто. Зафиксированный курс (все уроки на месте) сборка не получает, курс без
        преподавателя из проекта переходит в варианты как есть — их «не может» не помеха.
        """
        self.assertEqual(self.blocked(), [])

        markCannot(self.settings, self.OLD_TEACHER, "1", (0, 0))
        setHours(self.settings, self.MATH_1, 2)
        self.assertEqual(self.blocked(), [])

        setHours(self.settings, self.MATH_1, 3)
        self.answer[self.MATH_1] = courseWeek("Математика", "Уволен", (0, 0), (2, 0))
        self.assertEqual(self.blocked(), [])


class LockedFromAnswerTests(unittest.TestCase):
    """``lockedFromAnswer``: зафиксированные курсы этапа — из принятого расписания."""
    def test_locked_course_taken_from_answer(self):
        """Поток 1 идёт и все его уроки на месте (сегодня 04.10.2026): вариант с другим преподавателем
        у ``MATH_1`` показывается с преподавателем из расписания; курс, который ещё не идёт, остаётся из варианта.
        """
        settings, answer = jointProject()
        shiftStream(settings, 1, PAST)
        # «ЕГЭ продвинутый» Математика Потока 1 ещё не начинается — её вариант не трогается
        next(group for group in settings["classes"]["custom_groups"] if group["name"] == MATH_LEVEL_1)["start_date"] = FUTURE
        variant = {name: courseWeek("Математика", NEW_TEACHER, (1, 0), (3, 0)) for name in (MATH_1, MATH_LEVEL_1)}

        with mock.patch("datetime.date", FrozenDate):
            result = lockedFromAnswer(settings, answer, "1", copy.deepcopy(variant))

        self.assertEqual(result[MATH_1], answer[MATH_1])
        self.assertEqual(result[MATH_LEVEL_1], variant[MATH_LEVEL_1])
        self.assertEqual(result[RUS_1], answer[RUS_1])
