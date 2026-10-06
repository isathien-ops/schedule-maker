"""Вкладка «Запуск»: веса встроенных правил, тщательность и число вариантов, свои правила,
«Убрать из расписания», запуск и остановка сборки, ход сборки (GET /api/project/<p>/job).
Пара на странице — static/tabs/run.js.

Курсы-копии («линейка идёт вместе с Потоком N», модуль joint) этот поток не составляет: их уроки
задаёт поток-источник. Поэтому «Убрать из расписания» у источника спрашивает про копии
(resetStage), поток из одних копий составлять нечего, а копии не считаются в решении «оставить
принятое» (run).

Зависимости: actions (@action), core (app, UserError), project (файлы проекта, проверки
аргументов, версия «Перед: …»), build (сама сборка и её параметры — только как модуль) и
предметные модули (courses, grid, joint, model, penalties, stages; stageTotals импортируется по
имени: его подменяют тесты).
"""

import os

from flask import jsonify

from src.modules.translate import tr, translate
from src.modules.functions.courses import copiesOf, lineOf
from src.modules.functions.grid import DAYS
from src.modules.functions.joint import jointCopies
from src.modules.functions.model import groupsByName, hasLessons
from src.modules.functions.penalties import TARGETS, TEMPLATES, newPenalty, penalties
from src.modules.functions.stages import allStarted, changeableCourses, ownCourses, stageCopies, stageCourses, stageLabel, stageTotals
from src.web import build
from src.web.actions import action
from src.web.core import UserError, app
from src.web.project import (
    loadAnswer, loadSettings, loadWeights, number, projectPath, requireStage, saveAnswer, saveBeforeVersion, saveSettings,
    saveWeights
)


# Действия вкладки «Запуск»: веса, параметры, правила, сборка. Веса, параметры и правила — вход сборки:
# пока она идёт, их менять нельзя (blocking=True), как и сетку, курсы и преподавателей

@action(blocking=True)
def setWeight(project, key, value):
    """Вес встроенного штрафа решателя (weights.json). Новые ключи не создаются —
    только уже существующие в файле.
    """
    weights = loadWeights(project)

    if key not in weights:
        raise UserError(translate("web.error.generic"))

    weights[key] = number(value)
    saveWeights(project, weights)


@action(blocking=True)
def setNumber(project, key, value):
    """Параметр сборки: "iterations" (шагов решателя на вариант) или "variants" (сколько вариантов строить)."""
    # Границы проверяет только сервер (на странице у тщательности деления build.ITERATION_LEVELS,
    # а у числа вариантов только min=1)
    limits = {"iterations": (build.MIN_ITERATIONS, build.MAX_ITERATIONS), "variants": (1, build.MAX_VARIANTS)}

    if key not in limits:
        raise UserError(translate("web.error.generic"))

    settings = loadSettings(project)
    settings[key] = number(value, *limits[key])
    saveSettings(project, settings)


