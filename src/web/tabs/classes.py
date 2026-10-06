"""Вкладка «Курсы»: потоки и блоки, их даты, линейки, курсы, уроки в неделю, преподаватель
курса и закреплённые уроки. Пара на странице — static/tabs/classes.js.

Удаление потока, линейки и курса устроено одинаково, для этого здесь три помощника:
confirmRemoval (вопрос с перечнем идущих курсов), saveRemovalVersion (версия «Перед: …»,
если у курсов есть уроки в расписании) и purgeCourses (чистка правил, расписания и вариантов от
удалённых курсов). Если среди удаляемых есть курсы-источники, в вопросе названы их копии:
они станут обычными курсами со своими уроками.

«Линейка идёт вместе с Потоком N» (.spec/joint-lines/SPEC.md): отметку ставит и снимает действие
setJoint (сама отметка — joint.setJointLine; помехи от новых часов копий — joint.copyConflicts,
«не может» преподавателя в эти часы — joint.copyCannot). У курса-копии время, преподаватель и число уроков
те же, что у источника, поэтому setHours, setTeacher и setPins копию не меняют (project.requireOwnCourse), а у
источника проверяют «курс уже идёт» по всей группе «источник + копии» (courses.sharedStarted,
courses.sharedLocked). Новые уроки и часы источника копия получает при записи проекта
(project.saveSettings, project.saveAnswer).

Зависимости: actions (@action), core (UserError), project (файлы проекта, проверки аргументов,
версия «Перед: …», переписывание вариантов, формулировки) и предметные модули (model, courses,
joint, school_defaults, grid, stages, penalties, variants). datetime импортируется модулем: тесты
подменяют datetime.date.
"""

import copy
import datetime

from src.modules.translate import tr, translate
from src.modules.functions.courses import (
    addCourse, addLine, addStream, clearStageMarks, copiesOf, copyLineToStreams, courseHours, lessons, lineCourses, moveLessons,
    pinnedSlots, plannedMoves, removeCourses, removeLine, removeStream, replaceTeacherInAnswer, sectionEnd, sectionLines,
    sectionStart, setCourseTeacher, setPinnedSlots, setSectionEnd, setSectionStart, sharedLocked, sharedStarted, slotConflicts,
    streamIds, subjectTeachers, teacherConflicts, teacherLimit
)
from src.modules.functions.grid import dayGrid, lessonExists
from src.modules.functions.joint import copyCannot, copyConflicts, jointCopies, jointRoot, setJointLine, syncJointAnswer
from src.modules.functions.model import (
    courseDates, courseGroups, courseSlots, groupsByName, hasLessons, inSection, isBlock, lessonEntries, stageKey
)
from src.modules.functions.penalties import dropTargeted
from src.modules.functions.school_defaults import createOnlineCourseProgram
from src.modules.functions.stages import getStages, stageCopies, stageLabel, startedCourses
from src.modules.functions.variants import clearStaleVariants, clearVariants
from src.web.actions import action
from src.web.core import UserError
from src.web.project import (
    bullets, cannotParagraphs, conflictLines, conflictStages, lessonsText, loadAnswer, loadSettings, number, projectPath, requireCourse, requireLine,
    requireOwnCourse, requireSection, requireSubjects, rewriteVariants, saveAnswer, saveBeforeVersion, saveSettings, slotText
)


# ---------------------------------------------------------------- удаление курсов: общие шаги

def confirmRemoval(project, settings, names, text):
    """Вопрос перед удалением курсов `names`: ответ действия вида {"confirm": ..., "danger": True}.

    К тексту `text` добавляется перечень идущих курсов (их удаление особенно опасно), перечень
    копий удаляемых курсов-источников (они станут обычными, уроки останутся) и, если у курсов
    есть уроки в расписании, напоминание, что перед удалением будет сохранена версия.
    Идущие — только курсы, которые начались сами (``shared=False``): у них уроки пропадут из расписания
    учеников. Источник, который «идёт» лишь через копию, сюда не попадает — его поток ещё не начался,
    а уроки копии останутся (о ней — абзац web.classes.joint_remove_note).
    """
    answer = loadAnswer(project)
    running = sorted(startedCourses(settings, answer, names, complete=False, shared=False))

    if running:
        text += "\n\n" + tr("web.confirm_remove_started", courses=bullets(running))

    # Копии удаляемых источников не удаляются, а становятся обычными курсами со своими уроками
    # (project.saveSettings снимет у них отметку) — завуч должен знать, что они больше не общие
    orphans = [name for name in copiesOf(jointCopies(settings), names) if name not in names]

    if orphans:
        text += "\n\n" + tr("web.classes.joint_remove_note", courses=bullets(orphans))

    # Именно уроки, а не ключ курса в answer.json: после принятия варианта там бывают
    # и курсы с пустой неделей (решатель пишет в ответ каждый курс этапа)
    if any(hasLessons(answer, name) for name in names):
        text += "\n\n" + translate("web.confirm_remove_version")

    return {"confirm": text, "danger": True, "yes": translate("web.common.delete")}


