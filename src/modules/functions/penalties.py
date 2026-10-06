"""Свои правила («Свои правила»): мягкие правила пользователя, собранные из шаблонов.

``settings["custom_penalties"]`` — список словарей
    {"id", "name", "template", "weight", "params"}
Имя нужно только людям (список на вкладке «Запуск», строка в таблице на вкладке «Предпросмотр»);
шаблон и его параметры говорят решателю, что искать, а вес (weight) — сколько стоит каждое
нарушение.

Каждый шаблон описан в ``RULES`` тремя функциями (одно описание на все три задачи):
* compile — простые цены для решателя (``compilePenalties``: за урок курса в слоте, за урок
  преподавателя в слоте, за день…);
* count — сколько раз правило нарушено в построенной неделе (``countPenalties``, таблица
  вариантов на «Предпросмотре»);
* lessons — какие именно уроки его нарушают (``penaltyLessons``, подписи на карточках уроков);
  у «не больше N уроков в день» её нет: в нём виноват не один урок, а весь день целиком.

Шаблоны и параметры:
    time         {"target": "all|line|subject|course|teacher", "value": str, "days": [int], "times": [str]}
                 урок цели в один из дней в одно из времён (например, «не ставить
                 химию в пятницу на 19:40»)
    daily_limit  {"target": "teacher|line", "value": str ("" = каждый), "limit": int}
                 каждый урок сверх лимита в один день
    adjacent     {"target": "all|line|subject|course", "value": str}
                 уроки одного курса в два соседних дня (пн и вт)
    same_day     {"first": предмет, "second": предмет}
                 два предмета в один день внутри одной линейки одного раздела (потока или блока)

Здесь «линейка» — как на вкладке «Курсы» (courses.lineOf): у курса потока это программа
(ОГЭ, ЕГЭ основной, ЕГЭ продвинутый, 10 класс…; оба ЕГЭ здесь — разные линейки), у курса
блока — своя линейка (у доп. курсов, например, «Семинар ОГЭ», «Семинар ЕГЭ продвинутый»).
Этап — один раздел (один поток или один блок), и цель «line» со значением — эта линейка
среди курсов этапа.

Курсы-копии («линейка идёт вместе с Потоком N», joint.py) правила не касаются: их уроки
неподвижны, решатель этапа их не получает (solver_input), и подсчёт нарушений их тоже
не видит (``penaltyGroups``) — так число нарушений совпадает с тем, за что штрафует решатель.

Зависимости: model, grid (время уроков), courses (линейка курса), joint (курсы-копии),
src.modules.translate (подстановка значений в описание правила).
"""

import uuid

from src.modules.functions.courses import lineOf
from src.modules.functions.grid import dayGrid
from src.modules.functions.joint import jointCopies
from src.modules.functions.model import courseSubject, lessonEntries, sectionOf, stageGroups
from src.modules.translate import fill

# Вес «Средне» для своего правила: от него страница строит деления ползунка «Неважно … Очень
# важно», и с ним открывается диалог нового правила. Столько же стоит по умолчанию «урок во время
# «может»» (teacherPossibleSlot в src/files/weights.json). Страница получает его через /api/meta
MEDIUM_WEIGHT = 300

# Внутренний ключ строки своего правила на листе сравнения в книге Excel с вариантами
# (tabs/export.variantsBook → export.compareSheet): "custom:<id правила>"; у встроенных правил
# ключ — имя метрики (variants.METRICS). Собирает его только customKey, разбирает только customId.
# В API и в файлах проекта этого ключа нет: страница берёт число нарушений своего правила
# из metrics.custom[<id>]
CUSTOM_PREFIX = "custom:"


def customKey(penalty_id):
    """Ключ строки своего правила с этим id: "custom:<id>"."""
    return CUSTOM_PREFIX + penalty_id


def customId(key):
    """id своего правила по ключу строки; у строки встроенного правила — None."""
    return key[len(CUSTOM_PREFIX):] if key.startswith(CUSTOM_PREFIX) else None


