"""Сетка дня: время уроков по дням недели (задаётся на вкладке «Настройки»).

``settings["day_grid"]`` хранит 7 списков (понедельник..воскресенье) со временем уроков
дня («16:20 - 17:50»). День без уроков — выходной. ``working_days_per_week`` и
``max_lesson_count_per_day`` вычисляются из сетки для остальной программы: решатель
работает с прямоугольной неделей «рабочие дни × максимум уроков в день», а слоты, которых
в сетке нет (в какой-то день уроков меньше), передаются ему как недоступные
(``missingSlots``).

Урок везде адресуется парой (день, номер урока в дне), считая с нуля. Поэтому при
правке сетки уроки расписания приходится переносить по новым номерам.

Правка сетки на «Настройках» (действие setGrid в src/web/tabs/settings.py) идёт так:
1. ``parseGrid`` — разбор введённых текстов и проверка порядка времён (ошибка — ``GridError``);
2. ``columnMapping`` — куда переезжает каждый урок: урок остаётся в своём столбце, очищенная
   ячейка забирает свои уроки;
3. ``remapAnswer`` / ``lostPins`` — что при этом потеряется (уроки расписания, закрепления);
4. ``renamedTimes`` — какое время уроков переписали (для правил «Не ставить уроки в выбранное время»);
5. ``keepsColumns`` — сдвинулся ли хоть один урок; если да, ``remapSettings`` переносит
   закрепления и отметки доступности, а расписание берётся из ``remapAnswer``;
6. ``setDayGrid`` — запись самой сетки.

Зависимости: только model (пустая ячейка расписания).
"""

import re

from src.modules.functions.model import emptyCell, isLesson

# Дней в неделе
DAYS = 7
# В выходные могут быть и утренние, и вечерние уроки
MAX_LESSONS_PER_DAY = 6
# Сетка будней по умолчанию
DEFAULT_DAY = ["16:20 - 17:50", "18:00 - 19:30", "19:40 - 21:10"]

# Одно время так, как его вводят люди: "16:20", "16.20", "16,20", "16 20", "16ч20", "1620", "16"
CLOCK_PATTERN = re.compile(r"^(\d{1,2})(?:\s*[:.,чh]\s*|\s+)?(\d{2})?$")
# Слитная запись «1620»: последние две цифры — минуты
CLOCK_DIGITS = re.compile(r"^(\d{1,2})(\d{2})$")
# Между двумя временами: любое тире или «до»
RANGE_SEPARATOR = re.compile(r"\s*(?:[-–—−]+|\bдо\b)\s*", re.IGNORECASE)


def parseClock(text):
    """(часы, минуты) одного времени; None, если его не прочитать или оно вне 00:00–23:59."""
    text = text.strip().lower().rstrip(".")

    match = CLOCK_DIGITS.match(text) or CLOCK_PATTERN.match(text)

    if not match:
        return None

    hours, minutes = int(match.group(1)), int(match.group(2) or 0)

    if not (0 <= hours < 24 and 0 <= minutes < 60):
        return None

    return hours, minutes


def parseTime(text):
    """Нормализованное "ЧЧ:ММ - ЧЧ:ММ"; "" для пустой ячейки, None, если текст неверный.

    Терпимо к тому, как введено время: "16.20-17.50", "16,20 – 17,50", "1620-1750",
    "16:20 до 17:50", "16.20 17.50" и "16-18" — всё становится обычной формой.
    Конец урока должен быть позже начала, иначе None.
    """
    text = (text or "").strip()

    if not text:
        return ""

    parts = [part for part in RANGE_SEPARATOR.split(text) if part.strip()]

    # "16.20 17.50": два времени без тире
    if len(parts) == 1:
        parts = parts[0].split()

    # "16-20-17-50": часы и минуты разделены тире
    if len(parts) == 4 and all(part.strip().isdigit() for part in parts):
        parts = [f"{parts[0]}:{parts[1]}", f"{parts[2]}:{parts[3]}"]

    if len(parts) != 2:
        return None

    start, end = parseClock(parts[0]), parseClock(parts[1])

    if start is None or end is None or start >= end:
        return None

    return f"{start[0]:02d}:{start[1]:02d} - {end[0]:02d}:{end[1]:02d}"


