"""Курсы: разделы (потоки и блоки), линейки, названия и нагрузка курсов, преподаватель курса,
«курс уже идёт» и закреплённые уроки.

Каждый курс — один предмет одной линейки в одном потоке («Поток 1 — ОГЭ — Литература») либо
в блоке курсов без потока: доп. курсы («Семинар ОГЭ: Математика»), майские марафоны и летняя
школа («Летняя школа — ЕГЭ основной — Математика»). Устройство данных, разделы и этапы —
в шапке model.py.

Термины:
- поток («Поток 1», «Поток 2»…) — ученики, начинающие учиться с одной даты; у всех курсов потока
  общие даты начала и конца. Номер потока хранится в поле "stream_id" курса;
- блок — группа курсов без потока: "extra" (доп. курсы), "may" (майские марафоны), "summer"
  (летняя школа). Ключ блока хранится в поле "block" курса;
- линейка (line) — программа подготовки внутри потока: ОГЭ, ЕГЭ основной, ЕГЭ продвинутый,
  10 класс, 8 класс; у доп. курсов — своя линейка («Семинар ОГЭ», «Семинар ЕГЭ продвинутый»).

Имена: ``stream`` в имени или параметре функции — только поток (номер); ``section`` — раздел,
то есть поток или блок (см. model.py). Поэтому ``streamIds`` / ``addStream`` — про потоки,
а ``sectionStart`` / ``sectionLines`` / ``addCourse(settings, section, …)`` — про любой раздел.

Разделы модуля:
1. Названия, разделы и линейки: ``courseName`` и ``courseLabel`` (название курса и его подпись
   строятся только здесь, из ``nameParts``), ``courseLine``, ``lineOf``, ``streamIds``,
   ``sectionLines``, ``lineCourses``.
2. Нагрузка и даты разделов: ``courseLoad`` / ``courseHours``, ``sectionStart`` / ``sectionEnd``
   и их запись.
3. Добавление и удаление: ``addCourse``, ``removeCourses``, потоки и линейки целиком. Ссылки
   на курсы у преподавателей и в закреплённых уроках остаются согласованными; правила-штрафы,
   расписание и варианты удалённых курсов чистит сервер (purgeCourses в src/web/tabs/classes.py).
   Новый предмет линейки, которая идёт вместе с более ранним потоком, сразу становится копией.
4. Преподаватель и курс: состояния «не ведёт / может вести / ведёт / запрещено», правило
   «курс ведёт только один преподаватель» (``assignTeacher`` — единственное его описание),
   кто может вести курс (``courseCandidates`` — так же их ищет решатель), ограничение
   ``teacherLimit``, предметы преподавателя, замена преподавателя в готовом расписании
   (``teacherConflicts``: источник и его копии — один курс).
5. «Курс уже идёт» (``courseStarted``) и «курс зафиксирован» (``courseLocked``); то же для курса
   вместе с его общими уроками (``sharedStarted``, ``sharedLocked``; их общий шаг — ``anyShared``).
6. Закреплённые уроки (вкладка «Курсы», «День и время») и перенос уроков в готовом расписании
   (``slotConflicts`` смотрит и соседей копий: их уроки переезжают вместе с источником).
7. Общие уроки линеек: курс-копия и его источник (``copySource``, ``copySources``,
   ``sharedCourses``, ``lineTogetherWith``) и помощники от уже прочитанных копий (``copyRoot`` —
   источник или сам курс, ``copiesOf`` — копии данных курсов, ``copyFollowers`` — копии по
   источникам). Здесь только чтение отметки ``together_with``:
   этому модулю она нужна для накладок, лимита и переноса уроков, а он ниже joint.py. Ставит
   и снимает отметку, выравнивает копии — joint.py.

Почти все функции меняют ``settings`` на месте и возвращают их (или результат), так что
вызывающий код (сервер) после этого просто сохраняет проект. Списки курсов и нагрузки для
изменения дают ``editableGroups`` и ``lessons`` (создают пустые, если их нет); только для
чтения — model.courseGroups и ``courseLoad`` (ничего не создают).

Зависимости: model, grid, pairs.
"""

import datetime

from src.modules.functions.grid import lessonExists, pinSlot
from src.modules.functions.model import (
    EXTRA_BLOCK, cannotSlots, courseGroups, courseNames, courseSlots, coursesOverlap, courseSubject, emptyCell, groupsByName,
    inSection, isBlock, isLesson, normalizeSection, sectionOf, stageKey, teacherLessons
)
from src.modules.functions.pairs import isSubjectPair, programPairs, sameLine, subjectPairs

# Программа, к которой относятся все доп. курсы (семинары); по ней работает правило
# «Семинары и ЕГЭ продвинутый не пересекаются» (non_overlapping_programs)
EXTRA_PROGRAM = "Семинары"
# Линейки потока по умолчанию и линейки доп. курсов по умолчанию
DEFAULT_LINES = ["ОГЭ", "ЕГЭ основной", "ЕГЭ продвинутый", "10 класс", "8 класс"]
DEFAULT_EXTRA_LINES = ["Семинар ЕГЭ продвинутый", "Семинар ОГЭ"]

# Блоки курсов без потока в порядке показа: ключ блока -> его имя в данных. Из этого имени
# собирается название курса (nameParts: «Летняя школа — ЕГЭ основной — Математика»), а у майских
# и летних курсов это ещё и программа (sectionProgram). Название курса — его ключ во всех
# сохранённых проектах, поэтому значения менять нельзя: курсы уже сохранённых проектов остались бы
# со старыми названиями. У доп. курсов (extra) значение не используется: название —
# «Линейка: Предмет», программа — EXTRA_PROGRAM.
# Заголовок раздела на странице берётся не отсюда, а из stage.<ключ> в ru.hjson (stages.stageLabel):
# тексты совпадают только по виду, и править их можно независимо
BLOCKS ={EXTRA_BLOCK: "Доп. курсы", "may": "Майские марафоны", "summer": "Летняя школа"}