def penalties(settings):
    """Список своих правил проекта; создаёт пустой в ``settings``, если его нет (меняет на месте)."""
    return settings.setdefault("custom_penalties", [])


def newPenalty(name, template, weight, params):
    """Новое правило со случайным коротким id (8 шестнадцатеричных символов)."""
    return {"id": uuid.uuid4().hex[:8], "name": name.strip(), "template": template, "weight": int(weight), "params": params}


def renamePenaltyTimes(settings, renamed):
    """Правила «Не ставить уроки в выбранное время» (template "time") хранят время уроков текстом: после
    правки сетки старый текст времени заменяется новым по словарю ``renamed`` {старое: новое}.

    Повторы, если два времени слились в одно, убираются; порядок сохраняется. Меняет
    ``settings`` на месте.
    """
    for penalty in penalties(settings):
        if penalty.get("template") == "time":
            penalty["params"]["times"] = list(dict.fromkeys(renamed.get(time, time) for time in penalty["params"].get("times", [])))


def dropTargeted(settings, target, names):
    """Убирает правила, нацеленные на удалённые курсы или преподавателей.

    ``target`` — "course" или "teacher", ``names`` — их имена. Меняет ``settings`` на месте;
    True, если какое-то правило убрано.
    """
    names = set(names)
    kept = [item for item in penalties(settings) if not (item.get("params", {}).get("target") == target and item["params"].get("value") in names)]
    changed = len(kept) != len(penalties(settings))
    settings["custom_penalties"] = kept

    return changed


# ---------------------------------------------------------------- цели и слоты правила

def courseMatches(group, target, value):
    """Подходит ли курс ``group`` под цель правила (``target`` + ``value``).

    all — любой курс; line — курс линейки ``value``; subject — курс с предметом ``value``;
    course — курс с именем ``value``. Цель teacher здесь не подходит ни одному курсу
    (она обрабатывается отдельно).
    """
    if target == "all":
        return True

    if target == "line":
        return lineOf(group) == value

    if target == "subject":
        return value in group.get("subjects", [])

    if target == "course":
        return group.get("name") == value

    return False


def penaltyTeachers(params, everyone):
    """Преподаватели, на которых нацелено правило: выбранный или, если не выбран, ``everyone``."""
    return [params["value"]] if params.get("value") else list(everyone)


def penaltySlots(settings, params):
    """[(день, урок)] выбранных дней и времён уроков, которые есть в сетке.

    Время урока сравнивается текстом («16:20 - 17:50»), поэтому если в сетке дня такого
    времени нет, слот просто не попадает в результат.
    """
    grid = dayGrid(settings)
    times = set(params.get("times", []))
    result = []

    for day in params.get("days", []):
        if 0 <= day < len(grid):
            for lesson, time in enumerate(grid[day]):
                if time in times:
                    result.append((day, lesson))

    return result


def lineGroups(groups, value):
    """{(раздел, линейка): [имена курсов]} — каждая линейка каждого раздела (потока или блока) или только линейка ``value``.

    «Раздел» (``sectionOf``) — поток (или блок) курса, так что одна и та же линейка разных
    потоков даёт разные группы.
    """
    result = {}

    for group in groups:
        line = lineOf(group)

        if value and line != value:
            continue

        result.setdefault((sectionOf(group), line), []).append(group["name"])

    return result


def sameDayCoursePairs(groups, first, second):
    """Пары курсов (a, b) одной линейки одного раздела, чьи предметы — ``first`` и ``second``.

    a < b по названию, чтобы каждая пара попала один раз. Курс без предметов не подходит.
    """
    subjects = {group["name"]: courseSubject(group) for group in groups}

    for courses in lineGroups(groups, "").values():
        for a in courses:
            for b in courses:
                if a < b and {first, second} == {subjects[a], subjects[b]}:
                    yield a, b


def penaltyGroups(settings, stage):
    """Курсы этапа ``stage``, к которым относятся свои правила: все, кроме курсов-копий.

    Уроки копии задаёт поток-источник, решатель этапа их не двигает: цены за них ничего бы
    не дали, а нарушения из-за них нельзя исправить в этом этапе.
    """
    copies = jointCopies(settings)

    return [group for group in stageGroups(settings, stage) if group["name"] not in copies]