def saveRemovalVersion(project, settings, names, action):
    """Сохраняет версию «Перед: <action>», если хотя бы у одного из курсов `names` есть уроки
    в расписании — чтобы удаление можно было откатить. Без уроков в расписании версия не нужна
    (курс с пустой неделей в answer.json тоже считается «без уроков», см. confirmRemoval).
    """
    answer = loadAnswer(project)

    if any(hasLessons(answer, name) for name in names):
        saveBeforeVersion(project, settings, answer, action)


def purgeCourses(project, names):
    """Убирает следы удалённых курсов `names` из всех файлов проекта.

    * правила-штрафы, нацеленные на эти курсы;
    * их уроки в принятом расписании (answer.json);
    * их уроки во всех построенных вариантах — иначе принятие варианта вернуло бы удалённый курс;
    * варианты этапа, который пропал вместе с последними курсами (variants.clearStaleVariants).
    Файл перезаписывается, только если в нём действительно что-то поменялось.
    Вызывается после того, как курсы уже убраны из settings.json и он сохранён.
    """
    settings = loadSettings(project)
    gone = set(names)

    if dropTargeted(settings, "course", gone):
        saveSettings(project, settings)

    answer = loadAnswer(project)
    kept = {name: value for name, value in answer.items() if name not in gone}

    if len(kept) != len(answer):
        saveAnswer(project, kept)

    def dropCourses(variant):
        """Убирает удалённые курсы из варианта; True — что-то убрано."""
        found = gone & set(variant)

        for name in found:
            del variant[name]

        return bool(found)

    clearStaleVariants(projectPath(project), [stage["key"] for stage in getStages(settings)])
    rewriteVariants(project, settings, dropCourses)


# ---------------------------------------------------------------- потоки и даты

def newStreamStart(settings, streams):
    """Дата начала нового потока: через 7 недель после начала последнего (или сегодня, если
    потоков нет или дата неверна), сдвинутая на ближайший понедельник.
    """
    try:
        start = datetime.date.fromisoformat(sectionStart(settings, streams[-1]) if streams else "") + datetime.timedelta(weeks=7)

    except ValueError:
        start = datetime.date.today()

    return start + datetime.timedelta(days=(7 - start.weekday()) % 7)


def addTemplateCourses(settings, stream, start):
    """Новый поток `stream` получает курсы первого потока стандартной программы школы —
    только по предметам, которые есть в проекте (school_defaults.createOnlineCourseProgram).
    """
    known = {name for name, _ in settings.get("subjects", [])}
    _, template, template_lessons = createOnlineCourseProgram()

    for group in template:
        if group.get("stream_id") == 1:
            for subject in group["subjects"]:
                if subject in known:
                    addCourse(settings, stream, group["program"], subject, template_lessons[group["name"]][subject], start)


@action(blocking=True)
def newStream(project):
    """Добавляет новый поток.

    Дата начала — newStreamStart. Линейки и курсы копируются из предыдущего потока
    (courses.addStream). Номер нового потока мог быть у потока, который пропал раньше
    (например, удалили все его линейки), поэтому всё, что от того осталось, стирается:
    отметки «удобно / может / не может» преподавателей для этого номера (courses.clearStageMarks)
    и старые варианты этапа. Возвращает {"section": номер, "message": текст}.

    Если потоков нет совсем (человек удалил все), копировать не из чего, а поток без курсов
    программа не хранит (потоки — это номера stream_id у курсов, см. courses.streamIds).
    Тогда новый «Поток 1» получает линейки и курсы первого потока стандартной программы школы
    (addTemplateCourses). Если ни одного такого предмета нет — отказ: пустой поток всё равно
    не появился бы.
    """
    settings = loadSettings(project)
    streams = streamIds(settings)
    start = newStreamStart(settings, streams).isoformat()
    stream = addStream(settings, start)

    # Отметки времени от прежнего потока с этим номером новому потоку не достаются
    clearStageMarks(settings, stream)

    if not streams:
        addTemplateCourses(settings, stream, start)

        if stream not in streamIds(settings):
            raise UserError(translate("web.classes.stream_no_subjects"))

    saveSettings(project, settings)
    clearVariants(projectPath(project), str(stream))

    message = tr("web.classes.stream_added", name=stageLabel(str(stream), translate))

    if streams:
        message += " " + tr("web.classes.stream_copied", source=stageLabel(str(streams[-1]), translate))

    else:
        message += " " + translate("web.classes.stream_from_template")

    return {"section": stream, "message": message}


