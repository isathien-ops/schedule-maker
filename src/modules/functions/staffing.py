"""Хватает ли преподавателей: предупреждение «нужен ещё преподаватель» на странице «Расписание».

По каждому предмету сравнивается, сколько уроков в неделю нужно, и сколько свободного времени
осталось у преподавателей этого предмета.

* Свободное время преподавателя — уроки сетки (вкладка «Настройки»), которые не заняты его
  уроками в принятом расписании (answer.json) и не отмечены «не может».
* «Не может» берётся из отметок тех этапов (потоков и блоков курсов без потока), где у предмета
  ещё есть непоставленные уроки; если всё поставлено — из отметок последнего потока (по ним
  видно, как будет со следующим).
* Нужно поставить — часы курсов предмета минус уже стоящие в расписании уроки.

Итог для предмета — одно из двух предупреждений:
* "short" — свободного времени меньше, чем нужно поставить: уроки уже не помещаются;
* "tight" — поставить всё можно, но запаса меньше, чем нужно одному потоку по этому предмету:
  следующий поток уже не поместится, пора искать преподавателя.

Курсы-копии («линейка идёт вместе с Потоком N», joint.py) не считаются вовсе: их уроки —
это уроки источника, преподавателя им отдельно не нужно. Ждущая копия (у источника ещё нет
уроков) не даёт «не хватает», а поток с копиями требует только своих уроков.

Это грубая оценка «по часам»: она не учитывает пары «нельзя» и то, что у курса не больше
одного урока в день, поэтому настоящее составление может упереться раньше.

Зависимости: model, grid, courses (часы курса, преподаватели предмета), joint (курсы-копии),
stages (порядок потоков).
"""

from src.modules.functions.courses import courseHours, subjectTeachers
from src.modules.functions.grid import dayGrid
from src.modules.functions.joint import jointCopies
from src.modules.functions.model import allLessons, cannotSlots, courseGroups, courseSubject, isBlockStage, lessonEntries, stageKey
from src.modules.functions.stages import getStages


def staffing(settings, answer):
    """Предметы, которым не хватает (или скоро не хватит) преподавателей.

    Возвращает список словарей, сначала "short", потом "tight", внутри — по предмету:
    {"subject", "level": "short" | "tight", "needed": сколько уроков ещё нужно поставить,
     "free": свободных часов у преподавателей предмета, "next": уроков на один поток,
     "teachers": [имена преподавателей предмета по алфавиту]}.
    Предмет без единого преподавателя — всегда "short" (free = 0).

    "free" — всё свободное время, ещё до того, как поставят недостающие уроки. Страница
    (view.js) у "short" показывает его как есть, а у "tight" — остаток free − needed:
    столько останется свободно для следующего потока (текст web.view.staff_tight).
    """
    slots = [(day, lesson) for day, times in enumerate(dayGrid(settings)) for lesson in range(len(times))]
    # Потоки (не доп. курсы и не блоки) по порядку: последний — самый новый
    streams = [stage["key"] for stage in getStages(settings) if not isBlockStage(stage["key"])]
    busy = busySlots(answer)
    # Копии не требуют ни уроков, ни времени: за них отвечает курс-источник
    copies = jointCopies(settings)
    result = []

    for subject in sorted({courseSubject(group) for group in courseGroups(settings)} - {""}):
        courses = [group for group in courseGroups(settings) if courseSubject(group) == subject and group["name"] not in copies]
        names = subjectTeachers(settings, subject)
        needed, open_stages = unplacedLessons(settings, answer, courses)
        next_stream = streamLoad(settings, courses, streams)

        # Чьи отметки «не может» смотреть: этапов (потоков и блоков) с непоставленными уроками,
        # иначе последнего потока
        marks = open_stages or ({streams[-1]} if streams else set())
        free = sum(freeHours(settings, name, marks, slots, busy.get(name, set())) for name in names)

        if not names or free < needed:
            level = "short"

        elif next_stream and free - needed < next_stream:
            level = "tight"

        else:
            continue

        result.append({"subject": subject, "level": level, "needed": needed, "free": free, "next": next_stream, "teachers": names})

    return sorted(result, key=lambda item: (item["level"] != "short", item["subject"]))


def busySlots(answer):
    """Занятое время каждого преподавателя в принятом расписании: {имя: {(день, урок)}}."""
    busy = {}

    for _, day, lesson, entry in allLessons(answer):
        for name in entry.get("teachers", []):
            busy.setdefault(name, set()).add((day, lesson))

    return busy


def unplacedLessons(settings, answer, courses):
    """(сколько уроков курсов ``courses`` ещё не стоит в расписании, ключи их этапов с такими уроками)."""
    needed = 0
    open_stages = set()

    for group in courses:
        missing = courseHours(settings, group["name"]) - sum(1 for _ in lessonEntries(answer, group["name"]))

        if missing > 0:
            needed += missing
            open_stages.add(stageKey(group))

    return needed, open_stages


def streamLoad(settings, courses, streams):
    """Уроков в неделю на один поток (самый большой поток среди курсов ``courses``); без потоков — 0."""
    per_stream = {}

    for group in courses:
        if stageKey(group) in streams:
            per_stream[stageKey(group)] = per_stream.get(stageKey(group), 0) + courseHours(settings, group["name"])

    return max(per_stream.values(), default=0)


def freeHours(settings, name, stages, slots, busy):
    """Свободные часы преподавателя: слоты сетки ``slots`` без его уроков ``busy`` и без «не может» этапов ``stages``."""
    cannot = {tuple(slot) for stage in stages for slot in cannotSlots(settings, name, stage)}

    return sum(1 for slot in slots if slot not in busy and slot not in cannot)
