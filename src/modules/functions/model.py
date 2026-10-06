"""Модель данных проекта: самые простые понятия, на которых стоят все остальные модули.

Модуль ничего не импортирует из предметного слоя (нижний слой, см. шапку
``src/modules/functions/__init__.py``), поэтому его функции может брать любой модуль
без риска циклов импорта. Всё здесь только читает данные и ничего не меняет, кроме
``teacherAvailability`` (она создаёт пустые отметки этапа, см. её описание).

Данные проекта
--------------
* ``settings`` — настройки проекта (settings.json):

  - ``settings["classes"]["custom_groups"]`` — список курсов. Курс («группа» в данных) —
    словарь {"name", "program", "line", "subjects", "stream_id", "start_date", "end_date"},
    у курса без потока ещё "block", у курса-копии присоединённой линейки ещё "together_with"
    (номер более раннего потока, см. joint.py и DATA_CONTRACT §3.12). Один курс — один предмет
    одной линейки в одном потоке
    («Поток 1 — ОГЭ — Литература») или курс без потока (семинары и другие блоки);
  - ``settings["classes"]["lessons"]`` — недельная нагрузка {курс: {предмет: уроков в неделю}};
  - ``settings["teachers"]`` — преподаватели {имя: {"subjects": [{"subject", "classes" (курсы,
    которые может вести), "assigned" (курсы, которые ведёт точно)}], "forbidden" (курсы, которые
    вести нельзя), "availability" (отметки времени по этапам, см. ``teacherAvailability``)}};
  - ``settings["constants"]`` — закреплённые уроки {курс: {"день-урок": предмет}};
  - ``settings["joint_subject_pairs"]`` / ``["soft_subject_pairs"]`` — пары предметов «нельзя» /
    «нежелательно» одновременно, ``["non_overlapping_programs"]`` — пары программ, уроки одного
    предмета в которых не совпадают по времени (см. pairs.py).

* ``answer`` — принятое расписание (answer.json) или вариант этапа в том же виде:
  {курс: неделя}, неделя — список дней, день — список ячеек-уроков {"subject", "teachers"}.
  У пустой ячейки ``"subject": "#"`` (``EMPTY_SUBJECT``).

Раздел и этап
-------------
* Раздел (section) — где курс стоит на вкладке «Курсы»: номер потока (int) или ключ блока
  курсов без потока (str: "extra" — доп. курсы, "may" — майские марафоны, "summer" — летняя
  школа). В аргументе section функций предметного слоя None тоже означает доп. курсы
  (``normalizeSection``). Раздел курса из данных (``sectionOf``) None не бывает: курс без
  "stream_id" относится к своему блоку ("block") или к "extra". Сервер раздел None не принимает
  (project.requireSection).
* Этап (stage) — то, что строится за один запуск решателя: курсы одного раздела. Ключ этапа —
  раздел строкой: "1", "2"… или "extra", "may"… (``stageKey``).
"""

# Ключ блока доп. курсов: раздел курса без потока и без указанного блока
EXTRA_BLOCK = "extra"

# Предмет пустой ячейки расписания
EMPTY_SUBJECT = "#"


# ---------------------------------------------------------------- разделы и этапы

def normalizeSection(section):
    """Приводит аргумент section к ключу раздела: None -> "extra" (доп. курсы); остальное как есть."""
    return EXTRA_BLOCK if section is None else section


def isBlock(section):
    """True, если раздел — блок без потока (ключ-строка), а не номер потока."""
    return isinstance(normalizeSection(section), str)


def sectionOf(group):
    """Раздел курса ``group``: номер потока, если он есть, иначе ключ блока (по умолчанию "extra")."""
    if group.get("stream_id") is not None:
        return group["stream_id"]

    return group.get("block") or EXTRA_BLOCK


def inSection(group, section):
    """True, если курс ``group`` относится к разделу ``section`` (поток или блок)."""
    return sectionOf(group) == normalizeSection(section)


def stageKey(group):
    """Ключ этапа курса ``group``: его раздел строкой («1», «2»… или "extra", "may"…)."""
    return str(sectionOf(group))


def isBlockStage(stage):
    """True, если этап — блок курсов без потока (а не «Поток N»): ключи потоков — числа."""
    return not str(stage).isdigit()


# ---------------------------------------------------------------- курсы

def courseGroups(settings):
    """Список курсов проекта (``classes.custom_groups``) только для чтения: нет — пустой список."""
    return settings.get("classes", {}).get("custom_groups", [])


def courseNames(settings):
    """Названия всех курсов проекта в порядке их хранения."""
    return [group["name"] for group in courseGroups(settings)]


def groupsByName(settings):
    """Курсы проекта по названию: {название: курс}."""
    return {group["name"]: group for group in courseGroups(settings)}


def stageGroups(settings, stage):
    """Курсы этапа ``stage`` в порядке их хранения; нет такого этапа — пустой список."""
    return [group for group in courseGroups(settings) if stageKey(group) == stage]


