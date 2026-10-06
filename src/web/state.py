"""Что видит страница: полное состояние открытого проекта (state) и сводки по этапам.

Только чтение: ничего не записывает и LOCK сам не берёт — его вызывают уже под блокировкой
(после действия, при открытии проекта, по GET /api/project/<p>).

state() собирает ответ из частей, по функции на раздел страницы: sectionsInfo (разделы
вкладки «Курсы»), courseInfo (строка курса), stagesInfo (этапы вкладки «Запуск») и waitingLines
(линейки этапа, которые ждут поток-источник), noTeacherCourses и staffing (предупреждения над
расписанием), teachersInfo (список преподавателей).

«Линейка идёт вместе с Потоком N» (функции модуля joint): у раздела — какие потоки можно выбрать
и с каким идёт линейка, у курса-копии — её источник и «ждёт», у источника — потоки-копии. Копия
показывает часы, преподавателя и уроки источника, а выбор преподавателя и закрепления у неё пусты:
всё это меняется у источника. В «уроки без преподавателя» копии не попадают — там уже их источник.
Общий урок во время, где у преподавателя на этапе потока-копии «не может», — предупреждение
jointCannot над расписанием (joint.copyCannot).

Зависимости: project (файлы проекта), build (ход сборки и параметры по умолчанию, только как
модуль) и предметные модули. datetime импортируется модулем: тесты подменяют datetime.date.
"""

import datetime

import natsort

from src.variables import DEFAULT_WEIGHTS
from src.modules.translate import translate
from src.modules.functions.courses import (
    BLOCKS, DEFAULT_EXTRA_LINES, DEFAULT_LINES, copyRoot, courseHours, courseLabel, courseLocked, courseStarted, courseTeachers,
    lineOf, pinnedSlots, sectionEnd, sectionLines, sectionStart, sharedCourses, streamIds, subjectTeachers, teacherConflicts, teacherLimit
)
from src.modules.functions.files import readJson
from src.modules.functions.grid import MAX_LESSONS_PER_DAY, dayGrid
from src.modules.functions.joint import copyCannot, jointCopies, jointOptions, lineJoint
from src.modules.functions.model import (
    EXTRA_BLOCK, courseGroups, courseSlots, courseSubject, groupsByName, hasLessons, isBlock, lessonEntries, sectionOf,
    stageKey
)
from src.modules.functions.pairs import subjectPairState
from src.modules.functions.penalties import describePenalty, penalties
from src.modules.functions.solver_input import keepCourses, pinForecast
from src.modules.functions.stages import (
    allStarted, blockedStarted, countedCourses, getStages, pinContext, stageBuilt, stageDates, stageLabel, stageTotals, teacherClashes
)
from src.modules.functions.staffing import staffing
from src.modules.functions.variants import loadVariants, waitingCopies
from src.modules.functions.versions import lessonCount, listVersions
from src.web import build
from src.web.project import loadAnswer, loadSettings, loadWeights, movedStartedItems, projectPath


def busyOptions(settings, answer, course, subject):
    """Преподаватели предмета, которых нельзя поставить на уроки курса как они есть.

    Имеет смысл только для курса, который уже стоит в расписании, но остался без преподавателя
    (например, его прежнего преподавателя удалили). Страница показывает таких кандидатов
    отдельно с пометкой «сейчас назначить нельзя»: у них в это время другие уроки, отметка
    «не может» или они уже ведут максимум курсов (все причины courses.teacherConflicts).
    Для остальных курсов — пустой список.
    """
    if not courseSlots(answer, course, subject) or any(entry.get("teachers") for _, _, entry in lessonEntries(answer, course)):
        return []

    return [name for name in subjectTeachers(settings, subject, course) if teacherConflicts(settings, answer, course, subject, name)]


# ---------------------------------------------------------------- состояние проекта для страницы

def sectionTitle(settings, section):
    """Заголовок раздела вкладки «Курсы»: (название, даты).

    Для потока — «Поток N», для блока — его перевод (stage.extra и т.п.). Даты — «дд.мм.гггг – дд.мм.гггг»;
    если дата не задана или записана неверно, вторая часть пустая.
    """
    name = stageLabel(str(section), translate)

    try:
        start = datetime.date.fromisoformat(sectionStart(settings, section))
        end = datetime.date.fromisoformat(sectionEnd(settings, section))

        return name, f"{start:%d.%m.%Y} – {end:%d.%m.%Y}"

    except ValueError:
        return name, ""


