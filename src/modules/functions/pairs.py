"""Пары предметов и пары курсов: таблица «в одно время можно / нежелательно / нельзя» и
правила, которые из неё следуют для курсов одной линейки.

Таблица пар (вкладка «Настройки»)
---------------------------------
* ``settings["joint_subject_pairs"]`` — пары предметов «нельзя одновременно» (жёсткое правило);
* ``settings["soft_subject_pairs"]`` — «нежелательно одновременно» (мягкое правило, штраф).
Пары действуют только внутри одной линейки одного потока (``sameLine``): у этих курсов одни
и те же ученики. Пара, которой нет ни в одном списке, — «можно».

* ``settings["non_overlapping_programs"]`` — пары программ («Семинары» и «ЕГЭ продвинутый»),
  уроки одного предмета в которых не должны совпадать по времени (``programPairs``).

Пары курсов
-----------
* ``isLevelPair`` — один предмет одной линейки на двух уровнях ЕГЭ: их уроки лучше ставить
  в одно время (правило «уровни — в одно время»);
* ``takenTogether`` / ``sameDayMatters`` — предметы, которые ученики сдают вместе: их уроки
  в один день — тяжёлый день (правило «Пары — не в один день»).

Зависимости: только model.
"""

from src.modules.functions.model import courseSubject

# Состояния пары предметов в таблице на вкладке «Настройки»: "allowed" — правила нет,
# "soft" — «нежелательно одновременно» (штраф), "hard" — «нельзя одновременно» (запрет).
# PAIR_KEYS — в каком ключе settings хранится список пар каждого состояния (у "allowed" списка нет)
PAIR_ALLOWED = "allowed"
PAIR_SOFT = "soft"
PAIR_HARD = "hard"
PAIR_KEYS = {PAIR_HARD: "joint_subject_pairs", PAIR_SOFT: "soft_subject_pairs"}

# Предметы, которые сдают почти все ученики (русский и одна из математик). Их уроки в один день
# с другими предметами неизбежны, поэтому правило «Пары — не в один день» их не считает; они же
# по умолчанию «нежелательно одновременно» с каждым предметом (school_defaults.defaultSoftPairs)
COMMON_SUBJECTS = ("Русский язык", "Математика", "Математика база")


# ---------------------------------------------------------------- таблица пар предметов

def subjectPairState(settings, first, second):
    """Состояние пары предметов ``first`` + ``second``: "hard", "soft" или "allowed".

    Порядок предметов в паре не важен.
    """
    for state, key in PAIR_KEYS.items():
        for pair in settings.get(key, []):
            if sorted(pair) == sorted([first, second]):
                return state

    return PAIR_ALLOWED


def setSubjectPairState(settings, first, second, state):
    """Задаёт состояние пары предметов (``state``: "allowed" / "soft" / "hard").

    Сначала пара удаляется из обоих списков, затем (если состояние не "allowed")
    добавляется в нужный. Пара предмета с самим собой игнорируется.
    Меняет ``settings`` на месте и возвращает их.
    """
    if first == second:
        return settings

    for key in PAIR_KEYS.values():
        settings[key] = [pair for pair in settings.get(key, []) if sorted(pair) != sorted([first, second])]

    if state in PAIR_KEYS:
        settings[PAIR_KEYS[state]].append([first, second])

    return settings


def nextSubjectPairState(state):
    """Следующее состояние пары при клике по ячейке таблицы: можно -> нежелательно -> нельзя -> можно."""
    return {PAIR_ALLOWED: PAIR_SOFT, PAIR_SOFT: PAIR_HARD, PAIR_HARD: PAIR_ALLOWED}[state]


def subjectPairs(settings, *keys):
    """Пары предметов из списков ``keys`` ("joint_subject_pairs", "soft_subject_pairs") —
    множество отсортированных кортежей, чтобы порядок предметов в паре не имел значения.
    """
    return {tuple(sorted(pair)) for key in keys for pair in settings.get(key, [])}


def isSubjectPair(pairs, first, second):
    """Входят ли предметы ``first`` и ``second`` в ``pairs`` (результат ``subjectPairs``)."""
    return tuple(sorted([first, second])) in pairs


def programPairs(settings):
    """Пары программ, уроки одного предмета в которых не совпадают по времени, — в обе стороны."""
    pairs = {tuple(pair) for pair in settings.get("non_overlapping_programs", [])}

    return pairs | {(second, first) for first, second in pairs}


# ---------------------------------------------------------------- пары курсов

def sameLine(first, second):
    """Курсы ``first`` и ``second`` из одной линейки одного потока — у них одни ученики.

    Только для курсов потока: у курсов без потока (доп. курсы, блоки) общих учеников нет.
    Оба уровня ЕГЭ — одна линейка «ЕГЭ» (поле "line", см. courses.courseLine).
    """
    return (first.get("stream_id") is not None and first.get("stream_id") == second.get("stream_id")
            and first.get("line") == second.get("line"))


def isLevelPair(first, second):
    """Курсы — один предмет одной линейки потока на разных уровнях (ЕГЭ основной и ЕГЭ продвинутый).

    Такие уроки в одно время — не «пересечение», а наоборот хорошо: ученик может перейти
    с уровня на уровень, не меняя расписания (правило levelsApart). Курс без предметов
    парой уровней не бывает.
    """
    return (sameLine(first, second) and first.get("program") != second.get("program")
            and bool(first.get("subjects")) and bool(second.get("subjects")) and courseSubject(first) == courseSubject(second))


def takenTogether(first, second, together):
    """Курсы — предметы, которые ученики одной линейки потока сдают вместе: их пара отмечена
    «нежелательно» или «нельзя» (``together`` — такие пары, ``subjectPairs``). Пара уровней
    одного предмета сюда не входит.
    """
    if not sameLine(first, second) or isLevelPair(first, second):
        return False

    return isSubjectPair(together, courseSubject(first), courseSubject(second))


def sameDayMatters(first, second, together):
    """Стоит ли подсвечивать курсы в один день: их сдают вместе (``takenTogether``), и ни один
    из них не из COMMON_SUBJECTS — с русским и математикой один день неизбежен.
    """
    subjects = {courseSubject(first), courseSubject(second)}

    return takenTogether(first, second, together) and not subjects & set(COMMON_SUBJECTS)


def togetherPairs(settings):
    """Пары предметов, которые сдают вместе: «нежелательно» и «нельзя» одновременно."""
    return subjectPairs(settings, "soft_subject_pairs", "joint_subject_pairs")