def courseSubject(group):
    """Предмет курса (у курса в этой школе один предмет); у курса без предметов — ""."""
    return (group.get("subjects") or [""])[0]


# ---------------------------------------------------------------- даты курсов

def courseDates(settings, group):
    """(начало, конец) курса как ISO-строки; неизвестные границы считаются открытыми.

    Нет даты старта — курс идёт «с начала времён» ("0000-00-00"); нет даты окончания —
    до конца учебного календаря (``calendar_end_date``), а если и его нет — «навсегда».
    """
    start = group.get("start_date") or "0000-00-00"
    end = group.get("end_date") or settings.get("calendar_end_date") or "9999-99-99"

    return start, end


def datesOverlap(first, second):
    """Пересекаются ли два промежутка дат (пары ISO-строк, границы включительно)."""
    return first[0] <= second[1] and second[0] <= first[1]


def coursesOverlap(settings, first, second):
    """Идут ли курсы ``first`` и ``second`` (элементы custom_groups) хотя бы день одновременно.

    Курсы в разные месяцы не делят ни время преподавателя, ни учеников.
    """
    return datesOverlap(courseDates(settings, first), courseDates(settings, second))


# ---------------------------------------------------------------- уроки в расписании

def emptyCell():
    """Новая пустая ячейка расписания."""
    return {"subject": EMPTY_SUBJECT, "teachers": []}


def isLesson(cell):
    """Стоит ли в ячейке расписания урок (а не пустое место)."""
    return cell.get("subject", EMPTY_SUBJECT) != EMPTY_SUBJECT


def lessonEntries(answer, course):
    """Все уроки курса в расписании ``answer`` по одному: (день, номер урока, ячейка).

    Пустые ячейки пропускаются.
    """
    for day, cells in enumerate(answer.get(course, [])):
        for lesson, cell in enumerate(cells):
            if isLesson(cell):
                yield day, lesson, cell


def hasLessons(answer, course):
    """Есть ли у курса хотя бы один урок в расписании (или варианте) ``answer``."""
    return next(lessonEntries(answer, course), None) is not None


def courseSlots(answer, course, subject):
    """Список (день, урок) уроков курса по предмету ``subject`` в расписании ``answer``."""
    return [(day, lesson) for day, lesson, cell in lessonEntries(answer, course) if cell.get("subject") == subject]


def allLessons(answer):
    """Все уроки расписания ``answer`` по одному: (курс, день, урок, ячейка).

    Курсы идут в порядке ``answer``, пустые ячейки пропускаются. Ячейку можно менять на месте.
    """
    for course in answer:
        for day, lesson, cell in lessonEntries(answer, course):
            yield course, day, lesson, cell


def teacherLessons(answer, name, except_subjects=None):
    """Уроки преподавателя ``name`` в расписании по одному: (курс, день, урок, ячейка).

    ``except_subjects`` — уроки этих предметов пропускаются (нужно, когда у преподавателя
    убирают только часть предметов). Ячейку можно менять на месте.
    """
    for course, day, lesson, cell in allLessons(answer):
        if name in cell.get("teachers", []) and (except_subjects is None or cell.get("subject") not in except_subjects):
            yield course, day, lesson, cell


# ---------------------------------------------------------------- отметки времени преподавателя

def teacherAvailability(teacher, stage):
    """Отметки времени преподавателя на этапе ``stage``; создаёт пустые, если их ещё нет.

    Пустые отметки («удобно» во всё время) появляются так у каждого нового этапа —
    например, у только что добавленного потока — при первом обращении к ним.
    Меняет ``teacher`` на месте. Возвращает словарь ``{"free": [...], "possible": [...]}``
    со списками слотов ``[день, урок]``:

    * "free" — «не может». Имя историческое и обманчивое: так этот список называет решатель
      (solve.cpp), поэтому в данных проекта оно осталось. Везде вне данных (тексты, выгрузка,
      имена переменных) это «не может» / cannot;
    * "possible" — «может» (можно, но лучше не надо);
    * все остальные слоты — «удобно».

    Это единственное место, где описан смысл ключей; читать отметки без изменения данных —
    ``stageMarks``, ``cannotSlots``, ``possibleSlots``.
    """
    data = teacher.setdefault("availability", {}).setdefault(stage, {})
    data.setdefault("free", [])
    data.setdefault("possible", [])

    return data


def stageMarks(settings, teacher, stage):
    """Отметки преподавателя на этапе только для чтения: {"free", "possible"} или {} (ничего не создаёт)."""
    return settings.get("teachers", {}).get(teacher, {}).get("availability", {}).get(stage, {})


def cannotSlots(settings, teacher, stage):
    """Слоты [день, урок], отмеченные у преподавателя «не может» на этапе."""
    return stageMarks(settings, teacher, stage).get("free", [])


def possibleSlots(settings, teacher, stage):
    """Слоты [день, урок], отмеченные у преподавателя «может» на этапе."""
    return stageMarks(settings, teacher, stage).get("possible", [])