def courseInfo(settings, answer, group, copies):
    """Всё, что странице нужно знать об одном курсе (строка таблицы на вкладке «Курсы»).

    `group` — элемент `classes.custom_groups`. У курса в этой школе один предмет — берётся первый.
    `copies` — joint.jointCopies ({копия: источник}), прочитанные один раз на все курсы.
    Поля ответа:
      short — короткая подпись «Поток 2, ЕГЭ основной, Математика» (courses.courseLabel): страница
          берёт её готовой и не разбирает название курса;
      assigned / scheduled / candidates / forbidden — закреплённый преподаватель, преподаватель
          в принятом расписании, допустимые кандидаты, запрещённые (см. courses.courseTeachers);
      options     — кому можно назначить курс вручную;
      slots       — [день, урок] уроков курса в принятом расписании;
      locked / started — «курс зафиксирован» / «курс уже идёт». У курса-источника — по всей группе
          «источник + копии» (как courses.sharedLocked / sharedStarted, которыми сервер отказывает
          в правках): если ученики присоединённого потока уже ходят, уроки источника — это и их
          уроки, менять их нельзя, даже когда свой поток источника ещё не начался. У копии и
          обычного курса — только он сам;
      runningSince — с какой даты идут уроки курса (самое раннее начало среди идущих курсов той же
          группы) или "" — курс не идёт. У источника, который идёт только через копию, это начало
          потока-копии, а не своё ``start``: его страница пишет в подсказке «Курс идёт с …»;
      busyOptions — преподаватели предмета, которых нельзя поставить на уроки курса: заняты,
          отметили «не может» или упрутся в лимит курсов (см. busyOptions);
      pinned      — закреплённые уроки [день, урок];
      joint       — у курса-копии {number, stage, source, waiting}: номер и этап потока-источника,
          имя курса-источника и «ждёт Поток N» (у источника нет уроков); у остальных курсов None.
          Часы, преподаватель в расписании и уроки копии — источника, а «ведёт», кандидаты,
          выбор преподавателя и закрепления пусты: на странице эти поля копии закрыты;
      jointWith   — номера потоков, курсы-копии которых идут вместе с этим курсом (у источника).
    """
    name = group["name"]
    subject = courseSubject(group)
    # Курс, который отвечает за уроки (как joint.jointRoot): у копии — источник
    source = copyRoot(copies, name)
    teachers = courseTeachers(settings, answer, source, subject)
    by_name = groupsByName(settings)
    # Чьи уроки — уроки этого курса: у источника вся группа «источник + копии», у копии и обычного
    # курса — он сам (копия закрыта на странице и так, а её «идёт» нужно шапке линейки)
    members = sharedCourses(copies, name) if source == name else [name]
    running = [member for member in members if courseStarted(settings, answer, member, subject)]

    info = {
        "name": name,
        "short": courseLabel(group),
        "section": sectionOf(group),
        "stage": stageKey(group),
        "line": lineOf(group),
        "subject": subject,
        "hours": courseHours(settings, source, subject),
        "scheduled": teachers["scheduled"],
        "slots": [list(slot) for slot in courseSlots(answer, source, subject)],
        # «Курс зафиксирован»: идёт, стоит в принятом расписании и все уроки на месте —
        # преподаватель и время не меняются
        "locked": any(courseLocked(settings, answer, member, subject) for member in members),
        "started": bool(running),
        "runningSince": min((by_name[member].get("start_date") or "" for member in running), default=""),
        "start": group.get("start_date", ""),
        "joint": None if source == name else {
            "number": group["together_with"], "stage": stageKey(by_name[source]), "source": source,
            "waiting": not hasLessons(answer, source),
        },
        "jointWith": sorted(by_name[other]["stream_id"] for other, origin in copies.items() if origin == name),
    }

    # Копию меняют только через источник: выбирать и закреплять у неё нечего
    if source != name:
        return dict(info, assigned=[], candidates=[], forbidden=[], options=[], busyOptions=[], pinned=[])

    return dict(
        info,
        assigned=teachers["assigned"],
        candidates=teachers["candidates"],
        forbidden=teachers["forbidden"],
        # Преподаватели, которым курс запрещён, не предлагаются
        options=subjectTeachers(settings, subject, name),
        busyOptions=busyOptions(settings, answer, name, subject),
        pinned=[list(slot) for slot in pinnedSlots(settings, name, subject)],
    )


