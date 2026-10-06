"""Общие заготовки тестов: настройки, недели расписания, папки проектов, временная папка.

Пути и тексты:

* ``SOLVER`` — путь к движку ``src/modules/solve.exe`` (тесты с ним пропускаются, если он не собран);
* ``PROJECTS`` — папка проектов (внутри временной папки данных тестов, см. tests/__init__.py);
* ``GENERIC`` — общий текст ошибки «Что-то пошло не так…» (``web.error.generic``).

Настройки и преподаватели (маленькие примеры, которые собирают сами тесты):

* ``makeSettings`` — стандартная программа онлайн-школы с 5 преподавателями на каждый предмет;
* ``WEEKDAY_GRID`` — сетка «будни по три урока, выходные пустые» (7 дней);
* ``emptySettings`` — настройки без курсов и преподавателей, без сетки;
* ``weekdaySettings`` — то же с сеткой ``WEEKDAY_GRID`` (7 дней, выходные пустые);
* ``baseSettings`` — то же с сеткой только из 5 будних дней (через ``setDayGrid``);
* ``setDates`` — задать курсу даты начала и окончания;
* ``teacher`` — преподаватель с предметами и пустыми списками курсов;
* ``teacherWithCourses`` — преподаватель со своими списками «может вести» и «ведёт» по каждому предмету;
* ``chemist`` — преподаватель химии со списками «может вести», «ведёт» и «вести нельзя».

Недели расписания:

* ``emptyWeek`` / ``place`` — неделя расписания курса и урок в ней;
* ``lesson`` — ячейка с уроком и преподавателями (для записи прямо в неделю);
* ``chemistryWeek`` — неделя курса с уроками «Химия» у «Химия #1» в заданных ячейках;
* ``courseWeek`` — неделя 5 × 3 с уроками предмета у одного преподавателя в заданных ячейках;
* ``oneLessonWeek`` — неделя 7 × 3 с единственным уроком в понедельник первым уроком у «Иванова Анна».

«Линейка присоединяется к потоку» (общие уроки двух потоков):

* ``jointProject`` — потоки 1–3 с линейками «ЕГЭ основной» и «ЕГЭ продвинутый» (разные наборы
  предметов), преподаватели и принятый Поток 1 (``JOINT_*`` — его курсы, нагрузка, уроки);
* ``jointCourse`` — название курса такого проекта по потоку, предмету и линейке;
* ``markJoint`` — отметка «присоединяется к» прямо в данных (поле ``together_with`` курсов-копий
  и, по желанию, согласованные часы, закрепления и уроки копий) — без кода программы;
* ``markCannot`` — отметка «не может» у преподавателя на этапе прямо в данных;
* ``shiftStream`` — перенести дату начала всех курсов потока (например, чтобы Поток 1 ещё не начался);
* ``setHours`` — нагрузка курса по предмету прямо в данных (например, чтобы идущему курсу не хватало урока);
* ``stageVariant`` — вариант этапа: курсы этапа как в принятом расписании, кроме заданных.

Файлы:

* ``readJson`` / ``writeText`` — прочитать JSON-файл и записать файл как есть;
* ``FORMAT_PROJECT`` / ``FOLDER`` и ``writeProject`` / ``readProject`` — проект для проверок формата
  (тесты ``tree.py`` и стартового экрана) и JSON-файлы внутри его папки;
* ``unnumbered`` — настройки так, как их сохраняла программа до появления номера формата;
* ``TempFolderCase`` — база тестов, которым нужна своя временная папка.

Модуль не начинается с ``test_``, поэтому сам тестов не содержит.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import json
import os
import shutil
import tempfile
import unittest

from src.variables import PATH_TO_FOLDER
from src.modules.translate import translate
from src.modules.functions.courses import addCourse, courseName, lineCourses, setTeacherCourseState, setTeacherSubjects
from src.modules.functions.grid import DEFAULT_DAY, setDayGrid
from src.modules.functions.model import courseSubject, groupsByName, hasLessons, teacherAvailability
from src.modules.functions.school_defaults import (
    DEFAULT_JOINT_SUBJECT_PAIRS, DEFAULT_NON_OVERLAPPING_PROGRAMS, createOnlineCourseProgram
)
from src.modules.functions.stages import getStages, stageCourses
from src.modules.functions.tree import newProjectSettings

SOLVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "modules", "solve.exe")
PROJECTS = f"{PATH_TO_FOLDER}/projects"
GENERIC = translate("web.error.generic")

# Будни по три урока, выходные пустые
WEEKDAY_GRID = [["16:20 - 17:50", "18:00 - 19:30", "19:40 - 21:10"]] * 5 + [[], []]

# Проект для проверок формата (номер формата, старые настройки, архив и версия другого формата)
FORMAT_PROJECT = "__test_format__"
FOLDER = f"{PROJECTS}/{FORMAT_PROJECT}"


def makeSettings():
    """Настройки стандартной программы онлайн-школы с 5 учителями на каждый предмет.

    Учителя называются «<предмет> #1» … «#5» и могут вести все курсы своего предмета;
    у каждого — пустые отметки времени на каждом этапе. Сетка — будни по три урока.
    """
    subjects, groups, lessons = createOnlineCourseProgram()

    settings = {
        "max_courses_per_teacher": 5,
        "joint_subject_pairs": DEFAULT_JOINT_SUBJECT_PAIRS,
        "non_overlapping_programs": DEFAULT_NON_OVERLAPPING_PROGRAMS,
        "subjects": [[subject, 1] for subject in subjects],
        "classes": {"custom_groups": groups, "lessons": lessons},
        "teachers": {},
        "constants": {}
    }

    setDayGrid(settings, [list(DEFAULT_DAY)] * 5 + [[], []])

    for subject in subjects:
        for number in range(5):
            setTeacherSubjects(settings, f"{subject} #{number + 1}", [subject])

    for teacher in settings["teachers"].values():
        for stage in getStages(settings):
            teacherAvailability(teacher, stage["key"])

    return settings


def emptySettings(**extra):
    """Настройки без курсов и преподавателей, без сетки (плюс поля ``extra``)."""
    settings = {"classes": {"custom_groups": [], "lessons": {}}, "teachers": {}, "constants": {}}
    settings.update(extra)

    return settings


def weekdaySettings(**extra):
    """Настройки без курсов и преподавателей, с сеткой WEEKDAY_GRID — 7 дней, выходные пустые
    (плюс поля ``extra``).
    """
    settings = emptySettings(day_grid=[list(day) for day in WEEKDAY_GRID])
    settings.update(extra)

    return settings


def baseSettings(**extra):
    """Настройки без курсов и преподавателей, сетка — только 5 будних дней по три урока (плюс поля ``extra``).

    В отличие от ``weekdaySettings`` сетка записывается через ``setDayGrid``, как её сохраняет программа.
    """
    settings = emptySettings(**extra)
    setDayGrid(settings, [list(DEFAULT_DAY)] * 5)

    return settings


def setDates(settings, course, start, end):
    """Задаёт курсу ``course`` даты начала и окончания."""
    for group in settings["classes"]["custom_groups"]:
        if group["name"] == course:
            group["start_date"], group["end_date"] = start, end


def shiftStream(settings, stream, start):
    """Переносит дату начала всех курсов потока ``stream`` на ``start`` (меняет ``settings``)."""
    for group in settings["classes"]["custom_groups"]:
        if group.get("stream_id") == stream:
            group["start_date"] = start


def teacher(*subjects):
    """Преподаватель с предметами ``subjects`` и пустыми списками курсов."""
    return {"subjects": [{"subject": subject, "classes": [], "assigned": []} for subject in subjects]}


def teacherWithCourses(*items, availability=None):
    """Преподаватель с предметами `items` = (предмет, [курсы может вести], [курсы ведёт])."""
    return {"subjects": [{"subject": subject, "classes": list(classes), "assigned": list(assigned)} for subject, classes, assigned in items],
            "availability": availability or {}}


def chemist(*courses, assigned=(), forbidden=None):
    """Преподаватель химии, который «может вести» ``courses`` и «ведёт» ``assigned``;
    ``forbidden`` — курсы «вести нельзя» (без него поля ``forbidden`` нет совсем).
    """
    data = {"subjects": [{"subject": "Химия", "classes": list(courses), "assigned": list(assigned)}], "availability": {}}

    if forbidden is not None:
        data["forbidden"] = list(forbidden)

    return data


def emptyWeek(days=7, lessons=3):
    """Пустая неделя: `days` дней по `lessons` уроков, во всех ячейках «#»."""
    return [[{"subject": "#", "teachers": []} for _ in range(lessons)] for _ in range(days)]


