"""Что видит страница (`src/web/state.py`): полное состояние проекта и сводки по этапам.

Сколько уроков этапа расставлено и «этап построен» считает предметный слой (stages.stageTotals,
stages.stageBuilt) — их тесты в test_functions_stages.py; здесь — что эти поля доходят до страницы.

* ``StateTests`` — разделы, сводка этапов, прогноз закреплений, кандидаты курса, курсы без преподавателя;
* ``JointStateTests`` — «Линейка присоединяется к Потоку N»: выбор и отметка у разделов
  (``jointOptions``, ``joint``), курс-копия и источник (``joint``, ``jointWith``), «ждут Поток N»;
* ``JointCountsTests`` — уроки этапа и всего расписания без двойного счёта общих уроков;
* ``JointCannotStateTests`` — AC-39: общие уроки в часы «не может» преподавателя на этапе
  потока-копии — предупреждение над «Расписанием» (``jointCannot``);
* ``StartedSourceStateTests`` — источник, который «идёт» только через свою копию: started / locked
  и ``runningSince`` (дата, с которой идут его уроки);
* ``BlockedStartedStateTests`` — ``blockedStarted`` у этапа: уроки идущих курсов, которые сборка не сможет
  оставить на месте (предупреждение «Запуска» до сборки).
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

from unittest import mock

from src.modules.translate import tr, translate
from src.modules.functions import stages as stagesModule
from src.modules.functions.courses import removeCourses
from src.modules.functions.model import lessonEntries
from src.modules.functions.stages import builtStages, stageCourses
from src.web import build
from src.web.project import slotText
from tests.builders import (
    JOINT_LINE, LEVEL_LINE, OWN_LINE, courseWeek, jointCourse, jointProject, markCannot, markJoint, setHours,
    shiftStream
)
from tests.real_project import (
    GEO_1, GEO_2, PHYS_BASE_TEACHER, PHYS_PRO_1, RUS_8_2, RUS_BASE_2, RealProjectCase, SEM_MATH, SEM_RUS, unstaffed
)

EMPTY = {"subject": "#", "teachers": []}

# Курсы проекта builders.jointProject (StartedSourceStateTests) и даты относительно «сегодня» 04.10.2026
MATH_1, MATH_2, MATH_LEVEL_1 = jointCourse(1, "Математика"), jointCourse(2, "Математика"), jointCourse(1, "Математика", LEVEL_LINE)
FUTURE, PAST = "2026-10-12", "2026-09-14"


class StateTests(RealProjectCase):
    """Поля состояния: разделы, сводка этапов и прогноз закреплений, занятые кандидаты курса, курсы без преподавателя."""
    NAME = "__test_state__"

    def test_section_titles_and_broken_dates(self):
        """Заголовок раздела — «Поток N» и даты «дд.мм.гггг – дд.мм.гггг»; если дата испорчена, даты пустые,
        а страница всё равно открывается.
        """
        sections = {item["key"]: item for item in self.state()["sections"]}
        self.assertEqual((sections[1]["name"], sections[1]["dates"]), ("Поток 1", "07.09.2026 – 30.06.2027"))
        self.assertEqual(sections["extra"]["name"], translate("stage.extra"))

        settings = self.load("settings.json")
        for group in settings["classes"]["custom_groups"]:
            if group.get("stream_id") == 2:
                group["start_date"] = "23.11.2026"

        self.save("settings.json", settings)

        sections = {item["key"]: item for item in self.state()["sections"]}
        self.assertEqual((sections[2]["name"], sections[2]["dates"]), ("Поток 2", ""))

    def test_stage_summary(self):
        """Сводка этапов для «Запуска»: поток 1 построен и весь идёт; поток 2 не построен; числа уроков согласованы."""
        stages = {item["key"]: item for item in self.state()["stages"]}
        self.assertTrue(stages["1"]["built"] and stages["1"]["allStarted"])
        self.assertFalse(stages["2"]["built"] or stages["2"]["allStarted"])
        self.assertLess(stages["2"]["placed"], stages["2"]["expected"])
        self.assertEqual(stages["extra"]["dates"], ["2026-10-05", "2027-06-30"])

        # «Построен» — то же определение, что на стартовом экране (stages.builtStages)
        built = builtStages(self.load("settings.json"), self.load("answer.json"))
        self.assertEqual([key for key, item in stages.items() if item["built"]], built)

    def test_pin_forecast(self):
        """Прогноз у галочки «Оставить уже принятые уроки на месте» (solver_input.pinForecast) с галочкой
        (keep) и без неё (fresh): поток 2 ещё не начался — без галочки закрепляется 0 из 62, с ней
        41 стоящий урок; поток 1 идёт — его уроки закрепляются и без галочки, а идущий курс без
        преподавателя (2 урока) в прогноз не входит; доп. курсы ещё не начались.
        """
        stages = {item["key"]: item["forecast"] for item in self.state()["stages"]}

        def counts(pinned, total, nobody=0):
            return {"pinned": pinned, "total": total, "free": total - pinned - nobody, "noTeacher": nobody}

        self.assertEqual(stages["2"], {"keep": counts(41, 62), "fresh": counts(0, 62)})
        self.assertEqual(stages["1"], {"keep": counts(60, 60), "fresh": counts(60, 60)})
        self.assertEqual(stages["extra"], {"keep": counts(13, 13), "fresh": counts(0, 13)})

        # Ручные закрепления курса потока 2, которого нет в расписании, считаются и без галочки
        self.ok("setPins", course=RUS_BASE_2, subject="Русский язык", slots=[[0, 0], [2, 0]])
        forecast = next(item["forecast"] for item in self.state()["stages"] if item["key"] == "2")
        self.assertEqual((forecast["fresh"]["pinned"], forecast["keep"]["pinned"]), (2, 43))

        # Курс, который никто не может вести (1 урок): программа его не подберёт — он в noTeacher
        self.save("settings.json", unstaffed(self.load("settings.json"), RUS_8_2, "Русский язык"))
        forecast = next(item["forecast"] for item in self.state()["stages"] if item["key"] == "2")
        self.assertEqual(forecast, {"keep": counts(43, 62, 1), "fresh": counts(2, 62, 1)})

    def test_course_short_label_and_iteration_levels(self):
        """Курс несёт готовую короткую подпись (страница не разбирает название); ползунок
        «Тщательность» получает деления сервера.
        """
        course = self.course(PHYS_PRO_1)
        self.assertEqual(course["short"], PHYS_PRO_1.replace(" — ", ", "))
        self.assertEqual(self.course(SEM_MATH)["short"], SEM_MATH)

        state = self.state()
        self.assertEqual(state["iterationLevels"], list(build.ITERATION_LEVELS))
        self.assertIn(state["iterations"], state["iterationLevels"])

    def test_busy_options_of_course_without_teacher(self):
        """Курс в расписании, у всех уроков нет преподавателя: в busyOptions — преподаватель предмета,
        занятый в эти часы, а свободный новый преподаватель — нет.
        """
        self.ok("newTeacher", name="Новиков Пётр", subjects=["Физика"])

        course = self.course(PHYS_PRO_1)

        self.assertIn(PHYS_BASE_TEACHER, course["busyOptions"])
        self.assertNotIn("Новиков Пётр", course["busyOptions"])
        self.assertIn("Новиков Пётр", course["options"])

    def test_busy_options_empty_when_some_lessons_have_teacher(self):
        """Хотя бы у одного урока курса есть преподаватель — busyOptions пустой."""
        answer = self.load("answer.json")
        answer[PHYS_PRO_1][1][1]["teachers"] = [PHYS_BASE_TEACHER]
        self.save("answer.json", answer)

        self.assertEqual(self.course(PHYS_PRO_1)["busyOptions"], [])

    def test_extra_lesson_does_not_hide_missing_one(self):
        """Доп. курсы: у одного семинара лишний урок, у другого урока нет — этап не построен, placed < expected."""
        stages = {item["key"]: item for item in self.state()["stages"]}
        self.assertTrue(stages["extra"]["built"])
        expected = stages["extra"]["expected"]
        self.assertEqual(stages["extra"]["placed"], expected)

        answer = self.load("answer.json")
        answer[SEM_RUS][5][1] = {"subject": "Русский язык", "teachers": ["Хмелевская Анастасия"]}
        answer[SEM_MATH][6][1] = dict(EMPTY)
        self.save("answer.json", answer)

        stages = {item["key"]: item for item in self.state()["stages"]}
        self.assertEqual((stages["extra"]["expected"], stages["extra"]["placed"]), (expected, expected - 1))
        self.assertFalse(stages["extra"]["built"])

    def test_removed_teacher_counts_as_no_teacher(self):
        """Преподавателя убрали из настроек, а в расписании он остался: его курсы — в noTeacher
        с числом уроков и датой начала; список упорядочен по дате начала, затем по имени.
        """
        before = self.state()["noTeacher"]
        self.assertNotIn(GEO_1, [item[0] for item in before])

        settings = self.load("settings.json")
        del settings["teachers"]["Тюгалева"]
        self.save("settings.json", settings)

        after = self.state()["noTeacher"]

        self.assertIn([GEO_1, 1, "2026-09-07"], after)
        self.assertIn([GEO_2, 1, "2026-11-23"], after)
        self.assertEqual(after, sorted(before + [[GEO_1, 1, "2026-09-07"], [GEO_2, 1, "2026-11-23"]], key=lambda item: (item[2], item[0])))

    def test_handover_version_is_marked(self):
        """Версия «Передано руководителю» — исходное расписание, переданное вместе с программой, —
        отмечена полем handover (перед её удалением страница предупреждает особо); другие версии — нет.
        """
        handover = translate("web.save.handover_name")
        self.ok("newVersion", name=handover)
        self.ok("newVersion", name="Моя версия")

        marks = {item["name"]: item["handover"] for item in self.state()["versions"]}

        self.assertIs(marks[handover], True)
        self.assertIs(marks["Моя версия"], False)


def offered(section):
    """Линейки раздела, у которых есть выбор «Присоединяется к»: {линейка: [потоки]} без пустых списков."""
    return {line: numbers for line, numbers in section.get("jointOptions", {}).items() if numbers}


class JointStateTests(RealProjectCase):
    """Состояние для страницы и функция «Линейка присоединяется к Потоку N» (AC-1, AC-10, AC-13) на
    проекте ``builders.jointProject``: Потоки 1–3, «ЕГЭ основной» и «ЕГЭ продвинутый» в каждом,
    «ОГЭ» — только в Потоках 2 и 3.
    """
    NAME = "__test_state_joint__"

    def openJoint(self, accepted=True, mark=True):
        """Подменяет проект на jointProject (Поток 1 принят, если ``accepted``); при ``mark`` «ЕГЭ основной»
        Потока 2 присоединяется к Потоку 1 (``markJoint``). Проект открывается заново.
        Возвращает {копия: источник}.
        """
        settings, answer = jointProject(accepted=accepted)
        copies = markJoint(settings, 2, JOINT_LINE, 1, answer) if mark else {}
        self.openProject(settings, answer)

        return copies

    def sections(self):
        """Разделы вкладки «Курсы» из состояния: ключ раздела -> описание."""
        return {item["key"]: item for item in self.state()["sections"]}

    def test_joint_options_of_sections(self):
        """AC-1 (и AC-9): выбор «Присоединяется к» (``sections[*].jointOptions``) есть у линейки потока,
        если в более раннем потоке есть линейка с тем же названием: у Потока 2 — «ЕГЭ основной» и
        «ЕГЭ продвинутый» с Потоком 1, у «ОГЭ» Потока 2 (её нет в Потоке 1) выбора нет; у Потока 3
        «ОГЭ» — только Поток 2. У Потока 1 и у блоков выбора нет. Без отметок ``joint`` пуст.
        После отметки «ЕГЭ основной» Потока 2: ``joint == {«ЕГЭ основной»: 1}``, а Потоку 3 Поток 2
        для этой линейки больше не предлагается (он сам присоединён к Потоку 1).
        """
        self.openJoint(mark=False)
        sections = self.sections()

        self.assertEqual(sections[2]["jointOptions"].get(JOINT_LINE), [1])
        self.assertEqual(offered(sections[2]), {JOINT_LINE: [1], LEVEL_LINE: [1]})
        self.assertEqual(offered(sections[3]), {JOINT_LINE: [1, 2], LEVEL_LINE: [1, 2], OWN_LINE: [2]})
        self.assertEqual(offered(sections[1]), {})

        for key, section in sections.items():
            self.assertEqual(section.get("joint", {}), {}, key)

            if section["block"]:
                self.assertEqual(offered(section), {}, key)

        self.openJoint()
        sections = self.sections()

        self.assertEqual(sections[2]["joint"], {JOINT_LINE: 1})
        self.assertEqual(sections[3]["joint"], {})
        self.assertEqual(sections[1]["joint"], {})
        self.assertEqual(offered(sections[3])[JOINT_LINE], [1])

    def test_source_courses_name_streams_going_with_them(self):
        """AC-1: у курса-источника ``jointWith`` — потоки, которые идут вместе с ним (пометка web.classes.joint_with
        «К этой линейке присоединяется Поток 2»); у курса Потока 1 без копии и у обычного курса — пусто.
        """
        self.openJoint()

        self.assertEqual(self.course(jointCourse(1, "Математика"))["jointWith"], [2])
        self.assertEqual(self.course(jointCourse(1, "Русский язык"))["jointWith"], [2])
        self.assertEqual(self.course(jointCourse(1, "Биология"))["jointWith"], [])
        self.assertEqual(self.course(jointCourse(1, "Математика", LEVEL_LINE))["jointWith"], [])

    def test_copy_course_takes_hours_teacher_and_slots_from_source(self):
        """AC-10: курс-копия в состоянии — ``joint`` с номером и этапом потока-источника, названием
        источника и ``waiting: False``; часы, преподаватель в расписании и уроки — как у источника;
        «ведёт», закрепления и выбор преподавателя пусты (поля на странице закрыты). У источника и
        у обычного курса ``joint`` — null.
        """
        self.openJoint()

        for subject in ("Математика", "Русский язык"):
            copy, source = self.course(jointCourse(2, subject)), self.course(jointCourse(1, subject))

            self.assertEqual(copy["joint"], {"number": 1, "stage": "1", "source": source["name"], "waiting": False})

            for key in ("hours", "scheduled", "slots"):
                self.assertEqual(copy[key], source[key], (subject, key))

            for key in ("assigned", "pinned", "options", "busyOptions"):
                self.assertEqual(copy[key], [], (subject, key))

            self.assertIsNone(source["joint"])

        self.assertEqual(self.course(jointCourse(2, "Русский язык"))["hours"], 2)
        self.assertIsNone(self.course(jointCourse(2, "Информатика"))["joint"])

    def test_copies_are_not_listed_without_teacher(self):
        """Раздел «/api» спеки (state.noTeacher — копий нет): преподавателя курса-источника убрали из
        проекта — в «уроки без преподавателя» попадает только источник, а не его копия.
        """
        self.openJoint()
        settings = self.load("settings.json")
        del settings["teachers"]["Русский язык #1"]
        self.save("settings.json", settings)

        listed = [item[0] for item in self.state()["noTeacher"]]

        self.assertIn(jointCourse(1, "Русский язык"), listed)
        self.assertNotIn(jointCourse(2, "Русский язык"), listed)

    def test_copies_wait_for_source_stream(self):
        """AC-13: Поток 1 не принят — копии «ждут Поток 1»: ``joint.waiting`` у копий, уроков нет;
        у этапа «2» на «Запуске» — ``waiting: [{"line": «ЕГЭ основной», "number": 1}]``, у остальных
        этапов пусто. Когда Поток 1 принят, ждущих нет.
        """
        self.openJoint(accepted=False)

        copy = self.course(jointCourse(2, "Математика"))
        self.assertEqual(copy["joint"], {"number": 1, "stage": "1", "source": jointCourse(1, "Математика"), "waiting": True})
        self.assertEqual(copy["slots"], [])

        stages = {item["key"]: item for item in self.state()["stages"]}
        self.assertEqual(stages["2"]["waiting"], [{"line": JOINT_LINE, "number": 1}])
        self.assertEqual(stages["1"]["waiting"], [])
        self.assertEqual(stages["3"]["waiting"], [])

        self.openJoint()

        self.assertIs(self.course(jointCourse(2, "Математика"))["joint"]["waiting"], False)
        self.assertEqual({item["key"]: item["waiting"] for item in self.state()["stages"]}["2"], [])


class JointCountsTests(RealProjectCase):
    """Сколько уроков у этапа и во всём расписании, когда «ЕГЭ основной» Потока 2 идёт вместе с Потоком 1
    (замечания проверки): уроки копий ставит Поток 1, поэтому этап «2» по ним не «в расписании»
    и не «построен», а общий урок в числе уроков — один раз. Проект — ``builders.jointProject``.
    """
    NAME = "__test_state_joint_counts__"

    def stages(self):
        """Этапы «Запуска» из состояния: ключ -> описание."""
        return {item["key"]: item for item in self.state()["stages"]}

    def test_copies_do_not_put_stage_into_schedule(self):
        """Поток 1 принят (9 уроков), Поток 2 не составлялся, у копий уроки Потока 1. У этапа «2»
        expected и placed — без копий (6 и 0), он не построен и не «в расписании» (в версии этапы —
        только «1»); уроков в неделю во всём расписании — 9, а не 13.
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)

        stage = self.stages()["2"]

        self.assertEqual((stage["expected"], stage["placed"], stage["built"]), (6, 0, False))
        self.assertEqual(self.state()["lessons"], 9)

        self.ok("newVersion", name="Проверка")
        meta = next(item for item in self.state()["versions"] if item["name"] == "Проверка")
        self.assertEqual((meta["lessons"], meta["stages"]), (9, ["1"]))

    def test_stage_of_only_copies_counts_its_copies(self):
        """В Потоке 2 только копии (все его линейки идут вместе с Потоком 1): этап построен, когда
        стоят уроки копий, и не построен, пока Поток 1 не принят.
        """
        settings, answer = jointProject(streams=2)
        removeCourses(settings, [jointCourse(2, "Информатика"), jointCourse(2, "Математика", OWN_LINE)])

        for line in (JOINT_LINE, LEVEL_LINE):
            markJoint(settings, 2, line, 1, answer)

        self.openProject(settings, answer)
        stage = self.stages()["2"]
        self.assertEqual((stage["placed"], stage["expected"], stage["built"]), (8, 8, True))

        self.openProject(settings, {})
        stage = self.stages()["2"]
        self.assertEqual((stage["placed"], stage["built"]), (0, False))


