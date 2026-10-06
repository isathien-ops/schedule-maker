"""Вход решателя (solve.exe) для одного этапа: ``buildStageSettings``.

Решатель получает настройки проекта в том же виде, что settings.json, но урезанные до курсов
одного этапа и дополненные служебными ключами. Уроки других этапов при этом неподвижны: они
становятся занятым временем преподавателей и запрещёнными слотами курсов.

Как собирается вход (по шагу на функцию):
1. ``stageOnly`` — только курсы этапа: их нагрузка и закреплённые уроки;
2. ``flattenAvailability`` — отметки преподавателей этапа плоскими списками «не может» /
   «может»; в «не может» добавляются уроки других этапов, закрепления других этапов и слоты,
   которых нет в сетке дня;
3. ``programBlockedSlots`` — слоты, где курсу нельзя стоять из-за программ, которые не
   пересекаются («Семинары» и «ЕГЭ продвинутый»), и «дыр» сетки;
4. ``pinStartedCourses`` — идущие курсы и курсы из «оставить принятое» (keep) сохраняют свои
   уроки и преподавателя; начавшиеся курсы без преподавателя решатель не получает вовсе.
   Что именно закрепляется, решает ``pinPlan``, а какие ручные закрепления остаются — ``plannedPins``;
   по ним же ``pinForecast`` заранее считает, сколько уроков закрепится и у скольких нет
   преподавателя (подпись у галочки на «Запуске» и строка журнала сборки);
5. ``blockFixedCourses`` — время таких выброшенных курсов и курсов-копий запрещается курсам,
   с которыми они не должны совпадать;
6. свои правила пользователя (penalties.compilePenalties) и пары курсов (правило «Пары — не в один день»)
   (``sameDayPairs``; нарушения этого правила в готовой неделе ищет variants.sameDayClashes);
7. ``priceFixedNeighbours`` — мягкие правила с неподвижными курсами (копии и выброшенные идущие
   курсы без преподавателя) ценами слотов их соседей;
8. ``keepTeacherCourses`` — источники общих уроков: их преподавателя решатель не меняет при подборе.

Курсы-копии («линейка идёт вместе с Потоком N», модуль joint) решатель не получает: их уроки
задаёт поток-источник, а в каждый вариант их переносит сборка (src/web/build.py). Свои уроки копии
сообщают решателю прежними ключами входа (новый ключ нужен только источникам — ``keep_teacher_courses``,
ниже):
* занятость преподавателя и лимит курсов — stages.occupiedByOtherStages (копии этапа там «уже стоят»);
* жёсткие пары и непересекающиеся программы — ``blocked_slots`` соседей (``blockFixedCourses``);
* мягкие правила («нежелательно», «уровни врозь», «пары не в один день») — цены слотов
  ``custom_penalties_compiled.class_slots`` с весами из weights.json (``priceFixedNeighbours``; так же
  и с выброшенными идущими курсами без преподавателя — их уроки тоже стоят, а решатель их не получает).
Преподаватель источника ведёт и копии, а его «не может» и занятость в потоке-копии решатель не
видит. Поэтому источники перечислены в ``keep_teacher_courses`` (``keepTeacherCourses``): смена
преподавателя в подборе их не трогает, остаётся тот, кого решатель выбрал до подбора.
Кто из курсов этапа уходит решателю, решает ``solverGroups``.

Зависимости: model, grid, pairs, courses, joint, stages, penalties.
"""

import copy

from src.modules.functions.courses import assignTeacher, courseHours, courseLoad, nobodyTeaches, pinnedSlots, sharedStarted
from src.modules.functions.grid import dayGrid, missingSlots, pinSlot
from src.modules.functions.joint import jointCopies
from src.modules.functions.model import courseGroups, courseSlots, courseSubject, groupsByName, lessonEntries, stageGroups
from src.modules.functions.pairs import isLevelPair, isSubjectPair, programPairs, sameDayMatters, sameLine, subjectPairs, togetherPairs
from src.modules.functions.penalties import compilePenalties
from src.modules.functions.stages import (
    occupiedByOtherStages, pinConflicts, pinContext, pinnedForTeacher, stageCopies, startedTeacher, teacherLeft
)


