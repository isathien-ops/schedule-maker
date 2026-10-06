"""«Линейка идёт вместе с Потоком N»: курсы-копии, их источники и синхронизация копий с источниками.

Ученики двух потоков ходят на одни и те же уроки линейки (например, «ЕГЭ основной» Потоков 1 и 2).
Тогда линейка более позднего потока (поток-копия) отмечена «идёт вместе с Потоком N»: у каждого её
курса, предмет которого есть в той же линейке Потока N, поле ``together_with = N`` — это курс-копия.
Курс-источник — курс того же предмета той же линейки Потока N. Его имя строится через
courses.courseName, а не разбором названия копии. Источник всегда корневой: копия копии запрещена
(``setJointLine``), поэтому «источник + его копии» — одна ступень, без цепочек.

Что держит модуль
-----------------
* У копии часы (``classes.lessons``) как у источника, нет закреплений (``constants``) и её никто
  не «ведёт»: время, преподавателя и число уроков задаёт поток-источник.
* В answer у копии те же уроки, что у источника (``deepcopy``), а если у источника уроков нет —
  ключа копии нет («ждёт Поток N»). Уроки копии настоящие: календарь, версии и «Расписание»
  работают с ней как с любым курсом. Не считать пару «источник + копия» дважды (накладки, лимит
  курсов, занятость) — забота читателей: модуль ниже этого (courses) и модули над ним (stages,
  export, src/web/state.py) сводят пару через courses.copyRoot / sharedCourses / copyFollowers от один раз
  прочитанных copySources. ``jointRoot`` и ``jointGroup`` — обёртки для разового вызова от settings:
  ``jointRoot`` нужна вкладке «Курсы» (новый курс стал копией?), ``jointGroup`` — отказу has_copies
  в ``setJointLine``.
* Отметку ставит и снимает только ``setJointLine``. После любых других правок (принятие варианта,
  закрепления, преподаватель источника, удаление курсов) копии догоняют источник через
  ``syncJointSettings`` и ``syncJointAnswer``: их вызывают запись проекта (src/web/project.py)
  и его открытие (tree.prepareProject).
* Источник пропал (удалён курс, линейка или поток) — копия мягко становится обычной: читатели
  получают None, ``syncJointSettings`` убирает поле, а уроки копии остаются (если ученики потока-копии
  уже ходят, их уроки не должны исчезнуть из-за удаления в другом потоке).

Функции
-------
    чтение         jointSource (источник курса), jointCopies (все копии проекта), jointRoot
                   (источник или сам курс), jointGroup («источник + копии»), lineJoint (с каким
                   потоком идёт линейка), jointOptions (какие потоки можно выбрать)
    запись         setJointLine — единственная, кто ставит и снимает поле; sameLessons (одинаковы ли
                   уроки двух курсов) и alignCopies (часы источника, без закреплений и «ведёт») —
                   её шаги, alignCopies нужна и syncJointSettings
    синхронизация  syncJointSettings (поля без источника, часы, закрепления, «ведёт»),
                   syncJointAnswer (уроки копий), followSources (уроки копий в варианте или
                   другом расписании — из расписания, где стоят источники)
    помехи         copyConflicts — чем новые часы или новый преподаватель общих уроков мешают соседям
                   копии в её даты (её поток, блоки, другие потоки — кроме этапа источника);
                   copyCannot — общие уроки во время, где у преподавателя на этапе потока-копии
                   «не может» (не запрет, а предупреждение: вопросы setJoint и принятия варианта,
                   «Расписание»)

Само правило «копия и её источник» (только чтение поля) — courses.py, раздел 7: copySource,
copySources, sharedCourses, lineTogetherWith и помощники от уже прочитанных копий (copyRoot,
copiesOf, copyFollowers); функции чтения здесь — их обёртки от settings.

Зависимости: model, courses.
"""

import copy

from src.modules.functions.courses import (
    assignTeacher, copyRoot, copySource, copySources, courseName, courseStarted, lessons, lineCourses, lineTogetherWith,
    peerSlotConflicts, sharedCourses, streamIds
)
from src.modules.functions.model import (
    cannotSlots, courseGroups, courseSubject, groupsByName, hasLessons, isBlock, lessonEntries, stageKey
)


# ---------------------------------------------------------------- чтение
# Само правило «какой курс — копия и чья» записано в courses.py (раздел 7): оно нужно и ему для
# накладок, лимита и переноса уроков, а courses.py ниже этого модуля. Здесь — чтение от settings.