def overLimit(days, limit):
    """Сколько уроков сверх ``limit`` в каждый день, вместе: ``days`` — день каждого урока."""
    return sum(max(0, days.count(day) - limit) for day in set(days))


# ---------------------------------------------------------------- неделя этапа для подсчёта нарушений

class StageWeek:
    """Уроки варианта этапа, разложенные для подсчёта своих правил.

    * ``groups`` — курсы этапа без копий (``penaltyGroups``); ``by_name`` — они же по названию;
    * ``lessons`` — {курс: [(день, урок, преподаватели)]};
    * ``course_days`` — {курс: [день каждого урока]}; ``course_slots`` — {курс: {(день, урок)}};
    * ``teacher_slots`` — {преподаватель: [(день, урок)]}.
    """

    def __init__(self, settings, stage, variant):
        self.settings = settings
        self.groups = penaltyGroups(settings, stage)
        self.by_name = {group["name"]: group for group in self.groups}
        self.lessons = {
            name: [(day, lesson, entry.get("teachers", [])) for day, lesson, entry in lessonEntries(variant, name)]
            for name in self.by_name
        }
        self.course_days = {name: [day for day, _, _ in items] for name, items in self.lessons.items()}
        self.course_slots = {name: {(day, lesson) for day, lesson, _ in items} for name, items in self.lessons.items()}
        self.teacher_slots = {}

        for items in self.lessons.values():
            for day, lesson, teachers in items:
                for teacher in teachers:
                    self.teacher_slots.setdefault(teacher, []).append((day, lesson))

    def matching(self, params):
        """Курсы этапа, подходящие под цель правила (кроме цели «преподаватель»): [(название, курс)]."""
        return [(name, group) for name, group in self.by_name.items() if courseMatches(group, params.get("target"), params.get("value"))]


# ---------------------------------------------------------------- шаблон time: не ставить уроки в выбранное время

def compileTime(result, settings, groups, params, weight):
    """Цена за урок цели (курса или преподавателя) в каждом выбранном слоте."""
    slots = penaltySlots(settings, params)

    if params.get("target") == "teacher":
        for teacher in penaltyTeachers(params, settings.get("teachers", {})):
            result["teacher_slots"].setdefault(teacher, []).extend([day, lesson, weight] for day, lesson in slots)

        return

    for group in groups:
        if courseMatches(group, params.get("target"), params.get("value")):
            result["class_slots"].setdefault(group["name"], []).extend([day, lesson, weight] for day, lesson in slots)


def countTime(week, params):
    """Уроки цели, попавшие в выбранные слоты."""
    slots = set(penaltySlots(week.settings, params))

    if params.get("target") == "teacher":
        return sum(1 for teacher in penaltyTeachers(params, week.teacher_slots) for slot in week.teacher_slots.get(teacher, []) if slot in slots)

    return sum(len(week.course_slots[name] & slots) for name, _ in week.matching(params))


def timeLessons(week, params):
    """Уроки в выбранных слотах: у цели «преподаватель» — его (или любого) уроки, иначе уроки курсов цели."""
    slots = set(penaltySlots(week.settings, params))

    for name, group in week.by_name.items():
        for day, lesson, teachers in week.lessons[name]:
            if (day, lesson) not in slots:
                continue

            if params.get("target") == "teacher":
                hit = any(not params.get("value") or teacher == params["value"] for teacher in teachers)

            else:
                hit = courseMatches(group, params.get("target"), params.get("value"))

            if hit:
                yield name, day, lesson


# ---------------------------------------------------------------- шаблон daily_limit: не больше N уроков в день

