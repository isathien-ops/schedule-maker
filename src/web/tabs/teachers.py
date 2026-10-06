"""Вкладка «Преподаватели»: преподаватели и их предметы, отметки доступности «удобно / может /
не может» по этапам, отношение к курсам и карточка преподавателя (GET /api/project/<p>/teacher).
Пара на странице — static/tabs/teachers.js.

Расчёт карточки преподавателя — в src/modules/functions/teacher_card.py; маршрут здесь
только проверяет, что преподаватель есть, и отдаёт карточку.

Курс-копия линейки, которая идёт вместе с Потоком N (.spec/joint-lines/SPEC.md): его отношение
к преподавателю не меняется (cycleCourse — отказ web.error.joint_locked, project.requireOwnCourse), а его уроки — это уроки
источника, поэтому в вопросах об уроках преподавателя они не считаются второй раз (lessonCourses).
Клетка общего урока в сетке доступности не меняется, кроме одного: оставшееся под ней «не может»
снимается щелчком (cycleAvailability) — иначе предупреждение «Расписания» о таком уроке не убрать.
Так же и клетка своего урока идущего курса («уже идёт»): новую отметку там не поставить, а «не может»,
оставшееся с тех пор, когда курс ещё не шёл, снимается щелчком — иначе сборка переносила бы этот урок.

Зависимости: actions (@action), core (app, LOCK, UserError), project (файлы проекта, проверки
аргументов, версия «Перед: …», переписывание вариантов, формулировки) и предметные модули
(model, courses, joint, grid, stages, penalties, teacher_card).
"""

import copy

from flask import jsonify, request

from src.modules.translate import tr, translate
from src.modules.functions.courses import nextTeacherCourseState, setTeacherCourseState, setTeacherSubjects, teacherCourseState
from src.modules.functions.grid import lessonExists
from src.modules.functions.joint import jointCopies
from src.modules.functions.model import hasLessons, lessonEntries, stageKey, teacherAvailability, teacherLessons
from src.modules.functions.penalties import dropTargeted
from src.modules.functions.stages import teacherCommitments
from src.modules.functions.teacher_card import teacherCard
from src.web.actions import action
from src.web.core import LOCK, UserError, app
from src.web.project import (
    bullets, lessonsText, loadAnswer, loadSettings, requireOwnCourse, requireStage, requireSubjects, requireTeacher, rewriteVariants,
    saveAnswer, saveBeforeVersion, saveSettings
)


# Действия вкладки «Преподаватели»

def lessonCourses(settings, answer, name, except_subjects=None):
    """Курсы уроков преподавателя ``name`` в расписании — по элементу на каждый его урок
    (уроки предметов ``except_subjects`` не считаются, см. model.teacherLessons).

    Уроки курсов-копий не считаются: это те же уроки источника, преподаватель ведёт их один раз,
    и копия следует за источником сама (joint.syncJointAnswer при записи расписания).
    """
    copies = jointCopies(settings)

    return [course for course, *_ in teacherLessons(answer, name, except_subjects) if course not in copies]


@action(blocking=True)
def newTeacher(project, name, subjects):
    """Новый преподаватель с предметами `subjects` и пустыми отметками доступности."""
    name = (name or "").strip()
    settings = loadSettings(project)
    requireSubjects(settings, subjects)

    if not name:
        raise UserError(translate("web.error.teacher_name_empty"))

    if name in settings["teachers"]:
        raise UserError(translate("web.error.teacher_name_exists"))

    settings["teachers"][name] = {"subjects": [], "availability": {}}
    setTeacherSubjects(settings, name, subjects)
    saveSettings(project, settings)


@action(blocking=True)
def teacherSubjects(project, name, subjects, force=False):
    """Меняет список предметов преподавателя.

    Если у него в принятом расписании есть уроки по предмету, который убирают, — без force
    вопрос; с force эти уроки остаются без преподавателя (dropTeacherLessons, с версией «Перед: …»).
    """
    settings = loadSettings(project)
    requireSubjects(settings, subjects)
    requireTeacher(settings, name)

    # Уроки убранных предметов, которые он ведёт в принятом расписании, останутся без преподавателя
    # (сначала спрашиваем). dropped — по элементу на каждый такой урок
    answer = loadAnswer(project)
    dropped = lessonCourses(settings, answer, name, except_subjects=subjects)

    if dropped and not force:
        return {"confirm": tr("web.confirm_drop_subject", name=name, count=lessonsText(len(dropped)), courses=bullets(dropped)),
                "danger": True, "yes": translate("web.drop_subject_yes")}

    dropTeacherLessons(project, settings, answer, name, tr("web.version.drop_subject", name=name), keep_subjects=subjects)

    setTeacherSubjects(settings, name, subjects)
    saveSettings(project, settings)


