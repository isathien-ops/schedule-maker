"""Папки проектов: создание и открытие проекта, номер формата, импорт и экспорт архивов.

Каждый проект — папка ``<PROJECTS_DIR>/<имя>/`` (по умолчанию в %APPDATA%), в которой лежат:

* ``settings.json`` — настройки: курсы, нагрузка, преподаватели, сетка дня, правила…;
  поле ``"format"`` — номер формата проекта (``PROJECT_FORMAT``);
* ``weights.json`` — «цены» мягких правил для решателя (шаблон — ``src/files/weights.json``);
* ``answer.json`` — «принятое расписание» (курс -> неделя уроков);
* ``stages/`` — построенные варианты по этапам (вход решателя пишется во временную папку
  при каждой сборке и в проекте не хранится);
* ``versions/`` — автосохранённые версии (см. ``versions.py``).

Программа понимает только проекты текущего формата. Проект, архив или версия другого
формата не открываются: человек получает понятное сообщение, а файлы не меняются.

Главная точка входа — ``prepareProject``: она вызывается при создании и при каждом
открытии проекта. Новый проект получает стандартную программу онлайн-школы, у открываемого
проверяется формат и дописываются недостающие значения по умолчанию, испорченные файлы
откладываются в сторону, а курсы-копии «линейки, которая идёт вместе с Потоком N» приводятся
к своим источникам. Ещё здесь — упаковка проекта в zip-архив и распаковка такого
архива как нового проекта.

Зависимости: src.variables (папки, шаблон весов), files, grid, courses, joint, pairs, school_defaults.
"""

import datetime
import json
import os
import shutil
import zipfile

from src.modules.functions.courses import DEFAULT_TEACHER_LIMIT
from src.modules.functions.files import readJson, writeJson
from src.modules.functions.grid import DAYS, DEFAULT_DAY, applyDayGrid
from src.modules.functions.joint import syncJointAnswer, syncJointSettings
from src.modules.functions.pairs import subjectPairs
from src.modules.functions.school_defaults import (
    CALENDAR_END, CALENDAR_START, DEFAULT_JOINT_SUBJECT_PAIRS, DEFAULT_NON_OVERLAPPING_PROGRAMS, createOnlineCourseProgram,
    defaultSoftPairs
)
from src.variables import DEFAULT_WEIGHTS, FORBIDDEN_NAME_CHARS, PROJECTS_DIR

# Номер формата проекта (поле "format" в settings.json). Его нужно увеличить, если формат
# файлов проекта меняется так, что прежние проекты эта программа читать уже не может
PROJECT_FORMAT = 1

# Ключи settings.json, которые остались в проектах, сохранённых до появления поля "format":
# флажки прежних обновлений формата и параметры, которые программа больше не использует
UNNUMBERED_LEFTOVERS = (
    "joint_pairs_version", "seminar_subjects_version", "line_names_version", "iterations_version",
    "base_math_version", "pair_rules_version", "max_teachers_per_course", "max_teachers_per_stream",
    "display", "online_start_time", "lesson_duration_minutes", "break_duration_minutes", "extra_slots",
)


def isCurrentFormat(settings):
    """Сохранены ли настройки ``settings`` (словарь из settings.json) в текущем формате.

    Текущий формат — ``"format" == PROJECT_FORMAT``. Кроме того, текущим считается проект
    без поля "format", у которого есть ``"pair_rules_version" == 2`` и ``"base_math_version" == 2``:
    так помечены проекты, сохранённые программой 04.10.2026 перед тем, как появился номер
    формата (их содержимое уже такое, как нужно). Это временная проверка: когда у всех
    проектов (и их версий, и архивов) будет поле "format", её можно удалить вместе
    с ``UNNUMBERED_LEFTOVERS`` и ``numberFormat``.
    """
    if not isinstance(settings, dict):
        return False

    if "format" in settings:
        return settings["format"] == PROJECT_FORMAT

    return settings.get("pair_rules_version") == 2 and settings.get("base_math_version") == 2


def numberFormat(settings):
    """Проставляет номер формата проекту без поля "format" (см. ``isCurrentFormat``) и убирает
    оставшиеся в нём неиспользуемые ключи. Меняет ``settings`` на месте и возвращает его.

    Временная функция: нужна, пока есть проекты, сохранённые до появления номера формата.
    """
    if "format" in settings:
        return settings

    for key in UNNUMBERED_LEFTOVERS:
        settings.pop(key, None)

    # Поле "parallel" у курсов программа не использует
    for group in settings.get("classes", {}).get("custom_groups", []):
        group.pop("parallel", None)

    settings["format"] = PROJECT_FORMAT

    return settings


