"""Варианты одного этапа для вкладки «Предпросмотр»: хранение, оценка, сравнение, разбор проблем.

Кнопка «Составить варианты» запускает решатель несколько раз; каждый результат
сохраняется как вариант в ``stages/<этап>.variants/<n>.json`` (формат как у answer.json:
курс -> неделя уроков). Вкладка «Предпросмотр» сортирует варианты по оценке, а выбранный
(«принятый») вариант попадает в answer.json — «принятое расписание».

Разделы модуля
--------------
1. Файлы вариантов: ``saveVariant`` / ``loadVariants`` / ``clearVariants`` и метки рядом с ними:
   ``accepted.json`` (номер последнего принятого, ``acceptedNumber`` / ``markAccepted``) и
   ``rejected.json`` (номера отклонённых, ``rejectedNumbers`` / ``setRejected``), ``started.json``
   (курсы, которые уже шли при сборке, ``buildStarted`` / ``saveBuildStarted``). Метки лежат
   в папке вариантов, поэтому новая сборка (clearVariants) стирает их вместе с вариантами:
   отметки относятся только к тем вариантам, что видел человек.
2. Встроенные правила (``METRICS``). Каждое правило описано один раз — функцией, которая находит
   его нарушения в неделе варианта (``VariantWeek``). По этим нарушениям считаются и числа
   в таблице «Предпросмотра» (``variantMetrics``), и подписи на карточках уроков (``lessonIssues``).
   Накладки преподавателя (``teacherClashCount``) — с уроками других этапов (``teacherSlotIssues``)
   и внутри этапа (``stageTeacherClashes``: вариант с зафиксированными курсами из расписания).
3. ``missingDetails`` — почему часть уроков не разместилась (курсы stages.ownCourses, без копий);
   ``waitingCopies`` / ``waitingDetails`` — копии, которые ждут свой поток-источник.
4. Оценка и порядок: ``variantScore``, ``rankVariants`` (лучший вариант и «ничья», те, что принять нельзя, ``unacceptable``, — в конце), ``allTied``
   («все варианты одинаково хороши»), ``variantClashes`` (накладки — вопрос перед принятием),
   ``isAccepted``, ``dropUnknownTeachers``.
5. Кто ведёт курсы варианта (сборка может сменить преподавателя курса, .spec/teacher-swap):
   ``lessonTeachers`` (преподаватели уроков курса), ``teacherCourses`` (курсы, у которых преподаватель
   различается между вариантами или с расписанием — блок «Кто ведёт» на «Предпросмотре» и в Excel),
   ``teacherOverLimit`` (у кого вариант превышает лимит курсов — вопрос перед принятием).

Курсы-копии («линейка идёт вместе с Потоком N», модуль joint) в варианте потока-копии стоят
с уроками источника: сборка их не подбирает. Поэтому правила о линейке и уровнях («нежелательно
одновременно», «уровни врозь», «пары в один день») считаются с копиями — это уроки учеников потока, —
а правила о преподавателях и нехватка уроков — без них: за время и преподавателя копии отвечает
поток-источник, а занятость преподавателя её уроками приходит как уроки другого этапа
(stages.occupiedByOtherStages). Принят ли вариант, тоже решается без копий (``isAccepted``).

Страница сама варианты не оценивает: и порядок, и «лучший», и «ничья», и «все одинаковы»
приходят от сервера готовыми полями.

Зависимости: files, model, pairs, grid, courses, joint, stages, penalties, solver_input,
src.modules.translate (тексты подписей).
"""

import os
import shutil

from src.modules.functions.courses import courseCandidates, courseHours, courseLoad, teacherCourseState, teacherLimit
from src.modules.functions.files import readJson, writeJson
from src.modules.functions.grid import dayGrid
from src.modules.functions.joint import jointCopies
from src.modules.functions.model import (
    courseNames, courseSlots, courseSubject, groupsByName, hasLessons, lessonEntries, possibleSlots
)
from src.modules.functions.pairs import isLevelPair, isSubjectPair, sameDayMatters, sameLine, subjectPairs, togetherPairs
from src.modules.functions.penalties import countPenalties, penalties, penaltyLessons
from src.modules.functions.solver_input import buildStageSettings
from src.modules.functions.stages import occupiedByOtherStages, ownCourses, stageCopies, stageCourses, teacherClashes
from src.modules.translate import tr, translate

# Строки таблицы «Предпросмотра» (правила): ключ -> имя веса в weights.json (None: показывается, но в итог не входит)
METRICS = [
    ("missing", None),
    ("equalLessons", None),
    ("teacherClash", None),
    ("softSubjectPair", "softSubjectPair"),
    # Пары, которые сдают вместе («нежелательно» и «нельзя»), в один день: нагрузка на ученика,
    # но не помеха (ползунок «Пары — не в один день»)
    ("pairsSameDay", "pairsSameDay"),
    ("teacherPossibleSlot", "teacherPossibleSlot"),
    ("teacherFreeTime", "teacherFreeTime"),
    ("teacherWorkDays", "teacherWorkDays"),
    ("weekend", "weekendLesson"),
    ("levelsApart", "levelsApart"),
]

