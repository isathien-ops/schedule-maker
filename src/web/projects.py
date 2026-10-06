"""Стартовый экран и жизненный цикл проекта: список проектов, проверка имени, создание,
импорт архива, удаление, открытие и текущее состояние. Пара на странице — static/projects.js.

Зависимости: core (app, log, LOCK, UserError), project (папка проекта), build (идёт ли сборка,
забыть задание удалённого проекта — только как модуль), state (состояние проекта),
src.variables (папка проектов, запрещённые символы имени) и предметные модули tree (создание,
импорт и проверка формата проекта), stages (этапы и число построенных — stages.builtStages), files.
"""

import datetime
import os
import shutil
import tempfile

import natsort
from flask import jsonify, request

from src.variables import FORBIDDEN_NAME_CHARS, PROJECTS_DIR
from src.modules.translate import translate
from src.modules.functions.files import readJson
from src.modules.functions.stages import builtStages, getStages
from src.modules.functions.tree import freeProjectName, importProjectArchive, prepareProject
from src.web import build
from src.web.core import LOCK, UserError, app, log
from src.web.project import projectPath
from src.web.state import state


# ---------------------------------------------------------------- маршруты: список проектов

@app.route("/api/projects")
def projects():
    """Список проектов с краткой сводкой для стартового экрана.

    Для каждой папки в projects/: число курсов, преподавателей, этапов, полностью построенных
    этапов и время последнего изменения settings.json / answer.json. Файлы читаются без LOCK
    и без проверки формата: проект, который не удаётся разобрать, всё равно показывается
    (с нулями), чтобы его можно было открыть или удалить.
    """
    names = [name for name in natsort.natsorted(os.listdir(PROJECTS_DIR)) if os.path.isdir(os.path.join(PROJECTS_DIR, name)) and not name.startswith(".")]

    return jsonify([projectSummary(name, os.path.join(PROJECTS_DIR, name)) for name in names])


def projectSummary(name, path):
    """Сводка одного проекта для стартового экрана (см. projects).

    Файлы читаются терпимо (испорченный — как пустой), а не через project.loadSettings /
    loadAnswer: стартовый экран должен показать и сломанный проект, чтобы его можно было
    открыть (и получить понятное сообщение) или удалить.
    """
    settings = readJson(os.path.join(path, "settings.json"), {})
    answer = readJson(os.path.join(path, "answer.json"), {})
    # Числа курсов и преподавателей читаются терпимо к типам: в испорченном файле «classes» бывает
    # списком, «custom_groups» или «teachers» — числом. Чего не разобрать — ноль
    classes = settings.get("classes") if isinstance(settings, dict) else None
    groups = classes.get("custom_groups") if isinstance(classes, dict) else None
    groups = groups if isinstance(groups, list) else []
    teachers = settings.get("teachers") if isinstance(settings, dict) else None

    # Проект, этапы которого не удаётся разобрать, всё равно показывается в списке (с нулями)
    try:
        stages = getStages(settings) if groups else []
        built = len(builtStages(settings, answer)) if groups else 0

    except Exception:
        log.debug("Проект %s не разобран для списка проектов", name, exc_info=True)
        stages, built = [], 0

    # «Изменён» — самое позднее время изменения из двух главных файлов
    files = [os.path.join(path, item) for item in ("settings.json", "answer.json") if os.path.exists(os.path.join(path, item))]

    return {
        "name": name,
        "courses": len(groups),
        "teachers": len(teachers) if isinstance(teachers, (dict, list)) else 0,
        "stages": len(stages),
        "built": built,
        "modified": datetime.datetime.fromtimestamp(max(map(os.path.getmtime, files))).isoformat(timespec="minutes") if files else None,
    }


def checkProjectName(name):
    """Проверяет имя нового проекта (оно же имя папки в projects/); не годится — UserError.

    Одна проверка для «Создать проект» и «Импорт проекта», в одном и том же порядке:
      1. пустое имя — «Введите название»;
      2. символы \\ / : * ? " < > |, точка в начале или в конце — с ними Windows не создаст
         папку или исказит её имя;
      3. пробел — проекты называют через «_» (например, Расписание_27-28);
      4. длиннее 80 знаков — иначе пути к файлам проекта выходят слишком длинными;
      5. управляющие (невидимые) символы — табуляция, перевод строки и т. п.; обычно попадают
         в имя при вставке из таблицы, поэтому у них свой текст «наберите заново»;
      6. имена, которые Windows оставляет себе: CON, PRN, AUX, NUL, COM1…COM9, LPT1…LPT9
         (в том числе с расширением, «lpt1.txt»).
    Занято ли имя, здесь не проверяется: это делают сами маршруты (createProject — по наличию
    папки, importProject — через tree.importProjectArchive).
    Имя приходит уже без пробелов по краям (маршруты делают strip()).
    """
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

    if not name:
        raise UserError(translate("web.error.project_name_empty"))

    if any(char in name for char in FORBIDDEN_NAME_CHARS) or name.startswith(".") or name.endswith("."):
        raise UserError(translate("web.error.project_name_chars"))

    if " " in name:
        raise UserError(translate("web.error.project_name_spaces"))

    if len(name) > 80:
        raise UserError(translate("web.error.project_name_too_long"))

    if any(ord(char) < 32 for char in name):
        raise UserError(translate("web.error.project_name_control"))

    if name.split(".")[0].upper() in reserved:
        raise UserError(translate("web.error.project_name_reserved"))


