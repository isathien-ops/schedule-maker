"""Варианты расписания этапа (`src/modules/functions/variants.py`).

Решатель за один запуск этапа даёт несколько вариантов; пользователь сравнивает их по метрикам
(штрафам) и принимает один — он записывается в answer.json («принятое расписание»).

* ``VariantTests`` — метрики варианта (``variantMetrics``), оценка и порядок вариантов,
  сохранение и удаление вариантов на диске, принят ли вариант;
* ``VariantChecksTests`` — принят ли вариант (``isAccepted``) и подсчёт непоставленных уроков (``missing``);
* ``VariantMarksTests`` — метки «принят» (accepted.json) и «отклонён» (rejected.json), какие курсы
  шли при сборке, и их уроки на начало сборки (started.json), в том числе испорченные файлы меток;
* ``VariantStorageEdgeTests`` — чтение вариантов с посторонними и испорченными файлами, своё правило
  в итоге варианта;
* ``LessonIssueTests`` — подписи на карточках уроков (``lessonIssues``);
* ``MissingDetailsTests`` — почему урок не встал: нет преподавателя, лимит курсов, нет времени,
  мешают правила (в том числе час, закрытый курсу правилом ``blocked_slots``, — «rules», а не «no_time»);
* ``WeightKeysTests`` — имена весов совпадают в weights.json, ``WEIGHT_ORDER``, ``METRICS``, solve.cpp
  и у подписей ru.hjson;
* ``JointVariantTests`` — «Линейка присоединяется к Потоку N»: метрики варианта потока-копии (уровни
  и пары — с копиями, преподаватель и нехватка — без них), варианты Потока N рядом с принятыми
  копиями, лимит курсов и «принят» без учёта копий;
* ``JointIssuesTests`` — подписи уроков в варианте потока-копии: у копий их нет, помеха подписана
  у урока потока;
* ``TeacherOverLimitTests`` — «Смена преподавателя в подборе» (.spec/teacher-swap/SPEC.md):
  сторож лимита курсов ``teacherOverLimit`` (AC-20);
* ``StageClashTests`` — после подмены зафиксированных курсов уроками из расписания
  (stages.lockedFromAnswer) у преподавателя может оказаться два урока сразу внутри этапа: это накладка
  (``variantClashes``) и подпись web.issue.teacher_twice (``lessonIssues``).
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from src.modules.translate import tr, translate
from src.modules.functions.courses import addCourse, setTeacherCourseState
from src.modules.functions.grid import setDayGrid
from src.modules.functions.model import teacherAvailability
from src.modules.functions.penalties import newPenalty
from src.modules.functions.stages import lockedFromAnswer, stageCourses
from src.modules.functions.variants import (
    acceptedNumber, allTied, buildStarted, clearStaleVariants, clearVariants, dropUnknownTeachers, isAccepted, lessonIssues, loadVariants,
    markAccepted, missingDetails, rankVariants, rejectedNumbers, saveBuildStarted, saveVariant, setRejected, unacceptable, variantClashes, variantMetrics,
    variantScore,
    METRICS, WEIGHT_ORDER, variantsDir
)
from tests.builders import (
    JOINT_LINE, LEVEL_LINE, OWN_LINE, TempFolderCase, baseSettings, courseWeek, emptyWeek, jointCourse, jointProject, lesson,
    makeSettings, markJoint, place, setDates, shiftStream, stageVariant, teacher, teacherWithCourses, writeText
)
from tests.real_project import FrozenDate

WEIGHTS = {"equalLessons": 25, "teacherFreeTime": 10, "teacherPossibleSlot": 300, "softSubjectPair": 1000}
START = "2026-09-07"
# Дата начала в прошлом: курс с уроками в расписании «уже идёт» при любой сегодняшней дате
PAST = "2020-01-01"


class VariantTests(unittest.TestCase):
    """Метрики, хранение и принятие вариантов на маленьком примере потока 1."""
    def setUp(self):
        """Три курса потока 1 (химия и биология ЕГЭ основной, физика ОГЭ) и учитель с «может» в слоте 0-2."""
        self.settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}, "soft_subject_pairs": [["Химия", "Биология"]]}

        self.chemistry = addCourse(self.settings, 1, "ЕГЭ основной", "Химия", 2, "2026-09-07")
        self.biology = addCourse(self.settings, 1, "ЕГЭ основной", "Биология", 1, "2026-09-07")
        self.oge = addCourse(self.settings, 1, "ОГЭ", "Физика", 1, "2026-09-07")

        self.settings["teachers"]["Иванова Анна"] = {"subjects": [], "availability": {"1": {"free": [], "possible": [[0, 2]]}}}

    def test_metrics(self):
        """Метрики варианта считают каждое нарушение так, как его видит пользователь: непоставленные
        уроки, пары «нежелательно» в одно время, «может», окна, два урока в день; в итог идут
        только мягкие правила; пары «можно» и разные линейки потока могут совпадать по времени.
        """
        chemistry = place(place(emptyWeek(), 0, 0, "Химия", "Иванова Анна"), 0, 2, "Химия", "Иванова Анна")
        biology = place(emptyWeek(), 0, 0, "Биология", "Петров Пётр")
        oge = emptyWeek()

        metrics = variantMetrics(self.settings, "1", {self.chemistry: chemistry, self.biology: biology, self.oge: oge}, WEIGHTS)

        self.assertEqual(metrics["missing"], 1)              # физика не поставлена
        self.assertEqual(metrics["softSubjectPair"], 1)      # химия и биология одной линейки в 0-0 — пара "нежелательно"
        self.assertEqual(metrics["pairsSameDay"], 1)         # и в один день (понедельник): только для сведения
        self.assertNotIn("lineOverlap", metrics)             # общего правила «любые предметы линейки» больше нет
        self.assertEqual(metrics["teacherPossibleSlot"], 1)  # 0-2 для учителя — "может"
        self.assertEqual(metrics["teacherFreeTime"], 1)      # 0-1 — окно между её уроками
        self.assertEqual(metrics["equalLessons"], 1)         # два урока химии в понедельник
        self.assertEqual(metrics["weekend"], 0)
        # В итог входят только мягкие правила; непоставленные и сдвоенные уроки показываются отдельно
        self.assertEqual(metrics["total"], 1000 + 300 + 10)

        # Другая линейка потока может совпадать по времени свободно
        oge = place(emptyWeek(), 0, 0, "Физика", "Сидоров Иван")
        metrics = variantMetrics(self.settings, "1", {self.chemistry: chemistry, self.biology: biology, self.oge: oge}, WEIGHTS)
        self.assertEqual((metrics["missing"], metrics["softSubjectPair"]), (0, 1))

        # Пара «можно» (химия и биология без отметки «нежелательно») совпадать по времени может
        self.settings["soft_subject_pairs"] = []
        metrics = variantMetrics(self.settings, "1", {self.chemistry: chemistry, self.biology: biology, self.oge: oge}, WEIGHTS)
        self.assertEqual(metrics["softSubjectPair"], 0)

    def test_levels_of_one_subject_together(self):
        """Русский ЕГЭ основной и ЕГЭ продвинутый в одно время — не пересечение, а как и надо (ученик может
        перейти с уровня на уровень). В разное время — неудобство «ЕГЭ осн. и продв. не одновременно» (столбец «Предпросмотра») и подпись на карточке.
        """
        basic = addCourse(self.settings, 1, "ЕГЭ основной", "Русский язык", 1, "2026-09-07")
        advanced = addCourse(self.settings, 1, "ЕГЭ продвинутый", "Русский язык", 1, "2026-09-07")
        weights = dict(WEIGHTS, levelsApart=300)

        together = {basic: place(emptyWeek(), 1, 0, "Русский язык", "Иванова"), advanced: place(emptyWeek(), 1, 0, "Русский язык", "Петрова")}
        metrics = variantMetrics(self.settings, "1", together, weights)
        self.assertEqual((metrics["softSubjectPair"], metrics["levelsApart"]), (0, 0))
        self.assertNotIn(basic, lessonIssues(self.settings, "1", together))

        apart = {basic: place(emptyWeek(), 1, 0, "Русский язык", "Иванова"), advanced: place(emptyWeek(), 2, 0, "Русский язык", "Петрова")}
        metrics = variantMetrics(self.settings, "1", apart, weights)
        self.assertEqual((metrics["softSubjectPair"], metrics["levelsApart"], metrics["total"]), (0, 1, 300))
        self.assertEqual(lessonIssues(self.settings, "1", apart)[basic]["1-0"], ["ЕГЭ продв. — в другой день или час"])

    def test_same_day_label_names_only_that_day(self):
        """«В тот же день» — только у уроков в общий день пары и только с уроками другого курса этого дня;
        в метрике пара считается один раз на общий день.
        """
        chemistry = place(place(emptyWeek(), 0, 2, "Химия", "Иванова Анна"), 1, 0, "Химия", "Иванова Анна")
        biology = place(place(emptyWeek(), 0, 0, "Биология", "Петров Пётр"), 2, 1, "Биология", "Петров Пётр")
        variant = {self.chemistry: chemistry, self.biology: biology, self.oge: emptyWeek()}

        issues = lessonIssues(self.settings, "1", variant)

        self.assertIn({"text": "В тот же день: Биология (ЕГЭ осн.)", "level": "warn"}, issues[self.chemistry]["0-2"])
        self.assertNotIn("1-0", issues.get(self.chemistry, {}))
        self.assertNotIn("2-1", issues.get(self.biology, {}))
        self.assertEqual(variantMetrics(self.settings, "1", variant, WEIGHTS)["pairsSameDay"], 1)

    def test_level_label_only_for_lessons_without_pair(self):
        """Уровни ЕГЭ частично в одно время: урок, у которого другой уровень стоит тогда же, не подписан,
        остальные уроки обоих курсов (уроков поровну) — подписаны.
        """
        basic = addCourse(self.settings, 1, "ЕГЭ основной", "Русский язык", 2, "2026-09-07")
        advanced = addCourse(self.settings, 1, "ЕГЭ продвинутый", "Русский язык", 2, "2026-09-07")
        variant = {
            basic: place(place(emptyWeek(), 1, 0, "Русский язык", "Иванова"), 2, 0, "Русский язык", "Иванова"),
            advanced: place(place(emptyWeek(), 1, 0, "Русский язык", "Петрова"), 3, 0, "Русский язык", "Петрова"),
        }

        issues = lessonIssues(self.settings, "1", variant)

        self.assertNotIn("1-0", issues[basic])
        self.assertEqual(issues[basic]["2-0"], ["ЕГЭ продв. — в другой день или час"])
        self.assertEqual(list(issues[advanced]), ["3-0"])
        self.assertEqual(variantMetrics(self.settings, "1", variant, WEIGHTS)["levelsApart"], 1)

    def test_ranking_marks_best_and_tie(self):
        """Порядок — по обязательным нарушениям, потом по итогу, потом по номеру; «лучший» — первый
        не отклонённый; «ничья» — когда таких с той же оценкой несколько.
        """
        def item(number, total, missing=0, rejected=False):
            metrics = {"missing": missing, "equalLessons": 0, "teacherClash": 0, "total": total}
            return {"number": number, "metrics": metrics, "rejected": rejected}

        self.assertEqual(variantScore(item(1, 50, missing=2)["metrics"]), (2, 50))

        ranked = rankVariants([item(1, 50, missing=1), item(2, 70), item(3, 10, rejected=True), item(4, 70)])
        self.assertEqual([entry["number"] for entry in ranked], [3, 2, 4, 1])
        self.assertEqual([(entry["best"], entry["tied"]) for entry in ranked], [(False, False), (True, True), (False, True), (False, False)])

        ranked = rankVariants([item(1, 70), item(2, 60)])
        self.assertEqual([(entry["number"], entry["best"], entry["tied"]) for entry in ranked], [(2, True, False), (1, False, False)])

        ranked = rankVariants([item(1, 70, rejected=True)])
        self.assertEqual((ranked[0]["best"], ranked[0]["tied"]), (False, False))

    def test_all_tied_compares_full_score(self):
        """«Можно принять любой» — только когда у всех не отклонённых вариантов (их больше одного)
        одинаковая полная оценка: одинаковый итог при нехватке уроков у одного — это не ничья.
        """
        def item(number, total, missing=0, rejected=False):
            metrics = {"missing": missing, "equalLessons": 0, "teacherClash": 0, "total": total}
            return {"number": number, "metrics": metrics, "rejected": rejected}

        self.assertTrue(allTied(rankVariants([item(1, 70), item(2, 70)])))
        self.assertFalse(allTied(rankVariants([item(1, 70), item(2, 70, missing=1)])))
        self.assertTrue(allTied(rankVariants([item(1, 70), item(2, 70), item(3, 10, rejected=True)])))
        self.assertFalse(allTied(rankVariants([item(1, 70), item(2, 70, rejected=True)])))
        self.assertFalse(allTied(rankVariants([])))

    def test_stale_variant_is_never_best(self):
        """Вариант, собранный до начала идущих курсов (staleStarted не пуст), принять нельзя: он идёт
        после принимаемых даже с лучшей оценкой, не «лучший», не в «ничьей» и не даёт «можно принять любой».
        """
        def item(number, total, stale=()):
            metrics = {"missing": 0, "equalLessons": 0, "teacherClash": 0, "total": total}
            return {"number": number, "metrics": metrics, "rejected": False, "staleStarted": list(stale)}

        ranked = rankVariants([item(1, 10, stale=["Курс"]), item(2, 70), item(3, 70)])
        self.assertEqual([(entry["number"], entry["best"], entry["tied"]) for entry in ranked], [(2, True, True), (3, False, True), (1, False, False)])

        ranked = rankVariants([item(1, 70, stale=["Курс"]), item(2, 70)])
        self.assertEqual([(entry["number"], entry["best"], entry["tied"]) for entry in ranked], [(2, True, False), (1, False, False)])
        self.assertFalse(allTied(ranked))

        ranked = rankVariants([item(1, 70, stale=["Курс"]), item(2, 70, stale=["Курс"])])
        self.assertEqual([(entry["best"], entry["tied"]) for entry in ranked], [(False, False), (False, False)])
        self.assertFalse(allTied(ranked))

    def test_moved_started_variant_is_never_best(self):
        """Вариант, который сдвинул урок курса, шедшего уже при сборке (movedStarted не пуст), принять нельзя —
        как устаревший: после принимаемых, не «лучший», не в «ничьей» (variants.unacceptable).
        """
        def item(number, total, moved=()):
            metrics = {"missing": 0, "equalLessons": 0, "teacherClash": 0, "total": total}
            return {"number": number, "metrics": metrics, "rejected": False, "staleStarted": [], "movedStarted": list(moved)}

        ranked = rankVariants([item(1, 10, moved=[{"course": "Курс", "lines": ["Понедельник, 10:00: …"]}]), item(2, 70), item(3, 70)])
        self.assertEqual([(entry["number"], entry["best"], entry["tied"]) for entry in ranked], [(2, True, True), (3, False, True), (1, False, False)])
        self.assertTrue(unacceptable(ranked[2]))
        self.assertFalse(unacceptable(ranked[0]))

    def test_drop_unknown_teachers(self):
        """Преподаватели, которых уже нет в проекте, убираются из уроков варианта; остальные остаются."""
        variant = {self.chemistry: place(emptyWeek(), 0, 0, "Химия", "Иванова Анна")}
        variant[self.chemistry][0][0]["teachers"].append("Удалённая")

        self.assertIs(dropUnknownTeachers(self.settings, variant), variant)
        self.assertEqual(variant[self.chemistry][0][0]["teachers"], ["Иванова Анна"])

    def test_lesson_issues(self):
        """На карточке урока в «Предпросмотре» написано, что с ним не так: с каким предметом
        он совпал, два урока курса в день, неудобное время, выходной. У урока без проблем — ничего.
        """
        chemistry = place(place(emptyWeek(), 0, 0, "Химия", "Иванова Анна"), 0, 2, "Химия", "Иванова Анна")
        biology = place(emptyWeek(), 0, 0, "Биология", "Петров Пётр")
        oge = place(emptyWeek(), 5, 1, "Физика", "Сидоров Иван")

        issues = lessonIssues(self.settings, "1", {self.chemistry: chemistry, self.biology: biology, self.oge: oge})

        self.assertEqual(issues[self.chemistry]["0-0"], ["Одновременно с: Биология (ЕГЭ осн.)", "Два урока курса в один день"])
        self.assertIn("Преподавателю неудобно (отмечено «может»)", issues[self.chemistry]["0-2"])
        # Химия в 0-2 и биология в 0-0 — пара «нежелательно» в один день, но в разные часы: не критично (жёлтым)
        self.assertIn({"text": "В тот же день: Биология (ЕГЭ осн.)", "level": "warn"}, issues[self.chemistry]["0-2"])
        self.assertEqual(issues[self.biology]["0-0"], ["Одновременно с: Химия (ЕГЭ осн.)"])
        self.assertEqual(issues[self.oge]["5-1"], ["Урок в выходной"])

        # Без отметки «нежелательно» (пара «можно») совпадение химии и биологии не подписывается
        self.settings["soft_subject_pairs"] = []
        issues = lessonIssues(self.settings, "1", {self.chemistry: chemistry, self.biology: biology, self.oge: emptyWeek()})
        self.assertNotIn(self.biology, issues)
        self.assertNotIn(self.oge, issues)

    def test_teacher_work_days(self):
        """Число рабочих дней учителя считается по дням с уроками; дни, когда он уже работает
        в другом потоке, не считаются лишними.
        """
        # Два урока в понедельник, один в среду: два рабочих дня
        chemistry = place(place(emptyWeek(), 0, 0, "Химия", "Иванова Анна"), 2, 0, "Химия", "Иванова Анна")
        biology = place(emptyWeek(), 0, 1, "Биология", "Иванова Анна")
        variant = {self.chemistry: chemistry, self.biology: biology, self.oge: emptyWeek()}

        weights = dict(WEIGHTS, teacherWorkDays=100)
        metrics = variantMetrics(self.settings, "1", variant, weights)
        self.assertEqual(metrics["teacherWorkDays"], 2)

        # В среду она уже работает в другом потоке: лишний день — только понедельник
        other = addCourse(self.settings, 2, "ОГЭ", "Химия", 1, "2026-09-07")
        answer = {other: place(emptyWeek(), 2, 2, "Химия", "Иванова Анна")}
        with_other = variantMetrics(self.settings, "1", variant, weights, answer)
        self.assertEqual(with_other["teacherWorkDays"], 1)
        self.assertEqual(metrics["total"] - with_other["total"], 100)

    def test_teacher_clash_with_other_stage(self):
        """Вариант, ставящий учителя на время, где он уже ведёт урок в принятом расписании другого
        этапа, даёт накладку — но только если даты курсов пересекаются.
        """
        # В потоке 2 она уже стоит в понедельник первым уроком; этот вариант потока 1 ставит её туда же
        other = addCourse(self.settings, 2, "ЕГЭ основной", "Химия", 1, "2026-09-07")
        answer = {other: place(emptyWeek(), 0, 0, "Химия", "Иванова Анна")}
        variant = {self.chemistry: place(emptyWeek(), 0, 0, "Химия", "Иванова Анна"), self.biology: emptyWeek(), self.oge: emptyWeek()}

        self.assertEqual(variantMetrics(self.settings, "1", variant, WEIGHTS, answer)["teacherClash"], 1)
        self.assertEqual(variantClashes(self.settings, "1", variant, answer), 1)
        self.assertEqual(variantClashes(self.settings, "1", variant), 0)

        # Другой курс закончился до начала этого этапа: накладки нет
        for group in self.settings["classes"]["custom_groups"]:
            if group["name"] == other:
                group["start_date"], group["end_date"] = "2026-01-01", "2026-06-30"

        self.assertEqual(variantMetrics(self.settings, "1", variant, WEIGHTS, answer)["teacherClash"], 0)

    def test_storage_and_acceptance(self):
        """Варианты сохраняются на диск и читаются по номерам по порядку, для каждого этапа отдельно;
        вариант считается принятым, только если его уроки совпадают с answer.json; очистка удаляет все.
        """
        with tempfile.TemporaryDirectory() as project:
            first = {self.chemistry: place(emptyWeek(), 0, 0, "Химия", "Иванова Анна")}
            second = {self.chemistry: place(emptyWeek(), 1, 0, "Химия", "Иванова Анна")}

            saveVariant(project, "1", 2, second)
            saveVariant(project, "1", 1, first)

            self.assertEqual([number for number, _ in loadVariants(project, "1")], [1, 2])
            self.assertEqual(loadVariants(project, "2"), [])

            courses = [self.chemistry]
            self.assertTrue(isAccepted(dict(first), first, courses))
            self.assertFalse(isAccepted(dict(first), second, courses))
            self.assertFalse(isAccepted({}, first, courses))

            clearVariants(project, "1")
            self.assertEqual(loadVariants(project, "1"), [])

    def test_real_stage_courses(self):
        """На стандартной программе пустой вариант этапа 1 показывает непоставленными ровно все
        уроки этапа.
        """
        settings = makeSettings()

        self.assertTrue(stageCourses(settings, "1"))
        self.assertEqual(variantMetrics(settings, "1", {}, WEIGHTS)["missing"], sum(
            sum(settings["classes"]["lessons"][name].values()) for name in stageCourses(settings, "1")
        ))


class VariantChecksTests(unittest.TestCase):
    """Принят ли вариант и сколько уроков не поставлено."""
    def test_stage_absent_from_answer_is_not_accepted(self):
        """Этапа нет в расписании — вариант не «принят», даже пустой."""
        self.assertFalse(isAccepted({}, {}, ["A"]))
        self.assertFalse(isAccepted({"X": [[lesson("Химия")]]}, {}, ["A"]))
        self.assertTrue(isAccepted({"A": [[lesson("Химия")]]}, {"A": [[lesson("Химия")]]}, ["A"]))

    def test_extra_lessons_do_not_hide_missing(self):
        """Лишние уроки одного курса не покрывают недостающие у другого: missing = 2."""
        settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}}
        first = addCourse(settings, 1, "ОГЭ", "Химия", 1, "2026-09-07")
        second = addCourse(settings, 1, "ОГЭ", "Физика", 2, "2026-09-07")
        variant = {first: emptyWeek(5), second: emptyWeek(5)}

        for day in range(3):
            variant[first][day][0] = lesson("Химия", "Иванова")

        self.assertEqual(variantMetrics(settings, "1", variant, {})["missing"], 2)


class VariantMarksTests(unittest.TestCase):
    """Метки вариантов этапа: принятый (accepted.json) и отклонённые (rejected.json)."""
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="schedule-marks-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        os.makedirs(variantsDir(self.folder, "2"))

    def path(self, name):
        return os.path.join(variantsDir(self.folder, "2"), name)

    def test_accepted_number(self):
        """Пока ничего не принимали — None; после markAccepted — номер; файлы этапов раздельные."""
        self.assertIsNone(acceptedNumber(self.folder, "2"))

        markAccepted(self.folder, "2", 3)

        self.assertEqual(acceptedNumber(self.folder, "2"), 3)
        self.assertIsNone(acceptedNumber(self.folder, "1"))

    def test_broken_accepted_file(self):
        """accepted.json испорчен или не словарь — как будто ничего не принимали."""
        for text in ("{broken", "[3]"):
            writeText(self.path("accepted.json"), text)
            self.assertIsNone(acceptedNumber(self.folder, "2"), text)

    def test_rejected_numbers(self):
        """setRejected пишет номера целиком и по возрастанию; rejectedNumbers читает множество."""
        self.assertEqual(rejectedNumbers(self.folder, "2"), set())

        setRejected(self.folder, "2", {5, 1, 3})

        with open(self.path("rejected.json"), encoding="utf-8") as file:
            self.assertEqual(json.load(file), {"numbers": [1, 3, 5]})

        self.assertEqual(rejectedNumbers(self.folder, "2"), {1, 3, 5})

        setRejected(self.folder, "2", set())
        self.assertEqual(rejectedNumbers(self.folder, "2"), set())

    def test_broken_rejected_file(self):
        """Испорченный rejected.json — пустое множество; не числа в списке пропускаются."""
        for text, expected in (("{broken", set()), ("[1, 2]", set()), ('{"numbers": [1, "2", null, 4]}', {1, 4})):
            writeText(self.path("rejected.json"), text)
            self.assertEqual(rejectedNumbers(self.folder, "2"), expected, text)

    def test_started_at_build(self):
        """saveBuildStarted пишет курсы по алфавиту, buildStarted читает множество; пока сборки
        с меткой не было (или файл испорчен) — None: что шло при сборке, неизвестно; не строки пропускаются.
        """
        self.assertIsNone(buildStarted(self.folder, "2"))

        saveBuildStarted(self.folder, "2", {"Б", "А"})

        with open(self.path("started.json"), encoding="utf-8") as file:
            self.assertEqual(json.load(file), {"courses": ["А", "Б"]})

        self.assertEqual(buildStarted(self.folder, "2"), {"А", "Б"})
        self.assertIsNone(buildStarted(self.folder, "1"))

        for text in ("{broken", "[1]", '{"courses": 3}'):
            writeText(self.path("started.json"), text)
            self.assertIsNone(buildStarted(self.folder, "2"), text)

        writeText(self.path("started.json"), '{"courses": ["А", ["Б"], 3]}')
        self.assertEqual(buildStarted(self.folder, "2"), {"А"})

    def test_started_at_build_with_lessons(self):
        """С расписанием на начало сборки started.json запоминает и уроки этих курсов (место, предмет,
        преподаватели). buildStarted с нынешним расписанием не считает «шедшими при сборке» курсы, чьи
        уроки с тех пор поменялись (приняли другой вариант, вернули версию): вариант собран не по
        нынешнему расписанию — для них он устарел (stages.staleStarted), а не «программа не смогла».
        Без расписания (или в файле нет уроков — метка старой программы) сверки нет.
        """
        answer = {"А": place(emptyWeek(5), 0, 1, "Химия", "Иванова"), "Б": place(emptyWeek(5), 2, 0, "Физика", "Петров")}
        saveBuildStarted(self.folder, "2", {"А", "Б"}, answer)

        with open(self.path("started.json"), encoding="utf-8") as file:
            self.assertEqual(json.load(file)["lessons"], {"А": [[0, 1, "Химия", ["Иванова"]]], "Б": [[2, 0, "Физика", ["Петров"]]]})

        self.assertEqual(buildStarted(self.folder, "2", answer), {"А", "Б"})

        changed = {**answer, "Б": place(place(emptyWeek(5), 2, 0, "Физика", "Петров"), 3, 0, "Физика", "Петров")}
        self.assertEqual(buildStarted(self.folder, "2", changed), {"А"})
        self.assertEqual(buildStarted(self.folder, "2"), {"А", "Б"})

        saveBuildStarted(self.folder, "2", {"А", "Б"})
        self.assertEqual(buildStarted(self.folder, "2", changed), {"А", "Б"})

        # Уроки, испорченные руками (не словарь), не сверяются
        writeText(self.path("started.json"), '{"courses": ["А"], "lessons": [1]}')
        self.assertEqual(buildStarted(self.folder, "2", changed), {"А"})


class VariantStorageEdgeTests(TempFolderCase):
    """Чтение вариантов с посторонними и испорченными файлами; цена своих правил в итоге варианта."""
    def test_broken_and_foreign_files(self):
        """Читаются только «<число>.json», испорченные пропускаются; порядок — по числу (2 раньше 10)."""
        folder = os.path.join(self.folder, "stages", "1.variants")
        os.makedirs(folder)

        for name, text in {"10.json": '{"б": []}', "2.json": '{"а": []}', "3.json": "{испорчено", "notes.json": "{}", "4.txt": "{}"}.items():
            writeText(os.path.join(folder, name), text)

        self.assertEqual(loadVariants(self.folder, "1"), [(2, {"а": []}), (10, {"б": []})])

    def test_stale_stage_variants(self):
        """Стираются только папки вариантов этапов, которых нет в списке; посторонние файлы
        и папка без вариантов не мешают."""
        clearStaleVariants(self.folder, ["1"])

        for stage in ("1", "may"):
            saveVariant(self.folder, stage, 1, {"а": []})
        writeText(os.path.join(self.folder, "stages", "notes.json"), "{}")

        clearStaleVariants(self.folder, ["1"])
        self.assertEqual(loadVariants(self.folder, "1"), [(1, {"а": []})])
        self.assertFalse(os.path.isdir(variantsDir(self.folder, "may")))
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "stages", "notes.json")))

    def test_custom_rule_adds_to_total(self):
        """Своё правило входит в итог варианта: число нарушений × его вес."""
        settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}, "day_grid": [["16:20 - 17:50"]] * 5}
        course = addCourse(settings, 1, "ОГЭ", "Химия", 1, "2026-09-07")
        variant = {course: place(emptyWeek(), 0, 0, "Химия", "Иванова")}

        before = variantMetrics(settings, "1", variant, {})
        rule = newPenalty("Не в пн", "time", 7, {"target": "all", "value": "", "days": [0], "times": ["16:20 - 17:50"]})
        settings["custom_penalties"] = [rule]
        after = variantMetrics(settings, "1", variant, {})

        self.assertEqual(after["custom"], {rule["id"]: 1})
        self.assertEqual(after["total"] - before["total"], 7)


class LessonIssueTests(unittest.TestCase):
    """Подписи на карточках уроков: другой поток или блок, тот же преподаватель, правила, повторы,
    курс без программы, уровни ЕГЭ разного размера."""
    def test_teacher_busy_in_other_stream_and_levels_with_one_teacher(self):
        """«… в это время ведёт уроки в другом потоке или блоке курсов» — урок преподавателя совпал с его уроком из принятого
        расписания; уровни ЕГЭ в разное время с одним преподавателем — «(тот же преподаватель)».
        """
        settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}}
        basic = addCourse(settings, 1, "ЕГЭ основной", "Химия", 1, START)
        advanced = addCourse(settings, 1, "ЕГЭ продвинутый", "Химия", 1, START)
        other = addCourse(settings, 2, "ОГЭ", "Химия", 1, START)

        answer = {other: place(emptyWeek(), 0, 0, "Химия", "Иванова")}
        variant = {basic: place(emptyWeek(), 0, 0, "Химия", "Иванова"), advanced: place(emptyWeek(), 1, 0, "Химия", "Иванова")}
        issues = lessonIssues(settings, "1", variant, answer)

        self.assertIn("Иванова в это время ведёт уроки в другом потоке или блоке курсов", issues[basic]["0-0"])
        self.assertIn("ЕГЭ продв. — в другой день или час (тот же преподаватель)", issues[basic]["0-0"])
        self.assertIn("ЕГЭ осн. — в другой день или час (тот же преподаватель)", issues[advanced]["1-0"])

    def test_same_note_is_not_repeated(self):
        """Два преподавателя урока, оба отметили слот «может», — подпись «может» одна."""
        settings = baseSettings(teachers={"Иванова": teacher("Химия"), "Петров": teacher("Химия")})
        course = addCourse(settings, 1, "ОГЭ", "Химия", 1, "2026-09-01")

        for name in ("Иванова", "Петров"):
            teacherAvailability(settings["teachers"][name], "1")["possible"].append([0, 0])

        week = emptyWeek(5)
        week[0][0] = {"subject": "Химия", "teachers": ["Иванова", "Петров"]}

        self.assertEqual(lessonIssues(settings, "1", {course: week}), {course: {"0-0": [translate("web.issue.teacher_possible")]}})

    def test_same_day_with_course_without_program(self):
        """Пара «сдают вместе» в один день: у курса без программы предмет пишется без линейки."""
        settings = {
            "classes": {"custom_groups": [
                {"name": "A", "line": "X", "stream_id": 1, "subjects": ["Химия"], "program": "ОГЭ"},
                {"name": "B", "line": "X", "stream_id": 1, "subjects": ["Биология"]},
            ], "lessons": {}},
            "soft_subject_pairs": [["Биология", "Химия"]],
        }
        variant = {"A": place(emptyWeek(5), 0, 0, "Химия", "Иванова"), "B": place(emptyWeek(5), 0, 1, "Биология", "Петров")}
        text = translate("web.issue.pair_same_day")

        self.assertEqual(lessonIssues(settings, "1", variant), {
            "A": {"0-0": [{"text": text.replace("{subjects}", "Биология"), "level": "warn"}]},
            "B": {"0-1": [{"text": text.replace("{subjects}", "Химия (ОГЭ)"), "level": "warn"}]},
        })

    def test_only_smaller_level_is_marked(self):
        """Уровни ЕГЭ одного предмета в разное время: помечается только курс с меньшим числом уроков."""
        settings = baseSettings()
        base = addCourse(settings, 1, "ЕГЭ основной", "Химия", 2, "2026-09-01")
        advanced = addCourse(settings, 1, "ЕГЭ продвинутый", "Химия", 1, "2026-09-01")
        variant = {
            base: place(place(emptyWeek(5), 0, 0, "Химия", "Иванова"), 1, 0, "Химия", "Иванова"),
            advanced: place(emptyWeek(5), 2, 0, "Химия", "Петров"),
        }

        self.assertEqual(lessonIssues(settings, "1", variant), {
            advanced: {"2-0": [translate("web.issue.levels_apart").replace("{level}", "ЕГЭ осн.")]},
        })


class MissingDetailsTests(unittest.TestCase):
    """Почему часть уроков не встала (вкладка «Предпросмотр», блок «Что не получилось поставить»)."""
    def setUp(self):
        self.settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}, "max_courses_per_teacher": 1}
        setDayGrid(self.settings, [["16:20 - 17:50"]] + [[]] * 6)
        self.chemistry = addCourse(self.settings, 1, "ЕГЭ основной", "Химия", 1, START)
        self.biology = addCourse(self.settings, 1, "ЕГЭ основной", "Биология", 1, START)
        self.physics = addCourse(self.settings, 1, "ОГЭ", "Физика", 1, START)

    def reasons(self, variant):
        """{курс: причина} для курсов, которым не хватает уроков."""
        return {item["course"]: item["reason"] for item in missingDetails(self.settings, {}, "1", variant)}

    def test_reasons(self):
        """Нет преподавателя предмета — «no_teacher»; у единственного уже максимум курсов — «limit»;
        время единственного слота занято «не может» — «no_time»; время было — «rules».
        """
        self.settings["teachers"]["Иванова"] = teacherWithCourses(("Химия", [self.chemistry], []), ("Биология", [self.biology], []))
        self.settings["teachers"]["Петров"] = teacherWithCourses(("Физика", [self.physics], []), availability={"1": {"free": [[0, 0]], "possible": []}})
        variant = {self.chemistry: place(emptyWeek(), 0, 0, "Химия", "Иванова")}

        self.assertEqual(self.reasons(variant), {self.biology: "limit", self.physics: "no_time"})

        del self.settings["teachers"]["Петров"]
        self.assertEqual(self.reasons(variant)[self.physics], "no_teacher")

        self.settings["max_courses_per_teacher"] = 5
        self.settings["teachers"]["Петров"] = teacherWithCourses(("Физика", [self.physics], []))
        self.assertEqual(self.reasons({}), {self.chemistry: "rules", self.biology: "rules", self.physics: "rules"})
        self.assertEqual(self.reasons(variant)[self.biology], "no_time")  # её единственный час уже занят химией

    def test_rule_closed_hour_is_rules(self):
        """Свободный час преподавателя закрыт курсу правилом — причина «rules», а не «no_time».

        Сетка — один час (0, 0). Там стоит урок идущей химии без преподавателя, а у биологии с химией
        пара «нельзя одновременно»: час закрыт биологии (blocked_slots). У Ивановой этот час не отмечен
        «не может» и не занят — урок не встал из-за правила.
        """
        settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}, "max_courses_per_teacher": 5,
                    "joint_subject_pairs": [["Химия", "Биология"]]}
        setDayGrid(settings, [["16:20 - 17:50"]] + [[]] * 6)
        chemistry = addCourse(settings, 1, "ЕГЭ основной", "Химия", 1, PAST)
        biology = addCourse(settings, 1, "ЕГЭ основной", "Биология", 1, START)
        settings["teachers"]["Иванова"] = teacherWithCourses(("Биология", [biology], []))
        week = emptyWeek()
        week[0][0] = {"subject": "Химия", "teachers": []}

        reasons = {item["course"]: item["reason"] for item in missingDetails(settings, {chemistry: week}, "1", {})}

        self.assertEqual(reasons[biology], "rules")


class WeightKeysTests(unittest.TestCase):
    """Имена весов одинаковы во всех местах, где они записаны."""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def solverWeights(self):
        """Имена весов, которые движок читает в Weights::init (строки data.value("<вес>", …) в solve.cpp)."""
        with open(os.path.join(self.ROOT, "src", "modules", "solve.cpp"), encoding="utf-8") as file:
            text = file.read()

        start = text.index("static void init(const json& data) {")
        body = text[start:text.index("}", start)]

        return set(re.findall(r'data\.value\("(\w+)"', body))

    def test_weight_names_match_everywhere(self):
        """Шаблон весов (src/files/weights.json), порядок пунктов «Что важно в расписании» (WEIGHT_ORDER),
        столбцы «Предпросмотра» с весом (METRICS) и движок (solve.cpp) знают одни и те же веса. Иначе
        новый вес, добавленный в одно место и забытый в другом, страница покажет ключом вместо подписи,
        он не войдёт в итог варианта или движок его молча не прочитает.
        Подписи и подсказки есть в ru.hjson у каждого веса (weights.<вес>, weights_hint.<вес>) и у каждого
        столбца «Предпросмотра» (menu.main.tab.preview.column.<ключ> и column_hint.<ключ>).
        """
        with open(os.path.join(self.ROOT, "src", "files", "weights.json"), encoding="utf-8") as file:
            template = set(json.load(file))

        self.assertEqual(len(WEIGHT_ORDER), len(set(WEIGHT_ORDER)))
        self.assertEqual(set(WEIGHT_ORDER), template)
        self.assertEqual({weight for _, weight in METRICS if weight}, template)
        self.assertEqual(self.solverWeights(), template)

        # translate возвращает сам ключ, если текста нет в ru.hjson
        for weight in WEIGHT_ORDER:
            for key in (f"weights.{weight}", f"weights_hint.{weight}"):
                self.assertNotEqual(translate(key), key)

        for metric, _ in METRICS:
            for key in (f"menu.main.tab.preview.column.{metric}", f"menu.main.tab.preview.column_hint.{metric}"):
                self.assertNotEqual(translate(key), key)


class JointVariantTests(unittest.TestCase):
    """«ЕГЭ основной» Потока 2 идёт вместе с Потоком 1 (проект ``jointProject``): копии Математики
    («Математика #1», пн и ср первым уроком) и Русского языка («Русский язык #1», вт и чт вторым
    уроком) стоят как в принятом Потоке 1.
    """
    JOINT_WEIGHTS = dict(WEIGHTS, levelsApart=300, pairsSameDay=50, teacherWorkDays=100)

    def setUp(self):
        self.settings, self.answer = jointProject()

    def mark(self):
        """Отметка «ЕГЭ основной» Потока 2 «вместе с Потоком 1»: копии получают уроки источника; {копия: источник}."""
        return markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)

    @staticmethod
    def ownLessons():
        """Уроки обычных курсов Потока 2: уровень «ЕГЭ продвинутый» Математики — вт и чт (не в часы копии),
        Русского языка — в часы копии; «Информатика» — пн первым уроком (вместе с копией Математики,
        пара «нежелательно»); «ОГЭ» — пт вторым уроком. Преподаватели ни с кем не пересекаются.
        """
        return {
            jointCourse(2, "Математика", LEVEL_LINE): courseWeek("Математика", "Математика #2", (1, 0), (3, 0)),
            jointCourse(2, "Русский язык", LEVEL_LINE): courseWeek("Русский язык", "Русский язык #3", (1, 1), (3, 1)),
            jointCourse(2, "Информатика"): courseWeek("Информатика", "Информатика #1", (0, 0)),
            jointCourse(2, "Математика", OWN_LINE): courseWeek("Математика", "Математика #3", (4, 1)),
        }

    def variant(self, copies):
        """Вариант Потока 2: обычные курсы (``ownLessons``) и копии с уроками из answer — так их переносит сборка."""
        result = self.ownLessons()
        result.update({course: copy.deepcopy(self.answer[course]) for course in copies if course in self.answer})

        return result

    @staticmethod
    def texts(issues, course):
        """Все подписи урока курса ``course`` из ``lessonIssues`` (строки и тексты некритичных подписей)."""
        return [item["text"] if isinstance(item, dict) else item for items in issues.get(course, {}).values() for item in items]

    def test_levels_and_pairs_count_copies_teacher_rules_do_not(self):
        """AC-21: в варианте потока-копии «уровни врозь», «нежелательно одновременно» и «пары в один день»
        считаются с копиями так же, как с обычными курсами; а у преподавателя копии её уроки не дают
        ни накладки с уроками источника, ни «может». Урок третьего курса того же преподавателя в часы
        копии — накладка.
        """
        plain = copy.deepcopy(self.settings)
        copies = self.mark()
        variant = self.variant(copies)
        teacherAvailability(self.settings["teachers"]["Математика #1"], "2")["possible"].append([0, 0])

        metrics = variantMetrics(self.settings, "2", variant, self.JOINT_WEIGHTS, self.answer)
        reference = variantMetrics(plain, "2", variant, self.JOINT_WEIGHTS)

        for key in ("levelsApart", "softSubjectPair", "pairsSameDay"):
            self.assertEqual(metrics[key], reference[key], key)

        # Математика уровней врозь: оба урока копии без пары; Информатика в часы копии Математики
        self.assertEqual((metrics["levelsApart"], metrics["softSubjectPair"]), (2, 1))

        self.assertEqual((metrics["teacherClash"], metrics["teacherPossibleSlot"]), (0, 0))

        issues = lessonIssues(self.settings, "2", variant, self.answer)
        unwanted = {tr("web.issue.teacher_busy", name=name) for name in ("Математика #1", "Русский язык #1")}
        unwanted.add(translate("web.issue.teacher_possible"))

        for course in copies:
            self.assertFalse(unwanted & set(self.texts(issues, course)), course)

        variant[jointCourse(2, "Математика", OWN_LINE)] = courseWeek("Математика", "Математика #1", (0, 0))
        self.assertEqual(variantMetrics(self.settings, "2", variant, self.JOINT_WEIGHTS, self.answer)["teacherClash"], 1)

    def test_waiting_copy_is_not_missing(self):
        """AC-21 (и AC-14): «Русский язык» «ЕГЭ основной» Потока 1 не поставлен — его копия в Потоке 2
        ждёт и не считается непоставленной: ни в ``missing``, ни в ``missingDetails``.
        """
        del self.answer[jointCourse(1, "Русский язык")]
        copies = self.mark()
        variant = self.variant(copies)

        self.assertNotIn(jointCourse(2, "Русский язык"), variant)
        self.assertEqual(variantMetrics(self.settings, "2", variant, self.JOINT_WEIGHTS, self.answer)["missing"], 0)
        self.assertEqual(missingDetails(self.settings, self.answer, "2", variant), [])

    def test_copy_days_are_not_new_work_days(self):
        """AC-21 (и AC-20): дни уроков копии не считаются новыми рабочими днями её преподавателя —
        даже если Поток 1 закончился до начала Потока 2. «Математика #1» ведёт копию в пн и ср и урок
        «ОГЭ» в пт: новый рабочий день один — пятница.
        """
        for group in self.settings["classes"]["custom_groups"]:
            if group["stream_id"] == 1:
                setDates(self.settings, group["name"], group["start_date"], "2026-11-22")

        copies = self.mark()
        variant = {course: copy.deepcopy(self.answer[course]) for course in copies}
        variant[jointCourse(2, "Математика", OWN_LINE)] = courseWeek("Математика", "Математика #1", (4, 1))

        self.assertEqual(variantMetrics(self.settings, "2", variant, self.JOINT_WEIGHTS, self.answer)["teacherWorkDays"], 1)

    def test_accepted_copies_are_no_clash_for_source_stage(self):
        """AC-23: Поток 2 с копиями принят, составляется Поток 1 — вариант, оставляющий уроки Потока 1
        на месте, не получает накладок из-за копий (ни в метрике, ни в вопросе перед принятием,
        ни в подписях уроков).
        """
        self.mark()
        variant = {course: copy.deepcopy(self.answer[course]) for course in stageCourses(self.settings, "1") if course in self.answer}

        self.assertEqual(variantMetrics(self.settings, "1", variant, self.JOINT_WEIGHTS, self.answer)["teacherClash"], 0)
        self.assertEqual(variantClashes(self.settings, "1", variant, self.answer), 0)

        issues = lessonIssues(self.settings, "1", variant, self.answer)
        self.assertNotIn(tr("web.issue.teacher_busy", name="Математика #1"), self.texts(issues, jointCourse(1, "Математика")))

    def test_limit_counts_source_and_copy_once(self):
        """AC-26: лимит 2 курса; «Математика #1» ведёт источник и копию — это один курс, поэтому
        недостающий урок курса Потока 3, который может вести только она, — не «limit».
        """
        self.mark()
        self.settings["max_courses_per_teacher"] = 2
        course = jointCourse(3, "Математика", LEVEL_LINE)

        for name in ("Математика #2", "Математика #3"):
            setTeacherCourseState(self.settings, name, "Математика", course, "no")

        details = {item["course"]: item for item in missingDetails(self.settings, self.answer, "3", {})}

        self.assertEqual(details[course]["reason"], "rules")

    def test_variant_is_accepted_without_copies(self):
        """AC-25: вариант Потока 2 собран, когда «ЕГЭ основной» Потока 1 стоял в другие часы (копии в нём
        старые), а потом Поток 1 приняли заново. Обычные курсы варианта совпадают с расписанием —
        вариант «принят»: копии не сравниваются. Обычный курс отличается — не «принят».
        """
        self.mark()
        own = self.ownLessons()
        self.answer.update(copy.deepcopy(own))
        courses = stageCourses(self.settings, "2")

        variant = copy.deepcopy(own)
        variant[jointCourse(2, "Математика")] = courseWeek("Математика", "Математика #1", (1, 2), (3, 2))
        variant[jointCourse(2, "Русский язык")] = courseWeek("Русский язык", "Русский язык #1", (0, 2), (2, 2))

        self.assertTrue(isAccepted(self.answer, variant, courses, settings=self.settings))

        variant[jointCourse(2, "Информатика")] = courseWeek("Информатика", "Информатика #1", (2, 1))
        self.assertFalse(isAccepted(self.answer, variant, courses, settings=self.settings))


class JointIssuesTests(unittest.TestCase):
    """Подписи уроков (``lessonIssues``) в варианте потока-копии (замечание проверки): у копий их нет —
    время копии задаёт Поток 1, — а помеха между копией и уроком потока подписана у урока потока.
    Проект ``jointProject``, «ЕГЭ основной» Потока 2 идёт вместе с Потоком 1: копия Математики —
    пн и ср 1-м уроком.
    """

    def setUp(self):
        self.settings, self.answer = jointProject()
        self.copies = markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        self.level = jointCourse(2, "Математика", LEVEL_LINE)

    def issues(self, *slots):
        """``lessonIssues`` варианта Потока 2: копии как в answer, «ЕГЭ продвинутый» Математика
        в ``slots``, «Информатика» в пн 1-м уроком (вместе с копией Математики — пара «нежелательно»).
        """
        variant = {name: copy.deepcopy(self.answer[name]) for name in self.copies}
        variant[self.level] = courseWeek("Математика", "Математика #2", *slots)
        variant[jointCourse(2, "Информатика")] = courseWeek("Информатика", "Информатика #1", (0, 0))

        return lessonIssues(self.settings, "2", variant, self.answer)

    def test_copies_have_no_issues(self):
        """Уровни врозь (поровну уроков) и «нежелательно одновременно»: подписи у «ЕГЭ продвинутый»
        и у «Информатики», у копий — ни одной.
        """
        issues = self.issues((1, 0), (3, 0))

        for name in self.copies:
            self.assertNotIn(name, issues)

        self.assertEqual(set(issues[self.level]), {"1-0", "3-0"})
        self.assertIn("0-0", issues[jointCourse(2, "Информатика")])

    def test_bigger_level_is_signed_when_copy_is_smaller(self):
        """У копии меньше уроков, чем у «ЕГЭ продвинутый» (2 и 3), и они врозь: обычно подписан меньший
        курс пары, но копию не сдвинуть — подписаны уроки «ЕГЭ продвинутый».
        """
        issues = self.issues((1, 0), (3, 0), (4, 0))

        self.assertNotIn(jointCourse(2, "Математика"), issues)
        self.assertEqual(set(issues[self.level]), {"1-0", "3-0", "4-0"})


class TeacherOverLimitTests(unittest.TestCase):
    """``variants.teacherOverLimit(settings, answer, stage, variant)`` → [(преподаватель, курсов, лимит)]:
    курсы других этапов (копии — по своему источнику) и курсы варианта вместе больше лимита.
    Превышение из-за одних «ведёт» не считается. Проект ``jointProject``, лимит 2 курса: в принятом
    Потоке 1 «Математика #1» ведёт «ЕГЭ основной» Математику, вариант — Потока 2.
    """
    NAME = "Математика #1"

    def setUp(self):
        self.settings, self.answer = jointProject()
        self.settings["max_courses_per_teacher"] = 2
        self.level = jointCourse(2, "Математика", LEVEL_LINE)
        self.own = jointCourse(2, "Математика", OWN_LINE)

    def overLimit(self, variant):
        """Превышения лимита у варианта Потока 2 списком кортежей."""
        from src.modules.functions.variants import teacherOverLimit

        return [tuple(item) for item in teacherOverLimit(self.settings, self.answer, "2", variant)]

    def week(self, *slots):
        """Неделя Математики у «Математика #1» в ячейках ``slots``."""
        return courseWeek("Математика", self.NAME, *slots)

    def test_third_course_is_over_limit(self):
        """AC-20: вариант даёт «Математика #1» два курса Потока 2 при одном в Потоке 1 — 3 курса при лимите 2;
        один курс Потока 2 — 2 курса, превышения нет.
        """
        self.assertEqual(self.overLimit({self.level: self.week((1, 2))}), [])
        self.assertEqual(self.overLimit({self.level: self.week((1, 2)), self.own: self.week((4, 1))}), [(self.NAME, 3, 2)])

    def test_copy_and_source_are_one_course(self):
        """AC-20: «ЕГЭ основной» Потока 2 идёт вместе с Потоком 1. Копия Математики в варианте и её источник
        в расписании — один курс: с «ЕГЭ продвинутый» у неё 2 курса (лимит не превышен), с «ОГЭ» — 3.
        """
        copies = markJoint(self.settings, 2, JOINT_LINE, 1, self.answer)
        variant = {name: copy.deepcopy(self.answer[name]) for name in copies}
        variant[self.level] = self.week((1, 2))

        self.assertEqual(self.overLimit(variant), [])

        variant[self.own] = self.week((4, 1))
        self.assertEqual(self.overLimit(variant), [(self.NAME, 3, 2)])

    def test_assigned_courses_alone_are_not_reported(self):
        """AC-20: оба курса варианта у «Математика #1» — «ведёт»: 3 курса, но превышение из-за одних «ведёт»
        (движок его не создавал) не считается. «Ведёт» только один из них — превышение есть.
        """
        variant = {self.level: self.week((1, 2)), self.own: self.week((4, 1))}

        for course in (self.level, self.own):
            setTeacherCourseState(self.settings, self.NAME, "Математика", course, "assigned")

        self.assertEqual(self.overLimit(variant), [])

        setTeacherCourseState(self.settings, self.NAME, "Математика", self.own, "may")
        self.assertEqual(self.overLimit(variant), [(self.NAME, 3, 2)])