# Даты блока по умолчанию: (месяц, день) начала и конца в последнем календарном году
# учебного года (например, для 2026/27 — май и лето 2027). У доп. курсов дат по умолчанию нет
BLOCK_DATES = {"may": ((5, 1), (5, 31)), "summer": ((6, 1), (8, 31))}

# Сколько курсов может вести один преподаватель, если в проекте не указано иное
# (поле max_courses_per_teacher, вкладка «Настройки»)
DEFAULT_TEACHER_LIMIT = 5

# Кем преподаватель приходится курсу: "no" — не ведёт; "may" — может вести (выбирает
# решатель); "assigned" — ведёт (закреплён); "forbidden" — запрещено (никогда: курс не
# предлагается нигде, даже на вкладке «Курсы»). Порядок — порядок переключения по клику
COURSE_STATES = ("no", "may", "assigned", "forbidden")


# ---------------------------------------------------------------- 1. названия, разделы, линейки

def nameParts(section, line, subject):
    """Части названия курса: [раздел, линейка, предмет], у доп. курсов — одна часть.

    - доп. курсы: ["Семинар ОГЭ: Математика"];
    - другие блоки: ["Летняя школа", "ЕГЭ основной", "Математика"];
    - поток: ["Поток 1", "ОГЭ", "Литература"].
    Из этих частей собираются и название курса (``courseName``), и его подписи (``courseLabel``):
    так подпись никогда не приходится получать разбором названия.
    «Поток N» и имена блоков (``BLOCKS``) — части названия-ключа, их нельзя менять; подпись
    «Поток» на странице — отдельный текст stage.stream в ru.hjson.
    """
    section = normalizeSection(section)

    if section == EXTRA_BLOCK:
        return [f"{line}: {subject}"]

    if isBlock(section):
        return [BLOCKS.get(section, section), line, subject]

    return [f"Поток {section}", line, subject]


def courseName(section, line, subject):
    """Собирает название курса по разделу, линейке и предмету.

    «Семинар ОГЭ: Математика», «Летняя школа — ЕГЭ основной — Математика»,
    «Поток 1 — ОГЭ — Литература» (части — ``nameParts``).
    Название курса — его ключ во всех настройках, поэтому оно должно строиться только здесь.
    """
    return " — ".join(nameParts(section, line, subject))


def courseLabel(group, since=""):
    """Короткая подпись курса ``group`` через запятые: «Поток 2, ЕГЭ основной, Математика».

    Собирается из полей курса (раздел, линейка, предмет), а не из его названия. ``since``
    дописывается к первой части: «Поток 2 (с 23.11), ЕГЭ основной, Математика»; у доп. курса
    часть одна — «Семинар ОГЭ: Математика (с 01.10)».
    """
    parts = nameParts(sectionOf(group), lineOf(group), courseSubject(group))
    parts[0] += since

    return ", ".join(parts)


def courseLine(program):
    """Линейка (поле "line" курса потока) по названию программы.

    Оба уровня ЕГЭ («ЕГЭ основной» и «ЕГЭ продвинутый») делят одних и тех же учеников,
    поэтому для правил пар предметов они считаются одной линейкой «ЕГЭ».
    Остальные программы («ОГЭ», «10 класс»…) — сами себе линейка.
    """
    return "ЕГЭ" if program.startswith("ЕГЭ") else program


def editableGroups(settings):
    """Список курсов проекта (``settings["classes"]["custom_groups"]``) для изменения; создаёт его, если нет.

    Только для чтения — model.courseGroups: она ничего не создаёт.
    """
    return settings.setdefault("classes", {}).setdefault("custom_groups", [])


def lessons(settings):
    """Недельная нагрузка {курс: {предмет: уроков}} (``settings["classes"]["lessons"]``) для изменения; создаёт, если нет.

    Только для чтения — ``courseLoad`` / ``courseHours``.
    """
    return settings.setdefault("classes", {}).setdefault("lessons", {})


def streamIds(settings):
    """Отсортированный список номеров потоков, в которых есть хотя бы один курс."""
    return sorted({group["stream_id"] for group in courseGroups(settings) if group.get("stream_id") is not None})


def lineOf(group):
    """Линейка курса так, как она показывается на вкладке «Курсы».

    В потоке курсы группируются по программе ("program": «ЕГЭ основной»), а не по полю
    "line" (там оба ЕГЭ — одна линейка «ЕГЭ», см. ``courseLine``). Курсы без потока
    группируются по своей линейке («Семинар ОГЭ»).
    """
    return group.get("program") if group.get("stream_id") is not None else group.get("line", group.get("program"))


def sectionLines(settings, section):
    """Линейки раздела ``section`` (поток или блок) в порядке появления курсов, без повторов."""
    return list(dict.fromkeys(lineOf(group) for group in courseGroups(settings) if inSection(group, section)))


def lineCourses(settings, section, line):
    """Курсы (словари) линейки ``line`` в разделе ``section`` (поток или блок)."""
    return [group for group in courseGroups(settings) if inSection(group, section) and lineOf(group) == line]


# ---------------------------------------------------------------- 2. нагрузка и даты разделов

def courseLoad(settings, course):
    """Нагрузка курса только для чтения: {предмет: уроков в неделю} целыми числами.

    Пустое значение в записи считается нулём; у курса без записи — пустой словарь.
    """
    return {subject: int(hours or 0) for subject, hours in settings.get("classes", {}).get("lessons", {}).get(course, {}).items()}


