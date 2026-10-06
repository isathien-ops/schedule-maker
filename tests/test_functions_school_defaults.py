"""Программа онлайн-школы по умолчанию (`src/modules/functions/school_defaults.py`).

* ``OnlineProgramTests`` — стандартная программа нового проекта: потоки с датами, линейки,
  семинары и часы;
* ``DefaultPairsTests`` — пары предметов «нежелательно одновременно» по умолчанию
  (``defaultSoftPairs``): русский и математики со всеми, кроме двух математик между собой.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import unittest
from datetime import date

from src.modules.functions.school_defaults import createOnlineCourseProgram, defaultSoftPairs


class OnlineProgramTests(unittest.TestCase):
    """Стандартная программа онлайн-школы: потоки, семинары, часы."""
    def test_generates_dated_streams_and_standalone_seminars(self):
        """Стандартная программа: 192 курса, 4 потока, начинающихся в понедельник, 13 семинаров
        без потока с общей датой начала, во 2-м потоке нет литературы ОГЭ, у всех курсов есть часы.
        """
        subjects, groups, lessons = createOnlineCourseProgram()

        # 10 / 8 класс — по курсу на предмет: 4 * (11 + 10 + 1 + 10 + 11 + 2) - 1 (во 2-м потоке нет
        # литературы ОГЭ) + 13 семинаров; «+ 1» — «ЕГЭ основной — Математика база»
        self.assertEqual(len(groups), 192)
        # Семинары — это курсы по обычным предметам, а не отдельные предметы; «Математика база» —
        # отдельный предмет
        self.assertEqual(len(subjects), 12)
        self.assertEqual(subjects[subjects.index("Математика") + 1], "Математика база")
        self.assertEqual(sum(sum(load.values()) for load in lessons.values()), 276)

        starts = {
            group["stream_id"]: group["start_date"]
            for group in groups
            if group["stream_id"] is not None
        }
        self.assertEqual(starts, {
            1: "2026-09-07",
            2: "2026-11-23",
            3: "2027-01-11",
            4: "2027-02-22"
        })
        self.assertTrue(all(date.fromisoformat(value).weekday() == 0 for value in starts.values()))

        seminars = [group for group in groups if group["program"] == "Семинары"]
        self.assertEqual(len(seminars), 13)
        self.assertTrue(all(group["stream_id"] is None for group in seminars))
        self.assertTrue(all(group["start_date"] == "2026-10-05" for group in seminars))
        self.assertTrue(all(group["block"] == "extra" for group in seminars))
        self.assertFalse([group for group in groups if "parallel" in group])
        self.assertEqual(lessons["Семинар ОГЭ: Математика"], {"Математика": 1})

        for program in ("8 класс", "10 класс"):
            grade_groups = [group for group in groups if group["program"] == program]
            self.assertEqual({group["stream_id"] for group in grade_groups}, {1, 2, 3, 4})

        # Во 2-м потоке курса литературы ОГЭ нет вовсе
        self.assertNotIn("Поток 2 — ОГЭ — Литература", lessons)
        self.assertTrue(all(hours > 0 for load in lessons.values() for hours in load.values()))


class DefaultPairsTests(unittest.TestCase):
    """Какие пары «нежелательно одновременно» получает новый проект."""
    def test_defaults_cover_common_subjects(self):
        """Русский и обе математики — «нежелательно» со всеми, но не две математики между собой;
        литература и физика — «можно» (их не сдают вместе)."""
        pairs = {tuple(sorted(pair)) for pair in defaultSoftPairs(["Русский язык", "Математика", "Математика база", "Литература", "Физика"])}

        self.assertIn(("Литература", "Русский язык"), pairs)
        self.assertIn(("Математика база", "Физика"), pairs)
        self.assertNotIn(("Математика", "Математика база"), pairs)
        self.assertNotIn(("Литература", "Физика"), pairs)

    def test_default_soft_pairs_without_russian(self):
        """Без русского языка пары строятся только от математик; две математики между собой
        не пара (ученик сдаёт одну из них); предметы без общих — без пар.
        """
        self.assertEqual(defaultSoftPairs(["Математика", "Математика база", "Физика"]), [["Математика", "Физика"], ["Математика база", "Физика"]])
        self.assertEqual(defaultSoftPairs(["Химия", "Биология"]), [])
