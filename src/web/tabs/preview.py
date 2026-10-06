"""Вкладка «Предпросмотр»: варианты этапа с оценками (GET /api/project/<p>/variants),
отклонение варианта и принятие варианта в расписание. Пара на странице — static/tabs/preview.js.

Функции: variants (список вариантов), rejectVariant, accept (принятие) и его вопрос — acceptQuestion,
jointChanges (что принятие сделает с общими уроками: сдвиг в потоках-копиях, помехи от общих уроков,
у которых другие часы или другой преподаватель, чем при сборке варианта, и «не может» их преподавателя),
teacherParagraphs (кому из принятых курсов вариант сменит преподавателя, в том числе у общих уроков,
и у кого будет больше курсов, чем можно). В вопросе абзацы о преподавателях идут до переставленных уроков.

Зависимости: actions (@action), core (app, LOCK, UserError), project (файлы проекта, проверки
аргументов, версия «Перед: …», формулировки), ranking (оценка и порядок вариантов) и предметные
модули (variants — в том числе метки «принят» / «отклонён», stages, penalties, courses, joint, model).
"""

from flask import jsonify, request

from src.modules.translate import tr, translate
from src.modules.functions.courses import copiesOf, lineOf, teacherLimit
from src.modules.functions.joint import copyCannot, copyConflicts, jointCopies, syncJointAnswer
from src.modules.functions.penalties import describePenalty, penalties
from src.modules.functions.model import groupsByName
from src.modules.functions.stages import (
    changeableCourses, lockedFromAnswer, mergeStageAnswer, movedStarted, stageCopies, stageLabel, staleStarted
)
from src.modules.functions.variants import (
    HARD_METRICS, METRICS, allTied, buildStarted, dropUnknownTeachers, markAccepted, rejectedNumbers, setRejected, teacherCourses,
    teacherOverLimit, variantClashes
)
from src.web.actions import action
from src.web.core import LOCK, UserError, app
from src.web.project import (
    bullets, cannotParagraphs, conflictLines, conflictStages, lessonsText, loadAnswer, loadSettings, movedStartedItems, projectPath, requireStage,
    requireVariant, saveAnswer, saveBeforeVersion
)
from src.web.ranking import changedTeachers, jointMoved, movedLessons, rankedVariants, variantsBuild


# Просмотр и принятие вариантов (вкладка «Предпросмотр»)

@app.route("/api/project/<project>/variants")
def variants(project):
    """Варианты этапа (параметр адреса stage) с оценками, отсортированные от лучшего.

    Для каждого варианта: метрики (variants.variantMetrics: накладки, нехватка уроков,
    штрафы…), problems — каких курсов не хватает уроков и почему, moved — сколько уже принятых
    уроков вариант переставил бы, accepted — этот ли вариант сейчас принят, best / tied —
    лучший вариант и «ничья», teachers / teacherChanges — кто ведёт курсы и кому из принятых курсов
    вариант сменит преподавателя (все поля — в ranking.rankedVariants). teacherCourses — курсы,
    у которых преподаватель различается между не отклонёнными вариантами или с расписанием
    (variants.teacherCourses): строки блока «Кто ведёт».
    Сортировка (variants.rankVariants): варианты, которые принять нельзя (staleStarted, movedStarted), — в конце
    и никогда не «лучшие»; остальные — сначала по сумме «жёстких» нарушений (HARD_METRICS),
    затем по общему штрафу (это оценка variants.variantScore), при равной оценке — по номеру. allTied — все не отклонённые варианты одинаково
    хороши и все их можно принять (variants.allTied): страница пишет «можно принять любой», сама варианты не сравнивая.
    """
    stage = request.args.get("stage")

    with LOCK:
        settings, ranked = rankedVariants(project, stage)

        return jsonify({
            "build": variantsBuild(project, stage),
            "variants": ranked,
            "allTied": allTied(ranked),
            "teacherCourses": teacherCourses(settings, ranked),
            "metrics": [key for key, _ in METRICS],
            "hard": list(HARD_METRICS),
            "limit": teacherLimit(settings),
            "penalties": [dict(item, description=describePenalty(item, translate)) for item in penalties(settings)],
        })


@action(blocking=True)
def rejectVariant(project, stage, number, rejected=True):
    """Отмечает вариант как отклонённый («к нему не нужно возвращаться») или снимает отметку.

    Вариант не удаляется: он остаётся в таблице бледным, и отметку можно снять кнопкой «Вернуть».
    """
    requireStage(loadSettings(project), stage)
    number, _ = requireVariant(project, stage, number)
    path = projectPath(project)
    numbers = rejectedNumbers(path, stage)

    setRejected(path, stage, numbers | {number} if rejected else numbers - {number})


