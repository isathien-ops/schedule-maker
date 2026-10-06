"""Этапы составления расписания: список этапов, их даты и курсы, что уже принято и что занято.

Что такое «этап»
----------------
Все курсы проекта делятся на этапы по разделу (model.stageKey):

* курсы с потоком (``stream_id`` = 1, 2, …) — этап «Поток N»; ключ этапа — номер потока
  строкой: ``"1"``, ``"2"``…;
* курсы без потока группируются по блоку (``block``): доп. курсы, майские марафоны,
  летняя школа… Ключ этапа — слово (``"extra"``, ``"may"``…); если блок не задан —
  ``"extra"`` (model.EXTRA_BLOCK).

Этапы упорядочены по дате старта (самый ранний ``start_date`` среди их курсов).
У каждого этапа свои отметки времени преподавателей (``teacher["availability"][<этап>]``),
и строится он отдельно от других: решатель получает только курсы этого этапа (вход готовит
solver_input.buildStageSettings). Этапы, уже попавшие в «принятое расписание» (``answer.json``),
остаются неподвижными и занимают своих преподавателей и время — но только на тех неделях,
где их даты пересекаются с датами строящегося этапа (``occupiedByOtherStages``).

Курсы-копии («линейка идёт вместе с Потоком N», модуль joint) сборка этапа не меняет: их уроки
задаёт поток-источник. Поэтому копии этапа занимают время своих преподавателей как уроки другого
этапа (при любых датах), а пара «источник + копия» — один курс и один урок: не накладка и не
два курса в лимите преподавателя.

Главные точки входа
-------------------
* ``getStages`` — список этапов с курсами и датой старта;
* ``acceptedStages`` — этапы, которые уже есть в расписании (хотя бы одним уроком);
* ``stageTotals`` / ``stageBuilt`` / ``builtStages`` — сколько уроков этапа расставлено и
  «этап построен» (единственное определение: им пользуются и стартовый экран, и «Запуск»);
* ``stageCopies`` — курсы-копии этапа; ``ownCourses`` — курсы, уроки которых этап ставит сам
  (без копий); ``countedCourses`` — по каким курсам судят, что этап в расписании, построен
  и сколько уроков ему не хватает;
* ``startedCourses`` / ``changeableCourses`` / ``allStarted`` — идущие курсы этапа и те,
  что сборка ещё может менять; ``lockedFromAnswer`` — вариант, каким его сохранит принятие
  (зафиксированные курсы — из расписания); ``staleStarted`` — идущие курсы, которым вариант,
  собранный до их начала, сдвинул бы уроки или сменил преподавателя, ``movedStarted`` — идущие уже
  при сборке курсы, которым вариант всё равно сдвинул урок или сменил преподавателя (с причиной); такой
  вариант не принимается; ``blockedStarted`` — то же ещё до сборки: уроки идущих курсов, которые решатель
  не сможет оставить как в расписании (``pinConflicts`` по ``pinContext`` — что видит решатель, когда
  ставит закрепления этапа), — предупреждение «Запуска»;
* ``teacherCommitments`` / ``teacherClashes`` — занятость и накладки преподавателей (сетка
  на вкладке «Преподаватели» и предупреждения над «Расписанием»);
* ``mergeStageAnswer`` — вставляет выбранный вариант этапа в общее расписание.

Зависимости: model, grid (ключи закреплённых уроков, сетка), pairs (пары «нельзя» и программы — помехи
закреплениям), courses (идущие курсы, нагрузка курса), joint (копии и их источники).
"""

import copy

from src.modules.functions.courses import (
    copyFollowers, copyRoot, courseHours, courseLocked, courseStarted, nobodyTeaches, pinnedSlots, sharedStarted, subjectTeachers
)
from src.modules.functions.grid import lessonExists, pinSlot
from src.modules.functions.joint import jointCopies
from src.modules.functions.model import (
    cannotSlots, courseDates, courseGroups, courseSlots, coursesOverlap, datesOverlap, groupsByName, hasLessons, isBlockStage,
    lessonEntries, stageGroups, stageKey
)
from src.modules.functions.pairs import isSubjectPair, programPairs, sameLine, subjectPairs


def getStages(settings):
    """Все этапы проекта, отсортированные по дате старта.

    Возвращает список словарей ``{"key": ключ этапа, "courses": [имена курсов],
    "start": самая ранняя дата старта курсов этапа (ISO-строка) или None}``.
    Этапы без дат идут в конце; при равных датах — по ключу.
    """
    stages = {}

    for group in courseGroups(settings):
        stage = stages.setdefault(stageKey(group), {"key": stageKey(group), "courses": [], "start": None})
        stage["courses"].append(group["name"])

        start = group.get("start_date") or None

        # Дата старта этапа — самая ранняя среди его курсов (ISO-даты сравниваются как строки)
        if start and (stage["start"] is None or start < stage["start"]):
            stage["start"] = start

    return sorted(stages.values(), key=lambda stage: (stage["start"] or "9999-99-99", stage["key"]))


