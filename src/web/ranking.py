"""Варианты этапа глазами «Предпросмотра» и выгрузки: отметка сборки, порядок от лучшего
к худшему с оценками, переставленные уроки, отклонённые варианты.

Нужен двум вкладкам — «Предпросмотр» (tabs/preview.py) и «Экспорт» (tabs/export.py), поэтому
лежит отдельно: вкладки друг друга не импортируют. Только чтение, LOCK сам не берёт.
Метки «принят» и «отклонён» (accepted.json, rejected.json) и курсы, которые шли при сборке
(started.json, variants.buildStarted — для stages.staleStarted и stages.movedStarted), читаются и пишутся функциями
variants.py; здесь они только учитываются в пометках вариантов. Порядок вариантов, «лучший»
и «ничья» — variants.rankVariants.

Курсы-копии («линейка идёт вместе с Потоком N», модуль joint) в варианте потока-копии не
сравниваются с расписанием и не считаются переставленными: их уроки ставит поток-источник.
Поэтому в варианте копии показываются и оцениваются с уроками источников из принятого расписания,
а не какими были при сборке (источник с тех пор могли принять заново, закрепить, сменить ему
преподавателя или убрать из расписания).
А вариант потока-источника, который двигает общие уроки, сообщает, сколько уроков сдвинется
в потоках-копиях (``jointMoved``).

Сборка может сменить преподавателя курса (.spec/teacher-swap): у варианта видно, кто ведёт его курсы
(``teachers``) и кому из уже принятых курсов он сменит преподавателя (``changedTeachers``). Копии
и здесь не в счёт: их преподаватель — преподаватель источника.

Зависимости: project (файлы проекта) и предметные модули (variants, stages, joint, courses, model).
"""

import os

from src.modules.functions.courses import copiesOf, lineOf
from src.modules.functions.joint import followSources, jointCopies
from src.modules.functions.model import groupsByName, lessonEntries
from src.modules.functions.stages import (
    changeableCourses, lockedFromAnswer, movedStarted, ownCourses, stageCopies, stageCourses, staleStarted
)
from src.modules.functions.variants import (
    acceptedNumber, buildStarted, isAccepted, lessonIssues, lessonTeachers, loadVariants, missingDetails, rankVariants, rejectedNumbers,
    variantMetrics, variantsDir, waitingDetails
)
from src.web.project import loadAnswer, loadSettings, loadWeights, movedStartedItems, projectPath


def variantsBuild(project, stage):
    """«Отметка сборки» вариантов этапа: меняется, когда варианты построены заново.

    Страница передаёт её при принятии варианта (accept, параметр build): если варианты
    тем временем перестроили, номер варианта указывает уже на другой — принятие отклоняется.
    """
    folder = variantsDir(projectPath(project), stage)

    if not os.path.isdir(folder):
        return ""

    # Считаются только файлы вариантов (1.json, 2.json…): accepted.json меняется при
    # принятии, а не при новой сборке
    return str(max((os.path.getmtime(os.path.join(folder, name)) for name in os.listdir(folder) if os.path.splitext(name)[0].isdigit()), default=0))


def rankedVariants(project, stage):
    """(настройки, варианты этапа с оценками от лучшего к худшему) — для «Предпросмотра» и выгрузки в Excel.

    У каждого варианта: number, metrics (variants.variantMetrics), accepted / same (принят /
    совпадает с расписанием), answer (копии этапа — с нынешними уроками источников,
    joint.followSources; зафиксированные курсы — из расписания, stages.lockedFromAnswer), problems (каких курсов не хватает уроков и почему),
    moved (сколько уже принятых уроков он переставит), jointMoved (общие уроки потоков-копий,
    которые он сдвинет, ``jointMoved``), issues (подписи к урокам), teachers (кто ведёт курсы этапа
    без копий, ``variantTeachers``), teacherChanges (кому из принятых курсов он сменит преподавателя,
    ``changedTeachers``), staleStarted (идущие курсы, которым вариант, собранный до их начала или до того,
    как их уроки в расписании поменялись, сдвинул бы уроки или сменил преподавателя, stages.staleStarted;
    курсы, которые шли уже при сборке с теми же уроками, — variants.buildStarted — проверяет movedStarted;
    непустой — вариант accept не примет), movedStarted (курсы, которые шли уже при сборке, а вариант всё равно
    сдвинул им урок или сменил преподавателя, stages.movedStarted, — [{"course", "lines"}],
    project.movedStartedItems; непустой — accept тоже не примет), rejected,
    best / tied (лучший и «ничья», см. variants.rankVariants). В problems и копии, ждущие поток-источник (причина
    "joint_waiting"): их уроков нет не из-за сборки. Вызывать под LOCK.
    """
    settings = loadSettings(project)
    weights = loadWeights(project)
    answer = loadAnswer(project)
    path = projectPath(project)
    courses = stageCourses(settings, stage)
    changeable = changeableCourses(settings, answer, stage)
    # Номер последнего принятого варианта: несколько одинаковых вариантов не должны все
    # показываться принятыми
    chosen = acceptedNumber(path, stage)
    # Варианты, которые пользователь отклонил (rejectVariant): показываются бледными
    rejected = rejectedNumbers(path, stage)
    # Копии, ждущие поток-источник, — одни и те же у всех вариантов: от сборки они не зависят
    waiting = waitingDetails(settings, answer, stage)
    copies = stageCopies(settings, stage)
    own = ownCourses(settings, stage)
    # Курсы, которые шли уже при сборке: им вариант не «собран до начала» (stages.staleStarted)
    built = buildStarted(path, stage, answer)
    ranked = []

    for number, stored in loadVariants(path, stage):
        # Вариант такой, каким он примется: копии встанут в нынешние часы источников, а зафиксированные
        # после сборки курсы останутся как в расписании (accept)
        variant = lockedFromAnswer(settings, answer, stage, followSources(settings, answer, dict(stored), copies))
        metrics = variantMetrics(settings, stage, variant, weights, answer)
        # «принят» — только вариант, который приняли (его номер в accepted.json); вариант, просто
        # совпадающий с расписанием (например, всё было закреплено), — «как сейчас»
        same = isAccepted(answer, variant, courses, settings=settings)
        accepted = same and chosen == number
        ranked.append({
            "number": number, "metrics": metrics, "accepted": accepted, "same": same and not accepted, "answer": variant,
            # Каким курсам не хватает уроков и почему
            "problems": (missingDetails(settings, answer, stage, variant) if metrics["missing"] else []) + waiting,
            "moved": len(movedLessons(answer, variant, changeable)),
            "jointMoved": jointMoved(settings, answer, variant, changeable),
            # Что не так с каждым уроком — подписи на карточках недели
            "issues": lessonIssues(settings, stage, variant, answer),
            "teachers": variantTeachers(variant, own),
            "teacherChanges": changedTeachers(answer, variant, changeable),
            # Тот же отказ, что у принятия (preview.accept): страница и сервер судят одинаково
            "staleStarted": staleStarted(settings, answer, stage, variant, built),
            "movedStarted": movedStartedItems(settings, movedStarted(settings, answer, stage, variant, built)),
            "rejected": number in rejected,
        })

    return settings, rankVariants(ranked)



