"""Стыки «линейки, которая присоединяется к потоку», с другими вкладками страницы (третий круг проверки):

* поток только из присоединённых линеек: предупреждение «Общий урок, когда преподаватель «не может»»
  открывает на «Преподавателях» именно этот поток, и жёлтую клетку можно снять щелчком;
* легенда «Когда удобно» не называет «уже идёт», если все уроки идущих курсов нарисованы клетками «вместе»;
* «Расписание» по линейке и по потоку, которые ждут свой поток-источник, не советует составлять варианты;
* «Версии» не советуют составлять заново поток, где все курсы присоединены к другому потоку;
* первый вариант потока с присоединённой линейкой не обводит свои уроки пунктиром «новый».

Проект — ``builders.jointProject`` (база ``JointCase`` из ``joint_base.py``, как у ``test_joint``).
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy

from src.modules.functions.variants import saveVariant
from tests.builders import JOINT_LINE, LEVEL_LINE, courseWeek, jointCourse, markCannot, setDates
from tests.ui.base import expect, t
from tests.real_project import keyPattern
from tests.ui.joint_base import OWN_STREAM_2, STREAM_2, JointCase


class JointEdgesTest(JointCase):
    """Страница на проекте jointProject: стыки присоединённых линеек с другими вкладками."""

    def onlyCopies(self, settings, section=2):
        """Оставляет в потоке ``section`` только курсы-копии (линейка присоединена, остальное убрано)."""
        groups = settings["classes"]["custom_groups"]
        groups[:] = [group for group in groups if group.get("stream_id") != section or group["name"] in self.copies]

    def openTeacher(self, name, stage):
        """«Преподаватели»: выбирает преподавателя ``name`` и этап ``stage`` (подпись) в «Когда удобно»."""
        self.open("teachers")
        self.page.locator(".list .list-item", has_text=name).click()
        expect(self.page.locator(".teacher-head h2")).to_have_text(name)
        self.page.locator(".teacher-week .stage-tab", has_text=stage).click()
        expect(self.page.locator(".teacher-week .stage-tab.active")).to_contain_text(stage)
        expect(self.page.locator(".teacher-week table.week")).to_be_visible()

    def weekCell(self, day, lesson):
        """Ячейка (день, урок) таблицы «Когда удобно» (строки — уроки, столбцы — будни)."""
        return self.page.locator(".teacher-week table.week tbody tr").nth(lesson).locator("td").nth(day)

    def test_copy_only_stream_cannot_mark_opens_and_clears(self):
        """Поток 2 — только присоединённая линейка (этап «нечего менять»), у «Математика #1» на нём
        «не может» под общим уроком. Щелчок по строке предупреждения открывает «Когда удобно» Потока 2,
        а щелчок по жёлтой клетке снимает «не может» — предупреждения больше нет.
        """
        settings, _ = self.useJoint()
        self.onlyCopies(settings)
        markCannot(settings, "Математика #1", "2", (0, 0))
        self.save("settings.json", settings)
        self.assertTrue(next(stage for stage in self.state()["stages"] if stage["key"] == "2")["allStarted"])

        self.open("view")
        card = self.page.locator(".clash-card", has_text=t("web.view.joint_cannot_title"))
        expect(card).to_have_count(1)
        card.locator("li", has_text="Математика #1").click()

        expect(self.page.locator(".teacher-head h2")).to_have_text("Математика #1")
        expect(self.page.locator(".teacher-week .stage-tab.active")).to_contain_text(STREAM_2)
        cell = self.weekCell(0, 0)
        expect(cell).to_contain_text(t("menu.main.tab.teachers.busy"))

        with self.page.expect_response(lambda response: "/action" in response.url):
            cell.locator(".state").click()

        expect(cell).not_to_contain_text(t("menu.main.tab.teachers.busy"))
        self.assertNotIn([0, 0], self.load("settings.json")["teachers"]["Математика #1"]["availability"]["2"]["free"])

        self.open("view")
        expect(self.page.locator(".view-list")).to_be_visible()
        expect(self.page.locator(".clash-card", has_text=t("web.view.joint_cannot_title"))).to_have_count(0)

    def test_started_legend_only_with_started_cells(self):
        """Присоединённая линейка Потока 2 уже идёт (остальные курсы Потока 2 ещё нет), «Математика #1»
        ведёт в Потоке 2 только общие уроки: в «Когда удобно» Потока 2 они нарисованы клетками «вместе»,
        клеток «уже идёт» нет — и в легенде нет «уже идёт».
        """
        settings, _ = self.useJoint(own=OWN_STREAM_2)

        for name in self.copies:
            setDates(settings, name, "2020-01-01", None)

        self.save("settings.json", settings)
        self.openTeacher("Математика #1", STREAM_2)
        expect(self.weekCell(0, 0)).to_contain_text(t("menu.main.tab.teachers.commitment_joint"))

        week = self.page.locator(".teacher-week")
        expect(week.locator("table.week .state.static", has_text=t("web.state.started"))).to_have_count(0)
        expect(week.locator(".legend .badge", has_text=t("web.state.started"))).to_have_count(0)

    def test_waiting_line_and_stream_say_wait_for_source(self):
        """Поток 1 не принят. «Расписание» по линейке «ЕГЭ основной» Потока 2 (все её курсы присоединены)
        и по Потоку 2 из одних копий пишет, что линейка ждёт Поток 1 (как на «Запуске»), по курсу-копии —
        что его уроки встанут сами, и нигде не советует составить варианты Потока 2.
        """
        # В принятом расписании есть только курс Потока 3 — иначе «Расписание» пишет «ещё не составлено»
        stream_3 = {jointCourse(3, "Математика", LEVEL_LINE): courseWeek("Математика", "Математика #2", (1, 0))}
        settings, _ = self.useJoint(accepted=False, own=stream_3)
        self.onlyCopies(settings)
        self.save("settings.json", settings)
        self.open("view")
        line_hint = keyPattern("web.run.joint_waiting", line=JOINT_LINE, number=1)
        course_hint = keyPattern("web.classes.joint_waiting_hint", number=1)
        status = self.page.locator(".sticky-card")
        modes = (("line", f"2\t{JOINT_LINE}", line_hint), ("stream", "2", line_hint), ("course", next(iter(self.copies)), course_hint))

        for mode, key, hint in modes:
            with self.subTest(mode=mode):
                self.choose(mode, key)
                expect(status).to_contain_text(hint)
                expect(status).not_to_contain_text(keyPattern("menu.main.tab.view.line_not_built"))
                expect(status).not_to_contain_text(keyPattern("menu.main.tab.view.stage_not_built"))

    def test_save_tab_does_not_advise_rebuilding_copy_only_stream(self):
        """Поток 1 принят не полностью (у «Математики» один урок из двух), Поток 2 — только присоединённая
        линейка. На «Версиях» совет «составьте варианты заново» есть у Потока 1 и нет у Потока 2:
        у Потока 2 составлять нечего, его уроки придут из Потока 1.
        """
        settings, answer = self.useJoint()
        self.onlyCopies(settings)
        source = self.copies[next(name for name in self.copies if "Математика" in name)]
        day, lesson = next((day, lesson) for day, cells in enumerate(answer[source])
                           for lesson, cell in enumerate(cells) if cell["subject"] != "#")
        answer[source][day][lesson] = {"subject": "#", "teachers": []}

        for name, origin in self.copies.items():
            answer[name] = copy.deepcopy(answer[origin])

        self.save("settings.json", settings)
        self.save("answer.json", answer)
        stages = {stage["key"]: stage for stage in self.state()["stages"]}
        self.assertTrue(stages["2"]["placed"] and not stages["2"]["built"], stages["2"])

        self.open("save")
        partial = lambda name: keyPattern("web.save.partial", name=name)
        expect(self.page.locator("body")).to_contain_text(partial(stages["1"]["label"]))
        expect(self.page.locator("body")).not_to_contain_text(partial(stages["2"]["label"]))

    def test_first_variant_of_joint_stream_has_no_fresh(self):
        """Поток 1 принят, у Потока 2 «ЕГЭ основной» присоединён, своих уроков в принятом расписании нет.
        Вариант Потока 2 (копии там же, где источники, плюс свои курсы) — не «новый» относительно
        принятого: пунктира «новый урок» и его легенды нет.
        """
        settings, answer = self.useJoint()
        variant = {**{name: copy.deepcopy(answer[name]) for name in self.copies}, **copy.deepcopy(OWN_STREAM_2)}
        saveVariant(self.folder, "2", 1, variant)

        self.open("preview")
        self.page.locator(".segmented button", has_text=STREAM_2).click()
        expect(self.page.locator(".segmented button.active")).to_have_text(STREAM_2)
        expect(self.page.locator(".preview-week .lesson").first).to_be_visible()

        expect(self.page.locator(".preview-week .lesson.fresh")).to_have_count(0)
        expect(self.page.locator(".fresh-legend")).to_have_count(0)
