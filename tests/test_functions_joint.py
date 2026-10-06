"""«Линейка присоединяется к Потоку N» (`src/modules/functions/joint.py`).

Линейка потока-копии («ЕГЭ основной» Потока 2) отмечена «идёт вместе с Потоком 1»: у её курсов,
предмет которых есть в той же линейке Потока 1, поле ``together_with = 1``, часы как у курса
Потока 1 (источника), уроки в answer — копия уроков источника. Данные — ``jointProject``
(tests/builders.py): Потоки 1–3, принятый Поток 1, у «Поток 2 — ЕГЭ основной — Математика»
свои «ведёт» и закрепление.

* ``JointOptionsTests`` — какие потоки можно выбрать «вместе с» (``jointOptions``): AC-1, AC-9, AC-12;
* ``SetJointLineTests`` — включение отметки (``setJointLine``): AC-2, AC-3, AC-6;
* ``JointRefusalTests`` — отказы ``setJointLine`` без изменения данных: AC-1, AC-8, AC-9;
* ``JointRemovalTests`` — снятие отметки: AC-7, AC-8;
* ``JointSwitchTests`` — смена потока-источника (Поток 1 → Поток 2): бывшие копии, предмета которых
  в новом источнике нет, теряют общие уроки прежнего источника;
* ``JointNewSubjectTests`` — новый предмет в линейке-копии и в линейке источника: AC-4;
* ``JointReadingTests`` — ``jointSource``, ``jointCopies``, ``jointRoot``;
* ``JointSyncTests`` — синхронизация (``syncJointSettings``, ``syncJointAnswer``): AC-11 (часы), AC-34;
* ``JointSourceRemovedTests`` — удаление источника, его линейки или потока: AC-19;
* ``JointOldProjectTests`` — проект без отметок синхронизация не меняет: AC-37;
* ``JointDisjointLineTests`` — поток, где в линейке с тем же названием нет ни одного такого же предмета,
  не предлагается (``jointOptions``), а ``setJointLine`` к нему — отказ;
* ``CopyConflictsTests`` — ``copyConflicts``: помехи общих уроков ищутся и у курсов других этапов (блоки,
  другие потоки), которые идут в даты копии; курсы этапа источника не в счёт.

Отказ предметной функции — ValueError (как у других функций предметного слоя); текст для завуча
проверяют тесты сервера (test_web_tab_classes.py).

Даты: сегодня (05.10.2026) идёт только Поток 1. ``setJointLine`` получает расписание и дату
проверки «курс уже идёт» так же, как ``courses.courseStarted``: ``answer=…``, ``today=…``.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import datetime
import importlib
import unittest

from src.modules.functions.courses import (
    addCourse, addStream, copyLineToStreams, lineCourses, removeCourses, removeLine, removeStream, setSectionEnd
)
from src.modules.functions.model import groupsByName, hasLessons
from src.modules.functions.stages import stageCopies
from src.modules.functions.tree import PROJECT_FORMAT
from tests.builders import (
    JOINT_LINE, JOINT_PIN_TEACHER, JOINT_STARTS, LEVEL_LINE, OWN_LINE, courseWeek, jointCourse, jointProject, markJoint
)

# Даты проверки «курс уже идёт»: до начала Потока 2 (идёт только Поток 1) и после (идут Потоки 1 и 2)
BEFORE = datetime.date(2026, 10, 5)
LATER = datetime.date(2026, 12, 1)

MATH1, RUS1, BIO1 = jointCourse(1, "Математика"), jointCourse(1, "Русский язык"), jointCourse(1, "Биология")
MATH2, RUS2, INFO2 = jointCourse(2, "Математика"), jointCourse(2, "Русский язык"), jointCourse(2, "Информатика")
MATH3, RUS3 = jointCourse(3, "Математика"), jointCourse(3, "Русский язык")
MATH_LEVEL_1, OWN_3 = jointCourse(1, "Математика", LEVEL_LINE), jointCourse(3, "Математика", OWN_LINE)
OLD_TEACHER = "Математика #1"
# Поток 1 кончается до начала Потока 3 (11.01.2027), а Поток 2 (с 23.11.2026, без конца) — нет
STREAM_1_END = "2026-12-31"


def joint():
    """Модуль ``src.modules.functions.joint``.

    Берётся в самом тесте, а не в начале файла: пока модуля нет, каждый тест падает сам
    по себе (ModuleNotFoundError) и видно, какие критерии ещё не выполнены.
    """
    return importlib.import_module("src.modules.functions.joint")


def joinedStream2(settings, answer):
    """Пробная отметка «ЕГЭ основной» Потока 2 присоединяется к Потоку 1, как в setJoint: (settings,
    расписание с уроками копий, копии этапа «2»). Исходные ``settings`` и ``answer`` не меняются.
    """
    marked, scheduled = copy.deepcopy(settings), copy.deepcopy(answer)
    joint().setJointLine(marked, 2, JOINT_LINE, 1, scheduled)
    joint().syncJointAnswer(marked, scheduled)

    return marked, scheduled, stageCopies(marked, "2")


class JointCase(unittest.TestCase):
    """База: проект ``jointProject()`` (Потоки 1–3, принятый Поток 1) в ``self.settings`` / ``self.answer``."""
    def setUp(self):
        self.settings, self.answer = jointProject()

    def group(self, name):
        """Курс (словарь) ``name`` из ``self.settings``."""
        return groupsByName(self.settings)[name]

    def hours(self, name):
        """Нагрузка курса ``name``: {предмет: уроков в неделю}."""
        return self.settings["classes"]["lessons"][name]

    def assigned(self, name):
        """Преподаватели, которые «ведут» курс ``name``."""
        return [teacher for teacher, data in self.settings["teachers"].items()
                for item in data.get("subjects", []) if name in item.get("assigned", [])]

    def setJoint(self, section, line, source, today=BEFORE):
        """``setJointLine`` для ``self.settings`` с расписанием ``self.answer`` и датой ``today``."""
        return joint().setJointLine(self.settings, section, line, source, answer=self.answer, today=today)

    def sync(self):
        """Синхронизация, как при записи проекта: сначала settings, потом answer."""
        joint().syncJointSettings(self.settings)
        joint().syncJointAnswer(self.settings, self.answer)

    def assertRefused(self, section, line, source, today=BEFORE):
        """``setJointLine`` отказывает (ValueError), а settings и answer не меняются."""
        settings, answer = copy.deepcopy(self.settings), copy.deepcopy(self.answer)

        with self.assertRaises(ValueError):
            self.setJoint(section, line, source, today)

        self.assertEqual(self.settings, settings)
        self.assertEqual(self.answer, answer)


class JointOptionsTests(JointCase):
    """Какие потоки можно выбрать в «Присоединяется к» (``jointOptions``)."""
    def test_options_are_earlier_streams_with_same_line(self):
        """AC-1: у линейки предлагаются только более ранние потоки с линейкой того же названия."""
        options = joint().jointOptions

        self.assertEqual(options(self.settings, 2, JOINT_LINE), [1])
        self.assertEqual(options(self.settings, 2, LEVEL_LINE), [1])
        self.assertEqual(options(self.settings, 3, JOINT_LINE), [1, 2])

    def test_no_options_for_first_stream(self):
        """AC-1: у Потока 1 выбора нет — раньше потоков нет."""
        self.assertEqual(joint().jointOptions(self.settings, 1, JOINT_LINE), [])

    def test_no_options_for_line_missing_in_earlier_streams(self):
        """AC-1: «ОГЭ» нет в Потоке 1 — у Потока 2 выбора нет, а у Потока 3 есть только Поток 2."""
        self.assertEqual(joint().jointOptions(self.settings, 2, OWN_LINE), [])
        self.assertEqual(joint().jointOptions(self.settings, 3, OWN_LINE), [2])

    def test_no_options_for_block(self):
        """AC-1: у блока (майские марафоны) выбора нет, даже если в потоках есть линейка того же названия."""
        addCourse(self.settings, "may", JOINT_LINE, "Математика")

        self.assertEqual(joint().jointOptions(self.settings, "may", JOINT_LINE), [])

    def test_copy_stream_is_not_offered(self):
        """AC-9: Поток 2 идёт вместе с Потоком 1 — Потоку 3 предлагается только Поток 1 (цепочек нет)."""
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)

        self.assertEqual(joint().jointOptions(self.settings, 3, JOINT_LINE), [1])

    def test_new_stream_does_not_inherit_mark(self):
        """AC-12: новый поток после отмеченного Потока 2 — без ``together_with``, ему предлагается только Поток 1."""
        self.settings, self.answer = jointProject(streams=2)
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)

        stream = addStream(self.settings, JOINT_STARTS[3])
        joint().syncJointSettings(self.settings)

        self.assertEqual(stream, 3)
        self.assertTrue(lineCourses(self.settings, 3, JOINT_LINE))
        self.assertEqual([group["name"] for group in lineCourses(self.settings, 3, JOINT_LINE) if "together_with" in group], [])
        self.assertEqual(joint().jointOptions(self.settings, 3, JOINT_LINE), [1])


class SetJointLineTests(JointCase):
    """Включение отметки: поле у курсов-копий, часы источника, без закреплений и «ведёт», уроки источника."""
    def test_marks_courses_with_subject_in_source_line(self):
        """AC-2: ``together_with == 1`` у курсов линейки Потока 2, предмет которых есть в «ЕГЭ основной» Потока 1."""
        self.setJoint(2, JOINT_LINE, 1)

        self.assertEqual(self.group(MATH2).get("together_with"), 1)
        self.assertEqual(self.group(RUS2).get("together_with"), 1)

    def test_copy_hours_equal_source(self):
        """AC-2: уроков в неделю у копии — как у источника («Русский язык»: было 1, у Потока 1 — 2)."""
        self.assertEqual(self.hours(RUS2), {"Русский язык": 1})

        self.setJoint(2, JOINT_LINE, 1)

        self.assertEqual(self.hours(RUS2), self.hours(RUS1))
        self.assertEqual(self.hours(MATH2), self.hours(MATH1))

    def test_copy_loses_pins_and_assigned_teacher(self):
        """AC-2: у копии нет закреплений (constants), её никто не «ведёт» (было: закрепление и «ведёт» у Математики)."""
        self.assertIn(MATH2, self.settings["constants"])
        self.assertEqual(self.assigned(MATH2), [JOINT_PIN_TEACHER])

        self.setJoint(2, JOINT_LINE, 1)

        self.assertNotIn(MATH2, self.settings["constants"])
        self.assertEqual(self.assigned(MATH2), [])

    def test_copy_lessons_follow_source(self):
        """AC-2: после записи answer у копий — уроки источника (тот же день, урок, предмет, преподаватель)."""
        self.setJoint(2, JOINT_LINE, 1)
        joint().syncJointAnswer(self.settings, self.answer)

        self.assertEqual(self.answer[MATH2], self.answer[MATH1])
        self.assertEqual(self.answer[RUS2], self.answer[RUS1])

    def test_copy_of_source_without_lessons_has_no_key(self):
        """AC-2: у источника нет уроков — ключа копии в answer нет («ждёт Поток 1»), даже если он был."""
        del self.answer[RUS1]
        self.answer[RUS2] = courseWeek("Русский язык", "Русский язык #3", (4, 1))

        self.setJoint(2, JOINT_LINE, 1)
        joint().syncJointAnswer(self.settings, self.answer)

        self.assertNotIn(RUS2, self.answer)
        self.assertEqual(self.answer[MATH2], self.answer[MATH1])

    def test_subject_missing_in_source_stays_ordinary(self):
        """AC-3: «Информатики» нет в «ЕГЭ основной» Потока 1 — курс Потока 2 обычный: без поля, со своими часами."""
        self.setJoint(2, JOINT_LINE, 1)
        self.sync()

        self.assertNotIn("together_with", self.group(INFO2))
        self.assertEqual(self.hours(INFO2), {"Информатика": 1})
        self.assertIsNone(joint().jointSource(self.settings, self.group(INFO2)))

    def test_subject_missing_in_copy_does_not_appear(self):
        """AC-3: «Биология» есть только в Потоке 1 — в Потоке 2 не появляется ни курс, ни уроки."""
        biology = jointCourse(2, "Биология")

        self.setJoint(2, JOINT_LINE, 1)
        self.sync()

        self.assertNotIn(biology, groupsByName(self.settings))
        self.assertNotIn(biology, self.answer)
        self.assertNotIn(biology, joint().jointCopies(self.settings))

    def test_other_lines_untouched(self):
        """AC-2: отметка ставится только линейке «ЕГЭ основной» Потока 2 — другие линейки и потоки без поля."""
        self.setJoint(2, JOINT_LINE, 1)

        marked = sorted(group["name"] for group in self.settings["classes"]["custom_groups"] if "together_with" in group)

        self.assertEqual(marked, sorted([MATH2, RUS2]))

    def test_same_lessons_already_running_allowed(self):
        """AC-6, AC-8: копия уже идёт с теми же уроками, что у источника, — отметка ставится, уроки не меняются."""
        self.answer[MATH2] = copy.deepcopy(self.answer[MATH1])
        answer = copy.deepcopy(self.answer)

        self.setJoint(2, JOINT_LINE, 1, today=LATER)
        joint().syncJointAnswer(self.settings, self.answer)

        self.assertEqual(self.group(MATH2).get("together_with"), 1)
        self.assertEqual(self.answer[MATH2], answer[MATH2])

    def test_marking_again_keeps_mark(self):
        """AC-2: повторная отметка той же линейки ничего не портит: поле, часы и уроки те же."""
        self.setJoint(2, JOINT_LINE, 1)
        self.sync()
        settings, answer = copy.deepcopy(self.settings), copy.deepcopy(self.answer)

        self.setJoint(2, JOINT_LINE, 1)
        self.sync()

        self.assertEqual(self.settings, settings)
        self.assertEqual(self.answer, answer)


class JointRefusalTests(JointCase):
    """Отказы ``setJointLine``: ValueError, settings и answer не меняются."""
    def test_block_refused(self):
        """AC-1: у блока отметки нет — отказ."""
        addCourse(self.settings, "may", JOINT_LINE, "Математика")

        self.assertRefused("may", JOINT_LINE, 1)

    def test_source_not_earlier_refused(self):
        """AC-1: источник — свой или более поздний поток — отказ."""
        for section, source in ((2, 2), (2, 3), (1, 1), (1, 2)):
            with self.subTest(section=section, source=source):
                self.assertRefused(section, JOINT_LINE, source)

    def test_source_without_line_refused(self):
        """AC-1: в Потоке 1 нет линейки «ОГЭ» — отметка «ОГЭ» Потока 2 вместе с Потоком 1 отклоняется."""
        self.assertRefused(2, OWN_LINE, 1)

    def test_running_copy_with_other_lessons_refused(self):
        """AC-8: курс Потока 2 уже идёт с уроками, не как в Потоке 1, — включить отметку нельзя."""
        self.answer[MATH2] = courseWeek("Математика", JOINT_PIN_TEACHER, (4, 0), (4, 1))

        self.assertRefused(2, JOINT_LINE, 1, today=LATER)

    def test_not_started_copy_with_other_lessons_allowed(self):
        """AC-8: те же уроки, но Поток 2 ещё не начался — отметка ставится (вопрос задаёт сервер, AC-5)."""
        self.answer[MATH2] = courseWeek("Математика", JOINT_PIN_TEACHER, (4, 0), (4, 1))

        self.setJoint(2, JOINT_LINE, 1, today=BEFORE)

        self.assertEqual(self.group(MATH2).get("together_with"), 1)

    def test_copy_as_source_refused(self):
        """AC-9: Поток 2 сам идёт вместе с Потоком 1 — Поток 3 не может выбрать Поток 2."""
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)

        self.assertRefused(3, JOINT_LINE, 2)

    def test_source_of_other_stream_cannot_become_copy(self):
        """AC-9: Поток 3 уже идёт вместе с Потоком 2 — Поток 2 не может стать копией Потока 1."""
        markJoint(self.settings, 3, JOINT_LINE, 2, self.answer)

        self.assertRefused(2, JOINT_LINE, 1)


class JointRemovalTests(JointCase):
    """Снятие отметки (``source=None``)."""
    def setUp(self):
        super().setUp()
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)

    def test_removal_clears_field_on_whole_line(self):
        """AC-7: после снятия ни у одного курса «ЕГЭ основной» Потока 2 нет ``together_with``."""
        self.setJoint(2, JOINT_LINE, None)

        self.assertEqual([group["name"] for group in lineCourses(self.settings, 2, JOINT_LINE) if "together_with" in group], [])
        self.assertEqual(joint().jointCopies(self.settings), {})

    def test_removal_drops_copy_lessons(self):
        """AC-7: уроки бывших копий удалены из answer, уроки Потока 1 на месте; запись answer их не возвращает."""
        accepted = copy.deepcopy({name: self.answer[name] for name in (MATH1, RUS1, BIO1)})
        self.assertIn(MATH2, self.answer)

        self.setJoint(2, JOINT_LINE, None)
        self.sync()

        self.assertNotIn(MATH2, self.answer)
        self.assertNotIn(RUS2, self.answer)
        self.assertEqual({name: self.answer[name] for name in (MATH1, RUS1, BIO1)}, accepted)

    def test_removal_keeps_hours(self):
        """AC-7: часы остаются прежними — «Русский язык» Потока 2 остаётся с 2 уроками (как стало при отметке)."""
        self.setJoint(2, JOINT_LINE, None)
        self.sync()

        self.assertEqual(self.hours(RUS2), {"Русский язык": 2})
        self.assertEqual(self.hours(MATH2), {"Математика": 2})

    def test_removed_courses_are_auto(self):
        """AC-7: бывшие копии снова обычные «авто»: без закреплений и без «ведёт»."""
        self.setJoint(2, JOINT_LINE, None)

        self.assertNotIn(MATH2, self.settings.get("constants", {}))
        self.assertEqual(self.assigned(MATH2), [])
        self.assertIsNone(joint().jointSource(self.settings, self.group(MATH2)))

    def test_removal_refused_when_copy_running(self):
        """AC-8: копия уже идёт (Поток 2 начался, уроки есть) — снять отметку нельзя."""
        self.assertRefused(2, JOINT_LINE, None, today=LATER)


class JointSwitchTests(JointCase):
    """Смена потока-источника у присоединённой линейки (``setJointLine`` с другим потоком)."""
    def setUp(self):
        # «История» есть в «ЕГЭ основной» Потоков 1 и 3, но не Потока 2; в Потоке 1 она принята,
        # Поток 3 отмечен «присоединяется к Потоку 1» — его «История» копия с общим уроком
        super().setUp()
        self.history_1 = addCourse(self.settings, 1, JOINT_LINE, "История", 1, "2026-09-07")
        self.history_3 = addCourse(self.settings, 3, JOINT_LINE, "История", 1, "2027-01-11")
        self.answer[self.history_1] = courseWeek("История", "История #1", (4, 1))
        markJoint(self.settings, 3, JOINT_LINE, 1, self.answer)

    def test_former_copy_without_counterpart_loses_lessons(self):
        """Поток 3 был с Потоком 1, выбрали Поток 2: «История» Потока 3 больше не копия, её общий урок
        Потока 1 убран (иначе «История #1» была бы занята дважды), и она названа среди курсов,
        чьи уроки пропадут. Копии Математики и Русского языка теперь — Потока 2.
        """
        self.assertTrue(hasLessons(self.answer, self.history_3))

        changed = self.setJoint(3, JOINT_LINE, 2)
        self.sync()

        self.assertIn(self.history_3, changed)
        self.assertNotIn("together_with", self.group(self.history_3))
        self.assertNotIn(self.history_3, self.answer)
        self.assertEqual(self.group(MATH3)["together_with"], 2)

    def test_unmark_still_drops_copy_lessons(self):
        """Снятие отметки по-прежнему убирает уроки всех бывших копий, в том числе «Истории»."""
        changed = self.setJoint(3, JOINT_LINE, None)

        self.assertIn(self.history_3, changed)
        self.assertFalse(any(hasLessons(self.answer, name) for name in (self.history_3, MATH3)))


class JointNewSubjectTests(JointCase):
    """Новый предмет в линейке-копии (``newCourse``: курс добавляется и линейка отмечается снова)."""
    def setUp(self):
        super().setUp()
        self.setJoint(2, JOINT_LINE, 1)
        self.sync()

    def test_new_subject_from_source_becomes_copy(self):
        """AC-4: «Биология» есть в Потоке 1 — новый курс Потока 2 сразу копия: поле, часы и уроки источника."""
        biology = addCourse(self.settings, 2, JOINT_LINE, "Биология", 3)

        self.setJoint(2, JOINT_LINE, 1)
        self.sync()

        self.assertEqual(self.group(biology).get("together_with"), 1)
        self.assertEqual(self.hours(biology), self.hours(BIO1))
        self.assertEqual(self.answer[biology], self.answer[BIO1])

    def test_new_subject_missing_in_source_stays_ordinary(self):
        """AC-4: «Физики» нет в Потоке 1 — новый курс Потока 2 обычный, без поля и уроков."""
        physics = addCourse(self.settings, 2, JOINT_LINE, "Физика", 3)

        self.setJoint(2, JOINT_LINE, 1)
        self.sync()

        self.assertNotIn("together_with", self.group(physics))
        self.assertEqual(self.hours(physics), {"Физика": 3})
        self.assertNotIn(physics, self.answer)

    def test_subject_added_to_source_not_added_to_copy(self):
        """AC-4: предмет, добавленный в линейку Потока 1, в Поток 2 сам не добавляется."""
        addCourse(self.settings, 1, JOINT_LINE, "Физика", 2)

        self.sync()

        self.assertNotIn(jointCourse(2, "Физика"), groupsByName(self.settings))
        self.assertNotIn(jointCourse(2, "Физика"), self.answer)


class JointReadingTests(JointCase):
    """Чтение отметки: ``jointSource``, ``jointCopies``, ``jointRoot`` (Р-2, Р-3)."""
    def setUp(self):
        super().setUp()
        self.setJoint(2, JOINT_LINE, 1)

    def test_source_of_copy(self):
        """AC-2: источник копии — курс того же предмета в той же линейке Потока 1; у обычного курса — None."""
        self.assertEqual(joint().jointSource(self.settings, self.group(MATH2)), MATH1)
        self.assertEqual(joint().jointSource(self.settings, self.group(RUS2)), RUS1)
        self.assertIsNone(joint().jointSource(self.settings, self.group(MATH1)))
        self.assertIsNone(joint().jointSource(self.settings, self.group(INFO2)))

    def test_copies(self):
        """AC-2: ``jointCopies`` — все копии проекта: {копия: источник}."""
        self.assertEqual(joint().jointCopies(self.settings), {MATH2: MATH1, RUS2: RUS1})

    def test_copies_of_two_streams(self):
        """AC-9: Потоки 2 и 3 вместе с Потоком 1 — у источника две копии, источник у обеих корневой."""
        self.setJoint(3, JOINT_LINE, 1)

        self.assertEqual(joint().jointCopies(self.settings), {MATH2: MATH1, RUS2: RUS1, MATH3: MATH1, RUS3: RUS1})

    def test_root(self):
        """AC-2: ``jointRoot`` — источник для копии и само имя для источника и обычного курса."""
        root = joint().jointRoot

        self.assertEqual(root(self.settings, MATH2), MATH1)
        self.assertEqual(root(self.settings, MATH1), MATH1)
        self.assertEqual(root(self.settings, INFO2), INFO2)


class JointSyncTests(JointCase):
    """Синхронизация при записи проекта: ``syncJointSettings`` и ``syncJointAnswer``."""
    def test_source_hours_reach_copy(self):
        """AC-11: часы источника поменяли — после записи settings у копии те же часы."""
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        self.settings["classes"]["lessons"][RUS1] = {"Русский язык": 3}

        joint().syncJointSettings(self.settings)

        self.assertEqual(self.hours(RUS2), {"Русский язык": 3})

    def test_copy_line_cannot_change_copy_hours(self):
        """AC-11: «Скопировать линейку» из Потока 3 (кроме идущего Потока 1) дала копии 1 урок — запись возвращает 2, как у источника."""
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)

        copyLineToStreams(self.settings, 3, JOINT_LINE, skip=(1,))
        self.assertEqual(self.hours(RUS2), {"Русский язык": 1})

        joint().syncJointSettings(self.settings)

        self.assertEqual(self.hours(RUS2), self.hours(RUS1))
        self.assertEqual(self.hours(RUS1), {"Русский язык": 2})

    def test_consistent_project_unchanged(self):
        """AC-34: копии равны источникам — синхронизация ничего не меняет ни в settings, ни в answer."""
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        settings, answer = copy.deepcopy(self.settings), copy.deepcopy(self.answer)

        self.sync()

        self.assertEqual(self.settings, settings)
        self.assertEqual(self.answer, answer)

    def test_edited_copy_restored(self):
        """AC-34: копию правили руками (часы и уроки) — первая же запись приводит её к источнику, вторая ничего не меняет."""
        markJoint(self.settings, 2, JOINT_LINE, 1, sync=False)
        self.answer[MATH2] = courseWeek("Математика", JOINT_PIN_TEACHER, (4, 0), (4, 1))

        self.sync()

        self.assertEqual(self.hours(RUS2), self.hours(RUS1))
        self.assertEqual(self.answer[MATH2], self.answer[MATH1])
        self.assertEqual(self.answer[RUS2], self.answer[RUS1])

        settings, answer = copy.deepcopy(self.settings), copy.deepcopy(self.answer)
        self.sync()

        self.assertEqual(self.settings, settings)
        self.assertEqual(self.answer, answer)

    def test_copy_without_source_lessons_removed(self):
        """AC-34: у источника уроков нет, а у копии в файле есть — запись answer убирает уроки копии."""
        self.settings, self.answer = jointProject(accepted=False)
        markJoint(self.settings, 2, JOINT_LINE, 1)
        self.answer[MATH2] = courseWeek("Математика", JOINT_PIN_TEACHER, (4, 0), (4, 1))

        self.sync()

        self.assertNotIn(MATH2, self.answer)

    def test_ordinary_courses_untouched(self):
        """AC-34: синхронизация не трогает обычные курсы: уроки и часы «Информатики» Потока 2 остаются."""
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        self.answer[INFO2] = courseWeek("Информатика", "Информатика #1", (2, 2))
        week = copy.deepcopy(self.answer[INFO2])

        self.sync()

        self.assertEqual(self.answer[INFO2], week)
        self.assertEqual(self.hours(INFO2), {"Информатика": 1})


class JointSourceRemovedTests(JointCase):
    """Источник удалён: бывшие копии становятся обычными курсами со своими уроками (Р-7)."""
    def setUp(self):
        super().setUp()
        markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        self.lessons = copy.deepcopy({MATH2: self.answer[MATH2], RUS2: self.answer[RUS2]})

    def remove(self, courses):
        """Как сервер: удалить курсы из settings (уже сделано вызывающим) и их уроки из answer, затем записать проект."""
        for name in courses:
            self.answer.pop(name, None)

        self.sync()

    def assertOrdinary(self, *names):
        """Курсы ``names`` — обычные: без поля, не в ``jointCopies``, их уроки в answer прежние."""
        copies = joint().jointCopies(self.settings)

        for name in names:
            self.assertNotIn("together_with", self.group(name), name)
            self.assertNotIn(name, copies, name)
            self.assertEqual(self.answer[name], self.lessons[name], name)

    def test_delete_source_course(self):
        """AC-19: удалён курс-источник «Математика» — её копия обычная с уроками, «Русский язык» по-прежнему копия."""
        removeCourses(self.settings, [MATH1])
        self.remove([MATH1])

        self.assertOrdinary(MATH2)
        self.assertEqual(self.group(RUS2).get("together_with"), 1)
        self.assertEqual(self.answer[RUS2], self.answer[RUS1])

    def test_delete_source_line(self):
        """AC-19: удалена линейка «ЕГЭ основной» Потока 1 — все копии обычные, уроки сохранены."""
        removed = [group["name"] for group in lineCourses(self.settings, 1, JOINT_LINE)]
        removeLine(self.settings, 1, JOINT_LINE)
        self.remove(removed)

        self.assertOrdinary(MATH2, RUS2)
        self.assertEqual(joint().jointCopies(self.settings), {})

    def test_delete_source_stream(self):
        """AC-19: удалён Поток 1 — копии обычные, уроки сохранены, висячих отметок нет ни у одного курса."""
        removed = [group["name"] for group in self.settings["classes"]["custom_groups"] if group.get("stream_id") == 1]
        removeStream(self.settings, 1)
        self.remove(removed)

        self.assertOrdinary(MATH2, RUS2)
        self.assertEqual([group["name"] for group in self.settings["classes"]["custom_groups"] if "together_with" in group], [])

    def test_vanished_source_reads_as_none(self):
        """AC-19: пока поле ещё стоит, а источника уже нет, ``jointSource`` мягко отвечает None, ``jointRoot`` — само имя."""
        removeCourses(self.settings, [MATH1])

        self.assertIsNone(joint().jointSource(self.settings, self.group(MATH2)))
        self.assertEqual(joint().jointRoot(self.settings, MATH2), MATH2)
        self.assertNotIn(MATH2, joint().jointCopies(self.settings))

    def test_answer_sync_before_settings_keeps_lessons(self):
        """AC-19: запись answer раньше settings не стирает уроки копии, источник которой удалён."""
        removeCourses(self.settings, [MATH1])
        self.answer.pop(MATH1)

        joint().syncJointAnswer(self.settings, self.answer)

        self.assertEqual(self.answer[MATH2], self.lessons[MATH2])


class JointOldProjectTests(JointCase):
    """Старые проекты (без поля ``together_with``) работают как раньше."""
    def test_project_without_marks_unchanged_by_sync(self):
        """AC-37: в проекте нет ни одной отметки — копий нет, синхронизация при записи и открытии
        не меняет ни settings, ни answer (в том числе разные часы «Русского языка» в Потоках 1 и 2
        и свои «ведёт» и закрепление у Математики Потока 2), формат проекта прежний (1).
        """
        settings, answer = copy.deepcopy(self.settings), copy.deepcopy(self.answer)

        self.assertEqual(joint().jointCopies(self.settings), {})
        self.sync()

        self.assertEqual(self.settings, settings)
        self.assertEqual(self.answer, answer)
        self.assertEqual(self.settings["format"], PROJECT_FORMAT)
        self.assertEqual(PROJECT_FORMAT, 1)


class JointDisjointLineTests(JointCase):
    """``jointOptions`` и ``setJointLine``: поток без единого такого же предмета в линейке не предлагается."""
    def setUp(self):
        # Линейка «Новая»: в Потоке 1 — Математика, в Потоке 2 — Информатика (общих предметов нет)
        super().setUp()
        addCourse(self.settings, 1, "Новая", "Математика", 1, "2026-09-07")
        addCourse(self.settings, 2, "Новая", "Информатика", 1, "2026-11-23")

    def test_disjoint_line_not_offered(self):
        """У «Новой» Потока 2 выбора нет; у «ЕГЭ основной» Поток 1 по-прежнему предлагается."""
        self.assertEqual(joint().jointOptions(self.settings, 2, "Новая"), [])
        self.assertEqual(joint().jointOptions(self.settings, 2, JOINT_LINE), [1])

    def test_disjoint_line_refused(self):
        """setJointLine к такому потоку — отказ "invalid", данные не меняются."""
        settings, answer = copy.deepcopy(self.settings), copy.deepcopy(self.answer)

        with self.assertRaises(ValueError) as caught:
            joint().setJointLine(settings, 2, "Новая", 1, answer)

        self.assertEqual(caught.exception.args, ("invalid", None))
        self.assertEqual((settings, answer), (self.settings, self.answer))


class CopyConflictsTests(JointCase):
    """``copyConflicts``: помехи от новых часов копии в датах её потока."""
    def setUp(self):
        # Поток 1 кончается до начала Потока 3: его уроки Потоку 3 не мешают, а уроки копий Потока 2 — мешают
        super().setUp()
        setSectionEnd(self.settings, 1, STREAM_1_END)

    def test_other_stage_peer_is_found(self):
        """«ОГЭ» Математику Потока 3 ведёт «Математика #1» в пн 1-м уроком — там же встанет общий урок
        Математики Потока 2 с тем же преподавателем: помеха "busy" (раньше смотрелись только курсы Потока 2).
        """
        self.answer[OWN_3] = courseWeek("Математика", OLD_TEACHER, (0, 0))
        marked, scheduled, copies = joinedStream2(self.settings, self.answer)

        self.assertEqual(joint().copyConflicts(marked, scheduled, self.answer, copies), {2: [(0, 0, "busy", OWN_3)]})

    def test_source_stage_peers_are_not_copy_conflicts(self):
        """Накладка внутри Потока 1 (у источника и «ЕГЭ продвинутый» Математики Потока 1 один преподаватель
        в пн 1-м уроком) — это накладка самого источника, а не новая помеха потока-копии.
        """
        self.answer[MATH_LEVEL_1] = courseWeek("Математика", OLD_TEACHER, (0, 0), (2, 0))
        marked, scheduled, copies = joinedStream2(self.settings, self.answer)

        self.assertEqual(joint().copyConflicts(marked, scheduled, self.answer, copies), {})

    def test_same_stage_only(self):
        """``same_stage`` (вопрос «вариант собран при других часах источника»): помеха Потока 3 не названа —
        вариант этапа «2» её не ставил.
        """
        self.answer[OWN_3] = courseWeek("Математика", OLD_TEACHER, (0, 0))
        marked, scheduled, copies = joinedStream2(self.settings, self.answer)

        self.assertEqual(joint().copyConflicts(marked, scheduled, self.answer, copies, same_stage=True), {})