def buildStageSettings(settings, answer, stage, keep=(), weights=None):
    """Вход решателя для одного этапа; уроки других этапов при этом неподвижны.

    Параметры:
    * ``settings`` — настройки проекта (не меняются: работаем с глубокой копией);
    * ``answer`` — принятое расписание (answer.json);
    * ``stage`` — ключ этапа;
    * ``keep`` — курсы, для которых пользователь выбрал «оставить принятое» (keep mode):
      их уже принятые уроки закрепляются, программа лишь добавляет недостающие;
    * ``weights`` — веса мягких правил (weights.json проекта): по ним мягкие правила с курсами-копиями
      и выброшенными идущими курсами становятся ценами слотов (``priceFixedNeighbours``). Без весов
      таких цен нет.

    Уроки начавшихся курсов («курс уже идёт», courseStarted) и курсов из ``keep``
    закрепляются вместе с их преподавателем; программа только достраивает то, чего не хватает.
    Курсов-копий во входе нет (``solverGroups``), даже если они в ``keep``.

    Возвращает новый словарь настроек, который сервер пишет во вход solve.exe. Помимо
    обычных ключей в нём есть служебные: ``blocked_slots`` (курс -> запрещённые слоты),
    ``existing_courses_by_teacher``, ``teacher_busy_days``, ``custom_penalties_compiled`` и
    ``keep_teacher_courses`` (курсы, которым решатель не меняет преподавателя при подборе).
    """
    all_copies = jointCopies(settings)
    copies = stageCopies(settings, stage, all_copies)
    courses = {group["name"] for group in solverGroups(settings, stage, copies)}
    busy_by_teacher, program_slots, courses_by_teacher = occupiedByOtherStages(settings, answer, stage)
    # Дни, где в сетке на вкладке «Настройки» меньше уроков: этих слотов нет ни у кого.
    # Решатель работает с прямоугольной неделей (дни × макс. уроков), поэтому «дыры» сетки
    # передаются ему как занятые слоты
    missing = [tuple(slot) for slot in missingSlots(settings)]

    result = stageOnly(settings, courses)
    flattenAvailability(result, settings, stage, courses, busy_by_teacher, missing)
    result["blocked_slots"] = programBlockedSlots(result, program_slots, missing)

    # Выброшенные идущие курсы и копии стоят в расписании, но решатель их не получает: их время
    # запрещается соседям по жёстким правилам (здесь), а мягкие правила с ними становятся ценами (ниже)
    drop = pinStartedCourses(result, settings, answer, keep, pinContext(settings, answer, stage))
    fixed = sorted(drop | set(copies))
    blockFixedCourses(result, settings, answer, set(fixed))

    # Сколько курсов у преподавателя уже есть в других этапах: решатель учитывает это в лимите
    # курсов на преподавателя (max_courses_per_teacher)
    result["existing_courses_by_teacher"] = {teacher: len(items) for teacher, items in courses_by_teacher.items()}
    # Дни, в которые преподаватель уже приходит на уроки других этапов: уроки в эти дни не добавляют ему рабочий день
    result["teacher_busy_days"] = {teacher: sorted({day for day, _ in slots}) for teacher, slots in busy_by_teacher.items()}

    # Собственные штрафы пользователя («Свои правила») в виде простых цен и пары курсов этапа,
    # которые сдают вместе (ползунок «Пары — не в один день», вес — в weights.json)
    result["custom_penalties_compiled"] = compilePenalties(settings, stage)
    result["custom_penalties_compiled"]["same_day_pairs"] = sameDayPairs(settings, result["classes"]["custom_groups"])
    priceFixedNeighbours(result["custom_penalties_compiled"]["class_slots"], settings, answer, result["classes"]["custom_groups"], fixed, weights or {})
    result["keep_teacher_courses"] = keepTeacherCourses(result["classes"]["custom_groups"], all_copies)

    return result


def solverGroups(settings, stage, copies=None):
    """Курсы этапа, которые получает решатель: все, кроме курсов-копий (их уроки задаёт поток-источник).

    ``copies`` — уже прочитанные stages.stageCopies этапа, чтобы не читать их ещё раз.
    Начавшиеся курсы без преподавателя отсеиваются позже (pinPlan): для этого нужно расписание.
    """
    copies = stageCopies(settings, stage) if copies is None else copies

    return [group for group in stageGroups(settings, stage) if group["name"] not in copies]


