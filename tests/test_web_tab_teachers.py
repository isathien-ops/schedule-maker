"""Действия вкладки «Преподаватели» (`src/web/tabs/teachers.py`).

Новые преподаватели и их предметы (снятие предмета, который преподаватель ведёт), отметки
«удобно / может / не может» и их копирование, состояния «преподаватель — курс», карточка
преподавателя, удаление преподавателя с очисткой расписания, вариантов и своих правил.
``JointTeacherTests`` — курсы-копии «линейки, которая присоединяется к Потоку N» (.spec/joint-lines/SPEC.md):
их отношение к преподавателю не меняется, а общие уроки в вопросах считаются один раз; «не может»
под общим уроком (AC-39) можно снять.

Основа — `RealProjectCase` из `tests/real_project.py`: копия реального проекта 2026/27, «сегодня»
04.10.2026, действия идут через сервер, как со страницы (POST /api/project/<имя>/action).
Проверяется, что сервер защищает курсы, которые уже идут, переспрашивает (ответ с "confirm")
перед опасными действиями, сохраняет версии «Перед: …» и при отказе не портит файлы проекта.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import json
import os

from src.modules.translate import tr, translate
from src.modules.functions.stages import stageCourses
from src.modules.functions.variants import loadVariants, saveVariant, variantsDir
from src.web.project import bullets, lessonsText
from tests.builders import JOINT_LINE, jointCourse, jointProject, markCannot, markJoint
from tests.real_project import CHEMIST, CHEM_OGE_2, GEO_2, RUS_8_2, RealProjectCase, lessons

# Курс-источник Потока 1 и его копия в Потоке 2 (проект builders.jointProject) и их преподаватель
MATH_1, MATH_2 = jointCourse(1, "Математика"), jointCourse(2, "Математика")
MATH_TEACHER = "Математика #1"


class TeachersTabTests(RealProjectCase):
    """Вкладка «Преподаватели»: предметы, отметки, курсы, карточка, удаление."""
    NAME = "__test_teachers__"

    def card(self, name=CHEMIST, stage="2"):
        """Карточка преподавателя (GET /teacher) на этапе `stage`."""
        response = self.client.get(f"/api/project/{self.NAME}/teacher", query_string={"name": name, "stage": stage})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def courseState(self, course, name=CHEMIST):
        """Состояние «преподаватель — курс» из карточки."""
        return next(item["state"] for subject in self.card(name)["subjects"] for item in subject["courses"] if item["name"] == course)

    def test_new_teacher_validation(self):
        """Новый преподаватель: нужны имя, не занятое другим, и хотя бы один известный предмет."""
        self.refused("newTeacher", name=" ", subjects=["Химия"])
        self.refused("newTeacher", name=CHEMIST, subjects=["Химия"])
        self.refused("newTeacher", name="Новикова Ольга", subjects=[])
        self.refused("newTeacher", name="Новикова Ольга", subjects=["Астрология"])

        self.ok("newTeacher", name="  Новикова Ольга ", subjects=["Химия", "Биология"])
        teacher = next(item for item in self.state()["teachers"] if item["name"] == "Новикова Ольга")
        self.assertEqual(sorted(teacher["subjects"]), ["Биология", "Химия"])
        # Новый преподаватель может вести курсы своих предметов (а не «ведёт» их)
        states = {item["state"] for subject in self.card("Новикова Ольга")["subjects"] for item in subject["courses"]}
        self.assertEqual(states, {"may"})

    def test_removing_a_taught_subject_asks_and_frees_lessons(self):
        """Убрать предмет, по которому у преподавателя есть уроки: сначала вопрос со списком курсов;
        после согласия эти уроки остаются без преподавателя, а версия «Перед: …» позволяет откатить.
        """
        self.refused("teacherSubjects", name="Нет такого", subjects=["Химия"])

        body = self.ok("teacherSubjects", name=CHEMIST, subjects=["Биология"])
        self.assertTrue(body.get("danger"))
        self.assertIn("Химия", body["confirm"])

        self.ok("teacherSubjects", name=CHEMIST, subjects=["Биология"], force=True)
        answer = self.load("answer.json")
        self.assertFalse([name for name, week in answer.items() for _, _, cell in lessons(week) if CHEMIST in cell.get("teachers", [])])
        self.assertTrue(any(name.startswith("Перед:") for name in self.versions()))
        teacher = next(item for item in self.state()["teachers"] if item["name"] == CHEMIST)
        self.assertEqual(teacher["subjects"], ["Биология"])

    def test_availability_cycles_and_skips_committed_time(self):
        """Клик по клетке доступности: удобно -> может -> не может -> удобно. Время, занятое её уроками
        других этапов, и ячейки вне сетки не меняются. Неизвестный этап или преподаватель — отказ.
        """
        commitments = {(day, lesson) for day, lesson, _, _ in self.card()["commitments"]}
        self.assertIn((1, 0), commitments)  # урок потока 1 во вторник 16:20

        marks = lambda: (self.card()["possible"], self.card()["busy"])
        self.ok("cycleAvailability", name=CHEMIST, stage="2", day=0, lesson=0)
        self.assertEqual(marks(), ([[0, 0]], []))
        self.ok("cycleAvailability", name=CHEMIST, stage="2", day=0, lesson=0)
        self.assertEqual(marks(), ([], [[0, 0]]))
        self.ok("cycleAvailability", name=CHEMIST, stage="2", day=0, lesson=0)
        self.assertEqual(marks(), ([], []))

        self.ok("cycleAvailability", name=CHEMIST, stage="2", day=1, lesson=0)
        self.ok("cycleAvailability", name=CHEMIST, stage="2", day=6, lesson=5)
        self.assertEqual(marks(), ([], []))

        self.refused("cycleAvailability", name=CHEMIST, stage="9", day=0, lesson=0)
        self.refused("cycleAvailability", name="Нет такого", stage="2", day=0, lesson=0)

    def test_started_lesson_cell_only_drops_cannot(self):
        """Клетка своего урока идущего курса («уже идёт»): новая отметка там не ставится — время
        такого урока не меняют. А «не может», поставленное раньше, чем курс начался, щелчок снимает:
        иначе каждое новое составление переносило бы этот урок.
        """
        day, lesson, course, _ = next(item for item in self.card(stage="1")["own"] if item[3])
        self.assertEqual(course, "Поток 1 — ЕГЭ основной — Химия")
        marks = lambda: self.load("settings.json")["teachers"][CHEMIST].get("availability", {}).get("1", {})

        self.ok("cycleAvailability", name=CHEMIST, stage="1", day=day, lesson=lesson)
        self.assertEqual((marks().get("possible", []), marks().get("free", [])), ([], []))

        settings = self.load("settings.json")
        markCannot(settings, CHEMIST, "1", (day, lesson))
        self.save("settings.json", settings)
        self.ok("cycleAvailability", name=CHEMIST, stage="1", day=day, lesson=lesson)
        self.assertEqual((marks().get("possible", []), marks().get("free", [])), ([], []))

    def test_copy_availability_is_independent(self):
        """Отметки этапа копируются в другой этап; потом этапы меняются независимо друг от друга."""
        self.ok("cycleAvailability", name=CHEMIST, stage="2", day=2, lesson=2)
        self.ok("cycleAvailability", name=CHEMIST, stage="2", day=2, lesson=2)

        body = self.ok("copyAvailability", source="2", target="extra", name=CHEMIST)
        self.assertIn("message", body)
        self.assertEqual(self.card(stage="extra")["busy"], [[2, 2]])

        self.ok("cycleAvailability", name=CHEMIST, stage="2", day=2, lesson=2)
        self.assertEqual(self.card(stage="2")["busy"], [])
        self.assertEqual(self.card(stage="extra")["busy"], [[2, 2]])

        self.refused("copyAvailability", source="2", target="9")

    def test_course_states_cycle(self):
        """Клик по курсу в карточке: ведёт -> запрещено -> не ведёт -> может -> ведёт. Курс, который
        она ведёт в расписании, так не меняется; у курса из расписания без неё «ведёт» пропускается.
        """
        free = "Поток 2 — ЕГЭ основной — Химия"   # не в расписании, закреплён за ней
        orphan = "Поток 2 — ЕГЭ продвинутый — Химия"  # в расписании, но без преподавателя
        taught = "Поток 2 — 10 класс — Химия"   # в расписании ведёт она

        states = [self.courseState(free)]
        for _ in range(4):
            self.ok("cycleCourse", name=CHEMIST, subject="Химия", course=free)
            states.append(self.courseState(free))

        self.assertEqual(states, ["assigned", "forbidden", "no", "may", "assigned"])

        self.assertEqual(self.courseState(orphan), "may")
        self.ok("cycleCourse", name=CHEMIST, subject="Химия", course=orphan)
        self.assertEqual(self.courseState(orphan), "forbidden")

        self.refused("cycleCourse", name=CHEMIST, subject="Химия", course=taught)

    def test_teacher_card(self):
        """Карточка преподавателя: его уроки этапа, занятость уроками других этапов и курсы с пометками;
        неизвестный преподаватель — понятная ошибка.
        """
        card = self.card()
        own = {course for _, _, course, _ in card["own"]}
        self.assertIn("Поток 2 — 10 класс — Химия", own)
        self.assertTrue(all(kind == "busy" for _, _, kind, _ in card["commitments"]))
        self.assertEqual(card["limit"], 10)
        courses = {item["name"]: item for subject in card["subjects"] for item in subject["courses"]}
        self.assertTrue(courses["Поток 1 — ЕГЭ основной — Химия"]["started"])
        self.assertTrue(courses["Поток 2 — ЕГЭ продвинутый — Химия"]["orphan"])

        response = self.client.get(f"/api/project/{self.NAME}/teacher", query_string={"name": "Нет такого", "stage": "2"})
        self.assertEqual(response.status_code, 400)

    def test_removing_untaught_subject_changes_no_schedule(self):
        """Убрали предмет, по которому у преподавателя нет уроков: без вопроса, без версии,
        расписание и варианты не переписываются.
        """
        self.ok("newTeacher", name="Тестова Анна", subjects=["Химия", "Биология"])
        saveVariant(self.folder, "2", 1, {CHEM_OGE_2: self.load("answer.json")[CHEM_OGE_2]})
        variant = self.raw(os.path.join(variantsDir(self.folder, "2"), "1.json"))
        answer_before = self.raw("answer.json")
        versions = self.versions()

        body = self.ok("teacherSubjects", name="Тестова Анна", subjects=["Химия"])

        self.assertNotIn("confirm", body)
        self.assertEqual(next(item for item in body["state"]["teachers"] if item["name"] == "Тестова Анна")["subjects"], ["Химия"])
        self.assertEqual(self.versions(), versions)
        self.assertEqual(self.raw("answer.json"), answer_before)
        self.assertEqual(self.raw(os.path.join(variantsDir(self.folder, "2"), "1.json")), variant)

    def test_unknown_teacher_and_empty_subjects_are_refused(self):
        """Предметы, курс и удаление неизвестного преподавателя (удалён в другой вкладке) — понятный
        отказ «нет преподавателя», а не «что-то пошло не так»; пустой список предметов — отказ.
        """
        no_teacher = translate("web.error.no_teacher")
        self.assertEqual(self.refused("teacherSubjects", name="Нет такого", subjects=["Химия"]), no_teacher)
        self.assertEqual(self.refused("cycleCourse", name="Нет такого", subject="География", course=GEO_2), no_teacher)
        self.assertEqual(self.refused("deleteTeacher", name="Нет такого"), no_teacher)
        self.assertEqual(self.refused("teacherSubjects", name="Тюгалева", subjects=[]), translate("web.error.teacher_no_subjects"))
        self.assertEqual(self.refused("teacherSubjects", name="Тюгалева", subjects=["Латынь"]), translate("web.error.generic"))

    def test_deleting_teacher_without_lessons(self):
        """Преподаватель без уроков: короткий вопрос; после удаления — без версии, его правила удалены,
        расписание не переписано.
        """
        self.ok("newTeacher", name="Тестова Анна", subjects=["Химия"])
        self.ok("savePenalty", penalty={"name": "Не больше двух", "template": "daily_limit", "weight": 5,
                                        "params": {"target": "teacher", "value": "Тестова Анна", "limit": 2}})
        self.ok("savePenalty", penalty={"name": "Химия и биология", "template": "same_day", "weight": 5, "params": {"first": "Химия", "second": "Биология"}})
        answer_before = self.raw("answer.json")
        versions = self.versions()

        body = self.ok("deleteTeacher", name="Тестова Анна")
        self.assertEqual(body["confirm"], translate("web.confirm_delete_teacher").replace("{name}", "Тестова Анна"))
        self.assertTrue(body["danger"])

        state = self.ok("deleteTeacher", name="Тестова Анна", force=True)["state"]
        self.assertNotIn("Тестова Анна", [item["name"] for item in state["teachers"]])
        self.assertEqual([item["name"] for item in state["penalties"]], ["Химия и биология"])
        self.assertEqual(self.versions(), versions)
        self.assertEqual(self.raw("answer.json"), answer_before)

    def test_copy_availability_refuses_unknown_teacher_skips_same_stage(self):
        """Неизвестный преподаватель (удалён в другой вкладке) — отказ «нет такого преподавателя»,
        даже при одинаковых этапах; «из этапа в тот же этап» ничего не меняет; неизвестный этап — отказ.
        """
        settings = self.load("settings.json")
        settings["teachers"]["Тюгалева"]["availability"]["1"] = {"free": [[0, 0]], "possible": [[1, 1]]}
        self.save("settings.json", settings)
        teachers = self.load("settings.json")["teachers"]

        no_teacher = translate("web.error.no_teacher")
        self.assertEqual(self.refused("copyAvailability", source="1", target="2", name="Нет такого"), no_teacher)
        self.assertEqual(self.refused("copyAvailability", source="1", target="1", name="Нет такого"), no_teacher)
        self.ok("copyAvailability", source="1", target="1")
        self.assertEqual(self.load("settings.json")["teachers"], teachers)

        self.assertEqual(self.refused("copyAvailability", source="1", target="9"), translate("web.error.generic"))

        # Для одного преподавателя — меняются только его отметки
        self.ok("copyAvailability", source="1", target="2", name="Тюгалева")
        after = self.load("settings.json")["teachers"]
        self.assertEqual(after["Тюгалева"]["availability"]["2"], {"free": [[0, 0]], "possible": [[1, 1]]})
        self.assertEqual({name: data for name, data in after.items() if name != "Тюгалева"}, {name: data for name, data in teachers.items() if name != "Тюгалева"})

    def test_card_ignores_unknown_courses_and_subjects_without_courses(self):
        """Карточка преподавателя: курс из расписания, которого нет в настройках, не попадает в её уроки;
        предмет, по которому не осталось курсов, не показывается.
        """
        answer = self.load("answer.json")
        ghost = json.loads(json.dumps(answer[RUS_8_2] if RUS_8_2 in answer else answer[CHEM_OGE_2]))
        for day in ghost:
            for cell in day:
                cell.update(subject="#", teachers=[])

        ghost[0][0] = {"subject": "География", "teachers": ["Тюгалева"]}
        answer["Призрачный курс"] = ghost
        self.save("answer.json", answer)

        card = self.client.get(f"/api/project/{self.NAME}/teacher", query_string={"name": "Тюгалева", "stage": "2"}).get_json()
        self.assertEqual([item[2] for item in card["own"]], ["Поток 2 — ОГЭ — География"])
        self.assertEqual(card["clashes"], [])
        self.assertEqual([item["subject"] for item in card["subjects"]], ["География"])

        for name in ("Поток 1 — ОГЭ — География", "Поток 2 — ОГЭ — География"):
            self.ok("deleteCourse", course=name, force=True)

        card = self.client.get(f"/api/project/{self.NAME}/teacher", query_string={"name": "Тюгалева", "stage": "2"}).get_json()
        self.assertEqual((card["subjects"], card["own"]), ([], []))

    def test_delete_teacher_cleans_schedule_variants_and_wishes(self):
        """Удаление учителя сначала требует подтверждения, затем убирает его из принятого расписания,
        вариантов и правил и сохраняет версию «Перед: удаление преподавателя» для отката.
        """
        teacher = "Дускаева Дана"
        stage = "2"
        answer = self.load("answer.json")
        saveVariant(self.folder, stage, 1, {name: answer[name] for name in stageCourses(self.load("settings.json"), stage) if name in answer})
        self.act("savePenalty", penalty={"name": "w", "template": "daily_limit", "weight": 50, "params": {"target": "teacher", "value": teacher, "limit": 2}})

        code, body = self.act("deleteTeacher", name=teacher)
        self.assertIn("confirm", body)
        self.assertEqual(self.act("deleteTeacher", name=teacher, force=True)[0], 200)

        def has(answer_like):
            return any(teacher in cell.get("teachers", []) for week in answer_like.values() for _, _, cell in lessons(week))

        self.assertFalse(has(self.load("answer.json")))
        self.assertFalse(any(has(variant) for _, variant in loadVariants(self.folder, stage)))
        self.assertFalse(self.load("settings.json").get("custom_penalties"))
        self.assertTrue(any(name.startswith("Перед: удаление преподавателя") for name in self.versions()))

    def test_copy_availability_into_same_stage_changes_nothing(self):
        """Копирование отметок этапа в тот же этап не меняет настроек: у нового преподавателя не появляется
        пустых отметок этапа.
        """
        self.ok("newTeacher", name="Новикова Ольга", subjects=["Химия"])
        before = self.load("settings.json")
        self.assertNotIn("1", before["teachers"]["Новикова Ольга"]["availability"])

        body = self.ok("copyAvailability", source="1", target="1")

        self.assertEqual(body["message"], translate("web.teachers.copied"))
        self.assertEqual(self.load("settings.json"), before)


class JointTeacherTests(RealProjectCase):
    """Курсы-копии на вкладке «Преподаватели»: проект builders.jointProject, «ЕГЭ основной»
    Потока 2 идёт вместе с Потоком 1 (общие уроки «Математики» ведёт «Математика #1»).
    """
    NAME = "__test_joint_teachers__"

    def setUp(self):
        """Реальный проект подменяется проектом jointProject с отметкой у «ЕГЭ основной» Потока 2."""
        super().setUp()
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)

    def assertJointLessonsKept(self):
        """После удаления преподавателя источника или снятия его с предмета (AC-18): его нет ни в одном
        уроке; оба урока источника (пн и ср 1-м уроком) стоят на местах, но без преподавателя
        (teachers == []), а копия равна источнику — те же уроки, тоже без преподавателя.
        Сравнение через answer[...]: если курса в расписании нет, тест падает, а не сравнивает None с None.
        """
        answer = self.load("answer.json")
        self.assertFalse([name for name, week in answer.items() for _, _, cell in lessons(week) if MATH_TEACHER in cell["teachers"]])
        self.assertEqual(len(lessons(answer[MATH_1])), 2)

        for course in (MATH_1, MATH_2):
            self.assertEqual([cell["teachers"] for _, _, cell in lessons(answer[course])], [[], []], course)

        self.assertEqual(answer[MATH_2], answer[MATH_1])

    def test_copy_course_state_is_closed(self):
        """AC-10: клик по курсу-копии в карточке преподавателя — отказ web.error.joint_locked
        («Курс присоединён к Потоку 1: …»), settings.json не переписан.
        """
        before = self.raw("settings.json")

        error = self.refused("cycleCourse", name="Математика #2", subject="Математика", course=MATH_2)

        self.assertText("web.error.joint_locked", error)
        self.assertEqual(self.raw("settings.json"), before)

    def test_deleting_source_teacher_counts_joint_lessons_once(self):
        """AC-18: удаление преподавателя курса-источника: в вопросе общие уроки посчитаны один раз
        (2 урока «Поток 1 — … — Математика», без копии). После удаления уроки источника остаются
        на местах без преподавателя, а копия по-прежнему равна источнику (``assertJointLessonsKept``).
        """
        body = self.ok("deleteTeacher", name=MATH_TEACHER)

        self.assertEqual(body["confirm"], tr("web.confirm_delete_teacher_lessons", name=MATH_TEACHER, count=lessonsText(2), courses=bullets([MATH_1])))

        self.ok("deleteTeacher", name=MATH_TEACHER, force=True)

        self.assertJointLessonsKept()

    def test_dropping_source_subject_counts_joint_lessons_once(self):
        """AC-18: преподавателя курса-источника сняли с предмета: в вопросе общие уроки посчитаны
        один раз (только курс-источник); после согласия уроки источника остаются на местах без
        преподавателя, а копия по-прежнему равна источнику (``assertJointLessonsKept``).
        """
        body = self.ok("teacherSubjects", name=MATH_TEACHER, subjects=["Информатика"])

        self.assertEqual(body["confirm"], tr("web.confirm_drop_subject", name=MATH_TEACHER, count=lessonsText(2), courses=bullets([MATH_1])))

        self.ok("teacherSubjects", name=MATH_TEACHER, subjects=["Информатика"], force=True)

        self.assertJointLessonsKept()

    def test_cannot_under_shared_lesson_can_be_removed(self):
        """AC-39: у «Математика #1» на этапе «Поток 2» в пн 1-м уроком «не может», а там общий урок
        (отметку поставили раньше, чем уроки туда встали). Клик по этой клетке снимает отметку —
        иначе предупреждение «Общий урок, когда преподаватель «не может»» (web.view.joint_cannot_title) не убрать, ведь клетки общих уроков
        (вид "joint") в остальном не меняются.
        """
        settings = self.load("settings.json")
        markCannot(settings, MATH_TEACHER, "2", (0, 0))
        self.save("settings.json", settings)

        self.ok("cycleAvailability", name=MATH_TEACHER, stage="2", day=0, lesson=0)

        self.assertNotIn([0, 0], self.load("settings.json")["teachers"][MATH_TEACHER]["availability"]["2"]["free"])
