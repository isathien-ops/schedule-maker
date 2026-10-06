"""Стартовый экран: список проектов, открытие, создание, удаление и импорт проекта."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
import urllib.parse

from tests.ui.base import ARCHIVE, PROJECTS, UICase, expect, t


class StartScreenTest(UICase):
    """Стартовый экран и переходы между ним и открытым проектом."""

    def card(self, name):
        """Карточка проекта name на стартовом экране."""
        return self.page.locator(".project-card", has=self.page.locator(".p-name", has_text=name))

    def start(self):
        """Открывает стартовый экран и ждёт карточку тестового проекта."""
        self.page.goto(self.url)
        expect(self.card(self.NAME)).to_be_visible()

    def test_list_shows_project_with_numbers(self):
        """В списке — карточка проекта с числом курсов, преподавателей и «составлено/всего» этапов."""
        self.start()
        expect(self.page.locator(".start-hero h1")).to_have_text(t("menu.start.label_name"))
        self.assertEqual(self.page.title(), t("menu.start.label_name"))

        state = self.state()
        built = sum(1 for stage in state["stages"] if stage["built"])
        stats = self.card(self.NAME).locator(".p-stats b")
        expect(stats).to_have_text([str(len(state["courses"])), str(len(state["teachers"])), f"{built}/{len(state['stages'])}"])

    def test_open_by_click_goes_to_schedule_when_attention_needed(self):
        """Клик по карточке открывает проект; при проблемах в расписании — сразу «Расписание»
        с красным числом в меню (уроки без преподавателя и т.п.)."""
        self.start()
        self.card(self.NAME).click()

        expect(self.page.locator(".project-switch .name")).to_have_text(self.NAME)
        expect(self.page.locator(".page-head h1")).to_contain_text(t("menu.main.tab.view"))
        self.assertEqual(urllib.parse.unquote(self.page.evaluate("location.hash")), f"#{self.NAME}")

        state = self.state()
        inSchedule = {stage["key"] for stage in state["stages"] if stage["built"] or stage["placed"] > 0}
        short = [course for course in state["courses"] if len(course["slots"]) < course["hours"] and course["stage"] in inSchedule]
        attention = len({clash[0] for clash in state["clashes"]}) + len(state["noTeacher"]) + len(short) \
            + sum(1 for item in state["staffing"] if item["level"] == "short")
        self.assertGreater(attention, 0)
        expect(self.page.locator(".nav-item.active .nav-alert")).to_have_text(str(attention))

    def test_back_to_projects(self):
        """Кнопка с именем проекта в меню возвращает к списку проектов и очищает адрес."""
        self.open()
        self.page.locator(".project-switch").click()
        expect(self.card(self.NAME)).to_be_visible()
        self.assertEqual(self.page.evaluate("location.hash"), "")

    def test_open_missing_project_by_address(self):
        """Адрес #несуществующий — сообщение об ошибке и стартовый экран."""
        self.allowRefusals()
        self.page.goto(f"{self.url}/#{urllib.parse.quote('__test_ui_missing__')}")
        self.toast(t("web.error.no_project"))
        expect(self.card(self.NAME)).to_be_visible()

    def test_create_project(self):
        """«Создать»: новый проект (стандартные курсы, преподавателей нет) открывается, папка
        с settings.json на диске; раз преподавателей нет, сразу видна карточка «Нужен ещё преподаватель»."""
        name = "__test_ui_created__"
        self.extra.append(name)
        self.start()

        field = self.page.get_by_placeholder(t("web.new_project_placeholder"))
        field.fill(name)
        self.page.locator(".tile.new button", has_text=t("web.common.create")).click()

        expect(self.page.locator(".project-switch .name")).to_have_text(name)
        self.assertTrue(os.path.exists(f"{PROJECTS}/{name}/settings.json"))
        state = self.state(name)
        self.assertEqual(state["teachers"], [])
        self.assertTrue(state["courses"])
        expect(self.page.locator(".page-head h1")).to_contain_text(t("menu.main.tab.view"))
        expect(self.page.locator(".clash-card", has_text=t("web.view.staff_title"))).to_be_visible()
        expect(self.page.locator(".clash-card", has_text=t("web.view.staff_title")).locator("li")).to_have_count(len(state["staffing"]))

    def test_create_by_enter_and_duplicate_name(self):
        """Enter в поле создаёт проект; занятое имя — понятная ошибка под полем, проект не меняется."""
        self.allowRefusals()
        self.start()
        before = os.path.getmtime(f"{self.folder}/settings.json")

        field = self.page.get_by_placeholder(t("web.new_project_placeholder"))
        field.fill(self.NAME)
        field.press("Enter")

        error = self.page.locator(".tile.new").first.locator("p.hint")
        expect(error).to_have_text(t("web.error.project_name_exists"))
        expect(self.page.locator(".start-hero")).to_be_visible()
        self.assertEqual(os.path.getmtime(f"{self.folder}/settings.json"), before)

    def test_create_with_empty_name(self):
        """Пустое имя — ошибка под полем, новых папок проектов не появляется."""
        self.allowRefusals()
        self.start()
        before = sorted(os.listdir(PROJECTS))

        self.page.locator(".tile.new button", has_text=t("web.common.create")).click()

        expect(self.page.locator(".tile.new").first.locator("p.hint")).not_to_be_empty()
        self.assertEqual(sorted(os.listdir(PROJECTS)), before)

    def test_delete_project_cancel_then_confirm(self):
        """Корзина на карточке: «Отмена» ничего не удаляет; подтверждение удаляет папку и карточку."""
        self.start()
        trash = self.card(self.NAME).locator(".p-delete")

        trash.click()
        expect(self.page.locator(".dialog")).to_contain_text(self.NAME)
        self.dialogButton(t("web.common.cancel")).click()
        expect(self.page.locator(".dialog")).to_have_count(0)
        self.assertTrue(os.path.isdir(self.folder))

        trash.click()
        self.dialogButton(t("web.delete_project")).click()
        self.toast(t("web.project_deleted").replace("{name}", self.NAME))
        expect(self.card(self.NAME)).to_have_count(0)
        self.assertFalse(os.path.exists(self.folder))

    def test_import_project(self):
        """Импорт ZIP: имя подставляется из файла, после «Загрузить» проект открыт и совпадает с архивом."""
        name = "__test_ui_imported__"
        self.extra.append(name)
        self.start()

        importCard = self.page.locator(".tile.new", has_text=t("web.import_project"))
        importCard.locator("input[type=file]").set_input_files(ARCHIVE)
        expect(importCard.locator(".hint.grow")).to_have_text(os.path.basename(ARCHIVE))

        nameField = importCard.get_by_placeholder(t("web.import_name"))
        expect(nameField).to_have_value(os.path.splitext(os.path.basename(ARCHIVE))[0])
        nameField.fill(name)
        importCard.locator("button", has_text=t("web.import_button")).click()

        self.toast(t("web.import_done").replace("{name}", name))
        expect(self.page.locator(".project-switch .name")).to_have_text(name)
        self.assertEqual(len(self.state(name)["courses"]), len(self.state()["courses"]))

    def test_import_not_archive(self):
        """Файл, который не архив проекта: сервер отказывает, текст отказа — под полями карточки
        (FormData уходит через api() из core.js), проект не создаётся, кнопка снова доступна."""
        self.allowRefusals()
        name = "__test_ui_not_archive__"
        self.extra.append(name)
        self.start()

        importCard = self.page.locator(".tile.new", has_text=t("web.import_project"))
        importCard.locator("input[type=file]").set_input_files({"name": "broken.zip", "mimeType": "application/zip", "buffer": b"not a zip"})
        importCard.get_by_placeholder(t("web.import_name")).fill(name)
        button = importCard.locator("button", has_text=t("web.import_button"))
        button.click()

        expect(importCard.locator("p.form-error")).to_have_text(t("web.error.not_project_archive"))
        expect(button).to_be_enabled()
        expect(self.page.locator(".project-switch")).to_have_count(0)
        self.assertFalse(os.path.exists(f"{PROJECTS}/{name}"))

    def test_import_without_file(self):
        """«Загрузить» без выбранного файла — подсказка выбрать файл, запроса на сервер нет."""
        self.start()
        importCard = self.page.locator(".tile.new", has_text=t("web.import_project"))
        requests = []
        self.page.on("request", lambda request: "/import" in request.url and requests.append(request.url))

        importCard.locator("button", has_text=t("web.import_button")).click()

        expect(importCard.locator("p.hint")).to_have_text(t("web.import_pick"))
        self.assertEqual(requests, [])

    def test_broken_address_shows_start_screen(self):
        """Битый адрес #%E0%A4%A (обрезанная ссылка): без ошибки JS открывается стартовый экран
        со списком проектов (projectInAddress в projects.js считает такой адрес пустым).
        Ошибки JS проверяет tearDown.
        """
        self.page.goto(f"{self.url}/#%E0%A4%A")
        expect(self.card(self.NAME)).to_be_visible()
        expect(self.page.locator(".project-switch")).to_have_count(0)

    def test_address_typed_into_open_page_opens_project(self):
        """Адрес «/#проект», вставленный в уже открытую вкладку, открывает проект без перезагрузки
        (событие hashchange); «Назад» в браузере возвращает к списку проектов.
        """
        self.start()
        self.page.evaluate("name => { location.hash = encodeURIComponent(name); }", self.NAME)
        expect(self.page.locator(".project-switch .name")).to_have_text(self.NAME)

        self.page.go_back()
        expect(self.card(self.NAME)).to_be_visible()
        self.assertEqual(self.page.evaluate("location.hash"), "")

    def test_address_switches_between_projects(self):
        """В открытом проекте адрес «/#другой_проект» (hashchange) открывает другой проект без
        перезагрузки, а адрес несуществующего — сообщение и стартовый экран."""
        self.allowRefusals()
        other = "__test_ui_other__"
        self.extra.append(other)
        self.assertEqual(self.client.post("/api/projects", json={"name": other}).status_code, 200)
        self.open("settings")
        self.page.evaluate("() => { window.notReloaded = true; }")

        self.page.evaluate("name => { location.hash = encodeURIComponent(name); }", other)
        expect(self.page.locator(".project-switch .name")).to_have_text(other)

        self.page.evaluate("name => { location.hash = encodeURIComponent(name); }", "__test_ui_missing__")
        self.toast(t("web.error.no_project"))
        expect(self.card(self.NAME)).to_be_visible()
        self.assertTrue(self.page.evaluate("() => window.notReloaded"))

    def test_project_deleted_elsewhere(self):
        """Проект удалили в другой вкладке браузера: следующее действие возвращает к списку
        проектов с сообщением «Проект не найден» (isProjectGone в core.js)."""
        self.allowRefusals()
        self.open("settings")
        self.assertEqual(self.client.delete(f"/api/project/{urllib.parse.quote(self.NAME)}").status_code, 200)

        self.act(lambda: self.page.locator(".card-foot button", has_text=t("menu.main.tab.settings.copy_monday")).click())

        self.toast(t("web.error.no_project"))
        expect(self.page.locator(".start-hero")).to_be_visible()
        expect(self.card(self.NAME)).to_have_count(0)
        self.assertEqual(self.page.evaluate("location.hash"), "")

    def test_server_not_answering_on_start(self):
        """Сервер не ответил на список проектов: вместо пустой страницы — стартовый экран
        с сообщением об ошибке (renderStart в projects.js), а «Повторить», когда сервер снова
        отвечает, показывает список проектов."""
        self.allowed.append(r"Failed to load resource: net::ERR_FAILED")
        self.page.route("**/api/projects", lambda route: route.abort())
        self.page.goto(self.url)

        expect(self.page.locator(".start-hero")).to_be_visible()
        expect(self.page.locator(".start .empty .e-title")).to_have_text(t("web.error.generic"))
        expect(self.page.locator(".tile")).to_have_count(0)

        self.page.unroute("**/api/projects")
        self.page.locator(".start .empty button", has_text=t("web.common.retry")).click()

        expect(self.page.locator(".start .empty")).to_have_count(0)
        expect(self.page.locator(".tile.new").first).to_be_visible()