def isCount(value):
    """Целое неотрицательное число из JSON (true/false числом не считаются)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def checkPenaltyParams(template, params):
    """Параметры правила того вида, что ждут penalties.RULES: цель из TARGETS[template], дни —
    номера дней недели, времена — строки, лимит — целое неотрицательное число, предметы — строки.

    Почти всё это страница присылает всегда верным; другое бывает только у ручного или
    устаревшего запроса — общая ошибка. Исключение — лимит «Не больше N уроков в день»: его
    завуч вписывает в поле сам, и при пустом поле страница присылает null, а при дробном или
    отрицательном — такое число. Тогда ошибка понятная (penalty.dialog.error_limit), и окно
    правила остаётся открытым, чтобы исправить число.
    """
    valid = isinstance(params, dict) and (template not in TARGETS or params.get("target") in TARGETS[template])

    if valid and template == "time":
        days, times = params.get("days", []), params.get("times", [])
        valid = (isinstance(days, list) and all(isCount(day) and day < DAYS for day in days)
                 and isinstance(times, list) and all(isinstance(time, str) for time in times))

    # Строгая проверка: строка "2" и true тоже отклоняются (страница шлёт только число или null)
    if valid and template == "daily_limit" and not isCount(params.get("limit")):
        raise UserError(translate("penalty.dialog.error_limit"))

    if valid and template == "same_day":
        valid = isinstance(params.get("first"), str) and isinstance(params.get("second"), str)

    if not valid:
        raise UserError(translate("web.error.generic"))


def checkPenalty(name, template, params):
    """Проверяет правило из диалога «Правило»; ошибка — UserError с текстом для диалога."""
    if not name:
        raise UserError(translate("penalty.dialog.error_name"))

    if template not in TEMPLATES:
        raise UserError(translate("web.error.generic"))

    checkPenaltyParams(template, params)

    # Для цели «курс / предмет / линейка» нужно выбрать, какой именно; «каждый преподаватель»
    # и «каждая линейка» бывают только там, где их предлагают (линейка — только у daily_limit)
    if params.get("target") in ("course", "subject") or (params.get("target") == "line" and template != "daily_limit"):
        if not params.get("value"):
            raise UserError(translate("penalty.dialog.error_target"))

    if template == "time" and (not params.get("days") or not params.get("times")):
        raise UserError(translate("penalty.dialog.error_slots"))

    if template == "same_day" and params.get("first") == params.get("second"):
        raise UserError(translate("penalty.dialog.error_same_subject"))


@action(blocking=True)
def savePenalty(project, penalty):
    """Создаёт или изменяет правило-штраф (диалог «Правило» на вкладке «Запуск»).

    penalty — {"id"?, "name", "template", "weight", "params"}. template — вид правила из
    penalties.TEMPLATES (например, "time" — не ставить уроки в выбранное время, "same_day" — два предмета
    в один день, "daily_limit" — не больше N уроков в день); params — его настройки,
    params.target — на кого нацелено (курс / предмет / линейка / преподаватель…), value — кто именно.
    С известным id — заменяет существующее (id сохраняется), иначе добавляет новое.
    """
    settings = loadSettings(project)
    name = (penalty.get("name") or "").strip()
    template = penalty.get("template")
    params = penalty.get("params", {})
    checkPenalty(name, template, params)

    item = newPenalty(name, template, number(penalty.get("weight", 0)), params)
    items = penalties(settings)
    index = next((i for i, old in enumerate(items) if old["id"] == penalty.get("id")), None)

    if index is None:
        items.append(item)

    else:
        item["id"] = items[index]["id"]
        items[index] = item

    saveSettings(project, settings)


@action(blocking=True)
def setPenaltyWeight(project, id, weight):
    """Меняет только вес правила с данным id (поле в списке правил)."""
    settings = loadSettings(project)

    for item in penalties(settings):
        if item["id"] == id:
            item["weight"] = number(weight)

    saveSettings(project, settings)


@action(blocking=True)
def deletePenalty(project, id):
    """Удаляет правило с данным id."""
    settings = loadSettings(project)
    settings["custom_penalties"] = [item for item in penalties(settings) if item["id"] != id]
    saveSettings(project, settings)


@action(blocking=True)
def resetStage(project, stage, force=False, ask=False):
    """«Убрать из расписания»: убирает из принятого расписания уроки курсов этапа, кроме уже идущих.

    Перед этим сохраняется версия «Перед: снятие «…» с расписания». Если убирать нечего — ошибка;
    если в расписании этапа только общие уроки (копии), в ней сказано про них (nothingToReset).
    Варианты этапа не трогаются: их можно принять снова.
    Копии этапа (их уроки задаёт поток-источник) остаются. А если с курсами этапа идут линейки
    более поздних потоков, их уроки уберутся тоже (копия без уроков источника «ждёт» его): без
    force — вопрос со строкой про каждую такую линейку.
    ``ask`` — страница спрашивает «Убрать?» не сама, а через сервер: тогда без force вопрос есть
    всегда, в нём общий текст web.confirm_reset и строки про линейки. Так завуч видит один вопрос
    со всеми сведениями (SPEC, AC-40).
    """
    settings = loadSettings(project)
    requireStage(settings, stage)
    answer = loadAnswer(project)
    courses = changeableCourses(settings, answer, stage, complete=False)

    # «Есть что убирать» — именно уроки: после принятия варианта в answer.json бывают и курсы
    # с пустой неделей (решатель пишет в ответ каждый курс этапа). Сами их ключи ниже всё равно
    # убираются вместе с остальными курсами этапа
    if not any(hasLessons(answer, course) for course in courses):
        raise UserError(translate(nothingToReset(settings, answer, stage)))

    lines = followingLines(settings, [name for name in copiesOf(jointCopies(settings), courses) if hasLessons(answer, name)])
    question = [tr("web.confirm_reset", name=stageLabel(stage, translate))] if ask else []
    question += ["\n".join(tr("web.run.confirm_reset_joint", line=line, number=number) for line, number in lines)] if lines else []

    if question and not force:
        return {"confirm": "\n\n".join(question), "danger": True, "yes": translate("web.reset_yes")}

    saveBeforeVersion(project, settings, answer, tr("web.version.reset", name=stageLabel(stage, translate)))
    # Копии источников этого этапа теряют уроки при записи (joint.syncJointAnswer)
    saveAnswer(project, {name: value for name, value in answer.items() if name not in courses}, settings)


def nothingToReset(settings, answer, stage):
    """Ключ текста отказа «Убирать нечего» у этапа ``stage``, где нет уроков, которые можно убрать.

    В расписании этапа нет ни одного урока (например, запрос пришёл из устаревшей вкладки, а этап
    уже убрали) — «уроков нет». Только общие уроки (у копий уроки есть, у своих курсов нет) — текст
    про них, тот же, что подсказка у закрытой кнопки: их убирает поток-источник (SPEC, AC-41).
    Иначе — «только курсы, которые уже идут».
    """
    copies = stageCopies(settings, stage)
    scheduled = [course for course in stageCourses(settings, stage) if hasLessons(answer, course)]

    if not scheduled:
        return "web.run.nothing_to_reset_empty"

    if all(course in copies for course in scheduled):
        return "web.run.nothing_to_reset_joint"

    return "web.run.nothing_to_reset_any"


def followingLines(settings, copies):
    """Линейки курсов-копий ``copies`` без повторов: [(линейка, номер потока-копии)] в порядке курсов."""
    by_name = groupsByName(settings)

    return list(dict.fromkeys((lineOf(by_name[name]), by_name[name]["stream_id"]) for name in copies))


@action
def run(project, stage, keep=False):
    """Запускает сборку вариантов этапа `stage` в фоновой нити и сразу возвращается.

    keep=True — режим «оставить принятое»: уже принятые уроки курсов этапа сохраняются,
    решатель только добавляет недостающие. Отказ, если сборка уже идёт, нет solve.exe,
    этап неизвестен, все курсы этапа — копии (идут вместе с другим потоком) или все зафиксированы
    (идут и все уроки на месте — строить нечего). Ход сборки страница узнаёт через /job или
    поле "job" состояния.
    """
    if build.running(project):
        raise UserError(translate("web.error.busy"))

    if not os.path.exists(build.SOLVER):
        raise UserError(translate("web.error.no_solver"))

    settings = loadSettings(project)
    requireStage(settings, stage)
    answer = loadAnswer(project)
    courses = stageCourses(settings, stage)
    copies = stageCopies(settings, stage)

    # Все курсы этапа — копии: их уроки задаёт другой поток. Проверяется раньше allStarted: для
    # такого этапа он тоже верен, но «все курсы уже идут» было бы неправдой
    if all(course in copies for course in courses):
        raise UserError(translate("web.run.all_joint"))

    # Все курсы этапа зафиксированы (идут и все уроки на месте) — программе нечего менять
    if allStarted(settings, answer, stage):
        raise UserError(translate("web.run.all_started"))

    # «Оставить уже принятые уроки на месте» нужно, только пока потоку не хватает уроков (добавить недостающие).
    # Если все уроки уже стоят, с этой галочкой программе нечего менять — составляем заново. Копии не
    # в счёт (stages.ownCourses — тот же счёт, что у галочки на странице): недостающие уроки копий
    # встанут из потока-источника, а не из этой сборки
    expected, placed = stageTotals(settings, answer, ownCourses(settings, stage, copies))

    if keep and placed >= expected:
        keep = False

    build.startJob(project, stage, keep, int(settings.get("variants", build.DEFAULT_VARIANTS)))


@action
def stop(project):
    """Кнопка «Остановить»: останавливает сборку проекта (build.stopJob)."""
    build.stopJob(project)


@app.route("/api/project/<project>/job")
def jobStatus(project):
    """Ход сборки (см. build.jobState); страница опрашивает его, пока сборка идёт."""
    projectPath(project)

    return jsonify(build.jobState(project))