def courseHours(settings, course, subject=None, default=0):
    """Уроков в неделю у курса: по предмету ``subject`` или, без него, по всем предметам вместе.

    ``default`` — сколько считать, если у курса нет записи нагрузки по этому предмету.
    """
    load = courseLoad(settings, course)

    if subject is not None:
        return load.get(subject, default)

    return sum(load.values())


def blockDates(settings, block):
    """Даты блока, у которого ещё нет курсов: сохранённые, иначе сезон по умолчанию.

    Возвращает (начало, конец) строками "ГГГГ-ММ-ДД". Сохранённые даты лежат в
    ``settings["block_dates"][блок]``. Для блоков с сезоном (май, лето) недостающая дата
    берётся из BLOCK_DATES в году окончания календаря (``calendar_end_date``), а если он
    не задан — в текущем году. Для доп. курсов без сохранённых дат вернутся пустые строки.
    """
    saved = settings.get("block_dates", {}).get(block, {})

    if block not in BLOCK_DATES:
        return saved.get("start", ""), saved.get("end", "")

    year = (settings.get("calendar_end_date") or "")[:4]
    year = int(year) if year.isdigit() else datetime.date.today().year
    (start_month, start_day), (end_month, end_day) = BLOCK_DATES[block]

    return (
        saved.get("start") or f"{year}-{start_month:02d}-{start_day:02d}",
        saved.get("end") or f"{year}-{end_month:02d}-{end_day:02d}"
    )


def saveBlockDate(settings, section, key, date):
    """Запоминает дату блока (``key``: "start" или "end") в ``settings["block_dates"]``.

    Блок помнит свои даты даже без курсов — новые курсы блока получат их.
    Для потоков ничего не делает (у потока даты хранятся только в его курсах).
    """
    if isBlock(section):
        settings.setdefault("block_dates", {}).setdefault(normalizeSection(section), {})[key] = date


def sectionDate(settings, section, key):
    """Дата раздела (``key``: "start" или "end"): у первого его курса, у блока без курсов — дата блока."""
    date = next((group.get(f"{key}_date", "") for group in courseGroups(settings) if inSection(group, section)), "")

    if not date and isBlock(section):
        date = blockDates(settings, normalizeSection(section))[0 if key == "start" else 1]

    return date


def sectionStart(settings, section):
    """Дата начала раздела (поток или блок): дата первого его курса, а для пустого блока — дата блока."""
    return sectionDate(settings, section, "start")


def sectionEnd(settings, section):
    """Дата окончания раздела (как ``sectionStart``).

    Пустая дата окончания означает, что курс идёт до конца календаря, поэтому в этом
    случае возвращается ``calendar_end_date``.
    """
    return sectionDate(settings, section, "end") or settings.get("calendar_end_date", "")


def setSectionDate(settings, section, key, date):
    """Ставит дату (``key``: "start" или "end") всем курсам раздела и запоминает её для блока."""
    for group in editableGroups(settings):
        if inSection(group, section):
            group[f"{key}_date"] = date

    saveBlockDate(settings, section, key, date)

    return settings


def setSectionStart(settings, section, date):
    """Ставит дату начала всем курсам раздела (и запоминает её для блока). Возвращает ``settings``."""
    return setSectionDate(settings, section, "start", date)


def setSectionEnd(settings, section, date):
    """Ставит дату окончания всем курсам раздела (и запоминает её для блока). Возвращает ``settings``."""
    return setSectionDate(settings, section, "end", date)


# ---------------------------------------------------------------- 3. добавление и удаление курсов

def sectionProgram(section, line):
    """Программа нового курса: в потоке это сама линейка; доп. курсы сохраняют общую программу
    «Семинары» (на неё завязано правило «семинары / ЕГЭ продвинутый»); остальные блоки — сами себе
    программа («Майские марафоны», «Летняя школа»).
    """
    if not isBlock(section):
        return line

    if section == EXTRA_BLOCK:
        return EXTRA_PROGRAM

    return BLOCKS.get(section, section)


def addCourse(settings, section, line, subject, hours=1, start_date=None):
    """Добавляет курс «предмет ``subject`` линейки ``line`` в разделе ``section``».

    Параметры:
    - section — номер потока или ключ блока (None = доп. курсы);
    - hours — уроков в неделю;
    - start_date — дата начала; по умолчанию — дата начала раздела.
    Дата окончания берётся у других курсов раздела (или из дат блока): все курсы раздела
    заканчиваются одновременно.

    Если курс с таким названием уже есть, ничего не меняет и просто возвращает его
    название. Новый курс сразу попадает в «может вести» у всех преподавателей этого
    предмета, кроме тех, кому он «запрещён». Возвращает название курса.

    Линейка идёт вместе с более ранним Потоком N (``lineTogetherWith``), и предмет есть в её
    линейке Потока N — новый курс сразу курс-копия: ``together_with = N`` и часы источника вместо
    ``hours``. Так «вся линейка целиком» держится при любом добавлении («Добавить предмет»,
    «Скопировать в другие потоки»). Уроки источника копия получит при записи проекта
    (joint.syncJointAnswer). Новый поток (``addStream``) отметку не наследует: его линейки пустые.
    """
    name = courseName(section, line, subject)
    by_name = groupsByName(settings)

    if name in by_name:
        return name

    section = normalizeSection(section)
    block = section if isBlock(section) else None
    program = sectionProgram(section, line)
    number = lineTogetherWith(settings, section, line)
    source = courseName(number, line, subject) if number is not None else None

    group = {
        "name": name,
        "program": program,
        "line": courseLine(program) if block is None else line,
        "subjects": [subject],
        "stream_id": None if block is not None else section,
        "start_date": sectionStart(settings, section) if start_date is None else start_date,
        # У блока без курсов — дата блока; пустая дата потока значит «до конца календаря»
        "end_date": sectionDate(settings, section, "end"),
    }

    if block is not None:
        group["block"] = block

    if source in by_name:
        group["together_with"] = number
        hours = courseHours(settings, source, subject, default=hours)

    editableGroups(settings).append(group)
    offerCourse(settings, name, subject)
    lessons(settings)[name] = {subject: hours}

    return name