@action(blocking=True)
def deleteStream(project, section, force=False):
    """Удаляет поток `section` со всеми его курсами. Блоки удалить нельзя.

    Без force — вопрос (с перечнем идущих курсов, если они есть). С force: версия «Перед:
    удаление потока» (если курсы были в расписании), удаление из настроек, стирание вариантов
    этапа и уроков курсов из расписания и вариантов других этапов.
    """
    if isBlock(section):
        raise UserError(translate("web.error.generic"))

    settings = loadSettings(project)
    requireSection(settings, section)
    names = [group["name"] for group in courseGroups(settings) if group.get("stream_id") == section]
    label = stageLabel(str(section), translate)

    if not force:
        question = confirmRemoval(project, settings, names, tr("menu.main.tab.classes.confirm_remove_stream", name=label))
        question["yes"] = translate("web.delete_stream_yes")
        return question

    saveRemovalVersion(project, settings, names, tr("web.version.delete_stream", name=label))
    removeStream(settings, section)
    clearVariants(projectPath(project), str(section))
    saveSettings(project, settings)
    purgeCourses(project, names)


def checkDate(value):
    """Проверяет дату из формы (ISO, «гггг-мм-дд»); пустая — «не менять». Неверная — UserError."""
    if value:
        try:
            datetime.date.fromisoformat(value)

        except (TypeError, ValueError):
            raise UserError(translate("web.error.date"))


def checkDatesOrder(settings, section):
    """Конец не может быть раньше начала — ни у курсов раздела (у курса может быть своя дата
    начала), ни у самого раздела (блок без курсов проверяется по своим собственным датам).
    """
    for group in courseGroups(settings):
        if inSection(group, section):
            first, last = courseDates(settings, group)

            if first > last:
                raise UserError(translate("web.error.dates_order"))

    first, last = sectionStart(settings, section), sectionEnd(settings, section)

    if first and last and first > last:
        raise UserError(translate("web.error.dates_order"))


@action(blocking=True)
def setDates(project, section, start=None, end=None, force=False):
    """Даты начала и/или конца потока или блока `section` (ISO, «гггг-мм-дд»; None — не менять).

    Проверяется, что конец не раньше начала (checkDatesOrder). Если из-за новых дат какие-то
    курсы начинают или перестают «уже идти» (это меняет, что можно редактировать), без force
    задаётся вопрос.
    """
    settings = loadSettings(project)
    requireSection(settings, section)
    answer = loadAnswer(project)
    names = [group["name"] for group in courseGroups(settings) if inSection(group, section)]
    # Какие курсы «уже идут» до изменения — чтобы сравнить с тем, что будет после
    started_before = startedCourses(settings, answer, names, complete=False)

    checkDate(start)
    checkDate(end)

    if start:
        setSectionStart(settings, section, start)

    if end:
        setSectionEnd(settings, section, end)

    checkDatesOrder(settings, section)
    started_after = startedCourses(settings, answer, names, complete=False)

    if started_after != started_before and not force:
        key = "web.confirm_dates_start" if len(started_after) > len(started_before) else "web.confirm_dates_unstart"
        return {"confirm": translate(key), "yes": translate("web.dates_yes")}

    saveSettings(project, settings)


# ---------------------------------------------------------------- линейки и курсы

@action(blocking=True)
def newLine(project, section, name, subjects):
    """Новая линейка `name` в разделе `section` с курсами по выбранным предметам (по одному на предмет).
    Имя должно быть непустым и не повторять другую линейку этого раздела.
    """
    name = (name or "").strip()
    settings = loadSettings(project)
    requireSection(settings, section)
    requireSubjects(settings, subjects)

    if not name or name in sectionLines(settings, section):
        raise UserError(translate("web.error.line_name"))

    addLine(settings, section, name, subjects)
    saveSettings(project, settings)