def compileDailyLimit(result, settings, groups, params, weight):
    """Цена за каждый урок сверх лимита в день: у преподавателя или у всей линейки раздела."""
    limit = int(params.get("limit", 0) or 0)

    if params.get("target") == "teacher":
        for teacher in penaltyTeachers(params, settings.get("teachers", {})):
            result["teacher_daily"].setdefault(teacher, []).append([limit, weight])

        return

    # Лимит считается по всей линейке раздела (потока или блока): уроки всех её курсов в один день
    for courses in lineGroups(groups, params.get("value")).values():
        result["group_daily"].append({"classes": courses, "limit": limit, "weight": weight})


def countDailyLimit(week, params):
    """Каждый урок сверх лимита в каждый день."""
    limit = int(params.get("limit", 0) or 0)

    if params.get("target") == "teacher":
        return sum(overLimit([day for day, _ in week.teacher_slots.get(teacher, [])], limit) for teacher in penaltyTeachers(params, week.teacher_slots))

    return sum(overLimit([day for name in courses for day in week.course_days[name]], limit) for courses in lineGroups(week.groups, params.get("value")).values())


# ---------------------------------------------------------------- шаблон adjacent: не в соседние дни

def compileAdjacent(result, settings, groups, params, weight):
    """Цена за пару уроков курса в соседние дни; несколько подходящих правил на один курс складываются."""
    for group in groups:
        if courseMatches(group, params.get("target"), params.get("value")):
            result["adjacent"][group["name"]] = result["adjacent"].get(group["name"], 0) + weight


def countAdjacent(week, params):
    """Каждая пара соседних дней (день и следующий за ним), в которые у курса цели есть уроки."""
    count = 0

    for name, _ in week.matching(params):
        days = set(week.course_days[name])
        count += sum(1 for day in days if day + 1 in days)

    return count


def adjacentLessons(week, params):
    """Оба урока каждой пары соседних дней у курсов цели."""
    for name, _ in week.matching(params):
        days = set(week.course_days[name])

        for day, lesson, _ in week.lessons[name]:
            if day + 1 in days or day - 1 in days:
                yield name, day, lesson


# ---------------------------------------------------------------- шаблон same_day: два предмета в один день

def compileSameDay(result, settings, groups, params, weight):
    """Цена за каждый общий день у пары курсов одной линейки раздела с предметами first и second."""
    for a, b in sameDayCoursePairs(groups, params.get("first"), params.get("second")):
        result["same_day"].append({"a": a, "b": b, "weight": weight})


def countSameDay(week, params):
    """Число общих дней у каждой подходящей пары курсов одной линейки."""
    return sum(
        len(set(week.course_days[a]) & set(week.course_days[b]))
        for a, b in sameDayCoursePairs(week.groups, params.get("first"), params.get("second"))
    )


def sameDayLessons(week, params):
    """Уроки обоих курсов пары в их общие дни."""
    for a, b in sameDayCoursePairs(week.groups, params.get("first"), params.get("second")):
        common = set(week.course_days[a]) & set(week.course_days[b])

        for name in (a, b):
            for day, lesson, _ in week.lessons[name]:
                if day in common:
                    yield name, day, lesson


# Шаблоны правил: имя -> {"compile", "count", "lessons"} (см. шапку модуля). Порядок — порядок
# шаблонов в диалоге «Правило»
RULES = {
    "time": {"compile": compileTime, "count": countTime, "lessons": timeLessons},
    "daily_limit": {"compile": compileDailyLimit, "count": countDailyLimit, "lessons": None},
    "adjacent": {"compile": compileAdjacent, "count": countAdjacent, "lessons": adjacentLessons},
    "same_day": {"compile": compileSameDay, "count": countSameDay, "lessons": sameDayLessons},
}

# Все шаблоны и допустимые цели для каждого (у same_day цели нет — у него два предмета)
TEMPLATES = tuple(RULES)
TARGETS = {
    "time": ("all", "line", "subject", "course", "teacher"),
    "daily_limit": ("teacher", "line"),
    "adjacent": ("all", "line", "subject", "course"),
}


# ---------------------------------------------------------------- точки входа