def offerCourse(settings, course, subject):
    """Курс попадает в «может вести» у каждого преподавателя предмета (кроме тех, кому он «запрещён»)."""
    for teacher in settings.get("teachers", {}).values():
        if course in teacher.get("forbidden", []):
            continue

        for item in teacher.get("subjects", []):
            if item.get("subject") == subject and course not in item.setdefault("classes", []):
                item["classes"].append(course)


def removeCourses(settings, names):
    """Удаляет курсы ``names`` и все ссылки на них.

    Чистит нагрузку, закреплённые уроки и списки преподавателей («может вести»,
    «ведёт», «запрещено»). Возвращает ``settings``.
    """
    names = set(names)

    settings["classes"]["custom_groups"] = [group for group in editableGroups(settings) if group["name"] not in names]

    for name in names:
        lessons(settings).pop(name, None)
        settings.get("constants", {}).pop(name, None)

    for teacher in settings.get("teachers", {}).values():
        for item in teacher.get("subjects", []):
            item["classes"] = [course for course in item.get("classes", []) if course not in names]
            item["assigned"] = [course for course in item.get("assigned", []) if course not in names]

        if "forbidden" in teacher:
            teacher["forbidden"] = [course for course in teacher["forbidden"] if course not in names]

    return settings


def copyLineToStreams(settings, stream, line, skip=()):
    """Делает так, чтобы линейка ``line`` во всех остальных потоках имела те же предметы и нагрузку.

    Недостающие курсы добавляются; у существующих курсов нагрузка выставляется как
    в исходном потоке. Предметы, которые есть только в других потоках, остаются.
    Потоки из ``skip`` (например, уже начавшиеся) не трогаются.
    Возвращает ``settings``.
    """
    source = lineCourses(settings, stream, line)

    for other in streamIds(settings):
        if other == stream or other in skip:
            continue

        for group in source:
            for subject in group.get("subjects", []):
                hours = courseHours(settings, group["name"], subject)
                # addCourse не меняет нагрузку уже существующего курса, поэтому она
                # переписывается следующей строкой
                name = addCourse(settings, other, line, subject, hours)
                lessons(settings).setdefault(name, {})[subject] = hours

    return settings


def addStream(settings, start_date):
    """Добавляет новый поток с датой начала ``start_date``.

    Номер — следующий после последнего. Новый поток копирует линейки, предметы
    и нагрузку последнего потока. Если потоков ещё нет, возвращается номер 1 без
    курсов — наполнить его должен вызывающий (newStream в src/web/tabs/classes.py берёт курсы первого
    потока стандартной программы). Возвращает номер нового потока.
    """
    streams = streamIds(settings)

    if not streams:
        return 1

    stream = streams[-1] + 1

    for group in [group for group in courseGroups(settings) if group.get("stream_id") == streams[-1]]:
        for subject in group.get("subjects", []):
            addCourse(settings, stream, group["program"], subject, courseHours(settings, group["name"], subject, default=1), start_date)

    return stream


def clearStageMarks(settings, stage):
    """Убирает у всех преподавателей отметки «удобно / может / не может» этапа ``stage``
    (``teachers[*].availability[str(stage)]``).

    Нужна в двух местах: при удалении потока (``removeStream``) и при добавлении нового
    (newStream в src/web/tabs/classes.py). Номер нового потока мог принадлежать потоку,
    который пропал без removeStream (удалили все его линейки или курсы), — без этой чистки
    новый поток сразу получил бы чужие «не может». Возвращает ``settings``.
    """
    for teacher in settings.get("teachers", {}).values():
        teacher.get("availability", {}).pop(str(stage), None)

    return settings


def removeStream(settings, stream):
    """Удаляет поток: все его курсы (со ссылками) и отметки времени преподавателей для этого потока.

    Возвращает ``settings``.
    """
    removeCourses(settings, [group["name"] for group in courseGroups(settings) if group.get("stream_id") == stream])

    return clearStageMarks(settings, stream)


def addLine(settings, section, line, subjects):
    """Добавляет в раздел ``section`` (поток или блок) линейку ``line`` — по курсу на каждый предмет из ``subjects``."""
    for subject in subjects:
        addCourse(settings, section, line, subject)

    return settings


def removeLine(settings, section, line):
    """Удаляет из раздела ``section`` (поток или блок) все курсы линейки ``line``. Возвращает ``settings``."""
    return removeCourses(settings, [group["name"] for group in lineCourses(settings, section, line)])


# ---------------------------------------------------------------- 4. преподаватель и курс

def teacherLimit(settings):
    """Сколько курсов может вести один преподаватель (max_courses_per_teacher; не задано — 5)."""
    return int(settings.get("max_courses_per_teacher", DEFAULT_TEACHER_LIMIT) or DEFAULT_TEACHER_LIMIT)


def isForbidden(settings, teacher, course):
    """True, если преподавателю ``teacher`` запрещено вести курс ``course``.

    Запрет хранится у самого преподавателя (``teacher["forbidden"]``), а не у предмета,
    чтобы он пережил удаление и повторное добавление предмета.
    """
    return course in settings.get("teachers", {}).get(teacher, {}).get("forbidden", [])