# Обязательные правила: вариант, который их нарушает, принимать не стоит
HARD_METRICS = ("missing", "equalLessons", "teacherClash")

# Порядок пунктов «Что важно в расписании» на вкладке «Запуск» (имена весов из weights.json):
# сначала про линейку и уровни, потом про преподавателей. Страница получает его через /api/meta
WEIGHT_ORDER = (
    "softSubjectPair", "pairsSameDay", "levelsApart", "teacherPossibleSlot", "teacherFreeTime", "teacherWorkDays",
    "weekendLesson",
)

# Индексы субботы и воскресенья (понедельник = 0)
WEEKEND = (5, 6)

# Короткие названия линеек для подписей на карточках («Химия (ЕГЭ продв.)»). Это единственный
# список: страница получает его через /api/meta для своих меток на карточках уроков
SHORT_LINES = {
    "ЕГЭ продвинутый": "ЕГЭ продв.", "ЕГЭ основной": "ЕГЭ осн.",
    "10 класс": "10 кл.", "8 класс": "8 кл.",
    "Семинар ЕГЭ продвинутый": "Сем. ЕГЭ продв.", "Семинар ОГЭ": "Сем. ОГЭ",
}


def shortLine(line):
    """Короткое название линейки для подписи («ЕГЭ продв.»); неизвестная — как есть."""
    return SHORT_LINES.get(line, line)


# ---------------------------------------------------------------- 1. файлы вариантов и метки

def stagesDir(project_path):
    """Папка построенных вариантов всех этапов: ``<проект>/stages``."""
    return os.path.join(project_path, "stages")


def variantsDir(project_path, stage):
    """Папка вариантов этапа: ``<проект>/stages/<этап>.variants``."""
    return os.path.join(stagesDir(project_path), f"{stage}.variants")


def clearVariants(project_path, stage):
    """Удаляет все варианты этапа (перед новым запуском решателя). Ошибки удаления игнорируются."""
    shutil.rmtree(variantsDir(project_path, stage), ignore_errors=True)


def clearStaleVariants(project_path, stages):
    """Удаляет варианты этапов, которых больше нет; ``stages`` — ключи нынешних этапов.

    Этап пропадает, когда удалены все его курсы (последняя линейка блока, последний курс
    потока). Его старые варианты с удалёнными курсами иначе снова показались бы на
    «Предпросмотре» и в Excel, когда в этапе опять появятся курсы.
    """
    folder = stagesDir(project_path)

    if not os.path.isdir(folder):
        return

    for name in os.listdir(folder):
        stage, ext = os.path.splitext(name)

        if ext == ".variants" and stage not in stages:
            clearVariants(project_path, stage)


def saveVariant(project_path, stage, number, answer):
    """Сохраняет вариант номер ``number`` этапа в ``<n>.json`` (компактно, без отступов)."""
    folder = variantsDir(project_path, stage)
    os.makedirs(folder, exist_ok=True)

    writeJson(os.path.join(folder, f"{number}.json"), answer, indent=None)


def loadVariants(project_path, stage):
    """[(номер, расписание варианта)], по возрастанию номера.

    Читаются только файлы вида ``<число>.json``; нечитаемые файлы молча пропускаются.
    """
    folder = variantsDir(project_path, stage)
    result = []

    if not os.path.isdir(folder):
        return result

    for name in os.listdir(folder):
        stem, ext = os.path.splitext(name)
        variant = readJson(os.path.join(folder, name), None) if ext == ".json" and stem.isdigit() else None

        if variant is not None:
            result.append((int(stem), variant))

    return sorted(result, key=lambda item: item[0])


def acceptedNumber(project_path, stage):
    """Номер последнего принятого варианта этапа (accepted.json); None — ни один не принимали."""
    marker = readJson(os.path.join(variantsDir(project_path, stage), "accepted.json"), {})

    return marker.get("number") if isinstance(marker, dict) else None


def markAccepted(project_path, stage, number):
    """Запоминает, что вариант номер ``number`` этапа принят (accepted.json).

    Нужно, чтобы из нескольких одинаковых вариантов «принятым» показывался только этот.
    """
    writeJson(os.path.join(variantsDir(project_path, stage), "accepted.json"), {"number": number})


def rejectedNumbers(project_path, stage):
    """Номера отклонённых вариантов этапа (rejected.json); испорченный файл — пустое множество."""
    data = readJson(os.path.join(variantsDir(project_path, stage), "rejected.json"), {})

    return {number for number in data.get("numbers", []) if isinstance(number, int)} if isinstance(data, dict) else set()


def setRejected(project_path, stage, numbers):
    """Записывает номера отклонённых вариантов этапа (rejected.json) — целиком, по возрастанию."""
    writeJson(os.path.join(variantsDir(project_path, stage), "rejected.json"), {"numbers": sorted(numbers)})


