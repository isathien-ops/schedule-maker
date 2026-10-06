"""Вкладка «Расписание»: все 6 режимов просмотра, карточки «требует внимания» (в том числе
«Нужен ещё преподаватель»), окно выгрузки."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import collections
import re

from src.web.project import lessonsText
from tests.real_project import lessons as lessonsOf
from tests.ui.base import UICase, expect, plain, t

CARDS_JS = """() => [...document.querySelectorAll('.sticky-card .lesson')].map((card) => [
    card.querySelector('.l-tag')?.textContent ?? '', card.querySelector('.l-title').textContent,
    card.querySelector('.l-meta')?.textContent ?? ''])"""


class ViewTest(UICase):
    """Принятое расписание проекта в разных разрезах."""

    def mode(self, key):
        """Выбирает режим просмотра."""
        self.page.locator(".view-list .card-head select").select_option(key)
        expect(self.page.locator(".view-list .card-head select")).to_have_value(key)

    def item(self, text):
        """Пункт списка слева с подписью ровно text."""
        return self.page.locator(".view-list .list-item", has=self.page.locator(".title", has_text=re.compile(rf"^{re.escape(text)}$")))

    def title(self):
        """Заголовок недели (что показано) без «i»."""
        return plain(self.page.locator(".sticky-card > .card-head h2").inner_text())

    def cards(self):
        return [tuple(plain(part) for part in card) for card in self.page.evaluate(CARDS_JS)]

    def lessons(self, keep):
        """Уроки принятого расписания, для которых keep(курс, ячейка) истинно: [(курс, день, урок, ячейка)]."""
        answer = self.state()["answer"]
        return [(name, day, lesson, cell) for name, week in answer.items() for day, lesson, cell in lessonsOf(week) if keep(name, cell)]

    def checkCount(self, expected, everywhere=False):
        """Число карточек на неделе и значок «Уроков в неделю» совпадают с ожидаемым."""
        expect(self.page.locator(".sticky-card .lesson")).to_have_count(expected)
        key = "web.view.lessons_count_all" if everywhere else "menu.main.tab.view.lessons_count"
        expect(self.page.locator(".sticky-card > .card-head .badge")).to_have_text(t(key).replace("{count}", str(expected)))

    def test_all_six_modes(self):
        """Вся школа, линейка, поток, курс, предмет, преподаватель: на неделе ровно нужные уроки
        с подписями своего режима."""
        self.open("view")
        state = self.state()
        courses = {course["name"]: course for course in state["courses"]}
        stages = {stage["key"]: stage for stage in state["stages"]}
        place = lambda name: t("stage.extra") if courses[name]["stage"] == "extra" else stages[courses[name]["stage"]]["label"]

        with self.subTest(mode="all"):
            self.mode("all")
            expect(self.page.locator(".view-list .list-item")).to_have_count(1)
            self.checkCount(len(self.lessons(lambda name, cell: True)), everywhere=True)

        with self.subTest(mode="line"):
            self.mode("line")
            self.page.locator(".view-list .list-item", has_text="ОГЭ").first.click()
            self.assertEqual(self.title(), "Поток 1 — ОГЭ")
            self.checkCount(len(self.lessons(lambda name, cell: courses[name]["stage"] == "1" and courses[name]["line"] == "ОГЭ")))
            # В линейке: предмет и полные имена преподавателей, без метки
            first = self.cards()[0]
            self.assertEqual(first[0], "")

        with self.subTest(mode="stream"):
            self.mode("stream")
            self.item("Поток 2").click()
            self.assertEqual(self.title(), "Поток 2")
            self.checkCount(len(self.lessons(lambda name, cell: name in stages["2"]["courses"])))

        with self.subTest(mode="course"):
            self.mode("course")
            name = self.title()
            self.assertIn(name, courses)
            expect(self.page.locator(".view-list .list-item.active")).to_have_text(courses[name]["subject"])
            self.checkCount(len(self.lessons(lambda course, cell: course == name)))

        with self.subTest(mode="subject"):
            self.mode("subject")
            self.item("Математика").click()
            self.assertEqual(self.title(), "Математика")
            expected = self.lessons(lambda name, cell: cell["subject"] == "Математика")
            self.checkCount(len(expected), everywhere=len({courses[name]["stage"] for name, *_ in expected}) > 1)

        with self.subTest(mode="teacher"):
            self.mode("teacher")
            counts = collections.Counter(teacher for _, _, _, cell in self.lessons(lambda name, cell: True) for teacher in cell.get("teachers", []))
            teacher = counts.most_common(1)[0][0]
            self.item(teacher).click()
            self.assertEqual(self.title(), teacher)
            expected = self.lessons(lambda name, cell: teacher in cell.get("teachers", []))
            self.checkCount(len(expected), everywhere=len({courses[name]["stage"] for name, *_ in expected}) > 1)
            # Подписи: поток (или «Доп. курсы»), предмет, линейка
            self.assertEqual(collections.Counter(self.cards()), collections.Counter(
                (place(name), cell["subject"], courses[name]["line"]) for name, _, _, cell in expected))

    def test_mode_and_choice_are_remembered(self):
        """Режим и выбранный пункт запоминаются после перезагрузки."""
        self.open("view")
        self.mode("stream")
        self.item("Поток 2").click()
        self.page.reload()
        expect(self.page.locator(".view-list .card-head select")).to_have_value("stream")
        expect(self.page.locator(".view-list .list-item.active .title")).to_have_text("Поток 2")

    def test_empty_stream(self):
        """Новый поток ещё не составлен: в режиме «поток» неделя пустая, без значка с числом
        уроков, а строка статуса говорит, что поток не составлен."""
        self.apiAct("newStream")
        stream = next(item for item in self.state()["stages"] if item["key"].isdigit() and not item["placed"] and not item["built"])
        self.open("view")
        self.mode("stream")
        self.item(stream["label"]).click()

        expect(self.page.locator(".sticky-card .status-line")).to_have_text(t("menu.main.tab.view.stage_not_built").replace("{name}", stream["label"]))
        expect(self.page.locator(".sticky-card .lesson")).to_have_count(0)
        expect(self.page.locator(".sticky-card > .card-head .badge")).to_have_count(0)
        self.assertEqual(self.title(), stream["label"])

    def test_attention_cards_open_course(self):
        """«Уроки без преподавателя» — по строке на курс; клик открывает курс на вкладке «Курсы»."""
        self.open("view")
        state = self.state()
        card = self.page.locator(".clash-card", has_text=t("web.view.no_teacher_title"))
        expect(card.locator("li")).to_have_count(len(state["noTeacher"]))

        name = state["noTeacher"][0][0]
        course = next(item for item in state["courses"] if item["name"] == name)
        section = next(item for item in state["sections"] if item["key"] == course["section"])
        card.locator("li").first.click()

        expect(self.page.locator(".page-head h1")).to_contain_text(t("menu.main.tab.classes"))
        expect(self.page.locator(".sticky-card > .card-head h2")).to_have_text(re.compile(rf"{section['name']} — {course['line']}i?$"))

    def test_export_dialog(self):
        """«Экспортировать»: окно со всеми выгрузками; «Скачать» отдаёт книгу по курсам."""
        self.open("view")
        self.page.locator(".page-head button", has_text=t("web.export_button")).click()
        dialog = self.page.locator(".dialog")
        expect(dialog.locator(".item-card")).to_have_count(6)

        with self.page.expect_download() as info:
            dialog.locator(".item-card").first.locator("button").click()

        self.assertEqual(info.value.suggested_filename, f"{self.NAME}-курсы.xlsx")
        self.dialogButton(t("web.common.close")).click()
        expect(dialog).to_have_count(0)

    def test_tight_staffing_shows_what_is_left(self):
        """«Нужен ещё преподаватель», жёлтое: «свободно» — то, что останется после ещё не
        поставленных уроков (14 − 6 = 8), а не всё свободное время (14)."""
        self.open("view")
        self.page.evaluate("""() => {
            S.state.staffing = [{subject: "Химия", level: "tight", needed: 6, free: 14, next: 10, teachers: []}];
            render();
        }""")
        row = self.page.locator(f".clash-list li[title='{t('web.view.staff_open')}']")
        expect(row).to_have_count(1)
        expect(row).to_contain_text(lessonsText(8))
        expect(row).not_to_contain_text(lessonsText(14))
        expect(row).to_contain_text(lessonsText(10))