class GridError(Exception):
    """Сетку нельзя сохранить: введённое время не читается или идёт не по порядку.

    kind    — "invalid" (время не читается) или "order" (два времени дня пересекаются или
              идут в обратном порядке);
    details — подробности для сообщения: {"text"} для "invalid", {"day", "first", "second"}
              для "order" (day — номер дня, first и second — времена в нормальной форме).
    """

    def __init__(self, kind, **details):
        super().__init__(kind, details)
        self.kind = kind
        self.details = details


def parseCell(text):
    """Время одной ячейки сетки в нормальной форме "ЧЧ:ММ - ЧЧ:ММ"; "" — ячейка пуста.

    Неверное время — ``GridError("invalid", text=…)`` с текстом ячейки без пробелов по краям.
    """
    text = (text or "").strip()
    value = parseTime(text)

    if value is None:
        raise GridError("invalid", text=text)

    return value


def parseGrid(days):
    """Сетка, введённая на «Настройках», в нормальной форме.

    ``days`` — список дней (пн…вс, лишние отбрасываются), в каждом — тексты ячеек (лишние сверх
    MAX_LESSONS_PER_DAY отбрасываются). Пустые ячейки остаются на своих местах как "" — по ним
    ``columnMapping`` понимает, какие уроки пропали. Первая же ошибка — ``GridError``: время
    не читается или времена дня идут не по порядку (``timeOrderProblem``).
    """
    grid = []

    for day, cells in enumerate(days[:DAYS]):
        times = [parseCell(text) for text in cells[:MAX_LESSONS_PER_DAY]]
        problem = timeOrderProblem(times)

        if problem:
            raise GridError("order", day=day, first=problem[0], second=problem[1])

        grid.append(times)

    return grid


def compactGrid(grid):
    """Семь дней сетки без пустых ячеек: уроки каждого дня идут подряд."""
    return [[time for time in (grid[day] if day < len(grid) else []) if time] for day in range(DAYS)]


def dayGrid(settings):
    """Сетка из 7 дней: список списков времён уроков (копия, менять её можно).

    Недостающие дни (если в ``settings["day_grid"]`` меньше семи списков) считаются выходными.
    """
    grid = settings.get("day_grid", [])

    return [list(grid[day]) if day < len(grid) and isinstance(grid[day], list) else [] for day in range(DAYS)]


def timeOrderProblem(times):
    """Первая пара времён одного дня, которые пересекаются или идут в обратном порядке; иначе None.

    Времена — нормализованные строки "ЧЧ:ММ - ЧЧ:ММ", поэтому их можно сравнивать как текст.
    """
    times = [time for time in times if time]

    for first, second in zip(times, times[1:]):
        if second.split(" - ")[0] < first.split(" - ")[1]:
            return first, second

    return None


def columnMapping(old_grid, columns):
    """{(день, старый номер урока): новый номер} при правке сетки на «Настройках» ячейка за ячейкой.

    ``columns`` — отредактированная сетка, в которой пустые ячейки оставлены на своих местах;
    урок остаётся в своём столбце (его время может измениться), а очищенная ячейка забирает
    свои уроки с собой (их нет в соответствии — они будут потеряны в ``remapWeek``).
    """
    mapping = {}

    for day in range(DAYS):
        row = columns[day] if day < len(columns) else []
        new_index = {}
        count = 0

        # Непустые столбцы получают новые номера подряд: пустые ячейки «схлопываются»
        for column, text in enumerate(row[:MAX_LESSONS_PER_DAY]):
            if text:
                new_index[column] = count
                count += 1

        for lesson in range(len(old_grid[day])):
            if lesson in new_index:
                mapping[(day, lesson)] = new_index[lesson]

    return mapping


def remapWeek(week, mapping, grid):
    """Неделя курса (из answer.json), перенесённая на новую сетку; возвращает (неделя, сколько уроков потеряно).

    ``mapping`` — результат ``columnMapping``; ``grid`` — новая сетка (задаёт число ячеек
    в каждом дне). Урок, которому нет места в новой сетке, считается потерянным.
    """
    result = [[emptyCell() for _ in grid[day]] for day in range(DAYS)]
    lost = 0

    for day, cells in enumerate(week):
        for lesson, cell in enumerate(cells):
            # Пустые ячейки переносить не нужно
            if not isLesson(cell):
                continue

            target = mapping.get((day, lesson))

            if target is None or day >= DAYS or target >= len(result[day]):
                lost += 1
                continue

            result[day][target] = cell

    return result, lost