class JointCannotStateTests(RealProjectCase):
    """AC-39: предупреждение «Расписания» «Общий урок, когда преподаватель «не может»» (web.view.joint_cannot_title). Поле состояния ``jointCannot`` —
    ``[[преподаватель, день, урок, курс-копия]]``: урок копии, у преподавателя которого на этапе
    потока-копии в это время «не может». Оно есть, пока такая ситуация есть в принятом расписании.
    Проект — ``builders.jointProject``, «ЕГЭ основной» Потока 2 идёт вместе с Потоком 1 (общие уроки
    «Математики» у «Математика #1» в пн и ср 1-м уроком).
    """
    NAME = "__test_state_joint_cannot__"

    def test_shared_lesson_in_cannot_hours_is_listed(self):
        """У «Математика #1» на этапе «Поток 2» в пн 1-м уроком «не может» — там общий урок: в ``jointCannot``
        одна строка (преподаватель, день, урок, копия). Не попадают: «не может» на этапе потока-источника
        (ср 1-м уроком на «Поток 1») и «не может» на этапе «Поток 2» не в часы общих уроков (пт 3-м
        уроком у «Русский язык #1»). Накладкой (``clashes``) это не считается.
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        markCannot(settings, "Математика #1", "2", (0, 0))
        markCannot(settings, "Математика #1", "1", (2, 0))
        markCannot(settings, "Русский язык #1", "2", (4, 2))
        self.openProject(settings, answer)

        state = self.state()

        self.assertEqual(state.get("jointCannot"), [["Математика #1", 0, 0, jointCourse(2, "Математика")]])
        self.assertEqual(state["clashes"], [])

    def test_warning_goes_when_mark_is_removed_or_lessons_move(self):
        """Предупреждение есть, пока ситуация есть: «не может» сняли — ``jointCannot`` пуст; отметка снова
        стоит, но общие уроки «Математики» теперь во вт и чт 1-м уроком — тоже пуст.
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        markCannot(settings, "Математика #1", "2", (0, 0), (2, 0))
        self.openProject(settings, answer)

        self.assertEqual(sorted(self.state().get("jointCannot") or []),
                         [["Математика #1", 0, 0, jointCourse(2, "Математика")], ["Математика #1", 2, 0, jointCourse(2, "Математика")]])

        unmarked = self.load("settings.json")
        unmarked["teachers"]["Математика #1"]["availability"]["2"]["free"] = []
        self.save("settings.json", unmarked)

        self.assertEqual(self.state().get("jointCannot"), [])

        self.save("settings.json", settings)
        moved = courseWeek("Математика", "Математика #1", (1, 0), (3, 0))
        answer[jointCourse(1, "Математика")] = answer[jointCourse(2, "Математика")] = moved
        self.save("answer.json", answer)

        self.assertEqual(self.state().get("jointCannot"), [])


