"""Мягкие правила и ходы движка solve.exe — по его выходу.

Каждый тест — маленький вход, где нужное правило однозначно задаёт ответ: штраф окна, слота «может»,
лишнего рабочего дня, выходных, уровней, собственных штрафов пользователя; выбор преподавателя
из «может вести»; вставка непоставленного урока отжигом; запись лучшего, а не последнего состояния.
Испорченный штраф (не та формула, инвертированное условие) обычно не нарушает жёстких правил,
поэтому проверяется именно то, что этот штраф должен изменить в расписании или в строке «Шаг ...».

Запуск — ``solved`` из `tests/engine.py` (код выхода 0 и ответ есть; возвращает ответ и stdout).
Путь к решателю он берёт из имени ``tests.engine.SOLVER``: его можно подменить (``mock.patch``),
чтобы прогнать эти тесты на другой сборке solve.exe. Маленькие входы — ``tiny``, ``course``,
``teacher`` из `tests/engine.py`.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
import unittest

from tests.builders import SOLVER
from tests.engine import MISSING_TOTAL, cellsOf, course, placedLessons, solved, teacher, tiny

SEEDS = (1, 2, 3, 4, 5)


def days(answer, name):
    """Отсортированные номера дней с уроками курса."""
    return sorted(day for day, _, _, _ in cellsOf(answer, name))


def slots(answer, name):
    """Множество слотов (день, урок) с уроками курса."""
    return {(day, lesson) for day, lesson, _, _ in cellsOf(answer, name)}


def teacherSlots(answer, who):
    """Отсортированные слоты (день, урок) с уроками преподавателя."""
    return sorted((day, lesson) for _, day, lesson, _, teachers in placedLessons(answer) if who in teachers)


def lastStep(log):
    """Последняя строка прогресса «Шаг ...» (или None)."""
    lines = [line for line in log.splitlines() if line.startswith("Шаг ")]
    return lines[-1] if lines else None


def allSlots(days_count, lessons):
    """Все слоты сетки дни × уроки."""
    return [(day, lesson) for day in range(days_count) for lesson in range(lessons)]


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class TeacherPenaltyTests(unittest.TestCase):
    """Штрафы преподавателя: окна, слоты «может», лишние рабочие дни, дневной лимит."""

    def test_teacher_windows_are_removed(self):
        """Окна: у преподавателя 3 курса по уроку в одном дне из 6 уроков — уроки идут подряд."""
        settings = tiny(1, 6, [course(name, "Математика") for name in "ABC"], {"T": teacher("Математика", "ABC")})

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed, weights={"teacherFreeTime": 100})
            lessons = [lesson for _, lesson in teacherSlots(answer, "T")]
            self.assertEqual(len(lessons), 3, seed)
            self.assertEqual(lessons[-1] - lessons[0], 2, (seed, lessons))

    def test_annealing_quality_on_medium_input(self):
        """Качество отжига (правило Метрополиса): 6 преподавателей × 5 курсов по 2 урока, неделя 5 × 6.
        Жадный старт с окнами, после 300k шагов окон нет ни у кого (случайное блуждание даёт 8–12)."""
        courses, teachers = [], {}

        for number in range(6):
            names = [f"К{number}-{index}" for index in range(5)]
            courses += [course(name, "Математика", 2) for name in names]
            teachers[f"T{number}"] = teacher("Математика", names)

        settings = tiny(5, 6, courses, teachers)

        def windows(answer):
            """Сумма квадратов окон по преподавателям и дням (как штраф teacherFreeTime без веса)."""
            byDay = {}

            for _, day, lesson, _, who in placedLessons(answer):
                byDay.setdefault((who[0], day), []).append(lesson)

            return sum((max(items) - min(items) + 1 - len(items)) ** 2 for items in byDay.values())

        for seed in (1, 2, 3):
            greedy, _ = solved(self, settings, seed, 0, weights={"teacherFreeTime": 100})
            self.assertGreater(windows(greedy), 0, seed)

            answer, log = solved(self, settings, seed, 300000, weights={"teacherFreeTime": 100})
            self.assertNotIn(MISSING_TOTAL, log, seed)
            self.assertEqual(len(placedLessons(answer)), 60, seed)
            self.assertEqual(windows(answer), 0, seed)

    def test_possible_slot_is_avoided(self):
        """Слот «может» платный: у курса 1 урок, удобен только (1,2) — урок всегда там, хоть отжиг и долгий."""
        possible = [slot for slot in allSlots(3, 3) if slot != (1, 2)]
        settings = tiny(3, 3, [course("A", "Математика")], {"T": teacher("Математика", ["A"], possible=possible)})

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed)
            self.assertEqual(slots(answer, "A"), {(1, 2)}, seed)

    def test_best_not_last_state_is_written(self):
        """Горячий прогон (t0 = tend = 1e9, принимается почти любой ход): жадный старт без штрафов
        (единственный удобный слот) — в ответ пишется он, а не последнее случайное состояние."""
        possible = [slot for slot in allSlots(5, 6) if slot != (2, 3)]
        settings = tiny(5, 6, [course("A", "Математика")], {"T": teacher("Математика", ["A"], possible=possible)})

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed, 50000, extra=("--t0", "1e9", "--tend", "1e9"))
            self.assertEqual(slots(answer, "A"), {(2, 3)}, seed)

    def test_work_days_use_busy_days(self):
        """teacherWorkDays: дни 1 и 3 преподаватель уже работает на других этапах — оба урока курса туда."""
        settings = tiny(5, 3, [course("A", "Математика", 2)], {"T": teacher("Математика", ["A"])}, teacher_busy_days={"T": [1, 3]})

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed, weights={"teacherWorkDays": 1000})
            self.assertEqual(days(answer, "A"), [1, 3], seed)

    def test_work_days_gather_lessons_in_one_day(self):
        """teacherWorkDays без занятых дней: 3 курса по уроку у одного преподавателя — в один день."""
        settings = tiny(5, 3, [course(name, "Математика") for name in "ABC"], {"T": teacher("Математика", "ABC")})

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed, weights={"teacherWorkDays": 1000})
            self.assertEqual(len({day for day, _ in teacherSlots(answer, "T")}), 1, seed)

    def test_teacher_daily_limit(self):
        """Собственный штраф teacher_daily (лимит 1 урок в день): 3 курса преподавателя — в 3 разных дня."""
        settings = tiny(3, 3, [course(name, "Математика") for name in "ABC"], {"T": teacher("Математика", "ABC")},
                        custom_penalties_compiled={"teacher_daily": {"T": [[1, 5000]]}})

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed)
            self.assertEqual(sorted(day for day, _ in teacherSlots(answer, "T")), [0, 1, 2], seed)


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class CoursePenaltyTests(unittest.TestCase):
    """Штрафы курсов: выходные, уровни, собственные штрафы пользователя, пары «в разные дни»."""

    def test_weekend_lessons_are_avoided(self):
        """weekendLesson: при 6 и 7 днях 5 уроков курса стоят только в пн–пт."""
        for week in (6, 7):
            settings = tiny(week, 2, [course("A", "Математика", 5)], {"T": teacher("Математика", ["A"])})

            for seed in SEEDS:
                answer, _ = solved(self, settings, seed, weights={"weekendLesson": 5000})
                self.assertEqual(days(answer, "A"), [0, 1, 2, 3, 4], (week, seed))

    def levels(self):
        """Пара уровней одного предмета: ЕГЭ основной (2 урока) и ЕГЭ продвинутый (3 урока), разные преподаватели."""
        return tiny(5, 3, [
            course("Осн", "Математика", 2, program="ЕГЭ основной"),
            course("Пр", "Математика", 3, program="ЕГЭ продвинутый")
        ], {"T1": teacher("Математика", ["Осн"]), "T2": teacher("Математика", ["Пр"])})

    def test_levels_apart_puts_levels_together(self):
        """levelsApart: уроки меньшего уровня стоят в те же слоты, что и уроки большего."""
        settings = self.levels()

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed, weights={"levelsApart": 1000})
            self.assertLessEqual(slots(answer, "Осн"), slots(answer, "Пр"), seed)
            self.assertEqual(len(slots(answer, "Пр")), 3, seed)

    def test_levels_apart_equal_courses_same_slots(self):
        """levelsApart: два уровня по 2 урока — ровно одни и те же слоты."""
        settings = tiny(5, 3, [
            course("Осн", "Математика", 2, program="ЕГЭ основной"),
            course("Пр", "Математика", 2, program="ЕГЭ продвинутый")
        ], {"T1": teacher("Математика", ["Осн"]), "T2": teacher("Математика", ["Пр"])})

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed, weights={"levelsApart": 1000})
            self.assertEqual(slots(answer, "Осн"), slots(answer, "Пр"), seed)
            self.assertEqual(len(slots(answer, "Осн")), 2, seed)

    def test_levels_energy_in_progress_line(self):
        """Строка «Шаг» после 1e6 шагов: уровни совпали — «неудобства: 0 (лучшее пока 0)»."""
        answer, log = solved(self, self.levels(), 7, 1000000, weights={"levelsApart": 1000})
        self.assertLessEqual(slots(answer, "Осн"), slots(answer, "Пр"))
        self.assertIn("| неудобства: 0 (лучшее пока 0)", lastStep(log))

    def test_two_lessons_same_day_in_progress_line(self):
        """Два закрепления курса в один день: в строке «Шаг» — «2 урока курса в день: 1».
        Свободный курс B нужен, чтобы отжиг вообще запускался (когда всё закреплено, строк «Шаг» нет)."""
        settings = tiny(3, 3, [course("A", "Математика", 2), course("B", "Химия")],
                        {"T": teacher("Математика", ["A"]), "TB": teacher("Химия", ["B"])},
                        constants={"A": {"0-0": "Математика", "0-1": "Математика"}})
        answer, log = solved(self, settings, 1, 1000000)
        self.assertEqual(slots(answer, "A"), {(0, 0), (0, 1)})
        self.assertIn("| 2 урока курса в день: 1 |", lastStep(log))

    def test_soft_pairs_counted_in_progress_line_with_zero_weight(self):
        """Вес пар «нежелательно» 0: единственный слот, пара Математика + Физика в одной линейке и потоке
        неизбежна, и строка «Шаг» всё равно показывает её — «пары «нежелательно»: 1» (как «Предпросмотр»).

        Раньше движок при весе 0 вовсе не считал такие пары и писал в строке хода 0, хотя
        «Предпросмотр» (он считает пары без учёта веса) показывал 1. Второй прогон — с пустым
        файлом весов, то есть с весами, встроенными в движок, — проверяет, что и при ненулевом
        весе число то же.
        """
        settings = tiny(1, 1, [course("A", "Математика"), course("B", "Физика")],
                        {"T1": teacher("Математика", ["A"]), "T2": teacher("Физика", ["B"])},
                        soft_subject_pairs=[["Математика", "Физика"]])

        for weights in ({"softSubjectPair": 0}, {}):
            _, log = solved(self, settings, 1, 1000000, weights=weights)
            self.assertIn("| пары «нежелательно»: 1 |", lastStep(log), weights)

    def test_adjacent_days_penalty(self):
        """Собственный штраф adjacent: 3 урока курса в 5-дневной неделе — только дни 0, 2, 4."""
        settings = tiny(5, 2, [course("A", "Математика", 3)], {"T": teacher("Математика", ["A"])},
                        custom_penalties_compiled={"adjacent": {"A": 5000}})

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed)
            self.assertEqual(days(answer, "A"), [0, 2, 4], seed)

    def test_group_daily_limit(self):
        """Собственный штраф group_daily (A и B вместе не больше 1 урока в день): в каждом дне ≤ 1 урока группы."""
        settings = tiny(2, 3, [course("A", "Математика"), course("B", "Математика")],
                        {"T1": teacher("Математика", ["A"]), "T2": teacher("Математика", ["B"])},
                        custom_penalties_compiled={"group_daily": [{"classes": ["A", "B"], "limit": 1, "weight": 5000}]})

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed)
            self.assertEqual(sorted(days(answer, "A") + days(answer, "B")), [0, 1], seed)

    def test_group_daily_counts_repeated_course_once(self):
        """Курс, записанный в группу group_daily дважды, считается один раз: вход с группой [A, A, B]
        даёт тот же ответ и тот же журнал, что с [A, B], и неудобства 0 (A и B в разные дни).
        Если A считать дважды, его урок один уже превышает лимит 1 — неудобства не ниже 5000."""
        def group(classes):
            """Вход: A и B по уроку, вместе не больше 1 урока в день."""
            return tiny(2, 3, [course("A", "Математика"), course("B", "Математика")],
                        {"T1": teacher("Математика", ["A"]), "T2": teacher("Математика", ["B"])},
                        custom_penalties_compiled={"group_daily": [{"classes": classes, "limit": 1, "weight": 5000}]})

        for seed in (1, 2):
            answer, log = solved(self, group(["A", "A", "B"]), seed, 1000000)
            self.assertEqual((answer, log), solved(self, group(["A", "B"]), seed, 1000000), seed)
            self.assertIn("| неудобства: 0 (лучшее пока 0)", lastStep(log), seed)
            self.assertEqual(sorted(days(answer, "A") + days(answer, "B")), [0, 1], seed)

    def test_same_day_penalty(self):
        """Собственный штраф same_day (A и B не в один день): у A и B по 2 урока, общих дней нет."""
        settings = tiny(5, 3, [course("A", "Математика", 2), course("B", "Математика", 2)],
                        {"T1": teacher("Математика", ["A"]), "T2": teacher("Математика", ["B"])},
                        custom_penalties_compiled={"same_day": [{"a": "A", "b": "B", "weight": 5000}]})

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed)
            self.assertEqual(len(days(answer, "A")), 2, seed)
            self.assertFalse(set(days(answer, "A")) & set(days(answer, "B")), seed)

    def test_same_day_pairs_weight(self):
        """pairsSameDay со списком same_day_pairs: дни A и B не пересекаются; при весе 0 — пересекаются."""
        settings = tiny(5, 3, [course("A", "Математика", 2), course("B", "Математика", 2)],
                        {"T1": teacher("Математика", ["A"]), "T2": teacher("Математика", ["B"])},
                        custom_penalties_compiled={"same_day_pairs": [["A", "B"]]})
        common = []

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed, weights={"pairsSameDay": 5000})
            self.assertEqual(len(days(answer, "B")), 2, seed)
            self.assertFalse(set(days(answer, "A")) & set(days(answer, "B")), seed)

            # Контроль: без веса пары ничем не разводятся (жадный старт собирает предмет в одни слоты)
            answer, _ = solved(self, settings, seed, weights={"pairsSameDay": 0})
            common.append(set(days(answer, "A")) & set(days(answer, "B")))

        self.assertTrue(any(common))


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class EngineMoveTests(unittest.TestCase):
    """Ходы и выбор преподавателя: вставка непоставленного, закрепления, семинары, «хватает» ли часов и дней."""

    def stuck(self):
        """Вход, где жадная расстановка заведомо упирается.

        B (Физика, T2: удобно только (1,0), (0,0) — «может») ставится первым в (1,0); у A (Математика,
        2 урока, T1 не может (1,1)) остаётся только день 0 — второй урок не встаёт (пара «нельзя» с B).
        Решение есть: B в (0,0), A в (0,1) и (1,0).
        """
        return tiny(2, 2, [course("A", "Математика", 2), course("B", "Физика")], {
            "T1": teacher("Математика", ["A"], free=[(1, 1)]),
            "T2": teacher("Физика", ["B"], free=[(0, 1), (1, 1)], possible=[(0, 0)])
        }, joint_subject_pairs=[["Математика", "Физика"]])

    def test_annealing_inserts_missing_lesson(self):
        """Без отжига урок не поставлен («не удалось поставить уроков: 1»), после отжига — все уроки на месте."""
        settings = self.stuck()

        for seed in SEEDS:
            _, log = solved(self, settings, seed, 0)
            self.assertIn(MISSING_TOTAL + "1", log, seed)

            answer, log = solved(self, settings, seed)
            self.assertNotIn(MISSING_TOTAL, log, seed)
            self.assertEqual(slots(answer, "A"), {(0, 1), (1, 0)}, seed)
            self.assertEqual(slots(answer, "B"), {(0, 0)}, seed)

    def test_pinned_lesson_of_two_subject_course_stays(self):
        """Курс из двух предметов, Математика закреплена в (1,2): после отжига в (1,2) всегда Математика."""
        group = {"name": "A", "program": "ЕГЭ основной", "line": "ЕГЭ", "stream_id": 1, "subjects": ["Математика", "Физика"]}
        settings = tiny(3, 3, [], {"T1": teacher("Математика", ["A"]), "T2": teacher("Физика", ["A"])},
                        constants={"A": {"1-2": "Математика"}})
        settings["classes"] = {"custom_groups": [group], "lessons": {"A": {"Математика": 1, "Физика": 1}}}

        for seed in SEEDS:
            answer, _ = solved(self, settings, seed)
            self.assertEqual(answer["A"][1][2], {"subject": "Математика", "teachers": ["T1"]}, seed)
            self.assertEqual(len(cellsOf(answer, "A")), 2, seed)

    def test_seminars_without_stream_ignore_forbidden_pairs(self):
        """Семинары без потока одной линейки: пара «нельзя» между ними не действует —
        оба урока встают в единственный общий свободный слот."""
        settings = tiny(1, 2, [
            course("Семинар ОГЭ: Математика", "Математика", program="Семинар", line="Семинар ОГЭ", stream=None),
            course("Семинар ОГЭ: Физика", "Физика", program="Семинар", line="Семинар ОГЭ", stream=None)
        ], {
            "T1": teacher("Математика", ["Семинар ОГЭ: Математика"], free=[(0, 1)]),
            "T2": teacher("Физика", ["Семинар ОГЭ: Физика"], free=[(0, 1)])
        }, joint_subject_pairs=[["Математика", "Физика"]])

        for seed in (1, 2):
            answer, log = solved(self, settings, seed)
            self.assertNotIn(MISSING_TOTAL, log, seed)
            self.assertEqual(slots(answer, "Семинар ОГЭ: Математика"), {(0, 0)}, seed)
            self.assertEqual(slots(answer, "Семинар ОГЭ: Физика"), {(0, 0)}, seed)

    def test_teacher_choice_counts_days(self):
        """Выбор из «может вести»: у T1 6 свободных уроков, но в одном дне; у T2 по уроку в двух днях.
        Для курса из 2 уроков выбран T2, и оба урока поставлены."""
        settings = tiny(2, 6, [course("A", "Математика", 2)], {
            "T1": teacher("Математика", ["A"], free=[(1, lesson) for lesson in range(6)]),
            "T2": teacher("Математика", ["A"], free=[slot for slot in allSlots(2, 6) if slot[1] != 0])
        })

        for seed in (1, 2):
            answer, log = solved(self, settings, seed)
            self.assertNotIn(MISSING_TOTAL, log, seed)
            self.assertEqual(sorted(cellsOf(answer, "A")), [(0, 0, "Математика", "T2"), (1, 0, "Математика", "T2")], seed)

    def test_teacher_choice_ignores_blocked_slots(self):
        """Выбор из «может вести»: все свободные слоты T1 закрыты для курса (blocked_slots), у T2 — открыты.
        Выбран T2, все уроки поставлены."""
        open_slots = [(0, 0), (1, 0)]
        settings = tiny(2, 3, [course("A", "Математика", 2)], {
            "T1": teacher("Математика", ["A"], free=open_slots),
            "T2": teacher("Математика", ["A"], free=[slot for slot in allSlots(2, 3) if slot not in open_slots])
        }, blocked_slots={"A": [list(slot) for slot in allSlots(2, 3) if slot not in open_slots]})

        for seed in (1, 2):
            answer, log = solved(self, settings, seed)
            self.assertNotIn(MISSING_TOTAL, log, seed)
            self.assertEqual(sorted(cellsOf(answer, "A")), [(0, 0, "Математика", "T2"), (1, 0, "Математика", "T2")], seed)

    def test_pin_with_lesson_outside_day(self):
        """Закрепление «0-3» при 3 уроках в дне: предупреждение «out of range», урок не попадает
        в (1,0) (там у преподавателя «может») и ставится в удобный слот как обычный."""
        settings = tiny(2, 3, [course("A", "Математика")], {"T": teacher("Математика", ["A"], possible=[(1, 0)])},
                        constants={"A": {"0-3": "Математика"}})

        for seed in (1, 2, 3):
            answer, log = solved(self, settings, seed)
            self.assertIn('[WARNING] constants: key "0-3" out of range for A', log)
            self.assertEqual(len(cellsOf(answer, "A")), 1, seed)
            self.assertNotIn((1, 0), slots(answer, "A"), seed)