class StageClashTests(unittest.TestCase):
    """Проект ``jointProject``, «сегодня» 04.10.2026. Поток 1 идёт, «Математика» линейки «ЕГЭ основной»
    (``MATH_1``) зафиксирована: «Математика #1», пн и ср 1-й урок. ``MATH_LEVEL_1`` начнётся позже.
    Вариант собран, пока ``MATH_1`` не шёл: ему — «Математика #3», а освободившейся «Математика #1» —
    ``MATH_LEVEL_1`` в те же часы. После подмены ``MATH_1`` из расписания у «Математика #1» два урока
    сразу дважды.
    """
    MATH_1, MATH_LEVEL_1 = jointCourse(1, "Математика"), jointCourse(1, "Математика", LEVEL_LINE)
    OLD_TEACHER = "Математика #1"

    def test_clashes_counted_and_labelled(self):
        """variantClashes = 2; у уроков обоих курсов подпись web.issue.teacher_twice с другим курсом."""
        settings, answer = jointProject()
        shiftStream(settings, 1, "2026-09-14")
        next(group for group in settings["classes"]["custom_groups"] if group["name"] == self.MATH_LEVEL_1)["start_date"] = "2026-10-12"
        variant = stageVariant(settings, answer, **{
            self.MATH_1: courseWeek("Математика", "Математика #3", (1, 0), (3, 0)),
            self.MATH_LEVEL_1: courseWeek("Математика", self.OLD_TEACHER, (0, 0), (2, 0)),
        })

        with mock.patch("datetime.date", FrozenDate):
            variant = lockedFromAnswer(settings, answer, "1", variant)
            clashes = variantClashes(settings, "1", variant, answer)
            issues = lessonIssues(settings, "1", variant, answer)

        self.assertEqual(clashes, 2)
        self.assertIn(tr("web.issue.teacher_twice", name=self.OLD_TEACHER, courses=self.MATH_1), issues[self.MATH_LEVEL_1]["0-0"])
        self.assertIn(tr("web.issue.teacher_twice", name=self.OLD_TEACHER, courses=self.MATH_LEVEL_1), issues[self.MATH_1]["2-0"])