def stageOnly(settings, courses):
    """Глубокая копия настроек, в которой из курсов, нагрузки и закреплённых уроков остались
    только курсы ``courses`` (курсы этапа).
    """
    result = copy.deepcopy(settings)
    classes = result["classes"]

    classes["custom_groups"] = [group for group in classes.get("custom_groups", []) if group["name"] in courses]
    classes["lessons"] = {name: load for name, load in classes.get("lessons", {}).items() if name in courses}
    result["constants"] = {name: value for name, value in result.get("constants", {}).items() if name in courses}

    return result


def flattenAvailability(result, settings, stage, courses, busy_by_teacher, missing):
    """Отметки преподавателей этапа — плоскими списками, которые понимает решатель.

    ``teacher["free"]`` («не может») = собственные «не может» этапа + уроки других этапов +
    закреплённые уроки его курсов в других этапах + слоты ``missing``, которых нет в сетке;
    ``teacher["possible"]`` — «может». Из «может вести» (classes) и «ведёт» (assigned)
    убираются курсы других этапов. Меняет ``result`` на месте.
    """
    for name, teacher in result.get("teachers", {}).items():
        availability = teacher.pop("availability", {}).get(stage, {})
        busy = [list(slot) for slot in availability.get("free", [])]

        # Закреплённые уроки курсов преподавателя в других этапах — точно занятое время.
        # Слот занят, если в нём закреплён хоть один курс не из этого этапа; закрепления своих
        # курсов этапа решатель ставит сам, «не может» для них было бы ошибкой
        pinned_elsewhere = [
            slot for slot, names in pinnedForTeacher(settings, name, stage).items() if any(course not in courses for course in names)
        ]

        for day, lesson in list(busy_by_teacher.get(name, {})) + pinned_elsewhere + missing:
            if [day, lesson] not in busy:
                busy.append([day, lesson])

        teacher["free"] = busy
        teacher["possible"] = [list(slot) for slot in availability.get("possible", [])]

        for subject in teacher.get("subjects", []):
            subject["classes"] = [course for course in subject.get("classes", []) if course in courses]
            subject["assigned"] = [course for course in subject.get("assigned", []) if course in courses]


def programBlockedSlots(result, program_slots, missing):
    """{курс: [[день, урок]]} — где курсу этапа нельзя стоять (служебный ключ blocked_slots).

    Программы, которые никогда не должны стоять в одном слоте (например, семинары и
    ЕГЭ продвинутый), учитываются с уроками других этапов и у копий этого этапа (присоединённые
    линейки: их уроки сборка не двигает, см. stages.occupiedByOtherStages): курсу запрещены слоты,
    где уже стоит «конфликтующая» программа по тому же предмету. Плюс слоты ``missing``, которых нет
    в сетке. Курсы без запретов в словарь не попадают.
    """
    blocked = {}
    programs = programPairs(result)

    for group in result["classes"]["custom_groups"]:
        slots = set(missing)
        subjects = [subject for subject, hours in courseLoad(result, group["name"]).items() if hours > 0]

        for own, other in programs:
            if group.get("program") == own:
                for subject in subjects:
                    slots |= program_slots.get((other, subject), set())

        if slots:
            blocked[group["name"]] = [list(slot) for slot in sorted(slots)]

    return blocked


def keepCourses(settings, answer, stage):
    """Курсы этапа, чьи уроки закрепляет галочка «Оставить уже принятые уроки на месте» (keep):
    те, что уже есть в принятом расписании. Этот список сборка передаёт в ``buildStageSettings``,
    а состояние страницы — в ``pinForecast``. Курсов-копий здесь нет: решатель их не получает.
    """
    return [group["name"] for group in solverGroups(settings, stage) if group["name"] in answer]


def pinPlan(settings, answer, groups, keep):
    """Какие уроки из принятого расписания закрепляются у курсов ``groups``: единственное место,
    где это решается (вход решателя — ``pinStartedCourses``, прогноз — ``pinForecast``).

    Закрепляются все уроки курсов, которые уже идут, и курсов из ``keep``. Курс-источник идёт и тогда,
    когда идёт его копия (courses.sharedStarted): её ученики уже ходят на эти уроки, и в варианты
    сборка всё равно перенесёт их как есть (stages.startedCourses). Преподаватель курса —
    тот, кто стоит на его уроках в расписании (stages.startedTeacher: первый найденный; уроки не
    фильтруются по предмету — у курса один предмет), если он ещё есть в проекте.

    Возвращает (pins, drop): pins — [(курс, предмет, [(день, урок)], преподаватель или None)];
    drop — начавшиеся курсы, которые никто не ведёт: решатель их не получает (см. pinStartedCourses).
    """
    pins, drop = [], set()

    for group in groups:
        course = group["name"]

        for subject in group.get("subjects", []):
            started = sharedStarted(settings, answer, course, subject)

            if course not in keep and not started:
                continue

            teacher = startedTeacher(settings, answer, course)

            if teacher is None and started:
                drop.add(course)

            pins.append((course, subject, courseSlots(answer, course, subject), teacher))

    return pins, drop