def oneLessonWeek(subject):
    """Неделя (7 дней по 3 урока) с единственным уроком `subject` в понедельник первым уроком у «Иванова Анна»."""
    result = emptyWeek()
    result[0][0] = {"subject": subject, "teachers": ["Иванова Анна"]}

    return result


def place(week, day, lesson, subject, teacher):
    """Ставит в `week` урок `subject` с учителем `teacher` в (`day`, `lesson`) и возвращает ту же неделю."""
    week[day][lesson] = {"subject": subject, "teachers": [teacher]}

    return week


def lesson(subject, *teachers):
    """Ячейка с уроком ``subject`` и преподавателями ``teachers`` (без преподавателей — пустой список)."""
    return {"subject": subject, "teachers": list(teachers)}


def chemistryWeek(*lessons, days=7, size=3):
    """Неделя курса (`days` дней по `size` уроков) с уроками «Химия» у «Химия #1» в ячейках
    `lessons` — пары (день, урок).
    """
    result = emptyWeek(days, size)

    for day, number in lessons:
        place(result, day, number, "Химия", "Химия #1")

    return result


def courseWeek(subject, teacher, *slots, days=5, size=3):
    """Неделя курса (`days` дней по `size` уроков, как у сетки «будни по три урока») с уроками
    `subject` у преподавателя `teacher` в ячейках `slots` — пары (день, урок).
    """
    result = emptyWeek(days, size)

    for day, number in slots:
        place(result, day, number, subject, teacher)

    return result


