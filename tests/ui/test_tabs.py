"""Каждая вкладка открывается без ошибок JS, на ней есть свои главные элементы, в меню верные числа."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

from tests.ui.base import TABS, UICase, expect, t


class TabsTest(UICase):
    """Обход всех вкладок открытого проекта (без вариантов)."""

    def test_menu_numbers(self):
        """Числа в меню: курсов, преподавателей, «составлено/всего» этапов, сохранённых версий."""
        self.open()
        state = self.state()
        count = lambda tab: self.page.locator(".nav-item", has_text=t(f"menu.main.tab.{tab}")).locator(".count")

        expect(count("classes")).to_have_text(str(len(state["courses"])))
        expect(count("teachers")).to_have_text(str(len(state["teachers"])))
        expect(count("view")).to_have_text(f"{sum(1 for stage in state['stages'] if stage['built'])}/{len(state['stages'])}")
        expect(count("save")).to_have_text(str(len(state["versions"])))
        # Вариантов нет — у «Предпросмотра» числа нет
        expect(count("preview")).to_have_count(0)

    def test_every_tab_renders_its_parts(self):
        """Каждая вкладка: свой заголовок, активный пункт меню и главные элементы с числами из проекта."""
        self.open()
        state = self.state()
        page = self.page

        for tab in TABS:
            with self.subTest(tab=tab):
                self.tab(tab)
                expect(page.locator(".nav-item.active")).to_contain_text(t(f"menu.main.tab.{tab}"))

                if tab == "settings":
                    # Сетка: 7 дней × максимум уроков в день; матрица пар: предметы × предметы
                    expect(page.locator("table.times tbody tr")).to_have_count(7)
                    expect(page.locator("table.times .grid-input")).to_have_count(7 * state["maxLessons"])
                    expect(page.locator("table.times tbody tr").first.locator("input").first).to_have_value(state["grid"][0][0])
                    expect(page.locator("table.pairs tbody tr")).to_have_count(len(state["subjects"]))
                    expect(page.locator("table.pairs button.pair:not(.self)")).to_have_count(len(state["subjects"]) * (len(state["subjects"]) - 1))
                elif tab == "classes":
                    expect(page.locator(".chip-row .stage-pill")).to_have_count(len(state["sections"]))
                    expect(page.locator("table.data tbody tr")).not_to_have_count(0)
                elif tab == "teachers":
                    expect(page.locator(".list .list-item")).to_have_count(len(state["teachers"]))
                    expect(page.locator(".teacher-head h2")).to_have_text(state["teachers"][0]["name"])
                    expect(page.locator(".teacher-week table.week")).to_be_visible()
                elif tab == "run":
                    expect(page.locator(".stage-pills .stage-pill")).to_have_count(len(state["stages"]))
                    expect(page.locator("button", has_text=t("menu.main.tab.run.run_stage"))).to_be_visible()
                    expect(page.locator(".rules li")).to_have_count(11)
                    expect(page.locator(".slider-row input[type=range]")).to_have_count(len(state["weights"]) + 1)
                elif tab == "preview":
                    # Вариантов нет: пустая заглушка с переходом на «Запуск»
                    expect(page.locator(".empty")).to_contain_text(t("web.preview.empty_title"))
                elif tab == "view":
                    expect(page.locator("table.week")).to_be_visible()
                    expect(page.locator(".view-list select")).to_be_visible()
                elif tab == "save":
                    expect(page.locator("table.data tbody tr")).to_have_count(len(state["versions"]))
                elif tab == "export":
                    # 4 книги Excel, варианты потока и весь проект
                    expect(page.locator(".tile-grid .tile")).to_have_count(6)

                # Пропущенный ключ текста страница показывает как сам ключ — таких быть не должно
                for text in page.locator(".content").all_inner_texts():
                    self.assertNotRegex(text, r"\b(menu|web|penalty|weights|teachers|dialog)\.[a-z_]+\.[a-z_.]+")

    def test_error_collector_catches_js_errors(self):
        """Сама проверка ошибок работает: исключение на странице и console.error попадают в журнал."""
        self.open()
        self.page.evaluate("() => { console.error('проверка'); setTimeout(() => { throw new Error('сбой'); }); }")
        self.page.wait_for_timeout(200)
        self.assertTrue(any("проверка" in error for error in self.errors), self.errors)
        self.assertTrue(any("сбой" in error and error.startswith("pageerror") for error in self.errors), self.errors)
        self.errors.clear()

    def test_preview_empty_leads_to_run(self):
        """Пустой «Предпросмотр»: кнопка ведёт на «Запуск»."""
        self.open("preview")
        self.page.locator(".empty button").click()
        expect(self.page.locator(".page-head h1")).to_contain_text(t("menu.main.tab.run"))

    def test_tab_is_remembered_after_reload(self):
        """Открытая вкладка запоминается: после перезагрузки страницы открыта она же."""
        self.open("teachers")
        self.page.reload()
        expect(self.page.locator(".page-head h1")).to_contain_text(t("menu.main.tab.teachers"))
        expect(self.page.locator(".nav-item.active")).to_contain_text(t("menu.main.tab.teachers"))