def stageCourses(settings, stage):
    """Имена курсов этапа ``stage`` в порядке их хранения; пустой список, если такого этапа нет."""
    return [group["name"] for group in stageGroups(settings, stage)]


def stageExists(settings, stage):
    """Есть ли в проекте этап с ключом ``stage`` (хотя бы один курс этого потока или блока)."""
    return bool(stageGroups(settings, stage))


def stageLabel(stage, translate):
    """Название этапа для людей: «Поток 2» или перевод блока (``stage.<ключ>`` в ru.hjson)."""
    if isBlockStage(stage):
        return translate(f"stage.{stage}")

    return f"{translate('stage.stream')} {stage}"


def stageDates(settings, stage):
    """(начало, конец) этапа: от самого раннего старта до самого позднего окончания его курсов.

    Для этапа без курсов — весь возможный промежуток.
    """
    dates = [courseDates(settings, group) for group in stageGroups(settings, stage)]

    if not dates:
        return "0000-00-00", "9999-99-99"

    return min(start for start, _ in dates), max(end for _, end in dates)


# ---------------------------------------------------------------- этапы в принятом расписании

def acceptedStages(settings, answer):
    """Этапы с принятым вариантом: хотя бы один их урок есть в расписании.

    В отличие от ``builtStages``, сюда попадает и этап, часть уроков которого
    разместить не удалось. Уроки копий не в счёт (``countedCourses``): их ставит поток-источник,
    а этот этап могли ещё ни разу не составлять.
    """
    copies = jointCopies(settings)

    return [
        stage["key"] for stage in getStages(settings)
        if any(hasLessons(answer, course) for course in countedCourses(settings, stage["key"], copies))
    ]


def stageTotals(settings, answer, courses):
    """Пара (сколько уроков нужно курсам ``courses``, сколько из них стоит в расписании).

    ``courses`` — имена курсов (обычно — курсы одного этапа). Нужное число — сумма уроков
    в неделю по всем предметам курса. Лишние уроки курса (больше, чем ему положено)
    не засчитываются, чтобы один «перебор» не скрыл нехватку у другого курса.
    """
    expected = placed = 0

    for course in courses:
        hours = courseHours(settings, course)
        expected += hours
        placed += min(hours, sum(1 for _ in lessonEntries(answer, course)))

    return expected, placed


def stageBuilt(settings, answer, stage):
    """«Этап построен»: он есть в расписании (хотя бы один урок) и все его уроки расставлены.

    Единственное определение: по нему и стартовый экран считает «построено N этапов из M»,
    и вкладка «Запуск» отмечает этап готовым. Этап, у всех курсов которого 0 уроков в неделю,
    построен, только если его уроки всё же стоят в расписании. Копии не в счёт (``countedCourses``).
    """
    courses = countedCourses(settings, stage)
    expected, placed = stageTotals(settings, answer, courses)

    return any(hasLessons(answer, course) for course in courses) and placed >= expected


def builtStages(settings, answer):
    """Ключи построенных этапов (``stageBuilt``) в порядке ``getStages``."""
    return [stage["key"] for stage in getStages(settings) if stageBuilt(settings, answer, stage["key"])]


def stageCopies(settings, stage, copies=None):
    """Курсы-копии этапа ``stage``: {копия: источник} (источник — в более раннем потоке).

    ``copies`` — уже прочитанные joint.jointCopies, чтобы не читать их ещё раз.
    """
    stage_names = set(stageCourses(settings, stage))

    return {name: source for name, source in (jointCopies(settings) if copies is None else copies).items() if name in stage_names}


def ownCourses(settings, stage, copies=None):
    """Курсы этапа, уроки которых подбирает сборка: все, кроме копий (их уроки ставит поток-источник).

    Порядок — как в проекте. ``copies`` — уже прочитанные joint.jointCopies.
    """
    fixed = stageCopies(settings, stage, copies)

    return [course for course in stageCourses(settings, stage) if course not in fixed]


def countedCourses(settings, stage, copies=None):
    """Курсы, по которым судят, есть ли этап в расписании, построен ли он и сколько уроков ему
    не хватает (``acceptedStages``, ``stageBuilt``, «Запуск»).

    Это ``ownCourses``: копии, которые ждут поток-источник, не делают этап недостроенным, а уроки
    копий не делают этап составленным — его могли ещё ни разу не составлять. У этапа из одних копий
    других уроков нет — тогда это его копии: этап в расписании, когда принят поток-источник.
    """
    return ownCourses(settings, stage, copies) or stageCourses(settings, stage)


