"""Смена преподавателя в подборе (ход 4 движка solve.exe, .spec/teacher-swap) — по выходу настоящего solve.exe.

* ``BetterTeacherTests`` — ход находит преподавателя получше: рабочий день и часы «может» (AC-1),
  уровни ЕГЭ (AC-2);
* ``FixedTeacherTests`` — что ход не трогает: «ведёт» (AC-3), ручные закрепления времени (AC-5),
  курсы из ``keep_teacher_courses`` (AC-6, ключ входа движка). Каждая проверка с контролем: на том
  же входе без «ведёт» / закрепления / keep курс достаётся Петровой — иначе «не тронул» доказывал бы
  только то, что хода нет;
* ``KeptCoursesTests`` — идущий курс и курс из «оставить принятое» в настоящем входе этапа
  (``buildStageSettings(..., keep=keepCourses(...))``) сохраняют преподавателя из расписания (AC-4,
  часть движка);
* ``RulesWithSwapTests`` — жёсткие правила, лимит курсов и один преподаватель на курс на входах
  с курсами со сменой (лимит, урезанная доступность, закрепления, свои правила, непоставленные уроки,
  Поток 2 без «ведёт») с частым возвратом к лучшему (``--cycle 1000``) (AC-7, AC-8, AC-9);
* ``NoGainTests`` — без выигрыша преподаватель не меняется (решение заказчика 4, цена «без выигрыша»);
* ``CompatTests`` — побайтная совместимость с прежним движком там, где менять некому, и повтор
  прогона с тем же зерном (AC-13).

Маленькие входы (``twoCandidates``, ``levelsCase``), эталоны прежнего движка и разбор ответа —
в ``tests/engine.py``. AC-14 (старые тесты движка зелёные без изменения ожиданий) проверяют сами
старые тесты: ``test_engine_*``, ``test_functions_solver_input``, ``test_structure``.
Отладочная сборка с проверкой энергии (``-DCHECK_ENERGY``) — ``test_engine_swap_check.py``.

Тесты пропускаются, если solve.exe не собран.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import collections
import json
import os
import random
import re
import tempfile
import unittest

from src.variables import DEFAULT_WEIGHTS
from src.modules.functions.courses import addCourse
from src.modules.functions.model import teacherAvailability
from src.modules.functions.solver_input import buildStageSettings, keepCourses
from tests.builders import SOLVER, baseSettings, emptyWeek, makeSettings, place, readJson, teacher as projectTeacher
from tests.engine import (
    ASSIGNED_OVER, B_CANNOT, LEVEL_ADVANCED, LEVEL_SLOTS, MISSING_TOTAL, PIN_FAILED, SWAP_COURSE, SWAP_SUBJECT, TEACHER_A, TEACHER_B, TEACHER_C,
    bestEnergy, cellsOf, compatFiles, compatRuns, course, courseTeachers, coursesPerTeacher, levelMismatches, levelsCase,
    pinnedPenalty, ruleViolations, runRaw, runSolver, solved, stageInput, swapCandidates, teacher, twoCandidates
)

MILLION = 1000000
# Шагов на маленьких входах: решение находится за доли этого числа (прогон — сотые секунды)
SHORT = 100000
SEEDS = (1, 2, 3, 4, 5)
SWAP_KEY = (SWAP_COURSE, SWAP_SUBJECT)
LEVERS = ("workday", "possible")


def teachersOf(answer, key=SWAP_KEY):
    """Кто ведёт уроки курса и предмета ``key`` в ответе: множество имён (пустое — уроков нет)."""
    return courseTeachers(answer).get(key, set())


class SwapCase(unittest.TestCase):
    """Общие проверки маленьких входов: прогон, кто ведёт курс, контроль хода."""

    def teacherOf(self, settings, weights, seed, iterations=SHORT, key=SWAP_KEY):
        """Прогон, который должен пройти без нарушений жёстких правил: (кто ведёт ``key``, ответ, журнал)."""
        answer, log = solved(self, settings, seed, iterations, weights)
        self.assertEqual(ruleViolations(settings, answer, log), [], log)
        return teachersOf(answer, key), answer, log

    def assertSwapWorks(self, lever, seeds=SEEDS):
        """Контроль: на входе ``twoCandidates(lever)`` без «ведёт», закрепления и keep курс ведёт Петрова.
        Без этого проверка «ход курс не тронул» проходила бы и у движка, где хода нет вовсе."""
        settings, weights = twoCandidates(lever)

        for seed in seeds:
            names, _, log = self.teacherOf(settings, weights, seed)
            self.assertEqual(names, {TEACHER_B}, f"контроль ({lever}), зерно {seed}: ход 4 не сменил Иванову на Петрову\n{log}")


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class BetterTeacherTests(SwapCase):
    """Ход 4 отдаёт курс кандидату, с которым расписание лучше."""

    def test_busy_day_teacher_takes_the_course(self):
        """AC-1. Курс на 1 урок, кандидаты Иванова и Петрова, «ведёт» нет; до отжига выбирается Иванова
        (больше свободных часов). Петрова уже работает в день 1 (teacher_busy_days), Иванова — нигде.
        На 5 зёрнах: курс ведёт Петрова, урок в день 1, лучшая энергия меньше, чем у ответа с Ивановой
        на том же входе (рабочий день Ивановой не оплачивается)."""
        settings, weights = twoCandidates("workday")
        with_a, _ = twoCandidates("workday", assigned=TEACHER_A)

        for seed in SEEDS:
            names, answer, log = self.teacherOf(settings, weights, seed, MILLION)
            _, answer_a, log_a = self.teacherOf(with_a, weights, seed, MILLION)

            self.assertEqual(names, {TEACHER_B}, f"зерно {seed}: курс ведёт не Петрова\n{log}")
            self.assertEqual([day for day, *_ in cellsOf(answer, SWAP_COURSE)], [1], answer)
            self.assertIsNotNone(bestEnergy(log), log)
            self.assertLess(bestEnergy(log), bestEnergy(log_a), (log, log_a))

    def test_possible_slots_lever(self):
        """AC-1 (рычаг «может»). У Ивановой все часы «может» (вес 300), у Петровой — обычные: на 5 зёрнах
        курс ведёт Петрова, хотя до отжига выбрана Иванова."""
        settings, weights = twoCandidates("possible")

        for seed in SEEDS:
            names, _, log = self.teacherOf(settings, weights, seed)
            self.assertEqual(names, {TEACHER_B}, f"зерно {seed}\n{log}")

    def test_levels_reference_of_old_engine(self):
        """AC-2, эталон. Вход эталона ``levels`` — это ``levelsCase()``; прежний движок (до хода 4) на всех
        его зёрнах отдаёт «ЕГЭ продвинутый» Ивановой, и уровни врозь (levelsApart > 0)."""
        settings, _ = levelsCase()
        files = compatFiles("levels")

        self.assertEqual(readJson(files["input"]), settings)

        for seed in compatRuns()["levels"]["seeds"]:
            answer = readJson(compatFiles("levels", seed)["answer"])
            self.assertEqual(teachersOf(answer, (LEVEL_ADVANCED, SWAP_SUBJECT)), {TEACHER_A})
            self.assertGreater(levelMismatches(settings, answer), 0)

    def test_levels_apart_fixed_by_swap(self):
        """AC-2. «ЕГЭ основной» закреплён («ведёт» + constants) в часах LEVEL_SLOTS, где Иванова, выбранная
        до отжига для «ЕГЭ продвинутого», «не может»; Петрова в эти часы свободна. На 5 зёрнах:
        «ЕГЭ продвинутый» ведёт Петрова, уровни врозь — 0 (уроки уровней совпадают)."""
        settings, weights = levelsCase()
        key = (LEVEL_ADVANCED, SWAP_SUBJECT)

        for seed in SEEDS:
            names, answer, log = self.teacherOf(settings, weights, seed, key=key)
            self.assertEqual(names, {TEACHER_B}, f"зерно {seed}: «ЕГЭ продвинутый» ведёт не Петрова\n{log}")
            self.assertEqual(levelMismatches(settings, answer), 0, answer)
            self.assertEqual(sorted((day, lesson) for day, lesson, *_ in cellsOf(answer, LEVEL_ADVANCED)), sorted(LEVEL_SLOTS))


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class FixedTeacherTests(SwapCase):
    """Курсы с неподвижным преподавателем: ход 4 их не трогает, даже если с другим было бы лучше."""

    def test_assigned_teacher_stays(self):
        """AC-3. «Ведёт» Иванова, а Петрова дала бы меньшую энергию (оба рычага): на 10 зёрнах все
        уроки курса ведёт Иванова. Контроль: без «ведёт» курс ведёт Петрова."""
        for lever in LEVERS:
            settings, weights = twoCandidates(lever, assigned=TEACHER_A)

            for seed in range(1, 11):
                names, _, log = self.teacherOf(settings, weights, seed)
                self.assertEqual(names, {TEACHER_A}, f"{lever}, зерно {seed}\n{log}")

            self.assertSwapWorks(lever)

    def test_pinned_course_keeps_teacher(self):
        """AC-5. У курса без «ведёт» ручное закрепление времени (constants) в часе (1, 0); с Петровой
        было бы лучше (у Ивановой все часы «может»). На 5 зёрнах курс ведёт Иванова — и когда
        закрепление встало, и когда не встало (у Ивановой «не может» в этом часе, строка
        «[Внимание] закреплённый урок … не поставлен»). Строка «Из неудобств E дают закреплённые
        уроки» совпадает с пересчётом по ответу. Контроль: без закрепления курс ведёт Петрова."""
        pin = (1, 0)

        for blocked in (False, True):
            settings, weights = twoCandidates("possible", pin=pin, pinBlocked=blocked)

            for seed in SEEDS:
                names, answer, log = self.teacherOf(settings, weights, seed)
                self.assertEqual(names, {TEACHER_A}, f"закрепление {'не встало' if blocked else 'встало'}, зерно {seed}\n{log}")

                failed = PIN_FAILED.format(course=SWAP_COURSE, subject=SWAP_SUBJECT, day=pin[0] + 1, lesson=pin[1] + 1)
                self.assertEqual(failed in log, blocked, log)
                self.assertEqual(answer[SWAP_COURSE][pin[0]][pin[1]]["subject"] == SWAP_SUBJECT, not blocked, answer)
                self.assertEqual(pinnedPenalty(log) or 0, pinnedRecount(settings, answer, weights), log)

        self.assertSwapWorks("possible")

    def test_keep_teacher_courses_key(self):
        """AC-6 (ключ входа движка). Курс в ``keep_teacher_courses``, с Петровой было бы лучше (оба
        рычага): на 5 зёрнах курс ведёт выбранная до отжига Иванова. Контроль: без ключа — Петрова."""
        for lever in LEVERS:
            settings, weights = twoCandidates(lever, keep=True)

            for seed in SEEDS:
                names, _, log = self.teacherOf(settings, weights, seed)
                self.assertEqual(names, {TEACHER_A}, f"{lever}, зерно {seed}\n{log}")

            self.assertSwapWorks(lever)


def pinnedRecount(settings, answer, weights):
    """«Из неудобств E дают закреплённые уроки», пересчитанное по ответу: вес «может» за каждый
    закреплённый урок, который стоит на месте у преподавателя с отметкой «может» в этом часе
    (выходных и своих правил на входах twoCandidates нет)."""
    total = 0

    for name, pins in settings.get("constants", {}).items():
        for key, subject in pins.items():
            day, lesson = map(int, key.split("-"))
            cell = answer[name][day][lesson]

            if cell["subject"] == subject and [day, lesson] in settings["teachers"][cell["teachers"][0]].get("possible", []):
                total += weights.get("teacherPossibleSlot", 0)

    return total


# Даты начала: курс с уроками в расписании и датой в прошлом «уже идёт», с датой в будущем — ещё нет
PAST = "2020-01-01"
FUTURE = "2999-01-01"


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class KeptCoursesTests(SwapCase):
    """Идущие курсы и «оставить принятое» во входе этапа, собранном программой."""

    def keptProject(self):
        """Этап «Поток 1»: идущий курс химии ОГЭ и принятый, но не идущий курс химии ЕГЭ основной;
        обоих «может вести» Иванова, Петрова и Смирнова. В принятом расписании идущий курс ведёт
        Смирнова, принятый — Иванова; у обеих на этапе все часы «может» (вес 300), у Петровой —
        «не может» в B_CANNOT (свободных часов меньше, до отжига её не выбирают), так что с Петровой
        любой из курсов был бы лучше. Возвращает (настройки, расписание, идущий курс, принятый курс,
        веса, {курс: преподаватель в расписании})."""
        names = (TEACHER_A, TEACHER_B, TEACHER_C)
        settings = baseSettings(subjects=[[SWAP_SUBJECT, 1]], teachers={name: projectTeacher(SWAP_SUBJECT) for name in names})
        running = addCourse(settings, 1, "ОГЭ", SWAP_SUBJECT, 1, PAST)
        accepted = addCourse(settings, 1, "ЕГЭ основной", SWAP_SUBJECT, 1, FUTURE)

        for name in (TEACHER_A, TEACHER_C):
            teacherAvailability(settings["teachers"][name], "1")["possible"] = [[day, lesson] for day in range(5) for lesson in range(3)]

        teacherAvailability(settings["teachers"][TEACHER_B], "1")["free"] = [list(slot) for slot in B_CANNOT]

        answer = {
            running: place(emptyWeek(5), 1, 1, SWAP_SUBJECT, TEACHER_C),
            accepted: place(emptyWeek(5), 3, 1, SWAP_SUBJECT, TEACHER_A)
        }

        return settings, answer, running, accepted, {"teacherPossibleSlot": 300}, {running: TEACHER_C, accepted: TEACHER_A}

    def test_running_and_kept_courses_keep_teacher(self):
        """AC-4 (часть движка). Вход ``buildStageSettings(..., keep=keepCourses(...))``: у идущего курса
        во входе «ведёт» Смирнова, у принятого — Иванова, как в расписании, и на 5 зёрнах их уроки
        ведут они же, хотя с Петровой было бы лучше. Контроль: без keep принятый, но не идущий курс
        (до отжига — Иванова) достаётся Петровой, а идущий по-прежнему ведёт Смирнова."""
        settings, answer, running, accepted, weights, owners = self.keptProject()
        keep = keepCourses(settings, answer, "1")
        inp = buildStageSettings(settings, answer, "1", keep=keep)

        self.assertEqual(sorted(keep), sorted([running, accepted]))

        for name, owner in owners.items():
            self.assertEqual(inp["teachers"][owner]["subjects"][0]["assigned"], [name], inp["teachers"])

        for seed in SEEDS:
            answer_k, log = solved(self, inp, seed, SHORT, weights)
            self.assertEqual(ruleViolations(inp, answer_k, log), [], log)

            for name, owner in owners.items():
                self.assertEqual(teachersOf(answer_k, (name, SWAP_SUBJECT)), {owner}, f"{name}, зерно {seed}\n{log}")

        fresh = buildStageSettings(settings, answer, "1")

        for seed in SEEDS:
            answer_f, log = solved(self, fresh, seed, SHORT, weights)
            self.assertEqual(ruleViolations(fresh, answer_f, log), [], log)
            self.assertEqual(teachersOf(answer_f, (running, SWAP_SUBJECT)), {TEACHER_C}, log)
            self.assertEqual(teachersOf(answer_f, (accepted, SWAP_SUBJECT)), {TEACHER_B}, f"контроль, зерно {seed}: ход 4 не сменил Иванову\n{log}")


# ---------------------------------------------------------------- AC-7…AC-9: входы с курсами со сменой

# Шагов и зёрен на каждом входе правил; --cycle 1000 — частый возврат к лучшему (saveBest, Р-4)
RULE_STEPS = 300000
RULE_SEEDS = (1, 2, 3)
RULE_CYCLE = ("--cycle", "1000")
WEEK = [(day, lesson) for day in range(5) for lesson in range(3)]
MISSING_LINE = re.compile(rf"^{re.escape(MISSING_TOTAL)}(\d+)$", re.M)


def streamInput(stage="1"):
    """Вход этапа стандартной программы ``makeSettings``: 5 преподавателей на предмет, каждый «может
    вести» все курсы своего предмета, «ведёт» нет, сетка 5 × 3."""
    return stageInput(makeSettings(), {}, stage)


def subjectOf(inp, name):
    """Единственный предмет курса ``name`` во входе."""
    return next(subject for subject, hours in inp["classes"]["lessons"][name].items() if hours)


def coursesOf(inp, subject):
    """Курсы входа с уроками предмета ``subject`` в порядке входа."""
    return [name for name, load in inp["classes"]["lessons"].items() if load.get(subject, 0) > 0]


def limitInput():
    """Лимит курсов 3 и по 2 кандидата на предмет (#1 и #2): смены упираются в лимит. Математика #2
    и Физика #1 уже ведут курсы в других этапах (existing), Химия #1 «ведёт» все 4 курса химии —
    выше лимита из-за одних «ведёт»."""
    inp = streamInput()
    inp["teachers"] = {name: data for name, data in inp["teachers"].items() if name.endswith((" #1", " #2"))}
    inp["max_courses_per_teacher"] = 3
    inp["existing_courses_by_teacher"] = {"Математика #2": 1, "Физика #1": 2}
    inp["teachers"]["Химия #1"]["subjects"][0]["assigned"] = coursesOf(inp, "Химия")
    return inp


def tightInput():
    """Урезанная доступность: у каждого преподавателя «не может» примерно в половине часов и «может»
    ещё в части; лимит курсов 2."""
    inp = streamInput()
    rnd = random.Random(7)

    for name in sorted(inp["teachers"]):
        data = inp["teachers"][name]
        data["free"] = [[day, lesson] for day, lesson in WEEK if rnd.random() < 0.5]
        data["possible"] = [[day, lesson] for day, lesson in WEEK if [day, lesson] not in data["free"] and rnd.random() < 0.2]

    inp["max_courses_per_teacher"] = 2
    return inp


def pinsInput():
    """Закрепления времени у каждого третьего курса (без «ведёт»); одно закрепление не встаёт (все
    кандидаты курса «не могут» в этом часе); у двух закреплённых курсов «ведёт» #3; три курса
    в ``keep_teacher_courses``."""
    inp = streamInput()
    names = list(inp["classes"]["lessons"])
    pinned = names[::3]

    for index, name in enumerate(pinned):
        inp["constants"][name] = {f"{index % 5}-{index % 3}": subjectOf(inp, name)}

    subject = subjectOf(inp, pinned[0])

    for number in range(1, 6):
        inp["teachers"][f"{subject} #{number}"]["free"].append([0, 0])

    for name in pinned[1:3]:
        inp["teachers"][f"{subjectOf(inp, name)} #3"]["subjects"][0]["assigned"].append(name)

    inp["keep_teacher_courses"] = names[1:12:4]
    return inp


def customInput():
    """Свои правила: цены часов преподавателей и курсов, дневной лимит преподавателя, лимит линейки ОГЭ,
    соседние дни и «в один день»."""
    inp = streamInput()
    rnd = random.Random(11)
    teachers = sorted(inp["teachers"])
    names = list(inp["classes"]["lessons"])
    custom = inp["custom_penalties_compiled"]

    custom["teacher_slots"] = {name: [[day, lesson, rnd.choice((20, 50, 120))] for day, lesson in rnd.sample(WEEK, 4)] for name in teachers[::2]}
    custom["teacher_daily"] = {name: [[1, 60]] for name in teachers[1::3]}
    custom["class_slots"] = {name: [[day, lesson, 40] for day, lesson in rnd.sample(WEEK, 3)] for name in names[::4]}
    custom["group_daily"] = [{"classes": [name for name in names if " ОГЭ " in name], "limit": 2, "weight": 30}]
    custom["adjacent"] = {name: 25 for name in names[::5]}
    custom["same_day"] = [{"a": names[0], "b": names[1], "weight": 35}]
    return inp


def missingInput():
    """Непоставленные уроки: у преподавателей математики свободны 4 часа на всех (#1 — дни 0 и 1,
    #2 — дни 2 и 3, первый урок; #3…#5 «не могут» никогда), а уроков математики 7 — 3 не встают."""
    inp = streamInput()
    open_hours = {"Математика #1": [(0, 0), (1, 0)], "Математика #2": [(2, 0), (3, 0)]}

    for number in range(1, 6):
        name = f"Математика #{number}"
        inp["teachers"][name]["free"] = [[day, lesson] for day, lesson in WEEK if (day, lesson) not in open_hours.get(name, [])]

    return inp


def stream2Input():
    """Поток 2 без «ведёт»: у преподавателей случайные «может» и «не может», у части — рабочий день
    в других этапах (teacher_busy_days)."""
    inp = streamInput("2")
    rnd = random.Random(5)
    teachers = sorted(inp["teachers"])

    for name in teachers:
        data = inp["teachers"][name]
        data["free"] = [[day, lesson] for day, lesson in WEEK if rnd.random() < 0.15]
        data["possible"] = [[day, lesson] for day, lesson in WEEK if [day, lesson] not in data["free"] and rnd.random() < 0.3]

    inp["teacher_busy_days"] = {name: [rnd.randrange(5)] for name in teachers[::3]}
    return inp


RULE_INPUTS = {
    "лимит 3": limitInput,
    "урезанная доступность": tightInput,
    "закрепления": pinsInput,
    "свои правила": customInput,
    "непоставленные уроки": missingInput,
    "Поток 2 без «ведёт»": stream2Input,
}


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class RulesWithSwapTests(unittest.TestCase):
    """AC-7…AC-9: ответы на входах с курсами со сменой. Каждый вход прогоняется один раз на класс
    (3 зерна по RULE_STEPS шагов с --cycle 1000) и ещё раз без шагов — выбор преподавателей до отжига."""

    @classmethod
    def setUpClass(cls):
        """Прогоны всех входов RULE_INPUTS: {имя: {"input", "weights", "greedy", "runs": [(зерно, код, ответ, журнал, stderr)]}}."""
        weights = readJson(DEFAULT_WEIGHTS)
        cls.results = {}

        for name, build in RULE_INPUTS.items():
            inp = build()
            _, greedy, _, _ = runSolver(inp, 1, 0, weights)
            runs = [(seed, *runSolver(inp, seed, RULE_STEPS, weights, extra=RULE_CYCLE)) for seed in RULE_SEEDS]
            cls.results[name] = {"input": inp, "weights": weights, "greedy": greedy, "runs": runs}

    def answers(self):
        """(имя входа, вход, зерно, ответ, журнал) для всех прогонов; код 0 и ответ есть."""
        for name, result in self.results.items():
            for seed, code, answer, log, errors in result["runs"]:
                with self.subTest(input=name, seed=seed):
                    self.assertEqual(code, 0, errors)
                    self.assertIsNotNone(answer)

                yield name, result["input"], seed, answer, log

    def assertTeachersChanged(self):
        """Входы и правда проверяют ход: на каждом входе хотя бы на одном зерне у какого-то курса
        преподаватель не тот, что выбран до отжига (иначе проверка правил ничего не говорит о ходе 4)."""
        unchanged = []

        for name, result in self.results.items():
            before = courseTeachers(result["greedy"])
            changed = sum(
                1 for _, _, answer, _, _ in result["runs"] if answer
                for key, names in courseTeachers(answer).items() if key in before and names != before[key]
            )

            if not changed:
                unchanged.append(name)

        self.assertEqual(unchanged, [], "ход 4 не сменил ни одного преподавателя на этих входах")

    def test_inputs_are_what_they_claim(self):
        """AC-7, входы. У каждого входа есть курсы со сменой (Р-3, ``swapCandidates``); на входе
        «непоставленные уроки» не встают 3 урока («не удалось поставить уроков: 3»), на входе
        «закрепления» одно закрепление не встаёт, на входе «лимит 3» Химия #1 выше лимита из-за «ведёт»."""
        for name, result in self.results.items():
            self.assertTrue(swapCandidates(result["input"]), name)

        for _, _, _, log, _ in self.results["непоставленные уроки"]["runs"]:
            self.assertEqual(MISSING_LINE.findall(log), ["3"], log)

        for _, _, _, log, _ in self.results["закрепления"]["runs"]:
            self.assertEqual(log.count("[Внимание] закреплённый урок "), 1, log)

        for _, _, _, log, _ in self.results["лимит 3"]["runs"]:
            self.assertIn(ASSIGNED_OVER.format(teacher="Химия #1"), log)

    def test_hard_rules(self):
        """AC-7. На всех входах и зёрнах ``ruleViolations`` пуст: преподаватель из «может вести»,
        совпадает с «ведёт», не в часы «не может», не на двух уроках сразу; ход 4 правда менял
        преподавателей."""
        for name, inp, seed, answer, log in self.answers():
            with self.subTest(input=name, seed=seed):
                self.assertEqual(ruleViolations(inp, answer, log), [], log)

        self.assertTeachersChanged()

    def test_course_limit(self):
        """AC-8. У каждого преподавателя existing + число его пар «курс + предмет» ≤ лимита; кто выше
        лимита из-за одних «ведёт», тому ход курсов не добавляет (курсов ровно «ведёт» + existing)."""
        for name, inp, seed, answer, log in self.answers():
            limit = max(1, inp.get("max_courses_per_teacher", 5))
            existing = inp.get("existing_courses_by_teacher", {})
            fixed = collections.Counter(
                teacher_name for teacher_name, data in inp["teachers"].items()
                for item in data["subjects"] for _ in item.get("assigned", [])
            )

            for teacher_name, count in coursesPerTeacher(inp, answer).items():
                base = existing.get(teacher_name, 0) + fixed[teacher_name]

                with self.subTest(input=name, seed=seed, teacher=teacher_name):
                    if base > limit:
                        self.assertEqual(count, base)
                    else:
                        self.assertLessEqual(count, limit)

        self.assertTeachersChanged()

    def test_one_teacher_per_course(self):
        """AC-9. У каждой пары «курс + предмет» во всех клетках ответа один преподаватель — в том числе
        на входе с непоставленными уроками, где ход 3 вставляет уроки после смен."""
        for name, inp, seed, answer, log in self.answers():
            with self.subTest(input=name, seed=seed):
                self.assertEqual({key: names for key, names in courseTeachers(answer).items() if len(names) != 1}, {})

        self.assertTeachersChanged()


# ---------------------------------------------------------------- Цена «без выигрыша» (решение заказчика 4)

# Равноценные курсы: по курсу на поток 2…5 (физика ОГЭ, 1 урок), у каждого свои два кандидата.
# У второго «не может» в B_CANNOT — до отжига выбирается первый, а энергия с обоими одинакова
EQUAL_STREAMS = (2, 3, 4, 5)


def equalName(stream):
    """Название равноценного курса потока ``stream``."""
    return f"Поток {stream} — ОГЭ — Физика"


def noGainInput():
    """Вход ``twoCandidates()`` (курс с выигрышем у Петровой, вес рабочего дня 1000) плюс равноценные
    курсы EQUAL_STREAMS: (вход, веса, {курс: преподаватель до отжига})."""
    settings, _ = twoCandidates("workday")
    expected = {}

    for stream in EQUAL_STREAMS:
        group, load = course(equalName(stream), "Физика", program="ОГЭ", line="ОГЭ", stream=stream)
        settings["classes"]["custom_groups"].append(group)
        settings["classes"]["lessons"][group["name"]] = load
        first, second = f"Орлова {stream}", f"Соколова {stream}"
        settings["teachers"][first] = teacher("Физика", [group["name"]])
        settings["teachers"][second] = teacher("Физика", [group["name"]], free=B_CANNOT)
        expected[group["name"]] = first

    return settings, {"teacherWorkDays": 1000}, expected


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class NoGainTests(SwapCase):
    """Решение заказчика 4: смена «без выигрыша» не делается."""

    def test_equal_candidates_keep_teacher(self):
        """Цена «без выигрыша». Четыре курса с равноценными кандидатами (энергия с любым одинакова)
        и курс, где Петрова даёт выигрыш (рабочий день). На 5 зёрнах: у равноценных курсов преподаватель
        тот, что выбран до отжига (сменилось 0 курсов), а курс с выигрышем ведёт Петрова."""
        settings, weights, expected = noGainInput()

        for seed in SEEDS:
            names, answer, log = self.teacherOf(settings, weights, seed)
            changed = sorted(name for name, first in expected.items() if teachersOf(answer, (name, "Физика")) != {first})

            self.assertEqual(changed, [], f"зерно {seed}: сменилось курсов без выигрыша: {len(changed)}\n{log}")
            self.assertEqual(names, {TEACHER_B}, f"зерно {seed}: курс с выигрышем ведёт не Петрова\n{log}")


# ---------------------------------------------------------------- AC-13: совместимость

# Входы эталонов, где курсов со сменой нет: ответ и журнал нового движка те же байты, что у прежнего
COMPAT_INPUTS = ("all_assigned", "one_candidate", "limit", "pins_keep")


def readBytes(path):
    """Содержимое файла байтами."""
    with open(path, "rb") as file:
        return file.read()


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class CompatTests(unittest.TestCase):
    """AC-13: побайтная совместимость и повторяемость."""

    def test_same_bytes_as_old_engine(self):
        """AC-13. На входах без курсов со сменой (все «ведёт»; один кандидат; лимит не даёт сменить;
        без «ведёт» только курсы с закреплением и из keep_teacher_courses) ответ и журнал solve.exe
        побайтно равны эталону прежнего движка на тех же зёрнах, шагах и флагах (tests/fixtures/engine_compat)."""
        runs = compatRuns()

        for name in COMPAT_INPUTS:
            files = compatFiles(name)
            self.assertEqual(swapCandidates(readJson(files["input"])), {}, name)

            for seed in runs[name]["seeds"]:
                with self.subTest(input=name, seed=seed):
                    reference = compatFiles(name, seed)
                    code, answer, log, errors = runRaw(files["input"], files["weights"], seed, runs[name]["iterations"], runs[name]["extra"])

                    self.assertEqual(code, 0, errors)
                    self.assertEqual(log, readBytes(reference["log"]))
                    self.assertEqual(answer, readBytes(reference["answer"]))

    def test_same_seed_same_bytes(self):
        """AC-13. Повторный прогон с тем же зерном на входе с курсами со сменой (Поток 2 без «ведёт»,
        --cycle 1000 — частые возвраты к лучшему) даёт побайтно тот же ответ и журнал."""
        inp = stream2Input()
        self.assertTrue(swapCandidates(inp))

        with tempfile.TemporaryDirectory() as folder:
            paths = {name: os.path.join(folder, f"{name}.json") for name in ("input", "weights")}

            with open(paths["input"], "w", encoding="utf-8") as file:
                json.dump(inp, file, ensure_ascii=False)

            with open(paths["weights"], "w", encoding="utf-8") as file:
                json.dump(readJson(DEFAULT_WEIGHTS), file)

            for seed in (1, 2):
                first = runRaw(paths["input"], paths["weights"], seed, RULE_STEPS, RULE_CYCLE)
                second = runRaw(paths["input"], paths["weights"], seed, RULE_STEPS, RULE_CYCLE)

                self.assertEqual(first[0], 0, first[3])
                self.assertIsNotNone(first[1])
                self.assertEqual(first[1:3], second[1:3], f"зерно {seed}")


# ---------------------------------------------------------------- Доводка по ходу 4 и величина цены смены

# Горячий прогон: температура не падает (--t0 = --tend), лучшее запоминается в случайный момент блуждания
from tests.engine import tiny  # noqa: E402 (маленький вход с ценами часов; импорт рядом с новыми тестами)

HOT = ("--t0", "10000000", "--tend", "10000000")
HOT_STEPS = 200000


def hotInput():
    """Четыре равноценных курса (как в ``noGainInput``: Орлова и Соколова, у Соколовой «не может»
    в B_CANNOT, до отжига — Орлова) и три «шумных» курса химии по 3 урока, которые ведёт своя
    преподавательница, со своими ценами часов (class_slots) в 70 % клеток. Лучшая энергия «шума»
    встречается в блуждании редко, и в момент рекорда равноценные курсы стоят случайно — то у Орловой,
    то у Соколовой. Возвращает (вход, {равноценный курс: преподаватель до отжига})."""
    rnd = random.Random(3)
    courses, teachers, expected, prices = [], {}, {}, {}

    for stream in EQUAL_STREAMS:
        name = equalName(stream)
        courses.append(course(name, "Физика", program="ОГЭ", line="ОГЭ", stream=stream))
        teachers[f"Орлова {stream}"] = teacher("Физика", [name])
        teachers[f"Соколова {stream}"] = teacher("Физика", [name], free=B_CANNOT)
        expected[name] = f"Орлова {stream}"

    for number in range(3):
        name = f"Поток {number + 6} — ЕГЭ основной — Химия"
        courses.append(course(name, "Химия", 3, stream=number + 6))
        teachers[f"Шумова {number}"] = teacher("Химия", [name], [name])
        prices[name] = [[day, lesson, rnd.choice((10, 20, 30, 40, 50))] for day, lesson in WEEK if rnd.random() < 0.7]

    return tiny(5, 3, courses, teachers, custom_penalties_compiled={"class_slots": prices}), expected


def smallGainInput(lever):
    """Смена с выигрышем 10 при весах с ползунков, где самое лёгкое неудобство больше 20: (вход, веса).

    Один день, 6 уроков. Курс X (1 урок) может стоять только на 5-м уроке (остальные клетки дня
    в blocked_slots); «может вести» A и B, до отжига — A (B ведёт ещё два курса, курсов у него больше).
    B уже работает в этот день: «ведёт» Y (закреплён на 1-м уроке) и Z (закреплён на 3-м или 6-м).

    * ``"windows"`` — окна «Важно» (30), рабочий день 100: с A энергия 100 + 100 + 30 (окно B) = 230,
      с B — 100 + 30 · 2² = 220;
    * ``"possible"`` — окна 0, «может» «Немного» (90), рабочий день 100; у B «может» в клетке X:
      с A 200, с B 190.
    """
    names = (("X", "S1"), ("Y", "S2"), ("Z", "S3"))
    weights = readJson(DEFAULT_WEIGHTS)
    weights["teacherWorkDays"] = 100

    if lever == "windows":
        weights["teacherFreeTime"] = 30
        b_possible, z_slot = [], "0-2"
    elif lever == "possible":
        weights["teacherFreeTime"] = 0
        weights["teacherPossibleSlot"] = 90
        b_possible, z_slot = [[0, 4]], "0-5"
    else:
        raise ValueError(lever)

    settings = {
        "subjects": [[subject, 1] for _, subject in names],
        "classes": {
            "custom_groups": [{"name": name, "program": name, "line": name, "subjects": [subject]} for name, subject in names],
            "lessons": {name: {subject: 1} for name, subject in names}
        },
        "teachers": {
            "A": {"subjects": [{"subject": "S1", "classes": ["X"], "assigned": []}], "free": [], "possible": []},
            "B": {
                "subjects": [
                    {"subject": "S1", "classes": ["X"], "assigned": []},
                    {"subject": "S2", "classes": ["Y"], "assigned": ["Y"]},
                    {"subject": "S3", "classes": ["Z"], "assigned": ["Z"]}
                ],
                "free": [],
                "possible": b_possible
            }
        },
        "constants": {"Y": {"0-0": "S2"}, "Z": {z_slot: "S3"}},
        "max_courses_per_teacher": 5,
        "working_days_per_week": 1,
        "max_lesson_count_per_day": 6,
        "blocked_slots": {"X": [[0, 0], [0, 1], [0, 2], [0, 3], [0, 5]]},
        "joint_subject_pairs": [],
        "non_overlapping_programs": [],
        "soft_subject_pairs": []
    }

    return settings, weights


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class SwapPolishTests(SwapCase):
    """Решение заказчика 4 в ответе, а не только в оценке: смены без выигрыша нет, смена с выигрышем есть."""

    def test_hot_best_has_no_change_without_gain(self):
        """Лучшее запоминается в горячей части цикла вместе со сменами, принятыми «в гору». После возврата
        к лучшему движок делает все смены с Δ < 0 (раздел 8), в том числе возвращает выбранного до отжига
        там, где смена ничего не дала. Горячий прогон на ``hotInput``: на 5 зёрнах равноценные курсы ведёт
        Орлова. Без доводки на этих зёрнах у части курсов оставалась Соколова."""
        settings, expected = hotInput()

        for seed in SEEDS:
            answer, log = solved(self, settings, seed, HOT_STEPS, {}, extra=HOT)
            self.assertEqual(ruleViolations(settings, answer, log), [], log)
            changed = sorted(name for name, first in expected.items() if teachersOf(answer, (name, "Физика")) != {first})
            self.assertEqual(changed, [], f"зерно {seed}: смены без выигрыша в ответе\n{log}")

    def test_small_gain_is_taken(self):
        """Цена смены меньше любого настоящего выигрыша. Веса с ползунков: самое лёгкое неудобство 30 или 90,
        а выигрыш смены — 10 (разность сумм весов). Цена «половина самого лёгкого» (15 и 45) такую смену
        запрещала; цена «половина НОД весов» (5) — нет. На 5 зёрнах курс X ведёт B, и лучшая энергия
        (с ценой смены) меньше, чем у ответа с «ведёт» A."""
        for lever in ("windows", "possible"):
            settings, weights = smallGainInput(lever)
            with_a = json.loads(json.dumps(settings))
            with_a["teachers"]["A"]["subjects"][0]["assigned"] = ["X"]

            for seed in SEEDS:
                answer, log = solved(self, settings, seed, MILLION, weights)
                _, log_a = solved(self, with_a, seed, MILLION, weights)

                self.assertEqual(ruleViolations(settings, answer, log), [], log)
                self.assertEqual(teachersOf(answer, ("X", "S1")), {"B"}, f"{lever}, зерно {seed}\n{log}")
                self.assertLess(bestEnergy(log), bestEnergy(log_a), (log, log_a))


# ---------------------------------------------------------------- Доводка: обмен курсами без выигрыша

from tests.engine import LEVEL_BASIC  # noqa: E402 (основной уровень пары; импорт рядом с новыми тестами)

# Клетки, открытые обоим уровням pairInput: в одной клетке уровни вместе, в разных — врозь
PAIR_CELLS = ((0, 0), (1, 0))


def pairInput():
    """Два уровня ЕГЭ по математике (``LEVEL_BASIC``, ``LEVEL_ADVANCED``, по 1 уроку) с «может вести»
    Иванова и Петрова, «ведёт» нет; уровням открыты только клетки PAIR_CELLS, вес ``levelsApart`` 1000.
    До отжига «ЕГЭ основной» достаётся Ивановой, «ЕГЭ продвинутый» — Петровой (у неё меньше курсов).
    Плюс три «шумных» курса химии из ``hotInput`` (свои цены часов), чтобы лучшее запоминалось в разных
    состояниях. Обмен курсами (основной — Петровой, продвинутый — Ивановой) в одной клетке даёт те же
    штрафы преподавателей и две цены смены; вернуть один курс нельзя — преподаватель был бы на двух
    уроках сразу. Возвращает (вход, веса)."""
    settings, _ = hotInput()
    teachers = {name: data for name, data in settings["teachers"].items() if name.startswith("Шумова")}
    noise = [group for group in settings["classes"]["custom_groups"] if group["name"] in settings["custom_penalties_compiled"]["class_slots"]]
    courses = [
        course(LEVEL_BASIC, SWAP_SUBJECT, program="ЕГЭ основной"),
        course(LEVEL_ADVANCED, SWAP_SUBJECT, program="ЕГЭ продвинутый"),
    ]
    teachers[TEACHER_A] = teacher(SWAP_SUBJECT, [LEVEL_BASIC, LEVEL_ADVANCED])
    teachers[TEACHER_B] = teacher(SWAP_SUBJECT, [LEVEL_BASIC, LEVEL_ADVANCED])
    courses += [(group, settings["classes"]["lessons"][group["name"]]) for group in noise]
    blocked = [[day, lesson] for day, lesson in WEEK if (day, lesson) not in PAIR_CELLS]

    return tiny(5, 3, courses, teachers, blocked_slots={LEVEL_BASIC: blocked, LEVEL_ADVANCED: blocked},
                custom_penalties_compiled=settings["custom_penalties_compiled"]), {"levelsApart": 1000}


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class SwapPairPolishTests(SwapCase):
    """Доводка возвращает и пару курсов, обменявшихся преподавателями без выигрыша."""

    def test_exchanged_levels_are_returned(self):
        """Решение заказчика 4 для пары. Уровни стоят вместе; если лучшее запомнилось с обменом курсами
        (Иванова ↔ Петрова), одиночный возврат невозможен, а совместный даёт Δ = −2 цены смены. На 5 зёрнах
        обычного прогона: уровни вместе, «ЕГЭ основной» ведёт Иванова, «ЕГЭ продвинутый» — Петрова.
        Без совместного возврата на зёрнах 2 и 4 оставался обмен."""
        settings, weights = pairInput()

        for seed in SEEDS:
            answer, log = solved(self, settings, seed, SHORT, weights)
            self.assertEqual(ruleViolations(settings, answer, log), [], log)
            self.assertEqual(levelMismatches(settings, answer), 0, f"зерно {seed}\n{log}")
            pair = (teachersOf(answer, (LEVEL_BASIC, SWAP_SUBJECT)), teachersOf(answer, (LEVEL_ADVANCED, SWAP_SUBJECT)))
            self.assertEqual(pair, ({TEACHER_A}, {TEACHER_B}), f"зерно {seed}: обмен курсами без выигрыша в ответе\n{log}")