def dropTeacherLessons(project, settings, answer, name, action, keep_subjects=None):
    """Снимает преподавателя `name` с его уроков в расписании и во всех построенных вариантах.

    action — описание для версии «Перед: …», которая сохраняется, если расписание меняется.
    keep_subjects — уроки этих предметов остаются за ним (используется, когда из его списка
    убирают только часть предметов); None — снимаются все уроки.
    `answer` меняется на месте и записывается в answer.json.
    """
    def drop(weeks):
        """Убирает преподавателя из уроков словаря {курс: неделя} на месте; True — что-то изменилось."""
        lessons = list(teacherLessons(weeks, name, keep_subjects))

        for *_, entry in lessons:
            entry["teachers"] = [teacher for teacher in entry["teachers"] if teacher != name]

        return bool(lessons)

    # Варианты, где он стоит, вернули бы его при принятии — чистим и их
    rewriteVariants(project, settings, drop)

    # Сначала пробуем на копии: версия нужна, только если расписание действительно изменится,
    # и сохранить её надо ДО изменения
    if drop(copy.deepcopy(answer)):
        saveBeforeVersion(project, settings, answer, action)
        drop(answer)
        saveAnswer(project, answer)


@action(blocking=True)
def deleteTeacher(project, name, force=False):
    """Удаляет преподавателя: всегда сначала вопрос (с перечнем курсов, где он ведёт уроки).
    Преподавателя уже нет (удалён в другой вкладке) — понятная ошибка, а не вопрос.

    С force: его уроки в расписании и вариантах остаются без преподавателя (с версией
    «Перед: …»), он удаляется из настроек вместе с правилами, нацеленными на него.
    """
    settings = loadSettings(project)
    requireTeacher(settings, name)
    answer = loadAnswer(project)
    lessons = lessonCourses(settings, answer, name)

    if not force:
        if not lessons:
            return {"confirm": tr("web.confirm_delete_teacher", name=name), "danger": True, "yes": translate("web.common.delete")}

        return {"confirm": tr("web.confirm_delete_teacher_lessons", name=name, count=lessonsText(len(lessons)), courses=bullets(lessons)),
                "danger": True, "yes": translate("web.common.delete")}

    dropTeacherLessons(project, settings, answer, name, tr("web.version.delete_teacher", name=name))

    settings["teachers"].pop(name, None)
    dropTargeted(settings, "teacher", [name])
    saveSettings(project, settings)


@action(blocking=True)
def cycleAvailability(project, name, stage, day, lesson):
    """Клик по клетке сетки доступности преподавателя на этапе `stage`.

    По кругу: «удобно» (нет отметки) -> «может» (список "possible") -> «не может»
    (список "free"; смысл ключей — в model.teacherAvailability) -> «удобно».
    Клетки, занятые уроками других этапов или закреплёнными уроками его курсов
    (teacherCommitments), и несуществующие ячейки не меняются.
    Исключение — общий урок с более ранним потоком (вид "joint"), под которым стоит «не может»
    (отметку поставили раньше, чем туда встали уроки): клик снимает её, иначе предупреждение
    «Расписания» про такой урок (joint.copyCannot) не убрать. Новую отметку там поставить нельзя.
    Так же и свой урок идущего курса этого этапа (клетка «уже идёт», teacherCard → own): время
    такого урока не меняют, а оставшееся «не может» (поставили до начала курса) щелчок снимает —
    иначе каждое новое составление переносило бы этот урок.
    """
    settings = loadSettings(project)
    requireStage(settings, stage)
    requireTeacher(settings, name)

    if not lessonExists(settings, day, lesson):
        return

    availability = teacherAvailability(settings["teachers"][name], stage)
    pos = [day, lesson]
    answer = loadAnswer(project)
    commitment = teacherCommitments(settings, answer, name, stage).get((day, lesson))

    # Занятая клетка не меняется; под общим уроком только снимается «не может» (ветка ниже)
    if commitment is not None and (commitment[0] != "joint" or pos not in availability["free"]):
        return

    # Свой урок идущего курса: тоже только снимается «не может»
    started = any(item[:2] == pos and item[3] for item in teacherCard(settings, answer, name, stage)["own"])

    if started and pos not in availability["free"]:
        return

    if pos in availability["free"]:
        availability["free"].remove(pos)

    elif pos in availability["possible"]:
        availability["possible"].remove(pos)
        availability["free"].append(pos)

    else:
        availability["possible"].append(pos)

    saveSettings(project, settings)


