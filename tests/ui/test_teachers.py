"""Вкладка «Преподаватели»: карточка, поиск и фильтр, отметки удобства, курс «ведёт», урок «уже идёт»,
новый преподаватель и прокрутка списка к нему."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import re
import urllib.parse

from tests.builders import markCannot
from tests.real_project import CHEMIST
from tests.ui.base import UICase, expect, t

# Где пункт списка относительно окна самого списка: {top, bottom} пункта и списка
VISIBLE_JS = """() => {
    const item = document.querySelector('.list .list-item.active');
    const list = item.closest('.list');
    const [a, b] = [item.getBoundingClientRect(), list.getBoundingClientRect()];
    return {item: [a.top, a.bottom], list: [b.top, b.bottom], scroll: list.scrollTop, page: window.scrollY};
}"""


class TeachersTest(UICase):
    """Карточка преподавателя и правки, которые с неё уходят на сервер."""

    def details(self, name, stage):
        """Подробности о преподавателе так, как их получает страница."""
        address = f"/api/project/{self.NAME}/teacher?name={urllib.parse.quote(name)}&stage={urllib.parse.quote(stage)}"
        return self.client.get(address).get_json()

    def choose(self, name):
        """Выбирает преподавателя в списке слева и ждёт его карточку с таблицей удобства."""
        self.page.locator(".list .list-item", has_text=name).click()
        expect(self.page.locator(".teacher-head h2")).to_have_text(name)
        expect(self.page.locator(".teacher-week table.week")).to_be_visible()

    def shownStage(self):
        """Ключ этапа, выбранного в карточке «Когда удобно»."""
        label = self.page.locator(".teacher-week .stage-tab.active .t-name").inner_text()
        return next(stage["key"] for stage in self.state()["stages"] if stage["label"] == label)

    def test_teacher_card(self):
        """Клик по преподавателю: его имя и предметы в шапке, пункт списка выделен, есть таблица удобства."""
        self.open("teachers")
        teacher = self.state()["teachers"][3]
        self.choose(teacher["name"])

        expect(self.page.locator(".teacher-head .badge.subject")).to_have_text(teacher["subjects"])
        expect(self.page.locator(".list .list-item.active .title")).to_have_text(teacher["name"])
        # Карточки курсов — по одной на каждый предмет, по которому у него есть курсы
        subjects = [item["subject"] for item in self.details(teacher["name"], self.shownStage())["subjects"]]
        expect(self.page.locator(".content .card .card-head h2 .badge.subject")).to_have_text(subjects)

    def test_search_and_subject_filter(self):
        """Поиск по имени и фильтр по предмету сужают список; число «показано / всего» в шапке."""
        self.open("teachers")
        teachers = self.state()["teachers"]
        listCard = self.page.locator(".card", has=self.page.locator(".list"))

        self.page.locator("input[type=search]").fill("Дуск")
        expect(listCard.locator(".list-item")).to_have_count(1)
        expect(listCard.locator(".card-head .badge")).to_have_text(f"1 / {len(teachers)}")
        # Фокус остаётся в поле поиска, можно печатать дальше
        self.assertEqual(self.page.evaluate("document.activeElement.type"), "search")

        self.page.locator("input[type=search]").fill("")
        chemists = [teacher["name"] for teacher in teachers if "Химия" in teacher["subjects"]]
        self.page.locator(".card-body select").first.select_option("Химия")
        expect(listCard.locator(".list-item .title")).to_have_text(chemists)
        expect(self.page.locator(".teacher-head h2")).to_have_text(chemists[0])

    def test_search_without_results_hides_teacher_card(self):
        """Поиск никого не нашёл: справа нет карточки ранее выбранного преподавателя, а есть
        «Никого не найдено» с подсказкой, что делать; очистка поиска возвращает карточку.
        """
        self.open("teachers")
        expect(self.page.locator(".teacher-head h2")).to_have_count(1)

        self.page.locator("input[type=search]").fill("Ъъъ")
        expect(self.page.locator(".list-item")).to_have_count(0)
        expect(self.page.locator(".teacher-head")).to_have_count(0)
        expect(self.page.get_by_text(t("web.teachers.nothing_found_hint"))).to_be_visible()
        expect(self.page.get_by_text(t("web.nothing_found"))).to_have_count(2)

        self.page.locator("input[type=search]").fill("")
        expect(self.page.locator(".teacher-head h2")).to_have_count(1)

    def test_search_inside_subject_filter_finds_nobody(self):
        """Фильтр по предмету и поиск вместе: преподаватель другого предмета не находится —
        в шапке списка «0 / всего», справа «Никого не найдено»; фильтр «Все предметы»
        возвращает и его, и его карточку."""
        self.open("teachers")
        teachers = self.state()["teachers"]
        chemists = [item["name"].lower() for item in teachers if "Химия" in item["subjects"]]
        # Фамилия преподавателя не химии, которой нет ни у одного химика
        surname = next(item["name"].split()[0] for item in teachers
                       if "Химия" not in item["subjects"] and not any(item["name"].split()[0].lower() in name for name in chemists))
        listCard = self.page.locator(".card", has=self.page.locator(".card-body select"))

        self.page.locator(".card-body select").first.select_option("Химия")
        self.page.locator("input[type=search]").fill(surname)
        expect(listCard.locator(".list-item")).to_have_count(0)
        expect(listCard.locator(".card-head .badge")).to_have_text(f"0 / {len(teachers)}")
        expect(self.page.locator(".teacher-head")).to_have_count(0)
        expect(self.page.get_by_text(t("web.teachers.nothing_found_hint"))).to_be_visible()

        self.page.locator(".card-body select").first.select_option("")
        expect(listCard.locator(".list-item .title", has_text=surname).first).to_be_visible()
        expect(self.page.locator(".teacher-head h2")).to_contain_text(surname)

    def test_availability_mark_cycles(self):
        """Клик по клетке «Когда удобно»: удобно → может → не может → удобно, отметки сохраняются по этапу."""
        self.open("teachers")
        name = self.state()["teachers"][0]["name"]
        self.choose(name)
        stage = self.shownStage()
        before = self.details(name, stage)

        cells = self.page.locator(".teacher-week td.state-cell")
        index = next(i for i in range(cells.count()) if cells.nth(i).locator("button.state.ok").count())
        cell = lambda: cells.nth(index).locator("button.state")

        self.act(lambda: cell().click())
        after = self.details(name, stage)
        added = [slot for slot in after["possible"] if slot not in before["possible"]]
        self.assertEqual(len(added), 1)
        expect(cell()).to_have_class(re.compile(r"(^| )warn( |$)"))
        expect(cell()).to_contain_text(t("menu.main.tab.teachers.possible"))

        self.act(lambda: cell().click())
        after = self.details(name, stage)
        self.assertIn(added[0], after["busy"])
        self.assertNotIn(added[0], after["possible"])
        expect(cell()).to_contain_text(t("menu.main.tab.teachers.busy"))

        self.act(lambda: cell().click())
        after = self.details(name, stage)
        self.assertEqual((after["busy"], after["possible"]), (before["busy"], before["possible"]))
        expect(cell()).to_contain_text(t("menu.main.tab.teachers.free"))

    def test_course_becomes_teaches(self):
        """Курс «может вести» → клик → «ведёт»: преподаватель закреплён за курсом (как на «Курсах»)."""
        self.open("teachers")
        state = self.state()
        answer = state["answer"]
        stage = state["stages"][-1]["key"]
        name, course = next(
            (teacher["name"], item["name"])
            for teacher in state["teachers"]
            for subject in self.details(teacher["name"], stage)["subjects"]
            for item in subject["courses"]
            if item["state"] == "may" and item["name"] not in answer
        )
        self.choose(name)

        button = self.page.locator(f"button.state[title$='{course}']")
        expect(button).to_contain_text(t("web.state.may_teach"))
        self.act(lambda: button.click())

        expect(button).to_contain_text(t("web.state.teaches"))
        self.assertEqual(self.course(course)["assigned"], [name])

    def test_add_teacher(self):
        """«Добавить преподавателя»: имя и предмет — он появляется в списке выбранным и в файле проекта."""
        self.open("teachers")
        count = len(self.state()["teachers"])

        self.page.locator("button", has_text=t("menu.main.tab.teachers.add_teacher")).first.click()
        dialog = self.page.locator(".dialog")
        dialog.get_by_placeholder(t("web.teacher_name_placeholder")).fill("Тестова Анна")
        dialog.locator("label.check", has_text="Химия").locator("input").check()
        self.act(lambda: self.dialogButton(t("dialog.add_teacher.allow")).click())

        expect(dialog).to_have_count(0)
        expect(self.page.locator(".teacher-head h2")).to_have_text("Тестова Анна")
        teachers = self.state()["teachers"]
        self.assertEqual(len(teachers), count + 1)
        self.assertEqual(next(item for item in teachers if item["name"] == "Тестова Анна")["subjects"], ["Химия"])

    def test_delete_teacher_with_lessons(self):
        """Удаление преподавателя с уроками: вопрос с числом уроков; после «Удалить» его нет в списке,
        а его уроки остались без преподавателя."""
        self.open("teachers")
        name = self.state()["teachers"][0]["name"]
        self.choose(name)
        taught = [course["name"] for course in self.state()["courses"] if name in course["scheduled"]]
        self.assertTrue(taught)

        self.act(lambda: self.page.locator(".teacher-head button.danger").click(), idle=False)
        expect(self.page.locator(".dialog")).to_contain_text(name)
        self.act(lambda: self.dialogButton(t("web.common.delete")).click())

        expect(self.page.locator(".list .list-item", has_text=name)).to_have_count(0)
        expect(self.page.locator(".teacher-head h2")).not_to_have_text(name)
        state = self.state()
        self.assertNotIn(name, [teacher["name"] for teacher in state["teachers"]])
        for course in taught:
            self.assertNotIn(name, self.course(course)["scheduled"])

    def test_started_own_lessons_are_not_called_pinned(self):
        """Урок преподавателя в уже идущем курсе подписан «уже идёт» (с замком), а не «закреплён»,
        и в легенде есть «уже идёт». В проекте таких уроков в этапах с отметками нет, поэтому
        ответ сервера /teacher дополняется одним таким уроком в свободном месте недели."""
        def withStartedLesson(route):
            data = route.fetch().json()
            used = {(item[0], item[1]) for key in ("clashes", "commitments", "own") for item in data.get(key, [])}
            grid = self.state()["grid"]
            day, lesson = next((day, lesson) for day, times in enumerate(grid) for lesson in range(len(times)) if (day, lesson) not in used)
            data["own"] = [*data.get("own", []), [day, lesson, "Поток 1 — ОГЭ — Химия", True]]
            route.fulfill(json=data)

        self.page.route("**/teacher?*", withStartedLesson)
        self.open("teachers")
        expect(self.page.locator(".teacher-week table.week")).to_be_visible()

        cells = self.page.locator(".teacher-week td.state-cell .state.static.info", has_text=t("web.state.started"))
        expect(cells).to_have_count(1)
        expect(cells.locator(".icon")).to_have_count(1)
        expect(self.page.locator(".teacher-week .legend .badge", has_text=t("web.state.started"))).to_have_count(1)


    def test_cannot_under_started_lesson_is_removed_by_click(self):
        """Под своим уроком идущего курса осталось «не может» (поставили до начала курса): клетка
        «уже идёт» жёлтая и подписана «не может», в легенде — web.teachers.started_cannot_legend.
        Щелчок снимает отметку: клетка снова синяя «уже идёт», пометки в легенде нет. Урок идущего
        курса подставляется в ответ сервера /teacher (как в test_started_own_lessons_are_not_called_pinned),
        а «не может» стоит в settings.json по-настоящему.
        """
        name = CHEMIST
        self.open("teachers")
        self.choose(name)
        stage = self.shownStage()
        data = self.details(name, stage)
        used = {(item[0], item[1]) for key in ("clashes", "commitments", "own", "busy", "possible") for item in data.get(key, [])}
        grid = self.state()["grid"]
        day, lesson = next((day, lesson) for day, times in enumerate(grid) for lesson in range(len(times)) if (day, lesson) not in used)
        settings = self.load("settings.json")
        markCannot(settings, name, stage, (day, lesson))
        self.save("settings.json", settings)

        def withStartedLesson(route):
            body = route.fetch().json()
            body["own"] = [*body.get("own", []), [day, lesson, "Поток 1 — ОГЭ — Химия", True]]
            route.fulfill(json=body)

        self.page.route("**/teacher?*", withStartedLesson)
        self.open("teachers")
        self.choose(name)
        # Строки таблицы — время уроков всей недели по порядку, столбцы — дни, в которые есть уроки (weekTable)
        row = sorted({time for times in grid for time in times}).index(grid[day][lesson])
        column = [number for number, times in enumerate(grid) if times].index(day)
        cell = self.page.locator(".teacher-week table.week tbody tr").nth(row).locator("td").nth(column)
        legend = self.page.locator(".teacher-week .legend")

        expect(cell.locator(".state.static.warn")).to_contain_text(t("web.state.started"))
        expect(cell).to_contain_text(t("menu.main.tab.teachers.busy"))
        expect(legend).to_contain_text(t("web.teachers.started_cannot_legend"))

        with self.page.expect_response(lambda response: "/action" in response.url):
            cell.locator(".state").click()

        expect(cell.locator(".state.static.info")).to_contain_text(t("web.state.started"))
        expect(cell).not_to_contain_text(t("menu.main.tab.teachers.busy"))
        expect(legend).not_to_contain_text(t("web.teachers.started_cannot_legend"))
        self.assertNotIn([day, lesson], self.load("settings.json")["teachers"][name]["availability"][stage]["free"])

        # Тексты взяты из ru.hjson, а не показаны ключами
        for key in ("web.teachers.started_cannot_hint", "web.teachers.started_cannot_legend", "web.teachers.started_cannot_legend_hint"):
            self.assertNotEqual(t(key), key, f"в ru.hjson нет текста {key}")

class TeacherListTest(UICase):
    """Прокрутка списка преподавателей; окно ниже обычного, чтобы список был длиннее своего окна."""
    VIEWPORT = {"width": 1400, "height": 700}

    def test_new_teacher_is_scrolled_into_list(self):
        """Добавленный преподаватель встаёт в конец длинного списка: список (он прокручивается
        сам, а не страница) докручивается до него, страница при этом не сдвигается."""
        self.open("teachers")
        self.page.locator("button", has_text=t("menu.main.tab.teachers.add_teacher")).first.click()
        dialog = self.page.locator(".dialog")
        dialog.get_by_placeholder(t("web.teacher_name_placeholder")).fill("Яшина Тест")
        dialog.locator("label.check", has_text="Химия").locator("input").check()
        self.act(lambda: self.dialogButton(t("dialog.add_teacher.allow")).click())

        expect(self.page.locator(".list .list-item.active .title")).to_have_text("Яшина Тест")
        place = self.page.evaluate(VISIBLE_JS)
        # Список длиннее своего окна: без прокрутки новый пункт был бы за нижним краем
        self.assertGreater(place["scroll"], 0, place)
        self.assertGreaterEqual(place["item"][0], place["list"][0] - 1, place)
        self.assertLessEqual(place["item"][1], place["list"][1] + 1, place)
        self.assertEqual(place["page"], 0, place)

    def test_manual_list_scroll_is_kept(self):
        """Обычная перерисовка (тот же выбранный преподаватель) не дёргает список обратно к нему."""
        self.open("teachers")
        expect(self.page.locator(".list .list-item.active")).to_have_count(1)
        self.page.locator(".list").evaluate("(list) => { list.scrollTop = list.scrollHeight; }")
        bottom = self.page.locator(".list").evaluate("(list) => list.scrollTop")
        self.assertGreater(bottom, 0)

        self.page.evaluate("() => render()")
        self.assertEqual(self.page.locator(".list").evaluate("(list) => list.scrollTop"), bottom)