def teacherCourseState(settings, teacher, subject, course):
    """Состояние пары «преподаватель — курс» по предмету ``subject`` (одно из COURSE_STATES).

    Запрет проверяется первым; затем «ведёт» (курс в "assigned"), затем «может вести»
    (курс в "classes"); иначе "no".
    """
    if isForbidden(settings, teacher, course):
        return "forbidden"

    for item in settings.get("teachers", {}).get(teacher, {}).get("subjects", []):
        if item.get("subject") == subject:
            if course in item.get("assigned", []):
                return "assigned"

            if course in item.get("classes", []):
                return "may"

    return "no"


def nextTeacherCourseState(state):
    """Следующее состояние по кругу COURSE_STATES (для клика по ячейке)."""
    return COURSE_STATES[(COURSE_STATES.index(state) + 1) % len(COURSE_STATES)]


def setTeacherCourseState(settings, teacher, subject, course, state):
    """Задаёт состояние «преподаватель — курс» (``state`` из COURSE_STATES).

    Курс сначала убирается из всех трёх списков преподавателя, затем добавляется в нужные:
    "may" -> "classes"; "assigned" -> ``assignTeacher`` ("classes" и "assigned" у него,
    у остальных преподавателей закрепление снимается); "forbidden" -> "forbidden".
    Пустой список "forbidden" удаляется.
    Если у преподавателя нет такого предмета, ничего не меняет. Возвращает ``settings``.
    """
    data = settings["teachers"][teacher]
    item = next((entry for entry in data.get("subjects", []) if entry.get("subject") == subject), None)

    if item is None:
        return settings

    classes = item.setdefault("classes", [])
    assigned = item.setdefault("assigned", [])
    forbidden = data.setdefault("forbidden", [])

    for values in (classes, assigned, forbidden):
        if course in values:
            values.remove(course)

    if state == "may":
        classes.append(course)

    if state == "assigned":
        assignTeacher(settings["teachers"], course, subject, teacher)

    if state == "forbidden":
        forbidden.append(course)

    if not forbidden:
        data.pop("forbidden")

    return settings


def assignTeacher(teachers, course, subject, teacher):
    """Правило «курс ведёт только один преподаватель»: единственное место, где оно записано.

    ``teachers`` — словарь преподавателей ({имя: данные}, как ``settings["teachers"]``; во входе
    решателя — его копия). Преподаватель ``teacher`` по предмету ``subject`` получает курс
    и в «может вести» ("classes"), и в «ведёт» ("assigned"); у остальных преподавателей
    предмета закрепление снимается, но «может вести» остаётся. ``teacher=None`` снимает
    закрепление со всех — выбор остаётся решателю.

    Запрет («запрещено») здесь не проверяется: это делает тот, кто выбирает преподавателя
    (``setCourseTeacher``). Меняет ``teachers`` на месте.
    """
    for name, data in teachers.items():
        for item in data.get("subjects", []):
            if item.get("subject") != subject:
                continue

            if name != teacher:
                # Был закреплён другой преподаватель: он остаётся среди тех, кто «может вести»
                if course in item.get("assigned", []):
                    item["assigned"].remove(course)

                continue

            for key in ("classes", "assigned"):
                if course not in item.setdefault(key, []):
                    item[key].append(course)


def courseTeachers(settings, answer, course, subject):
    """Кто преподаёт курс по предмету ``subject``.

    Возвращает словарь списков имён:
    - "assigned" — закреплены («ведёт»);
    - "scheduled" — стоят на уроках курса в расписании ``answer`` (так их расставил решатель);
    - "candidates" — «может вести»;
    - "forbidden" — вести запрещено.
    """
    assigned, candidates, forbidden = [], [], []

    for name in sorted(settings.get("teachers", {})):
        state = teacherCourseState(settings, name, subject, course)

        if state == "forbidden":
            forbidden.append(name)

        elif state == "assigned":
            assigned.append(name)

        elif state == "may":
            candidates.append(name)

    # Преподаватели из готового расписания — в порядке первого появления, без повторов
    scheduled = []

    for day, lesson in courseSlots(answer, course, subject):
        scheduled += [teacher for teacher in answer[course][day][lesson].get("teachers", []) if teacher not in scheduled]

    return {"assigned": assigned, "scheduled": scheduled, "candidates": candidates, "forbidden": forbidden}


def subjectTeachers(settings, subject, course=None):
    """Отсортированные имена преподавателей предмета; если задан курс — без тех, кому он запрещён."""
    return sorted(
        name for name, teacher in settings.get("teachers", {}).items()
        if any(item.get("subject") == subject for item in teacher.get("subjects", []))
        and (course is None or course not in teacher.get("forbidden", []))
    )


def nobodyTeaches(settings, course, subject, teacher):
    """Курс по предмету ``subject`` некому вести: у преподавателя ``teacher`` (с уроков курса в расписании;
    None — такого нет) этого предмета нет, и в «может вести» курс ни у кого (``courseCandidates``).
    Решатель уроки такого курса не ставит, даже закреплённые (solver_input.pinForecast, stages.teacherLeft).
    """
    return teacher not in subjectTeachers(settings, subject) and not courseCandidates(settings.get("teachers", {}), course, subject)


def courseCandidates(teachers, course, subject):
    """Кто может вести курс по предмету ``subject``: у кого курс в «может вести» ("classes";
    «ведёт» его туда тоже кладёт, assignTeacher). ``teachers`` — как ``settings["teachers"]`` или
    они же во входе решателя. Так же кандидатов ищет solve.exe: без них уроки курса не ставятся.
    """
    return [
        name for name, teacher in teachers.items()
        if any(item.get("subject") == subject and course in item.get("classes", []) for item in teacher.get("subjects", []))
    ]