def saveBuildStarted(project_path, stage, courses, answer=None):
    """Запоминает курсы этапа, которые уже шли, когда составляли его варианты (started.json, по алфавиту).

    Пишет сборка вместе с первым вариантом (build._storeVariant). Уроки таких курсов сборка закрепляла,
    поэтому её вариант для них не «собран до начала» (stages.staleStarted). Если решатель какое-то
    закрепление всё же не поставил, такой вариант находит stages.movedStarted — с причиной.
    ``answer`` — расписание на начало сборки: с ним запоминаются и уроки этих курсов (startedLessons),
    чтобы buildStarted узнал курсы, чьи уроки с тех пор поменялись.
    """
    folder = variantsDir(project_path, stage)
    os.makedirs(folder, exist_ok=True)
    data = {"courses": sorted(courses)}

    if answer is not None:
        data["lessons"] = {course: startedLessons(answer, course) for course in sorted(courses)}

    writeJson(os.path.join(folder, "started.json"), data)


def buildStarted(project_path, stage, answer=None):
    """Курсы, которые шли при сборке вариантов этапа (started.json, ``saveBuildStarted``), — множество.

    None — неизвестно: варианты составлены до того, как программа стала это запоминать, или файл испорчен.
    С нынешним расписанием ``answer`` курсы, чьи уроки с начала сборки поменялись (приняли другой
    вариант, вернули версию), не в счёт: вариант собран не по нынешнему расписанию, для них он устарел
    (stages.staleStarted), а не «программа не смогла оставить урок» (stages.movedStarted). Если уроков
    в файле нет (метка старой программы), сверки нет.
    """
    data = readJson(os.path.join(variantsDir(project_path, stage), "started.json"), None)
    courses = data.get("courses") if isinstance(data, dict) else None

    if not isinstance(courses, list):
        return None

    # Не строки (файл правили руками) пропускаются
    result = {name for name in courses if isinstance(name, str)}
    lessons = data.get("lessons")

    if answer is not None and isinstance(lessons, dict):
        result = {name for name in result if lessons.get(name) == startedLessons(answer, name)}

    return result


def startedLessons(answer, course):
    """Уроки курса в расписании для started.json: [[день, урок, предмет, [преподаватели]]] по порядку мест."""
    return [[day, lesson, cell.get("subject"), sorted(cell.get("teachers", []))] for day, lesson, cell in lessonEntries(answer, course)]


# ---------------------------------------------------------------- 2. встроенные правила

class VariantWeek:
    """Неделя варианта этапа, разложенная для проверки правил.

    * ``courses`` — курсы этапа по алфавиту; ``groups`` — все курсы проекта по названию;
    * ``entries`` — {курс: [(день, урок, ячейка)]}; ``slots`` — {курс: {(день, урок)}};
    * ``by_slot`` — {(день, урок): [(курс, предмет)]} в порядке ``courses``;
    * ``busy_slots`` — {преподаватель: {(день, урок): курс}}: уроки других этапов в те же даты
      и уроки копий этапа;
    * ``copies`` — копии этапа {копия: источник} (stages.stageCopies): они в ``courses`` и
      ``entries``, но не в правилах о преподавателях и нехватке уроков;
    * ``variant`` — сама неделя варианта {курс: неделя} (для ``stageTeacherClashes``).
    """

    def __init__(self, settings, stage, variant, answer=None):
        self.settings = settings
        self.stage = stage
        self.variant = variant
        self.courses = sorted(stageCourses(settings, stage))
        self.copies = stageCopies(settings, stage)
        self.groups = groupsByName(settings)
        self.entries = {course: list(lessonEntries(variant, course)) for course in self.courses}
        self.slots = {course: {(day, lesson) for day, lesson, _ in entries} for course, entries in self.entries.items()}
        self.by_slot = {}

        for course in self.courses:
            for day, lesson, entry in self.entries[course]:
                self.by_slot.setdefault((day, lesson), []).append((course, entry.get("subject")))

        self.busy_slots = occupiedByOtherStages(settings, answer or {}, stage)[0]

    def group(self, course):
        """Курс (элемент custom_groups) по названию; неизвестный — пустой словарь."""
        return self.groups.get(course, {})

    def lessons(self, copies=True):
        """Все уроки этапа по одному: (курс, день, урок, ячейка).

        ``copies=False`` — без уроков копий: для правил о преподавателях, у которых урок копии —
        это урок источника, уже учтённый в ``busy_slots``.
        """
        for course in self.courses:
            if copies or course not in self.copies:
                for day, lesson, entry in self.entries[course]:
                    yield course, day, lesson, entry


def softPairClashes(week):
    """Правило «нежелательно одновременно»: (слот, (курс, предмет), (курс, предмет)) — два курса
    одной линейки потока в одно время, чьи предметы отмечены «нежелательно». Тот же предмет на
    другом уровне ЕГЭ в одно время — это хорошо, а не пересечение; совпадение пар «можно» не мешает.
    """
    soft = subjectPairs(week.settings, "soft_subject_pairs")

    for slot, items in week.by_slot.items():
        for i, first in enumerate(items):
            for second in items[i + 1:]:
                a, b = week.group(first[0]), week.group(second[0])

                if sameLine(a, b) and not isLevelPair(a, b) and isSubjectPair(soft, first[1], second[1]):
                    yield slot, first, second


