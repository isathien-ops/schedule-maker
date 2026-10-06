"""Отладочная проверка энергии движка: сборка solve.cpp с флагом -DCHECK_ENERGY (смена преподавателя в подборе).

Спека .spec/teacher-swap (подзадача T3): AC-8 (смены отклоняются по лимиту курсов), AC-9 (у непоставленных
уроков тот же преподаватель, что в клетках), AC-10 (подсчёт энергии по частям равен полному пересчёту),
решение Р-11 (отладочная проверка — отдельная сборка, в solve.exe для завуча её нет).

Тест сам собирает ``src/modules/solve.cpp`` с ``-DCHECK_ENERGY`` во временную папку — тем же g++ и с теми же
флагами, что ``compile.bat``: g++ из PATH, а если его там нет, то из папки WinLibs (winget), путь к которой
берётся из самого ``compile.bat``. Без g++ тесты пропускаются (skip) с причиной. Сборка — около 30 с,
один раз на класс; прогоны на маленьких входах — секунды.

Чего тест ждёт от отладочной сборки (договорённость для T6, флагов командной строки она не добавляет):

* раз в N шагов (N ≤ 100 000, так что на 2 млн шагов проверок не меньше 20) текущая энергия сравнивается
  с полным пересчётом, а состояние — с пересчётом (рёбра курса и преподавателя зеркальны, один
  преподаватель на курс + предмет, у непоставленных уроков тот же преподаватель, счётчики курсов равны
  пересчёту, лимит соблюдён);
* в конце журнала строка ``CHECK checks=<число> bad=<число> badState=<число> … limitRejects=<число>``:
  ``limitRejects`` — сколько раз ход 4 не дал курс преподавателю, у которого уже максимум курсов.

Входы — как в AC-7, только меньше (5 дней × 4 урока, 16 курсов, без «ведёт», почти все курсы со сменой):
лимит курсов 4; урезанная доступность и лимит 5; закрепления; свои правила; непоставленные уроки;
Поток 2 без «ведёт». Собираются здесь же (``stressInput``) из построителей ``tests/engine.py``.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import collections
import os
import random
import re
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from tests import engine
from tests.builders import SOLVER
from tests.engine import MISSING_TOTAL, course, courseTeachers, coursesPerTeacher, ruleViolations, swapCandidates, teacher, tiny

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPILE_BAT = os.path.join(ROOT, "compile.bat")

# Итог отладочной сборки и счётчик отказов хода 4 по лимиту курсов (в той же строке CHECK)
CHECK_LINE = re.compile(r"^CHECK checks=(\d+) bad=(\d+) badState=(\d+)\b.*$", re.M)
LIMIT_REJECTS = re.compile(r"\blimitRejects=(\d+)\b")
MISSING_COUNT = re.compile("^" + re.escape(MISSING_TOTAL) + r"(\d+)$", re.M)

# AC-10: 2 млн шагов, циклы по 100 тыс. (частый возврат к лучшему), проверок не меньше 20 на вход
ITERATIONS = 2000000
CYCLE = ("--cycle", "100000")
MIN_CHECKS = 20
SEED = 1

# Сетка входов и веса (все ненулевые, чтобы в энергии участвовали все слагаемые)
DAYS, LESSONS = 5, 4
WEIGHTS = {
    "teacherFreeTime": 10, "teacherPossibleSlot": 300, "softSubjectPair": 1000, "weekendLesson": 50,
    "teacherWorkDays": 100, "levelsApart": 500, "pairsSameDay": 200
}

# Преподавателей на предмет: каждый «может вести» все курсы своего предмета, «ведёт» нет
STAFF = {"Математика": 4, "Русский язык": 3, "Физика": 2, "Химия": 2, "Информатика": 2, "Английский язык": 2}

# Программы этапа: (программа, линейка, {предмет: уроков в неделю}); плюс семинар по математике
PROGRAMS = (
    ("ЕГЭ основной", "ЕГЭ", {"Математика": 3, "Русский язык": 2, "Информатика": 2, "Английский язык": 2}),
    ("ЕГЭ продвинутый", "ЕГЭ", {"Математика": 3, "Русский язык": 2, "Информатика": 2, "Английский язык": 2}),
    ("ОГЭ", "ОГЭ", {"Математика": 2, "Русский язык": 2, "Физика": 2, "Химия": 2}),
    ("10 класс", "10 класс", {"Математика": 2, "Физика": 2, "Химия": 1}),
)
SEMINAR = "Семинар ЕГЭ — Математика"

# Входы AC-7 (уменьшенные) и зерно случайных «не может» у каждого
KINDS = {
    "limit4": 11,       # лимит 4, у пяти преподавателей по 3 курса в других этапах
    "tight": 7,         # у каждого преподавателя «не может» около 45 % ячеек, лимит 5
    "pins": 13,         # закрепления времени без «ведёт» (одно не встаёт), пара «ведёт», keep
    "custom": 17,       # свои правила всех видов
    "missing": 19,      # не меньше 3 непоставленных уроков у курсов с двумя кандидатами
    "stream2": 23,      # Поток 2 без «ведёт», уровни ЕГЭ, занятость в других этапах
}


def teacherName(subject, number):
    """Имя преподавателя входа: «Математика #1»."""
    return f"{subject} #{number}"


