"""Модальные окна страницы (dialog() в src/web/static/ui.js): окно поверх окна и клавиша Esc,
в том числе при раскрытом выпадающем списке."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

from tests.ui.base import UICase, expect


class DialogsTest(UICase):
    """Окно над окном: так бывает, когда сервер задаёт вопрос «точно?» (confirm) на действие из
    открытого окна — например, закрепление времени в окне «День и время» (setPins)."""

    def test_escape_closes_only_the_top_dialog(self):
        """Esc закрывает только верхнее окно — как его «Отмена»; нижнее остаётся открытым
        с тем, что в нём уже выбрано, и закрывается следующим Esc."""
        self.open("classes")
        self.page.evaluate("""() => {
            window.lower = dialog("Нижнее окно", h("p", {}, "текст"), [["Готово", true, "primary"]]);
            window.upper = confirmDialog("Верхнее окно");
        }""")
        dialogs = self.page.locator(".dialog")
        expect(dialogs).to_have_count(2)

        self.page.keyboard.press("Escape")
        expect(dialogs).to_have_count(1)
        expect(dialogs.locator("h2")).to_have_text("Нижнее окно")
        # Верхнее окно ответило «нет ответа» (null), как при клике по затемнению
        self.assertIsNone(self.page.evaluate("() => window.upper"))

        self.page.keyboard.press("Escape")
        expect(dialogs).to_have_count(0)
        self.assertIsNone(self.page.evaluate("() => window.lower"))

    def test_escape_on_open_list_closes_only_the_list(self):
        """Esc при раскрытом выпадающем списке в окне закрывает только список, окно остаётся с тем, что
        в нём выбрано; следующий Esc закрывает окно. Раскрытый список в оформлении программы (app.css,
        «настраиваемый select») — часть страницы, и Esc доходит до окна (ui.selectOpen)."""
        self.open("classes")
        self.page.evaluate("""() => {
            window.answer = dialog("Окно со списком", select([["a", "Первый"], ["b", "Второй"]], "a", () => {}), [["Готово", true, "primary"]]);
        }""")
        dialogs = self.page.locator(".dialog")
        field = dialogs.locator("select")
        expect(dialogs).to_have_count(1)

        field.click()
        opened = field.evaluate("(select) => { try { return select.matches(':open'); } catch { return null; } }")

        if opened is None:
            self.skipTest("the browser has no :open pseudo-class")

        self.assertTrue(opened)
        self.page.keyboard.press("Escape")
        expect(dialogs).to_have_count(1)
        self.assertFalse(field.evaluate("(select) => select.matches(':open')"))

        self.page.keyboard.press("Escape")
        expect(dialogs).to_have_count(0)
        self.assertIsNone(self.page.evaluate("() => window.answer"))