def sameDayClashes(week):
    """Правило «Пары — не в один день»: (курс, курс, [общие дни]) — курсы, которые сдают вместе
    (pairs.sameDayMatters), с уроками в одни и те же дни. По одной записи на пару курсов.
    """
    together = togetherPairs(week.settings)
    placed = [course for course in week.courses if week.entries[course]]

    for i, first in enumerate(placed):
        for second in placed[i + 1:]:
            if sameDayMatters(week.group(first), week.group(second), together):
                days = sorted({day for day, _ in week.slots[first]} & {day for day, _ in week.slots[second]})

                if days:
                    yield first, second, days


def levelPairs(week):
    """Правило «уровни — в одно время»: пары уровней одного предмета (курс, курс) среди курсов этапа."""
    for i, first in enumerate(week.courses):
        for second in week.courses[i + 1:]:
            if isLevelPair(week.group(first), week.group(second)):
                yield first, second


def levelMismatch(week, first, second):
    """Сколько уроков пары уровней стоит не в одно время: min(уроков) − общих слотов (как в решателе)."""
    own, other = week.slots[first], week.slots[second]

    return max(0, min(len(own), len(other)) - len(own & other))


def courseDayCounts(week):
    """Правило «один урок курса в день»: {(курс, день): уроков курса в этот день}."""
    counts = {}

    for course, day, _, _ in week.lessons():
        counts[(course, day)] = counts.get((course, day), 0) + 1

    return counts


def teacherSlotIssues(week):
    """Правила о времени преподавателя: (курс, день, урок, преподаватель, вид), где вид —
    "busy" (в это время у него урок другого этапа — накладка) или "possible" (урок во время
    «может», а не «удобно» — мягкий штраф).
    Уроки копий не проверяются: их время выбрано в потоке-источнике. Урок другого курса в часы
    копии — накладка у этого курса (копия есть в ``busy_slots``).
    """
    for course, day, lesson, entry in week.lessons(copies=False):
        for teacher in entry.get("teachers", []):
            if (day, lesson) in week.busy_slots.get(teacher, {}):
                yield course, day, lesson, teacher, "busy"

            if [day, lesson] in possibleSlots(week.settings, teacher, week.stage):
                yield course, day, lesson, teacher, "possible"


def stageTeacherClashes(week):
    """Накладки внутри этапа: один преподаватель в одно время на уроках двух своих курсов этапа
    (не копий), которые идут хотя бы день одновременно — [(преподаватель, день, урок, [курсы])],
    как stages.teacherClashes.

    Решатель такого не ставит. Но вариант показывается и принимается с зафиксированными курсами
    из принятого расписания (stages.lockedFromAnswer): если курс начался уже после сборки, а вариант
    сменил ему преподавателя, освободившееся время вариант мог отдать этому же преподавателю на
    другом курсе этапа — после подмены у преподавателя два урока сразу. Копии не проверяются: их
    уроки — уроки источника, занятость ими уже в ``busy_slots``.
    """
    own = {course: week.variant[course] for course in week.courses if course not in week.copies and course in week.variant}

    return teacherClashes(week.settings, own)


def teacherClashCount(week):
    """Сколько уроков варианта стоят у преподавателя одновременно с другим его уроком — метрика
    "teacherClash" и вопрос перед принятием (``variantClashes``): уроки других этапов в то же время
    (``teacherSlotIssues``, "busy") плюс накладки внутри этапа (``stageTeacherClashes``: в слоте
    с N курсами лишних уроков N − 1).
    """
    busy = sum(1 for *_, kind in teacherSlotIssues(week) if kind == "busy")

    return busy + sum(len(courses) - 1 for *_, courses in stageTeacherClashes(week))


def weekendLessons(week):
    """Правило «без уроков в выходные»: (курс, день, урок) уроков в субботу и воскресенье."""
    return [(course, day, lesson) for course, day, lesson, _ in week.lessons() if day in WEEKEND]


def teacherDays(week):
    """{(преподаватель, день): [номера его уроков]} — для «окон» и рабочих дней преподавателей.

    Без уроков копий: их дни уже рабочие из-за уроков источника (копии этапа — в ``busy_slots``).
    """
    result = {}

    for _, day, lesson, entry in week.lessons(copies=False):
        for teacher in entry.get("teachers", []):
            result.setdefault((teacher, day), []).append(lesson)

    return result