def jointSource(settings, group):
    """Имя курса-источника курса ``group`` (словарь курса) или None, если курс не копия.

    Мягкое чтение: пропавший источник — тоже None, хотя поле ещё может стоять до записи проекта
    (правило — courses.copySource).
    """
    return copySource(group, groupsByName(settings))


def jointCopies(settings):
    """Все курсы-копии проекта с живым источником: {копия: источник} в порядке курсов."""
    return copySources(groupsByName(settings))


def jointRoot(settings, name):
    """Курс, который отвечает за уроки курса ``name``: источник у копии, у остальных — сам ``name``.

    По нему читатели сводят пару «источник + копия» к одному курсу: один урок, один курс в лимите.
    """
    return copyRoot(jointCopies(settings), name)


def jointGroup(settings, name):
    """Группа курса ``name``: [источник, его копии…]; у обычного курса — [name].

    Нужна ``setJointLine`` для отказа has_copies: у линейки-источника уже есть копии в других
    потоках. «Курс уже идёт» по всей группе считают courses.sharedStarted / sharedLocked.
    """
    return sharedCourses(jointCopies(settings), name)


def lineJoint(settings, section, line):
    """Номер потока, вместе с которым идёт линейка ``line`` раздела ``section``, или None
    (courses.lineTogetherWith).
    """
    return lineTogetherWith(settings, section, line)


def jointOptions(settings, section, line):
    """Потоки, которые можно выбрать в «Присоединяется к» у линейки ``line`` раздела ``section``.

    Это более ранние потоки (по номеру), где есть линейка с тем же названием и хотя бы одним таким же
    предметом, как в этой линейке, и которые сами ни с кем не идут: источник всегда корневой. Поток без
    общего предмета не предлагается: присоединять там нечего — ни один курс не стал бы копией, а отметка
    «присоединена» ничего бы не значила. У блоков выбора нет. Список отсортирован.
    """
    if isBlock(section):
        return []

    subjects = {courseSubject(group) for group in lineCourses(settings, section, line)}

    return [stream for stream in streamIds(settings)
            if stream < section and subjects & {courseSubject(group) for group in lineCourses(settings, stream, line)}
            and lineJoint(settings, stream, line) is None]


# ---------------------------------------------------------------- запись

def sameLessons(answer, first, second):
    """Стоят ли у курсов ``first`` и ``second`` одни и те же уроки (место, предмет, преподаватели)."""
    return list(lessonEntries(answer, first)) == list(lessonEntries(answer, second))


def setJointLine(settings, section, line, source, answer, today=None):
    """Отмечает линейку ``line`` потока ``section`` «идёт вместе с Потоком ``source``»; None снимает отметку.

    Включение: курсы линейки, предмет которых есть в той же линейке Потока ``source``, получают
    ``together_with`` и становятся копиями (часы источника, без закреплений и «ведёт»); у остальных
    курсов линейки поля нет. Повторный вызов с тем же потоком добавляет в копии новые предметы
    («Добавить предмет» в отмеченной линейке). Уроки копий в answer ставит ``syncJointAnswer``
    при записи проекта.
    Снятие: поле убирается у всей линейки, уроки бывших копий удаляются из ``answer`` — курсы
    снова подбираются как обычные; часы остаются.
    Смена потока-источника (линейка была с Потоком 1, выбрали Поток 2): копии, предмет которых есть
    и в новом источнике, получают его уроки; бывшие копии, предмета которых там нет, становятся
    обычными курсами и теряют уроки, как при снятии (иначе у них остались бы общие уроки чужого
    потока, и преподаватель источника оказался бы занят дважды). Обычные курсы линейки, которые
    копиями не были, своих уроков не теряют.

    Отказ — ValueError(причина, номер потока), данные не меняются:
    - "invalid", None — блок, нет такой линейки, поток не раньше своего, в нём нет линейки или в ней
      нет ни одного такого же предмета (``jointOptions``);
    - "chain", N — выбранный поток сам идёт вместе с Потоком N (выбирать надо его);
    - "has_copies", N — с этой линейкой уже идёт Поток N: копией она стать не может;
    - "started", None — пропали бы или сменились бы уроки курса, который уже идёт
      (courses.courseStarted на дату ``today``).

    Возвращает отсортированный список курсов, чьи уроки в ``answer`` пропадут или сменятся. По нему
    сервер решает, спрашивать ли завуча и сохранять ли версию (пробный вызов на копии данных).
    Меняет ``settings`` и ``answer`` на месте.
    """
    courses = lineCourses(settings, section, line)

    if isBlock(section) or not courses:
        raise ValueError("invalid", None)

    by_name = groupsByName(settings)
    names = [group["name"] for group in courses]
    # Копии этой линейки до изменения: при снятии отметки или смене источника часть из них станет обычной
    former = {name: origin for name, origin in jointCopies(settings).items() if name in names}

    if source is None:
        affected = former
    else:
        if source not in jointOptions(settings, section, line):
            chained = lineJoint(settings, source, line) if source < section else None
            raise ValueError("chain" if chained is not None else "invalid", chained)

        # Потоки, которые уже идут вместе с этой линейкой: у курса-источника группа начинается
        # с него самого, за ним — его копии в других потоках
        groups = [jointGroup(settings, name) for name in names]
        followers = sorted(by_name[other]["stream_id"] for group in groups if group[0] in names for other in group[1:])

        if followers:
            raise ValueError("has_copies", followers[0])

        # Копиями становятся курсы, предмет которых есть в той же линейке потока source
        origins = {name: courseName(source, line, courseSubject(by_name[name])) for name in names}
        affected = {name: origin for name, origin in origins.items() if origin in by_name}

    # Бывшие копии, которые перестают быть копиями: при снятии — все, при смене источника — те, чьего
    # предмета в новом источнике нет. Их уроки (общие уроки прежнего источника) удаляются
    dropped = list(affected) if source is None else [name for name in former if name not in affected]
    # Уроки, которые пропадут (бывшие копии) или сменятся уроками источника (включение)
    changed = sorted({name for name in dropped if hasLessons(answer, name)} | {
        name for name, origin in affected.items()
        if source is not None and hasLessons(answer, name) and not sameLessons(answer, name, origin)
    })

    if any(courseStarted(settings, answer, name, courseSubject(by_name[name]), today) for name in changed):
        raise ValueError("started", None)

    for group in courses:
        if source is not None and group["name"] in affected:
            group["together_with"] = source
        else:
            group.pop("together_with", None)

    for name in dropped:
        answer.pop(name, None)

    if source is not None:
        alignCopies(settings, affected)

    return changed