def newProjectSettings():
    """Настройки нового проекта: стандартная программа онлайн-школы и правила по умолчанию.

    Курсы четырёх потоков и семинары (``createOnlineCourseProgram``), будни с тремя
    вечерними уроками, пары предметов «нельзя одновременно» и «нежелательно одновременно»,
    правило «Семинары и ЕГЭ продвинутый не пересекаются», даты учебного года 2026/27.
    Преподавателей и закреплённых уроков нет. Возвращает новый словарь.
    """
    subjects, course_groups, course_lessons = createOnlineCourseProgram()
    joint = [list(pair) for pair in DEFAULT_JOINT_SUBJECT_PAIRS]
    hard = subjectPairs({"joint_subject_pairs": joint}, "joint_subject_pairs")

    return {
        "format": PROJECT_FORMAT,
        "working_days_per_week": 5,
        "max_lesson_count_per_day": 3,
        "day_grid": [list(DEFAULT_DAY) if day < 5 else [] for day in range(DAYS)],
        "max_courses_per_teacher": DEFAULT_TEACHER_LIMIT,
        "joint_subject_pairs": joint,
        # Пара, которая уже «нельзя», во второй список не попадает
        "soft_subject_pairs": [pair for pair in defaultSoftPairs(subjects) if tuple(sorted(pair)) not in hard],
        "non_overlapping_programs": [list(pair) for pair in DEFAULT_NON_OVERLAPPING_PROGRAMS],
        "calendar_start_date": CALENDAR_START,
        "calendar_end_date": CALENDAR_END,
        "subjects": [[subject, 1] for subject in subjects],
        "classes": {
            "custom_groups": course_groups,
            "lessons": course_lessons
        },
        "teachers": {},
        "constants": {}
    }


# ---------------------------------------------------------------- архивы и имена проектов

def exportProjectArchive(project_path, archive_path):
    """Упаковывает всю папку проекта ``project_path`` в zip-архив ``archive_path``.

    Пути внутри архива — относительно папки проекта (settings.json лежит в корне архива).
    Если архив создаётся внутри самой папки проекта, он не пакуется сам в себя.
    """
    project_path = os.path.abspath(project_path)
    archive_path = os.path.abspath(archive_path)

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, _, files in os.walk(project_path):
            for name in files:
                path = os.path.join(root, name)

                if os.path.abspath(path) == archive_path:
                    continue

                archive.write(path, os.path.relpath(path, project_path))


def importProjectArchive(archive_path, name):
    """Распаковывает архив проекта (сделанный ``exportProjectArchive``) как новый проект «name».

    Бросает ValueError с ключом перевода, если файл — не архив проекта, имя занято
    или проект в архиве сохранён в другом формате (``isCurrentFormat``; тогда ничего
    не распаковывается). Файлы, которые попали бы за пределы папки проекта (пути с «..»
    и т. п.), отклоняются. Возвращает имя созданного проекта.
    """
    target = os.path.abspath(os.path.join(PROJECTS_DIR, name))

    if os.path.exists(target):
        raise ValueError("web.error.project_name_exists")

    try:
        archive = zipfile.ZipFile(archive_path)

    except (zipfile.BadZipFile, OSError):
        raise ValueError("web.error.not_project_archive")

    with archive:
        names = archive.namelist()

        if "settings.json" not in names:
            raise ValueError("web.error.not_project_archive")

        # Его settings.json должен действительно быть настройками проекта (JSON-объектом)
        try:
            settings = json.loads(archive.read("settings.json").decode("utf-8"))

            if not isinstance(settings, dict):
                raise ValueError

        except (ValueError, UnicodeDecodeError):
            raise ValueError("web.error.not_project_archive")

        if not isCurrentFormat(settings):
            raise ValueError("web.error.old_archive")

        # Защита от «zip slip»: каждый файл архива должен оказаться внутри папки проекта
        for member in names:
            path = os.path.abspath(os.path.join(target, member))

            if not path.startswith(target + os.sep):
                raise ValueError("web.error.not_project_archive")

        os.makedirs(target)

        try:
            archive.extractall(target)

        except Exception:
            # Не оставляем наполовину распакованный проект
            shutil.rmtree(target, ignore_errors=True)
            raise ValueError("web.error.not_project_archive")

    return name


def freeProjectName(name):
    """Свободное имя проекта: «name», или «name_2», «name_3»…, если такой проект уже есть.

    Пробелы заменяются на «_», символы, запрещённые в именах файлов Windows, убираются;
    пустое имя превращается в «Проект».
    """
    name = "".join(char for char in name.strip().replace(" ", "_") if char not in FORBIDDEN_NAME_CHARS) or "Проект"
    candidate, number = name, 1

    while os.path.exists(os.path.join(PROJECTS_DIR, candidate)):
        number += 1
        candidate = f"{name}_{number}"

    return candidate


