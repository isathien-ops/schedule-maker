"""Сохранённые версии проекта: вкладка «Версии» (на странице она в шаге «Результат»).

Версия — копия настроек, весов и расписания проекта (settings.json, weights.json,
answer.json) в ``versions/<id>/`` с именем, комментарием и временем сохранения
(``meta.json``). Программа сама сохраняет версии перед рискованными действиями —
они называются «Перед: …». Восстановление версии возвращает файлы на место; текущее
состояние перед этим сохраняется как отдельная версия (это делает вызывающий код),
так что ничего не теряется.

Зависимости: files, model (пустая ячейка), joint (общие уроки считаются один раз), variants
(папка построенных вариантов).
"""

import datetime
import os
import shutil

from src.modules.functions.files import readJson, writeJson
from src.modules.functions.joint import jointCopies
from src.modules.functions.model import isLesson
from src.modules.functions.variants import stagesDir

# Файлы проекта, которые входят в версию
FILES = ("settings.json", "weights.json", "answer.json")
# Файл с описанием версии: имя, комментарий, время, число уроков, этапы
META = "meta.json"


def versionsDir(project_path):
    """Папка версий проекта: ``<проект>/versions``."""
    return os.path.join(project_path, "versions")


def lessonCount(answer, settings):
    """Сколько уроков в расписании (непустых ячеек).

    Уроки курсов-копий не считаются: общий урок двух потоков — один урок, его уже посчитал
    источник (так же считает «Расписание» в режиме «Вся школа»).
    """
    copies = jointCopies(settings)

    return sum(1 for course, week in answer.items() if course not in copies for day in week for cell in day if isLesson(cell))


def saveVersion(project_path, name, comment="", stages=None, now=None):
    """Копирует файлы проекта в новую версию; возвращает её id.

    id — время сохранения «ГГГГММДД-ччммсс» (с суффиксом «-2», «-3»…, если в ту же секунду
    уже есть версия). Пустое имя заменяется датой и временем. ``stages`` — этапы, которые
    на момент сохранения уже есть в принятом расписании (пишется в meta.json для показа
    в списке версий). ``now`` можно передать в тестах.
    """
    now = now or datetime.datetime.now()
    base = now.strftime("%Y%m%d-%H%M%S")
    version = base
    number = 1

    while os.path.exists(os.path.join(versionsDir(project_path), version)):
        number += 1
        version = f"{base}-{number}"

    folder = os.path.join(versionsDir(project_path), version)
    os.makedirs(folder)

    # Копируем те файлы, что есть (у нового проекта answer.json может ещё не быть)
    for file in FILES:
        source = os.path.join(project_path, file)

        if os.path.exists(source):
            shutil.copy2(source, os.path.join(folder, file))

    # Число уроков — по файлам самой версии: курсы-копии узнаются по отметкам в её settings.json
    answer, settings = (readJson(os.path.join(folder, file), {}) for file in ("answer.json", "settings.json"))
    meta = {
        "name": name.strip() or now.strftime("%d.%m.%Y %H:%M"),
        "comment": comment.strip(),
        "created": now.isoformat(timespec="seconds"),
        "lessons": lessonCount(answer, settings),
        "stages": list(stages or [])
    }

    writeJson(os.path.join(folder, META), meta)

    return version


def listVersions(project_path):
    """[(id, meta)], сначала новые. Папки без читаемого meta.json пропускаются."""
    folder = versionsDir(project_path)
    result = []

    if not os.path.isdir(folder):
        return result

    for version in os.listdir(folder):
        meta = readJson(os.path.join(folder, version, META), None)

        if isinstance(meta, dict):
            result.append((version, meta))

    return sorted(result, key=lambda item: (item[1].get("created", ""), item[0]), reverse=True)


def restoreVersion(project_path, version):
    """Возвращает файлы версии в проект. Построенные варианты этапов удаляются.

    Нет такой версии — ``FileNotFoundError``. Файл, которого в версии не было (например,
    answer.json, когда расписания ещё не было), удаляется и из проекта.
    """
    folder = os.path.join(versionsDir(project_path), version)

    if not os.path.isdir(folder):
        raise FileNotFoundError(version)

    for name in FILES:
        source = os.path.join(folder, name)
        target = os.path.join(project_path, name)

        if os.path.exists(source):
            shutil.copy2(source, target)

        elif os.path.exists(target):
            # В версии ещё не было расписания
            os.remove(target)

    # Варианты строились для прежних курсов и преподавателей — после восстановления они неверны
    shutil.rmtree(stagesDir(project_path), ignore_errors=True)


def deleteVersion(project_path, version):
    """Удаляет папку версии (ошибки игнорируются)."""
    shutil.rmtree(os.path.join(versionsDir(project_path), version), ignore_errors=True)