# ---------------------------------------------------------------- «Линейка присоединяется к Потоку N»

# Линейки проекта jointProject: общая (её отмечают «вместе с Потоком 1»), вторая линейка ЕГЭ
# (её уровни — пара для «уровней врозь») и линейка, которой нет в Потоке 1
JOINT_LINE = "ЕГЭ основной"
LEVEL_LINE = "ЕГЭ продвинутый"
OWN_LINE = "ОГЭ"

# Даты начала потоков (как в стандартной программе); дат окончания нет — все идут до конца
# календаря (2027-06-30), поэтому даты всех потоков пересекаются
JOINT_STARTS = {1: "2026-09-07", 2: "2026-11-23", 3: "2027-01-11"}

# Предметы и уроки в неделю по потокам: {поток: {линейка: {предмет: уроков}}}.
# «Биология» есть только в «ЕГЭ основной» Потока 1, «Информатика» — только в Потоках 2 и 3;
# у «Русского языка» «ЕГЭ основной» в Потоках 2 и 3 1 урок, а в Потоке 1 — 2 (часы копии выравниваются)
JOINT_LINES = {
    1: {
        JOINT_LINE: {"Математика": 2, "Русский язык": 2, "Биология": 1},
        LEVEL_LINE: {"Математика": 2, "Русский язык": 2},
    },
    2: {
        JOINT_LINE: {"Математика": 2, "Русский язык": 1, "Информатика": 1},
        LEVEL_LINE: {"Математика": 2, "Русский язык": 2},
        OWN_LINE: {"Математика": 1},
    },
}
JOINT_LINES[3] = copy.deepcopy(JOINT_LINES[2])

# Преподаватели: «<предмет> #1» … «#N», каждый «может вести» все курсы своего предмета
JOINT_TEACHERS = {"Математика": 3, "Русский язык": 3, "Биология": 1, "Информатика": 1}