def startedCourses(settings, answer, courses, complete=True, shared=True):
    """Курсы из ``courses``, которые уже начались и есть в принятом расписании.

    ``complete=True`` — только «зафиксированные» курсы (courseLocked: курс идёт и все его
    уроки расставлены — время и число уроков больше не меняются);
    ``complete=False`` — любой начавшийся курс с уроками (courseStarted: «курс уже идёт»).
    Курс-источник считается идущим и тогда, когда идёт хотя бы одна его копия: его уроки —
    это и её уроки, поэтому менять их уже нельзя.
    ``shared=False`` — без этого правила: только курсы, которые начались сами (ученики их потока
    уже ходят). Так говорят с завучем о «начавшихся потоках» и «уроках, которые пропадут у учеников»:
    источник, который идёт только через копию, менять нельзя, но его поток ещё не начался.
    Возвращает множество имён курсов.
    """
    check = courseLocked if complete else courseStarted
    groups = groupsByName(settings)
    # Копии каждого источника (как joint.jointGroup, но одним чтением на все курсы); у копии и
    # обычного курса проверяется только он сам
    followers = copyFollowers(jointCopies(settings)) if shared else {}

    return {
        course for course in courses
        if course in groups and any(
            check(settings, answer, member, subject)
            for subject in groups[course].get("subjects", []) for member in [course] + followers.get(course, [])
        )
    }


def changeableCourses(settings, answer, stage, complete=True):
    """Курсы этапа, которые сборка может менять: все, кроме идущих (при ``complete=True`` — только
    зафиксированных: идут и все уроки на месте) и копий; порядок — как в проекте.

    ``complete`` — как в ``startedCourses``: True — кроме зафиксированных (принятие варианта,
    переставленные уроки), False — кроме всех идущих («Убрать из расписания»).
    Уроки копий задаёт поток-источник, поэтому ни принятие варианта, ни «Убрать из расписания»
    их не трогают.
    """
    courses = stageCourses(settings, stage)
    fixed = startedCourses(settings, answer, courses, complete) | set(stageCopies(settings, stage))

    return [course for course in courses if course not in fixed]


def lockedFromAnswer(settings, answer, stage, variant):
    """Вариант ``variant`` этапа ``stage`` таким, каким его сохранит принятие: зафиксированные курсы этапа
    (идут и все уроки на месте; не копии) — из принятого расписания ``answer``.

    Принятие берёт из варианта только ``changeableCourses`` (``mergeStageAnswer``), а сборка получает
    идущие курсы неподвижными. Но вариант могли собрать, пока курс ещё не шёл: с тех пор наступила
    дата начала или число уроков снизили до уже стоящих — курс стал зафиксированным, а в файле
    варианта у него остались другие уроки или другой преподаватель. Без этой подмены «Кто ведёт»,
    карточки недели, оценки варианта и вопрос о лимите курсов показывали бы то, чего принятие
    не сделает (как joint.followSources для копий). Меняет ``variant`` на месте и возвращает его.
    """
    changeable = set(changeableCourses(settings, answer, stage))

    for course in ownCourses(settings, stage):
        # У зафиксированного курса уроки в answer есть всегда: без них курс не «идёт»
        if course not in changeable:
            variant[course] = copy.deepcopy(answer[course])

    return variant


def staleStarted(settings, answer, stage, variant, built=None):
    """Курсы этапа ``stage``, которые уже идут, но вариант ``variant`` собран до их начала: он сдвинул
    бы их уроки или сменил им преподавателя. Список имён в порядке проекта; пустой — вариант годится.

    Правило заказчика: у начавшегося курса время и преподаватель больше не меняются. Зафиксированные
    курсы (идут и все уроки на месте) принятие и так берёт из расписания (``lockedFromAnswer``).
    А идущий курс, которому ещё не хватает уроков, принятие берёт из варианта — чтобы он получил
    недостающие. Свежая сборка такой курс не трогает: закрепляет все его уроки из расписания и его
    преподавателя (solver_input.pinPlan, courses.sharedStarted — курс-источник идёт и тогда, когда
    идёт его копия). Но вариант могли собрать, пока курс ещё не шёл, — тогда в нём у курса бывают
    другие часы или другой преподаватель. Такой курс здесь и находится:
    * не каждый его урок из расписания ``answer`` стоит в варианте на том же месте с тем же предметом;
    * или на каком-то его уроке в варианте нет преподавателя либо есть преподаватель, которого
      на уроках курса в расписании не было.
    Преподаватели, которых уже нет в проекте, не сравниваются ни с одной стороны (их удалили после
    сборки — принятие их тоже уберёт, variants.dropUnknownTeachers); если в расписании у курса не
    осталось ни одного преподавателя из проекта, сверяется только время (сборка тоже оставляет
    такой курс как есть). Копии не проверяются: их уроки — уроки источника.
    ``built`` — курсы, которые шли уже при сборке варианта (variants.buildStarted); их здесь не проверяют:
    вариант для них не «собран до начала», их проверяет ``movedStarted``. Курс, чьи уроки в расписании
    с начала сборки поменялись (приняли другой вариант, вернули версию), buildStarted в ``built`` не кладёт:
    вариант собран по прежнему расписанию — здесь он и найдётся.
    None — неизвестно (варианты старой программы): проверяются все идущие курсы.
    """
    built = built or set()
    courses = [name for name in changeableCourses(settings, answer, stage) if name not in built]

    return [course for course, _ in startedChanges(settings, answer, variant, courses)]