def sectionsInfo(settings):
    """Разделы вкладки «Курсы»: сначала потоки по порядку, затем блоки (доп. курсы, май, лето).

    "suggested" — названия линеек, которые страница предлагает добавить одной кнопкой.
    "joint" — {линейка: N} для линеек, которые идут вместе с Потоком N; "jointOptions" —
    {линейка: [N…]}: какие потоки можно выбрать в «Присоединяется к» (joint.jointOptions; у блоков,
    у Потока 1 и у линейки, которой нет в более ранних потоках или в которой там нет ни одного
    такого же предмета, список пуст).
    """
    sections = []

    for section in streamIds(settings) + list(BLOCKS):
        name, dates = sectionTitle(settings, section)
        lines = sectionLines(settings, section)
        joint = {line: lineJoint(settings, section, line) for line in lines}
        sections.append({
            "key": section, "name": name, "dates": dates, "block": isBlock(section),
            "start": sectionStart(settings, section), "end": sectionEnd(settings, section),
            "lines": lines,
            "suggested": DEFAULT_EXTRA_LINES if section == EXTRA_BLOCK else DEFAULT_LINES,
            "joint": {line: number for line, number in joint.items() if number is not None},
            "jointOptions": {line: jointOptions(settings, section, line) for line in lines},
        })

    return sections


def stagesInfo(settings, answer, path):
    """Этапы для вкладки «Запуск» в порядке getStages.

    У каждого: сколько уроков нужно (expected) и сколько уже стоит (placed) — у курсов, уроки которых
    этап ставит сам (stages.countedCourses: без копий, их ставит поток-источник), сколько вариантов
    построено, даты, built — «этап построен» (stages.stageBuilt — то же, что на стартовом экране),
    allStarted — сборке нечего менять: все курсы этапа зафиксированы (идут и все их уроки на месте)
    или это копии, уроки которых ставит поток-источник (stages.allStarted); верен и для этапа из
    одних копий. Идущий курс, которому не хватает уроков,
    сюда не относится — для него сборка ещё нужна.

    forecast — сколько уроков закрепит сборка (solver_input.pinForecast) с галочкой «Оставить
    уже принятые уроки на месте» (keep) и без неё (fresh): страница пишет это у галочки.
    Уроки идущих курсов закрепляются и без галочки.

    waiting — линейки этапа, курсы-копии которых ждут поток-источник (waitingLines): страница
    пишет на «Запуске», что эти уроки встанут, когда у курсов-источников появятся уроки в расписании.

    blockedStarted — уроки идущих курсов, которые сборка не сможет оставить как в расписании — на месте и с тем же
    преподавателем (stages.blockedStarted),
    [{"course", "lines"}] как movedStarted у вариантов (project.movedStartedItems): «Запуск» заранее
    предупреждает, что такие варианты принять будет нельзя, и называет причины.
    И это, и прогноз берут помехи закреплениям из одного stages.pinContext этапа: его сборка — самая
    долгая часть состояния, а состояние отдаётся после каждого действия. Контекст — свежей сборки и для
    прогноза с галочкой (редкий случай, когда тот выйдет меньше, — в solver_input.pinForecast).
    """
    stages = []
    copies = jointCopies(settings)

    for stage in getStages(settings):
        expected, placed = stageTotals(settings, answer, countedCourses(settings, stage["key"], copies))
        context = pinContext(settings, answer, stage["key"])
        stages.append({
            "key": stage["key"], "label": stageLabel(stage["key"], translate), "courses": stage["courses"],
            "built": stageBuilt(settings, answer, stage["key"]), "variants": len(loadVariants(path, stage["key"])),
            "expected": expected, "placed": placed, "dates": list(stageDates(settings, stage["key"])),
            "allStarted": allStarted(settings, answer, stage["key"]),
            "waiting": waitingLines(settings, answer, stage["key"]),
            "blockedStarted": movedStartedItems(settings, blockedStarted(settings, answer, stage["key"], context)),
            "forecast": {
                "keep": pinForecast(settings, answer, stage["key"], keepCourses(settings, answer, stage["key"]), context),
                "fresh": pinForecast(settings, answer, stage["key"], context=context),
            },
        })

    return stages


def waitingLines(settings, answer, stage):
    """Линейки этапа ``stage``, которые ждут свой поток-источник: [{line, number}] без повторов.

    Ждёт линейка, у курса-копии которой источник ещё без уроков (variants.waitingCopies).
    """
    groups = groupsByName(settings)
    lines = dict.fromkeys((lineOf(groups[name]), groups[name]["together_with"]) for name in waitingCopies(settings, answer, stage))

    return [{"line": line, "number": number} for line, number in lines]