def setCourseTeacher(settings, course, subject, teacher):
    """Закрепляет за курсом одного преподавателя («ведёт»); None оставляет выбор решателю.

    Это проверка запрета плюс ``assignTeacher``: преподавателя, которому курс запрещён,
    закрепить нельзя — ValueError(teacher). Возвращает ``settings``.
    """
    if teacher is not None and isForbidden(settings, teacher, course):
        raise ValueError(teacher)

    assignTeacher(settings.get("teachers", {}), course, subject, teacher)

    return settings


def coursesForSubject(settings, subject):
    """Курсы, в которых у предмета ``subject`` ненулевая недельная нагрузка (список названий)."""
    return [name for name in courseNames(settings) if courseHours(settings, name, subject) > 0]


def setTeacherSubjects(settings, teacher, subjects):
    """Задаёт преподавателю ``teacher`` список предметов ``subjects``.

    Для предметов, которые у преподавателя уже были, сохраняется выбор курсов
    («может вести» / «ведёт»). Новый предмет начинается со всех курсов, где он есть
    (кроме курсов из «запрещено»), — решатель сам выберет, какой из них дать.
    Если преподавателя ещё нет, он создаётся. Меняет ``settings`` на месте
    и возвращает словарь данных преподавателя.
    """
    data = settings["teachers"].setdefault(teacher, {"subjects": [], "availability": {}})
    current = {item["subject"]: item for item in data.get("subjects", [])}
    forbidden = set(data.get("forbidden", []))

    data["subjects"] = [
        current.get(subject) or {"subject": subject, "classes": [course for course in coursesForSubject(settings, subject) if course not in forbidden]}
        for subject in subjects
    ]

    return data


def teacherConflicts(settings, answer, course, subject, teacher):
    """Почему преподаватель не может взять уроки курса в готовом расписании как они есть.

    Используется при замене преподавателя в принятом расписании без перезапуска решателя.
    Возвращает список [(день, урок, причина, подробность)], где причина:
    - "unavailable" — преподаватель в это время отметил «не может» (на этапе курса);
    - "busy" — в это время он ведёт другой курс (подробность — название того курса);
    - "limit" — (None, None, "limit", число курсов): он превысит max_courses_per_teacher.
    Курсы, которые идут в другие даты, время преподавателя не занимают; неизвестные курсы
    считаются идущими одновременно. Список отсортирован по дню и уроку, "limit" — в конце.

    Источник и его копии (раздел 7) — один курс с одними уроками: друг другу они не «busy»,
    в лимите считаются один раз. Уроки группы идут в даты каждого её курса, поэтому помехой
    считается курс, который идёт одновременно хотя бы с одним из них.
    """
    by_name = groupsByName(settings)
    group = by_name.get(course)
    copies = copySources(by_name)
    shared = sharedCourses(copies, course)
    members = [by_name[name] for name in shared if name in by_name]
    slots = courseSlots(answer, course, subject)
    conflicts = []
    # Курсы, которые преподаватель уже ведёт в пересекающиеся даты (для проверки лимита): у общих
    # уроков — их источник
    courses = set()

    for other, day, lesson, _ in teacherLessons(answer, teacher):
        if members and other in by_name and not any(coursesOverlap(settings, member, by_name[other]) for member in members):
            continue

        root = copyRoot(copies, other)
        courses.add(root)

        if root != shared[0] and (day, lesson) in slots:
            conflicts.append((day, lesson, "busy", other))

    # Отметки «не может» зависят от этапа курса — периода, в котором он идёт
    cannot = cannotSlots(settings, teacher, stageKey(group)) if group else []
    conflicts += [(day, lesson, "unavailable", "") for day, lesson in slots if [day, lesson] in cannot]

    if shared[0] not in courses and len(courses) + 1 > teacherLimit(settings):
        conflicts.append((None, None, "limit", len(courses)))

    return sorted(conflicts, key=lambda item: (item[0] is None, item[0] or 0, item[1] or 0))


def replaceTeacherInAnswer(answer, course, subject, teacher):
    """Ставит преподавателя ``teacher`` на все уроки курса по предмету ``subject`` в расписании.

    Меняет ``answer`` на месте и возвращает его.
    """
    for day, lesson in courseSlots(answer, course, subject):
        answer[course][day][lesson]["teachers"] = [teacher]

    return answer


# ---------------------------------------------------------------- 5. идущие курсы

def courseStarted(settings, answer, course, subject, today=None):
    """«Курс уже идёт»: дата начала наступила и у курса есть уроки в принятом расписании.

    У такого курса преподаватель фиксируется, а уже стоящие уроки остаются на своих местах
    (ученики уже ходят по этому расписанию). ``today`` — дата для проверки (по умолчанию
    сегодня), удобно для тестов. Курс без даты начала уже идущим не считается.
    """
    start = groupsByName(settings).get(course, {}).get("start_date") or ""
    today = (today or datetime.date.today()).isoformat()

    # Даты "ГГГГ-ММ-ДД" сравниваются как строки
    return bool(start) and start <= today and bool(courseSlots(answer, course, subject))


def courseLocked(settings, answer, course, subject, today=None):
    """«Курс зафиксирован»: курс уже идёт и все его уроки расставлены.

    Время и число уроков такого курса больше не меняются. Идущий курс, которому не хватает
    уроков (нагрузка больше, чем уроков в расписании), ещё может получить недостающие
    (и его нагрузку можно менять).
    """
    hours = courseHours(settings, course, subject)

    return courseStarted(settings, answer, course, subject, today) and len(courseSlots(answer, course, subject)) >= hours