@action(blocking=True)
def deleteLine(project, section, line, force=False):
    """Удаляет линейку со всеми её курсами: без force — вопрос; с force — версия «Перед: …»,
    удаление из настроек и из расписания/вариантов (purgeCourses).
    """
    settings = loadSettings(project)
    requireLine(settings, section, line)
    names = [group["name"] for group in lineCourses(settings, section, line)]

    if not force:
        return confirmRemoval(project, settings, names, tr("menu.main.tab.classes.confirm_remove_line", name=line))

    saveRemovalVersion(project, settings, names, tr("web.version.delete_line", name=line))
    removeLine(settings, section, line)
    saveSettings(project, settings)
    purgeCourses(project, names)


@action(blocking=True)
def newCourse(project, section, line, subject):
    """Новый курс по предмету `subject` в линейке `line` раздела `section` (1 урок в неделю).

    В линейке, которая идёт вместе с Потоком N, курс предмета из той же линейки Потока N сразу
    становится копией с часами источника (courses.addCourse). Тогда переписывается и расписание:
    при записи копия получает уроки источника (project.saveAnswer).
    """
    settings = loadSettings(project)
    requireLine(settings, section, line)
    requireSubjects(settings, [subject])
    name = addCourse(settings, section, line, subject, 1)
    saveSettings(project, settings)

    if jointRoot(settings, name) != name:
        saveAnswer(project, loadAnswer(project), settings)


@action(blocking=True)
def deleteCourse(project, course, force=False):
    """Удаляет один курс: без force — вопрос; с force — версия «Перед: …», удаление
    из настроек и из расписания/вариантов.
    """
    settings = loadSettings(project)
    requireCourse(settings, course)

    if not force:
        return confirmRemoval(project, settings, [course], tr("menu.main.tab.classes.confirm_remove_subject", name=course))

    saveRemovalVersion(project, settings, [course], tr("web.version.delete_course", name=course))
    removeCourses(settings, [course])
    saveSettings(project, settings)
    purgeCourses(project, [course])


@action(blocking=True)
def copyLine(project, section, line):
    """Копирует линейку `line` (её курсы с часами и т.п.) из потока `section` во все остальные потоки.

    Только для потоков: у блока нет «остальных блоков» с теми же линейками (кнопка на странице
    у блока выключена; ручной запрос — общая ошибка, иначе появились бы курсы «Поток N — Семинар…»).
    Потоки, где уже идут курсы, не трогаются — о них возвращается сообщение. Поток, курсы которого
    «идут» только через присоединённые к ним курсы более позднего потока (сам он ещё не начался), тоже
    не трогается, но назван отдельно (web.classes.copy_skipped_joint): «уже начавшимся» его не назвать.
    Если в потоке линейка присоединена к другому потоку, новые курсы там становятся копиями;
    тогда переписывается и расписание: копии получают уроки источника (как у newCourse).
    """
    if isBlock(section):
        raise UserError(translate("web.error.generic"))

    settings = loadSettings(project)
    requireLine(settings, section, line)
    answer = loadAnswer(project)
    groups = groupsByName(settings)

    def startedStreams(shared):
        """Потоки (кроме этого) с идущими курсами; ``shared`` — как в stages.startedCourses."""
        return {
            groups[name]["stream_id"] for name in startedCourses(settings, answer, list(groups), complete=False, shared=shared)
            if groups[name].get("stream_id") not in (None, section)
        }

    # Потоки с уже идущими курсами (по дате и с уроками в расписании) не трогаются — и те, где курсы
    # «идут» только через присоединённые к ним курсы более позднего потока (их уроки менять нельзя)
    started = startedStreams(True)
    own = startedStreams(False)

    copyLineToStreams(settings, section, line, started)
    saveSettings(project, settings)

    # В линейке, которая присоединена к другому потоку, новый курс сразу становится копией
    # (courses.addCourse) — тогда, как у newCourse, переписывается и расписание: копия получает
    # уроки источника (project.saveAnswer). Без новых копий answer.json не трогается
    added = set(groupsByName(settings)) - set(groups)

    if any(jointRoot(settings, name) != name for name in added):
        saveAnswer(project, answer, settings)

    def labels(streams):
        """«Поток 1, Поток 3» — потоки по порядку."""
        return ", ".join(stageLabel(str(stream), translate) for stream in sorted(streams))

    message = ([tr("web.classes.copy_skipped", streams=labels(own))] if own else []) + (
        [tr("web.classes.copy_skipped_joint", streams=labels(started - own))] if started - own else [])

    if message:
        return {"message": " ".join(message)}


# ---------------------------------------------------------------- линейка идёт вместе с Потоком N