# ---------------------------------------------------------------- синхронизация

def alignCopies(settings, copies):
    """Копии ``copies`` ({копия: источник}) получают часы источника и теряют закрепления и «ведёт»."""
    by_name = groupsByName(settings)
    load = lessons(settings)

    for name, source in copies.items():
        load[name] = copy.deepcopy(load.get(source, {}))
        settings.get("constants", {}).pop(name, None)
        # «Ведёт» снимается тем же правилом, что и выбор «авто» на вкладке «Курсы»
        assignTeacher(settings.get("teachers", {}), name, courseSubject(by_name[name]), None)


def syncJointSettings(settings):
    """Приводит отметки в ``settings`` к правилам; согласованный проект не меняется.

    Поле без источника (источник удалён) убирается: курс становится обычным, его уроки остаются.
    У каждой копии часы — как у источника (изменённые у источника, «Скопировать линейку», ручная
    правка файла), закреплений и «ведёт» нет. Меняет ``settings`` на месте и возвращает их.
    """
    by_name = groupsByName(settings)
    # Сначала выбираются все недействительные отметки, потом убираются: результат не зависит от порядка курсов
    stale = [group for group in courseGroups(settings) if "together_with" in group and copySource(group, by_name) is None]

    for group in stale:
        group.pop("together_with")

    alignCopies(settings, jointCopies(settings))

    return settings


def syncJointAnswer(settings, answer):
    """Ставит копиям в ``answer`` уроки источника; у источника нет уроков — ключа копии нет («ждёт»).

    Трогает только копии с живым источником: если источник уже удалён, а settings ещё не записаны,
    уроки бывшей копии остаются. Меняет ``answer`` на месте и возвращает его.
    """
    return followSources(settings, answer, answer)


def followSources(settings, sources, target, copies=None):
    """Ставит копиям ``copies`` ({копия: источник}; по умолчанию все копии проекта) в ``target`` уроки
    их источников из расписания ``sources``; у источника без уроков ключа копии в ``target`` нет.

    Так вариант потока-копии показывает и принимает общие уроки такими, какие они сейчас в принятом
    расписании, а не какими были при сборке: с тех пор источник могли принять заново, закрепить
    или сменить ему преподавателя. Меняет ``target`` на месте и возвращает его.
    """
    for name, source in (jointCopies(settings) if copies is None else copies).items():
        if hasLessons(sources, source):
            target[name] = copy.deepcopy(sources[source])
        else:
            target.pop(name, None)

    return target


# ---------------------------------------------------------------- помехи общих уроков

