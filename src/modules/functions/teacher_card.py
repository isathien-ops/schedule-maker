"""Карточка преподавателя на вкладке «Преподаватели»: что показать о нём на выбранном этапе.

Карточка собирается из настроек проекта и принятого расписания и ничего не меняет. Её отдаёт
маршрут GET /api/project/<p>/teacher (src/web/tabs/teachers.py): он только проверяет, что
преподаватель есть, и вызывает ``teacherCard``.

Выбранный на странице этап задаёт только сетку доступности: отметки «может / не может»,
занятые клетки и уроки в этой сетке. Список курсов в карточке — всех этапов.

Общий урок двух потоков («линейка идёт вместе с Потоком N», joint.py) — урок курса-копии этапа:
в сетке это клетка «вместе» (вид "joint" из stages.teacherCommitments), а не «занят» уроком
потока-источника; у копии в списке курсов есть поле ``joint``. Накладкой такой урок не считается
(stages.teacherClashes).

Функции
-------
    coursesInStageOrder  курсы проекта в порядке этапов
    lessonsInStageDates  уроки преподавателя, видимые в сетке этапа
    teacherCourses       курсы по предметам с пометками для таблиц курсов
    teacherCard          карточка целиком (её отдаёт /teacher)

Зависимости: model, courses (отношение к курсу, лимит), joint (курсы-копии), stages (этапы,
занятость, накладки).
"""

from src.modules.functions.courses import lineOf, teacherCourseState, teacherLimit
from src.modules.functions.joint import jointCopies
from src.modules.functions.model import (
    allLessons, cannotSlots, courseDates, courseGroups, datesOverlap, groupsByName, hasLessons, lessonEntries, possibleSlots,
    stageKey, teacherLessons
)
from src.modules.functions.stages import (
    getStages, stageCourses, stageDates, startedCourses, teacherClashes, teacherCommitments
)


def coursesInStageOrder(settings):
    """Курсы проекта (элементы ``classes.custom_groups``) в порядке этапов; курсы неизвестного
    этапа — в конце. Внутри этапа порядок прежний.
    """
    order = {item["key"]: index for index, item in enumerate(getStages(settings))}

    return sorted(courseGroups(settings), key=lambda group: order.get(stageKey(group), len(order)))


def lessonsInStageDates(settings, answer, name, stage):
    """Уроки преподавателя ``name``, видимые в сетке этапа ``stage``: {(день, урок): [курсы]}.

    Это его уроки курсов этого этапа и любых других курсов, идущих в те же даты: так два урока
    в одно время видны, даже если оба из других этапов. Курсы, которых уже нет в настройках,
    пропускаются.
    """
    own_courses = set(stageCourses(settings, stage))
    dates = stageDates(settings, stage)
    groups = groupsByName(settings)
    lessons_at = {}

    for course in answer:
        group = groups.get(course)

        if group is None or (course not in own_courses and not datesOverlap(courseDates(settings, group), dates)):
            continue

        for day, lesson, entry in lessonEntries(answer, course):
            if name in entry.get("teachers", []):
                lessons_at.setdefault((day, lesson), []).append(course)

    return lessons_at


def teacherCourses(settings, answer, name, groups, started):
    """Курсы по каждому предмету преподавателя: [{"subject", "courses": [...]}].

    ``groups`` — курсы в порядке показа, ``started`` — идущие курсы. У каждого курса: состояние
    «не ведёт / может / ведёт / запрещено» и пометки scheduled (ведёт его в расписании),
    started (курс идёт) и orphan (курс стоит в расписании, но ни у одного его урока нет
    преподавателя). Предметы без курсов не показываются.
    У курса-копии ``joint`` = {"number": номер потока-источника, "source": курс-источник}: его
    отношение к преподавателю меняется только у источника («как в Потоке N»); у остальных — None.
    """
    teaching = {course for course, *_ in teacherLessons(answer, name)}
    taught = {course for course, _, _, entry in allLessons(answer) if entry.get("teachers")}
    copies = jointCopies(settings)
    result = []

    for item in settings["teachers"][name].get("subjects", []):
        courses = [
            {
                "name": group["name"], "stage": stageKey(group), "line": lineOf(group),
                "state": teacherCourseState(settings, name, item["subject"], group["name"]),
                "scheduled": group["name"] in teaching,
                "started": group["name"] in started,
                "orphan": hasLessons(answer, group["name"]) and group["name"] not in taught,
                "joint": {"number": group["together_with"], "source": copies[group["name"]]} if group["name"] in copies else None,
            }
            for group in groups
            if item["subject"] in group.get("subjects", [])
        ]

        if courses:
            result.append({"subject": item["subject"], "courses": courses})

    return result


def teacherCard(settings, answer, name, stage):
    """Карточка преподавателя ``name`` (он должен быть в проекте) на этапе ``stage``.

    Поля:
      busy / possible — его отметки «не может» / «может» этого этапа;
      commitments — клетки, занятые уроками других этапов, закреплениями или общими уроками:
                [день, урок, "busy" | "pinned" | "joint", курс] (см. stages.teacherCommitments);
      own     — его уроки этого этапа в расписании: [день, урок, курс, курс идёт];
      clashes — его накладки (два урока в одно время), видимые в этой сетке: [день, урок, курсы];
      subjects — его курсы по предметам (см. teacherCourses);
      limit   — сколько курсов может вести один преподаватель.
    """
    groups = coursesInStageOrder(settings)
    own_courses = set(stageCourses(settings, stage))
    lessons_at = lessonsInStageDates(settings, answer, name, stage)
    # Идущие курсы всех этапов («курс уже идёт»): и для пометки уроков own, и для списка курсов
    started = startedCourses(settings, answer, [group["name"] for group in groups], complete=False)

    return {
        "busy": cannotSlots(settings, name, stage),
        "possible": possibleSlots(settings, name, stage),
        "commitments": [[day, lesson, kind, course] for (day, lesson), (kind, course) in teacherCommitments(settings, answer, name, stage).items()],
        "own": [[day, lesson, course, course in started] for (day, lesson), courses in lessons_at.items() for course in courses if course in own_courses],
        "clashes": [[day, lesson, courses] for _, day, lesson, courses in teacherClashes(settings, answer, name) if (day, lesson) in lessons_at],
        "subjects": teacherCourses(settings, answer, name, groups, started),
        "limit": teacherLimit(settings),
    }