class StartedSourceStateTests(RealProjectCase):
    """Поток 1 ещё не начался, а его копии в Потоке 2 уже идут (действия с таким источником —
    test_web_tab_classes, StartedSourceTests)."""
    NAME = "__test_state_started_source__"

    def setUp(self):
        super().setUp()
        settings, answer = jointProject()
        shiftStream(settings, 1, FUTURE)
        shiftStream(settings, 2, PAST)
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)

    def test_source_is_shown_started(self):
        """Сервер не меняет у источника преподавателя, часы и закрепления — и страница получает
        started / locked = True и дату, с которой идут его уроки (``runningSince``, начало Потока 2).
        Курс Потока 1 без копий — как был: не идёт.
        """
        course = self.course(MATH_1)

        self.assertEqual((course["started"], course["locked"], course["runningSince"]), (True, True, PAST))
        self.assertEqual(course["start"], FUTURE)
        self.assertEqual((self.course(MATH_LEVEL_1)["started"], self.course(MATH_LEVEL_1)["runningSince"]), (False, ""))
        self.assertEqual((self.course(MATH_2)["started"], self.course(MATH_2)["runningSince"]), (True, PAST))


class BlockedStartedStateTests(RealProjectCase):
    """Поток 1 идёт; «Математике» Потока 1 не хватает урока (часов 3), у её преподавателя в пн 1-й урок —
    под её уроком — «не может»: сборка не сможет оставить этот урок на месте.
    """
    NAME = "__test_state_blocked_started__"

    def test_run_tab_warns_before_build(self):
        """Сводка этапа несёт ``blockedStarted`` (stages.blockedStarted): курс и строка «день и час: причина»
        (как movedStarted у вариантов) — «Запуск» предупреждает до сборки; прогноз закреплений этот урок
        не считает закреплённым. У этапа без таких уроков — пусто.
        """
        settings, answer = jointProject()
        setHours(settings, MATH_1, 3)
        markCannot(settings, "Математика #1", "1", (0, 0))
        self.openProject(settings, answer)

        stages = {item["key"]: item for item in self.state()["stages"]}
        line = f"{slotText(settings, 0, 0)}: {tr('menu.main.tab.classes.slot_unavailable', detail='Математика #1')}"

        self.assertEqual(stages["1"]["blockedStarted"], [{"course": MATH_1, "lines": [line]}])
        self.assertEqual(stages["2"]["blockedStarted"], [])
        self.assertEqual(stages["1"]["forecast"]["fresh"]["pinned"] + 1, sum(len(list(lessonEntries(answer, name))) for name in stageCourses(settings, "1")))

    def test_pin_context_once_per_stage(self):
        """Предупреждение и прогноз с галочкой и без берут помехи из одного stages.pinContext этапа: идущие
        курсы этапа (stages.startedPins) ищутся один раз на этап — состояние отдаётся после каждого действия.
        """
        settings, answer = jointProject()
        setHours(settings, MATH_1, 3)
        self.openProject(settings, answer)

        with mock.patch("src.modules.functions.stages.startedPins", wraps=stagesModule.startedPins) as spy:
            stages = self.state()["stages"]

        self.assertEqual(spy.call_count, len(stages))