def sharedStarted(settings, answer, course, subject, today=None):
    """«Курс уже идёт» вместе с общими уроками: идёт сам курс или любой курс его группы
    «источник + копии» (``sharedCourses``).

    Уроки источника — это и уроки его копий: если ученики потока-копии уже ходят, источник
    менять нельзя, даже когда его собственный поток ещё не начался. У обычного курса — то же,
    что ``courseStarted``.
    """
    return anyShared(courseStarted, settings, answer, course, subject, today)


def sharedLocked(settings, answer, course, subject, today=None):
    """«Курс зафиксирован» вместе с общими уроками: зафиксирован сам курс или любой курс его группы
    (как ``sharedStarted``; у обычного курса — то же, что ``courseLocked``).
    """
    return anyShared(courseLocked, settings, answer, course, subject, today)


def anyShared(check, settings, answer, course, subject, today):
    """Верна ли проверка ``check`` (``courseStarted`` или ``courseLocked``) хотя бы для одного курса группы ``course``."""
    group = sharedCourses(copySources(groupsByName(settings)), course)

    return any(check(settings, answer, name, subject, today) for name in group)


# ---------------------------------------------------------------- 6. закреплённые уроки и перенос уроков

def pinnedSlots(settings, course, subject):
    """Отсортированный список (день, урок), закреплённых за курсом на вкладке «Курсы» («День и время»).

    Закрепления хранятся в ``settings["constants"][курс]`` как {"день-урок": предмет}.
    """
    return sorted(pinSlot(key) for key, value in settings.get("constants", {}).get(course, {}).items() if value == subject)


def setPinnedSlots(settings, course, subject, slots):
    """Заменяет закреплённые уроки курса по предмету ``subject`` на ``slots`` [(день, урок)].

    Если у курса не осталось закреплений, его запись удаляется из constants.
    Возвращает ``settings``.
    """
    fixed = settings.setdefault("constants", {}).setdefault(course, {})

    for key in [key for key, value in fixed.items() if value == subject]:
        fixed.pop(key)

    for day, lesson in slots:
        fixed[f"{day}-{lesson}"] = subject

    if not fixed:
        settings["constants"].pop(course, None)

    return settings


def plannedMoves(current, pinned, hours):
    """Планирует перенос уроков курса под новые закрепления.

    ``current`` — где уроки стоят сейчас; ``pinned`` — новые закреплённые места, которые
    обязательно должны быть заняты; ``hours`` — сколько всего уроков у курса. Остальные
    уроки по возможности остаются на своих местах, освободившиеся места уходят под
    новые закрепления.

    Возвращает (moves [(старое место, новое место)], итоговые места отсортированно).
    """
    # Сначала закреплённые места (не больше нагрузки), потом добираем текущими. Текущие уроки
    # в другие дни берутся первыми: урок, стоящий в день нового закрепления, иначе остался бы
    # рядом с ним — два урока курса в один день (например, уроки Пн-1 и Ср-1, закрепили Пн-2:
    # переезжает урок Пн-1, а не Ср-1)
    final = list(dict.fromkeys(pinned))[:hours]
    pinned_days = {slot[0] for slot in final}
    rest = [slot for slot in current if slot not in final]
    rest.sort(key=lambda slot: slot[0] in pinned_days)
    final += rest[:hours - len(final)]

    removed = [slot for slot in current if slot not in final]
    added = [slot for slot in final if slot not in current]

    # Каждый убранный урок переезжает на одно новое место; лишние убранные или
    # добавленные места без пары в moves не попадают
    return list(zip(removed, added)), sorted(final)


def slotConflicts(settings, answer, course, subject, moves):
    """Почему уроки курса нельзя перенести на новые места в готовом расписании как оно есть.

    ``moves`` — список (старое место, новое место) из ``plannedMoves``.
    Возвращает [(день, урок, причина, подробность)], где причина:
    - "missing" — такого урока нет в сетке занятий;
    - "course" — у курса в это время уже стоит другой урок (подробность — предмет);
    - "unavailable" — преподаватель курса в это время отметил «не может» (подробность — имя);
    - "busy" — преподаватель в это время ведёт курс ``подробность``;
    - "pair" — в той же линейке того же потока стоит курс ``подробность``, чей предмет
      образует с нашим пару «нельзя одновременно»;
    - "program" — курс ``подробность`` из программы, которая не должна пересекаться
      с нашей («Семинары» / «ЕГЭ продвинутый»), с тем же предметом.

    Уроки копий повторяют уроки источника и переезжают вместе с ними (раздел 7), поэтому помехи
    ("busy", "pair", "program") ищутся у каждого курса группы «источник + копии» — в его потоке
    и в его даты; сами курсы группы друг другу не помеха. Одна и та же помеха — один раз.
    """
    by_name = groupsByName(settings)
    group = by_name.get(course, {})
    shared = sharedCourses(copySources(by_name), course)
    # Места, которые освобождаются при переносе: занятость ими не считается конфликтом
    leaving = {old for old, _ in moves}
    conflicts = []

    for old, (day, lesson) in moves:
        if not lessonExists(settings, day, lesson):
            conflicts.append((day, lesson, "missing", ""))
            continue

        # Преподаватели переносимого урока (берутся из его старой ячейки)
        teachers = list(answer[course][old[0]][old[1]].get("teachers", []))

        conflicts += ownSlotConflicts(answer, course, day, lesson, leaving)
        conflicts += [(day, lesson, "unavailable", teacher) for teacher in teachers
                      if group and [day, lesson] in cannotSlots(settings, teacher, stageKey(group))]

        for member in shared:
            conflicts += peerSlotConflicts(settings, answer, by_name, member, subject, teachers, (day, lesson), shared)

    # Курс, который идёт одновременно и с источником, и с копией, нашёлся бы дважды
    return list(dict.fromkeys(conflicts))


