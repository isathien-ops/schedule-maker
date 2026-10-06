"""Пары предметов и курсов (`src/modules/functions/pairs.py`).

* ``SubjectPairStateTests`` — состояние пары предметов в таблице «Настроек»: «можно» ->
  «нежелательно» -> «нельзя» -> «можно», не зависит от порядка предметов, пары предмета
  с самим собой нет;
* ``CoursePairTests`` — пары курсов одной линейки: одни ученики, уровни ЕГЭ, предметы,
  которые «сдают вместе», программы, которые не пересекаются.

Пары по умолчанию для нового проекта — `test_functions_school_defaults.py`.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import unittest

from src.modules.functions.pairs import (
    isLevelPair, isSubjectPair, nextSubjectPairState, programPairs, sameDayMatters, sameLine, setSubjectPairState,
    subjectPairState, subjectPairs, takenTogether, togetherPairs
)


def course(subject, program="ЕГЭ основной", stream=1):
    """Курс потока ``stream`` по предмету ``subject`` (без предмета — subject=None)."""
    line = "ЕГЭ" if program.startswith("ЕГЭ") else program

    return {"name": f"{program}: {subject}", "program": program, "line": line, "subjects": [subject] if subject else [], "stream_id": stream}


class SubjectPairStateTests(unittest.TestCase):
    """Состояние пары предметов: по кругу, симметрично, без пары предмета с самим собой."""
    def test_subject_pair_states_cycle_and_stay_symmetric(self):
        """Состояние пары предметов переключается по кругу «можно» -> «нежелательно» -> «нельзя» ->
        «можно» и не зависит от порядка предметов в паре.
        """
        settings = {"joint_subject_pairs": [["Химия", "Биология"]]}

        self.assertEqual(subjectPairState(settings, "Биология", "Химия"), "hard")
        self.assertEqual(subjectPairState(settings, "Математика", "Физика"), "allowed")

        state = "allowed"
        seen = []

        for _ in range(3):
            state = nextSubjectPairState(state)
            setSubjectPairState(settings, "Физика", "Математика", state)
            seen.append(subjectPairState(settings, "Математика", "Физика"))

        self.assertEqual(seen, ["soft", "hard", "allowed"])
        self.assertEqual(settings["joint_subject_pairs"], [["Химия", "Биология"]])
        self.assertEqual(settings["soft_subject_pairs"], [])

        setSubjectPairState(settings, "Химия", "Биология", "soft")
        self.assertEqual(settings["joint_subject_pairs"], [])
        self.assertEqual(settings["soft_subject_pairs"], [["Химия", "Биология"]])

    def test_pair_of_subject_with_itself_is_ignored(self):
        """Пара предмета с самим собой не записывается ни в один список."""
        settings = {}

        setSubjectPairState(settings, "Химия", "Химия", "hard")

        self.assertEqual(settings, {})
        self.assertEqual(subjectPairState(settings, "Химия", "Химия"), "allowed")


class CoursePairTests(unittest.TestCase):
    """Правила для пар курсов одной линейки: одни ученики, уровни ЕГЭ, предметы «сдают вместе»."""
    SETTINGS = {
        "joint_subject_pairs": [["Химия", "Биология"]],
        "soft_subject_pairs": [["История", "Литература"], ["Русский язык", "История"]],
        "non_overlapping_programs": [["Семинары", "ЕГЭ продвинутый"]],
    }

    def test_subject_and_program_pairs(self):
        """Пары предметов — без учёта порядка; пары программ — в обе стороны."""
        hard = subjectPairs(self.SETTINGS, "joint_subject_pairs")

        self.assertTrue(isSubjectPair(hard, "Биология", "Химия"))
        self.assertFalse(isSubjectPair(hard, "История", "Литература"))
        self.assertEqual(len(togetherPairs(self.SETTINGS)), 3)
        self.assertEqual(programPairs(self.SETTINGS), {("Семинары", "ЕГЭ продвинутый"), ("ЕГЭ продвинутый", "Семинары")})
        self.assertEqual(programPairs({}), set())

    def test_same_line(self):
        """Одна линейка — один поток и одна линейка; оба уровня ЕГЭ — одна линейка; у курсов без потока
        общих учеников нет.
        """
        self.assertTrue(sameLine(course("Химия"), course("Биология", "ЕГЭ продвинутый")))
        self.assertFalse(sameLine(course("Химия"), course("Биология", stream=2)))
        self.assertFalse(sameLine(course("Химия"), course("Биология", "ОГЭ")))
        self.assertFalse(sameLine(course("Химия", stream=None), course("Биология", stream=None)))

    def test_level_pair(self):
        """Пара уровней — один предмет одной линейки на разных уровнях; курс без предметов — никогда."""
        self.assertTrue(isLevelPair(course("Химия"), course("Химия", "ЕГЭ продвинутый")))
        self.assertFalse(isLevelPair(course("Химия"), course("Химия")))
        self.assertFalse(isLevelPair(course("Химия"), course("Биология", "ЕГЭ продвинутый")))
        self.assertFalse(isLevelPair(course(None), course(None, "ЕГЭ продвинутый")))

    def test_taken_together_and_same_day(self):
        """«Сдают вместе» — пара «нежелательно» или «нельзя» в одной линейке, но не пара уровней;
        «в разные дни» не касается русского и математики — их сдают все.
        """
        together = togetherPairs(self.SETTINGS)

        self.assertTrue(takenTogether(course("Химия"), course("Биология"), together))
        self.assertTrue(sameDayMatters(course("История"), course("Литература"), together))
        self.assertTrue(takenTogether(course("Русский язык"), course("История"), together))
        self.assertFalse(sameDayMatters(course("Русский язык"), course("История"), together))
        self.assertFalse(takenTogether(course("Химия"), course("Биология", stream=2), together))
        self.assertFalse(takenTogether(course("Химия"), course("Физика"), together))