# ---------------------------------------------------------------- создание и открытие проекта

def prepareProject(project):
    """Создаёт или открывает проект: проверяет формат, чинит файлы, дописывает значения по умолчанию.

    Порядок работы:
    1. settings.json (``projectSettings``): нет файла — новый проект с ``newProjectSettings()``;
       иначе проверяется формат и дописываются недостающие параметры. Проект другого формата
       не открывается — ValueError («web.error.old_project»), файлы не меняются. Нечитаемый
       settings.json откладывается, и бросается ValueError («web.error.broken_settings»): он
       никогда молча не заменяется пустым проектом.
    2. weights.json (``repairWeights``): создаётся из шаблона, испорченный откладывается,
       недостающие веса дописываются.
    3. answer.json (``repairAnswer``): испорченный файл откладывается, расписание — пустое.
    4. Число рабочих дней и уроков в день пересчитываются по сетке, отметки «идёт вместе
       с Потоком N» приводятся к правилам (joint.syncJointSettings); итог записывается
       в settings.json и возвращается.
    5. Курсы-копии в answer.json получают уроки источников (``syncAnswer``).

    Отложенный файл — копия ``<имя>.broken-<время>`` рядом с ним (``setAside``).
    """
    path = os.path.join(PROJECTS_DIR, project)
    settings = projectSettings(path)

    repairWeights(path)
    repairAnswer(path)

    # Число рабочих дней и уроков в день решатель берёт из сетки: пересчитываем их по ней.
    # Отметки и уроки копий согласуются и здесь, а не только при записи (src/web/project.py):
    # answer.json пишут и мимо неё — восстановление версии, tools/create_school_project.py,
    # ручная правка файла
    applyDayGrid(settings)
    syncJointSettings(settings)
    writeJson(os.path.join(path, "settings.json"), settings)
    syncAnswer(path, settings)

    return settings


def setAside(path):
    """Откладывает испорченный файл: копия ``<path>.broken-<ГГГГММДД-ччммсс>`` рядом с ним."""
    shutil.copy(path, f"{path}.broken-{datetime.datetime.now():%Y%m%d-%H%M%S}")


def readDictOrSetAside(path):
    """Словарь из JSON-файла ``path``; файл не читается или в нём не словарь — он откладывается
    (``setAside``) и возвращается None.
    """
    data = readJson(path, None)

    if isinstance(data, dict):
        return data

    setAside(path)

    return None


def projectSettings(path):
    """Настройки проекта в папке ``path``: новые для нового проекта, иначе прочитанные и проверенные."""
    defaults = newProjectSettings()
    file = os.path.join(path, "settings.json")

    if not os.path.exists(file):
        return defaults

    settings = readDictOrSetAside(file)

    if settings is None:
        raise ValueError("web.error.broken_settings")

    if not isCurrentFormat(settings):
        raise ValueError("web.error.old_project")

    numberFormat(settings)

    for key, value in defaults.items():
        settings.setdefault(key, value)

    return settings


def repairWeights(path):
    """weights.json — «цены» правил для решателя: создаётся из шаблона ``src/files/weights.json``,
    если его нет; испорченный откладывается и пишется заново из шаблона; веса, которые появились
    в шаблоне позже, дописываются со значениями по умолчанию.
    """
    file = os.path.join(path, "weights.json")

    if not os.path.exists(file):
        shutil.copy(DEFAULT_WEIGHTS, file)

    weights = readDictOrSetAside(file) or {}
    added = [weights.setdefault(key, value) for key, value in readJson(DEFAULT_WEIGHTS, {}).items() if key not in weights]

    if added:
        writeJson(file, weights)


def repairAnswer(path):
    """Испорченный answer.json откладывается в сторону, а расписание становится пустым, чтобы
    проект всё равно открылся (и его версии можно было восстановить). Файл-метка
    answer.json.repaired сообщает странице, что расписание пришлось сбросить
    (src/web/projects.takeRepairedMark).
    """
    file = os.path.join(path, "answer.json")

    if os.path.exists(file) and readDictOrSetAside(file) is None:
        writeJson(file, {})
        open(f"{file}.repaired", "w").close()


def syncAnswer(path, settings):
    """Курсы-копии в answer.json проекта ``path`` получают уроки источников (joint.syncJointAnswer).

    Вызывается после ``repairAnswer``, поэтому файл, если он есть, — словарь. Файл переписывается
    при каждом открытии, как и settings.json: у согласованного проекта содержимое не меняется.
    Нового файла не появляется: у проекта без расписания копиям нечего брать у источников.
    """
    file = os.path.join(path, "answer.json")

    if os.path.exists(file):
        writeJson(file, syncJointAnswer(settings, readJson(file, {})))