@action(blocking=True)
def accept(project, stage, number, force=False, build=None):
    """Вариант номер `number` становится расписанием этапа `stage`; зафиксированные курсы
    (идут, все уроки на месте) остаются как есть.

    build — «отметка сборки» (variantsBuild), которую видела страница: если варианты
    перестроили, принять нельзя — номер уже указывает на другой вариант. Имя параметра
    совпадает с именем модуля src.web.build, но это имя аргумента в API страницы, и менять его
    нельзя; модуль build здесь не импортирован. Если он понадобится — импортировать его под
    другим именем (`from src.web import build as builds`).
    Вариант, собранный до того, как часть курсов этапа начала идти, и сдвигающий им уроки или
    меняющий преподавателя (stages.staleStarted), не принимается совсем, даже с force: время и
    преподаватель идущего курса не меняются (правило заказчика) — этап надо составить заново.
    Так же проверяется курс, который шёл уже при сборке, но чьи уроки в расписании с тех пор
    поменялись (приняли другой вариант, вернули версию): variants.buildStarted его не возвращает.
    Остальные курсы, которые шли уже при сборке, проверяет stages.movedStarted: если вариант всё же
    сдвинул их урок (решатель не смог оставить его на месте: «не может», урок другого этапа…) или
    сменил им преподавателя, вариант тоже не принимается — отказ называет урок и причину (решение
    заказчика 06.10.2026).
    Без force спрашивает, если вариант ставит преподавателя на два урока сразу (накладки), меняет
    преподавателя уже принятым курсам или даёт кому-то курсов больше лимита (teacherParagraphs),
    переставляет уже принятые уроки, двигает общие уроки потоков-копий (jointChanges). Затем:
    метка accepted.json, версия «Перед: принятие…» и слияние уроков этапа с остальным расписанием
    (stages.mergeStageAnswer).

    Копии этапа (линейка идёт вместе с более ранним потоком) вариант не меняет: их нет среди
    changeableCourses, уроки им ставит поток-источник. Копии источников этого этапа получают
    новые уроки источников (joint.syncJointAnswer). Если источник с тех пор, как вариант собрали,
    сдвинули, копии этапа встанут в новые часы — помехи от этого названы в вопросе (jointChanges).
    Нового преподавателя курса принятие в настройки не пишет: курс остаётся «может вести», и при
    следующей сборке без «оставить принятое» преподаватель снова может смениться.
    """
    settings = loadSettings(project)
    requireStage(settings, stage)
    number, variant = requireVariant(project, stage, number)

    if build is not None and build != variantsBuild(project, stage):
        raise UserError(translate("web.error.no_variant"))

    # Преподаватель, удалённый после сборки, не должен вернуться вместе с вариантом
    dropUnknownTeachers(settings, variant)

    answer = loadAnswer(project)

    # Идущие курсы, которым вариант (собран до их начала) сдвинул бы уроки или сменил преподавателя:
    # это не вопрос, а отказ — force его не снимает
    built = buildStarted(projectPath(project), stage, answer)
    stale = staleStarted(settings, answer, stage, variant, built)

    if stale:
        raise UserError(tr("web.error.variant_stale_started", courses=bullets(stale)))

    moved_started = movedStartedItems(settings, movedStarted(settings, answer, stage, variant, built))

    if moved_started:
        # Курс — отдельной строкой, его уроки с причинами — под ним: в полном названии курса уже есть тире
        lessons = "\n".join(f"• {item['course']}" + "".join(f"\n    {line}" for line in item["lines"]) for item in moved_started)
        raise UserError(tr("web.error.variant_moved_started", lessons=lessons))

    courses = changeableCourses(settings, answer, stage)
    # Зафиксированные после сборки курсы принятие оставит как в расписании — так их видят и вопросы
    # (накладки, лимит курсов), а не какими они были в файле варианта
    variant = lockedFromAnswer(settings, answer, stage, variant)
    clashes = variantClashes(settings, stage, variant, answer)
    moved = movedLessons(answer, variant, courses)
    # Расписание после принятия — с копиями, уже вставшими в новые часы источников
    merged = syncJointAnswer(settings, mergeStageAnswer(answer, variant, courses))
    joint = jointChanges(settings, answer, merged, courses, variant, stage)
    teachers = teacherParagraphs(settings, answer, variant, courses, stage)

    if (clashes or moved or joint or teachers) and not force:
        return acceptQuestion(clashes, teachers, moved, joint)

    markAccepted(projectPath(project), stage, number)
    saveBeforeVersion(project, settings, answer, tr("web.version.accept", number=number, name=stageLabel(stage, translate)))
    saveAnswer(project, merged, settings)


def acceptQuestion(clashes, teachers, moved, joint):
    """Вопрос перед принятием варианта: сколько накладок у преподавателей (clashes), готовые абзацы
    ``teachers`` о смене преподавателей и лимите курсов (teacherParagraphs), какие уже принятые уроки
    вариант переставит (moved — [(курс, (день, урок))]) и абзацы ``joint`` о том, что станет с общими
    уроками потоков-копий (jointChanges). Смена преподавателей — до списка переставленных уроков: она
    короче и важнее, а длинный список иначе уводит её за край окна.
    """
    parts = [tr("web.preview.confirm_clash", count=clashes)] if clashes else []
    parts += teachers

    if moved:
        parts.append(tr("web.preview.confirm_moved", lessons=lessonsText(len(moved)), courses=bullets(course for course, _ in moved)))

    parts += joint

    return {"confirm": "\n\n".join(parts) + "\n\n" + translate("web.preview.confirm_accept"), "yes": translate("web.accept_yes")}