def remapAnswer(answer, mapping, grid):
    """Расписание, перенесённое на новую сетку: ({курс: неделя}, {курс: сколько уроков потеряно}).

    ``mapping`` — результат ``columnMapping``; ``grid`` — новая сетка (пустые ячейки могут
    стоять на своих местах, см. ``parseGrid``).
    """
    compact = compactGrid(grid)
    weeks, lost = {}, {}

    for course, week in answer.items():
        weeks[course], lost[course] = remapWeek(week, mapping, compact)

    return weeks, lost


def pinSlot(key):
    """(день, урок) закреплённого урока по его ключу «день-урок» в ``settings["constants"]``."""
    day, lesson = map(int, key.split("-"))

    return day, lesson


def lostPins(settings, mapping):
    """Сколько закреплённых уроков пропадёт с новой сеткой: их ячейки нет в ``mapping``."""
    return sum(1 for fixed in settings.get("constants", {}).values() for key in fixed if pinSlot(key) not in mapping)


def keepsColumns(old_grid, mapping):
    """True, если ни один урок не сдвинулся в другой столбец (поменялось только время уроков или
    добавились ячейки в конце дня): тогда расписание, закрепления, отметки и варианты
    переписывать не нужно.
    """
    return all(mapping.get((day, lesson)) == lesson for day in range(DAYS) for lesson in range(len(old_grid[day])))


def renamedTimes(old_grid, grid):
    """{старое время: новое} — ячейки, в которых переписали время урока.

    Время считается переименованным, только если старого текста больше нет ни в одном дне
    новой сетки: правило «только вторник, 16:20» сохранит 16:20, если во вторнике такое время
    осталось, даже если в понедельнике его поменяли.
    """
    new_times = {time for row in grid for time in row if time}
    renamed = {}

    for day in range(DAYS):
        row = grid[day] if day < len(grid) else []

        for lesson, old in enumerate(old_grid[day]):
            if lesson < len(row) and row[lesson] and row[lesson] != old and old not in new_times:
                renamed[old] = row[lesson]

    return renamed


def remapSettings(settings, mapping):
    """Переносит на новые номера уроков закреплённые уроки и отметки доступности (меняет ``settings``).

    * ``constants`` — {курс: {"день-урок": предмет}}: закрепление пропавшей ячейки удаляется;
    * отметки доступности преподавателей по этапам: списки "free" («не может») и "possible"
      («может»); смысл ключей описан в model.teacherAvailability.
    """
    for course, fixed in list(settings.get("constants", {}).items()):
        settings["constants"][course] = {
            f"{day}-{mapping[(day, lesson)]}": value
            for key, value in fixed.items()
            for day, lesson in [pinSlot(key)]
            if (day, lesson) in mapping
        }

    for teacher in settings.get("teachers", {}).values():
        for marks in teacher.get("availability", {}).values():
            for kind in ("free", "possible"):
                marks[kind] = [[day, mapping[(day, lesson)]] for day, lesson in marks.get(kind, []) if (day, lesson) in mapping]

    return settings


def setDayGrid(settings, grid):
    """Записывает новую сетку в ``settings`` (на месте) и пересчитывает производные параметры."""
    # Пустые ячейки выбрасываются, так что уроки дня всегда идут подряд: 1..N
    settings["day_grid"] = [times[:MAX_LESSONS_PER_DAY] for times in compactGrid(grid)]
    applyDayGrid(settings)

    return settings


def applyDayGrid(settings):
    """Выводит из сетки ``working_days_per_week`` и ``max_lesson_count_per_day`` (меняет ``settings``).

    Число рабочих дней — номер последнего дня с уроками + 1 (выходные посреди недели
    решатель видит как дни без доступных слотов).
    """
    grid = dayGrid(settings)
    working = [day for day in range(DAYS) if grid[day]]

    settings["working_days_per_week"] = (working[-1] + 1) if working else 1
    settings["max_lesson_count_per_day"] = max([len(day) for day in grid] + [1])

    return settings


def lessonExists(settings, day, lesson):
    """Есть ли урок номер ``lesson`` в дне ``day`` по сетке."""
    grid = dayGrid(settings)

    return 0 <= day < DAYS and 0 <= lesson < len(grid[day])


def missingSlots(settings):
    """[день, урок] внутри прямоугольной недели решателя, которых нет в сетке."""
    return [
        [day, lesson]
        for day in range(settings.get("working_days_per_week", 5))
        for lesson in range(settings.get("max_lesson_count_per_day", MAX_LESSONS_PER_DAY))
        if not lessonExists(settings, day, lesson)
    ]