def movedStarted(settings, answer, stage, variant, built, context=None):
    """Курсы этапа ``stage``, которые шли уже при сборке варианта (``built``, variants.buildStarted),
    а вариант всё равно сдвинул им урок или сменил преподавателя. Такой вариант не принимается
    (решение заказчика 06.10.2026): у идущего курса время и преподаватель не меняются.

    Сборка закрепляет уроки и преподавателя идущих курсов (solver_input.pinPlan), но решатель
    не ставит закрепление, если прежнее место стало невозможным: преподаватель отметил «не может»,
    в это время у него урок другого этапа, изменилась сетка. Тогда каждая новая сборка даст такой же
    вариант, пока завуч не уберёт причину, — поэтому причина называется.

    Возвращает [(курс, [(день, урок, причина, подробность)])] в порядке проекта; причины:
    * как у ``pinConflicts`` — для прежнего места урока в расписании ``answer``;
    * "noteacher" / "lostsubject" — у преподавателя курса больше нет его предмета (``teacherLeft``: курс
      некому вести / его поведёт другой преподаватель); одна строка на курс, подробность — этот
      преподаватель, место — первый урок курса в расписании, как у ``blockedStarted``;
    * "unplaced" — помеху найти не удалось (возможно, её уже убрали);
    * "teacher" — время то же, но урок ведёт другой преподаватель (подробность — прежний преподаватель,
      место — первый такой урок).
    Пустой ``built`` или None — ничего (None проверяет ``staleStarted``). ``context`` — уже собранный
    ``pinContext`` этапа; без него он собирается здесь, если понадобится.
    """
    courses = [name for name in changeableCourses(settings, answer, stage) if name in (built or set())]
    result = []

    for course, (subject, moved, teachers, changed) in startedChanges(settings, answer, variant, courses):
        teacher = startedTeacher(settings, answer, course)
        left = teacherLeft(settings, course, subject, teacher)

        if left:
            # Место — первый урок курса в расписании, как у blockedStarted
            reasons = [(*(courseSlots(answer, course, subject) or moved or [changed])[0], left, teacher)]

        elif not moved:
            reasons = [(*changed, "teacher", ", ".join(sorted(teachers)))]

        else:
            context = context or pinContext(settings, answer, stage)
            found = pinConflicts(context, course, subject, moved, teacher)
            reasons = [reason for slot in moved for reason in found.get(slot, [(*slot, "unplaced", "")])]

        result.append((course, reasons))

    return result


def startedTeacher(settings, answer, course):
    """Преподаватель идущего курса для сборки: тот, кто стоит на его уроках в расписании (первый найденный),
    если он ещё есть в проекте; иначе None — тогда сборка курс не получает и переносит его уроки
    в варианты как есть (solver_input.pinPlan).
    """
    teachers = [name for _, _, entry in lessonEntries(answer, course) for name in entry.get("teachers", [])]

    return teachers[0] if teachers and teachers[0] in settings.get("teachers", {}) else None


def teacherLeft(settings, course, subject, teacher):
    """Почему преподаватель идущего курса ``teacher`` (``startedTeacher``) не поведёт его уроки по
    предмету ``subject``: у него больше нет этого предмета (во входе решателя «ведёт» курс только
    преподаватель предмета, courses.assignTeacher).

    "noteacher" — и «может вести» курс никто: решатель его уроки не ставит, даже закреплённые
    (solver_input.pinForecast считает их в noTeacher); "lostsubject" — курс поведёт другой преподаватель
    из «может вести», а у идущего курса преподаватель не меняется. None — предмет у преподавателя есть
    или преподавателя из проекта нет (тогда курс переходит в варианты как есть).
    """
    if teacher is None or teacher in subjectTeachers(settings, subject):
        return None

    return "noteacher" if nobodyTeaches(settings, course, subject, teacher) else "lostsubject"