def jointChanges(settings, answer, merged, courses, variant, stage):
    """Абзацы вопроса о том, что принятие варианта сделает с общими уроками.

    ``courses`` — курсы этапа ``stage``, которые принятие меняет; ``merged`` — расписание после
    принятия, копии в нём уже с уроками своих источников; ``variant`` — сам вариант, каким его
    собрал решатель.
    * Копии этих курсов (в более поздних потоках) сдвигаются вместе с ними: строка
      web.preview.confirm_joint_moved на каждую линейку потока-копии. Если новые часы копии мешают
      урокам в её даты (её поток, блоки, другие потоки; joint.copyConflicts), — абзац
      web.preview.confirm_joint_conflicts: тогда лучше составить заново этапы, где стоят мешающие
      уроки (project.conflictStages). Принять всё равно можно: поток-источник важнее (SPEC, Р-6).
      Если общие уроки встанут к преподавателю (новые часы или новый преподаватель) там, где у него
      на этапе потока-копии «не может» (joint.copyCannot), — абзац web.preview.confirm_joint_cannot
      с преподавателем и временем.
    * Копии самого этапа встают в часы источника, какие они сейчас, с его преподавателем. Если с тех
      пор, как вариант собрали, источник сдвинули или сменили ему преподавателя, уроки варианта
      стоят вокруг прежних копий, и новые могут им мешать — абзац web.preview.confirm_joint_stale.
    Пустой список — общих уроков принятие не касается.
    """
    copies = jointCopies(settings)
    following = copiesOf(copies, courses)

    # Сколько уроков копий сдвинется — тот же подсчёт, что пометка варианта на «Предпросмотре»
    # (ranking.jointMoved): в merged у источников уже уроки варианта
    parts = [tr("web.preview.confirm_joint_moved", line=item["line"], number=item["number"], lessons=lessonsText(item["lessons"]))
             for item in jointMoved(settings, answer, merged, courses)]
    parts += [tr("web.preview.confirm_joint_conflicts", number=stream, conflicts=bullets(conflictLines(settings, items)),
                 stages=conflictStages(settings, items))
              for stream, items in sorted(copyConflicts(settings, merged, answer, following).items())]
    parts += cannotParagraphs(settings, copyCannot(settings, merged, following, answer), "web.preview.confirm_joint_cannot")
    # Здесь — только уроки самого варианта (соседи из этапа копии): курсы других этапов стоят как в расписании
    parts += [tr("web.preview.confirm_joint_stale", number=stream, conflicts=bullets(conflictLines(settings, items)))
              for stream, items in sorted(copyConflicts(settings, merged, variant, stageCopies(settings, stage, copies), same_stage=True).items())]

    return parts


def teacherParagraphs(settings, answer, variant, courses, stage):
    """Абзацы вопроса о преподавателях варианта ``variant`` этапа ``stage``; ``courses`` — курсы, которые
    принятие меняет (stages.changeableCourses).

    * Уже принятым курсам вариант сменит преподавателя (ranking.changedTeachers) — абзац
      web.preview.confirm_teacher со строкой «курс: прежний → новый» на каждый курс (нового нет: его
      удалили или запретили ему курс после сборки — «без преподавателя», web.classes.no_teacher); если
      у курса есть копии, — абзац web.preview.confirm_teacher_joint на каждую линейку потока-копии: общие уроки
      поведёт новый преподаватель. Его занятость в потоке-копии проверяет jointChanges (copyConflicts).
    * У преподавателя будет курсов больше лимита (variants.teacherOverLimit) — абзац
      web.preview.confirm_over_limit на каждого.
    Пустой список — спрашивать о преподавателях нечего.
    """
    changes = changedTeachers(answer, variant, courses)
    parts = []

    if changes:
        lines = (f"{item['course']}: {', '.join(item['before'])} → {', '.join(item['after']) or translate('web.classes.no_teacher')}"
                 for item in changes)
        parts.append(tr("web.preview.confirm_teacher", courses=bullets(lines)))

    groups = groupsByName(settings)
    copies = copiesOf(jointCopies(settings), [item["course"] for item in changes])
    lines = sorted({(groups[name]["stream_id"], lineOf(groups[name])) for name in copies})
    parts += [tr("web.preview.confirm_teacher_joint", line=line, number=number) for number, line in lines]
    parts += [tr("web.preview.confirm_over_limit", teacher=teacher, count=count, limit=limit)
              for teacher, count, limit in teacherOverLimit(settings, answer, stage, variant)]

    return parts