# Принятый Поток 1: (линейка, предмет) -> (преподаватель, ячейки (день, урок)).
# Уровни одного предмета стоят в одни часы у разных преподавателей
JOINT_ACCEPTED = {
    (JOINT_LINE, "Математика"): ("Математика #1", [(0, 0), (2, 0)]),
    (LEVEL_LINE, "Математика"): ("Математика #2", [(0, 0), (2, 0)]),
    (JOINT_LINE, "Русский язык"): ("Русский язык #1", [(1, 1), (3, 1)]),
    (LEVEL_LINE, "Русский язык"): ("Русский язык #2", [(1, 1), (3, 1)]),
    (JOINT_LINE, "Биология"): ("Биология #1", [(4, 2)]),
}

# У «Поток 2 — ЕГЭ основной — Математика» до отметки есть своё: «ведёт» и закрепление
JOINT_PIN_TEACHER = "Математика #3"
JOINT_PIN = {"4-0": "Математика"}


def jointCourse(stream, subject, line=JOINT_LINE):
    """Название курса проекта ``jointProject``: «Поток <stream> — <line> — <subject>» (через courseName)."""
    return courseName(stream, line, subject)


def jointProject(streams=3, accepted=True):
    """Проект для функции «Линейка присоединяется к Потоку N»: пара (settings, answer).

    Настройки — как у нового проекта (``newProjectSettings``: формат, сетка «будни по три урока»,
    пары предметов, календарь 2026/27), но курсы свои:

    * потоки 1…``streams`` (2 или 3) с датами ``JOINT_STARTS``, без дат окончания — все
      пересекаются; линейки и нагрузка — ``JOINT_LINES``: «ЕГЭ основной» и «ЕГЭ продвинутый»
      в каждом потоке, «ОГЭ» — только в Потоках 2 и 3; в «ЕГЭ основной» «Биология» есть
      только в Потоке 1, «Информатика» — только в Потоках 2 и 3;
    * преподаватели ``JOINT_TEACHERS`` («Математика #1» … «#3», «Русский язык #1» … «#3»,
      «Биология #1», «Информатика #1») «могут вести» все курсы своего предмета, у каждого
      пустые отметки времени на каждом этапе;
    * у «Поток 2 — ЕГЭ основной — Математика» «ведёт» ``JOINT_PIN_TEACHER`` и закрепление
      ``JOINT_PIN`` (их должна снять отметка «вместе с Потоком 1»).

    ``answer``: при ``accepted`` — принятый Поток 1 (``JOINT_ACCEPTED``, недели 5 × 3), иначе
    пустое расписание. У Потоков 2 и 3 уроков нет. Отметок ``together_with`` нет — их ставит
    ``markJoint``.
    """
    settings = newProjectSettings()
    settings["classes"] = {"custom_groups": [], "lessons": {}}

    for stream in range(1, streams + 1):
        for line, load in JOINT_LINES[stream].items():
            for subject, hours in load.items():
                addCourse(settings, stream, line, subject, hours, JOINT_STARTS[stream])

    subjects = list(JOINT_TEACHERS)
    settings["subjects"] = [[subject, 1] for subject in subjects]
    settings["soft_subject_pairs"] = [pair for pair in settings["soft_subject_pairs"] if all(subject in subjects for subject in pair)]

    for subject, count in JOINT_TEACHERS.items():
        for number in range(count):
            setTeacherSubjects(settings, f"{subject} #{number + 1}", [subject])

    for data in settings["teachers"].values():
        for stage in getStages(settings):
            teacherAvailability(data, stage["key"])

    pinned = jointCourse(2, "Математика")
    setTeacherCourseState(settings, JOINT_PIN_TEACHER, "Математика", pinned, "assigned")
    settings["constants"][pinned] = dict(JOINT_PIN)

    answer = {}

    if accepted:
        for (line, subject), (name, slots) in JOINT_ACCEPTED.items():
            answer[courseName(1, line, subject)] = courseWeek(subject, name, *slots)

    return settings, answer