# Причина отказа joint.setJointLine -> текст для завуча. В тексты подставляются выбранный поток
# ({stream}) и поток из отказа ({number}): корень цепочки или поток, который уже идёт вместе с линейкой
JOINT_REFUSALS = {
    "invalid": "web.error.joint_source",
    "chain": "web.error.joint_chain",
    "has_copies": "web.error.joint_has_copies",
    "started": "web.error.joint_started",
}


def jointLessonParagraphs(changed, scheduled, copies, line, section, source):
    """Абзацы вопроса setJoint о курсах ``changed`` (joint.setJointLine), чьи уроки в расписании сменятся
    или пропадут при отметке «присоединяется к Потоку ``source``».

    ``scheduled`` — расписание после отметки (копии уже с уроками источников, joint.syncJointAnswer),
    ``copies`` — копии потока после отметки. По ним курсы делятся на три группы:
    * уроки остались — встанут в дни и часы источника: web.classes.joint_confirm;
    * уроков нет, а курс — копия: у источника уроков пока нет, копия их ждёт: web.classes.joint_confirm_waiting;
    * уроков нет, а курс больше не копия (сменили поток-источник, а в новом этого предмета нет): курс
      стал обычным, общие уроки прежнего источника убраны: web.classes.joint_confirm_dropped.
    Обещать «поставить в те же часы» курсам, уроки которых на деле пропадут, нельзя.
    """
    lost = [name for name in changed if not hasLessons(scheduled, name)]
    waiting = [name for name in lost if name in copies]
    dropped = [name for name in lost if name not in copies]
    parts = [tr("web.classes.joint_confirm", line=line, stream=section, number=source)] if len(lost) < len(changed) else []

    if waiting:
        parts.append(tr("web.classes.joint_confirm_waiting", line=line, stream=section, number=source, courses=bullets(waiting)))

    if dropped:
        parts.append(tr("web.classes.joint_confirm_dropped", line=line, stream=section, number=source, courses=bullets(dropped)))

    return parts


@action(blocking=True)
def setJoint(project, section, line, source=None, force=False):
    """Отмечает, что линейка ``line`` потока ``section`` присоединяется к Потоку ``source``; None — «нет»
    (снять отметку, линейка составляется отдельно).

    Сама отметка — joint.setJointLine; она же решает, где отказ (блок, поток не раньше своего,
    цепочка, линейка-источник другого потока, курсы уже идут). Её вызов сначала идёт на копиях
    данных: при отказе или «Отмене» файлы проекта не меняются.
    * Включение, когда у будущих копий в расписании другие уроки, — без force вопрос: они встанут
      в дни и часы источника (web.classes.joint_confirm). Уроков нет или они уже такие же — без вопроса.
      Если у источника уроков нет, уроки копии не встают, а убираются («ждут Поток N»): такие курсы
      названы отдельно (web.classes.joint_confirm_waiting), как и бывшие копии, которые при смене
      потока-источника становятся обычными и теряют общие уроки (web.classes.joint_confirm_dropped);
      см. jointLessonParagraphs. В конце вопроса — что перед изменением сохранится версия
      (web.classes.joint_version).
    * Включение, когда уроки источника встанут туда, где мешают другим урокам в даты этого потока
      (пара «нельзя», преподаватель занят, программы, которые не пересекаются; joint.copyConflicts), —
      без force вопрос с этими помехами и этапами, где они стоят (project.conflictStages): их варианты
      тогда лучше составить заново.
    * Включение, когда общие уроки встанут во время, где у их преподавателя на этапе этого потока
      «не может» (joint.copyCannot), — не запрет: в том же вопросе абзац с преподавателем и временем.
      Названы все такие уроки новых копий и копий, у которых сменился источник (выбрали другой
      поток), даже если урок уже стоял там до отметки.
    * Снятие убирает уроки бывших копий, курсы снова подбираются как обычные. То же при смене
      потока-источника у бывших копий, предмета которых в новом источнике нет (joint.setJointLine).
    Об отметке и о её снятии — сообщение. Если уроки в расписании пропадают или меняются, сначала
    сохраняется версия «Перед: …». Варианты этапа удаляются всегда: они собраны без отметки или
    с ней и больше не годятся.
    """
    settings = loadSettings(project)
    requireLine(settings, section, line)
    answer = loadAnswer(project)
    marked, scheduled = copy.deepcopy(settings), copy.deepcopy(answer)

    try:
        changed = setJointLine(marked, section, line, source, scheduled)

    except ValueError as error:
        reason, stream = error.args
        raise UserError(tr(JOINT_REFUSALS[reason], stream=source, number=stream))

    # Копии получают уроки источника уже здесь, чтобы проверить их новые часы. Копии других линеек
    # потока не сдвигаются — новых мест у них нет, и помех от них тоже
    syncJointAnswer(marked, scheduled)
    copies = stageCopies(marked, str(section))
    conflicts = copyConflicts(marked, scheduled, answer, copies)
    question = jointLessonParagraphs(changed, scheduled, copies, line, section, source) if source is not None else []
    question += [tr("web.classes.joint_conflicts", line=line, stream=stream, conflicts=bullets(conflictLines(marked, items)),
                    stages=conflictStages(marked, items))
                 for stream, items in conflicts.items()]
    # «Не может» — только у новых копий и у копий, у которых сменился источник, зато все их уроки:
    # до отметки курс был обычным (или стоял в часы другого потока), и предупреждения о нём здесь
    # не было, даже если урок уже стоял там же. Уроки копий с прежним источником отметка не двигает
    before = jointCopies(settings)
    fresh = {name: origin for name, origin in copies.items() if before.get(name) != origin}
    question += cannotParagraphs(marked, copyCannot(marked, scheduled, fresh), "web.classes.joint_cannot", line=line)

    if question and not force:
        # Версия сохраняется, только когда уроки в расписании пропадают или меняются (ниже)
        return {"confirm": "\n\n".join(question + ([translate("web.classes.joint_version")] if changed else []))}

    if changed:
        what = (tr("web.version.joint", line=line, stream=section, number=source) if source is not None
                else tr("web.version.joint_off", line=line, stream=section))
        saveBeforeVersion(project, settings, answer, what)

    # Настройки первыми: по ним saveAnswer ставит копиям уроки источника
    saveSettings(project, marked)
    saveAnswer(project, scheduled, marked)
    clearVariants(projectPath(project), str(section))

    if source is None:
        return {"message": tr("web.classes.joint_off", line=line, number=section)}

    return {"message": tr("web.classes.joint_on", line=line, stream=section, number=source)}