def startedPins(settings, answer, stage):
    """Идущие курсы этапа, чьи уроки из расписания сборка закрепляет вместе с преподавателем
    (solver_input.pinPlan): [(курс, предмет, места [(день, урок)] в расписании, преподаватель,
    зафиксирован)] в порядке проекта.

    Преподаватель — ``startedTeacher``; курса без преподавателя из проекта здесь нет: решатель его
    не получает, а его уроки переходят в варианты как есть. Зафиксированные курсы (идут и все уроки
    на месте) решатель тоже получает с закреплениями, но в варианты их переносит из расписания сборка
    (build._fixedCourses): их закрепления важны прогнозу (solver_input.pinForecast) и курсам, которые
    решатель ставит после них (``pinContext``), но не принятию варианта.
    """
    rebuilt = set(changeableCourses(settings, answer, stage, complete=False))
    changeable = set(changeableCourses(settings, answer, stage))
    groups = groupsByName(settings)
    result = []

    for course in ownCourses(settings, stage):
        teacher = startedTeacher(settings, answer, course)

        if course in rebuilt or teacher is None:
            continue

        result += [
            (course, subject, courseSlots(answer, course, subject), teacher, course not in changeable)
            for subject in groups[course].get("subjects", []) if sharedStarted(settings, answer, course, subject)
        ]

    return result


def pinContext(settings, answer, stage):
    """Что видит решатель, когда ставит закреплённые уроки этапа ``stage`` (раздел 5 solve.cpp), —
    для ``pinConflicts``. Собирается один раз на этап: им пользуются ``blockedStarted``, ``movedStarted``
    и вход решателя с прогнозом (solver_input.pinStartedCourses, solver_input.pinForecast).

    Решатель ставит закрепления по курсам в порядке их имён (во входе это словарь, ключи по алфавиту),
    каждое — с учётом того, что уже стоит:
    * уроки, которые стоят при любой сборке (``standingCourses``): других этапов в даты этапа и копий
      этапа — их преподаватель занят (solver_input.flattenAvailability), их программа закрывает время
      (solver_input.programBlockedSlots, blockFixedCourses); и выброшенные идущие курсы этапа без
      преподавателя — только пары и программы (их преподавателя решатель не видит);
    * закрепления курсов этапа, поставленные раньше: уроки идущих курсов (``startedPins``; курс, который
      некому вести, не ставится вовсе, а у курса, чей преподаватель потерял предмет, преподаватель
      неизвестен) и ручные закрепления курсов, которые ещё не начались, с преподавателем из «ведёт».
      Они мешают только курсу, чьё имя по алфавиту позже.
    Ручные закрепления идущих курсов и уроки курсов из «Оставить уже принятые уроки на месте» не
    учитываются: в согласованном расписании они не мешают урокам идущих курсов.

    Возвращает словарь: "lessons" — {(день, урок): [(курс, предмет, [преподаватели], причина, порядок)]},
    причина — "busy" (урок из расписания) или "elsewhere" (ручное закрепление), порядок — имя курса
    (мешает только курсам с именем позже) или None (мешает всем); "solver" — курсы этапа, которые
    получает решатель; "started" — ``startedPins``; служебные "settings", "stage", "groups",
    "pinned" (pinnedForTeacher по преподавателям) и "memo" (уже найденное ``pinConflicts``).
    """
    groups = groupsByName(settings)
    copies = jointCopies(settings)
    own = ownCourses(settings, stage, copies)
    rebuilt = set(changeableCourses(settings, answer, stage, complete=False))
    started = startedPins(settings, answer, stage)
    lessons = {}

    def add(slot, course, subject, teachers, reason, order):
        """Записывает урок или закрепление ``course`` в место ``slot``."""
        lessons.setdefault(slot, []).append((course, subject, teachers, reason, order))

    for course in standingCourses(settings, answer, stage, groups, copies):
        for day, lesson, cell in lessonEntries(answer, course):
            add((day, lesson), course, cell.get("subject"), cell.get("teachers", []), "busy", None)

    for course in own:
        if course in rebuilt:
            for subject in groups[course].get("subjects", []):
                staff = [
                    name for name, data in settings.get("teachers", {}).items()
                    if any(item.get("subject") == subject and course in item.get("assigned", []) for item in data.get("subjects", []))
                ]

                for slot in pinnedSlots(settings, course, subject):
                    add(slot, course, subject, staff, "elsewhere", course)

        elif startedTeacher(settings, answer, course) is None:
            for day, lesson, cell in lessonEntries(answer, course):
                add((day, lesson), course, cell.get("subject"), [], "busy", None)

    for course, subject, slots, teacher, _ in started:
        left = teacherLeft(settings, course, subject, teacher)

        for slot in slots if left != "noteacher" else []:
            add(slot, course, subject, [] if left else [teacher], "busy", course)

    return {
        "settings": settings, "stage": stage, "groups": groups, "lessons": lessons, "solver": set(own),
        "started": started, "pinned": {}, "memo": {},
    }


