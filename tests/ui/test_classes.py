"""Вкладка «Курсы»: выбор потока и линейки, преподаватель курса, закрепление урока, число уроков."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import re

from tests.ui.base import UICase, expect, t

COURSE = "Поток 2 — ЕГЭ основной — Математика"


class ClassesTest(UICase):
    """Правки курса на «Курсах» и замочки у идущих курсов."""

    def test_stream_and_line_selection(self):
        """Поток и линейка выбираются кликом; таблица — ровно курсы этой линейки; выбор помнится после перезагрузки."""
        self.open("classes")
        self.pick("Поток 2", "ЕГЭ основной")

        state = self.state()
        section = next(item for item in state["sections"] if item["name"] == "Поток 2")
        expected = [course["subject"] for course in state["courses"] if course["section"] == section["key"] and course["line"] == "ЕГЭ основной"]
        expect(self.page.locator("table.data tbody tr td:first-child b")).to_have_text(expected)
        expect(self.page.locator(".dates-row .dates-title")).to_have_text("Поток 2")
        expect(self.page.locator(".dates-row input[type=date]").first).to_have_value(section["start"])

        # Число на чипе линейки — сколько в ней курсов
        expect(self.page.locator(".chip-row .chip.active .badge")).to_have_text(str(len(expected)))

        self.page.reload()
        expect(self.page.locator(".sticky-card > .card-head h2")).to_have_text(re.compile(r"Поток 2 — ЕГЭ основнойi?$"))

    def test_started_course_is_locked(self):
        """Идущий курс (поток 1): преподаватель, время и число уроков с замочком, без полей для правки."""
        self.open("classes")
        self.pick("Поток 1", "ЕГЭ основной")

        course = self.course("Поток 1 — ЕГЭ основной — Русский язык")
        self.assertTrue(course["locked"])
        row = self.row("Русский язык")
        expect(row.locator(".locked")).to_have_count(3)
        expect(row.locator("select")).to_have_count(0)
        expect(row.locator("input[type=number]")).to_have_count(0)
        expect(row.locator(".locked").first).to_contain_text(", ".join(course["scheduled"]))

    def test_set_course_teacher(self):
        """Выбор преподавателя в списке закрепляет его за курсом в файле проекта."""
        self.open("classes")
        self.pick("Поток 2", "ЕГЭ основной")
        before = self.course(COURSE)
        teacher = next(name for name in before["options"] if name not in before["assigned"])

        box = self.row("Математика").locator("select")
        expect(box).to_have_value(before["assigned"][0])
        self.act(lambda: box.select_option(teacher))

        self.assertEqual(self.course(COURSE)["assigned"], [teacher])
        expect(self.row("Математика").locator("select")).to_have_value(teacher)

        # Пустой пункт — «авто»: закрепление снимается
        self.act(lambda: self.row("Математика").locator("select").select_option(""))
        self.assertEqual(self.course(COURSE)["assigned"], [])

    def test_pin_lesson(self):
        """«День и время»: первый урок закрепляется на понедельник, первый час — значок с булавкой."""
        self.open("classes")
        self.pick("Поток 2", "ЕГЭ основной")
        state = self.state()
        self.assertEqual(self.course(COURSE)["pinned"], [])

        self.row("Математика").locator("td").nth(2).locator("button").click()
        dialog = self.page.locator(".dialog")
        expect(dialog).to_contain_text(COURSE)
        # По одному списку на урок недели
        expect(dialog.locator("select")).to_have_count(self.course(COURSE)["hours"])
        dialog.locator("select").first.select_option("0-0")
        self.act(lambda: self.dialogButton(t("web.common.save")).click())

        expect(dialog).to_have_count(0)
        self.assertEqual(self.course(COURSE)["pinned"], [[0, 0]])
        badge = self.row("Математика").locator("td").nth(2).locator(".badge.accent")
        expect(badge).to_have_text(f"{t('abbreviate.day.0')} {state['grid'][0][0].split(' - ')[0]}")
        expect(badge.locator("svg")).to_have_count(1)

    def test_pin_two_lessons_same_day_refused(self):
        """Два урока курса в один день закрепить нельзя: понятная ошибка, окно остаётся открытым."""
        self.allowRefusals()
        self.open("classes")
        self.pick("Поток 2", "ЕГЭ основной")

        self.row("Математика").locator("td").nth(2).locator("button").click()
        dialog = self.page.locator(".dialog")
        dialog.locator("select").nth(0).select_option("0-0")
        dialog.locator("select").nth(1).select_option("0-1")
        self.act(lambda: self.dialogButton(t("web.common.save")).click())

        self.toast(t("web.error.pins_same_day"))
        expect(dialog).to_be_visible()
        self.assertEqual(self.course(COURSE)["pinned"], [])

    def test_lesson_count(self):
        """Число уроков в неделю: новое значение сохраняется, окно «День и время» предлагает столько же уроков."""
        self.open("classes")
        self.pick("Поток 2", "ЕГЭ основной")
        self.assertEqual(self.course(COURSE)["hours"], 2)

        field = self.row("Математика").locator("input[type=number]")
        field.fill("1")
        self.act(lambda: field.press("Tab"))

        self.assertEqual(self.course(COURSE)["hours"], 1)
        expect(self.row("Математика").locator("input[type=number]")).to_have_value("1")
        self.row("Математика").locator("td").nth(2).locator("button").click()
        expect(self.page.locator(".dialog select")).to_have_count(1)

    def test_new_line_and_subject_in_empty_block(self):
        """Пустой блок «Майские марафоны»: заглушка «линеек нет»; «Линейка» создаёт линейку
        с отмеченным предметом, «Добавить предмет» — ещё один курс; всё в файле проекта."""
        self.open("classes")
        self.page.locator(".chip-row .stage-pill", has_text="Майские марафоны").click()
        expect(self.page.locator(".sticky-card .empty")).to_be_visible()
        expect(self.page.locator("button", has_text=t("menu.main.tab.classes.add_subject"))).to_be_disabled()

        self.page.locator(".card-head button", has_text=t("web.add_line_short")).click()
        dialog = self.page.locator(".dialog")
        dialog.locator(".form input").fill("ОГЭ")
        dialog.locator("label.check", has_text="Химия").locator("input").check()
        self.act(lambda: self.dialogButton(t("web.common.create")).click())

        expect(dialog).to_have_count(0)
        expect(self.page.locator(".sticky-card > .card-head h2")).to_have_text(re.compile(r"Майские марафоны — ОГЭi?$"))
        expect(self.page.locator("table.data tbody tr td:first-child b")).to_have_text(["Химия"])

        self.page.locator("button", has_text=t("menu.main.tab.classes.add_subject")).click()
        # Предлагаются только предметы, которых в линейке ещё нет
        expect(dialog.locator("option", has_text="Химия")).to_have_count(0)
        dialog.locator("select").select_option("Биология")
        self.act(lambda: self.dialogButton(t("web.common.add")).click())

        expect(self.page.locator("table.data tbody tr td:first-child b")).to_have_text(["Химия", "Биология"])
        may = [(course["line"], course["subject"]) for course in self.state()["courses"] if course["section"] == "may"]
        self.assertEqual(sorted(may), [("ОГЭ", "Биология"), ("ОГЭ", "Химия")])

    def test_new_stream(self):
        """Кнопка «Поток» добавляет поток 3 (копия последнего): он выбран, сообщение, курсы в проекте."""
        self.open("classes")
        streams = [item for item in self.state()["sections"] if not item["block"]]

        self.act(lambda: self.page.locator(".card-head button", has_text=t("web.add_stream_short")).click())

        self.toast(t("web.classes.stream_added").replace("{name}", f"{t('stage.stream')} 3"))
        expect(self.page.locator(".dates-row .dates-title")).to_have_text("Поток 3")
        state = self.state()
        self.assertEqual(len([item for item in state["sections"] if not item["block"]]), len(streams) + 1)
        self.assertTrue([course for course in state["courses"] if course["section"] == 3])
        expect(self.page.locator(".chip-row .stage-pill.active")).to_contain_text("Поток 3")