def copyConflicts(settings, answer, before, copies, same_stage=False):
    """Чем общие уроки копий ``copies`` ({копия: источник}) мешают соседям в даты своих потоков.

    ``answer`` — расписание, в котором у копий уже уроки источников; ``before`` — расписание, вокруг
    которого соседи копии уже стоят (принятое до изменения или вариант, каким его собрал решатель).
    Проверяются только новые места копии, которых в ``before`` у неё не было: старые соседи уже
    обошли. Помеха — урок другого курса, который идёт в те же даты, что и копия, в то же время
    (courses.peerSlotConflicts: преподаватель занят, пара «нельзя одновременно» — только в линейке
    копии, программы, которые не пересекаются). Соседи — не только курсы потока-копии, но и других
    этапов: блоков (семинары — «программы не пересекаются»), более поздних потоков. Поток-источник
    может кончиться раньше, и тогда такую помеху не найдёт ни одна проверка самого источника.
    Не помеха:
    * копии ``copies`` друг другу: друг относительно друга они стоят так же, как их источники;
    * курсы, уроки которых задаёт этап источника (сам источник, его другие копии, курсы его потока
      и их копии): это помехи самого источника, их видят его сборка и принятие его варианта, а
      составлять заново поток-копию ради них бесполезно.
    ``same_stage`` — соседи только из этапа самой копии: вопрос «вариант собран, когда у общих уроков
    были другие часы» (preview.jointChanges) говорит об уроках варианта, а курсы других этапов в нём
    стоят как в принятом расписании, их помехи уже были до принятия.
    На прежнем месте у копии мог смениться преподаватель (сборка сменила его источнику): тогда
    проверяется только, не занят ли новый преподаватель (причина "busy") — сам урок соседям уже не мешал.

    Возвращает {номер потока-копии: [(день, урок, причина, курс-помеха)]} без повторов; пустой
    словарь — помех нет.
    """
    by_name = groupsByName(settings)
    every = jointCopies(settings)
    conflicts = {}

    for name in copies:
        group = by_name[name]
        # Этап, чьи уроки задаёт источник копии: курсы, корень которых в нём, копии не соседи
        source_stage = stageKey(by_name[copies[name]])
        peers = {other: week for other, week in answer.items()
                 if other in by_name and other not in copies and (
                     stageKey(by_name[other]) == stageKey(group) if same_stage
                     else stageKey(by_name[copyRoot(every, other)]) != source_stage)}
        placed = {(day, lesson): cell.get("teachers", []) for day, lesson, cell in lessonEntries(before, name)}

        for day, lesson, cell in lessonEntries(answer, name):
            # На прежнем месте — только преподаватели, которых там у копии не было
            old = placed.get((day, lesson))
            teachers = [teacher for teacher in cell.get("teachers", []) if old is None or teacher not in old]
            items = peerSlotConflicts(settings, peers, by_name, name, cell.get("subject"), teachers, (day, lesson), [name])
            conflicts.setdefault(group["stream_id"], []).extend(item for item in items if old is None or item[2] == "busy")

    return {stream: list(dict.fromkeys(items)) for stream, items in conflicts.items() if items}


def copyCannot(settings, answer, copies, before=None):
    """Общие уроки копий ``copies`` ({копия: источник}) во время, где у их преподавателя на этапе
    потока-копии отмечено «не может» (SPEC, AC-39).

    Это не запрет: время общих уроков задаёт поток-источник, а движок соблюдает отметки этапа
    источника, не копии. Программа только предупреждает — в вопросах setJoint и принятия варианта
    и на «Расписании». ``answer`` — расписание, в котором у копий уже уроки источников. ``before`` —
    расписание до изменения: тогда названы только новые уроки преподавателя (этого места у копии
    с этим преподавателем там не было), о старых завуч уже знает (принятие варианта). Без ``before`` —
    все такие уроки («Расписание»; setJoint — для новых копий: до отметки курс был обычным).

    Возвращает [(преподаватель, день, урок, копия)] в порядке копий и уроков; пустой список —
    таких уроков нет.
    """
    by_name = groupsByName(settings)
    found = []

    for name in copies:
        stage = stageKey(by_name[name])
        placed = {(day, lesson, teacher) for day, lesson, cell in lessonEntries(before or {}, name)
                  for teacher in cell.get("teachers", [])}

        for day, lesson, cell in lessonEntries(answer, name):
            found += [(teacher, day, lesson, name) for teacher in cell.get("teachers", [])
                      if (day, lesson, teacher) not in placed and [day, lesson] in cannotSlots(settings, teacher, stage)]

    return found
