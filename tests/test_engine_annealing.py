"""Сколько подбирать движку solve.exe и как идёт отжиг — по журналу (stdout) и ответу.

* строка «Закреплено N из M уроков, подбирается K» сразу после закреплённых уроков: N — закрепления,
  которые встали, K — уроки, которые подбирает программа, хвост «без преподавателя» — уроки курсов,
  которым преподаватель не нашёлся (нет подходящих или у всех уже максимум курсов);
* строка «Из неудобств X дают закреплённые уроки»: урок в выходной, слот «может», цена слота
  из своих правил — у закреплённого урока они не меняются;
* K = 0 — отжиг не запускается, строка называет причину (всё закреплено / остальным урокам некому
  вести / уроков нет); K ≤ 2 — предупреждение, что варианты совпадут;
* ранняя остановка при K ≤ 5, если лучшее не менялось 1 млн шагов; при K > 5 её нет;
* последний цикл отжига всегда полный и остывает до конечной температуры.

Маленькие входы и разбор строк журнала — в `tests/engine.py`. Итоговая строка «Готово: …» —
в `test_engine_rules.py` (test_progress_and_final_lines).
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
import unittest

from tests.builders import SOLVER
from tests.engine import (
    LITTLE_TO_SOLVE, NOTHING_EMPTY, NOTHING_TO_SOLVE, NOTHING_WITHOUT_TEACHER, NO_TEACHER, LIMIT_REACHED, PIN_FAILED, cellsOf,
    course, earlyStop, finalLine, pinSummary, pinnedPenalty, progressLines, runSolver, solved, teacher, tiny
)

MILLION = 1000000


def cheapSlot(index):
    """Единственный бесплатный слот свободного курса номер `index` (день, урок); урок 0 занят закреплениями."""
    return index % 5, 1 + index // 5


def pinnedWeek(movable):
    """Неделя 5 × 6: курс A (5 уроков) закреплён в урок 0 каждого дня, и `movable` свободных курсов
    F0, F1, … по уроку, у каждого свой преподаватель. Свой штраф 1000 за любой слот курса, кроме
    cheapSlot: лучшее расписание единственное, неудобства 0, и жадная расстановка его не знает —
    отжигу есть что улучшать."""
    names = [f"F{index}" for index in range(movable)]
    teachers = {"TA": teacher("Математика", ["A"])}
    teachers.update({f"T{index}": teacher("Физика", [name]) for index, name in enumerate(names)})
    prices = {
        name: [[day, lesson, 1000] for day in range(5) for lesson in range(6) if (day, lesson) != cheapSlot(index)]
        for index, name in enumerate(names)
    }

    return tiny(5, 6, [course("A", "Математика", 5)] + [course(name, "Физика") for name in names], teachers,
                constants={"A": {f"{day}-0": "Математика" for day in range(5)}},
                custom_penalties_compiled={"class_slots": prices})


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class PinSummaryTests(unittest.TestCase):
    """«Закреплено N из M уроков, подбирается K[, без преподавателя (не ставятся): X]», M = N + K + X."""

    def summary(self, settings, expected):
        """Прогон без отжига: строка журнала даёт `expected` = (N, M, K, X). Возвращает stdout."""
        _, log = solved(self, settings, 1, 1000)
        found = pinSummary(log)
        self.assertEqual(found, expected, log)
        self.assertEqual(found[1], found[0] + found[2] + found[3])
        return log

    def test_without_pins(self):
        """Закреплений нет: подбираются все уроки, хвоста «без преподавателя» нет."""
        settings = tiny(2, 2, [course("A", "Математика", 2), course("B", "Физика")],
                        {"T1": teacher("Математика", ["A"]), "T2": teacher("Физика", ["B"])})
        log = self.summary(settings, (0, 3, 3, 0))
        self.assertIn("Закреплено 0 из 3 уроков, подбирается 3\n", log)
        self.assertNotIn("без преподавателя", log)

    def test_placed_pins(self):
        """Закрепления, которые встали, — в N; остальные уроки курса подбираются."""
        settings = tiny(2, 2, [course("A", "Математика", 2), course("B", "Физика")],
                        {"T1": teacher("Математика", ["A"]), "T2": teacher("Физика", ["B"])},
                        constants={"A": {"0-0": "Математика"}, "B": {"1-1": "Физика"}})
        self.summary(settings, (2, 3, 1, 0))

    def test_failed_pins_are_counted_as_movable(self):
        """Закрепление, которое не встало (закрытый слот, «не может», закреплений больше часов),
        не входит в N: его урок подбирается и считается в K."""
        settings = tiny(2, 3, [course("A", "Математика", 2), course("B", "Физика"), course("C", "Химия")], {
            "TA": teacher("Математика", ["A"]),
            "TB": teacher("Физика", ["B"]),
            "TC": teacher("Химия", ["C"], free=[(0, 2)])
        }, constants={
            "A": {"0-0": "Математика", "1-0": "Математика"},
            "B": {"0-1": "Физика", "1-1": "Физика"},
            "C": {"0-2": "Химия"}
        }, blocked_slots={"A": [[0, 0]]})
        log = self.summary(settings, (2, 4, 2, 0))

        # Причины, по которым два закрепления не встали, и лишнее закрепление B
        self.assertIn(PIN_FAILED.format(course="A", subject="Математика", day=1, lesson=1) + "это время закрыто", log)
        self.assertIn(PIN_FAILED.format(course="C", subject="Химия", day=1, lesson=3) + "преподаватель TC", log)
        self.assertIn("закреплено больше уроков, чем часов у курса", log)

    def test_courses_without_teacher(self):
        """Часы курса без подходящих преподавателей (B) и курса, которому преподаватель не достался
        из-за лимита курсов (Y), — в хвосте «без преподавателя»; закрепление урока B не считается;
        предмет с нулевыми часами (Z) не входит в M."""
        settings = tiny(2, 2, [
            course("A", "Математика", 2),
            course("Y", "Математика", 2, line="Y"),
            course("B", "Физика"),
            course("Z", "Химия", 0)
        ], {"T1": teacher("Математика", ["A", "Y"]), "TZ": teacher("Химия", ["Z"])},
            max_courses_per_teacher=1, constants={"A": {"0-0": "Математика"}, "B": {"1-0": "Физика"}})
        log = self.summary(settings, (1, 5, 1, 3))

        self.assertIn(NO_TEACHER.format(course="B", subject="Физика"), log)
        self.assertIn(LIMIT_REACHED.format(course="Y", subject="Математика"), log)
        self.assertIn("Закреплено 1 из 5 уроков, подбирается 1, без преподавателя (не ставятся): 3\n", log)


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class PinnedPenaltyTests(unittest.TestCase):
    """«Из неудобств X дают закреплённые уроки»: X — та часть итоговых неудобств, которую программа
    не может уменьшить."""

    def test_number_equals_pinned_part_of_total(self):
        """A закреплён в выходной (5000), в слот «может» (300) и в слот со своей ценой курса (70)
        и преподавателя (11): строка даёт 5381, и ровно столько же — лучшие неудобства в строке «Шаг»
        (свободный урок B без штрафов, окон у TA нет: у него по уроку в день)."""
        settings = tiny(6, 2, [course("A", "Математика", 3), course("B", "Физика")],
                        {"TA": teacher("Математика", ["A"], possible=[(1, 0)]), "TB": teacher("Физика", ["B"])},
                        constants={"A": {"5-0": "Математика", "1-0": "Математика", "2-1": "Математика"}},
                        custom_penalties_compiled={"class_slots": {"A": [[2, 1, 70]]}, "teacher_slots": {"TA": [[2, 1, 11]]}})

        for seed in (1, 2):
            _, log = solved(self, settings, seed, MILLION, weights={"weekendLesson": 5000, "teacherPossibleSlot": 300})
            self.assertEqual(pinnedPenalty(log), 5381, log)
            self.assertEqual(progressLines(log)[-1][3], 5381, log)

    def test_no_line_without_pinned_penalty(self):
        """Строки нет, если закреплённые уроки ничего не стоят: закреплений нет; закрепление в выходной
        при весе выходных 0; закрепление в удобный слот."""
        free = tiny(6, 2, [course("A", "Математика", 2)], {"T": teacher("Математика", ["A"])})
        weekend = tiny(6, 2, [course("A", "Математика", 2)], {"T": teacher("Математика", ["A"], possible=[(1, 1)])},
                       constants={"A": {"5-0": "Математика", "1-0": "Математика"}})

        for settings in (free, weekend):
            _, log = solved(self, settings, 1, 1000)
            self.assertIsNotNone(pinSummary(log), log)
            self.assertIsNone(pinnedPenalty(log), log)


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class NothingToSolveTests(unittest.TestCase):
    """K = 0 — отжиг не запускается; 1 ≤ K ≤ 2 — предупреждение, что варианты совпадут."""

    def assertNothingToSolve(self, settings, summary, line):
        """K = 0: строка «Закреплено …» — ``summary``, из строк «Подбирать нечего» — только ``line``;
        строк «Шаг» нет даже при 5 млн шагов, код 0, в итоге — 0 оценённых изменений. Возвращает ответ
        (у этапа без курсов он пустой — None)."""
        code, answer, log, errors = runSolver(settings, 1, 5 * MILLION)

        self.assertEqual(code, 0, errors)

        self.assertEqual(pinSummary(log), summary, log)
        self.assertEqual([text for text in (NOTHING_TO_SOLVE, NOTHING_WITHOUT_TEACHER, NOTHING_EMPTY, LITTLE_TO_SOLVE) if text in log], [line], log)
        self.assertIn(line + "\n", log)
        self.assertEqual(progressLines(log), [])
        self.assertNotIn("Шаг ", log)
        self.assertIsNone(earlyStop(log))
        self.assertIn("Готово: оценено изменений 0 из ", log)

        return answer

    def test_all_lessons_pinned(self):
        """Все уроки закреплены: «все уроки закреплены», в ответе ровно закреплённые уроки."""
        settings = tiny(2, 3, [course("A", "Математика", 2)], {"T": teacher("Математика", ["A"])},
                        constants={"A": {"0-1": "Математика", "1-2": "Математика"}})
        answer = self.assertNothingToSolve(settings, (2, 2, 0, 0), NOTHING_TO_SOLVE)

        self.assertEqual(cellsOf(answer, "A"), [(0, 1, "Математика", "T"), (1, 2, "Математика", "T")])

    def test_rest_without_teacher(self):
        """Незакреплённые уроки — только у курсов без преподавателя: нет подходящих (B) или у всех
        уже максимум курсов (Y). «Все уроки закреплены» тут неправда — строка говорит, что остальным
        некому вести; так же, когда закреплённых нет вовсе (новый этап, преподаватели не отмечены)."""
        pinned = tiny(2, 3, [course("A", "Математика", 2), course("B", "Физика")], {"T": teacher("Математика", ["A"])},
                      constants={"A": {"0-1": "Математика", "1-2": "Математика"}})
        answer = self.assertNothingToSolve(pinned, (2, 3, 0, 1), NOTHING_WITHOUT_TEACHER)

        self.assertEqual(cellsOf(answer, "A"), [(0, 1, "Математика", "T"), (1, 2, "Математика", "T")])
        self.assertEqual(cellsOf(answer, "B"), [])

        limit = tiny(2, 2, [course("A", "Математика"), course("Y", "Математика", line="Y")], {"T": teacher("Математика", ["A", "Y"])},
                     max_courses_per_teacher=1, constants={"A": {"0-0": "Математика"}})
        self.assertNothingToSolve(limit, (1, 2, 0, 1), NOTHING_WITHOUT_TEACHER)

        nobody = tiny(2, 2, [course("A", "Математика"), course("B", "Физика")], {})
        self.assertNothingToSolve(nobody, (0, 2, 0, 2), NOTHING_WITHOUT_TEACHER)

    def test_empty_stage(self):
        """В этапе нет ни одного урока: «в этом потоке или блоке курсов нет уроков», а не «все уроки закреплены»."""
        self.assertNothingToSolve(tiny(2, 2, [], {}), (0, 0, 0, 0), NOTHING_EMPTY)

    def test_little_to_solve(self):
        """«Подбирать почти нечего» — только при K = 1 и K = 2."""
        for movable in (1, 2, 3, 6):
            with self.subTest(movable):
                _, log = solved(self, pinnedWeek(movable), 1, 1000)
                self.assertEqual(pinSummary(log), (5, 5 + movable, movable, 0), log)
                self.assertEqual(LITTLE_TO_SOLVE in log, movable <= 2, log)
                self.assertNotIn(NOTHING_TO_SOLVE, log)


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class EarlyStopTests(unittest.TestCase):
    """Ранняя остановка: подбирается K ≤ 5 уроков и лучшее не менялось 1 млн шагов."""

    def test_one_movable_lesson_stops_early(self):
        """K = 1, бюджет 4 млн: остановка на 1 или 2 млн шагов со строкой о причине, строки «Шаг»
        обрываются на шаге остановки, ответ — лучшее расписание (F0 в бесплатном слоте, неудобства 0),
        итог «Готово» на месте."""
        for seed in (1, 2):
            with self.subTest(seed):
                answer, log = solved(self, pinnedWeek(1), seed, 4 * MILLION)
                stop = earlyStop(log)
                self.assertIsNotNone(stop, log)
                step, total, movable = stop
                self.assertEqual((total, movable), (4 * MILLION, 1))
                self.assertIn(step, (MILLION, 2 * MILLION))

                steps = progressLines(log)
                self.assertEqual([item[0] for item in steps], list(range(MILLION, step + 1, MILLION)))
                self.assertEqual(steps[-1][3], 0, log)
                self.assertLess(log.index(f"Шаг {step} из"), log.index("Остановлено на шаге"))
                self.assertIsNotNone(finalLine(log), log)

                self.assertEqual(cellsOf(answer, "F0"), [(0, 1, "Физика", "T0")])
                self.assertEqual(sorted(cellsOf(answer, "A")), [(day, 0, "Математика", "TA") for day in range(5)])

    def test_five_movable_lessons_stop(self):
        """Граница: K = 5 — тоже остановка раньше бюджета, все свободные курсы в бесплатных слотах."""
        answer, log = solved(self, pinnedWeek(5), 1, 3 * MILLION)
        stop = earlyStop(log)
        self.assertIsNotNone(stop, log)
        self.assertLess(stop[0], 3 * MILLION)
        self.assertEqual(stop[2], 5)

        for index in range(5):
            self.assertEqual(cellsOf(answer, f"F{index}"), [(*cheapSlot(index), "Физика", f"T{index}")])

    def test_six_movable_lessons_run_full_budget(self):
        """K = 6: лучшее давно не меняется, но остановки нет — все строки «Шаг» до конца бюджета,
        в итоге «Готово» — весь бюджет шагов."""
        _, log = solved(self, pinnedWeek(6), 1, 2 * MILLION)
        self.assertIsNone(earlyStop(log), log)
        self.assertNotIn("Остановлено", log)
        self.assertEqual([item[0] for item in progressLines(log)], [MILLION, 2 * MILLION])
        self.assertEqual(progressLines(log)[-1][3], 0, log)

        final = finalLine(log)
        self.assertIsNotNone(final, log)
        self.assertEqual(final[1], 2 * MILLION)


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class CycleTests(unittest.TestCase):
    """Число шагов не делится на длину цикла: последний цикл всё равно полный и остывает."""

    def test_last_cycle_cools_down(self):
        """2 млн шагов при цикле 1,5 млн (--cycle): циклы становятся по 1 млн, и к последнему шагу
        температура снова конечная. Шесть курсов (K = 6, ранней остановки нет), у каждого
        преподавателя удобен один слот, остальные — «может» (300). При горячем старте (t0 = 1e6)
        текущее расписание к концу остывшего цикла совпадает с лучшим: «неудобства: 0 (лучшее пока 0)»
        в последней строке «Шаг». Раньше последний цикл в 0,5 млн шагов обрывался горячим
        (T около 10 000), и текущее расписание к концу было случайным."""
        names = [f"F{index}" for index in range(6)]
        teachers = {
            f"T{index}": teacher("Физика", [name], possible=[(day, lesson) for day in range(5) for lesson in range(6)
                                                           if (day, lesson) != cheapSlot(index)])
            for index, name in enumerate(names)
        }
        settings = tiny(5, 6, [course(name, "Физика") for name in names], teachers)

        for seed in (1, 2):
            with self.subTest(seed):
                _, log = solved(self, settings, seed, 2 * MILLION, extra=("--t0", "1e6", "--tend", "1", "--cycle", "1500000"))
                self.assertEqual(progressLines(log)[-1], (2 * MILLION, 2 * MILLION, 0, 0), log)