def pinConflicts(context, course, subject, slots, teacher, later=False):
    """Почему решатель не поставит закреплённые уроки курса ``course`` этапа на места ``slots``
    [(день, урок)], если их ведёт ``teacher`` (None — преподаватель неизвестен, его помехи не ищутся):
    {(день, урок): [(день, урок, причина, подробность)]} — только места с помехами. ``context`` —
    ``pinContext`` этапа: помехи — то, что видит решатель. ``later`` — помехой считаются и уроки идущих
    курсов, чьё имя позже: решатель поставил бы закрепление ``course`` первым и отверг бы такой урок
    (solver_input.plannedPins).

    Причины — как у courses.slotConflicts:
    * "missing" — такого урока нет в сетке;
    * "unavailable" — у ``teacher`` на этапе это время отмечено «не может» (подробность — он сам);
    * "busy" — ``teacher`` в это время ведёт урок курса-подробности: другого этапа (в даты этапа),
      копии этапа или идущего курса этапа, чьё имя по алфавиту раньше;
    * "elsewhere" — у ``teacher`` в это время закреплён вручную урок курса-подробности, которого в это
      время нет в расписании: курса другого этапа (stages.pinnedForTeacher; решатель считает это время
      занятым) или курса этапа, который ещё не начался и чьё имя раньше;
    * "pair" и "program" — в это время стоит или закреплён курс-подробность той же линейки с парой
      «нельзя» или программы, которая не должна пересекаться с нашей, по тому же предмету.
    """
    key = (course, subject, tuple(slots), teacher, later)

    if key in context["memo"]:
        return context["memo"][key]

    settings, stage, groups = context["settings"], context["stage"], context["groups"]
    group = groups[course]
    hard_pairs = subjectPairs(settings, "joint_subject_pairs")
    programs = programPairs(settings)
    cannot = cannotSlots(settings, teacher, stage) if teacher else []

    if teacher not in context["pinned"]:
        context["pinned"][teacher] = pinnedForTeacher(settings, teacher, stage) if teacher else {}

    result = {}

    for day, lesson in slots:
        if not lessonExists(settings, day, lesson):
            result[(day, lesson)] = [(day, lesson, "missing", "")]
            continue

        found = [(day, lesson, "unavailable", teacher)] if [day, lesson] in cannot else []

        for other, other_subject, teachers, reason, order in context["lessons"].get((day, lesson), []):
            # Порядок есть только у закреплений этапа; "busy" среди них — уроки идущих курсов
            if other == course or (order is not None and order > course and not (later and reason == "busy")):
                continue

            peer = groups.get(other, {})

            if teacher in teachers:
                found.append((day, lesson, reason, other))

            if sameLine(group, peer) and isSubjectPair(hard_pairs, subject, other_subject):
                found.append((day, lesson, "pair", other))

            if (group.get("program"), peer.get("program")) in programs and other_subject == subject:
                found.append((day, lesson, "program", other))

        found += [
            (day, lesson, "elsewhere", other) for other in context["pinned"][teacher].get((day, lesson), [])
            if other not in context["solver"] and (day, lesson, "busy", other) not in found
        ]

        if found:
            result[(day, lesson)] = list(dict.fromkeys(found))

    context["memo"][key] = result

    return result


def blockedStarted(settings, answer, stage, context=None):
    """Ещё до сборки: уроки идущих курсов этапа (``startedPins``, кроме зафиксированных: их в варианты
    переносит сборка), которые решатель не сможет оставить как есть, — [(курс, [(день, урок, причина,
    подробность)])] в порядке проекта (причины — как у ``movedStarted``, без "unplaced" и "teacher").
    Каждый вариант такой сборки сдвинет эти уроки или сменит курсу преподавателя, и принять его будет
    нельзя (``movedStarted``) — «Запуск» предупреждает об этом заранее. ``context`` — уже собранный
    ``pinContext`` этапа.
    """
    context = context or pinContext(settings, answer, stage)
    result = []

    for course, subject, slots, teacher, locked in context["started"]:
        if locked:
            continue

        left = teacherLeft(settings, course, subject, teacher)

        if left:
            reasons = [(*slot, left, teacher) for slot in slots[:1]]

        else:
            found = pinConflicts(context, course, subject, slots, teacher)
            reasons = [reason for slot in slots for reason in found.get(slot, [])]

        if reasons:
            result.append((course, reasons))

    return result