def pinStartedCourses(result, settings, answer, keep, context):
    """Закрепляет уроки и преподавателя курсов, которые уже идут, и курсов из ``keep`` (pinPlan).

    Все уже принятые уроки такого курса становятся закреплёнными уроками (constants), а его
    преподаватель из расписания «ведёт» этот курс. Из ручных закреплений курса остаются те, что
    выбирает ``plannedPins`` (``context`` — stages.pinContext этапа): уроки из расписания важнее.

    Возвращает множество курсов, которые решатель не получит вовсе: начавшиеся курсы, которые
    никто не ведёт. Ни один преподаватель не может взять их закреплённое время, поэтому сервер
    оставляет их уроки как есть в каждом варианте. Курс, который только «оставлен» (keep), но ещё
    не начался, остаётся: решатель сам подберёт ему преподавателя.
    """
    pins, drop = pinPlan(settings, answer, result["classes"]["custom_groups"], keep)

    for course, subject, slots, teacher in pins:
        fixed = result.setdefault("constants", {}).setdefault(course, {})
        kept, _ = plannedPins(settings, context, course, subject, slots, teacher)
        placed = {f"{day}-{lesson}" for day, lesson in slots}

        for key in [key for key, value in fixed.items() if value == subject and key not in placed and pinSlot(key) not in kept]:
            del fixed[key]

        fixed.update({key: subject for key in placed})

        if teacher is not None:
            # «Ведёт» — только он (правило одно на всю программу, courses.assignTeacher)
            assignTeacher(result["teachers"], course, subject, teacher)

    return drop


def plannedPins(settings, context, course, subject, slots, teacher):
    """Закрепления курса ``course`` по предмету ``subject`` во входе решателя, когда сборка закрепляет
    его уроки из расписания ``slots`` с преподавателем ``teacher`` (pinPlan): (ручные закрепления,
    которые остаются, [(день, урок)]; места закреплений, которые решатель не поставит, — множество).

    Вместе с уроками из расписания закреплений не больше часов курса: решатель перебирает закрепления
    по порядку и лишние отвергает — тогда он мог бы отвергнуть урок из расписания, и идущий курс
    сдвинулся бы в каждом варианте. Поэтому лишние ручные закрепления отбрасываются: сначала те,
    которые решатель всё равно не поставит (stages.pinConflicts, ``context`` — stages.pinContext этапа),
    затем последние по порядку мест. Не поставит он и уроки из расписания и оставшиеся ручные
    закрепления с помехой. Ручное закрепление, которое решатель поставил бы на место урока идущего курса
    с именем позже и отверг бы тот урок (тот же преподаватель, пара «нельзя», программа), отбрасывается
    всегда. Если у ``teacher`` больше нет предмета, курс поведёт другой преподаватель
    (stages.teacherLeft) — тогда ищутся только помехи, которые от преподавателя не зависят.
    """
    placed = set(slots)
    manual = [slot for slot in pinnedSlots(settings, course, subject) if slot not in placed]
    who = None if teacherLeft(settings, course, subject, teacher) else teacher
    found = pinConflicts(context, course, subject, sorted(placed) + manual, who)
    clash = pinConflicts(context, course, subject, manual, who, later=True)
    # Закрепление, которое решатель и так не поставит, урок идущего курса не вытеснит
    manual = [slot for slot in manual if slot in found or slot not in clash]
    # Сортировка устойчивая: сначала возможные, внутри — по порядку мест
    manual.sort(key=lambda slot: slot in found)
    kept = manual[:max(courseHours(settings, course, subject) - len(placed), 0)]

    return kept, {slot for slot in found if slot in placed or slot in kept}


