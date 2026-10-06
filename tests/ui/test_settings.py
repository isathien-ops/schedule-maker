"""Вкладка «Настройки»: сетка времени, ограничение курсов, пары предметов по кругу."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import time

from src.web import build
from tests.ui.base import UICase, expect, t


class SettingsTest(UICase):
    """Правки «Настроек» уходят на сервер и видны в файлах проекта."""

    def cell(self, day, lesson):
        """Поле сетки времени: день day (0 — понедельник), урок lesson."""
        return self.page.locator(f"table.times tr[data-day='{day}'] input").nth(lesson)

    def test_add_lesson_time_to_grid(self):
        """Новое время в пустой ячейке воскресенья сохраняется в сетку проекта (время приводится к виду «ЧЧ:ММ - ЧЧ:ММ»)."""
        self.open("settings")
        before = self.state()["grid"]
        self.assertEqual(len(before[6]), 2)

        field = self.cell(6, 2)
        field.fill("13:20-14:50")
        self.act(lambda: field.press("Tab"))

        grid = self.state()["grid"]
        self.assertEqual(grid[6], before[6] + ["13:20 - 14:50"])
        self.assertEqual(grid[:6], before[:6])
        expect(self.cell(6, 2)).to_have_value("13:20 - 14:50")

    def test_two_quick_edits_both_saved(self):
        """Две правки подряд (вторая — пока первая идёт на сервер) обе попадают в сетку."""
        self.open("settings")

        first, second = self.cell(6, 2), self.cell(6, 3)
        first.fill("13:20 - 14:50")
        first.press("Tab")
        second.fill("15:00 - 16:10")
        second.press("Tab")
        self.idle()

        self.assertEqual(self.state()["grid"][6][2:], ["13:20 - 14:50", "15:00 - 16:10"])

    def test_wrong_time_is_refused(self):
        """Непонятное время — сообщение об ошибке, сетка на сервере не меняется, поле снова пустое."""
        self.allowRefusals()
        self.open("settings")
        before = self.state()["grid"]

        field = self.cell(6, 2)
        field.fill("когда-нибудь")
        self.act(lambda: field.press("Tab"))

        self.toast(t("menu.main.tab.settings.grid_invalid"))
        self.assertEqual(self.state()["grid"], before)
        expect(self.cell(6, 2)).to_have_value("")

    def test_courses_per_teacher_limit(self):
        """Поле «сколько курсов на преподавателя» сохраняет число; на «Запуске» правило показывает его."""
        self.open("settings")
        field = self.page.locator(".fields input[type=number]")
        field.fill("4")
        self.act(lambda: field.press("Tab"))

        self.assertEqual(self.state()["limits"]["max_courses_per_teacher"], 4)
        self.tab("run")
        expect(self.page.locator(".rules")).to_contain_text("4")

    def test_subject_pair_cycles(self):
        """Клетка пары предметов по кругу: можно → нежелательно → нельзя → можно; зеркальная клетка
        и файл проекта меняются вместе с ней."""
        self.open("settings")
        first, second = "География", "Химия"
        self.assertEqual(self.state()["pairs"][first][second], "allowed")

        button = self.page.locator(f"table.pairs button[title^='{first} + {second}:']")
        mirror = self.page.locator(f"table.pairs button[title^='{second} + {first}:']")

        for expected in ("soft", "hard", "allowed"):
            self.act(lambda: button.click())
            pairs = self.state()["pairs"]
            self.assertEqual((pairs[first][second], pairs[second][first]), (expected, expected))
            expect(button).to_have_class(f"pair {expected}")
            expect(mirror).to_have_class(f"pair {expected}")
            expect(button).to_have_attribute("title", f"{first} + {second}: {t(f'menu.main.tab.settings.pair_{expected}')}")

    def test_diagonal_pair_is_disabled(self):
        """Предмет сам с собой — неактивная клетка «—»."""
        self.open("settings")
        cells = self.page.locator("table.pairs button.pair.self")
        expect(cells).to_have_count(len(self.state()["subjects"]))
        expect(cells.first).to_be_disabled()

    def test_settings_locked_while_building(self):
        """Пока идёт сборка, сетка, «Сделать все рабочие дни как понедельник», ограничение и пары предметов
        закрыты, сверху — подпись почему. Сборка кончилась — страница сама перерисовывается, всё снова доступно."""
        build.JOBS[self.NAME] = {"stage": "2", "keep": False, "number": 1, "total": 1, "saved": 0, "repeats": 0, "stopped": False,
                                 "running": True, "started": time.time(), "finished": None, "log": [], "process": None,
                                 "fake": True}
        self.open("settings")
        main = self.page.locator(".content")
        controls = main.locator("table.times input, .card-foot button, .fields input, table.pairs button.pair:not(.self)")
        count = len(self.state()["grid"]) * self.state()["maxLessons"] + 2 + len(self.state()["subjects"]) * (len(self.state()["subjects"]) - 1)

        expect(main.locator(".build-note")).to_have_text(t("web.run.locked"))
        expect(controls).to_have_count(count)
        expect(main.locator("table.times input:disabled, .card-foot button:disabled, .fields input:disabled, table.pairs button.pair:disabled:not(.self)")).to_have_count(count)

        build.JOBS[self.NAME]["running"] = False
        expect(main.locator(".build-note")).to_have_count(0)
        expect(main.locator("table.times input:enabled, .card-foot button:enabled, .fields input:enabled, table.pairs button.pair:enabled")).to_have_count(count)