def startedChanges(settings, answer, variant, courses):
    """Идущие курсы из ``courses``, которым вариант ``variant`` сдвинул бы уроки или сменил преподавателя.

    Курс найден, если по предмету, по которому он идёт (courses.sharedStarted):
    * не каждый его урок из расписания ``answer`` стоит в варианте на том же месте с тем же предметом;
    * или на каком-то его уроке в варианте нет преподавателя либо есть преподаватель, которого
      на уроках курса в расписании не было.
    Преподаватели, которых уже нет в проекте, не сравниваются ни с одной стороны; если в расписании
    у курса не осталось ни одного преподавателя из проекта, сверяется только время.

    Возвращает [(курс, (предмет, сдвинутые места [(день, урок)] по порядку, преподаватели курса
    в расписании, первое место варианта с другим преподавателем или None))] в порядке ``courses``.
    """
    known = set(settings.get("teachers", {}))
    groups = groupsByName(settings)
    result = []

    def staff(cell):
        """Преподаватели урока, которые ещё есть в проекте."""
        return {name for name in cell.get("teachers", []) if name in known}

    for course in courses:
        for subject in groups[course].get("subjects", []):
            if not sharedStarted(settings, answer, course, subject):
                continue

            now = {(day, lesson): cell for day, lesson, cell in lessonEntries(answer, course) if cell.get("subject") == subject}
            new = {(day, lesson): cell for day, lesson, cell in lessonEntries(variant, course) if cell.get("subject") == subject}
            teachers = set().union(*(staff(cell) for cell in now.values()))
            moved = [slot for slot in sorted(now) if slot not in new]
            # На каждом уроке варианта — только преподаватели курса из расписания, и хотя бы один
            changed = next((slot for slot, cell in sorted(new.items()) if teachers and (not staff(cell) or not staff(cell) <= teachers)), None)

            if moved or changed:
                result.append((course, (subject, moved, teachers, changed)))
                break

    return result


def allStarted(settings, answer, stage):
    """Сборке нечего менять: все курсы этапа зафиксированы (идут и все уроки на месте) или копии.

    Этап, в котором только копии, тоже «нечего менять»: их уроки задаёт поток-источник.
    """
    courses = stageCourses(settings, stage)

    return bool(courses) and not changeableCourses(settings, answer, stage)


def mergeStageAnswer(answer, stage_answer, courses):
    """Общее расписание, в котором курсы ``courses`` взяты из ``stage_answer`` (варианта этапа).

    Курсы других этапов остаются из ``answer``. Курсы этапа, которых нет в ``stage_answer``,
    из результата пропадают. Исходные словари не меняются.
    """
    courses = set(courses)

    merged = {name: value for name, value in answer.items() if name not in courses}
    merged.update({name: value for name, value in stage_answer.items() if name in courses})

    return merged


# ---------------------------------------------------------------- занятость преподавателей

def standingCourses(settings, answer, stage, groups, copies):
    """Курсы расписания ``answer``, чьи уроки при сборке этапа ``stage`` стоят как есть и занимают время
    (``occupiedByOtherStages``, ``pinContext``): курсы других этапов, чьи даты пересекаются с датами
    этапа, и копии самого этапа — при любых датах источника, последними (в слоте общего урока остаётся
    копия, а не источник). Копии других этапов, чей источник в этапе ``stage``, — нет: это уроки самого
    строящегося этапа. ``groups`` и ``copies`` — уже прочитанные groupsByName и joint.jointCopies.
    """
    own_copies = stageCopies(settings, stage, copies)
    # Курс, который закончился до начала этапа (или начнётся после его конца), ничьё время не занимает
    dates = stageDates(settings, stage)

    return [
        course for course in sorted(answer, key=lambda name: name in own_copies)
        if course in groups and (course in own_copies or not (
            stageKey(groups[course]) == stage
            or (course in copies and stageKey(groups[copies[course]]) == stage)
            or not datesOverlap(courseDates(settings, groups[course]), dates)
        ))
    ]


def occupiedByOtherStages(settings, answer, stage):
    """Уроки, уже стоящие в других этапах и пересекающиеся с этапом ``stage`` по датам.

    Возвращает тройку:
    * ``teachers`` — преподаватель -> {(день, урок): курс}: когда он уже занят;
    * ``program_slots`` — (программа, предмет) -> {(день, урок)}: где уже стоят уроки
      программы (нужно для правила «программы не пересекаются», напр. семинары и
      ЕГЭ продвинутый);
    * ``courses_by_teacher`` — преподаватель -> {курсы других этапов}: сколько курсов
      у него уже есть (для лимита курсов на преподавателя).

    Копии этапа ``stage`` сборка не меняет — их уроки здесь тоже «уже стоят», при любых датах
    источника (в слоте общего урока записана копия). Копии других этапов, чей источник в этапе
    ``stage``, пропускаются: это уроки самого строящегося этапа, их можно оставить на месте или
    сдвинуть. В ``courses_by_teacher`` курс записан своим источником (joint.jointRoot): источник
    и копия — один курс в лимите.
    """
    groups = groupsByName(settings)
    copies = jointCopies(settings)

    teachers = {}
    program_slots = {}
    courses_by_teacher = {}

    for course in standingCourses(settings, answer, stage, groups, copies):
        program = groups[course].get("program", course)

        for day, lesson, entry in lessonEntries(answer, course):
            program_slots.setdefault((program, entry.get("subject")), set()).add((day, lesson))

            for teacher in entry.get("teachers", []):
                teachers.setdefault(teacher, {})[(day, lesson)] = course
                courses_by_teacher.setdefault(teacher, set()).add(copyRoot(copies, course))

    return teachers, program_slots, courses_by_teacher