def compilePenalties(settings, stage):
    """Простые цены для решателя по курсам одного этапа (без курсов-копий, ``penaltyGroups``).

    Возвращает словарь (попадает во вход решателя как ``custom_penalties_compiled``):
    * ``class_slots`` — курс -> [[день, урок, цена]]: урок курса в этом слоте стоит «цена»;
    * ``teacher_slots`` — преподаватель -> [[день, урок, цена]];
    * ``teacher_daily`` — преподаватель -> [[лимит, цена]]: каждый урок сверх лимита в день;
    * ``group_daily`` — [{"classes": [курсы линейки], "limit", "weight"}]: то же для линейки;
    * ``adjacent`` — курс -> цена за пару уроков в соседние дни;
    * ``same_day`` — [{"a": курс, "b": курс, "weight"}]: цена за каждый общий день.
    Правила с весом 0 и меньше и неизвестные шаблоны пропускаются.
    """
    groups = penaltyGroups(settings, stage)
    result = {"class_slots": {}, "teacher_slots": {}, "teacher_daily": {}, "group_daily": [], "adjacent": {}, "same_day": []}

    for penalty in penalties(settings):
        weight = int(penalty.get("weight", 0) or 0)
        rule = RULES.get(penalty.get("template"))

        if weight > 0 and rule:
            rule["compile"](result, settings, groups, penalty.get("params", {}), weight)

    return result


def countPenalties(settings, stage, variant):
    """{id правила: сколько раз оно нарушено} в построенной неделе этапа (``variant`` — как answer.json).

    Считает так же, как решатель штрафует по ``compilePenalties``, но без весов; в отличие
    от неё учитывает и правила с нулевым весом (для них тоже показывается число нарушений).
    Неизвестный шаблон — 0 нарушений.
    """
    week = StageWeek(settings, stage, variant)
    result = {}

    for penalty in penalties(settings):
        rule = RULES.get(penalty.get("template"))
        result[penalty["id"]] = rule["count"](week, penalty.get("params", {})) if rule else 0

    return result


def penaltyLessons(settings, stage, variant):
    """Какие уроки нарушают свои правила: {(курс, день, урок): [название правила, …]}.

    Нужна для подписей на карточках уроков в «Предпросмотре». Считает так же, как
    ``countPenalties``, но запоминает сами уроки (у «не больше N уроков в день» их нет).
    """
    week = StageWeek(settings, stage, variant)
    result = {}

    for penalty in penalties(settings):
        rule = RULES.get(penalty.get("template"))

        for lesson in rule["lessons"](week, penalty.get("params", {})) if rule and rule["lessons"] else ():
            names = result.setdefault(lesson, [])

            if penalty.get("name") not in names:
                names.append(penalty.get("name"))

    return result


def describePenalty(penalty, translate):
    """Фраза о том, что проверяет правило, — для списка на вкладке «Запуск» и подсказки на «Предпросмотре».

    Текст собирается из шаблонов ``penalty.describe.*`` в ru.hjson, в которые подставляются
    {target}, {days}, {times}, {limit}, {first}, {second} (за один проход, как в tr: значение
    с фигурными скобками, например название курса, не подставляется повторно). Неизвестный
    шаблон — пустая строка.
    """
    params = penalty.get("params", {})
    template = penalty.get("template")

    if template not in RULES:
        return ""

    values = {
        "target": penaltyTarget(params, translate),
        "days": ", ".join(translate(f"abbreviate.day.{day}") for day in sorted(params.get("days", []))) or "—",
        "times": ", ".join(sorted(params.get("times", []))) or "—",
        "limit": params.get("limit", 0),
        "first": params.get("first", ""),
        "second": params.get("second", ""),
    }

    return fill(translate(f"penalty.describe.{template}"), **values)


def penaltyTarget(params, translate):
    """Описание цели правила: «все курсы», «каждый преподаватель», «линейка «ОГЭ»»…"""
    kind = params.get("target", "all")
    value = params.get("value") or ""

    if kind == "all":
        return translate("penalty.target.all")

    if not value:
        return translate(f"penalty.target.every_{kind}")

    return f"{translate(f'penalty.target.{kind}')} «{value}»"
