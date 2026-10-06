"""Действия вкладки «Настройки» (`src/web/tabs/settings.py`): сетка времени, ограничения, пары предметов.

* сетка (setGrid, copyMonday): неверное время и порядок, перенос уроков, закреплений, отметок
  и своих правил на новые часы, вопрос и версия перед удалением уроков из сетки;
* ограничения (setLimit) и таблица пар предметов (cyclePair);
* ``JointGridTests`` — общий урок линеек, которые идут вместе, в вопросе о сетке считается один раз,
  а в отказе (урок идущей копии) называется один раз — курсом копии.

Основа — `RealProjectCase` из `tests/real_project.py`: копия реального проекта 2026/27, «сегодня»
04.10.2026, действия идут через сервер, как со страницы (POST /api/project/<имя>/action).
Проверяется, что сервер защищает курсы, которые уже идут, переспрашивает (ответ с "confirm")
перед опасными действиями, сохраняет версии «Перед: …» и при отказе не портит файлы проекта.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

from src.modules.translate import translate
from src.modules.functions.stages import stageCourses
from src.modules.functions.variants import loadVariants, saveVariant
from tests.builders import JOINT_LINE, jointCourse, jointProject, markJoint, shiftStream
from tests.real_project import RUS_8_2, RealProjectCase, lessons


class SettingsTabTests(RealProjectCase):
    """Вкладка «Настройки»: сетка, ограничения, пары предметов."""
    NAME = "__test_settings__"

    def grid(self):
        """Текущая сетка времени (7 дней)."""
        return [list(day) for day in self.state()["grid"]]

    def test_grid_rejects_bad_time_and_wrong_order(self):
        """Нечитаемое время и время не по порядку отклоняются с понятным текстом, файл не меняется."""
        grid = self.grid()
        before = self.load("settings.json")["day_grid"]

        grid[0][1] = "абракадабра"
        self.assertIn("абракадабра", self.refused("setGrid", days=grid))

        grid = self.grid()
        grid[0][1] = "15:00 - 16:00"  # раньше первого урока 16:20
        self.assertIn("по порядку", self.refused("setGrid", days=grid))
        self.assertEqual(self.load("settings.json")["day_grid"], before)

    def test_grid_time_change_keeps_lessons_variants_and_follows_rules(self):
        """Сменили только время урока (столбцы не сдвинулись): расписание и варианты остаются,
        без вопросов, а правило «Не ставить уроки в выбранное время» подхватывает новое время.
        """
        answer = self.load("answer.json")
        saveVariant(self.folder, "2", 1, {})
        self.ok("savePenalty", penalty={"name": "Поздно", "template": "time", "weight": 10,
                                        "params": {"target": "all", "value": "", "days": [0, 1, 2, 3, 4, 5], "times": ["19:40 - 21:10"]}})

        grid = self.grid()
        for day in range(6):
            grid[day] = ["19:45 - 21:15" if time == "19:40 - 21:10" else time for time in grid[day]]

        body = self.ok("setGrid", days=grid)
        self.assertNotIn("confirm", body)
        self.assertEqual(self.load("answer.json"), answer)
        self.assertEqual(len(loadVariants(self.folder, "2")), 1)
        self.assertEqual(self.load("settings.json")["custom_penalties"][0]["params"]["times"], ["19:45 - 21:15"])
        self.assertEqual(self.grid()[0][2], "19:45 - 21:15")

    def test_grid_cannot_drop_lessons_of_started_courses(self):
        """Убрать время, на котором стоят уроки идущего потока 1, нельзя — отказ со списком курсов."""
        grid = self.grid()
        grid[0] = []

        error = self.refused("setGrid", days=grid)
        self.assertIn("Поток 1", error)
        self.assertEqual(len(self.grid()[0]), 3)

    def test_grid_dropping_lessons_asks_and_saves_version(self):
        """Убрать время, где стоят только уроки ещё не начавшихся курсов: сначала вопрос (опасное действие),
        после согласия — версия «Перед: …», уроки этого времени уходят, варианты всех этапов стираются.
        """
        answer = self.load("answer.json")
        settings = self.load("settings.json")
        started = set(stageCourses(settings, "1"))
        # Время, где стоят уроки, но ни одного урока потока 1
        used = {}
        for name, week in answer.items():
            for day, lesson, _ in lessons(week):
                used.setdefault((day, lesson), set()).add(name)

        day, lesson = next(slot for slot, names in sorted(used.items()) if not names & started)

        saveVariant(self.folder, "2", 1, {})
        grid = self.grid()
        grid[day][lesson] = ""

        body = self.ok("setGrid", days=grid)
        self.assertIn("confirm", body)
        self.assertTrue(body.get("danger"))
        self.assertEqual(self.load("answer.json"), answer)

        self.ok("setGrid", days=grid, force=True)
        self.assertTrue(any(name.startswith("Перед:") for name in self.versions()))
        self.assertEqual(loadVariants(self.folder, "2"), [])
        after = self.load("answer.json")
        self.assertLess(sum(len(lessons(week)) for week in after.values()), sum(len(lessons(week)) for week in answer.values()))

    def test_copy_monday_to_working_days(self):
        """«Как в понедельник»: время понедельника переносится во все будни с уроками, выходные не трогаются."""
        grid = self.grid()
        saturday = list(grid[5])
        grid[1] = ["16:30 - 18:00", "18:10 - 19:40", "19:50 - 21:20"]
        self.ok("setGrid", days=grid)
        self.assertEqual(self.grid()[1][0], "16:30 - 18:00")

        self.ok("copyMonday")
        grid = self.grid()
        self.assertEqual(grid[1], grid[0])
        self.assertEqual(grid[5], saturday)

    def test_limits(self):
        """Ограничения: число читается терпимо («1 5» = 15), курсов на преподавателя не меньше 1,
        мусор и неизвестный ключ отклоняются.
        """
        self.ok("setLimit", key="max_courses_per_teacher", value="1 5")
        self.assertEqual(self.state()["limits"]["max_courses_per_teacher"], 15)
        self.ok("setLimit", key="max_courses_per_teacher", value="0")
        self.assertEqual(self.state()["limits"]["max_courses_per_teacher"], 1)
        self.refused("setLimit", key="max_teachers_per_course", value="0")

        self.refused("setLimit", key="max_courses_per_teacher", value="много")
        self.refused("setLimit", key="iterations", value="5")

    def test_pair_table_cycles_and_is_symmetric(self):
        """Клик по клетке пар: можно -> нежелательно -> нельзя -> можно, одинаково в обе стороны."""
        pairs = lambda: self.state()["pairs"]
        first, second = "География", "Информатика"
        start = pairs()[first][second]
        seen = [start]

        for _ in range(3):
            self.ok("cyclePair", first=first, second=second)
            current = pairs()
            self.assertEqual(current[first][second], current[second][first])
            seen.append(current[first][second])

        self.assertEqual(seen[-1], start)
        self.assertEqual(set(seen), {"allowed", "soft", "hard"})

    def test_grid_shift_moves_pins_marks_and_lessons(self):
        """Очищена первая ячейка воскресенья: вопрос о потере урока; с force урок этой ячейки пропадает,
        а урок, закрепление и отметка из второй ячейки переезжают в первую; правило «в один день»
        не меняется, правило «в это время» сохраняет время; сохраняется версия «Перед: …».
        """
        self.ok("setPins", course=RUS_8_2, subject="Русский язык", slots=[[6, 1]])
        self.ok("savePenalty", penalty={"name": "Химия и биология", "template": "same_day", "weight": 5, "params": {"first": "Химия", "second": "Биология"}})
        self.ok("savePenalty", penalty={"name": "Воскресенье днём", "template": "time", "weight": 5,
                                        "params": {"target": "all", "days": [6], "times": ["11:40 - 13:10"]}})
        settings = self.load("settings.json")
        settings["teachers"]["Тюгалева"]["availability"]["2"] = {"free": [[6, 0]], "possible": [[6, 1]]}
        self.save("settings.json", settings)
        penalties_before = self.state()["penalties"]

        answer = self.load("answer.json")
        sunday = {name: [lesson for day, lesson, _ in lessons(week) if day == 6] for name, week in answer.items()}
        first = [name for name, slots in sunday.items() if 0 in slots]
        second = [name for name, slots in sunday.items() if 1 in slots]
        self.assertTrue(first and second)

        grid = self.state()["grid"]
        grid[6] = ["", grid[6][1]]

        body = self.ok("setGrid", days=grid)
        self.assertIn(translate("web.confirm_grid_remove").split("{")[0], body["confirm"])
        self.assertEqual(self.course(RUS_8_2)["pinned"], [[6, 1]])

        versions = self.versions()
        state = self.ok("setGrid", days=grid, force=True)["state"]

        self.assertEqual(state["grid"][6], ["11:40 - 13:10"])
        self.assertEqual(self.course(RUS_8_2)["pinned"], [[6, 0]])
        self.assertEqual(self.load("settings.json")["teachers"]["Тюгалева"]["availability"]["2"], {"free": [], "possible": [[6, 0]]})
        answer = self.load("answer.json")
        for name in second:
            self.assertIn(0, [lesson for day, lesson, _ in lessons(answer[name]) if day == 6], name)

        for name in first:
            self.assertFalse([lesson for day, lesson, _ in lessons(answer[name]) if day == 6], name)

        self.assertEqual(state["penalties"], penalties_before)
        self.assertEqual(len(self.versions()), len(versions) + 1)

    def test_pair_of_unknown_subject_is_refused(self):
        """Пара предметов с неизвестным предметом (устаревшая вкладка, ручной запрос) — общий отказ,
        settings.json не меняется (cyclePair проверяет оба предмета через requireSubjects).
        """
        before = self.raw("settings.json")

        for first, second in (("Латынь", "Химия"), ("Химия", "Латынь")):
            self.assertEqual(self.refused("cyclePair", first=first, second=second), translate("web.error.generic"))

        self.assertEqual(self.raw("settings.json"), before)

    def test_grid_change_losing_only_pins_saves_version(self):
        """Очищена ячейка, где нет уроков, но есть закрепление: вопрос «0 уроков, 1 закрепление»;
        с force — версия «Перед: изменение сетки», закрепление пропало.
        """
        answer = self.load("answer.json")
        self.assertFalse([name for name, value in answer.items() if (5, 2) in [(d, l) for d, l, _ in lessons(value)]])
        self.ok("setPins", course=RUS_8_2, subject="Русский язык", slots=[[5, 2]])
        grid = self.state()["grid"]
        grid[5][2] = ""

        body = self.ok("setGrid", days=grid)
        self.assertEqual(body["confirm"], translate("web.confirm_grid_remove").replace("{lessons}", "0").replace("{pins}", "1"))

        before = set(self.versionList())
        self.ok("setGrid", days=grid, force=True)

        after = self.versionList()
        self.assertEqual([after[key]["name"] for key in set(after) - before],
                         [translate("web.version.before").replace("{action}", translate("web.version.grid"))])
        self.assertEqual(self.course(RUS_8_2)["pinned"], [])

    def test_time_rule_follows_time_only_when_it_is_gone_everywhere(self):
        """Правило «Не ставить уроки в выбранное время»: время поменяли только в понедельнике — правило хранит старое
        (оно осталось в других днях); поменяли во всех днях — правило переходит на новое.
        """
        self.ok("savePenalty", penalty={"name": "Ранний урок", "template": "time", "weight": 5,
                                        "params": {"target": "all", "days": [0], "times": ["16:20 - 17:50"]}})

        def rule():
            return next(item for item in self.state()["penalties"] if item["name"] == "Ранний урок")["params"]["times"]

        grid = self.state()["grid"]
        grid[0][0] = "16:00 - 17:30"
        self.assertNotIn("confirm", self.ok("setGrid", days=grid))
        self.assertEqual(self.state()["grid"][0][0], "16:00 - 17:30")
        self.assertEqual(rule(), ["16:20 - 17:50"])

        grid = [[("16:00 - 17:30" if time == "16:20 - 17:50" else time) for time in day] for day in self.state()["grid"]]
        self.assertNotIn("confirm", self.ok("setGrid", days=grid))
        self.assertEqual(rule(), ["16:00 - 17:30"])


class JointGridTests(RealProjectCase):
    """Сетка, когда «ЕГЭ основной» Потока 2 идёт вместе с Потоком 1 (замечание проверки): общий урок
    курса-копии и его источника в вопросе о потерянных уроках — один урок. Проект — ``builders.jointProject``.
    """
    NAME = "__test_settings_joint__"

    def test_shared_lesson_is_lost_once(self):
        """Поток 1 ещё не начался. Из сетки убран пн 1-й урок: там Математика обоих уровней Потока 1
        и копия Математики в Потоке 2 — в вопросе 2 урока, а не 3; с force копия теряет урок вместе
        с источником.
        """
        settings, answer = jointProject()

        shiftStream(settings, 1, "2026-10-12")

        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        grid = [list(day) for day in self.state()["grid"]]
        grid[0][0] = ""

        body = self.ok("setGrid", days=grid)

        self.assertEqual(body["confirm"], translate("web.confirm_grid_remove").replace("{lessons}", "2").replace("{pins}", "0"))

        self.ok("setGrid", days=grid, force=True)
        answer = self.load("answer.json")
        math = jointCourse(1, "Математика")
        self.assertEqual(answer[jointCourse(2, "Математика")], answer[math])
        self.assertEqual(len(lessons(answer[math])), 1)

    def test_started_copy_refusal_names_only_its_course(self):
        """Поток 1 ещё не начался, Поток 2 уже идёт, его «ЕГЭ основной» присоединяется к Потоку 1.
        Из сетки убран пн 1-й урок: общая Математика — урок идущей копии, поэтому отказ. В отказе
        назван только курс Потока 2: ученики Потока 1 ещё не ходят, и общий урок не повторяется.
        """
        settings, answer = jointProject()

        shiftStream(settings, 1, "2026-12-01")
        shiftStream(settings, 2, "2026-09-01")

        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        grid = [list(day) for day in self.state()["grid"]]
        grid[0][0] = ""

        error = self.refused("setGrid", days=grid)

        self.assertEqual(error, translate("web.error.grid_started").replace("{courses}", f"• {jointCourse(2, 'Математика')}"))
