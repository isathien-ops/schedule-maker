"""Помощники тестов движка solve.exe: запуск решателя на входе и проверка его выхода.

Используются модулями tests/test_engine_*.py:
* ``runSolver`` / ``solved`` — запустить настоящий ``src/modules/solve.exe`` на входе (словарь настроек)
  с заданным зерном и числом шагов и прочитать ответ и вывод;
* ``tiny``, ``course``, ``teacher`` — маленький искусственный вход, где правило легко загнать в угол;
* ``stageInput`` — вход этапа реального проекта (``solver_input.buildStageSettings`` при «сегодня» 04.10.2026);
* ``ruleViolations`` — все нарушения жёстких правил в ответе (пустой список — всё верно);
* ``placedLessons``, ``cellsOf``, ``otherStageLessons`` — уроки ответа в удобном виде;
* тексты сообщений решателя «[Внимание] …» (NO_TIME, NO_TEACHER и др.), на которые опираются проверки;
* ``pinSummary``, ``pinnedPenalty``, ``progressLines``, ``earlyStop``, ``finalLine`` — числа из строк
  журнала решателя («Закреплено N из M», «Шаг N из M», «Остановлено на шаге …», «Готово: …»).

Смена преподавателя в подборе (ход 4, .spec/teacher-swap):

* ``twoCandidates`` — курс на 1 урок с двумя кандидатами «может вести» (Иванова и Петрова):
  до отжига выбирается Иванова, но с Петровой энергия меньше (рычаги: рабочий день, «может»);
  по желанию «ведёт», закрепление времени, курс в ``keep_teacher_courses``;
* ``levelsCase`` — два уровня ЕГЭ одного предмета: «ЕГЭ основной» закреплён там, где Иванова,
  выбранная до отжига для «ЕГЭ продвинутого», «не может»; Петрова может вести его в эти часы;
* ``courseTeachers``, ``coursesPerTeacher``, ``levelMismatches``, ``swapCandidates``, ``bestEnergy`` —
  кто ведёт курсы в ответе, сколько курсов у преподавателя, уровни врозь, какие курсы ход 4 вправе
  трогать, лучшая энергия из журнала;
* ``COMPAT``, ``compatRuns``, ``compatFiles``, ``runRaw`` — эталоны прежнего движка
  (``tests/fixtures/engine_compat``, записаны до хода 4) и запуск, который отдаёт ответ и журнал
  как есть, байтами.

Модуль не начинается с ``test_``, поэтому сам тестов не содержит.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import collections
import json
import os
import re
import subprocess
import tempfile
from unittest import mock

from src.modules.functions.model import courseDates, datesOverlap
from src.modules.functions.solver_input import buildStageSettings
from src.modules.functions.stages import stageCourses
from tests.builders import SOLVER
from tests.real_project import FrozenDate

# Сообщения решателя (stdout), на которые опираются проверки
NO_TIME = "[Внимание] {course} / {subject}: нет свободного времени"
NO_TEACHER = "[Внимание] {course}: нет преподавателя, который может вести «{subject}»"
LIMIT_REACHED = "[Внимание] {course} / {subject}: у всех подходящих преподавателей уже максимум курсов"
PIN_FAILED = "[Внимание] закреплённый урок {course} / {subject} (день {day}, урок {lesson}) не поставлен: "
ASSIGNED_OVER = "[Внимание] {teacher}: курсов с отметкой «ведёт»"
MISSING_TOTAL = "[Внимание] не удалось поставить уроков: "

# Строки журнала о том, сколько программе подбирать (печатаются до отжига). При K = 0 — ровно одна
# из трёх «Подбирать нечего»: всё закреплено / остальным урокам некому вести / уроков нет вовсе
NOTHING_TO_SOLVE = "Подбирать нечего: все уроки закреплены, расписание оставлено как есть"
NOTHING_WITHOUT_TEACHER = "Подбирать нечего: у незакреплённых уроков нет преподавателя"
NOTHING_EMPTY = "Подбирать нечего: в этом потоке или блоке курсов нет уроков"
LITTLE_TO_SOLVE = "Подбирать почти нечего: варианты, скорее всего, совпадут"

# Строки журнала с числами; «урок\w*» — слово «урок» может склоняться по числу
PIN_SUMMARY = re.compile(r"^Закреплено (\d+) из (\d+) урок\w*, подбирается (\d+)(?:, без преподавателя \(не ставятся\): (\d+))?$", re.M)
PINNED_PENALTY = re.compile(r"^Из неудобств (\d+) дают закреплённые уроки\b", re.M)
PROGRESS = re.compile(r"^Шаг (\d+) из (\d+) \|.*\| неудобства: (-?\d+) \(лучшее пока (-?\d+)\)$", re.M)
EARLY_STOP = re.compile(r"^Остановлено на шаге (\d+) из (\d+): подбирается только (\d+) урок\w*, лучшее не менялось 1 млн шагов$", re.M)
FINAL = re.compile(r"^Готово: оценено изменений (\d+) из (\d+) шагов$", re.M)


def pinSummary(log):
    """Строка «Закреплено N из M уроков, подбирается K[, без преподавателя (не ставятся): X]»:
    (N, M, K, X), X = 0 без хвоста; None — строки нет. Строка должна быть ровно одна."""
    found = PIN_SUMMARY.findall(log)
    assert len(found) <= 1, found
    return tuple(int(value or 0) for value in found[0]) if found else None


def pinnedPenalty(log):
    """Число из строки «Из неудобств X дают закреплённые уроки …» или None, если строки нет."""
    found = PINNED_PENALTY.search(log)
    return int(found.group(1)) if found else None


def progressLines(log):
    """Строки хода «Шаг N из M | … | неудобства: E (лучшее пока B)»: [(N, M, E, B)]."""
    return [tuple(map(int, item)) for item in PROGRESS.findall(log)]


def earlyStop(log):
    """Строка «Остановлено на шаге N из M: подбирается только K …»: (N, M, K) или None."""
    found = EARLY_STOP.search(log)
    return tuple(map(int, found.groups())) if found else None


def finalLine(log):
    """Итог «Готово: оценено изменений N из M шагов»: (N, M) или None."""
    found = FINAL.search(log)
    return tuple(map(int, found.groups())) if found else None


def stageInput(settings, answer, stage):
    """Вход решателя для этапа, собранный при замороженной дате."""
    with mock.patch("datetime.date", FrozenDate):
        return buildStageSettings(settings, answer, stage)


def runSolver(settings, seed=1, iterations=200000, weights=None, args=None, extra=()):
    """Запускает solve.exe; возвращает (код выхода, ответ или None, stdout, stderr).

    `args` заменяет всю командную строку, `extra` дописывается к обычной (например, ``--t0``).
    """
    with tempfile.TemporaryDirectory() as folder:
        paths = {name: os.path.join(folder, f"{name}.json") for name in ("input", "weights", "output")}

        with open(paths["input"], "w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False)

        with open(paths["weights"], "w", encoding="utf-8") as file:
            json.dump(weights or {}, file)

        command = args if args is not None else [
            "--weights", paths["weights"], "--input", paths["input"], "--output", paths["output"],
            "--iterations", str(iterations), "--seed", str(seed), *extra
        ]
        result = subprocess.run([SOLVER, *command], capture_output=True, timeout=120)
        answer = None

        if os.path.exists(paths["output"]):
            with open(paths["output"], encoding="utf-8") as file:
                answer = json.load(file)

        # Консоль Windows: строки stdout оканчиваются на \r\n
        log = result.stdout.decode("utf-8", "replace").replace("\r\n", "\n")

        return result.returncode, answer, log, result.stderr.decode("utf-8", "replace")


def solved(test, settings, seed=1, iterations=200000, weights=None, extra=()):
    """Запуск, который должен пройти: код 0 и ответ есть. Возвращает (ответ, stdout)."""
    code, answer, log, errors = runSolver(settings, seed, iterations, weights, extra=extra)
    test.assertEqual(code, 0, errors)
    test.assertIsNotNone(answer)
    return answer, log


def utf8Order(names):
    """Порядок имён, как у объекта nlohmann::json (std::map — побайтно по UTF-8)."""
    return sorted(names, key=lambda name: name.encode("utf-8"))


def placedLessons(answer):
    """Непустые ячейки ответа: [(курс, день, урок, предмет, [преподаватели])]."""
    return [
        (course, day, lesson, cell["subject"], cell["teachers"])
        for course, week in answer.items()
        for day, cells in enumerate(week)
        for lesson, cell in enumerate(cells)
        if cell.get("subject", "#") != "#"
    ]


def otherStageLessons(settings, answer, stage, inp):
    """Неподвижные уроки, с которыми этап не должен сталкиваться: уроки других этапов,
    пересекающиеся с ним по датам, и уроки курсов этапа, которые не попали во вход решателя
    (начавшийся курс без преподавателя).

    [(курс, группа, предмет, преподаватели, день, урок)] — посчитано здесь заново,
    независимо от того, как buildStageSettings кодирует их во входе решателя.
    """
    groups = {group["name"]: group for group in settings["classes"]["custom_groups"]}
    own = set(stageCourses(settings, stage))
    solved_here = {group["name"] for group in inp["classes"]["custom_groups"]}
    dates = [courseDates(settings, groups[name]) for name in own]
    span = (min(start for start, _ in dates), max(end for _, end in dates))

    return [
        (course, groups[course], subject, teachers, day, lesson)
        for course, day, lesson, subject, teachers in placedLessons(answer)
        if course not in solved_here and course in groups and datesOverlap(courseDates(settings, groups[course]), span)
    ]


def ruleViolations(inp, out, log, outside=()):
    """Все нарушения жёстких правил в ответе `out` решателя на вход `inp` (пустой список — всё верно).

    `log` — stdout решателя (сообщения «[Внимание]»), `outside` — уроки других этапов
    (см. `otherStageLessons`).
    """
    problems = []
    days = inp["working_days_per_week"]
    width = min(6, inp["max_lesson_count_per_day"])
    subjects = {item[0] for item in inp["subjects"]}
    groups = {group["name"]: group for group in inp["classes"]["custom_groups"]}
    load = inp["classes"]["lessons"]
    teachers = inp.get("teachers", {})
    constants = inp.get("constants", {})
    grid = inp.get("day_grid")

    # --- Формат: все курсы входа, неделя дни × уроки, ячейка {"subject", "teachers"} ---
    if set(out) != set(groups):
        problems.append(f"курсы ответа не совпадают со входом: лишние {set(out) - set(groups)}, нет {set(groups) - set(out)}")

    cells = []

    for course, week in out.items():
        if not isinstance(week, list) or len(week) != days or any(not isinstance(row, list) or len(row) != width for row in week):
            problems.append(f"{course}: неделя не {days}×{width}")
            continue

        for day, row in enumerate(week):
            for lesson, cell in enumerate(row):
                if not isinstance(cell, dict) or set(cell) != {"subject", "teachers"}:
                    problems.append(f"{course} {day}-{lesson}: ячейка не того вида: {cell}")
                elif cell["subject"] == "#":
                    if cell["teachers"] != []:
                        problems.append(f"{course} {day}-{lesson}: в пустой ячейке есть преподаватель")
                elif cell["subject"] not in subjects or not isinstance(cell["teachers"], list) or len(cell["teachers"]) != 1:
                    problems.append(f"{course} {day}-{lesson}: неизвестный предмет или не один преподаватель: {cell}")
                else:
                    cells.append((course, day, lesson, cell["subject"], cell["teachers"][0]))

    # Закреплённые слоты курса (для исключения «два урока в день» у явно закреплённых)
    pinned = collections.defaultdict(dict)

    for course, items in constants.items():
        for key, subject in (items.items() if isinstance(items, dict) else []):
            try:
                day, lesson = map(int, key.split("-"))
            except ValueError:
                continue

            if 0 <= day < days and 0 <= lesson < width and isinstance(subject, str) and subject in subjects:
                pinned[course][(day, lesson)] = subject

    # Кто может вести и кто «ведёт» (ведёт учитывается, только если курс есть и в «может вести»)
    eligible = collections.defaultdict(set)
    assigned = collections.defaultdict(list)

    for name in utf8Order(teachers):
        for item in teachers[name].get("subjects", []):
            for course in item.get("classes", []):
                eligible[(course, item["subject"])].add(name)

            for course in item.get("assigned", []):
                if course in item.get("classes", []):
                    assigned[(course, item["subject"])].append(name)

    slot_teacher = collections.Counter()
    per_day = collections.Counter()
    course_teachers = collections.defaultdict(set)
    placed = collections.Counter()
    by_slot = collections.defaultdict(list)

    for course, day, lesson, subject, teacher in cells:
        slot_teacher[(teacher, day, lesson)] += 1
        per_day[(course, day)] += 1
        course_teachers[(course, subject)].add(teacher)
        placed[(course, subject)] += 1
        by_slot[(day, lesson)].append((course, subject))

        free = {tuple(slot) for slot in teachers.get(teacher, {}).get("free", [])}

        if (day, lesson) in free:
            problems.append(f"{teacher}: урок {course} в слоте «не может» {day}-{lesson}")

        if teacher not in eligible[(course, subject)]:
            problems.append(f"{teacher} не может вести {course} / {subject}")

        if assigned[(course, subject)] and teacher != assigned[(course, subject)][0]:
            problems.append(f"{course} / {subject}: ведёт {teacher}, а закреплён {assigned[(course, subject)][0]}")

        if [day, lesson] in inp.get("blocked_slots", {}).get(course, []):
            problems.append(f"{course}: урок в закрытом слоте {day}-{lesson}")

        if grid is not None and not (day < len(grid) and lesson < len(grid[day])):
            problems.append(f"{course}: урок вне сетки дня {day}-{lesson}")

        if int(load.get(course, {}).get(subject, 0) or 0) <= 0:
            problems.append(f"{course}: урок предмета {subject} без нагрузки")

        # Неподвижные уроки вне входа: время преподавателя, непересекающиеся программы, пары «нельзя»
        for other, group, other_subject, other_teachers, other_day, other_lesson in outside:
            if (other_day, other_lesson) != (day, lesson):
                continue

            if teacher in other_teachers:
                problems.append(f"{teacher}: {course} и {other} (вне входа) в одном слоте {day}-{lesson}")

            pair = [groups[course].get("program", course), group.get("program", other)]

            if subject == other_subject and (pair in inp.get("non_overlapping_programs", []) or pair[::-1] in inp.get("non_overlapping_programs", [])):
                problems.append(f"{course} совпадает с {other} (вне входа, программы не пересекаются) в {day}-{lesson}")

            same_line = groups[course].get("stream_id") is not None and groups[course].get("stream_id") == group.get("stream_id") and groups[course].get("line") == group.get("line")

            if same_line and sorted([subject, other_subject]) in [sorted(item) for item in inp.get("joint_subject_pairs", [])]:
                problems.append(f"пара «нельзя» {course} / {other} (вне входа) в {day}-{lesson}")

    problems += [f"{teacher}: два урока в слоте {day}-{lesson}" for (teacher, day, lesson), count in slot_teacher.items() if count > 1]
    problems += [
        f"{course}: {count} урока в день {day}" for (course, day), count in per_day.items()
        if count > 1 and sum(1 for pin_day, _ in pinned[course] if pin_day == day) < count
    ]
    problems += [f"{course} / {subject}: несколько преподавателей {sorted(names)}" for (course, subject), names in course_teachers.items() if len(names) > 1]

    # --- Пары «нельзя» в одной линейке и потоке; непересекающиеся программы с общим предметом ---
    pairs = {tuple(sorted(pair)) for pair in inp.get("joint_subject_pairs", [])}
    programs = {tuple(pair) for pair in inp.get("non_overlapping_programs", [])}

    def line(course):
        """Линейка курса так, как её понимает решатель."""
        group = groups[course]
        return group.get("line", group.get("program", course))

    def stream(course):
        """Номер потока или None."""
        value = groups[course].get("stream_id")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def shareSubject(first, second):
        """Есть ли у курсов общий предмет с нагрузкой."""
        return any(int(hours or 0) > 0 and int(load.get(second, {}).get(subject, 0) or 0) > 0 for subject, hours in load.get(first, {}).items())

    for (day, lesson), items in by_slot.items():
        for index, (first, subject_a) in enumerate(items):
            for second, subject_b in items[index + 1:]:
                if stream(first) is not None and stream(first) == stream(second) and line(first) == line(second) and tuple(sorted([subject_a, subject_b])) in pairs:
                    problems.append(f"пара «нельзя» {first} / {second} в {day}-{lesson}")

                programs_ab = (groups[first].get("program", first), groups[second].get("program", second))

                if (programs_ab in programs or programs_ab[::-1] in programs) and shareSubject(first, second):
                    problems.append(f"непересекающиеся программы {first} / {second} в {day}-{lesson}")

    # --- Закреплённые уроки: на месте или понятное сообщение ---
    for course, items in pinned.items():
        if course not in out:
            continue

        for (day, lesson), subject in items.items():
            week = out[course]
            cell = week[day][lesson] if day < len(week) and lesson < len(week[day]) and isinstance(week[day][lesson], dict) else {}

            if cell.get("subject") != subject and PIN_FAILED.format(course=course, subject=subject, day=day + 1, lesson=lesson + 1) not in log:
                problems.append(f"закреплённый урок {course} {day}-{lesson} ({subject}) не на месте и без сообщения")

    # --- Число уроков = нагрузка, иначе сообщение «[Внимание]» ---
    missing_lines = 0

    for course, subjects_load in load.items():
        if course not in groups:
            continue

        for subject, hours in subjects_load.items():
            hours = int(hours or 0)
            count = placed[(course, subject)]
            no_time = log.count(NO_TIME.format(course=course, subject=subject))
            missing_lines += no_time

            if hours <= 0 or count == hours and not no_time:
                continue

            explained = (
                count == 0 and (NO_TEACHER.format(course=course, subject=subject) in log or LIMIT_REACHED.format(course=course, subject=subject) in log)
                or count < hours and no_time == hours - count
            )

            if not explained:
                problems.append(f"{course} / {subject}: уроков {count} из {hours}, сообщений «нет свободного времени»: {no_time}")

    if missing_lines and f"{MISSING_TOTAL}{missing_lines}\n" not in log:
        problems.append(f"нет итога «не удалось поставить уроков: {missing_lines}»")

    if not missing_lines and MISSING_TOTAL in log:
        problems.append("итог о непоставленных уроках без самих уроков")

    # --- Лимит курсов на преподавателя (отметки «ведёт» лимит не останавливают, но о них сообщается) ---
    limit = max(1, inp.get("max_courses_per_teacher", 5))
    existing = inp.get("existing_courses_by_teacher", {})
    fixed = collections.Counter(
        names[0] for (course, subject), names in assigned.items()
        if names and course in groups and int(load.get(course, {}).get(subject, 0) or 0) > 0
    )
    free_courses = collections.defaultdict(set)

    for course, _, _, subject, teacher in cells:
        if assigned[(course, subject)][:1] != [teacher]:
            free_courses[teacher].add((course, subject))

    for teacher in set(fixed) | set(free_courses):
        before = existing.get(teacher, 0) + fixed[teacher]

        if len(free_courses[teacher]) > max(0, limit - before):
            problems.append(f"{teacher}: курсов {before + len(free_courses[teacher])} при лимите {limit}")

        if before > limit and ASSIGNED_OVER.format(teacher=teacher) not in log:
            problems.append(f"{teacher}: «ведёт» больше лимита, а сообщения нет")

    return problems


def course(name, subject, hours=1, program="ЕГЭ основной", line="ЕГЭ", stream=1):
    """Курс маленького входа: (группа, нагрузка)."""
    return {"name": name, "program": program, "line": line, "stream_id": stream, "subjects": [subject]}, {subject: hours}


def teacher(subject, classes, assigned=(), free=(), possible=()):
    """Преподаватель маленького входа с одним предметом."""
    return {
        "subjects": [{"subject": subject, "classes": list(classes), "assigned": list(assigned)}],
        "free": [list(slot) for slot in free],
        "possible": [list(slot) for slot in possible]
    }


def tiny(days, lessons, courses, teachers, **extra):
    """Маленький вход решателя: сетка days × lessons, курсы `course(...)`, преподаватели `teacher(...)`."""
    names = sorted({subject for _, load in courses for subject in load} | {"Математика", "Физика", "Химия", "Биология"})
    settings = {
        "working_days_per_week": days,
        "max_lesson_count_per_day": lessons,
        "max_courses_per_teacher": 5,
        "subjects": [[name, 1] for name in names],
        "classes": {
            "custom_groups": [group for group, _ in courses],
            "lessons": {group["name"]: load for group, load in courses}
        },
        "teachers": teachers,
        "constants": {},
        "joint_subject_pairs": [],
        "non_overlapping_programs": [],
        "soft_subject_pairs": []
    }
    settings.update(extra)
    return settings


def cellsOf(answer, name):
    """[(день, урок, предмет, преподаватель)] курса `name`."""
    return [(day, lesson, subject, teachers[0]) for course, day, lesson, subject, teachers in placedLessons(answer) if course == name]


# ---------------------------------------------------------------- Смена преподавателя в подборе (ход 4)

# Кандидаты маленьких входов twoCandidates и levelsCase: до отжига выбирается TEACHER_A
# (у неё больше свободных часов), а с TEACHER_B энергия меньше; TEACHER_C «ведёт» «ЕГЭ основной»
TEACHER_A = "Иванова"
TEACHER_B = "Петрова"
TEACHER_C = "Смирнова"

# Курс twoCandidates и пара уровней levelsCase
SWAP_COURSE = "Поток 1 — ЕГЭ основной — Математика"
SWAP_SUBJECT = "Математика"
LEVEL_BASIC = "Поток 1 — ЕГЭ основной — Математика"
LEVEL_ADVANCED = "Поток 1 — ЕГЭ продвинутый — Математика"

# twoCandidates: у Петровой «не может» в этих ячейках (не в рабочий день busyDay), чтобы свободных
# часов у неё было меньше, чем у Ивановой, и до отжига выбиралась Иванова
B_CANNOT = ((0, 0), (2, 0))

# levelsCase: часы, в которые закреплён «ЕГЭ основной» и в которые Иванова «не может»
LEVEL_SLOTS = ((0, 0), (1, 0))


def twoCandidates(lever="workday", assigned=None, pin=None, pinBlocked=False, keep=False, busyDay=1, days=3, lessons=2, **extra):
    """Курс ``SWAP_COURSE`` (1 урок в неделю) с двумя кандидатами «может вести»: (вход, веса).

    До отжига выбирается ``TEACHER_A`` (Иванова): у ``TEACHER_B`` (Петровой) «не может» в ячейках
    ``B_CANNOT``, свободных часов меньше. Рычаг ``lever`` делает Петрову выгоднее:

    * ``"workday"`` — Петрова уже работает в день ``busyDay`` (``teacher_busy_days``, с 0), Иванова —
      нигде; вес ``teacherWorkDays`` = 100: с Ивановой урок стоит 100, с Петровой в день ``busyDay`` — 0;
    * ``"possible"`` — у Ивановой все ячейки «может» (``possible``), вес ``teacherPossibleSlot`` = 300.

    ``assigned`` — имя, которому стоит «ведёт» курса (AC-3); ``pin`` — закрепление времени (день, урок)
    во входе (``constants``, AC-5); ``pinBlocked`` — у Ивановой «не может» в ячейке ``pin``, закрепление
    не встаёт; ``keep`` — курс в ``keep_teacher_courses`` (AC-6). Сетка ``days`` × ``lessons``;
    ``extra`` дописывается во вход (например, ``max_courses_per_teacher``).
    """
    a_cannot = [pin] if pin is not None and pinBlocked else []
    teachers = {
        TEACHER_A: teacher(SWAP_SUBJECT, [SWAP_COURSE], [SWAP_COURSE] if assigned == TEACHER_A else (), free=a_cannot),
        TEACHER_B: teacher(SWAP_SUBJECT, [SWAP_COURSE], [SWAP_COURSE] if assigned == TEACHER_B else (), free=B_CANNOT),
    }
    settings = tiny(days, lessons, [course(SWAP_COURSE, SWAP_SUBJECT)], teachers)

    if lever == "workday":
        settings["teacher_busy_days"] = {TEACHER_B: [busyDay]}
        weights = {"teacherWorkDays": 100}
    elif lever == "possible":
        teachers[TEACHER_A]["possible"] = [[day, lesson] for day in range(days) for lesson in range(lessons)]
        weights = {"teacherPossibleSlot": 300}
    else:
        raise ValueError(lever)

    if pin is not None:
        settings["constants"] = {SWAP_COURSE: {f"{pin[0]}-{pin[1]}": SWAP_SUBJECT}}

    if keep:
        settings["keep_teacher_courses"] = [SWAP_COURSE]

    settings.update(extra)

    return settings, weights


def levelsCase(days=5, lessons=2, **extra):
    """Два уровня ЕГЭ по математике в Потоке 1 (линейка «ЕГЭ»): (вход, веса). Для AC-2.

    * ``LEVEL_BASIC`` (2 урока): «ведёт» ``TEACHER_C`` и закрепление в ячейках ``LEVEL_SLOTS``;
    * ``LEVEL_ADVANCED`` (2 урока): «может вести» ``TEACHER_A`` и ``TEACHER_B``, «ведёт» нет.
      У Ивановой «не может» в ``LEVEL_SLOTS`` — она занята как раз тогда, когда идёт «ЕГЭ основной»;
      у Петровой «не может» во все дни, начиная с четвёртого (день 3 с 0), так что свободных часов у неё
      меньше и до отжига выбирается Иванова.

    Вес ``levelsApart`` = 1000. С Ивановой уроки уровней не могут совпасть (``levelMismatches`` = 2),
    с Петровой — могут (0). ``extra`` дописывается во вход.
    """
    teachers = {
        TEACHER_A: teacher(SWAP_SUBJECT, [LEVEL_ADVANCED], free=LEVEL_SLOTS),
        TEACHER_B: teacher(SWAP_SUBJECT, [LEVEL_ADVANCED], free=[(day, lesson) for day in range(3, days) for lesson in range(lessons)]),
        TEACHER_C: teacher(SWAP_SUBJECT, [LEVEL_BASIC], [LEVEL_BASIC]),
    }
    courses = [
        course(LEVEL_BASIC, SWAP_SUBJECT, 2, program="ЕГЭ основной"),
        course(LEVEL_ADVANCED, SWAP_SUBJECT, 2, program="ЕГЭ продвинутый"),
    ]
    settings = tiny(days, lessons, courses, teachers)
    settings["constants"] = {LEVEL_BASIC: {f"{day}-{lesson}": SWAP_SUBJECT for day, lesson in LEVEL_SLOTS}}
    settings.update(extra)

    return settings, {"levelsApart": 1000}


def bestEnergy(log):
    """Лучшая энергия из последней строки «Шаг N из M | … (лучшее пока B)» или None. Строка печатается
    раз в 1 млн шагов, поэтому прогону нужен хотя бы 1 млн шагов (маленький вход — доли секунды)."""
    lines = progressLines(log)
    return lines[-1][3] if lines else None


def courseTeachers(answer):
    """Кто ведёт уроки ответа: {(курс, предмет): {имена}} (у каждой пары должно быть одно имя)."""
    result = collections.defaultdict(set)

    for course_name, _, _, subject, names in placedLessons(answer):
        result[(course_name, subject)].update(names)

    return dict(result)


def coursesPerTeacher(inp, answer):
    """Сколько курсов у преподавателя по ответу: {имя: existing_courses_by_teacher + число его пар
    «курс + предмет» с уроками в ответе}. Курс без поставленных уроков не считается."""
    result = collections.Counter({name: int(count) for name, count in inp.get("existing_courses_by_teacher", {}).items()})

    for names in courseTeachers(answer).values():
        for name in names:
            result[name] += 1

    return dict(result)


def levelMismatches(inp, answer):
    """Уровни врозь, как ``levelsApart`` в решателе и на «Предпросмотре» (без веса): по всем парам
    уровней одного предмета (тот же поток и линейка, другая программа, тот же главный предмет)
    сумма min(уроков) − общих ячеек."""
    groups = {group["name"]: group for group in inp["classes"]["custom_groups"]}
    load = inp["classes"]["lessons"]
    slots = collections.defaultdict(set)

    for course_name, day, lesson, _, _ in placedLessons(answer):
        slots[course_name].add((day, lesson))

    def mainSubject(name):
        """Первый по порядку UTF-8 предмет курса с уроками (как mainSubject в solve.cpp)."""
        return next((subject for subject in utf8Order(load.get(name, {})) if int(load[name][subject] or 0) > 0), "")

    def stream(group):
        """Номер потока или None (курс без потока пар уровней не имеет)."""
        value = group.get("stream_id")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    total = 0
    names = list(groups)

    for index, first in enumerate(names):
        for second in names[index + 1:]:
            a, b = groups[first], groups[second]
            program_a, program_b = a.get("program", first), b.get("program", second)

            if (
                stream(a) is not None and stream(a) == stream(b) and a.get("line", program_a) == b.get("line", program_b)
                and program_a != program_b and mainSubject(first) and mainSubject(first) == mainSubject(second)
            ):
                total += max(0, min(len(slots[first]), len(slots[second])) - len(slots[first] & slots[second]))

    return total


def swapCandidates(inp):
    """Курсы, которым ход 4 вправе сменить преподавателя (решение Р-3), по одному входу, без запуска:
    {(курс, предмет): [кандидаты не на лимите]}.

    Пара попадает, если у неё нет «ведёт», нет закрепления времени этого предмета во входе
    (``constants``), курса нет в ``keep_teacher_courses`` и хотя бы двум кандидатам «может вести»
    лимит не мешает: existing_courses_by_teacher + число их «ведёт» < max_courses_per_teacher.
    (Курс, которому до отжига не досталось преподавателя из-за лимита, здесь тоже есть — его отсеет
    сам движок.) Пустой словарь — входы эталонов AC-13.
    """
    groups = {group["name"] for group in inp["classes"]["custom_groups"]}
    load = inp["classes"]["lessons"]
    teachers = inp.get("teachers", {})
    keep = set(inp.get("keep_teacher_courses", []))
    limit = max(1, inp.get("max_courses_per_teacher", 5))
    existing = inp.get("existing_courses_by_teacher", {})
    candidates = collections.defaultdict(list)
    fixed = {}

    for name in utf8Order(teachers):
        for item in teachers[name].get("subjects", []):
            for course_name in item.get("classes", []):
                candidates[(course_name, item["subject"])].append(name)

            for course_name in item.get("assigned", []):
                if course_name in item.get("classes", []):
                    fixed.setdefault((course_name, item["subject"]), name)

    fixed = {key: name for key, name in fixed.items() if key[0] in groups and int(load.get(key[0], {}).get(key[1], 0) or 0) > 0}
    taken = collections.Counter(fixed.values())
    result = {}

    for course_name in groups:
        pins = inp.get("constants", {}).get(course_name)
        pins = list(pins.values()) if isinstance(pins, dict) else []

        for subject, hours in load.get(course_name, {}).items():
            key = (course_name, subject)

            if int(hours or 0) <= 0 or key in fixed or subject in pins or course_name in keep:
                continue

            free = [name for name in candidates[key] if existing.get(name, 0) + taken[name] < limit]

            if len(free) >= 2:
                result[key] = free

    return result


# Эталоны прежнего движка (до хода 4): входы, веса и для каждого зерна ответ и журнал solve.exe байтами.
# Какие прогоны записаны (шагов, флаги, зёрна) — в runs.json той же папки
COMPAT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "engine_compat")


def compatRuns():
    """Прогоны эталонов: {имя входа: {"iterations": N, "extra": [флаги], "seeds": [зёрна], "about": "…"}}."""
    with open(os.path.join(COMPAT, "runs.json"), encoding="utf-8") as file:
        return json.load(file)


def compatFiles(name, seed=None):
    """Пути файлов эталона ``name``: {"input", "weights"} и при ``seed`` ещё {"answer", "log"}."""
    paths = {"input": os.path.join(COMPAT, f"{name}.input.json"), "weights": os.path.join(COMPAT, f"{name}.weights.json")}

    if seed is not None:
        paths["answer"] = os.path.join(COMPAT, f"{name}.seed{seed}.answer.json")
        paths["log"] = os.path.join(COMPAT, f"{name}.seed{seed}.log")

    return paths


def runRaw(input_path, weights_path, seed, iterations, extra=()):
    """Запускает solve.exe на готовых файлах входа и весов: (код выхода, ответ байтами или None,
    stdout байтами как есть — с \\r\\n, stderr текстом). Для побайтного сравнения с эталоном."""
    with tempfile.TemporaryDirectory() as folder:
        output = os.path.join(folder, "output.json")
        command = [SOLVER, "--weights", weights_path, "--input", input_path, "--output", output,
                   "--iterations", str(iterations), "--seed", str(seed), *extra]
        result = subprocess.run(command, capture_output=True, timeout=120)
        answer = None

        if os.path.exists(output):
            with open(output, "rb") as file:
                answer = file.read()

        return result.returncode, answer, result.stdout, result.stderr.decode("utf-8", "replace")