def movedLessons(answer, variant, courses):
    """Уроки принятого расписания, которые вариант ставит в другое место: [(курс, (день, урок))].

    Смотрятся только курсы `courses` (обычно — курсы этапа без зафиксированных,
    stages.changeableCourses) в их порядке, поэтому и вопрос о переезде уроков перечисляет курсы
    всегда в одном порядке. Курсы, которых ещё нет в расписании, пропускаются: им переставлять нечего.
    """
    result = []

    for course in courses:
        if course not in answer:
            continue

        now = {(day, lesson) for day, lesson, _ in lessonEntries(answer, course)}
        new = {(day, lesson) for day, lesson, _ in lessonEntries(variant, course)}
        result += [(course, slot) for slot in sorted(now - new)]

    return result


def jointMoved(settings, answer, variant, courses):
    """Общие уроки потоков-копий, которые сдвинет вариант: [{"line", "number", "lessons"}].

    Копия идёт за своим источником, поэтому её принятые уроки, которых у источника в варианте
    не будет, тоже переедут на другое время, если принять вариант (как ``movedLessons`` для самого
    источника). Смотрятся только
    источники из ``courses`` — курсов, которые принятие варианта может менять
    (stages.changeableCourses). Одна запись на линейку потока-копии: «line» — линейка, «number» —
    номер потока-копии, «lessons» — сколько её уроков сдвинется; по номеру потока, затем по линейке.
    ``variant`` — вариант этапа или всё расписание после принятия (так считает и вопрос accept):
    берутся только уроки источников.
    """
    groups = groupsByName(settings)
    copies = copiesOf(jointCopies(settings), courses)
    # Уроки, которые получит каждая копия после принятия, — уроки её источника в варианте
    following = {name: variant.get(source, []) for name, source in copies.items()}
    counts = {}

    for name, _ in movedLessons(answer, following, copies):
        key = (groups[name]["stream_id"], lineOf(groups[name]))
        counts[key] = counts.get(key, 0) + 1

    return [{"line": line, "number": number, "lessons": count} for (number, line), count in sorted(counts.items())]


def variantTeachers(variant, courses):
    """Кто ведёт курсы ``courses`` в варианте: {курс: [преподаватели]}, только курсы с уроками,
    у которых есть преподаватель. Имена — в порядке первого появления в неделе курса.
    """
    result = {}

    for course in courses:
        names = list(dict.fromkeys(name for names in lessonTeachers(variant, course).values() for name in names))

        if names:
            result[course] = names

    return result


def changedTeachers(answer, variant, courses):
    """Кому из уже принятых курсов вариант сменит преподавателя: [{"course", "subject", "before", "after"}].

    Смотрятся курсы ``courses`` (обычно stages.changeableCourses: без зафиксированных (идут и все уроки
    на месте) и копий) в их порядке,
    по каждому предмету курса. «before» — кто ведёт уроки в принятом расписании ``answer``, «after» —
    в варианте; смена — когда это разные люди. Курс, которого нет в расписании или в варианте, или
    уроки без преподавателя в расписании — не смена: менять в расписании нечего или некого. А уроки
    без преподавателя в варианте при принятом преподавателе — смена («after» пуст): так бывает, когда
    выбранного сборкой преподавателя удалили или запретили ему курс, и варианты переписали без него.
    """
    result = []

    for course in courses:
        now = lessonTeachers(answer, course)

        for subject, after in lessonTeachers(variant, course).items():
            before = now.get(subject, [])

            if before and set(before) != set(after):
                result.append({"course": course, "subject": subject, "before": before, "after": after})

    return result
