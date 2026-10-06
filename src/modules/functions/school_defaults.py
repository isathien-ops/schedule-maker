"""Знания по умолчанию об онлайн-школе: с чего начинается новый проект.

* ``createOnlineCourseProgram`` — стандартная программа курсов на учебный год 2026/27:
  четыре потока и семинары без потока (названия курсов строит courses.courseName);
* пары предметов «нельзя одновременно» (``DEFAULT_JOINT_SUBJECT_PAIRS``) и «нежелательно
  одновременно» (``defaultSoftPairs``), правило «Семинары и ЕГЭ продвинутый не пересекаются»
  (``DEFAULT_NON_OVERLAPPING_PROGRAMS``);
* даты учебного календаря по умолчанию (``CALENDAR_START`` / ``CALENDAR_END``).

Сами настройки нового проекта собирает tree.newProjectSettings; новый поток, когда потоков
не осталось, берёт курсы первого потока программы (newStream в src/web/tabs/classes.py).

Зависимости: courses (названия и добавление курсов), pairs (COMMON_SUBJECTS), model.
"""

from src.modules.functions.courses import EXTRA_PROGRAM, addCourse
from src.modules.functions.model import EXTRA_BLOCK
from src.modules.functions.pairs import COMMON_SUBJECTS

# Учебный календарь 2026/27 по умолчанию: даты курсов без своих дат и год сезонных блоков
CALENDAR_START = "2026-09-07"
CALENDAR_END = "2027-06-30"

# Потоки стандартной программы: (номер потока, дата старта)
STREAMS = [(1, CALENDAR_START), (2, "2026-11-23"), (3, "2027-01-11"), (4, "2027-02-22")]

# Предметы школы в порядке показа на страницах («Математика база» добавляется отдельно, см. ниже)
SUBJECTS = [
    "Русский язык", "Математика", "Литература", "Обществознание", "История", "География",
    "Английский язык", "Информатика", "Физика", "Химия", "Биология",
]

# «Математика база» — отдельный предмет линейки «ЕГЭ основной» (не уровень ЕГЭ)
BASE_MATH = "Математика база"

# Дата старта семинаров (они идут без потока, все с одной даты)
SEMINARS_START = "2026-10-05"

# Пары предметов по умолчанию, которые нельзя ставить одновременно в одной линейке
# одного потока: ученики обычно берут оба предмета из пары (например, обществознание
# и историю), и уроки не должны накладываться
DEFAULT_JOINT_SUBJECT_PAIRS = [
    ["Обществознание", "История"],
    ["Литература", "Русский язык"],
    ["Химия", "Биология"],
    ["Математика", "Физика"]
]

# Пары «нежелательно одновременно» по умолчанию, кроме пар с COMMON_SUBJECTS: предметы,
# которые ученики часто сдают вместе. Остальные совпадения («можно») программа не считает неудобством
DEFAULT_SOFT_EXTRA_PAIRS = [
    ["Обществознание", "Английский язык"],
    ["История", "Литература"],
]

# Семинары идут без потока; их ученики одновременно учатся на курсах «ЕГЭ продвинутый»,
# поэтому уроки одного предмета в этих двух программах не должны совпадать по времени
DEFAULT_NON_OVERLAPPING_PROGRAMS = [
    [EXTRA_PROGRAM, "ЕГЭ продвинутый"]
]


def defaultSoftPairs(subjects):
    """Пары «нежелательно» по умолчанию для списка предметов ``subjects``.

    Русский и математику (профильную или базовую) сдают почти все (COMMON_SUBJECTS), поэтому
    они «нежелательно» с каждым предметом; две математики между собой — нет (ученик сдаёт одну
    из них). Плюс DEFAULT_SOFT_EXTRA_PAIRS, если оба предмета пары есть в ``subjects``.
    """
    pairs = []

    for common in COMMON_SUBJECTS:
        if common not in subjects:
            continue

        for other in subjects:
            if other == common or {common, other} == {"Математика", BASE_MATH}:
                continue

            if sorted([common, other]) not in [sorted(pair) for pair in pairs]:
                pairs.append([common, other])

    pairs += [list(pair) for pair in DEFAULT_SOFT_EXTRA_PAIRS if all(subject in subjects for subject in pair)]

    return pairs


def createOnlineCourseProgram():
    """Строит шаблон курсов онлайн-школы на учебный год 2026/27.

    Четыре потока (у каждого своя дата старта), в каждом линейки ОГЭ, ЕГЭ основной,
    ЕГЭ продвинутый, 10 класс и 8 класс; плюс семинары без потока. Каждый курс —
    один предмет одной линейки. Курсы добавляются обычным courses.addCourse, поэтому
    названия, программы и линейки у них такие же, как у курсов, добавленных на странице.

    Возвращает кортеж (subjects, groups, lessons):
    - subjects — список предметов проекта (в порядке показа на страницах);
    - groups — список курсов в формате custom_groups;
    - lessons — недельная нагрузка {курс: {предмет: уроков в неделю}}.
    """
    program = {"classes": {"custom_groups": [], "lessons": {}}}
    # География в ЕГЭ не сдаётся
    exam_subjects = [subject for subject in SUBJECTS if subject != "География"]

    for stream, start in STREAMS:
        for subject in SUBJECTS:
            # Во втором потоке нет литературы ОГЭ
            if not (stream == 2 and subject == "Литература"):
                addCourse(program, stream, "ОГЭ", subject, 1, start)

        for subject in exam_subjects + [BASE_MATH]:
            addCourse(program, stream, "ЕГЭ основной", subject, 2, start)

        for subject in exam_subjects:
            addCourse(program, stream, "ЕГЭ продвинутый", subject, 2, start)

        for subject in SUBJECTS:
            addCourse(program, stream, "10 класс", subject, 1, start)

        for subject in ("Русский язык", "Математика"):
            addCourse(program, stream, "8 класс", subject, 1, start)

    # Семинары — доп. курсы без потока: линейка «Семинар ЕГЭ продвинутый» по всем предметам ЕГЭ
    # и «Семинар ОГЭ» по трём предметам
    for subject in exam_subjects:
        addCourse(program, EXTRA_BLOCK, "Семинар ЕГЭ продвинутый", subject, 1, SEMINARS_START)

    for subject in ("Русский язык", "Математика", "Обществознание"):
        addCourse(program, EXTRA_BLOCK, "Семинар ОГЭ", subject, 1, SEMINARS_START)

    # «Математика база» есть только в «ЕГЭ основном», поэтому в общий список предметов
    # проекта она встаёт сразу за «Математикой»
    subjects = list(SUBJECTS)
    subjects.insert(subjects.index("Математика") + 1, BASE_MATH)

    return subjects, program["classes"]["custom_groups"], program["classes"]["lessons"]