def pinForecast(settings, answer, stage, keep=(), context=None):
    """Сколько уроков этапа ``stage`` закрепит вход решателя: {"pinned", "total", "free", "noTeacher"}.

    total — часы курсов, которые получит решатель (без выброшенных идущих курсов без
    преподавателя, pinPlan); noTeacher — часы тех из них, кого никто не может вести: решатель их
    уроки не ставит, даже закреплённые; pinned — сколько у остальных закрепится: уроки из
    расписания (pinPlan) вместе с ручными закреплениями курса, которые останутся во входе
    (``plannedPins``), без тех, что решатель не поставит, — по каждому курсу и предмету не больше
    его часов; free = total − pinned − noTeacher — сколько подберёт программа.
    ``keep`` — как у buildStageSettings; ``context`` — уже собранный stages.pinContext этапа (страница
    считает прогноз с галочкой и без по одному). Часы курсов-копий не в счёт: решатель их не получает.

    Решатель печатает те же числа («Закреплено N из M уроков, подбирается K, без преподавателя
    (не ставятся): X»); отвергнутое закрепление он называет предупреждением («закреплённый урок …
    не поставлен»). Помехи ручным закреплениям курсов, чьи уроки сборка не закрепляет, прогноз не
    ищет — такое закрепление он считает поставленным. Курсы, которым преподаватель не достанется
    из-за лимита курсов, решатель узнаёт только при подборе и тоже относит к X — прогноз их считает в free.
    ``context`` с ``keep`` — тот же, что без него (stages.pinContext свежей сборки): ручное закрепление курса
    из ``keep``, которое вход отбросит (``plannedPins``), он всё равно считает помехой курсам с именем позже —
    тогда прогноз меньше, чем закрепит решатель (редкий случай: закрепление поставлено «всё равно» на время
    урока другого курса того же преподавателя).
    """
    context = context or pinContext(settings, answer, stage)
    groups = solverGroups(settings, stage)
    pins, drop = pinPlan(settings, answer, groups, keep)
    from_answer = {(course, subject): (slots, teacher) for course, subject, slots, teacher in pins}
    total = pinned = nobody = 0

    for course in [group["name"] for group in groups]:
        if course in drop:
            continue

        for subject, hours in courseLoad(settings, course).items():
            slots, teacher = from_answer.get((course, subject), ([], None))
            total += hours

            # Преподаватель из расписания во входе решателя «ведёт» курс (pinStartedCourses), если
            # у него есть этот предмет (assignTeacher); иначе курс ведут только те, кто «может вести»
            if nobodyTeaches(settings, course, subject, teacher):
                nobody += hours
                continue

            if (course, subject) in from_answer:
                kept, rejected = plannedPins(settings, context, course, subject, slots, teacher)

            else:
                kept, rejected = pinnedSlots(settings, course, subject), set()

            pinned += min(hours, len(set(slots) | set(kept)) - len(rejected))

    return {"pinned": pinned, "total": total, "free": total - pinned - nobody, "noTeacher": nobody}


def droppedLessons(settings, answer, stage):
    """Сколько уроков у идущих курсов этапа без преподавателя: решатель их не получает
    (pinPlan), а сервер переносит их уроки в каждый вариант как есть.
    """
    _, drop = pinPlan(settings, answer, solverGroups(settings, stage), ())

    return sum(1 for course in drop for _ in lessonEntries(answer, course))


def blockFixedCourses(result, settings, answer, fixed):
    """Убирает курсы ``fixed`` из входа решателя, а их время запрещает другим курсам этапа.

    ``fixed`` — курсы этапа, которые стоят в расписании как есть, но решатель их не получает:
    начавшиеся курсы без преподавателя (pinStartedCourses) и курсы-копии (их уроки задаёт
    поток-источник; во входе их нет с самого начала). Их уроки не должны совпасть с курсами, с
    которыми им нельзя пересекаться: жёсткие пары предметов в одной линейке одного потока
    (joint_subject_pairs) и непересекающиеся программы по тому же предмету.
    Меняет ``result`` на месте; без таких курсов ничего не делает.
    """
    if not fixed:
        return

    classes = result["classes"]
    hard_pairs = subjectPairs(settings, "joint_subject_pairs")
    programs = programPairs(settings)
    # Порядок — как в проекте: от него зависит порядок запрещённых слотов
    gone_groups = [group for group in courseGroups(settings) if group["name"] in fixed]

    for group in classes["custom_groups"]:
        if group["name"] in fixed:
            continue

        for gone in gone_groups:
            for subject in group.get("subjects", []):
                for other in gone.get("subjects", []):
                    pair = sameLine(group, gone) and isSubjectPair(hard_pairs, subject, other)
                    program = (group.get("program"), gone.get("program")) in programs and subject == other

                    if pair or program:
                        blocked = result["blocked_slots"].setdefault(group["name"], [])
                        blocked += [[day, lesson] for day, lesson in courseSlots(answer, gone["name"], other) if [day, lesson] not in blocked]

    classes["custom_groups"] = [group for group in classes["custom_groups"] if group["name"] not in fixed]
    classes["lessons"] = {name: load for name, load in classes["lessons"].items() if name not in fixed}
    result["constants"] = {name: value for name, value in result.get("constants", {}).items() if name not in fixed}