def ownSlotConflicts(answer, course, day, lesson, leaving):
    """Занято ли новое место у самого курса (кроме мест, которые при переносе освобождаются)."""
    cells = answer.get(course, [])
    cell = cells[day][lesson] if day < len(cells) and lesson < len(cells[day]) else emptyCell()

    return [(day, lesson, "course", cell.get("subject"))] if isLesson(cell) and (day, lesson) not in leaving else []


def peerSlotConflicts(settings, answer, by_name, course, subject, teachers, slot, shared):
    """Помехи от уроков других курсов в это же время: "busy", "pair" и "program" (см. slotConflicts).

    Курс, который идёт в другие даты (закончился до начала нашего или начнётся после его
    конца), не мешает. Курсы ``shared`` (сам курс и его общие уроки, ``sharedCourses``) тоже
    не мешают: это те же уроки.
    """
    day, lesson = slot
    group = by_name.get(course, {})
    hard_pairs = subjectPairs(settings, "joint_subject_pairs")
    programs = programPairs(settings)
    conflicts = []

    for other, week in answer.items():
        if other in shared or day >= len(week) or lesson >= len(week[day]) or not isLesson(week[day][lesson]):
            continue

        peer = by_name.get(other, {})

        if group and peer and not coursesOverlap(settings, group, peer):
            continue

        entry = week[day][lesson]

        if any(teacher in teachers for teacher in entry.get("teachers", [])):
            conflicts.append((day, lesson, "busy", other))

        # Пары предметов действуют только внутри одной линейки одного потока
        if sameLine(group, peer) and isSubjectPair(hard_pairs, subject, entry.get("subject")):
            conflicts.append((day, lesson, "pair", other))

        if (group.get("program"), peer.get("program")) in programs and entry.get("subject") == subject:
            conflicts.append((day, lesson, "program", other))

    return conflicts


def moveLessons(answer, course, moves):
    """Переносит уроки курса в расписании ``answer`` по списку ``moves`` [(старое место, новое место)].

    Сначала все старые места очищаются (чтобы обмен местами внутри курса работал),
    затем ячейки ставятся на новые места; при необходимости неделя курса дополняется
    пустыми днями и уроками. Меняет ``answer`` на месте и возвращает его.
    """
    week = answer.get(course, [])
    cells = {old: week[old[0]][old[1]] for old, _ in moves}

    for old, _ in moves:
        week[old[0]][old[1]] = emptyCell()

    for old, (day, lesson) in moves:
        while len(week) <= day:
            week.append([])

        while len(week[day]) <= lesson:
            week[day].append(emptyCell())

        week[day][lesson] = cells[old]

    return answer


# ---------------------------------------------------------------- 7. общие уроки линеек

def copySource(group, by_name):
    """Имя курса-источника, если курс ``group`` — курс-копия, иначе None. ``by_name`` — курсы проекта по названию.

    Курс-копия — курс линейки потока, которая идёт вместе с более ранним Потоком N: у него поле
    ``together_with = N`` (ставит и снимает joint.setJointLine). Его источник — курс того же предмета
    той же линейки Потока N; имя строится через ``courseName``, а не разбором названия копии.

    None и тогда, когда отметка недействительна: у блока, на свой или более поздний поток, источника
    нет (его удалили) или он сам идёт вместе с кем-то (цепочек не бывает — такую отметку оставила бы
    только ручная правка файла). Так пропавший источник мягко делает копию обычным курсом.
    """
    number, stream = group.get("together_with"), group.get("stream_id")

    if number is None or stream is None or number >= stream:
        return None

    name = courseName(number, lineOf(group), courseSubject(group))
    source = by_name.get(name)

    return name if source is not None and "together_with" not in source else None


def copySources(by_name):
    """Все курсы-копии с живым источником: {копия: источник} в порядке курсов ``by_name``."""
    copies = {}

    for name, group in by_name.items():
        source = copySource(group, by_name)

        if source is not None:
            copies[name] = source

    return copies


def copyRoot(copies, course):
    """Курс, который отвечает за уроки курса ``course``: источник у копии, у остальных — сам ``course``.

    ``copies`` — {копия: источник} (``copySources``), прочитанные один раз. По корню читатели сводят
    пару «источник + копия» к одному курсу: один урок, один курс в лимите преподавателя.
    """
    return copies.get(course, course)


def copiesOf(copies, courses):
    """Копии курсов ``courses``: {копия: источник} в порядке ``copies``.

    Нужны там, где меняются уроки источников (принятие варианта, «Убрать из расписания», удаление
    курсов): их копии меняются вместе с ними.
    """
    courses = set(courses)

    return {name: source for name, source in copies.items() if source in courses}


def copyFollowers(copies):
    """{источник: [его копии…]} — те же ``copies``, собранные по источникам (порядок копий сохраняется)."""
    followers = {}

    for name, source in copies.items():
        followers.setdefault(source, []).append(name)

    return followers


def sharedCourses(copies, course):
    """Группа общих уроков курса ``course``: [источник, его копии…]; у обычного курса — [course].

    ``copies`` — {копия: источник} (``copySources``). Первый в списке — источник: он отвечает за
    уроки всей группы, по нему пара «источник + копия» считается одним курсом.
    """
    root = copyRoot(copies, course)

    return [root] + copyFollowers(copies).get(root, [])


def lineTogetherWith(settings, section, line):
    """Номер потока, вместе с которым идёт линейка ``line`` раздела ``section``, или None.

    Линейка идёт вместе с Потоком N, если хотя бы у одного её курса действующая отметка N
    (разные N внутри одной линейки joint.setJointLine не ставит).
    """
    by_name = groupsByName(settings)

    return next((group["together_with"] for group in lineCourses(settings, section, line) if copySource(group, by_name)), None)