def pinnedForTeacher(settings, teacher, stage):
    """{(день, урок): [курсы]} — где преподаватель закреплён за курсом и урок курса закреплён.

    «Закреплённый урок» — запись в ``settings["constants"]`` (пользователь поставил урок
    на конкретное время вручную). Если преподаватель назначен на курс (``assigned``), то
    закреплённые уроки этого курса по его предмету — гарантированно его время.
    В одном слоте может быть несколько таких курсов, поэтому значение — список имён курсов:
    его сверяют с курсами этапа (solver_input.flattenAvailability), а склеивает имена через
    « и » только показ (``teacherCommitments``).
    Учитываются только курсы, чьи даты пересекаются с датами этапа ``stage``, и источники копий
    этапа при любых датах: копия встанет в часы источника. Закрепления самих копий не в счёт:
    время копии задаёт источник (такие записи остаются только от ручной правки файла).
    """
    result = {}
    groups = groupsByName(settings)
    dates = stageDates(settings, stage)
    copies = jointCopies(settings)
    sources = set(stageCopies(settings, stage, copies).values())

    for item in settings.get("teachers", {}).get(teacher, {}).get("subjects", []):
        for course in item.get("assigned", []):
            if course in copies or (course in groups and course not in sources and not datesOverlap(courseDates(settings, groups[course]), dates)):
                continue

            # constants: {курс: {"день-урок": предмет}} — берём закрепления по предмету преподавателя
            for key, subject in settings.get("constants", {}).get(course, {}).items():
                if subject == item.get("subject"):
                    result.setdefault(pinSlot(key), []).append(course)

    return result


def teacherCommitments(settings, answer, teacher, stage):
    """Что уже занимает время преподавателя на этапе — так, как это видно на вкладке «Преподаватели».

    ``{(день, урок): ("busy", курс)}`` — уроки, построенные в других этапах;
    ``{(день, урок): ("pinned", курс)}`` — закреплённые уроки курсов, за которыми
    преподаватель закреплён. Несколько курсов в одном слоте пишутся через « и »; если в слоте
    и то и другое, показывается «busy»: сначала построенный курс, затем остальные закреплённые
    (сам построенный курс второй раз не повторяется).
    ``{(день, урок): ("joint", источник)}`` — общий урок копии этапа и её источника: это не «занят»
    чужим уроком и не отметка, которую можно менять, а тот же урок; время задаёт поток-источник,
    поэтому назван источник, а его закрепление второй раз не называется.
    """
    pinned = pinnedForTeacher(settings, teacher, stage)
    result = {slot: ("pinned", " и ".join(names)) for slot, names in pinned.items()}
    copies = jointCopies(settings)
    own_copies = stageCopies(settings, stage, copies)

    for slot, course in occupiedByOtherStages(settings, answer, stage)[0].get(teacher, {}).items():
        # Курс слота и его источник (как joint.jointRoot) — один урок, закрепления этого источника не повторяются
        root = copyRoot(copies, course)
        others = [name for name in pinned.get(slot, []) if name not in (course, root)]
        result[slot] = ("joint", " и ".join([root] + others)) if course in own_copies else ("busy", " и ".join([course] + others))

    return result


def teacherClashes(settings, answer, teacher=None):
    """Накладки: два урока одного преподавателя в одно время в курсах с пересекающимися датами.

    Нужны вкладке «Преподаватели» (карточка преподавателя) и предупреждениям над «Расписанием».
    Возвращает ``[(преподаватель, день, урок, [курсы])]`` — в списке курсов каждый курс
    слота, который пересекается по датам хотя бы с одним другим курсом этого слота.
    С ``teacher`` проверяется только этот преподаватель.
    Уроки в одно время у курсов, идущих в разные месяцы, накладкой не считаются.
    Общий урок источника и его копии — один урок (сравниваются источники, как joint.jointRoot):
    накладка только с курсом другой группы.
    """
    groups = groupsByName(settings)
    copies = jointCopies(settings)
    at = {}

    # Собираем, какие курсы у каждого преподавателя стоят в каждом слоте
    for course in answer:
        if course not in groups:
            continue

        for day, lesson, entry in lessonEntries(answer, course):
            for name in entry.get("teachers", []):
                if teacher is None or name == teacher:
                    at.setdefault((name, day, lesson), []).append(course)

    result = []

    # Накладка — только если в слоте есть хотя бы два курса, идущих одновременно по датам
    for (name, day, lesson), courses in sorted(at.items()):
        clashing = [
            course for course in courses
            if any(
                copyRoot(copies, other) != copyRoot(copies, course) and coursesOverlap(settings, groups[course], groups[other])
                for other in courses
            )
        ]

        if clashing:
            result.append((name, day, lesson, clashing))

    return result
