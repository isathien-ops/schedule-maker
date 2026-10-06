"""Вкладка «Запуск»: ползунок важности, точное число, свои правила (пустое поле лимита — не 0),
составление с переходом на «Предпросмотр» и остановка, подпись с прогнозом у галочки «Оставить
уже принятые уроки на месте», совпавшие варианты и конец сборки, когда решатель закончил подбор
раньше (сборка поддельным решателем FakeSolver из tests/real_project.py)."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import os
from unittest import mock

from src.modules.translate import tr
from src.modules.functions.stages import stageCourses
from src.web import build
from tests.engine import NOTHING_TO_SOLVE
from tests.builders import markCannot
from tests.real_project import CHEM_OGE_2, RUS_8_2, FakeSolver, emptied, forecastText, keyPattern, lessons, relocated, unstaffed
from tests.ui.base import UICase, expect, t

KEY = "softSubjectPair"
# Курс Потока 1, который идёт (в расписании, все уроки на месте)
CHEM_OGE_1 = "Поток 1 — ОГЭ — Химия"


class RunTest(UICase):
    """Правки «Запуска» и сборка вариантов настоящим решателем (1 млн шагов, 2 варианта) или поддельным."""

    def sliderRow(self, key):
        """Строка «Что важно в расписании» с ползунком правила key."""
        return self.page.locator(".slider-row", has_text=t(f"weights.{key}"))

    def test_importance_slider(self):
        """Ползунок на «Очень важно»: вес правила = обычный × 10, подпись деления меняется."""
        self.open("run")
        state = self.state()
        base = state["weightDefaults"][KEY]
        # В проекте вес 1 500 при обычном 1 000: ползунок на ближайшем делении «Средне», рядом — «своё значение»
        self.assertEqual((state["weights"][KEY], base), (1500, 1000))
        row = self.sliderRow(KEY)
        expect(row.locator(".level-head b")).to_have_text(t("web.level.importance.2"))
        expect(row.locator(".level-note")).to_have_text(t("web.level.own").replace("{value}", "1 500"))

        # Ползунок отпустили на последнем делении: input (подпись) и change (сохранение)
        self.act(lambda: row.locator("input[type=range]").evaluate(
            "(range) => { range.value = 4; range.dispatchEvent(new Event('input', {bubbles: true})); range.dispatchEvent(new Event('change', {bubbles: true})); }"))

        self.assertEqual(self.state()["weights"][KEY], base * 10)
        expect(self.sliderRow(KEY).locator(".level-head b")).to_have_text(t("web.level.importance.4"))
        expect(self.sliderRow(KEY).locator("input[type=range]")).to_have_value("4")

    def test_exact_weight_number(self):
        """Щелчок по «вес N» — поле для точного числа; Enter сохраняет его, подпись «своё значение»."""
        self.open("run")
        row = self.sliderRow(KEY)
        row.locator(".level-note").click()
        field = row.locator("input.level-input")
        expect(field).to_be_focused()
        field.fill("777")
        self.act(lambda: field.press("Enter"))

        self.assertEqual(self.state()["weights"][KEY], 777)
        expect(self.sliderRow(KEY).locator(".level-note")).to_have_text(t("web.level.own").replace("{value}", "777"))

    def test_custom_rule_add_and_delete(self):
        """Своё правило: без времени — ошибка и окно открыто; с днём и временем — карточка и запись
        в проекте; удаление — после подтверждения."""
        self.allowRefusals()
        self.open("run")
        self.assertEqual(self.state()["penalties"], [])
        expect(self.page.locator(".card", has_text=t("menu.main.tab.run.custom_title")).locator("p.hint")).to_have_text(t("web.no_penalties"))

        self.page.locator("button", has_text=t("menu.main.tab.run.custom_add")).click()
        dialog = self.page.locator(".dialog")
        dialog.get_by_placeholder(t("penalty.dialog.name_placeholder")).fill("Не в субботу утром")
        dialog.locator(".checks.days label", has_text=t("abbreviate.day.5")).locator("input").check()
        self.act(lambda: self.dialogButton(t("penalty.dialog.save")).click())
        self.toast(t("penalty.dialog.error_slots"))
        expect(dialog).to_be_visible()

        dialog.locator(".checks:not(.days) label", has_text="10:00 - 11:30").locator("input").check()
        self.act(lambda: self.dialogButton(t("penalty.dialog.save")).click())

        expect(dialog).to_have_count(0)
        penalties = self.state()["penalties"]
        self.assertEqual([(item["name"], item["template"], item["params"]["days"], item["params"]["times"]) for item in penalties],
                         [("Не в субботу утром", "time", [5], ["10:00 - 11:30"])])
        card = self.page.locator(".item-card", has_text="Не в субботу утром")
        expect(card).to_be_visible()

        card.locator("button", has_text=t("menu.main.tab.run.custom_delete")).click()
        expect(self.page.locator(".dialog")).to_contain_text(t("menu.main.tab.run.custom_confirm_delete").replace("{name}", "Не в субботу утром"))
        self.act(lambda: self.dialogButton(t("web.common.yes")).click())

        expect(card).to_have_count(0)
        self.assertEqual(self.state()["penalties"], [])

    def test_make_variants(self):
        """«Составить варианты» для потока 2: идёт сборка (кнопка «Остановить»), затем открывается
        «Предпросмотр» с двумя вариантами, они же лежат в папке проекта."""
        self.open("run")
        self.page.locator(".stage-pills .stage-pill", has_text="Поток 2").click()
        expect(self.page.locator(".grid.run .card h2").last).to_have_text("Поток 2")
        # Потоку не хватает уроков — видна галочка «оставить принятые уроки», по умолчанию включена
        expect(self.page.locator(".keep-check input")).to_be_checked()

        self.act(lambda: self.page.locator("button", has_text=t("menu.main.tab.run.run_stage")).click())
        expect(self.page.locator("button", has_text=t("menu.main.tab.run.stop"))).to_be_visible()

        expect(self.page.locator(".page-head h1")).to_contain_text(t("menu.main.tab.preview"), timeout=120000)
        self.toast(t("web.run.variants_ready_short").replace("{count}", "2"))
        expect(self.page.locator("table.variants th.variant-head")).to_have_count(2)

        stage = next(item for item in self.state()["stages"] if item["key"] == "2")
        self.assertEqual(stage["variants"], 2)
        self.assertEqual(sorted(name for name in os.listdir(f"{self.folder}/stages/2.variants") if name[0].isdigit()), ["1.json", "2.json"])
        # В меню у «Предпросмотра» — число этапов с вариантами, которые ещё не составлены полностью
        expect(self.page.locator(".nav-item", has_text=t("menu.main.tab.preview")).locator(".count")).to_have_text("1")

    def test_stop_build(self):
        """«Остановить» прерывает долгую сборку: вариантов нет, снова доступна кнопка «Составить варианты»."""
        self.apiAct("setNumber", key="iterations", value=2000000000)
        self.open("run")
        self.page.locator(".stage-pills .stage-pill", has_text="Поток 2").click()

        self.act(lambda: self.page.locator("button", has_text=t("menu.main.tab.run.run_stage")).click())
        stop = self.page.locator("button", has_text=t("menu.main.tab.run.stop"))
        expect(stop).to_be_visible()
        self.act(lambda: stop.click())

        expect(self.page.locator("button", has_text=t("menu.main.tab.run.run_stage"))).to_be_enabled(timeout=30000)
        expect(self.page.locator(".page-head h1")).to_contain_text(t("menu.main.tab.run"))
        self.assertEqual(next(item for item in self.state()["stages"] if item["key"] == "2")["variants"], 0)
        self.page.locator(".log-details summary").click()
        # Вариантов у этапа нет — журнал говорит «вариантов нет», а не «прежние варианты остались»
        expect(self.page.locator("pre.console")).to_contain_text(t("web.run.stopped_none"))

        # Оформление строк журнала — по уровню, который прислал сервер, а не по тексту строки
        log = self.client.get(f"/api/project/{self.NAME}/job").get_json()["log"]
        classes = {"head": "c-head", "done": "c-done", "warn": "c-warn", "progress": "c-dim"}
        self.assertIn("head", [line["level"] for line in log])
        shown = self.page.evaluate("() => [...document.querySelectorAll('pre.console span')].map((span) => [span.textContent, span.className])")
        self.assertEqual(shown, [[f"{line['text']}\n", classes.get(line["level"], "")] for line in log])

    def test_settings_locked_while_building(self):
        """Пока идёт сборка, веса, тщательность, число вариантов и свои правила закрыты: поля и кнопки
        недоступны, «вес N» не открывает поле для числа, над карточками — подпись почему. После
        «Остановить» всё снова доступно, подписи нет."""
        self.apiAct("savePenalty", penalty={"name": "Не в субботу", "template": "time", "weight": 100,
                                            "params": {"target": "all", "value": "", "days": [5], "times": ["10:00 - 11:30"]}})
        self.apiAct("setNumber", key="iterations", value=2000000000)
        self.open("run")
        self.page.locator(".stage-pills .stage-pill", has_text="Поток 2").click()
        left = self.page.locator(".grid.run > .stack").first
        controls = left.locator("input, button")
        count = controls.count()
        # Ползунки весов, тщательности и правила, число вариантов, «Изменить», «Удалить», «Добавить правило»
        self.assertEqual(count, len(self.state()["weights"]) + 6)
        expect(left.locator(".build-note")).to_have_count(0)

        self.act(lambda: self.page.locator("button", has_text=t("menu.main.tab.run.run_stage")).click())
        stop = self.page.locator("button", has_text=t("menu.main.tab.run.stop"))
        expect(stop).to_be_visible()

        expect(left.locator(".build-note")).to_have_text(t("web.run.locked"))
        expect(left.locator("input:disabled, button:disabled")).to_have_count(count)
        expect(left.locator(".level-note.editable")).to_have_count(0)
        self.sliderRow(KEY).locator(".level-note").click()
        expect(left.locator("input.level-input")).to_have_count(0)

        self.act(lambda: stop.click())
        expect(self.page.locator("button", has_text=t("menu.main.tab.run.run_stage"))).to_be_enabled(timeout=30000)
        expect(left.locator(".build-note")).to_have_count(0)
        expect(left.locator("input:enabled, button:enabled")).to_have_count(count)
        self.sliderRow(KEY).locator(".level-note").click()
        expect(left.locator("input.level-input")).to_be_focused()

    def test_build_opens_preview_from_top_and_remembers_it(self):
        """Сборка закончилась — «Предпросмотр» открывается как обычный переход: страница сверху,
        вкладка запомнена (после перезагрузки снова «Предпросмотр»)."""
        self.open("run")
        self.page.locator(".stage-pills .stage-pill", has_text="Поток 2").click()
        self.page.evaluate("() => window.scrollTo(0, 400)")
        self.assertGreater(self.page.evaluate("() => window.scrollY"), 0)

        self.act(lambda: self.page.locator("button", has_text=t("menu.main.tab.run.run_stage")).click())
        expect(self.page.locator(".page-head h1")).to_contain_text(t("menu.main.tab.preview"), timeout=120000)
        expect(self.page.locator("table.variants th.variant-head")).to_have_count(2)
        self.assertEqual(self.page.evaluate("() => window.scrollY"), 0)

        self.page.reload()
        expect(self.page.locator(".page-head h1")).to_contain_text(t("menu.main.tab.preview"))

    def test_empty_daily_limit_is_not_zero(self):
        """«Не больше N уроков в день» с пустым полем: на сервер уходит пустое значение (а не 0),
        сервер отказывает, окно остаётся открытым, правило не сохраняется."""
        self.allowRefusals()
        self.open("run")
        self.page.locator("button", has_text=t("menu.main.tab.run.custom_add")).click()
        dialog = self.page.locator(".dialog")
        dialog.get_by_placeholder(t("penalty.dialog.name_placeholder")).fill("Лимит")
        dialog.locator("select").first.select_option("daily_limit")
        dialog.locator("input[type=number]").fill("")

        with self.page.expect_request(lambda request: "/action" in request.url) as info:
            self.dialogButton(t("penalty.dialog.save")).click()

        self.idle()
        self.assertIsNone(info.value.post_data_json["args"]["penalty"]["params"]["limit"])
        expect(dialog).to_be_visible()
        self.assertEqual(self.state()["penalties"], [])

    def stageAnswers(self):
        """Два разных ответа решателя для потока 2: его курсы из принятого расписания и они же
        с уроком химии ОГЭ в другом месте.
        """
        answer = self.load("answer.json")
        base = {name: answer[name] for name in stageCourses(self.load("settings.json"), "2") if name in answer}

        return base, {**base, CHEM_OGE_2: relocated(base[CHEM_OGE_2], 0, 2)}

    def fakeBuild(self, outputs, lines):
        """Подмены для сборки поддельным решателем: запуск номер n возвращает outputs[n - 1] и печатает lines.
        Файл решателя должен быть (подойдёт любой), к программе процесс не привязывается.
        """
        solver = FakeSolver(output=lambda number: outputs[number - 1], lines=lines)

        return (mock.patch.object(build, "SOLVER", os.path.abspath(__file__)), mock.patch.object(build.subprocess, "Popen", solver),
                mock.patch.object(build, "closeWithProgram"))

    def buildStream2(self, outputs, lines):
        """«Составить варианты» для потока 2 поддельным решателем; ждёт перехода на «Предпросмотр»."""
        self.open("run")
        self.page.locator(".stage-pills .stage-pill", has_text="Поток 2").click()
        path, popen, bind = self.fakeBuild(outputs, lines)

        with path, popen, bind:
            self.act(lambda: self.page.locator("button", has_text=t("menu.main.tab.run.run_stage")).click())
            expect(self.page.locator(".page-head h1")).to_contain_text(t("menu.main.tab.preview"), timeout=30000)

    def test_keep_forecast_caption(self):
        """У галочки «Оставить уже принятые уроки на месте» — сколько уроков останется на месте и
        сколько подберёт программа (forecast этапа с сервера): с галочкой 41 из 62, без неё — 0 из 62.
        Где галочки нет (поток 1 весь идёт, доп. курсы стоят целиком), нет и подписи.
        """
        forecast = next(item["forecast"] for item in self.state()["stages"] if item["key"] == "2")
        self.assertEqual((forecast["keep"], forecast["fresh"]),
                         ({"pinned": 41, "total": 62, "free": 21, "noTeacher": 0}, {"pinned": 0, "total": 62, "free": 62, "noTeacher": 0}))

        self.open("run")
        self.page.locator(".stage-pills .stage-pill", has_text="Поток 2").click()
        check = self.page.locator(".keep-check input")
        caption = self.page.locator(".keep-forecast")
        expect(check).to_be_checked()
        expect(caption).to_have_text(tr("web.run.pin_forecast", **forecast["keep"]))

        check.uncheck()
        expect(caption).to_have_text(tr("web.run.pin_forecast", **forecast["fresh"]))
        check.check()
        expect(caption).to_have_text(tr("web.run.pin_forecast", **forecast["keep"]))

        for label in ("Поток 1", t("stage.extra")):
            self.page.locator(".stage-pills .stage-pill", has_text=label).click()
            expect(self.page.locator(".grid.run .card h2").last).to_have_text(label)
            expect(self.page.locator(".keep-check")).to_have_count(0)
            expect(caption).to_have_count(0)

    def test_keep_forecast_names_lessons_without_teacher(self):
        """Курс потока 2 (1 урок) никто не может вести: подпись у галочки не обещает его подобрать —
        «подберёт программа» на 1 меньше и хвост «без преподавателя (не ставятся): 1», с галочкой и без.
        """
        self.save("settings.json", unstaffed(self.load("settings.json"), RUS_8_2, "Русский язык"))
        forecast = next(item["forecast"] for item in self.state()["stages"] if item["key"] == "2")
        self.assertEqual((forecast["keep"]["free"], forecast["keep"]["noTeacher"]), (20, 1))

        self.open("run")
        self.page.locator(".stage-pills .stage-pill", has_text="Поток 2").click()
        caption = self.page.locator(".keep-forecast")
        expect(caption).to_have_text(forecastText(forecast["keep"]))
        self.page.locator(".keep-check input").uncheck()
        expect(caption).to_have_text(forecastText(forecast["fresh"]))

    def test_blocked_started_lesson_is_warned_before_and_after_build(self):
        """Идущей химии ОГЭ Потока 1 не хватает урока (часов 3), а её преподаватель отметил «не может»
        под её уроком. До сборки «Запуск» предупреждает (web.run.started_blocked, курс коротко и причина);
        решатель урок не оставил — сообщение о конце сборки говорит, что принять нельзя ни один вариант
        (web.run.variants_unacceptable_short), а не зовёт выбирать.
        """
        settings, answer = self.load("settings.json"), self.load("answer.json")
        settings["classes"]["lessons"][CHEM_OGE_1]["Химия"] = 3
        day, lesson, cell = lessons(answer[CHEM_OGE_1])[0]
        markCannot(settings, cell["teachers"][0], "1", (day, lesson))
        self.save("settings.json", settings)
        for key in ("web.run.started_blocked", "web.run.variants_unacceptable_short"):
            self.assertNotEqual(t(key), key)

        self.open("run")
        self.page.locator(".stage-pills .stage-pill", has_text="Поток 1").click()
        note = self.page.locator(".started-blocked")
        expect(note).to_contain_text(keyPattern("web.run.started_blocked"))
        expect(note).to_contain_text(self.course(CHEM_OGE_1)["short"])
        expect(note).to_contain_text(tr("menu.main.tab.classes.slot_unavailable", detail=cell["teachers"][0]))

        week = emptied(answer[CHEM_OGE_1])
        week[6][1] = {"subject": "Химия", "teachers": cell["teachers"]}
        output = {**{name: answer[name] for name in stageCourses(settings, "1") if name in answer}, CHEM_OGE_1: week}
        path, popen, bind = self.fakeBuild([output] * 10, [])

        with path, popen, bind:
            self.act(lambda: self.page.locator("button", has_text=t("menu.main.tab.run.run_stage")).click())
            expect(self.page.locator(".page-head h1")).to_contain_text(t("menu.main.tab.preview"), timeout=30000)

        self.toast(tr("web.run.variants_unacceptable_short", count=1))

    def test_repeated_variants_are_named(self):
        """Решатель подбирать не стал (строк «Шаг» нет), оба варианта одинаковые: сохранён один,
        сообщение о конце сборки говорит и о совпавшем; в журнале «Запуска» — строка «совпал» и итог.
        """
        same, _ = self.stageAnswers()
        self.buildStream2([same, same], ["Закреплено 62 из 62 уроков, подбирается 0", NOTHING_TO_SOLVE])

        self.toast(t("web.run.variants_all_same_short"))
        expect(self.page.locator("table.variants th.variant-head")).to_have_count(1)
        self.assertEqual(sorted(name for name in os.listdir(f"{self.folder}/stages/2.variants") if name[0].isdigit()), ["1.json"])

        self.tab("run")
        self.page.locator(".log-details summary").click()
        log = self.page.locator("pre.console")
        expect(log).to_contain_text(tr("web.run.variant_repeated", number=2, same=1))
        expect(log).to_contain_text(t("menu.main.tab.run.variants_all_same"))

    def test_build_ends_when_steps_stop_early(self):
        """Решатель остановил подбор раньше: строки «Шаг N из M» оборвались до M. Сборка всё равно
        заканчивается как обычно — «Предпросмотр» с двумя вариантами, а на «Запуске» полосы хода
        уже нет и снова доступна кнопка «Составить варианты».
        """
        lines = [
            "Закреплено 61 из 62 уроков, подбирается 1",
            "Шаг 1000000 из 100000000 | 0.9 с | неудобства: 12786 (лучшее пока 12786)",
            "Остановлено на шаге 2000000 из 100000000: подбирается только 1 урок, лучшее не менялось 1 млн шагов",
        ]
        self.buildStream2(list(self.stageAnswers()), lines)

        self.toast(tr("web.run.variants_ready_short", count=2))
        expect(self.page.locator("table.variants th.variant-head")).to_have_count(2)

        self.tab("run")
        expect(self.page.locator("#run-progress-bar")).to_have_count(0)
        expect(self.page.locator("button", has_text=t("menu.main.tab.run.run_stage"))).to_be_enabled()
        self.page.locator(".log-details summary").click()
        expect(self.page.locator("pre.console")).to_contain_text(lines[-1])