def markJoint(settings, section, line, source, answer=None, sync=True):
    """Отмечает линейку ``line`` потока ``section`` «присоединяется к Потоку ``source``» прямо в данных.

    Без кода программы: так тесты строят «уже отмеченный» проект. Курс-копия — курс линейки,
    у которого в той же линейке Потока ``source`` есть курс с тем же предметом; ему ставится
    ``together_with = source``. Курсы, предмета которых в Потоке ``source`` нет, не меняются.

    При ``sync`` копия ещё и согласована с источником, как после ``setJointLine``: нагрузка
    (``classes.lessons``) как у источника, закреплений (``constants``) и «ведёт» нет, а если
    передан ``answer`` — его уроки как у источника (``deepcopy``) или ключа нет, если у источника
    уроков нет. ``sync=False`` ставит только поле (рассогласованный проект).
    Меняет ``settings`` (и ``answer``) на месте; возвращает {копия: источник}.
    """
    section, source = int(section), int(source)
    groups = groupsByName(settings)
    copies = {}

    for group in lineCourses(settings, section, line):
        origin = courseName(source, line, courseSubject(group))

        if origin in groups:
            group["together_with"] = source
            copies[group["name"]] = origin

    if not sync:
        return copies

    for course, origin in copies.items():
        settings["classes"]["lessons"][course] = copy.deepcopy(settings["classes"]["lessons"].get(origin, {}))
        settings.get("constants", {}).pop(course, None)

        for data in settings.get("teachers", {}).values():
            for item in data.get("subjects", []):
                if course in item.get("assigned", []):
                    item["assigned"].remove(course)

        if answer is not None:
            if hasLessons(answer, origin):
                answer[course] = copy.deepcopy(answer[origin])
            else:
                answer.pop(course, None)

    return copies


def markCannot(settings, teacher, stage, *slots):
    """Отмечает у преподавателя ``teacher`` на этапе ``stage`` «не может» в ячейках ``slots`` — пары
    (день, урок). Прямо в данных, без кода программы: так тесты строят отметку, которая уже стоит,
    когда общие уроки встают на это время. Меняет ``settings`` на месте.
    """
    marks = teacherAvailability(settings["teachers"][teacher], stage)
    marks["free"] += [[day, lesson] for day, lesson in slots if [day, lesson] not in marks["free"]]


def setHours(settings, course, hours, subject="Математика"):
    """Ставит курсу ``course`` нагрузку ``hours`` уроков в неделю по предмету ``subject`` (меняет ``settings``)."""
    settings["classes"]["lessons"][course] = {subject: hours}


def stageVariant(settings, answer, stage="1", **weeks):
    """Вариант этапа ``stage``: курсы этапа как в ``answer`` (копии недель), кроме ``weeks`` ({курс: неделя})."""
    variant = {name: copy.deepcopy(week) for name, week in answer.items() if name in stageCourses(settings, stage)}
    variant.update(weeks)

    return variant


def readJson(path):
    """Содержимое JSON-файла ``path``."""
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def writeProject(name, data):
    """Записывает JSON-файл `name` в папку проекта FOLDER (`name` — путь внутри неё, подпапки создаются)."""
    path = os.path.join(FOLDER, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False)


def readProject(name):
    """Читает JSON-файл `name` из папки проекта FOLDER."""
    return readJson(os.path.join(FOLDER, name))


def unnumbered(settings):
    """Настройки так, как их сохраняла программа до появления номера формата (04.10.2026)."""
    old = copy.deepcopy({key: value for key, value in settings.items() if key != "format"})
    old.update({"pair_rules_version": 2, "base_math_version": 2, "joint_pairs_version": 2, "max_teachers_per_course": 0,
                "max_teachers_per_stream": 0, "display": {"time": {}}, "online_start_time": "16:20"})

    for group in old["classes"]["custom_groups"]:
        group["parallel"] = group["program"]

    return old


def writeText(path, text):
    """Записывает в ``path`` текст ``text`` как есть (в том числе испорченный JSON); папка создаётся."""
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        file.write(text)


class TempFolderCase(unittest.TestCase):
    """База: временная папка ``self.folder``, удаляется после теста."""
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="schedule-test-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
