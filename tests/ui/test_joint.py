"""«Линейка присоединяется к Потоку N» на странице (.spec/joint-lines/SPEC.md): выбор «Присоединяется к»
на «Курсах» (AC-1, AC-5, AC-7), закрытые ячейки копий (AC-10), копии, которые ждут принятия
Потока 1 (AC-13), подписи и склейка общих уроков в «Расписании» (AC-29), «Предпросмотр» (AC-30),
«Преподаватели» (AC-31), предупреждение «Общий урок, когда преподаватель «не может»» в «Расписании», снятие
«не может» щелчком по ячейке «вместе» на «Преподавателях» и её пометка в легенде (AC-39), один
вопрос при «Убрать из расписания» у Потока-источника (AC-40) и подсказка у закрытой «Убрать из
расписания», когда у потока стоят только общие уроки (AC-41).

* ``JointPageTest`` — проект ``builders.jointProject`` вместо данных 2026/27 (Потоки 1–3, принятый
  Поток 1, отметка ``builders.markJoint`` прямо в файлах); в нём же — курс-источник, который идёт
  только через копию: подсказка у замочка называет ``runningSince``, а не своё будущее начало;
* ``JointPreviewTest`` — проект 2026/27, в котором «ЕГЭ основной» Потока 2 присоединяется к
  Потоку 1 ещё до сборки (крючок ``UICase.PREPARE``), и варианты Потока 2 составлены настоящим решателем;
* ``JointSeparateSubjectTest`` — предмет, который появился в линейке Потока 1 после отметки: пометка
  «не присоединён к Потоку 1…» (web.classes.joint_separate) и кнопка «Присоединить к Потоку 1» (web.classes.joint_join).

Тексты сравниваются по ключам ru.hjson (``keyPattern`` из tests/real_project.py): подстановки ``{имя}`` — их значения или
любой текст.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import json
import re

from src.modules.functions.courses import addCourse
from src.modules.functions.model import hasLessons
from src.modules.functions.stages import stageCourses
from src.modules.functions.variants import saveVariant
from tests.builders import JOINT_LINE, OWN_LINE, courseWeek, markCannot, markJoint, readJson, shiftStream
from tests.real_project import keyPattern, lessons as lessonsOf
from tests.ui.base import expect, plain, t
# База классов, имена курсов проекта и селекторы — общие с test_joint_edges.py (см. joint_base.py)
from tests.ui.joint_base import (
    LESSONS, MATH_1, MATH_2, OWN_STREAM_2, PREVIEW_LESSONS, RUS_2, INFO_2, STREAM_1, STREAM_2, JointCase, cells, jointCopies
)

# Начало Потока 2 (уже идёт: «сегодня» в тестах — 04.10.2026) и Потока 1 (ещё впереди)
PAST, FUTURE = "2026-09-01", "2027-01-11"


class JointPageTest(JointCase):
    """Страница на проекте jointProject."""

    # ------------------------------------------------------------------ AC-1, AC-5, AC-7: «Присоединяется к»

    def test_select_only_where_earlier_stream_has_same_line(self):
        """AC-1: у «ЕГЭ основной» Потока 2 в шапке курсов выбор «Присоединяется к» с пунктами «нет» (web.classes.joint_apart)
        (выбран) и «Поток 1». Выбора нет у Потока 1 (раньше потоков нет), у линейки «ОГЭ» Потока 2
        (в Потоке 1 её нет) и у блока, даже если в нём есть линейка «ЕГЭ основной».
        """
        self.useJoint(mark=False)
        self.apiAct("newLine", section="may", name=JOINT_LINE, subjects=["Математика"])
        self.open("classes")
        self.pick(STREAM_2, JOINT_LINE)

        expect(self.jointSelect()).to_have_count(1)
        expect(self.jointSelect().locator("option")).to_have_text([t("web.classes.joint_apart"), STREAM_1])
        self.assertEqual(self.chosenLabel(), t("web.classes.joint_apart"))
        expect(self.page.locator(".sticky-card")).to_contain_text(t("web.classes.joint_label"))

        for section, line in ((STREAM_2, OWN_LINE), (STREAM_1, JOINT_LINE), ("Майские марафоны", JOINT_LINE)):
            self.pick(section, line)
            expect(self.jointSelect()).to_have_count(0)

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.classes.joint_apart")
        self.known("web.classes.joint_label")

    def test_choosing_stream_1_marks_line(self):
        """AC-1 и AC-2 со страницы: выбор «Поток 1» отправляет setJoint (поток 2, «ЕГЭ основной»,
        источник 1) без вопроса; отметка у курсов, чьи предметы есть в Потоке 1 (не у «Информатики»),
        уроки копий — как у Потока 1, в выборе стоит «Поток 1».
        """
        self.useJoint(mark=False)
        self.open("classes")
        self.pick(STREAM_2, JOINT_LINE)
        expect(self.jointSelect()).to_have_count(1)

        response = self.act(lambda: self.jointSelect().select_option(label=STREAM_1))

        request = response.request.post_data_json
        self.assertEqual(request["action"], "setJoint")
        self.assertEqual((str(request["args"]["section"]), request["args"]["line"], int(request["args"]["source"])), ("2", JOINT_LINE, 1))
        self.assertEqual(self.marks(), {MATH_2: 1, RUS_2: 1})
        answer = self.load("answer.json")
        self.assertEqual(cells(answer.get(MATH_2)), cells(answer[MATH_1]))
        self.assertEqual(self.chosenLabel(), STREAM_1)

    def test_source_line_names_streams_going_with_it(self):
        """AC-1: у «ЕГЭ основной» Потока 1 выбора нет, вместо него пометка «К этой линейке
        присоединяется Поток 2» (web.classes.joint_with); у отмеченной линейки Потока 2 в выборе стоит «Поток 1».
        """
        self.useJoint()
        self.open("classes")
        self.pick(STREAM_2, JOINT_LINE)
        expect(self.jointSelect()).to_have_count(1)
        self.assertEqual(self.chosenLabel(), STREAM_1)

        self.pick(STREAM_1, JOINT_LINE)
        expect(self.jointSelect()).to_have_count(0)
        expect(self.page.locator(".sticky-card")).to_contain_text(keyPattern("web.classes.joint_with", streams=STREAM_2))
        expect(self.page.locator(".sticky-card")).to_contain_text(STREAM_2)

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.classes.joint_with")

    def test_mark_over_own_lessons_asks_and_cancel_keeps_project(self):
        """AC-5: у «ЕГЭ основной» Потока 2 свои уроки, не как в Потоке 1. Выбор «Поток 1» — вопрос
        «уже есть уроки… поставить их в то же время?»; «Отмена» — файлы и версии не меняются.
        Повторный выбор и «Да» — версия «Перед: …» (web.version.joint), отметка стоит, уроки копии —
        как у Потока 1.
        """
        self.useJoint(mark=False, own={MATH_2: courseWeek("Математика", "Математика #3", (1, 0), (4, 0))})
        self.open("classes")
        self.pick(STREAM_2, JOINT_LINE)
        expect(self.jointSelect()).to_have_count(1)
        files, versions = (self.raw("settings.json"), self.raw("answer.json")), len(self.state()["versions"])
        dialog = self.page.locator(".dialog")

        self.act(lambda: self.jointSelect().select_option(label=STREAM_1), idle=False)
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text(keyPattern("web.classes.joint_confirm", line=JOINT_LINE, name=JOINT_LINE, number=1))
        expect(dialog).to_contain_text(JOINT_LINE)
        self.dialogButton(t("web.common.cancel")).click()
        expect(dialog).to_have_count(0)
        self.idle()

        self.assertEqual((self.raw("settings.json"), self.raw("answer.json")), files)
        self.assertEqual(len(self.state()["versions"]), versions)

        # Список выбора снова как в проекте («нет»), и выбор повторяется
        self.page.evaluate("() => render()")
        self.act(lambda: self.jointSelect().select_option(label=STREAM_1), idle=False)
        expect(dialog).to_be_visible()
        self.act(lambda: self.page.locator(".dialog .dialog-foot button").last.click())

        state = self.state()
        self.assertEqual(len(state["versions"]), versions + 1)
        self.assertRegex(state["versions"][0]["name"], keyPattern("web.version.joint", line=JOINT_LINE, number=1))
        self.assertEqual(self.marks(), {MATH_2: 1, RUS_2: 1})
        answer = self.load("answer.json")
        self.assertEqual(cells(answer.get(MATH_2)), cells(answer[MATH_1]))

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.classes.joint_confirm")
        self.known("web.version.joint")

    def test_apart_returns_line_to_own_schedule(self):
        """AC-7: у отмеченной линейки (курсы не идут) выбор «нет»: отметки нет, уроков копий
        в расписании нет, курсы снова «авто» и с выбором преподавателя, часы прежние; сообщение
        web.classes.joint_off («Линейка «ЕГЭ основной» Потока 2 больше не присоединена к другому потоку…»).
        """
        self.useJoint()
        self.open("classes")
        self.pick(STREAM_2, JOINT_LINE)
        expect(self.jointSelect()).to_have_count(1)

        self.act(lambda: self.jointSelect().select_option(label=t("web.classes.joint_apart")))

        expect(self.page.locator("#toast")).to_contain_text(keyPattern("web.classes.joint_off", line=JOINT_LINE, name=JOINT_LINE, number=2))
        expect(self.page.locator("#toast")).to_contain_text(JOINT_LINE)
        self.assertEqual(self.marks(), {})
        answer = self.load("answer.json")
        self.assertFalse(hasLessons(answer, MATH_2) or hasLessons(answer, RUS_2))
        self.assertEqual(self.chosenLabel(), t("web.classes.joint_apart"))

        math = self.row("Математика")
        expect(math.locator("td").nth(1).locator("select")).to_have_count(1)
        expect(math.locator("td").nth(2)).to_contain_text(t("menu.main.tab.classes.auto_short"))
        expect(self.row("Русский язык").locator("input[type=number]")).to_have_value("2")

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.classes.joint_apart")
        self.known("web.classes.joint_off")

    # ------------------------------------------------------------------ AC-10: закрытые ячейки копии

    def test_copy_cells_are_locked_as_in_stream_1(self):
        """AC-10: у курса-копии преподаватель, «День и время» и число уроков — неизменяемые ячейки
        «как в Потоке 1» (.locked): без списка выбора, без поля числа, без кнопки закрепления.
        Обычный курс той же линейки («Информатика») по-прежнему меняется.
        """
        self.useJoint()
        self.open("classes")
        self.pick(STREAM_2, JOINT_LINE)

        for subject in ("Математика", "Русский язык"):
            row = self.row(subject)
            expect(row.locator(".locked")).to_have_count(3)
            expect(row.locator("select")).to_have_count(0)
            expect(row.locator("input[type=number]")).to_have_count(0)
            expect(row.locator("td").nth(2).locator("button")).to_have_count(0)

            for index in range(3):
                expect(row.locator(".locked").nth(index)).to_contain_text(keyPattern("web.state.joint", number=1))

        informatics = self.row("Информатика")
        expect(informatics.locator(".locked")).to_have_count(0)
        expect(informatics.locator("select")).to_have_count(1)
        expect(informatics.locator("input[type=number]")).to_have_count(1)

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.state.joint")

    # ------------------------------------------------------------------ AC-13: Поток 1 не принят

    def test_waiting_copies_on_courses_tab(self):
        """AC-13: Поток 1 не принят. У копий в «Курсах» Потока 2 вместо дня и часа — «ждут Поток 1»
        с подсказкой «Уроки встанут сами, когда у этого курса в Потоке 1 будут уроки в расписании»
        (web.classes.joint_waiting, web.classes.joint_waiting_hint).
        """
        self.useJoint(accepted=False, own=OWN_STREAM_2)
        self.open("classes")
        self.pick(STREAM_2, JOINT_LINE)

        hint = keyPattern("web.classes.joint_waiting_hint", number=1)

        for subject in ("Математика", "Русский язык"):
            slot = self.row(subject).locator("td").nth(2)
            expect(slot).to_contain_text(keyPattern("web.classes.joint_waiting", number=1))
            tips = slot.evaluate("(cell) => [cell, ...cell.querySelectorAll('*')].map((item) => item.dataset?.tip || item.getAttribute('title') || '')")
            self.assertTrue([tip for tip in tips if hint.search(tip)], (subject, tips))

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.classes.joint_waiting")
        self.known("web.classes.joint_waiting_hint")

    def test_waiting_copies_are_not_lacking(self):
        """AC-13: Поток 1 не принят, обычные курсы Потока 2 стоят полностью. Копии без уроков не
        попадают в «Не хватает уроков» на «Расписании» и в красный счётчик у пункта меню.
        """
        self.useJoint(accepted=False, own=OWN_STREAM_2)
        self.open("view")
        state = self.state()
        shorts = {course["short"] for course in state["courses"] if course["name"] in self.copies}

        lacking = self.page.locator(".clash-card", has_text=t("web.view.short_title")).locator("li b")
        self.assertFalse(set(map(plain, lacking.all_inner_texts())) & shorts)

        # Красное число — как без копий: накладки (по преподавателю), уроки без преподавателя,
        # нехватка уроков у обычных курсов этапов в расписании, «не хватает преподавателей»
        scheduled = {stage["key"] for stage in state["stages"] if stage["built"] or stage["placed"] > 0}
        expected = (len({teacher for teacher, *_ in state["clashes"]}) + len(state["noTeacher"])
                    + len([course for course in state["courses"] if course["name"] not in self.copies
                           and course["stage"] in scheduled and len(course["slots"]) < course["hours"]])
                    + len([item for item in state["staffing"] if item["level"] == "short"]))
        alert = self.page.locator(".nav-item", has_text=t("menu.main.tab.view")).locator(".nav-alert")

        if expected:
            expect(alert).to_have_text(str(expected))
        else:
            expect(alert).to_have_count(0)

    def test_run_tab_names_line_waiting_for_stream_1(self):
        """AC-13: на «Запуске» у Потока 2 строка «Линейка «ЕГЭ основной» присоединена к Потоку 1
        и ждёт его: уроки встанут, когда у этих курсов в Потоке 1 появятся уроки в расписании» (web.run.joint_waiting).
        """
        self.useJoint(accepted=False, own=OWN_STREAM_2)
        self.open("run")
        self.page.locator(".stage-pills .stage-pill", has_text=STREAM_2).click()
        expect(self.page.locator(".grid.run .card h2").last).to_have_text(STREAM_2)

        expect(self.page.locator(".grid.run")).to_contain_text(keyPattern("web.run.joint_waiting", line=JOINT_LINE, name=JOINT_LINE, number=1))

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.run.joint_waiting")

    # ------------------------------------------------------------------ AC-29: «Расписание»

    def test_copy_and_source_cards_are_signed(self):
        """AC-29: в режимах «Поток 2», «Линейка» и «Курс» карточки копий подписаны «вместе с Потоком 1»
        (у каждого урока копии), в режиме «Поток 1» карточки источников — «вместе с Потоком 2».
        """
        self.useJoint()
        self.open("view")
        with_1, with_2 = keyPattern("web.lesson.joint", number=1), keyPattern("web.lesson.joint", number=2)
        answer = self.state()["answer"]
        copies = sum(len(lessonsOf(answer[name])) for name in self.copies)
        self.assertEqual(copies, 4)

        for mode, key, expected in (("stream", "2", copies), ("line", f"2\t{JOINT_LINE}", copies), ("course", MATH_2, 2)):
            with self.subTest(mode=mode):
                self.choose(mode, key)
                expect(self.page.locator(LESSONS, has_text=with_1)).to_have_count(expected)

        self.choose("stream", "1")
        expect(self.page.locator(LESSONS, has_text=with_2)).to_have_count(copies)
        # Обычные курсы Потока 1 («ЕГЭ продвинутый», «Биология») без подписи
        expect(self.page.locator(LESSONS)).to_have_count(9)

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.lesson.joint")

    def test_shared_lesson_is_one_card_without_clash(self):
        """AC-29: в режимах «Вся школа», «Преподаватель» и «Предмет» общий урок источника и копии —
        одна карточка «Потоки 1 и 2», число уроков без двойного счёта; карточки «Преподаватель на
        двух уроках сразу» по общим урокам нет.
        """
        self.useJoint()
        self.open("view")
        shared = keyPattern("web.lesson.joint_streams", numbers="1 и 2", streams="1 и 2")
        count = lambda value: re.compile(rf"(^|\D){value}(\D|$)")

        expect(self.page.locator(".clash-card", has_text=t("web.view.clashes_title"))).to_have_count(0)

        # Вся школа: 9 уроков Потока 1, 4 из них общие с Потоком 2
        for mode, key, total, joint in (("all", "all", 9, 4), ("teacher", "Математика #1", 2, 2), ("subject", "Математика", 4, 2)):
            with self.subTest(mode=mode):
                self.choose(mode, key)
                expect(self.page.locator(LESSONS)).to_have_count(total)
                expect(self.page.locator(".sticky-card > .card-head .badge")).to_have_text(count(total))
                expect(self.page.locator(LESSONS, has_text=shared)).to_have_count(joint)
                expect(self.page.locator(LESSONS, has_text="1 и 2")).to_have_count(joint)

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.lesson.joint_streams")

    # ------------------------------------------------------------------ AC-39: общий урок в часы «не может»

    def test_shared_lesson_in_cannot_hours_is_warned(self):
        """AC-39: у «Математика #1» на этапе «Поток 2» в пн 1-м уроком «не может», а там общий урок.
        Над «Расписанием» — карточка-предупреждение «Общий урок, когда преподаватель «не может»» (web.view.joint_cannot_title)
        со строкой: преподаватель, Поток 2, день и час (как в карточке накладок, slotLabel). Карточки
        накладок нет. Когда отметку сняли, карточки нет.
        """
        settings, _ = self.useJoint()
        markCannot(settings, "Математика #1", "2", (0, 0))
        self.save("settings.json", settings)
        self.open("view")
        card = self.page.locator(".clash-card", has_text=t("web.view.joint_cannot_title"))

        expect(card).to_have_count(1)
        expect(card.locator("li")).to_have_count(1)
        expect(card).to_contain_text("Математика #1")
        expect(card).to_contain_text(STREAM_2)
        expect(card).to_contain_text(self.page.evaluate("() => slotLabel([0, 0])"))
        expect(self.page.locator(".clash-card", has_text=t("web.view.clashes_title"))).to_have_count(0)

        settings["teachers"]["Математика #1"]["availability"]["2"]["free"] = []
        self.save("settings.json", settings)
        self.open("view")
        expect(self.page.locator(".view-list")).to_be_visible()
        expect(self.page.locator(".clash-card", has_text=t("web.view.joint_cannot_title"))).to_have_count(0)

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.view.joint_cannot_title")
        self.known("web.view.joint_cannot_hint")

    # ------------------------------------------------------------------ AC-40: «Убрать из расписания» у Потока 1

    def test_reset_source_stage_asks_once(self):
        """AC-40: Поток 1 ещё не начался, с ним идёт «ЕГЭ основной» Потока 2. «Убрать из расписания» у
        Потока 1 — ровно одно окно-вопрос, и в нём всё: общий текст web.confirm_reset («Поток 1») и строка
        web.run.confirm_reset_joint («ЕГЭ основной», Поток 2). После «Убрать» второго вопроса нет, уроков
        источников и копий в расписании нет.
        """
        settings, _ = self.useJoint()

        shiftStream(settings, 1, "2026-10-12")

        self.save("settings.json", settings)
        self.open("run")
        self.page.locator(".stage-pills .stage-pill", has_text=STREAM_1).click()
        expect(self.page.locator(".grid.run .card h2").last).to_have_text(STREAM_1)

        # Сколько окон страница откроет: каждое окно — новый .dialog в body (ui.js, dialog)
        self.page.evaluate("""() => {
            window.dialogsShown = 0;
            new MutationObserver((records) => records.forEach((record) => record.addedNodes.forEach((node) => {
                if (node.nodeType === 1 && (node.matches(".dialog") || node.querySelector(".dialog"))) window.dialogsShown += 1;
            }))).observe(document.body, { childList: true });
        }""")
        dialog = self.page.locator(".dialog")

        self.page.locator("button", has_text=t("menu.main.tab.run.reset_stage")).click()
        expect(dialog).to_be_visible()
        question = plain(dialog.inner_text())

        with self.page.expect_response(lambda response: "/action" in response.url):
            self.dialogButton(t("web.reset_yes")).click()

        # Дальше либо очередь действий пустеет (вопрос был один), либо открывается второе окно
        self.page.wait_for_function("() => pendingActs === 0 || window.dialogsShown > 1")
        self.assertEqual(self.page.evaluate("() => window.dialogsShown"), 1, "второй вопрос после «Убрать»")
        self.assertRegex(question, keyPattern("web.confirm_reset", name=STREAM_1))
        self.assertRegex(question, keyPattern("web.run.confirm_reset_joint", line=JOINT_LINE, number=2))

        expect(dialog).to_have_count(0)
        answer = self.load("answer.json")
        self.assertFalse([name for pair in self.copies.items() for name in pair if hasLessons(answer, name)])

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.confirm_reset")
        self.known("web.run.confirm_reset_joint")

    def test_reset_with_only_shared_lessons_says_why(self):
        """AC-41 на странице: у Потока 2 свои курсы без уроков, а общие уроки «ЕГЭ основной» стоят. Кнопка
        «Убрать из расписания» закрыта, и подсказка у неё — тот же текст, что отказ сервера:
        web.run.nothing_to_reset_joint.
        """
        self.useJoint()
        self.open("run")
        self.page.locator(".stage-pills .stage-pill", has_text=STREAM_2).click()
        expect(self.page.locator(".grid.run .card h2").last).to_have_text(STREAM_2)
        button = self.page.locator("button", has_text=t("menu.main.tab.run.reset_stage"))

        expect(button).to_be_disabled()
        expect(button).to_have_attribute("title", t("web.run.nothing_to_reset_joint"))

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.run.nothing_to_reset_joint")

    # ------------------------------------------------------------------ AC-30: вариант Потока 1 двигает общие уроки

    def test_stream_1_variant_moving_shared_lessons_is_marked(self):
        """AC-30: вариант Потока 1, который переставляет «ЕГЭ основной — Математику», помечен «Если
        принять, уроки «ЕГЭ основной» Потока 2 тоже переедут на другое время» (web.preview.joint_moves); у варианта, который общих уроков
        не трогает, ``jointMoved`` пуст, у сдвигающего — линейка, Поток 2 и 2 урока.
        """
        settings, answer = self.useJoint()

        # Поток 1 ещё не начался: идущие уроки вариант не двигает (как в test_web_tab_preview.sourceVariant)
        shiftStream(settings, 1, "2026-10-12")

        self.save("settings.json", settings)
        same = {name: copy.deepcopy(answer[name]) for name in stageCourses(settings, "1") if name in answer}
        moved = {**same, MATH_1: courseWeek("Математика", "Математика #1", (1, 0), (3, 0))}
        saveVariant(self.folder, "1", 1, moved)
        saveVariant(self.folder, "1", 2, same)

        self.open("preview")
        self.page.locator(".segmented button", has_text=STREAM_1).click()
        expect(self.page.locator(".segmented button.active")).to_have_text(STREAM_1)
        self.page.locator(".week-head .stage-tab", has_text=f"{t('menu.main.tab.run.variant')} 1").click()
        expect(self.page.locator(".preview-week .week-head h2")).to_contain_text(f"{t('menu.main.tab.run.variant')} 1")

        expect(self.page.locator("body")).to_contain_text(keyPattern("web.preview.joint_moves", line=JOINT_LINE, name=JOINT_LINE, number=2))

        data = {item["number"]: item for item in self.variants("1")["variants"]}
        self.assertEqual([(item["line"], item["number"], item["lessons"]) for item in data[1].get("jointMoved", [])], [(JOINT_LINE, 2, 2)])
        self.assertEqual(data[2].get("jointMoved"), [])

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.preview.joint_moves")

    # ------------------------------------------------------------------ AC-31: «Преподаватели»

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

    def test_shared_hours_are_together_cells(self):
        """AC-31: у «Математика #1» в «Когда удобно» этапа «Поток 2» часы общего урока (пн и ср,
        1-й урок) — ячейка «вместе» с иконкой link: не красная накладка и не серое «занят».
        """
        self.useJoint()
        self.openTeacher("Математика #1", STREAM_2)
        link = self.page.evaluate("() => ICONS.link || null")

        for day in (0, 2):
            with self.subTest(day=day):
                cell = self.weekCell(day, 0)
                expect(cell.locator(".state.bad")).to_have_count(0)
                expect(cell).not_to_contain_text(t("menu.main.tab.teachers.commitment_busy"))
                expect(cell).not_to_contain_text(t("web.teachers.clash"))
                self.assertTrue(link, "в ui.js нет иконки link")
                self.assertIn(link, cell.locator("svg.icon path").evaluate_all("(paths) => paths.map((path) => path.getAttribute('d'))"))
                expect(cell).to_contain_text(t("menu.main.tab.teachers.commitment_joint"))

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("menu.main.tab.teachers.commitment_joint")

    def test_cannot_under_shared_lesson_is_removed_by_click(self):
        """AC-39: у «Математика #1» на этапе «Поток 2» в пн 1-м уроком «не может», а там общий урок. Ячейка
        «вместе» подписана «не может»; щелчок по ней снимает отметку, ячейка остаётся «вместе», а
        предупреждения на «Расписании» больше нет.
        """
        settings, _ = self.useJoint()
        markCannot(settings, "Математика #1", "2", (0, 0))
        self.save("settings.json", settings)
        self.openTeacher("Математика #1", STREAM_2)
        cell = self.weekCell(0, 0)

        expect(cell).to_contain_text(t("menu.main.tab.teachers.commitment_joint"))
        expect(cell).to_contain_text(t("menu.main.tab.teachers.busy"))

        with self.page.expect_response(lambda response: "/action" in response.url):
            cell.locator(".state").click()

        expect(cell).not_to_contain_text(t("menu.main.tab.teachers.busy"))
        expect(cell).to_contain_text(t("menu.main.tab.teachers.commitment_joint"))
        self.assertNotIn([0, 0], self.load("settings.json")["teachers"]["Математика #1"]["availability"]["2"]["free"])

        self.open("view")
        expect(self.page.locator(".view-list")).to_be_visible()
        expect(self.page.locator(".clash-card", has_text=t("web.view.joint_cannot_title"))).to_have_count(0)

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.teachers.joint_cannot_hint")

    def test_legend_names_together_cell_with_cannot(self):
        """AC-39: пока под общим уроком «не может», в легенде «Когда удобно» есть пометка
        web.teachers.joint_cannot_legend (жёлтая ячейка «вместе»); после щелчка по ячейке её нет.
        """
        settings, _ = self.useJoint()
        markCannot(settings, "Математика #1", "2", (0, 0))
        self.save("settings.json", settings)
        self.openTeacher("Математика #1", STREAM_2)
        legend = self.page.locator(".teacher-week .legend")

        expect(legend).to_contain_text(t("web.teachers.joint_cannot_legend"))

        with self.page.expect_response(lambda response: "/action" in response.url):
            self.weekCell(0, 0).locator(".state").click()

        expect(self.weekCell(0, 0)).not_to_contain_text(t("menu.main.tab.teachers.busy"))
        expect(legend).not_to_contain_text(t("web.teachers.joint_cannot_legend"))

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.teachers.joint_cannot_legend")

    def test_copy_in_course_table_is_fixed_as_in_stream_1(self):
        """AC-31: в таблице курсов «Математика #1» ячейка «Поток 2 × ЕГЭ основной» — неизменяемая
        «как в Потоке 1»: не кнопка, щелчок ничего не отправляет на сервер.
        """
        self.useJoint()
        self.openTeacher("Математика #1", STREAM_2)
        table = self.page.locator(".course-tables table").first
        expect(table).to_be_visible()
        heads = [plain(text) for text in table.locator("thead th").all_inner_texts()]
        row = table.locator("tbody tr", has=self.page.locator("th", has_text=re.compile(rf"^{STREAM_2}$")))
        cell = row.locator("td").nth(heads.index(JOINT_LINE) - 1)

        expect(cell).to_contain_text(keyPattern("web.state.joint", number=1))
        expect(cell.locator("button")).to_have_count(0)

        sent = []
        self.page.on("request", lambda request: "/action" in request.url and sent.append(request.url))
        cell.click()
        self.page.wait_for_timeout(300)
        self.assertEqual(sent, [])

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.state.joint")

    # ------------------------------------------------------------------ источник идёт только через копию

    def test_locked_tip_names_copy_start(self):
        """Поток 1 начнётся позже (FUTURE), Поток 2 уже идёт (PAST), «ЕГЭ основной» Потока 2 присоединяется
        к Потоку 1. У «Математики» линейки «ЕГЭ основной» Потока 1 ячейки закрыты замочком, и подсказка
        «Курс идёт с …» называет 01.09.2026 (начало Потока 2, ``runningSince``), а не 11.01.2027 (своё
        начало): иначе завуч читает «Курс идёт с 11.01.2027», хотя курс уже не меняется.
        """
        settings, answer = self.useJoint(mark=False)
        shiftStream(settings, 1, FUTURE)
        shiftStream(settings, 2, PAST)
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.save("settings.json", settings)
        self.save("answer.json", answer)

        self.open("classes")
        self.pick(STREAM_1, JOINT_LINE)
        locked = self.row("Математика").locator(".locked")
        expect(locked.first).to_be_visible()
        tips = locked.evaluate_all("(cells) => cells.map((cell) => cell.dataset.tip || '')")

        self.assertTrue(tips, "у источника нет закрытых ячеек")

        for tip in tips:
            self.assertRegex(tip, keyPattern("web.course_locked", date="01.09.2026"))
            self.assertNotIn("11.01.2027", tip)


def markRealProject(folder):
    """PREPARE: «ЕГЭ основной» Потока 2 проекта 2026/27 присоединяется к Потоку 1 (``builders.markJoint``
    прямо в settings.json и answer.json): у копий уроки Потока 1 ещё до сборки вариантов.
    """
    settings, answer = readJson(f"{folder}/settings.json"), readJson(f"{folder}/answer.json")
    markJoint(settings, 2, JOINT_LINE, 1, answer)

    for name, data in (("settings.json", settings), ("answer.json", answer)):
        with open(f"{folder}/{name}", "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False)


class JointPreviewTest(JointCase):
    """Варианты Потока 2 проекта 2026/27 с линейкой «ЕГЭ основной», которая присоединяется к Потоку 1."""
    VARIANTS_STAGE = "2"
    PREPARE = staticmethod(markRealProject)

    def test_copy_cards_in_stream_2_variant(self):
        """AC-30: в варианте Потока 2 у каждого урока копии подпись «вместе с Потоком 1», без пунктира
        «новое»; уроки копий в варианте — как у принятого Потока 1.
        """
        self.open("preview")
        expect(self.page.locator(".segmented button.active")).to_have_text(STREAM_2)
        settings, answer = self.load("settings.json"), self.load("answer.json")
        copies = jointCopies(settings)
        self.assertTrue(copies)
        expected = sum(len(lessonsOf(answer[source])) for source in copies.values() if source in answer)
        self.assertGreater(expected, 0)

        note = keyPattern("web.lesson.joint", number=1)
        expect(self.page.locator(PREVIEW_LESSONS, has_text=note)).to_have_count(expected)
        expect(self.page.locator(f"{PREVIEW_LESSONS}.fresh", has_text=note)).to_have_count(0)

        for variant in self.variants("2")["variants"]:
            for copy_name, source in copies.items():
                self.assertEqual(cells(variant["answer"].get(copy_name)), cells(answer.get(source)), (variant["number"], copy_name))

        # Тексты взяты из ru.hjson, а не показаны ключами
        self.known("web.lesson.joint")


class JointSeparateSubjectTest(JointCase):
    """Предмет, который появился в линейке Потока 1 уже после отметки (замечание проверки)."""

    def test_subject_added_to_source_later_can_join(self):
        """«Информатику» добавили в «ЕГЭ основной» Потока 1 после того, как Поток 2 присоединили
        к Потоку 1. В Потоке 2 у неё не «в Потоке 1 этого предмета нет», а «не присоединён к Потоку 1…»
        и кнопка «Присоединить к Потоку 1»: она отправляет setJoint с тем же потоком, и курс становится копией.
        """
        settings, _ = self.useJoint()
        addCourse(settings, 1, JOINT_LINE, "Информатика", 1)
        self.save("settings.json", settings)
        self.open("classes")
        self.pick(STREAM_2, JOINT_LINE)
        row = self.row("Информатика")

        expect(row).to_contain_text(keyPattern("web.classes.joint_separate", number=1))
        expect(row).not_to_contain_text(keyPattern("web.classes.joint_missing", number=1))

        response = self.act(lambda: row.locator("button", has_text=keyPattern("web.classes.joint_join", number=1)).click())

        request = response.request.post_data_json
        self.assertEqual((request["action"], int(request["args"]["source"])), ("setJoint", 1))
        self.assertEqual(self.marks(), {MATH_2: 1, RUS_2: 1, INFO_2: 1})
        expect(self.row("Информатика").locator(".locked")).to_have_count(3)

        # Тексты взяты из ru.hjson, а не показаны ключами
        for key in ("web.classes.joint_separate", "web.classes.joint_join", "web.classes.joint_join_hint", "web.classes.joint_on"):
            self.known(key)
