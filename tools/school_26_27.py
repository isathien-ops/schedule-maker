"""Настройки проекта, собранные из реальных данных школы (потоки 1 и 2 учебного года 2026/27).

Источник — `tests/fixtures/school_26_27.json`, его делает `tools/import_26_27.py`
из Google-таблицы «Расписание и программы 26/27».

Учителя, указанные в таблице, закрепляются за своими курсами («ведёт»); курсы без
учителя может взять любой учитель этого предмета («может вести»). Время уроков
здесь не закрепляется. "slots" в фикстуре — реальные дни и время уроков из таблицы:
их использует `tools/create_school_project.py`, чтобы построить принятое расписание.

Настройки собираются сразу в текущем формате проекта (поле "format" = `tree.PROJECT_FORMAT`).

Кто использует модуль:
- скрипты `tools/create_test_project.py` и `tools/create_school_project.py` — импортируют
  его напрямую (`from school_26_27 import buildSettings`, папка tools у них в пути импорта);
- тесты — через `tests/fixture_26_27.py`, который сначала импортирует пакет `tests`
  (подмена папки данных на временную), а затем повторно экспортирует отсюда
  `SUBJECTS`, `loadFixture` и `buildSettings`.

Почему модуль лежит в tools, а не в tests: импорт пакета `tests` подменяет папку данных
(SCHEDULE_DATA_DIR и APPDATA) на временную, которая удаляется при выходе, и запрещает
импорт после `src` (см. tests/__init__.py). Скрипты в tools создают настоящие проекты
в папке пользователя, поэтому пакет `tests` им импортировать нельзя. В src модуль
тоже не кладётся: тогда он попал бы в собранную программу, а ей он не нужен.

Модуль импортирует `src.…`, поэтому корень проекта должен быть в пути импорта
(скрипты tools добавляют его сами, тесты запускаются из корня).
"""

import json
import os

from src.modules.functions.courses import addCourse, courseName, setCourseTeacher
from src.modules.functions.grid import setDayGrid
from src.modules.functions.model import teacherAvailability
from src.modules.functions.school_defaults import DEFAULT_JOINT_SUBJECT_PAIRS, DEFAULT_NON_OVERLAPPING_PROGRAMS
from src.modules.functions.stages import getStages
from src.modules.functions.tree import PROJECT_FORMAT

# Корень проекта: модуль лежит в tools, а данные — в tests/fixtures
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "school_26_27.json")

# Список предметов проекта (порядок задаёт порядок в интерфейсе).
# «Математика база» — отдельный предмет базовой математики линейки «ЕГЭ основной».
SUBJECTS = [
    "Русский язык", "Математика", "Математика база", "Литература", "Обществознание", "История", "География",
    "Английский язык", "Информатика", "Физика", "Химия", "Биология"
]


def loadFixture():
    """Читает и возвращает содержимое `school_26_27.json` (словарь, см. `import_26_27.parse`)."""
    with open(FIXTURE, "r", encoding="utf-8") as file:
        return json.load(file)


def buildSettings(max_courses_per_teacher=10, data=None):
    """Собирает словарь `settings` проекта (то, что лежит в settings.json).

    Параметры:
    - `max_courses_per_teacher` — ограничение «не больше N курсов на учителя»
      (тесты уменьшают его, чтобы проверить нехватку учителей);
    - `data` — уже прочитанные данные фикстуры; по умолчанию читается файл `FIXTURE`.

    Возвращает новый словарь настроек: предметы, сетка уроков, курсы потоков и семинаров
    с датами начала, учителя с их предметами и курсами, стандартные пары предметов
    «нельзя одновременно» (joint_subject_pairs) и правило непересекающихся программ
    (non_overlapping_programs).
    """
    data = data or loadFixture()

    # Базовые настройки проекта. Пар «нежелательно одновременно» здесь нет: тесты проверяют
    # решатель на одних обязательных правилах, а проекту, созданному из этих настроек
    # (tools/create_test_project.py), их по умолчанию дописывает tree.prepareProject
    settings = {
        "format": PROJECT_FORMAT,
        "subjects": [[subject, 1] for subject in SUBJECTS],
        "classes": {"custom_groups": [], "lessons": {}},
        "teachers": {},
        "constants": {},
        "max_courses_per_teacher": max_courses_per_teacher,
        "joint_subject_pairs": [list(pair) for pair in DEFAULT_JOINT_SUBJECT_PAIRS],
        "non_overlapping_programs": [list(pair) for pair in DEFAULT_NON_OVERLAPPING_PROGRAMS],
        "calendar_start_date": data["streams"]["1"],
        "calendar_end_date": "2027-06-30",
    }

    setDayGrid(settings, data["day_grid"])

    # Курсы: у курса потока дата начала — дата потока, у семинара (поток None) — общая дата семинаров
    for item in data["courses"]:
        stream = item["stream"]
        start = data["streams"][str(stream)] if stream is not None else data["extra_start"]

        addCourse(settings, stream, item["line"], item["subject"], item["hours"], start)

    # Каждый учитель преподаёт предметы своих курсов
    for item in data["courses"]:
        for teacher in item["teachers"]:
            subjects = settings["teachers"].setdefault(teacher, {"subjects": [], "availability": {}})["subjects"]

            if not any(entry["subject"] == item["subject"] for entry in subjects):
                subjects.append({"subject": item["subject"], "classes": [], "assigned": []})

    # Закрепляем учителей за курсами: первый учитель из таблицы «ведёт» курс
    for item in data["courses"]:
        course = courseName(item["stream"], item["line"], item["subject"])

        if item["teachers"]:
            setCourseTeacher(settings, course, item["subject"], item["teachers"][0])
            continue

        # В таблице учителя нет: курс может взять любой учитель этого предмета
        for teacher in settings["teachers"].values():
            for entry in teacher["subjects"]:
                if entry["subject"] == item["subject"] and course not in entry["classes"]:
                    entry["classes"].append(course)

    # У каждого учителя — пустые отметки времени («удобно» всегда) на каждом этапе
    for teacher in settings["teachers"].values():
        for stage in getStages(settings):
            teacherAvailability(teacher, stage["key"])

    return settings