@action(blocking=True)
def setHours(project, course, subject, hours):
    """Число уроков курса в неделю.

    Не больше одного урока в день, поэтому максимум — число дней, в которые в сетке есть уроки.
    У идущего курса нельзя сделать меньше уроков, чем уже стоит в расписании.
    У зафиксированного курса (идёт и все уроки стоят, courses.courseLocked) число уроков
    не меняется вовсе — страница это поле у него не показывает, отказ ловит устаревшую
    вкладку. То же число, что уже записано, принимается (ничего не меняется).
    Лишние закреплённые уроки (если их стало больше, чем уроков) отбрасываются.

    У курса-копии число уроков не меняется (project.requireOwnCourse): его задаёт источник, а новое число
    источника копия получит при записи. Поэтому «идёт» и «зафиксирован» у источника проверяются
    по всей группе «источник + копии».
    """
    settings = loadSettings(project)
    requireOwnCourse(settings, course, subject)
    answer = loadAnswer(project)

    days = sum(1 for times in dayGrid(settings) if times)
    hours = number(hours, 1, max(days, 1))

    # Идущий курс сохраняет уже стоящие уроки: уменьшить число ниже них нельзя
    placed = len(courseSlots(answer, course, subject))

    if sharedStarted(settings, answer, course, subject) and hours < placed:
        raise UserError(tr("web.error.hours_below_started", lessons=lessonsText(placed)))

    # Уменьшение у зафиксированного курса уже отклонено выше понятным «меньше нельзя»;
    # здесь — увеличение: оно перевело бы курс в «идёт, не хватает уроков»
    if sharedLocked(settings, answer, course, subject) and hours != courseHours(settings, course, subject):
        raise UserError(translate("web.error.course_locked"))

    lessons(settings).setdefault(course, {})[subject] = hours

    # Закреплённых уроков не может быть больше, чем уроков у курса
    pins = pinnedSlots(settings, course, subject)

    if len(pins) > hours:
        setPinnedSlots(settings, course, subject, pins[:hours])

    saveSettings(project, settings)


# ---------------------------------------------------------------- преподаватель курса

def conflictText(settings, teacher, conflicts):
    """Текст «почему преподаватель не может взять уроки курса»: по строке на каждое время
    (занят на другом курсе / отметил «не может») или строка о превышении лимита курсов.

    conflicts — список (день, урок, причина, подробность) из courses.teacherConflicts;
    причина "limit" — подробность = сколько курсов у него уже есть.
    """
    lines = []

    for day, lesson, reason, detail in conflicts:
        if reason == "limit":
            lines.append(tr("menu.main.tab.classes.conflict_limit", count=detail, limit=teacherLimit(settings)))

        else:
            text = tr("menu.main.tab.classes.conflict_busy", course=detail) if reason == "busy" else translate("menu.main.tab.classes.conflict_unavailable")
            lines.append(f"{slotText(settings, day, lesson)}: {text}")

    return tr("menu.main.tab.classes.conflicts", teacher=teacher) + "\n\n" + "\n".join(dict.fromkeys(lines))