def noTeacherCourses(settings, answer):
    """Курсы, у которых в расписании есть уроки без преподавателя: [курс, сколько таких уроков, дата начала].

    Преподаватель, которого уже нет в проекте, считается отсутствующим. Сначала курсы, которые
    начинаются раньше, при равных датах — по имени. Курсов-копий в списке нет: у них уроки
    источника, и преподавателя ставят ему.
    """
    known = set(settings.get("teachers", {}))
    starts = {group["name"]: group.get("start_date", "") for group in courseGroups(settings)}
    copies = jointCopies(settings)
    counts = {}

    for course in answer:
        if course in copies:
            continue

        for _, _, entry in lessonEntries(answer, course):
            if not [teacher for teacher in entry.get("teachers", []) if teacher in known]:
                counts[course] = counts.get(course, 0) + 1

    return sorted(([course, count, starts.get(course, "")] for course, count in counts.items()), key=lambda item: (item[2], item[0]))


def teachersInfo(settings, subjects):
    """Преподаватели по алфавиту (natsort: «Иванова 2» раньше «Иванова 10») с предметами,
    которые ещё есть в проекте (`subjects`).
    """
    return [
        {"name": name, "subjects": [item["subject"] for item in settings["teachers"][name].get("subjects", []) if item.get("subject") in subjects]}
        for name in natsort.natsorted(settings.get("teachers", {}))
    ]


def state(project):
    """Полное состояние проекта для страницы: по нему страница перерисовывает все вкладки.

    Отдаётся при открытии проекта, по GET /api/project/<p> и после каждого действия
    (поле "state" ответа). Ничего не записывает. Вызывать под LOCK, чтобы не прочитать
    файлы посреди чужой записи.
    """
    settings = loadSettings(project)
    answer = loadAnswer(project)
    path = projectPath(project)
    subjects = [name for name, _ in settings.get("subjects", []) if name]
    copies = jointCopies(settings)

    return {
        # Предупреждения над расписанием: «накладки» (у преподавателя два урока в одно время),
        # курсы с уроками без преподавателя и предметы, где у преподавателей не хватает
        # (или скоро не хватит) времени — «нужен ещё преподаватель»
        "clashes": [[teacher, day, lesson, courses] for teacher, day, lesson, courses in teacherClashes(settings, answer)],
        "noTeacher": noTeacherCourses(settings, answer),
        # Общие уроки во время, где у преподавателя на этапе потока-копии «не может» (joint.copyCannot):
        # не накладка и не запрет, а предупреждение — [преподаватель, день, урок, курс-копия]
        "jointCannot": [list(item) for item in copyCannot(settings, answer, copies)],
        "staffing": staffing(settings, answer),
        "grid": dayGrid(settings),
        "maxLessons": MAX_LESSONS_PER_DAY,
        "subjects": subjects,
        # Можно ли ставить уроки двух предметов одной линейки в одно время: разрешено / нежелательно / запрещено
        "pairs": {first: {second: subjectPairState(settings, first, second) for second in subjects if second != first} for first in subjects},
        "limits": {"max_courses_per_teacher": teacherLimit(settings)},
        "sections": sectionsInfo(settings),
        "courses": [courseInfo(settings, answer, group, copies) for group in courseGroups(settings)],
        "teachers": teachersInfo(settings, subjects),
        "stages": stagesInfo(settings, answer, path),
        "weights": loadWeights(project),
        # Обычные значения весов: от них считаются деления ползунков «Неважно … Очень важно»
        "weightDefaults": readJson(DEFAULT_WEIGHTS, {}),
        "iterations": settings.get("iterations", build.DEFAULT_ITERATIONS),
        # Деления ползунка «Тщательность» (шагов решателя на вариант)
        "iterationLevels": list(build.ITERATION_LEVELS),
        "variants": settings.get("variants", build.DEFAULT_VARIANTS),
        "penalties": [dict(item, description=describePenalty(item, translate)) for item in penalties(settings)],
        # Само принятое расписание и число уроков в нём (общий урок — один раз, как на «Расписании»);
        # список сохранённых версий; ход сборки.
        # handover — исходное расписание, которое передали вместе с программой (версия
        # «Передано руководителю», её сохраняет tools/create_school_project.py): перед её
        # удалением страница предупреждает особо
        "answer": answer,
        "lessons": lessonCount(answer, settings),
        "versions": [dict(meta, id=version, handover=meta.get("name") == translate("web.save.handover_name"))
                     for version, meta in listVersions(path)],
        "job": build.jobState(project),
    }
