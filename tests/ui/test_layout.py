"""Вид страницы: тёмная тема, прилипающие шапки при прокрутке (Курсы, Преподаватели, Расписание,
Предпросмотр), отсутствие горизонтальной прокрутки при ширине окна 1100, раскрытые выпадающие списки в оформлении программы."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

from tests.ui.base import TABS, UICase, expect, t

LIGHT, DARK = "rgb(244, 245, 247)", "rgb(14, 16, 20)"

# Прокручивает окно так, чтобы верх карточки ушёл на 200px выше окна, и меряет карточку, её шапку
# и первую ячейку строки заголовков таблицы внутри (если есть)
MEASURE_JS = """([card, head, cell]) => new Promise((done) => {
    const box = document.querySelector(card);
    window.scrollTo(0, box.getBoundingClientRect().top + window.scrollY + 200);
    requestAnimationFrame(() => requestAnimationFrame(() => {
        const rect = (selector) => { const item = selector && box.querySelector(selector); return item ? item.getBoundingClientRect() : null; };
        const own = box.getBoundingClientRect(), top = rect(head), th = rect(cell);
        done({scroll: window.scrollY, card: own.top, bottom: own.bottom, head: top.top, height: top.height, th: th ? th.top : null});
    }));
})"""


class LayoutTest(UICase):
    """Тема, прилипающие шапки и ширина страницы (проект с вариантами потока 2)."""
    VARIANTS_STAGE = "2"

    def background(self):
        return self.page.evaluate("getComputedStyle(document.body).backgroundColor")

    def test_dark_theme(self):
        """«Тёмная»: тёмный фон сразу и после перезагрузки (выбор хранится), все вкладки без ошибок;
        «Светлая» возвращает светлый фон."""
        self.open("settings")
        self.assertEqual(self.background(), LIGHT)

        self.page.locator(".sidebar .theme-switch button", has_text=t("web.theme.dark")).click()
        self.assertEqual(self.page.evaluate("document.documentElement.dataset.theme"), "dark")
        self.assertEqual(self.background(), DARK)
        self.assertEqual(self.page.evaluate("localStorage.getItem('schedule.theme')"), "dark")

        self.page.reload()
        expect(self.page.locator(".sidebar .theme-switch button[aria-checked=true]")).to_have_text(t("web.theme.dark"))
        self.assertEqual(self.background(), DARK)

        for tab in TABS:
            with self.subTest(tab=tab):
                self.tab(tab)
                self.assertEqual(self.background(), DARK)

        self.page.locator(".sidebar .theme-switch button", has_text=t("web.theme.light")).click()
        self.assertEqual(self.background(), LIGHT)

        # Стартовый экран — тот же выбор темы
        self.page.locator(".project-switch").click()
        expect(self.page.locator(".start-theme button[aria-checked=true]")).to_have_text(t("web.theme.light"))

    def test_auto_theme_follows_system(self):
        """«Авто» (по умолчанию): при тёмной теме системы страница тёмная, явный выбор «Светлая» сильнее."""
        self.newContext(self.VIEWPORT, color_scheme="dark")

        self.open("settings")
        expect(self.page.locator(".sidebar .theme-switch button[aria-checked=true]")).to_have_text(t("web.theme.auto"))
        self.assertEqual(self.background(), DARK)
        self.page.locator(".sidebar .theme-switch button", has_text=t("web.theme.light")).click()
        self.assertEqual(self.background(), LIGHT)

    def measure(self, card, head, cell=None):
        return self.page.evaluate(MEASURE_JS, [card, head, cell])

    def checkSticky(self, box, what):
        """Карточка ушла вверх, а её шапка стоит у верхнего края окна, строка дней таблицы — сразу под ней."""
        self.assertGreater(box["scroll"], 0, what)
        self.assertLess(box["card"], 0, what)
        self.assertGreater(box["bottom"], box["height"], what)
        self.assertAlmostEqual(box["head"], 0, delta=1, msg=what)

        if box["th"] is not None:
            self.assertAlmostEqual(box["th"], box["height"], delta=2, msg=what)

    def test_sticky_heads(self):
        """Прилипающие шапки при прокрутке: курсы линейки, преподаватель, неделя расписания и варианта."""
        self.newContext({"width": 1280, "height": 520})
        self.open("classes")
        self.page.locator(".chip-row .stage-pill", has_text="Поток 1").click()
        self.page.locator(".chip-row .chip", has_text="ЕГЭ продвинутый").click()
        expect(self.page.locator(".sticky-card table.data")).to_be_visible()
        self.checkSticky(self.measure(".sticky-card", ":scope > .card-head", "thead th"), "Курсы")

        self.tab("teachers")
        expect(self.page.locator(".teacher-week table.week")).to_be_visible()
        teacher = self.measure(".content .grid.side > .stack", ".teacher-head")
        self.assertAlmostEqual(teacher["head"], 0, delta=1)
        week = self.page.evaluate(MEASURE_JS, [".teacher-week", "thead th", None])
        head = self.page.evaluate("document.querySelector('.teacher-head').getBoundingClientRect().height")
        self.assertLess(week["card"], head)
        self.assertAlmostEqual(week["head"], head, delta=2, msg="строка дней под карточкой преподавателя")

        self.tab("view")
        expect(self.page.locator(".sticky-card table.week")).to_be_visible()
        self.checkSticky(self.measure(".sticky-card", ":scope > .card-head", "thead th"), "Расписание")

        self.tab("preview")
        expect(self.page.locator(".preview-week table.week")).to_be_visible()
        self.checkSticky(self.measure(".preview-week", ":scope > .week-head", "table.week thead th"), "Предпросмотр")

    def test_no_horizontal_scroll_at_1100(self):
        """При ширине окна 1100 ни на одной вкладке и на стартовом экране нет горизонтальной прокрутки."""
        self.newContext({"width": 1100, "height": 800})
        overflow = "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        self.page.goto(self.url)
        expect(self.page.locator(".project-card").first).to_be_visible()
        self.assertLessEqual(self.page.evaluate(overflow), 0, "start screen")

        self.open()

        for tab in TABS:
            with self.subTest(tab=tab):
                self.tab(tab)

                if tab == "preview":
                    expect(self.page.locator(".preview-week table.week")).to_be_visible()
                if tab == "teachers":
                    expect(self.page.locator(".teacher-week table.week")).to_be_visible()

                self.assertLessEqual(self.page.evaluate(overflow), 0, tab)

        # Самый широкий вид «Расписания» — вся школа
        self.tab("view")
        self.page.locator(".view-list .card-head select").select_option("all")
        expect(self.page.locator(".sticky-card .lesson").first).to_be_visible()
        self.assertLessEqual(self.page.evaluate(overflow), 0, "view: all")

    def test_dropdown_in_app_style(self):
        """Раскрытый выпадающий список — в оформлении программы (app.css, «настраиваемый select»
        Chromium 135+): у списка преподавателя на «Курсах» вид base-select, список открывается вниз под
        полем, выбранный пункт подсвечен цветом --accent-soft, стрелка одна (своя, в фоне). Выбор
        мышью меняет значение поля. В браузере без такой поддержки тест пропускается: там остаётся
        обычный список браузера."""
        self.open("classes")
        self.pick("Поток 2", "ЕГЭ основной")

        if not self.page.evaluate("CSS.supports('appearance', 'base-select')"):
            self.skipTest("the browser has no customizable select")

        field = self.page.locator("tbody .select").first
        field.scroll_into_view_if_needed()
        self.assertEqual(field.evaluate("(select) => getComputedStyle(select).appearance"), "base-select")
        self.assertEqual(field.evaluate("(select) => getComputedStyle(select, '::picker-icon').display"), "none")

        field.click()
        self.assertTrue(field.evaluate("(select) => select.matches(':open')"))
        box = field.bounding_box()
        # Под полем — пункт списка, а не страница: список открылся вниз
        below = self.page.evaluate("([x, y]) => document.elementFromPoint(x, y)?.tagName", [box["x"] + 20, box["y"] + box["height"] + 18])
        self.assertEqual(below, "OPTION")

        chosen = field.evaluate("(select) => getComputedStyle(select.selectedOptions[0]).backgroundColor")
        accent = self.page.evaluate("""() => { const probe = document.createElement('div'); probe.style.background = 'var(--accent-soft)';
            document.body.append(probe); const color = getComputedStyle(probe).backgroundColor; probe.remove(); return color; }""")
        self.assertEqual(chosen, accent)

        other = field.locator("option:not(:checked)").first
        value = other.get_attribute("value")
        other.click()
        expect(field).to_have_value(value)

    def test_long_dropdown_label_stays_on_one_line(self):
        """Длинная подпись выбранного пункта в закрытом списке — в одну строку и обрезается перед стрелкой, высота поля
        прежняя (34px): при ширине окна 390 «— авто (выберет программа)» и имена преподавателей
        не переносятся и не вылезают из рамки."""
        self.newContext({"width": 390, "height": 800})
        self.open("classes")
        self.pick("Поток 2", "ЕГЭ основной")
        field = self.page.locator("tbody .select").first
        field.scroll_into_view_if_needed()
        height, wrap, clip = field.evaluate("""(select) => { const style = getComputedStyle(select);
            return [select.offsetHeight, style.whiteSpace, style.overflowClipMargin]; }""")

        self.assertEqual(height, 34)
        self.assertEqual(wrap, "nowrap")
        self.assertIn("content-box", clip)