def checkStartedCourseTeacher(answer, course, teacher):
    """Идущему курсу («курс уже идёт») преподавателя не меняют: назначить можно только курсу,
    у которого в расписании нет преподавателя, и только кого-то (снять закрепление нельзя).
    """
    if any(entry.get("teachers") for _, _, entry in lessonEntries(answer, course)):
        raise UserError(translate("web.error.course_locked"))

    if not teacher:
        raise UserError(translate("web.error.course_locked_teacher"))


def checkSubjectTeacher(settings, course, subject, teacher):
    """Назначить можно только преподавателя этого предмета, которому не запрещён этот курс."""
    if teacher and teacher not in subjectTeachers(settings, subject, course):
        raise UserError(tr("web.error.not_subject_teacher", teacher=teacher, subject=subject))


def confirmStartedCourseTeacher(project, settings, answer, course, subject, teacher, force):
    """Вопрос перед назначением преподавателя идущему курсу.

    Идущий курс нельзя построить заново, поэтому кандидат обязан быть свободен во все его уроки
    (иначе — notice с причинами), а выбор окончательный: без force — вопрос, с force — версия
    «Перед: …». Возвращает ответ действия (notice / вопрос) или None, если можно назначать.
    """
    busy = teacherConflicts(settings, answer, course, subject, teacher)

    if busy:
        return {"notice": conflictText(settings, teacher, busy) + "\n\n" + translate("web.classes.locked_pick_other")}

    if not force:
        return {"confirm": tr("web.confirm_assign_started", teacher=teacher, course=course), "yes": translate("web.assign_yes")}

    saveBeforeVersion(project, settings, answer, tr("web.version.assign", teacher=teacher, course=course))

    return None


def replaceScheduledTeacher(project, settings, answer, course, subject, teacher):
    """Ставит преподавателя на уроки курса, уже стоящего в расписании ``answer``, если он свободен во все их.

    Замена идёт и в расписании, и в вариантах этапа — чтобы принятие варианта не вернуло
    прежнего преподавателя. Возвращает список помех (courses.teacherConflicts): пустой —
    замена сделана (``answer`` изменён и записан), иначе расписание не тронуто.
    """
    conflicts = teacherConflicts(settings, answer, course, subject, teacher)

    if conflicts:
        return conflicts

    replaceTeacherInAnswer(answer, course, subject, teacher)
    saveAnswer(project, answer)

    def replace(variant):
        """Ставит нового преподавателя на уроки курса в варианте; True — курс в варианте есть."""
        if course not in variant:
            return False

        replaceTeacherInAnswer(variant, course, subject, teacher)
        return True

    rewriteVariants(project, settings, replace, [stageKey(requireCourse(settings, course))])

    return []


@action(blocking=True)
def setTeacher(project, course, subject, teacher=None, force=False):
    """Закрепляет за курсом преподавателя (teacher=None — снять закрепление).

    Обычный курс: закрепление пишется в настройки. Если курс уже стоит в расписании и новый
    преподаватель свободен во все его уроки — он сразу заменяет прежнего и в расписании,
    и в вариантах этапа (replaceScheduledTeacher). Если не свободен — без force вопрос
    «закрепить всё равно?» (тогда расписание не меняется, учтётся при следующей сборке).

    Идущий курс («курс уже идёт»): менять преподавателя нельзя, можно только назначить его
    курсу, который остался без преподавателя (checkStartedCourseTeacher), и только свободного,
    с вопросом и версией «Перед: …» (confirmStartedCourseTeacher).

    Курс-копия: отказ web.error.joint_locked (меняется только у Потока N; project.requireOwnCourse).
    Курс-источник: «идёт» по всей группе «источник + копии», а новый преподаватель его уроков переходит
    в копии при записи расписания.
    """
    settings = loadSettings(project)
    requireOwnCourse(settings, course, subject)
    answer = loadAnswer(project)
    started = sharedStarted(settings, answer, course, subject)

    if started:
        checkStartedCourseTeacher(answer, course, teacher)

    checkSubjectTeacher(settings, course, subject, teacher)

    if started:
        reply = confirmStartedCourseTeacher(project, settings, answer, course, subject, teacher, force)

        if reply:
            return reply

    # Запрещённого преподавателя сюда не пропустит проверка checkSubjectTeacher выше
    setCourseTeacher(settings, course, subject, teacher)
    message = None

    if teacher and courseSlots(answer, course, subject):
        conflicts = replaceScheduledTeacher(project, settings, answer, course, subject, teacher)

        if not conflicts:
            message = tr("menu.main.tab.classes.replaced", teacher=teacher)

        elif not force:
            return {"confirm": conflictText(settings, teacher, conflicts) + "\n\n" + translate("menu.main.tab.classes.keep_anyway")}

    saveSettings(project, settings)

    return {"message": message} if message else {}