def priceFixedNeighbours(prices, settings, answer, groups, fixed, weights):
    """Мягкие правила с неподвижными курсами ``fixed`` — цены слотов для курсов ``groups``, которые
    получает решатель.

    Неподвижные курсы — это копии этапа (их уроки задаёт поток-источник) и выброшенные идущие курсы
    без преподавателя (pinStartedCourses): их уроки стоят в расписании и переносятся в каждый вариант,
    а во входе решателя их нет. Поэтому решатель сам не видит, что сосед стоит одновременно с таким
    курсом или в другие часы, чем он (ниже он для краткости — «копия»). Вместо этого соседу
    назначаются цены за урок в слоте (``prices`` —
    ``custom_penalties_compiled.class_slots``, дописывается на месте), с весами ``weights``:
    * «нежелательно одновременно» (softSubjectPair) — сосед по линейке потока с парой «нежелательно»:
      цена в слотах копии;
    * «уровни врозь» (levelsApart) — тот же предмет на другом уровне: цена во всех слотах сетки,
      кроме слотов копии. Решатель считает min(уроков, уроков копии) − общих слотов; цена за урок
      вне слотов копии отличается от этого на постоянную величину, поэтому выбор тот же;
    * «пары не в один день» (pairsSameDay) — предметы, которые сдают вместе (pairs.sameDayMatters):
      цена в каждом слоте дней копии.
    Курс без уроков (копия ждёт поток-источник) и правило с весом 0 цен не дают.
    """
    by_name = groupsByName(settings)
    soft_pairs = subjectPairs(settings, "soft_subject_pairs")
    together = togetherPairs(settings)
    grid = [(day, lesson) for day, times in enumerate(dayGrid(settings)) for lesson in range(len(times))]

    for name in fixed:
        shared = by_name[name]
        slots = sorted({(day, lesson) for day, lesson, _ in lessonEntries(answer, name)})

        if not slots:
            continue

        days = {day for day, _ in slots}

        for group in groups:
            rules = (
                ("softSubjectPair", sameLine(group, shared) and isSubjectPair(soft_pairs, courseSubject(group), courseSubject(shared)), slots),
                ("levelsApart", isLevelPair(group, shared), [slot for slot in grid if slot not in slots]),
                ("pairsSameDay", sameDayMatters(group, shared, together), [slot for slot in grid if slot[0] in days]),
            )

            for key, applies, where in rules:
                if applies and weights.get(key, 0) > 0:
                    prices.setdefault(group["name"], []).extend([day, lesson, weights[key]] for day, lesson in where)


def keepTeacherCourses(groups, copies):
    """[курс] — курсы ``groups`` (курсы входа решателя), к которым присоединяется более поздний поток:
    источники общих уроков (``copies`` — joint.jointCopies, {копия: источник}). Порядок — как в ``groups``.

    Их преподаватель ведёт и копии, но «не может» и занятость преподавателя на этапе потока-копии
    решатель не видит. Чтобы смена преподавателя в подборе не ставила на общие уроки того, кто там
    занят, решатель оставляет им преподавателя, выбранного до подбора (служебный ключ
    ``keep_teacher_courses``). Без копий список пуст.
    """
    sources = set(copies.values())

    return [group["name"] for group in groups if group["name"] in sources]


def sameDayPairs(settings, groups):
    """[[курс, курс]] — пары курсов ``groups``, чьи уроки лучше ставить в разные дни (pairs.sameDayMatters)."""
    together = togetherPairs(settings)

    return [
        [first["name"], second["name"]]
        for i, first in enumerate(groups) for second in groups[i + 1:]
        if sameDayMatters(first, second, together)
    ]