def courseName(stream, program, subject):
    """Имя курса входа: «Поток 1 — ЕГЭ основной — Математика»."""
    return f"Поток {stream} — {program} — {subject}"


def cannot(rnd, share, days=range(DAYS)):
    """Случайные ячейки «не может»: каждая ячейка дней `days` с вероятностью `share`."""
    return [[day, lesson] for day in days for lesson in range(LESSONS) if rnd.random() < share]


def stressInput(kind):
    """Вход AC-7 вида `kind` (см. KINDS): (вход, веса).

    Общее у всех: два уровня ЕГЭ по четырём предметам в одной линейке (``levelsApart``), ОГЭ с парой
    «нельзя» Физика/Химия, «нежелательно» Математика/Физика, семинар, который не пересекается с ЕГЭ
    продвинутым, «может» и занятые дни у части преподавателей. Почти у всех курсов несколько кандидатов
    и нет «ведёт» — ход 4 трогает их постоянно.
    """
    rnd = random.Random(KINDS[kind])
    stream = 2 if kind == "stream2" else 1
    courses = []
    candidates = collections.defaultdict(list)

    for program, line, load in PROGRAMS:
        for subject, hours in load.items():
            name = courseName(stream, program, subject)
            courses.append(course(name, subject, hours, program=program, line=line, stream=stream))
            candidates[subject].append(name)

    courses.append(({"name": SEMINAR, "program": "Семинар ЕГЭ", "line": "Семинар ЕГЭ", "subjects": ["Математика"]}, {"Математика": 1}))
    candidates["Математика"].append(SEMINAR)

    teachers = {
        teacherName(subject, number): teacher(subject, candidates[subject])
        for subject, count in STAFF.items() for number in range(1, count + 1)
    }
    teachers[teacherName("Математика", 2)]["possible"] = [[1, 3], [2, 3], [3, 3]]
    teachers[teacherName("Английский язык", 1)]["possible"] = [[4, 0], [4, 1]]
    teachers[teacherName("Математика", 3)]["free"] = [[0, 0], [0, 1], [1, 0]]

    inp = tiny(DAYS, LESSONS, courses, teachers)
    inp["subjects"] = [[name, 1] for name in sorted(STAFF)]
    inp["joint_subject_pairs"] = [["Физика", "Химия"]]
    inp["soft_subject_pairs"] = [["Математика", "Физика"]]
    inp["non_overlapping_programs"] = [["Семинар ЕГЭ", "ЕГЭ продвинутый"]]
    inp["teacher_busy_days"] = {teacherName("Математика", 1): [2], teacherName("Русский язык", 1): [0]}
    load = inp["classes"]["lessons"]

    def name(program, subject):
        """Курс этого входа."""
        return courseName(stream, program, subject)

    if kind == "limit4":
        inp["max_courses_per_teacher"] = 4
        inp["existing_courses_by_teacher"] = {
            teacherName(subject, 1): 3 for subject in ("Математика", "Русский язык", "Физика", "Информатика")
        } | {teacherName("Математика", 2): 3}

    elif kind == "tight":
        inp["max_courses_per_teacher"] = 5

        for item in teachers.values():
            item["free"] = cannot(rnd, 0.45)

    elif kind == "pins":
        inp["constants"] = {
            name("ЕГЭ основной", "Математика"): {"0-0": "Математика"},
            name("ОГЭ", "Русский язык"): {"1-1": "Русский язык"},
            name("10 класс", "Физика"): {"3-2": "Физика"},
            name("ЕГЭ продвинутый", "Информатика"): {"2-1": "Информатика"},
        }
        # Закрепление «ЕГЭ продвинутый — Информатика» не встаёт: ячейка закрыта для курса
        inp["blocked_slots"] = {name("ЕГЭ продвинутый", "Информатика"): [[2, 1]]}
        teachers[teacherName("Химия", 2)]["subjects"][0]["assigned"] = [name("ОГЭ", "Химия")]
        teachers[teacherName("Английский язык", 1)]["subjects"][0]["assigned"] = [name("ЕГЭ основной", "Английский язык")]
        inp["keep_teacher_courses"] = [name("10 класс", "Математика")]

    elif kind == "custom":
        inp["custom_penalties_compiled"] = {
            "teacher_slots": {teacherName("Математика", 3): [[1, 1, 80], [2, 2, 80]], teacherName("Русский язык", 2): [[3, 0, 120]]},
            "teacher_daily": {teacherName("Математика", 1): [[1, 150]], teacherName("Физика", 2): [[1, 90]]},
            "class_slots": {name("ОГЭ", "Математика"): [[0, 2, 60]]},
            "group_daily": [{"classes": [name("ЕГЭ основной", "Математика"), name("ЕГЭ продвинутый", "Математика")], "limit": 1, "weight": 70}],
            "adjacent": {name("ЕГЭ основной", "Русский язык"): 40},
            "same_day": [{"a": name("ОГЭ", "Математика"), "b": name("10 класс", "Математика"), "weight": 30}],
            "same_day_pairs": [[name("ОГЭ", "Физика"), name("ОГЭ", "Химия")]],
        }

    elif kind == "missing":
        # Химия может только в дни 0–1, информатика — в дни 2–3; у курса не больше урока в день,
        # поэтому у курсов на 3 урока по одному уроку остаётся без места при любом из двух кандидатов
        for number in (1, 2):
            teachers[teacherName("Химия", number)]["free"] = [[day, lesson] for day in range(2, DAYS) for lesson in range(LESSONS)]
            teachers[teacherName("Информатика", number)]["free"] = [[day, lesson] for day in (0, 1, 4) for lesson in range(LESSONS)]

        load[name("ОГЭ", "Химия")]["Химия"] = 3
        load[name("10 класс", "Химия")]["Химия"] = 3
        load[name("ЕГЭ основной", "Информатика")]["Информатика"] = 3

        # Остальным — немного случайных «не может», чтобы ходу 3 иногда было куда вставить урок
        for subject in ("Математика", "Русский язык", "Физика", "Английский язык"):
            for number in range(1, STAFF[subject] + 1):
                teachers[teacherName(subject, number)]["free"] = cannot(rnd, 0.3)

    elif kind == "stream2":
        # Занятость в других этапах уже во входе: «не может» и рабочие дни
        for item in teachers.values():
            item["free"] = cannot(rnd, 0.2)

        inp["teacher_busy_days"] |= {teacherName("Информатика", 2): [1, 3], teacherName("Английский язык", 2): [0]}

    return inp, dict(WEIGHTS)