@app.route("/api/projects", methods=["POST"])
def createProject():
    """Создаёт новый пустой проект. Тело запроса: {"name": имя}.

    Имя проверяет checkProjectName (годится ли оно для папки Windows), занятое имя —
    отдельная ошибка. Папка создаётся под LOCK, затем tree.prepareProject заполняет
    её начальными файлами проекта. Возвращает {"project": имя}.
    """
    name = (request.json or {}).get("name", "").strip()
    checkProjectName(name)

    path = os.path.join(PROJECTS_DIR, name)

    if os.path.exists(path):
        raise UserError(translate("web.error.project_name_exists"))

    with LOCK:
        os.mkdir(path)
        prepareProject(name)

    return jsonify({"project": name})


@app.route("/api/projects/import", methods=["POST"])
def importProject():
    """Архив проекта (ZIP с шага «Экспорт» → «Весь проект») становится новым проектом.

    Форма: file — архив, name — имя нового проекта (необязательно; по умолчанию имя файла,
    а если оно занято — свободное похожее, см. tree.freeProjectName); имя проверяет
    checkProjectName, как при создании проекта. Архив сохраняется во
    временную папку и распаковывается в projects/<имя>. Архив проекта другого формата
    не распаковывается (понятная ошибка). Возвращает {"project": имя}.
    """
    upload = request.files.get("file")

    if upload is None or not upload.filename:
        raise UserError(translate("web.error.not_project_archive"))

    name = (request.form.get("name") or "").strip() or freeProjectName(os.path.splitext(upload.filename)[0])

    checkProjectName(name)

    with LOCK, tempfile.TemporaryDirectory() as folder:
        archive = os.path.join(folder, "project.zip")
        upload.save(archive)

        try:
            importProjectArchive(archive, name)

        except ValueError as error:
            raise UserError(translate(str(error)))

        # Распакованный проект сразу открывается, как при «Открыть»; если он не открывается,
        # папка удаляется, чтобы не оставлять мусор
        try:
            prepareProject(name)

        except Exception:
            log.debug("Импортированный проект %s не открылся", name, exc_info=True)
            shutil.rmtree(os.path.join(PROJECTS_DIR, name), ignore_errors=True)
            raise UserError(translate("web.error.not_project_archive"))

    return jsonify({"project": name})


@app.route("/api/project/<project>", methods=["DELETE"])
def deleteProject(project):
    """Удаляет папку проекта со всем содержимым (расписание, варианты, версии).

    Пока идёт сборка, удалять нельзя: фоновая нить продолжает писать в эту папку.
    """
    path = projectPath(project)

    with LOCK:
        if build.running(project):
            raise UserError(translate("web.error.delete_running"))

        shutil.rmtree(path)

    build.forget(project)

    return jsonify({})


def takeRepairedMark(project):
    """Забирает метку «расписание пришлось сбросить»: True, если при открытии повреждённый файл
    расписания отложили в сторону (tree.repairAnswer).

    tree.prepareProject оставляет в папке метку answer.json.repaired; здесь она читается
    и удаляется, так что сообщение человеку показывается один раз.
    """
    folder = projectPath(project)
    marker = os.path.join(folder, "answer.json.repaired")

    if os.path.exists(marker):
        os.remove(marker)
        return True

    return False


@app.route("/api/project/<project>/open", methods=["POST"])
def openProject(project):
    """Открытие проекта на странице: проверка формата и полное состояние.

    Проект другого формата не открывается (понятная ошибка, файлы не меняются).
    Если расписание пришлось восстановить (см. takeRepairedMark), в ответ добавляется
    "message" с объяснением.
    """
    projectPath(project)

    # prepareProject проверяет формат и дописывает значения по умолчанию
    with LOCK:
        try:
            prepareProject(project)

        except ValueError as error:
            raise UserError(translate(str(error)))

        result = state(project)

    if takeRepairedMark(project):
        result["message"] = translate("web.answer_repaired")

    return jsonify(result)


@app.route("/api/project/<project>")
def projectState(project):
    """Текущее состояние проекта без изменений (страница опрашивает его, например, после сборки)."""
    with LOCK:
        return jsonify(state(project))