@action(blocking=True)
def copyAvailability(project, source, target, name=None):
    """Отметки «удобно / может / не может» этапа `source` становятся отметками этапа `target`.

    name — только для одного преподавателя; None — для всех. Отметки копируются глубоко,
    чтобы этапы потом менялись независимо. Неизвестный преподаватель (например, удалён в другой
    вкладке) — отказ web.error.no_teacher, как у остальных действий вкладки, а не «скопированы»
    без копирования; проверка стоит до сравнения этапов, чтобы отказ был и при одинаковых.
    """
    settings = loadSettings(project)
    requireStage(settings, source)
    requireStage(settings, target)

    if name:
        requireTeacher(settings, name)

    names = [name] if name else list(settings["teachers"])

    # Копировать этап сам в себя нечего
    if source != target:
        for teacher in names:
            data = settings["teachers"][teacher]
            marks = teacherAvailability(data, source)
            data["availability"][target] = {"free": copy.deepcopy(marks["free"]), "possible": copy.deepcopy(marks["possible"])}

    saveSettings(project, settings)

    return {"message": translate("web.teachers.copied")}


@action(blocking=True)
def cycleCourse(project, name, subject, course):
    """Клик по курсу в карточке преподавателя: следующее состояние его отношения к курсу.

    По кругу: не ведёт -> может вести (выбирает программа) -> ведёт (закреплён) ->
    запрещено -> не ведёт.
    Если в принятом расписании он уже ведёт этот курс — отказ: это меняется на вкладке
    «Курсы» или новой сборкой этапа. Состояние «ведёт» пропускается для курса, который уже
    стоит в расписании: его преподавателя меняют на «Курсах», где это сверяется с расписанием.
    Курс-копия — отказ web.error.joint_locked (меняется только у Потока N): преподаватель у неё тот же,
    что у курса-источника.
    Запрещённый курс снимается с него и в построенных вариантах этапа: иначе принятие варианта,
    собранного до запрета, поставило бы его на этот курс (сборка могла выбрать его сама).
    """
    settings = loadSettings(project)
    requireTeacher(settings, name)
    group = requireOwnCourse(settings, course, subject)

    answer = loadAnswer(project)

    # В принятом расписании он этот курс ведёт: меняется на «Курсах» или новой сборкой этапа
    if course in lessonCourses(settings, answer, name):
        raise UserError(translate("web.error.course_scheduled"))

    new_state = nextTeacherCourseState(teacherCourseState(settings, name, subject, course))

    # Курсу из принятого расписания другого преподавателя назначают на «Курсах», где это
    # проверяется по расписанию — здесь «ведёт» пропускаем
    if new_state == "assigned" and hasLessons(answer, course):
        new_state = nextTeacherCourseState(new_state)

    setTeacherCourseState(settings, name, subject, course, new_state)
    saveSettings(project, settings)

    def drop(variant):
        """Снимает его с уроков курса в варианте на месте; True — что-то изменилось."""
        cells = [cell for _, _, cell in lessonEntries(variant, course) if name in cell.get("teachers", [])]

        for cell in cells:
            cell["teachers"] = [teacher for teacher in cell["teachers"] if teacher != name]

        return bool(cells)

    if new_state == "forbidden":
        rewriteVariants(project, settings, drop, [stageKey(group)])


@app.route("/api/project/<project>/teacher")
def teacherDetails(project):
    """Карточка одного преподавателя на этапе: сетка доступности и его курсы.

    Параметры адреса: name — преподаватель, stage — этап, выбранный на странице (он задаёт только
    сетку доступности; курсы показываются всех этапов). Поля ответа — в teacher_card.teacherCard.
    Преподавателя нет (например, удалён в другой вкладке) — понятная ошибка.
    """
    name, stage = request.args.get("name"), request.args.get("stage")

    with LOCK:
        settings = loadSettings(project)
        requireTeacher(settings, name)

        return jsonify(teacherCard(settings, loadAnswer(project), name, stage))