def variantMetrics(settings, stage, variant, weights, answer=None):
    """Количество каждой проблемы в варианте и взвешенная сумма по мягким правилам.

    ``weights`` — содержимое weights.json; ``answer`` — принятое расписание: дни, когда
    преподаватель уже ведёт уроки других этапов, не считаются для него лишними рабочими днями,
    а его уроки других этапов в то же время — накладки.

    Возвращает словарь: по ключу на каждую метрику из ``METRICS``, плюс
    ``"custom"`` ({id своего правила: число нарушений}) и ``"total"`` — итоговый штраф
    (только мягкие правила и свои правила; жёсткие нарушения показываются отдельно).
    """
    week = VariantWeek(settings, stage, variant, answer)
    teacher_issues = list(teacherSlotIssues(week))
    by_teacher_day = teacherDays(week)
    busy_days = {teacher: {day for day, _ in slots} for teacher, slots in week.busy_slots.items()}
    # «Окна» — свободные уроки между уроками преподавателя за день; решатель возводит каждое окно в квадрат
    gaps = [max(lessons) - min(lessons) + 1 - len(set(lessons)) for lessons in by_teacher_day.values()]

    counts = {
        # Без копий: их уроки ставит поток-источник, а ждущая копия — не ошибка этого этапа
        "missing": sum(max(0, courseHours(settings, course) - len(week.entries[course])) for course in week.courses if course not in week.copies),
        # Два урока курса в один день: по одному нарушению на каждую пару уроков
        "equalLessons": sum(count * (count - 1) // 2 for count in courseDayCounts(week).values()),
        # Накладки с уроками других этапов и внутри этапа (teacherClashCount)
        "teacherClash": teacherClashCount(week),
        "softSubjectPair": sum(1 for _ in softPairClashes(week)),
        "pairsSameDay": sum(len(days) for _, _, days in sameDayClashes(week)),
        "teacherPossibleSlot": sum(1 for *_, kind in teacher_issues if kind == "possible"),
        "teacherFreeTime": sum(gaps),
        # Рабочие дни, которые добавляет этот этап: дни, когда преподаватель уже ведёт уроки других этапов, не считаются
        "teacherWorkDays": sum(1 for teacher, day in by_teacher_day if day not in busy_days.get(teacher, set())),
        "weekend": len(weekendLessons(week)),
        "levelsApart": sum(levelMismatch(week, first, second) for first, second in levelPairs(week)),
    }
    counts["custom"] = countPenalties(settings, stage, variant)
    counts["total"] = variantTotal(settings, weights, counts, sum(gap * gap for gap in gaps))

    return counts


def variantTotal(settings, weights, counts, squared_gaps):
    """Итоговый штраф: цена мягких правил (у «окон» — сумма квадратов) плюс свои правила по своей цене."""
    total = 0

    for key, weight in METRICS:
        if weight is not None:
            total += (squared_gaps if key == "teacherFreeTime" else counts[key]) * int(weights.get(weight, 0) or 0)

    for penalty in penalties(settings):
        total += counts["custom"].get(penalty["id"], 0) * int(penalty.get("weight", 0) or 0)

    return total


def lessonIssues(settings, stage, variant, answer=None):
    """Что не так с каждым уроком варианта — для подписей на карточках в «Предпросмотре».

    Возвращает {курс: {"день-урок": [подпись, …]}}, только уроки, у которых что-то есть.
    Подпись — строка (проблема, красным) или {"text", "level": "warn"} (не критично, жёлтым).
    Нарушения находят те же функции правил, что и для ``variantMetrics``, но здесь видно,
    какой именно урок их нарушил. Тексты подписей — ключи web.issue.* в ru.hjson
    («Одновременно с: …», «Урок в выходной», «Против правила «…»» и т. д.).
    «Окна» и лишние рабочие дни преподавателей сюда не входят: они про весь день
    преподавателя, а не про один урок. У копий этапа подписей нет: их время задаёт
    поток-источник, а помеха между копией и уроком потока подписана у урока потока.
    """
    week = VariantWeek(settings, stage, variant, answer)
    result = {}

    def add(course, day, lesson, text, level=None):
        """Подпись к уроку; level="warn" — не критично (жёлтым), иначе — проблема (красным)."""
        items = result.setdefault(course, {}).setdefault(f"{day}-{lesson}", [])
        item = {"text": text, "level": level} if level else text

        if item not in items:
            items.append(item)

    for (course, day, lesson), labels in softPairLabels(week).items():
        add(course, day, lesson, tr("web.issue.soft_pair", subjects=", ".join(labels)))

    for (course, day, lesson), subjects in sameDayLabels(week).items():
        # «Английский язык (ЕГЭ осн., ЕГЭ продв.), Информатика (ЕГЭ осн.)»
        labels = [f"{name} ({', '.join(levels)})" if levels else name for name, levels in subjects.items()]
        add(course, day, lesson, tr("web.issue.pair_same_day", subjects=", ".join(labels)), "warn")

    days = courseDayCounts(week)

    for course, day, lesson, _ in week.lessons():
        if days[(course, day)] > 1:
            add(course, day, lesson, translate("web.issue.same_day"))

    for course, day, lesson, teacher, kind in teacherSlotIssues(week):
        add(course, day, lesson, tr("web.issue.teacher_busy", name=teacher) if kind == "busy" else translate("web.issue.teacher_possible"))

    # Накладка внутри этапа — у каждого её урока, с названиями других курсов в это время
    for teacher, day, lesson, courses in stageTeacherClashes(week):
        for course in courses:
            add(course, day, lesson, tr("web.issue.teacher_twice", name=teacher, courses=", ".join(other for other in courses if other != course)))

    for course, day, lesson in weekendLessons(week):
        add(course, day, lesson, translate("web.issue.weekend"))

    for course, day, lesson, key, level in levelLabels(week):
        add(course, day, lesson, tr(key, level=level))

    for (course, day, lesson), names in penaltyLessons(settings, stage, variant).items():
        for name in names:
            add(course, day, lesson, tr("web.issue.wish", name=name or ""))

    # Урок копии в этом потоке не сдвинуть — его время задаёт поток-источник. Подпись у копии
    # звала бы менять то, что здесь не меняется; помеха с уроком потока уже подписана у того урока
    return {course: items for course, items in result.items() if course not in week.copies}


def softPairLabels(week):
    """{(курс, день, урок): [«Химия (ЕГЭ продв.)», …]} — с какими предметами урок стоит «нежелательно»
    одновременно. Предмет всегда с линейкой курса коротко: у одной линейки бывает несколько уровней.
    """
    labels = {}

    for (day, lesson), first, second in softPairClashes(week):
        for (own, _), (other, subject) in ((first, second), (second, first)):
            program = week.group(other).get("program")
            labels.setdefault((own, day, lesson), []).append(f"{subject} ({shortLine(program)})" if program else subject)

    return labels


def sameDayLabels(week):
    """{(курс, день, урок): {предмет: [линейки коротко]}} — предметы, которые сдают вместе, в тот же день,
    но в другой час: ученик успеет на оба, но день тяжёлый. Один предмет на двух уровнях ЕГЭ — один раз.
    Если такие курсы стоят ровно в одно время, об этом говорит подпись «нежелательно одновременно».
    """
    labels = {}

    for first, second, days in sameDayClashes(week):
        for own, other in ((first, second), (second, first)):
            program = week.group(other).get("program")

            for day, lesson, _ in week.entries[own]:
                if day not in days or (day, lesson) in week.slots[other]:
                    continue

                for other_day, _, entry in week.entries[other]:
                    if other_day != day:
                        continue

                    levels = labels.setdefault((own, day, lesson), {}).setdefault(entry.get("subject"), [])

                    if program and shortLine(program) not in levels:
                        levels.append(shortLine(program))

    return labels


def levelLabels(week):
    """(курс, день, урок, ключ текста, уровень) — урок, у которого тот же предмет другого уровня
    идёт в другое время. Помечаются уроки меньшего курса пары (у большего лишние уроки без пары
    неизбежны), при равных — обоих. Меньший — копия: её урок в этом потоке не сдвинуть (время
    задаёт поток-источник), поэтому помечается и больший курс; у самой копии подписи убирает
    ``lessonIssues``. Если оба уровня ведёт один преподаватель, в одно время их не поставить —
    так и пишется (web.issue.levels_same_teacher).
    """
    for first, second in levelPairs(week):
        if not levelMismatch(week, first, second):
            continue

        for own, other in ((first, second), (second, first)):
            if len(week.slots[own]) > len(week.slots[other]) and other not in week.copies:
                continue

            theirs = {name for _, _, entry in week.entries[other] for name in entry.get("teachers", [])}

            for day, lesson, entry in week.entries[own]:
                if (day, lesson) not in week.slots[other]:
                    key = "web.issue.levels_same_teacher" if set(entry.get("teachers", [])) & theirs else "web.issue.levels_apart"
                    yield own, day, lesson, key, shortLine(week.group(other).get("program"))


# ---------------------------------------------------------------- 3. почему уроки не разместились

def missingDetails(settings, answer, stage, variant):
    """Почему уроки варианта не размещены: по одной записи на каждый курс/предмет, которому не хватает уроков.

    {"course", "subject", "expected", "placed", "teachers", "reason"}, где reason:
      "no_teacher" — никто не может вести этот курс;
      "limit"      — у каждого, кто может его вести, уже максимум курсов;
      "no_time"    — у преподавателей не осталось ни одного часа: «не может», уроки других
                     этапов, их собственные уроки; дни, где у курса уже есть урок, не в счёт;
      "rules"      — время было, но его забрали другие правила (пары «нельзя», семинары и
                     другие программы, которые не пересекаются, общие уроки присоединённой линейки).
    teachers: [(имя, свободных часов)] для "no_time" / "rules", просто имена для "limit".
    """
    # Вход решателя строится заново по текущим настройкам и принятому расписанию, без режима
    # «оставить принятое» (keep). Решатель мог видеть другой вход: при сборке был выбран keep
    # или настройки и расписание с тех пор изменились. Поэтому причины здесь приблизительные
    stage_settings = buildStageSettings(settings, answer, stage)
    taken = teacherTaken(settings, stage, variant)
    result = []

    for course in ownCourses(settings, stage):
        for subject, hours in courseLoad(settings, course).items():
            placed = courseSlots(variant, course, subject)

            if len(placed) < hours:
                item = {"course": course, "subject": subject, "expected": hours, "placed": len(placed)}
                item["teachers"], item["reason"] = missingReason(settings, stage_settings, taken, course, subject, placed)
                result.append(item)

    return result


def waitingCopies(settings, answer, stage):
    """Копии этапа, которые ждут свой поток-источник: {копия: источник}, у источника нет уроков в ``answer``."""
    return {name: source for name, source in stageCopies(settings, stage).items() if not hasLessons(answer, source)}


def waitingDetails(settings, answer, stage):
    """Записи «Что не получилось поставить» для копий, ждущих поток-источник (``waitingCopies``).

    Тот же вид, что у ``missingDetails`` (страница показывает «не поставлено N из N»), с причиной
    "joint_waiting" и номером потока-источника ``number``: уроки встанут, когда у курса-источника
    появятся уроки в расписании.
    """
    groups = groupsByName(settings)
    result = []

    for name in waitingCopies(settings, answer, stage):
        hours = courseHours(settings, name)
        result.append({
            "course": name, "subject": courseSubject(groups[name]), "expected": hours, "placed": 0, "teachers": [],
            "reason": "joint_waiting", "number": groups[name]["together_with"],
        })

    return result


def teacherTaken(settings, stage, variant):
    """Что уже занято у преподавателей в варианте: ({преподаватель: {(день, урок)}}, {преподаватель: {курсы}}).

    Без копий: их уроки и курс уже учтены входом решателя как чужие (занятость и лимит курсов).
    """
    slots, courses = {}, {}

    for course in ownCourses(settings, stage):
        for day, lesson, entry in lessonEntries(variant, course):
            for teacher in entry.get("teachers", []):
                slots.setdefault(teacher, set()).add((day, lesson))
                courses.setdefault(teacher, set()).add(course)

    return slots, courses


def missingReason(settings, stage_settings, taken, course, subject, placed):
    """(преподаватели, причина) нехватки уроков курса по предмету (см. ``missingDetails``)."""
    teacher_slots, teacher_courses = taken
    teachers = stage_settings.get("teachers", {})

    # Кто вообще может вести этот предмет в этом курсе
    candidates = courseCandidates(teachers, course, subject)

    if not candidates:
        return [], "no_teacher"

    # Преподаватели, которые ещё могут взять один курс (или уже ведут этот)
    existing = stage_settings.get("existing_courses_by_teacher", {})
    limit = teacherLimit(settings)
    open_candidates = [
        name for name in candidates
        if course in teacher_courses.get(name, set()) or existing.get(name, 0) + len(teacher_courses.get(name, set())) < limit
    ]

    if not open_candidates:
        return candidates, "limit"

    # Свободные часы каждого: не «не может», не занят своими уроками и в этот день у курса ещё нет
    # урока. Слоты, запрещённые курсу правилами (blocked_slots: пары «нельзя», программы, которые не
    # пересекаются, общие уроки), здесь свободны: если только они и остались, причина — «rules»
    all_slots = [(day, lesson) for day, times in enumerate(dayGrid(settings)) for lesson in range(len(times))]
    busy_days = {day for day, _ in placed}
    free = []

    for name in open_candidates:
        busy = {tuple(slot) for slot in teachers[name].get("free", [])} | teacher_slots.get(name, set())
        free.append((name, sum(1 for slot in all_slots if slot not in busy and slot[0] not in busy_days)))

    # Есть свободные часы, а урок всё равно не встал — значит, мешают другие правила
    return free, "rules" if any(count for _, count in free) else "no_time"


# ---------------------------------------------------------------- 4. оценка и порядок вариантов

def variantScore(metrics):
    """Оценка варианта для сравнения (меньше — лучше): сначала нарушения обязательных правил
    (HARD_METRICS), потом итоговый штраф за неудобства.
    """
    return sum(metrics.get(key, 0) for key in HARD_METRICS), metrics["total"]


def unacceptable(item):
    """Вариант ``item`` (словарь ranking.rankedVariants) принять нельзя: он собран до начала курсов,
    которые уже идут ("staleStarted", stages.staleStarted), или сдвигает урок курса, который шёл уже при
    сборке ("movedStarted", stages.movedStarted). Принятие (preview.accept) откажет и с force.
    """
    return bool(item.get("staleStarted") or item.get("movedStarted"))


def rankVariants(items):
    """Сортирует варианты от лучшего к худшему и отмечает лучший и «ничью» (меняет ``items``).

    ``items`` — словари с "number", "metrics", "rejected" и (не обязательно) "staleStarted" и "movedStarted".
    Порядок — сначала варианты, которые можно принять, потом те, что принять нельзя (``unacceptable``);
    внутри — по ``variantScore``,
    при равной оценке — по номеру. Каждому варианту добавляются поля:
    * "best" — это лучший вариант: первый не отклонённый из тех, что можно принять;
    * "tied" — у варианта та же оценка, что у лучшего, и таких не отклонённых и принимаемых
      вариантов несколько: тогда «лучшего» нет (страница и лист сравнения в Excel пишут «одинаково»).
    Возвращает ``items``.
    """
    items.sort(key=lambda item: (unacceptable(item), variantScore(item["metrics"]), item["number"]))
    candidates = [item for item in items if not item.get("rejected") and not unacceptable(item)]
    best = candidates[0] if candidates else None
    tied = [item for item in candidates if variantScore(item["metrics"]) == variantScore(best["metrics"])]

    for item in items:
        item["best"] = item is best
        item["tied"] = len(tied) > 1 and any(item is other for other in tied)

    return items


def allTied(items):
    """Все не отклонённые варианты (а их больше одного) одинаково хороши: «можно принять любой».

    ``items`` — варианты после ``rankVariants``. Сравнивается полная оценка ``variantScore``
    (поле "tied"), а не только итоговый штраф: вариант, которому не хватает уроков, никогда
    не «такой же», как полный. У варианта, который принять нельзя (``unacceptable``), "tied" нет,
    поэтому при нём «можно принять любой» не пишется.
    """
    shown = [item for item in items if not item.get("rejected")]

    return len(shown) > 1 and all(item["tied"] for item in shown)


def variantClashes(settings, stage, variant, answer=None):
    """Сколько накладок у преподавателей в варианте: уроков в то же время, что их уроки других
    этапов или другого своего курса этапа (``teacherClashCount``; то же число, что метрика
    "teacherClash" в ``variantMetrics``, но без остальных правил).
    """
    return teacherClashCount(VariantWeek(settings, stage, variant, answer))


def isAccepted(answer, variant, courses, settings=None):
    """Стоит ли этот вариант сейчас в принятом расписании ``answer``.

    С ``settings`` курсы-копии не сравниваются: их уроки ставит источник, а не сборка. Единственный
    вызов (ranking.rankedVariants) уже подтянул копии варианта к нынешним урокам источников
    (joint.followSources), так что фильтр — страховка: на случай несинхронного ``answer``, вызова
    с вариантом, каким он был при сборке (тест AC-25), и чтобы одни копии не делали этап «принятым»
    (условие any ниже).
    """
    if settings is not None:
        copies = jointCopies(settings)
        courses = [course for course in courses if course not in copies]

    # Вариант принят, когда каждый курс этапа в расписании совпадает с вариантом
    # (и хотя бы один курс этапа в расписании вообще есть)
    return all(answer.get(course) == variant.get(course) for course in courses) and any(course in answer for course in courses)


def dropUnknownTeachers(settings, variant):
    """Убирает из уроков варианта преподавателей, которых уже нет в проекте (меняет ``variant``).

    Нужно при принятии варианта: преподаватель, удалённый после сборки, не должен вернуться
    в расписание вместе с вариантом. Возвращает ``variant``.
    """
    known = set(settings.get("teachers", {}))

    for course in variant:
        for _, _, entry in lessonEntries(variant, course):
            entry["teachers"] = [teacher for teacher in entry.get("teachers", []) if teacher in known]

    return variant


# ---------------------------------------------------------------- 5. кто ведёт курсы варианта

def lessonTeachers(answer, course):
    """Кто ведёт уроки курса ``course`` в расписании или варианте ``answer``: {предмет: [преподаватели]}
    в порядке первого появления, без повторов. Курса нет — пустой словарь.
    """
    result = {}

    for _, _, entry in lessonEntries(answer, course):
        names = result.setdefault(entry.get("subject"), [])
        names += [teacher for teacher in entry.get("teachers", []) if teacher not in names]

    return result


def teacherCourses(settings, items):
    """Курсы, у которых преподаватель различается между не отклонёнными вариантами или с принятым
    расписанием, — строки блока «Кто ведёт» на «Предпросмотре» и в Excel. Порядок — как в проекте.

    ``items`` — варианты, как их отдаёт сервер (ranking.rankedVariants): у каждого ``teachers``
    ({курс: [имена]}) и ``teacherChanges`` (курсы, которым вариант сменит преподавателя в расписании).
    Курс, которого нет в каком-то варианте, по нему не сравнивается: это нехватка уроков, а не
    другой преподаватель.
    """
    shown = [item for item in items if not item.get("rejected")]
    changed = {change["course"] for item in shown for change in item.get("teacherChanges", [])}
    found = {}

    for item in shown:
        for course, names in item.get("teachers", {}).items():
            found.setdefault(course, set()).add(frozenset(names))

    return [name for name in courseNames(settings) if name in changed or len(found.get(name, ())) > 1]


def teacherOverLimit(settings, answer, stage, variant):
    """Преподаватели, у которых с вариантом ``variant`` этапа ``stage`` курсов больше лимита:
    [(преподаватель, курсов, лимит)] по имени.

    Курсы — это курсы других этапов (stages.occupiedByOtherStages: копия считается своим источником)
    и курсы варианта без копий (их уроки ставит поток-источник). Сборка лимит соблюдает, поэтому
    превышение значит, что файл варианта правили или проект изменился после сборки.
    Превышение из-за курсов, которые сборке не выбирать, не считается: курсов «ведёт» и курсов, которые
    этот преподаватель ведёт и в принятом расписании (идущие, «оставить принятое» — решатель получает
    их как «ведёт»). Такому преподавателю сборка курсов не добавляет, но и не отнимает.
    ``variant`` — каким его сохранит принятие (stages.lockedFromAnswer: зафиксированные курсы этапа —
    из расписания; так его передаёт preview.accept). Иначе курс, который стал зафиксированным после
    сборки, считался бы у преподавателя из файла варианта, хотя принятие его не сменит.
    """
    limit = teacherLimit(settings)
    existing = occupiedByOtherStages(settings, answer, stage)[2]
    courses, fixed = {}, {}

    for course in ownCourses(settings, stage):
        now = lessonTeachers(answer, course)

        for subject, names in lessonTeachers(variant, course).items():
            for teacher in names:
                courses.setdefault(teacher, set()).add(course)

                if teacher in now.get(subject, []) or teacherCourseState(settings, teacher, subject, course) == "assigned":
                    fixed.setdefault(teacher, set()).add(course)

    result = []

    for teacher in sorted(courses):
        before = existing.get(teacher, set())
        count = len(before | courses[teacher])

        if count > max(limit, len(before | fixed.get(teacher, set()))):
            result.append((teacher, count, limit))

    return result
