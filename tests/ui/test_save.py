"""Вкладка «Версии»: сохранить версию, вернуться к ней, удалить; число уроков «Сейчас в расписании»."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
import re

from tests.ui.base import UICase, expect, t


class VersionsTest(UICase):
    """Версии проекта с вкладки «Версии»."""

    def row(self, name):
        """Строка таблицы версий с именем name."""
        return self.page.locator("table.data tbody tr", has=self.page.locator("td b", has_text=name))

    def save(self, name, comment=""):
        """Сохраняет версию с вкладки и ждёт её строку в таблице."""
        self.page.locator(".card", has_text=t("web.save.new")).locator("input").fill(name)
        self.page.locator("textarea").fill(comment)
        self.act(lambda: self.page.locator("button", has_text=t("menu.main.tab.save.save")).click())
        expect(self.row(name)).to_be_visible()

    def test_save_version(self):
        """«Сохранить версию»: строка с именем, комментарием и числом уроков; папка версии на диске."""
        self.open("save")
        before = self.state()

        self.save("Проверка", "до опытов")

        versions = self.state()["versions"]
        self.assertEqual(len(versions), len(before["versions"]) + 1)
        version = next(item for item in versions if item["name"] == "Проверка")
        self.assertEqual((version["comment"], version["lessons"]), ("до опытов", before["lessons"]))
        self.assertTrue(os.path.isdir(f"{self.folder}/versions/{version['id']}"))
        expect(self.row("Проверка").locator("td").nth(4)).to_have_text("до опытов")
        expect(self.row("Проверка").locator("td").nth(3)).to_have_text(str(before["lessons"]))
        expect(self.page.locator(".nav-item", has_text=t("menu.main.tab.save")).locator(".count")).to_have_text(str(len(versions)))

    def test_save_version_without_name(self):
        """Пустое имя: версию называет сервер — «Версия от ДД.ММ.ГГГГ ЧЧ:ММ» (в поле это видно подсказкой)."""
        self.open("save")
        field = self.page.locator(".card", has_text=t("web.save.new")).locator("input")
        expect(field).to_have_attribute("placeholder", re.compile(rf"^{re.escape(t('menu.main.tab.save.default_name'))} \d\d\.\d\d\.\d{{4}} \d\d:\d\d$"))
        before = {item["id"] for item in self.state()["versions"]}

        self.act(lambda: self.page.locator("button", has_text=t("menu.main.tab.save.save")).click())

        added = [item for item in self.state()["versions"] if item["id"] not in before]
        self.assertEqual(len(added), 1)
        self.assertRegex(added[0]["name"], rf"^{re.escape(t('menu.main.tab.save.default_name'))} \d\d\.\d\d\.\d{{4}} \d\d:\d\d$")
        expect(self.row(added[0]["name"])).to_be_visible()

    def test_restore_version(self):
        """«Вернуться к этой версии»: изменения после версии отменяются, прежнее состояние
        само сохраняется версией."""
        self.open("save")
        self.save("Исходная")
        self.apiAct("cyclePair", first="География", second="Химия")
        self.assertEqual(self.state()["pairs"]["География"]["Химия"], "soft")
        count = len(self.state()["versions"])
        self.page.reload()

        restore = self.page.locator("button", has_text=t("menu.main.tab.save.restore"))
        expect(restore).to_be_disabled()
        self.row("Исходная").click()
        expect(self.row("Исходная")).to_have_class("clickable selected")
        restore.click()
        expect(self.page.locator(".dialog")).to_contain_text("Исходная")
        self.act(lambda: self.dialogButton(t("web.restore_yes")).click())

        self.toast(t("web.restored"))
        state = self.state()
        self.assertEqual(state["pairs"]["География"]["Химия"], "allowed")
        self.assertEqual(len(state["versions"]), count + 1)

    def test_delete_version(self):
        """«Удалить версию» после подтверждения убирает строку и папку версии."""
        self.open("save")
        self.save("Лишняя")
        version = next(item for item in self.state()["versions"] if item["name"] == "Лишняя")

        self.row("Лишняя").click()
        self.page.locator("button", has_text=t("menu.main.tab.save.delete")).click()
        self.act(lambda: self.dialogButton(t("web.common.delete")).click())

        expect(self.row("Лишняя")).to_have_count(0)
        self.assertNotIn("Лишняя", [item["name"] for item in self.state()["versions"]])
        self.assertFalse(os.path.exists(f"{self.folder}/versions/{version['id']}"))

    def test_versions_lessons_badge(self):
        """«Сейчас в расписании»: число уроков стоит после двоеточия (без «22 уроков»)."""
        self.open("save")
        lessons = self.state()["lessons"]
        badge = self.page.locator(".card", has_text=t("web.save.now")).locator(".badge.accent")
        expect(badge).to_have_text(t("web.view.lessons_count_all").replace("{count}", str(lessons)))