def compileRecipe():
    """Как compile.bat собирает solve.exe: (путь к g++ или None, папка WinLibs, аргументы g++).

    compile.bat берёт g++ из PATH, а если его там нет — из папки WinLibs (``set "WINLIBS=…"``);
    аргументы — из его строки ``g++ …``.
    """
    with open(COMPILE_BAT, encoding="utf-8") as file:
        text = file.read()

    winlibs = re.search(r'^set "WINLIBS=(.+)"\s*$', text, re.M)
    command = re.search(r"^g\+\+ (.+?)\s*$", text, re.M)
    assert winlibs and command, "compile.bat: нет строки WINLIBS или строки g++"

    folder = re.sub(r"%(\w+)%", lambda found: os.environ.get(found.group(1), ""), winlibs.group(1))
    compiler = shutil.which("g++")

    if compiler is None and os.path.isfile(os.path.join(folder, "g++.exe")):
        compiler = os.path.join(folder, "g++.exe")

    return compiler, folder, command.group(1).split()


def buildCheckSolver(folder):
    """Собирает solve.cpp с -DCHECK_ENERGY в `folder`: (путь к exe или None, вывод компилятора)."""
    compiler, winlibs, args = compileRecipe()
    output = os.path.join(folder, "solve_check.exe")
    args = list(args)
    args[args.index("-o") + 1] = output
    environment = dict(os.environ, PATH=winlibs + os.pathsep + os.environ.get("PATH", ""))
    result = subprocess.run([compiler, *args, "-DCHECK_ENERGY"], cwd=ROOT, env=environment, capture_output=True, timeout=600)
    errors = result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace")
    return (output if result.returncode == 0 and os.path.isfile(output) else None), errors


