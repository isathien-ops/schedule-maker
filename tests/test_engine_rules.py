"""Жёсткие правила движка solve.exe — по его ВЫХОДУ.

Настоящий `src/modules/solve.exe` запускается (subprocess) с небольшим числом шагов и
фиксированным зерном на входах двух видов:

* маленькие искусственные входы, где каждое правило загнано в угол (единственный
  допустимый слот, единственный подходящий преподаватель и т. п.);
* входы этапов, собранные `solver_input.buildStageSettings` из копии реального проекта
  `Расписание_2026-27.zip` (уроки других этапов неподвижны и занимают время преподавателей).

Общая проверка `ruleViolations` читает только вход и выход и перечисляет нарушения:
формат ответа, преподаватель не ведёт два урока сразу и не работает в «не может», у курса
не больше урока в день, все уроки курса ведёт один преподаватель из тех, кто может его вести,
«ведёт» соблюдено, пары «нельзя» и непересекающиеся программы не совпадают по слоту,
закреплённые уроки на месте, закрытые слоты и слоты вне сетки пусты, число уроков = нагрузка
(иначе — сообщение «[Внимание]»), лимит курсов на преподавателя соблюдён.

Запуск решателя, маленькие входы и сама проверка — в `tests/engine.py`. Мягкие правила —
`test_engine_soft_rules.py`, целые программы школы — `test_engine_programs.py`.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src.variables import PATH_TO_FOLDER
from src.modules.functions.solver_input import buildStageSettings
from src.modules.functions.stages import getStages, mergeStageAnswer, stageCourses, teacherClashes
from src.modules.functions.tree import importProjectArchive
from tests.builders import SOLVER
from tests.engine import (
    LIMIT_REACHED, MISSING_TOTAL, NO_TEACHER, NO_TIME, PIN_FAILED, cellsOf, course, finalLine, otherStageLessons, pinSummary,
    placedLessons, ruleViolations, runSolver, solved, stageInput, teacher, tiny
)
from tests.real_project import ARCHIVE, FrozenDate


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
class EngineSmallInputTests(unittest.TestCase):
    """Каждое правило на маленьком входе, где у решателя ровно один допустимый ответ (или ни одного)."""

    def check(self, settings, seeds=(1, 2, 3), iterations=200000):
        """Прогоны с несколькими зёрнами: нарушений нет. Возвращает [(ответ, stdout)]."""
        results = []

        for seed in seeds:
            answer, log = solved(self, settings, seed, iterations)
            self.assertEqual(ruleViolations(settings, answer, log), [], (seed, log))
            results.append((answer, log))

        return results

    def test_output_format_and_week_size(self):
        """Ответ: все курсы входа, неделя дни × min(6, уроков в дне), пустая ячейка {"#", []};
        курс без преподавателя остаётся пустым, о нём сообщение «нет преподавателя»."""
        settings = tiny(2, 8, [course("A", "Математика", 2), course("B", "Физика", 1)], {"T1": teacher("Математика", ["A"])})

        for answer, log in self.check(settings):
            self.assertEqual(set(answer), {"A", "B"})
            self.assertEqual([len(day) for day in answer["A"]], [6, 6])
            self.assertTrue(all(cell == {"subject": "#", "teachers": []} for day in answer["B"] for cell in day))
            self.assertIn(NO_TEACHER.format(course="B", subject="Физика"), log)
            self.assertEqual(sorted(day for day, _, _, _ in cellsOf(answer, "A")), [0, 1])
            self.assertEqual({name for _, _, _, name in cellsOf(answer, "A")}, {"T1"})

    def test_progress_and_final_lines(self):
        """stdout для журнала сервера: сначала «Закреплено N из M уроков, подбирается K», раз в миллион
        шагов строка «Шаг N из M | …», в конце — «Готово: оценено изменений N из M шагов».
        Подбирается 6 уроков, поэтому ни предупреждения «почти нечего», ни ранней остановки нет."""
        settings = tiny(6, 2, [course("A", "Математика", 6)], {"T": teacher("Математика", ["A"])})
        _, log = solved(self, settings, 4, 1000000)
        lines = log.strip().split("\n")

        self.assertEqual(lines[0], "Закреплено 0 из 6 уроков, подбирается 6")
        self.assertRegex(lines[1], r"^Шаг 1000000 из 1000000 \| пары «нежелательно»: 0 \| 2 урока курса в день: 0 \| неудобства: \d+ \(лучшее пока \d+\)$")
        self.assertRegex(lines[-1], r"^Готово: оценено изменений \d+ из 1000000 шагов$")
        self.assertEqual(len(lines), 3)

        # Оценённых изменений меньше шагов: часть шагов отсеивают жёсткие правила
        evaluated, steps = finalLine(log)
        self.assertLess(0, evaluated)
        self.assertLess(evaluated, steps)

    def test_teacher_never_teaches_two_lessons_at_once(self):
        """Один преподаватель на три курса и два слота: два урока в разных слотах, третий не поставлен
        и назван в сообщении, итог «не удалось поставить уроков: 1»."""
        settings = tiny(1, 2, [course(name, "Математика") for name in "ABC"], {"T": teacher("Математика", "ABC")})

        for answer, log in self.check(settings):
            slots = [(day, lesson) for name in "ABC" for day, lesson, _, _ in cellsOf(answer, name)]
            self.assertEqual(sorted(slots), [(0, 0), (0, 1)])
            self.assertEqual(log.count(": нет свободного времени"), 1)
            self.assertIn(MISSING_TOTAL + "1\n", log)

    def test_cannot_slots_are_never_used(self):
        """«Не может» (free) во всех слотах, кроме одного: урок встаёт ровно туда."""
        free = [(day, lesson) for day in range(2) for lesson in range(3) if (day, lesson) != (1, 2)]
        settings = tiny(2, 3, [course("A", "Математика")], {"T": teacher("Математика", ["A"], free=free)})

        for answer, _ in self.check(settings):
            self.assertEqual(cellsOf(answer, "A"), [(1, 2, "Математика", "T")])

    def test_cannot_everywhere_leaves_lesson_unplaced(self):
        """Преподаватель «не может» всю неделю: урока нет, есть сообщение «нет свободного времени»."""
        free = [(day, lesson) for day in range(2) for lesson in range(2)]
        settings = tiny(2, 2, [course("A", "Математика")], {"T": teacher("Математика", ["A"], free=free)})

        for answer, log in self.check(settings):
            self.assertEqual(cellsOf(answer, "A"), [])
            self.assertIn(NO_TIME.format(course="A", subject="Математика"), log)

    def test_blocked_slots_are_never_used(self):
        """Закрытые слоты курса (blocked_slots) пусты; слот вне сетки в списке не ломает решатель."""
        blocked = [[day, lesson] for day in range(2) for lesson in range(3) if (day, lesson) != (0, 1)] + [[9, 9]]
        settings = tiny(2, 3, [course("A", "Математика"), course("B", "Физика", 2)],
                        {"T1": teacher("Математика", ["A"]), "T2": teacher("Физика", ["B"])},
                        blocked_slots={"A": blocked})

        for answer, _ in self.check(settings):
            self.assertEqual(cellsOf(answer, "A"), [(0, 1, "Математика", "T1")])
            self.assertEqual(len(cellsOf(answer, "B")), 2)

    def test_one_lesson_per_day(self):
        """У курса не больше урока в день: 3 часа на 3 дня — по уроку в каждый день;
        3 часа на 2 дня — два урока и сообщение о третьем."""
        settings = tiny(3, 3, [course("A", "Математика", 3)], {"T": teacher("Математика", ["A"])})

        for answer, _ in self.check(settings):
            self.assertEqual(sorted(day for day, _, _, _ in cellsOf(answer, "A")), [0, 1, 2])

        settings = tiny(2, 3, [course("A", "Математика", 3)], {"T": teacher("Математика", ["A"])})

        for answer, log in self.check(settings):
            self.assertEqual(sorted(day for day, _, _, _ in cellsOf(answer, "A")), [0, 1])
            self.assertEqual(log.count(NO_TIME.format(course="A", subject="Математика")), 1)

    def test_course_has_one_teacher_from_those_who_can(self):
        """Все уроки курса у одного преподавателя из «может вести»: T1 свободен только 2 дня, T2 — 3,
        курсу нужно 3 урока — ведёт T2; свободные T3 (тот же предмет, другой курс) и T4 (другой
        предмет) не берутся никогда."""
        settings = tiny(5, 1, [course("A", "Математика", 3), course("Z", "Математика", 0)], {
            "T1": teacher("Математика", ["A"], free=[(day, 0) for day in (2, 3, 4)]),
            "T2": teacher("Математика", ["A"], free=[(day, 0) for day in (0, 1)]),
            "T3": teacher("Математика", ["Z"]),
            "T4": teacher("Физика", ["A"])
        })

        for answer, _ in self.check(settings):
            self.assertEqual([(day, name) for day, _, _, name in cellsOf(answer, "A")], [(2, "T2"), (3, "T2"), (4, "T2")])

    def test_course_is_not_split_between_teachers(self):
        """Если ни одному преподавателю не хватает дней, курс всё равно не делится между ними:
        уроки ведёт один, недостающий урок назван в сообщении."""
        settings = tiny(5, 1, [course("A", "Математика", 4)], {
            "T1": teacher("Математика", ["A"], free=[(day, 0) for day in (2, 3, 4)]),
            "T2": teacher("Математика", ["A"], free=[(day, 0) for day in (0, 1)])
        })

        for answer, log in self.check(settings):
            lessons = cellsOf(answer, "A")
            self.assertEqual(len({name for _, _, _, name in lessons}), 1)
            self.assertEqual(len(lessons), 3)
            self.assertEqual(log.count(NO_TIME.format(course="A", subject="Математика")), 1)

    def test_assigned_teacher_wins(self):
        """«Ведёт» соблюдается, даже если другой кандидат свободнее; «ведёт» без «может вести» не действует."""
        settings = tiny(5, 1, [course("A", "Математика", 2)], {
            # Первая по алфавиту: «ведёт», но курса нет в «может вести» — отметка не действует
            "А-без-может": {"subjects": [{"subject": "Математика", "classes": [], "assigned": ["A"]}], "free": []},
            "Б-ведёт": teacher("Математика", ["A"], assigned=["A"], free=[(day, 0) for day in (0, 1, 2)]),
            "В-свободен": teacher("Математика", ["A"])
        })

        for answer, _ in self.check(settings):
            self.assertEqual([(day, name) for day, _, _, name in cellsOf(answer, "A")], [(3, "Б-ведёт"), (4, "Б-ведёт")])

    def test_forbidden_pair_only_inside_line_and_stream(self):
        """Пара «нельзя» (Математика — Физика) не совпадает по слоту в одной линейке и потоке, а в другом
        потоке, другой линейке и у курса без потока — совпадать может."""
        courses = [
            course("A", "Математика"),
            course("B", "Физика"),
            course("C", "Физика", stream=2),
            course("D", "Физика", line="ОГЭ", program="ОГЭ"),
            course("E", "Физика", stream=None)
        ]
        teachers = {f"T{name}": teacher(subject, [name]) for name, subject in zip("ABCDE", ["Математика"] + ["Физика"] * 4)}
        settings = tiny(1, 1, courses, teachers, joint_subject_pairs=[["Физика", "Математика"]], constants={"A": {"0-0": "Математика"}})

        for answer, log in self.check(settings):
            self.assertEqual(cellsOf(answer, "A"), [(0, 0, "Математика", "TA")])
            self.assertEqual(cellsOf(answer, "B"), [])
            self.assertIn(NO_TIME.format(course="B", subject="Физика"), log)

            for name in "CDE":
                self.assertEqual(cellsOf(answer, name), [(0, 0, "Физика", f"T{name}")])

        # С двумя слотами пару просто разводят по разным урокам
        settings = tiny(1, 2, courses[:2], {key: teachers[key] for key in ("TA", "TB")}, joint_subject_pairs=[["Физика", "Математика"]], constants={"A": {"0-0": "Математика"}})

        for answer, _ in self.check(settings):
            self.assertEqual(cellsOf(answer, "B"), [(0, 1, "Физика", "TB")])

    def test_non_overlapping_programs(self):
        """Семинар не совпадает по слоту с ЕГЭ продвинутым по тому же предмету (пара программ в любом
        порядке); семинар по другому предмету совпадать может."""
        courses = [
            course("P", "Математика", program="ЕГЭ продвинутый"),
            course("S1", "Математика", program="Семинары", line="Семинар", stream=None),
            course("S2", "Физика", program="Семинары", line="Семинар", stream=None)
        ]
        teachers = {"TP": teacher("Математика", ["P"]), "TS1": teacher("Математика", ["S1"]), "TS2": teacher("Физика", ["S2"])}

        for order in (["Семинары", "ЕГЭ продвинутый"], ["ЕГЭ продвинутый", "Семинары"]):
            settings = tiny(1, 1, courses, teachers, non_overlapping_programs=[order], constants={"P": {"0-0": "Математика"}})

            for answer, log in self.check(settings):
                self.assertEqual(cellsOf(answer, "P"), [(0, 0, "Математика", "TP")])
                self.assertEqual(cellsOf(answer, "S1"), [])
                self.assertIn(NO_TIME.format(course="S1", subject="Математика"), log)
                self.assertEqual(cellsOf(answer, "S2"), [(0, 0, "Физика", "TS2")])

    def test_pinned_lessons(self):
        """Закреплённый урок стоит на своём месте; невозможное закрепление (закрытый слот, «не может»,
        больше закреплений, чем часов, вне сетки, два закрепления одного преподавателя в слоте)
        не ставится, о нём понятное сообщение, а урок всё равно ставится в другое время."""
        courses = [
            course("A", "Математика", 2),
            course("B", "Физика"),
            course("C", "Химия"),
            course("D", "Биология"),
            course("E", "Математика", line="E"),
            course("F", "Физика", line="F"),
            course("G", "Физика", line="G")
        ]
        teachers = {
            "TA": teacher("Математика", ["A"]),
            "TB": teacher("Физика", ["B"]),
            "TC": teacher("Химия", ["C"], free=[(0, 1)]),
            "TD": teacher("Биология", ["D"]),
            "TE": teacher("Математика", ["E"]),
            "TFG": teacher("Физика", ["F", "G"])
        }
        constants = {
            "A": {"1-2": "Математика"},
            "B": {"0-0": "Физика"},
            "C": {"0-1": "Химия"},
            "D": {"0-0": "Биология", "1-0": "Биология"},
            "E": {"5-0": "Математика"},
            "F": {"1-1": "Физика"},
            "G": {"1-1": "Физика"}
        }
        settings = tiny(2, 3, courses, teachers, constants=constants, blocked_slots={"B": [[0, 0]]})

        for answer, log in self.check(settings):
            self.assertIn((1, 2, "Математика", "TA"), cellsOf(answer, "A"))
            self.assertEqual(len(cellsOf(answer, "A")), 2)

            self.assertIn(PIN_FAILED.format(course="B", subject="Физика", day=1, lesson=1) + "это время закрыто для курса", log)
            self.assertEqual(len(cellsOf(answer, "B")), 1)
            self.assertNotIn((0, 0), [(day, lesson) for day, lesson, _, _ in cellsOf(answer, "B")])

            self.assertIn(PIN_FAILED.format(course="C", subject="Химия", day=1, lesson=2) + "преподаватель TC в это время не может", log)
            self.assertEqual(len(cellsOf(answer, "C")), 1)

            self.assertIn("закреплено больше уроков, чем часов у курса", log)
            self.assertEqual(len(cellsOf(answer, "D")), 1)

            self.assertIn('[WARNING] constants: key "5-0" out of range for E', log)
            self.assertEqual(len(cellsOf(answer, "E")), 1)

            # F и G закреплены в один слот у одного преподавателя: один на месте, второй — в другое время
            self.assertIn("в это время ведёт другой закреплённый урок", log)
            self.assertEqual(sorted(slot[:2] for name in "FG" for slot in cellsOf(answer, name)).count((1, 1)), 1)

    def test_max_courses_per_teacher(self):
        """Лимит курсов на преподавателя: курсы делятся между свободными; если брать некому — курс
        без уроков и с сообщением; курсы других этапов (existing_courses_by_teacher) входят в лимит;
        отметки «ведёт» лимит не останавливают, но о превышении есть сообщение."""
        both = [course("X", "Математика"), course("Y", "Математика", line="Y")]

        settings = tiny(2, 1, both, {"T1": teacher("Математика", "XY"), "T2": teacher("Математика", "XY")}, max_courses_per_teacher=1)

        for answer, _ in self.check(settings):
            self.assertEqual({cellsOf(answer, name)[0][3] for name in "XY"}, {"T1", "T2"})

        settings = tiny(2, 1, both, {"T1": teacher("Математика", "XY")}, max_courses_per_teacher=1)

        for answer, log in self.check(settings):
            self.assertEqual(len(cellsOf(answer, "X")) + len(cellsOf(answer, "Y")), 1)
            self.assertEqual(log.count(": у всех подходящих преподавателей уже максимум курсов"), 1)

        settings = tiny(2, 1, both, {"T1": teacher("Математика", "XY"), "T2": teacher("Математика", "XY")},
                        max_courses_per_teacher=2, existing_courses_by_teacher={"T1": 2})

        for answer, _ in self.check(settings):
            self.assertEqual({cellsOf(answer, name)[0][3] for name in "XY"}, {"T2"})

        settings = tiny(2, 1, both, {"T1": teacher("Математика", "XY", assigned="XY")}, max_courses_per_teacher=1)

        for answer, log in self.check(settings):
            self.assertEqual({cellsOf(answer, name)[0][3] for name in "XY"}, {"T1"})
            self.assertIn("[Внимание] T1: курсов с отметкой «ведёт» (вместе с другими потоками и доп. курсами) 2 — больше максимума 1", log)

    def test_checker_catches_broken_answers(self):
        """Сама проверка ruleViolations ловит испорченный ответ (иначе остальные тесты ничего не значат)."""
        settings = tiny(2, 2, [course("A", "Математика", 2), course("B", "Физика")],
                        {"T1": teacher("Математика", ["A"], free=[(1, 1)]), "T2": teacher("Физика", ["B"])},
                        joint_subject_pairs=[["Математика", "Физика"]], constants={"A": {"0-0": "Математика"}})
        answer, log = solved(self, settings)
        self.assertEqual(ruleViolations(settings, answer, log), [])

        def broken(change):
            """Копия ответа после правки `change`."""
            result = copy.deepcopy(answer)
            change(result)
            return ruleViolations(settings, result, log)

        empty = {"subject": "#", "teachers": []}

        def clear(result, name):
            """Убирает все уроки курса."""
            result[name] = [[dict(empty) for _ in day] for day in result[name]]

        def put(result, name, day, lesson, subject, who):
            """Ставит урок в ячейку."""
            result[name][day][lesson] = {"subject": subject, "teachers": [who]}

        # Как испорчен ответ в каждом случае:
        # free — урок A в слот (1, 1), где T1 «не может»; day — два урока A в один день;
        # pair — B в слот закреплённого урока A (пара «нельзя»); teacher — B ведёт T1, который не ведёт Физику;
        # lost — у B нет уроков; pin — урок A не в закреплённой ячейке (0, 0); shape — у A на один день меньше
        cases = {
            "free": lambda result: (clear(result, "A"), put(result, "A", 0, 0, "Математика", "T1"), put(result, "A", 1, 1, "Математика", "T1")),
            "day": lambda result: (clear(result, "A"), put(result, "A", 0, 0, "Математика", "T1"), put(result, "A", 0, 1, "Математика", "T1")),
            "pair": lambda result: (clear(result, "B"), put(result, "B", 0, 0, "Физика", "T2")),
            "teacher": lambda result: (clear(result, "B"), put(result, "B", 1, 0, "Физика", "T1")),
            "lost": lambda result: clear(result, "B"),
            "pin": lambda result: (clear(result, "A"), put(result, "A", 0, 1, "Математика", "T1"), put(result, "A", 1, 0, "Математика", "T1")),
            "shape": lambda result: result["A"].pop()
        }

        for name, change in cases.items():
            with self.subTest(name):
                self.assertNotEqual(broken(change), [])

    def test_broken_input_exits_with_error(self):
        """Битый вход, нет файла, неверные флаги: код выхода ≠ 0, прежний файл ответа не тронут."""
        good = tiny(1, 1, [course("A", "Математика")], {"T": teacher("Математика", ["A"])})

        with tempfile.TemporaryDirectory() as folder:
            def path(name, text=None):
                """Путь к файлу во временной папке; с `text` — файл с этим содержимым."""
                result = os.path.join(folder, name)

                if text is not None:
                    with open(result, "w", encoding="utf-8") as file:
                        file.write(text)

                return result

            weights = path("weights.json", "{}")
            inputs = {
                "broken json": path("broken.json", "{\"working_days_per_week\": "),
                "not an object": path("array.json", "[]"),
                "no week size": path("nokeys.json", json.dumps({"classes": {}, "teachers": {}})),
                "missing file": path("missing.json"),
                "good": path("good.json", json.dumps(good, ensure_ascii=False))
            }
            cases = {name: ["--input", source, "--weights", weights] for name, source in inputs.items() if name != "good"}
            cases["missing weights"] = ["--input", inputs["good"], "--weights", path("nothing.json")]
            cases["broken weights"] = ["--input", inputs["good"], "--weights", path("bad_weights.json", "{oops")]
            cases["bad iterations"] = ["--input", inputs["good"], "--weights", weights, "--iterations", "abc"]
            cases["unknown flag"] = ["--input", inputs["good"], "--weights", weights, "--unknown", "1"]

            for name, args in cases.items():
                with self.subTest(name):
                    output = path("answer.json", "PREVIOUS")
                    result = subprocess.run([SOLVER, *args, "--output", output], capture_output=True, timeout=60)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue(result.stderr.strip())

                    with open(output, encoding="utf-8") as file:
                        self.assertEqual(file.read(), "PREVIOUS")

            # Контроль: тот же набор с хорошими файлами проходит
            output = path("answer.json")
            result = subprocess.run([SOLVER, "--input", inputs["good"], "--weights", weights, "--output", output, "--iterations", "1000", "--seed", "1"],
                                    capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)

            with open(output, encoding="utf-8") as file:
                self.assertEqual(cellsOf(json.load(file), "A"), [(0, 0, "Математика", "T")])


@unittest.skipUnless(os.path.exists(SOLVER), "solve.exe is not built")
@unittest.skipUnless(os.path.exists(ARCHIVE), "the 2026/27 project archive is not here")
class EngineRealProjectTests(unittest.TestCase):
    """Этапы реального проекта 2026/27: вход — buildStageSettings, проверка — по выходу solve.exe."""
    NAME = "__test_engine__"

    @classmethod
    def setUpClass(cls):
        """Импортирует архив во временную папку проектов, читает settings/answer/weights и удаляет копию."""
        folder = f"{PATH_TO_FOLDER}/projects/{cls.NAME}"
        shutil.rmtree(folder, ignore_errors=True)
        importProjectArchive(ARCHIVE, cls.NAME)

        try:
            data = {}

            for name in ("settings", "answer", "weights"):
                with open(f"{folder}/{name}.json", encoding="utf-8") as file:
                    data[name] = json.load(file)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

        cls.settings, cls.answer, cls.weights = data["settings"], data["answer"], data["weights"]

    def solveStage(self, settings, answer, stage, seed=5, iterations=300000):
        """Строит вход этапа, запускает решатель и проверяет все правила (и против уроков других этапов).

        Возвращает (вход, ответ, stdout).
        """
        inp = stageInput(settings, answer, stage)
        out, log = solved(self, inp, seed, iterations, self.weights)
        self.assertEqual(ruleViolations(inp, out, log, otherStageLessons(settings, answer, stage, inp)), [], log)
        return inp, out, log

    def test_every_stage_against_accepted_schedule(self):
        """Каждый этап поверх принятого расписания: правила соблюдены, преподаватели не заняты уроками
        других этапов, семинары не совпадают с ЕГЭ продвинутым; все уроки поставлены; уже идущий
        поток 1 остаётся ровно таким, как в принятом расписании."""
        self.assertEqual([stage["key"] for stage in getStages(self.settings)], ["1", "extra", "2"])

        for stage in ("1", "extra", "2"):
            with self.subTest(stage):
                inp, out, log = self.solveStage(self.settings, self.answer, stage)
                self.assertNotIn(MISSING_TOTAL, log)

                if stage == "1":
                    # Все курсы потока 1 начались: их уроки и преподаватели закреплены
                    self.assertEqual(len(inp["constants"]), len(out))
                    # (в answer.json дни обрезаны по сетке, у решателя неделя прямоугольная — сравниваем уроки)
                    self.assertEqual(sorted(placedLessons(out)), sorted(placedLessons({name: self.answer[name] for name in out})))

    def test_all_stages_from_empty_schedule(self):
        """Все этапы подряд с пустого расписания (как «Составить» для нового года): в каждом этапе правила
        соблюдены, а в итоговом расписании нет ни одной накладки преподавателя (teacherClashes)."""
        answer = {}

        for stage in getStages(self.settings):
            _, out, log = self.solveStage(self.settings, answer, stage["key"], seed=9)
            self.assertNotIn(MISSING_TOTAL, log)
            answer = mergeStageAnswer(answer, out, stage["courses"])

        self.assertEqual(teacherClashes(self.settings, answer), [])
        self.assertEqual(
            {name: sum(1 for item in placedLessons(answer) if item[0] == name) for name in answer},
            {name: sum(int(hours) for hours in load.values()) for name, load in self.settings["classes"]["lessons"].items()}
        )

    def test_stage2_with_restrictions(self):
        """Поток 2 со стеснёнными условиями: лимит 5 курсов, трём преподавателям «не может» в пн и вт,
        три урока закреплены в свободные для них слоты. Правила соблюдены, закрепления на месте
        у закреплённого за курсом преподавателя, лишние курсы — с сообщениями о лимите."""
        settings = copy.deepcopy(self.settings)
        settings["max_courses_per_teacher"] = 5
        closed = ["Хмелевская Анастасия", "Дускаева Дана", "Передерин Дмитрий"]

        for name in closed:
            settings["teachers"][name]["availability"]["2"]["free"] = [[day, lesson] for day in (0, 1) for lesson in range(6)]

        # Места для закреплений: слот в сетке, открыт курсу, преподаватель «ведёт» курс и свободен
        inp = stageInput(settings, self.answer, "2")
        pins = {}

        for name in ["Поток 2 — ЕГЭ основной — Русский язык", "Поток 2 — ОГЭ — Физика", "Поток 2 — 8 класс — Математика"]:
            subject = next(iter(inp["classes"]["lessons"][name]))
            owner = next(who for who, data in inp["teachers"].items() for item in data["subjects"] if name in item["assigned"])
            slot = next(
                (day, lesson) for day in range(2, 5) for lesson in range(3)
                if [day, lesson] not in inp["teachers"][owner]["free"] and [day, lesson] not in inp.get("blocked_slots", {}).get(name, [])
                and (day, lesson) not in [value[0] for value in pins.values()]
            )
            pins[name] = (slot, subject, owner)
            settings["constants"][name] = {f"{slot[0]}-{slot[1]}": subject}

        inp, out, log = self.solveStage(settings, self.answer, "2", seed=21)

        for name, ((day, lesson), subject, owner) in pins.items():
            self.assertEqual(out[name][day][lesson], {"subject": subject, "teachers": [owner]}, name)

        self.assertNotIn("[Внимание] закреплённый урок", log)
        self.assertIn(LIMIT_REACHED.format(course="Поток 2 — 10 класс — Физика", subject="Физика"), log)

        for name in closed:
            self.assertFalse([item for item in placedLessons(out) if name in item[4] and item[1] in (0, 1)], name)

    def test_dropped_started_course_still_blocks_its_pairs(self):
        """Идущий курс без преподавателя (Поток 1 — ЕГЭ продвинутый — Физика) не передаётся решателю,
        но его уроки остаются: математика линейки ЕГЭ потока 1 (пара «нельзя» с физикой) в его
        время не ставится, остальные курсы потока строятся заново и ставятся полностью."""
        dropped = "Поток 1 — ЕГЭ продвинутый — Физика"
        answer = {dropped: self.answer[dropped]}
        taken = {(day, lesson) for _, day, lesson, _, _ in placedLessons(answer)}
        self.assertEqual(len(taken), 2)

        inp, out, log = self.solveStage(self.settings, answer, "1", seed=13)
        groups = {group["name"]: group for group in inp["classes"]["custom_groups"]}

        self.assertNotIn(dropped, out)
        self.assertNotIn(MISSING_TOTAL, log)

        math = [item for item in placedLessons(out) if item[3] == "Математика" and groups[item[0]]["line"] == "ЕГЭ"]
        self.assertTrue(math)
        self.assertFalse([item for item in math if (item[1], item[2]) in taken])

    def test_keep_mode_lessons_stay_in_place(self):
        """«Оставить уже принятые уроки на месте» для уже составленных курсов потока 2: их уроки и преподаватели в ответе
        ровно как в принятом расписании, остальные курсы достраиваются по правилам."""
        keep = [name for name in stageCourses(self.settings, "2") if name in self.answer]
        self.assertTrue(keep)

        with mock.patch("datetime.date", FrozenDate):
            inp = buildStageSettings(self.settings, self.answer, "2", keep)

        out, log = solved(self, inp, 17, 300000, self.weights)
        self.assertEqual(ruleViolations(inp, out, log, otherStageLessons(self.settings, self.answer, "2", inp)), [], log)
        self.assertNotIn("[Внимание] закреплённый урок", log)
        self.assertNotIn(MISSING_TOTAL, log)

        # «Закреплено N из M»: встали все закрепления входа, M — все часы курсов этапа
        summary = pinSummary(log)
        self.assertIsNotNone(summary, log)
        pinned, total, movable, unstaffed = summary
        self.assertEqual(pinned, sum(len(cells) for cells in inp["constants"].values()))
        self.assertEqual(total, sum(int(hours) for load in inp["classes"]["lessons"].values() for hours in load.values()))
        self.assertEqual(total, pinned + movable + unstaffed)
        self.assertGreater(movable, 0)

        for name in keep:
            accepted = sorted((day, lesson, subject, teachers[:1]) for course, day, lesson, subject, teachers in placedLessons(self.answer) if course == name)
            built = sorted((day, lesson, subject, [who]) for day, lesson, subject, who in cellsOf(out, name))

            # Время сохраняется всегда; преподаватель — если он был (у трёх курсов в принятом его нет,
            # и решатель подбирает его сам)
            self.assertEqual([item[:3] for item in built], [item[:3] for item in accepted], name)
            for old, new in zip(accepted, built):
                if old[3]:
                    self.assertEqual(new[3], old[3], name)

    def test_greedy_start_already_keeps_rules(self):
        """Без отжига (--iterations 0) жадная расстановка уже соблюдает все жёсткие правила."""
        inp = stageInput(self.settings, self.answer, "2")
        out, log = solved(self, inp, seed=3, iterations=0, weights=self.weights)
        self.assertEqual(ruleViolations(inp, out, log, otherStageLessons(self.settings, self.answer, "2", inp)), [], log)

    def test_same_seed_same_result(self):
        """Одинаковое зерно — одинаковый ответ и вывод; другое зерно — другой вариант."""
        inp = stageInput(self.settings, self.answer, "2")
        first = runSolver(inp, 11, 300000, self.weights)
        second = runSolver(inp, 11, 300000, self.weights)
        other = runSolver(inp, 12, 300000, self.weights)

        self.assertEqual(first[0], 0)
        self.assertEqual(first[1], second[1])
        self.assertEqual(first[2], second[2])
        self.assertNotEqual(first[1], other[1])