# ---------------------------------------------------------------- закреплённые уроки

def pinsFromForm(slots):
    """Закрепления из формы как [(день, урок)] целыми числами.

    Страница присылает пары чисел; строки из цифр («2») тоже принимаются. Не пара или не
    число — «нет такого урока»: со строками в местах уроков сравнение мест (plannedMoves)
    молча ошибалось бы.
    """
    try:
        pins = [(int(day), int(lesson)) for day, lesson in slots]

    except (TypeError, ValueError):
        raise UserError(translate("web.error.no_slot"))

    return pins


def checkPins(settings, course, subject, pins):
    """Проверяет закрепления (``pinsFromForm``): только существующие ячейки сетки, не больше одного
    урока в день и не больше, чем уроков у курса в неделю. Возвращает число уроков курса в неделю.

    Повтор ячейки отдельно не проверяется: два одинаковых закрепления — это два урока в один
    день, их отсекает проверка «один урок в день».
    """
    if any(not lessonExists(settings, day, lesson) for day, lesson in pins):
        raise UserError(translate("web.error.no_slot"))

    if len({day for day, _ in pins}) != len(pins):
        raise UserError(translate("web.error.pins_same_day"))

    # Курс без записанной нагрузки (или с нулём уроков) считается курсом с одним уроком
    hours = max(1, courseHours(settings, course, subject))

    # Закреплений не больше, чем уроков у курса в неделю (окно на странице и так не даёт больше)
    if len(pins) > hours:
        raise UserError(tr("web.error.pins_too_many", lessons=lessonsText(hours)))

    return hours


def slotConflictsQuestion(settings, conflicts):
    """Вопрос «закрепить всё равно?», когда закреплённые места в расписании заняты."""
    text = translate("menu.main.tab.classes.slot_conflicts") + "\n\n" + "\n".join(conflictLines(settings, conflicts))

    return {"confirm": text + "\n\n" + translate("menu.main.tab.classes.keep_pins_anyway"), "yes": translate("web.pin_yes")}


@action(blocking=True)
def setPins(project, course, subject, slots, force=False):
    """Закрепляет уроки курса за днями и временем. slots — список [день, урок].

    Правила (checkPins): только существующие ячейки сетки, не больше одного урока в день
    и не больше, чем уроков у курса; у идущего курса закрепления менять нельзя. Если курс уже
    стоит в расписании, его уроки переносятся на закреплённые места (courses.plannedMoves —
    остальные остаются где были), когда эти места свободны. Если нет — без force вопрос
    «закрепить всё равно?» (расписание тогда не меняется, закрепление учтёт следующая сборка).

    Курс-копия: отказ web.error.joint_locked (меняется только у Потока N; project.requireOwnCourse).
    Курс-источник: «идёт» по всей группе «источник + копии»; его перенесённые уроки переходят в копии
    при записи расписания, а помехи
    ищутся и у соседей копий (courses.slotConflicts).
    """
    settings = loadSettings(project)
    requireOwnCourse(settings, course, subject)
    answer = loadAnswer(project)

    if sharedStarted(settings, answer, course, subject):
        raise UserError(translate("web.error.course_started_pins"))

    pins = pinsFromForm(slots)
    hours = checkPins(settings, course, subject, pins)
    setPinnedSlots(settings, course, subject, pins)
    current = courseSlots(answer, course, subject)
    moves = plannedMoves(current, pins, hours)[0] if current else []
    message = None

    # Курс уже в расписании: переносим его уроки на закреплённые места, если там свободно
    if moves:
        conflicts = slotConflicts(settings, answer, course, subject, moves)

        if not conflicts:
            moveLessons(answer, course, moves)
            saveAnswer(project, answer)
            message = translate("menu.main.tab.classes.moved")

        elif not force:
            return slotConflictsQuestion(settings, conflicts)

    saveSettings(project, settings)

    return {"message": message} if message else {}