@unittest.skipIf(compileRecipe()[0] is None, "нет g++ (ни в PATH, ни в папке WinLibs из compile.bat): отладочную сборку -DCHECK_ENERGY не собрать")
class CheckEnergyTests(unittest.TestCase):
    """Отладочная сборка на шести входах AC-7: по 2 млн шагов с --cycle 100000, зерно 1."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.exe, cls.compilerLog = buildCheckSolver(cls.folder.name)
        cls.inputs = {kind: stressInput(kind) for kind in KINDS}
        cls.runs = {}

        if cls.exe is None:
            return

        # Шесть прогонов параллельно; runSolver запускает engine.SOLVER — подменяем его отладочной сборкой
        with mock.patch.object(engine, "SOLVER", cls.exe), ThreadPoolExecutor(len(KINDS)) as pool:
            jobs = {
                kind: pool.submit(engine.runSolver, inp, SEED, ITERATIONS, weights, extra=CYCLE)
                for kind, (inp, weights) in cls.inputs.items()
            }
            cls.runs = {kind: job.result() for kind, job in jobs.items()}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def checkedRun(self, kind):
        """Прогон отладочной сборки на входе `kind`: (вход, ответ, журнал, строка CHECK как (checks, bad, badState))."""
        self.assertIsNotNone(self.exe, f"solve.cpp не собрался с -DCHECK_ENERGY:\n{self.compilerLog[-3000:]}")
        code, answer, log, errors = self.runs[kind]
        self.assertEqual(code, 0, errors)
        self.assertIsNotNone(answer)
        found = CHECK_LINE.findall(log)
        self.assertEqual(len(found), 1, f"{kind}: в журнале отладочной сборки нет строки «CHECK checks=… bad=… badState=…» (или их несколько)")
        return self.inputs[kind][0], answer, log, tuple(map(int, found[0]))

    def test_energy_by_parts_equals_full_recount(self):
        """AC-10: на всех шести входах AC-7 (2 млн шагов, --cycle 100000) отладочная сборка сделала не меньше
        20 проверок, и ни одна не нашла расхождения энергии (bad=0) или состояния (badState=0); ответы при этом
        соблюдают жёсткие правила (ruleViolations пуст)."""
        for kind in KINDS:
            with self.subTest(kind):
                inp, answer, log, (checks, bad, bad_state) = self.checkedRun(kind)
                self.assertGreaterEqual(checks, MIN_CHECKS, log[-2000:])
                self.assertEqual(bad, 0, log[-2000:])
                self.assertEqual(bad_state, 0, log[-2000:])
                self.assertEqual(ruleViolations(inp, answer, log), [])

    def test_limit_rejects_on_limit_input(self):
        """AC-8: на входе «лимит 4» ход 4 упирался в лимит курсов (limitRejects > 0 в строке CHECK),
        а в ответе ни у кого не больше 4 курсов вместе с курсами других этапов."""
        inp, answer, log, (_, _, bad_state) = self.checkedRun("limit4")
        line = CHECK_LINE.search(log).group(0)
        rejects = LIMIT_REJECTS.search(line)
        self.assertIsNotNone(rejects, f"в строке CHECK нет limitRejects=…: {line}")
        self.assertGreater(int(rejects.group(1)), 0, line)
        self.assertEqual(bad_state, 0, line)
        over = {name: count for name, count in coursesPerTeacher(inp, answer).items() if count > inp["max_courses_per_teacher"]}
        self.assertEqual(over, {})

    def test_missing_lessons_keep_course_teacher(self):
        """AC-9: на входе с непоставленными уроками (не меньше 3) отладочная сборка подтверждает, что у
        непоставленных уроков тот же преподаватель, что в клетках курса (badState=0), а в ответе после
        вставок ходом 3 у каждой пары «курс + предмет» по-прежнему один преподаватель."""
        inp, answer, log, (checks, _, bad_state) = self.checkedRun("missing")
        self.assertGreaterEqual(checks, MIN_CHECKS)
        self.assertEqual(bad_state, 0, log[-2000:])

        missing = MISSING_COUNT.search(log)
        self.assertIsNotNone(missing, "на входе «missing» нет строки о непоставленных уроках")
        self.assertGreaterEqual(int(missing.group(1)), 3)

        several = {key: names for key, names in courseTeachers(answer).items() if len(names) != 1}
        self.assertEqual(several, {})
        self.assertEqual(ruleViolations(inp, answer, log), [])


class CheckInputsTests(unittest.TestCase):
    """Сторожа входов и сборки — зелёные и до хода 4: входы действительно дают ходу 4 работу,
    а отладочной проверки нет в обычной сборке (Р-11)."""

    def test_inputs_have_switchable_courses(self):
        """AC-10 (сторож входов): на каждом входе AC-7 есть курсы со сменой (Р-3) — не меньше 8, у входа
        «missing» среди них курсы, у которых урок заведомо не встаёт, у «limit4» — преподаватели,
        которым до лимита остаётся один курс."""
        for kind in KINDS:
            with self.subTest(kind):
                inp, _ = stressInput(kind)
                self.assertGreaterEqual(len(swapCandidates(inp)), 8, kind)

        inp, _ = stressInput("missing")
        self.assertIn((courseName(1, "ОГЭ", "Химия"), "Химия"), swapCandidates(inp))
        self.assertIn((courseName(1, "ЕГЭ основной", "Информатика"), "Информатика"), swapCandidates(inp))

        inp, _ = stressInput("limit4")
        self.assertEqual(
            sorted(name for name, count in inp["existing_courses_by_teacher"].items() if count == inp["max_courses_per_teacher"] - 1),
            sorted(inp["existing_courses_by_teacher"])
        )

    def test_release_build_has_no_check(self):
        """Р-11: compile.bat собирает solve.exe без -DCHECK_ENERGY, и обычный solve.exe не печатает строку CHECK."""
        _, _, args = compileRecipe()
        self.assertFalse([arg for arg in args if "CHECK_ENERGY" in arg])

        if not os.path.exists(SOLVER):
            self.skipTest("solve.exe is not built")

        inp, weights = stressInput("limit4")
        code, answer, log, errors = engine.runSolver(inp, SEED, 100000, weights, extra=CYCLE)
        self.assertEqual(code, 0, errors)
        self.assertIsNone(CHECK_LINE.search(log))
