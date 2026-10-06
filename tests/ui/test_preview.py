"""Вкладка «Предпросмотр»: таблица вариантов, выбор варианта, подписи на карточках уроков,
отклонить / вернуть, принять вариант, выгрузка вариантов в Excel; «Смена преподавателя в подборе»
(.spec/teacher-swap/SPEC.md, AC-17): блок «Кто ведёт», значок «Сменится преподаватель», метка на карточке;
вариант, составленный до начала курса, который уже идёт, или сдвинувший урок курса, шедшего при сборке
(``StaleStartedVariantTest``): «Принять» неактивна, пометка web.preview.stale_started или web.preview.moved_started,
вариант не «лучший» и не выбран сам."""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import collections
import io
import re
import shutil

import openpyxl

from src.modules.functions.model import teacherAvailability
from src.modules.functions.variants import SHORT_LINES, saveBuildStarted, saveVariant
from tests.builders import courseWeek, setHours, stageVariant
from tests.real_project import keyPattern, lessons as lessonsOf
from tests.ui.base import UICase, expect, plain, t
from tests.ui.joint_base import MATH_1, STREAM_1, JointCase

STAGE = "2"
CARDS_JS = """() => [...document.querySelectorAll('.preview-week .lesson')].map((card) => [
    card.querySelector('.l-tag')?.textContent ?? '', card.querySelector('.l-title').textContent,
    card.querySelector('.l-meta')?.textContent ?? '', card.classList.contains('fresh')])"""
# Все подсказки элемента и его потомков (data-tip и title) одной строкой
TIPS_JS = """(element) => [element, ...element.querySelectorAll('[data-tip], [title]')]
    .map((node) => `${node.dataset.tip ?? ''} ${node.getAttribute('title') ?? ''}`).join(' ')"""


def surname(name):
    """Фамилия, как её пишет страница (первое слово имени, domain.js surnames)."""
    return name.split(" ")[0]


class PreviewTest(UICase):
    """Варианты потока 2, составленные заранее (2 варианта)."""
    VARIANTS_STAGE = STAGE

    def week(self):
        """Заголовок недели выбранного варианта."""
        return self.page.locator(".preview-week .week-head h2")

    def chosenTitle(self, number):
        return f"{t('web.preview.week')} — {t('menu.main.tab.run.variant')} {number}"

    def cards(self):
        """Карточки уроков недели: [(метка, предмет, преподаватели, новый ли урок)]."""
        return [(plain(tag), plain(title), meta, fresh) for tag, title, meta, fresh in self.page.evaluate(CARDS_JS)]

    def expectedCards(self, variant, line=None):
        """Карточки, которые должна нарисовать страница для варианта: метка линейки (коротко),
        предмет, фамилии; новый — если в принятом расписании курса нет урока в этом месте."""
        state = self.state()
        lines = {course["name"]: course["line"] for course in state["courses"]}
        joint = {course["name"] for course in state["courses"] if course.get("joint")}
        # Новые уроки отмечаются, только если что-то из курсов варианта уже есть в принятом расписании
        # и сам вариант ещё не принят. Курсы-копии (линейка присоединяется к другому потоку) не в счёт:
        # их уроки задаёт поток-источник — так же считает anyFresh в preview.js
        marking = not variant["accepted"] and any(name in state["answer"] and name not in joint for name in variant["answer"])
        result = []

        for name, week in variant["answer"].items():
            if line and lines.get(name) != line:
                continue

            accepted = {(day, lesson) for day, lesson, _ in lessonsOf(state["answer"].get(name, []))}

            for day, lesson, cell in lessonsOf(week):
                meta = ", ".join(teacher.split(" ")[0] for teacher in cell.get("teachers", [])) or "—"
                fresh = marking and (day, lesson) not in accepted
                result.append((SHORT_LINES.get(lines.get(name, name), lines.get(name, name)), cell["subject"], meta, fresh))

        return result

    def test_manual_stream_choice_is_kept(self):
        """Выбор потока переключателем главнее перескока: у потока 1 расписание принято, у потока 2
        есть непринятые варианты — по умолчанию показан поток 2, но щелчок по «Поток 1» оставляет
        поток 1 (раньше страница сразу перескакивала обратно на поток 2)."""
        shutil.copytree(f"{self.folder}/stages/{STAGE}.variants", f"{self.folder}/stages/1.variants")
        self.open("preview")

        switch = self.page.locator(".segmented")
        expect(switch.locator("button.active")).to_have_text(t("stage.stream") + " " + STAGE)

        switch.locator("button", has_text=t("stage.stream") + " 1").click()
        expect(switch.locator("button.active")).to_have_text(t("stage.stream") + " 1")
        expect(switch.locator("button.active")).to_have_attribute("aria-checked", "true")

    def test_stream_chosen_on_other_tab_wins(self):
        """Ручной выбор на «Предпросмотре» действует, пока поток не сменили на другой вкладке:
        выбран «Поток 1», затем на «Запуске» выбран другой поток — «Предпросмотр» показывает его."""
        shutil.copytree(f"{self.folder}/stages/{STAGE}.variants", f"{self.folder}/stages/1.variants")
        self.open("preview")
        switch = self.page.locator(".segmented")
        switch.locator("button", has_text=t("stage.stream") + " 1").click()
        expect(switch.locator("button.active")).to_have_text(t("stage.stream") + " 1")

        self.tab("run")
        self.page.locator(".stage-pill", has_text=t("stage.stream") + " " + STAGE).click()
        expect(self.page.locator(".stage-pill.active")).to_contain_text(t("stage.stream") + " " + STAGE)

        self.tab("preview")
        expect(self.page.locator(".segmented button.active")).to_have_text(t("stage.stream") + " " + STAGE)

    def test_table_of_variants(self):
        """Таблица: столбец на каждый вариант в порядке оценки, строка «Итого» — суммы штрафов сервера."""
        self.open("preview")
        data = self.variants(STAGE)
        self.assertEqual(len(data["variants"]), 2)

        heads = self.page.locator("table.variants th.variant-head .v-name")
        expect(heads).to_have_text([f"{t('menu.main.tab.run.variant')} {item['number']}" for item in data["variants"]])
        totals = self.page.locator("table.variants tr.total-row td b").all_inner_texts()
        self.assertEqual([int(text.replace(" ", "").replace(" ", "")) for text in totals], [item["metrics"]["total"] for item in data["variants"]])
        # Строки правил: встроенные и итог
        expect(self.page.locator("table.variants tbody tr")).to_have_count(1 + len(data["metrics"]))

    def test_select_variant_and_lesson_cards(self):
        """Клик по столбцу выбирает вариант; карточки недели — ровно уроки этого варианта
        с меткой линейки, предметом и фамилиями; новые уроки обведены."""
        self.open("preview")
        data = self.variants(STAGE)
        first, second = data["variants"]

        expect(self.week()).to_have_text(self.chosenTitle(first["number"]))
        self.assertEqual(collections.Counter(self.cards()), collections.Counter(self.expectedCards(first)))

        self.page.locator("table.variants tr.total-row td").nth(1).click()
        expect(self.week()).to_have_text(self.chosenTitle(second["number"]))
        expect(self.page.locator(".week-head .stage-tab.active")).to_contain_text(f"{t('menu.main.tab.run.variant')} {second['number']}")
        self.assertEqual(collections.Counter(self.cards()), collections.Counter(self.expectedCards(second)))
        self.assertTrue(any(fresh for *_, fresh in self.cards()))

    def test_line_filter(self):
        """«Показать линейку»: на неделе остаются только уроки выбранной линейки; выбор запоминается."""
        self.open("preview")
        first = self.variants(STAGE)["variants"][0]

        self.page.locator(".line-filter .line-chip", has_text="ОГЭ").click()
        expect(self.page.locator(".line-filter .line-chip.active")).to_have_text("ОГЭ")
        expected = self.expectedCards(first, "ОГЭ")
        self.assertTrue(expected)
        self.assertEqual(collections.Counter(self.cards()), collections.Counter(expected))

        self.page.reload()
        expect(self.page.locator(".line-filter .line-chip.active")).to_have_text("ОГЭ")
        self.page.locator(".line-filter .line-chip", has_text=t("web.preview.all_lines")).click()
        self.assertEqual(len(self.cards()), len(self.expectedCards(first)))

    def routeVariants(self, change):
        """Ответ сервера с вариантами потока подменяется: change(data) правит его на месте."""
        def handle(route):
            data = route.fetch().json()
            change(data)
            route.fulfill(json=data)

        self.page.route("**/variants?stage=*", handle)

    def test_all_equal_note_follows_server(self):
        """Пометка «можно принять любой» — по признаку сервера allTied (variants.allTied), а не по
        совпадению сумм штрафов: у варианта может не хватать уроков при той же сумме."""
        def sameTotal(tied):
            def change(data):
                for item in data["variants"]:
                    item["metrics"]["total"] = 100
                    item["best"] = item is data["variants"][0]
                    item["tied"] = tied
                data["allTied"] = tied
            return change

        # Суммы одинаковые, но сервер «ничьей» не признал (у одного из вариантов хуже обязательные правила)
        self.routeVariants(sameTotal(False))
        self.open("preview")
        expect(self.page.locator("table.variants th.variant-head")).to_have_count(2)
        expect(self.page.locator(".card-foot", has_text=t("web.preview.all_equal"))).to_have_count(0)

        # Сервер отметил «ничью» у всех вариантов — пометка есть
        self.page.unroute("**/variants?stage=*")
        self.routeVariants(sameTotal(True))
        self.page.reload()
        expect(self.page.locator(".card-foot")).to_contain_text(t("web.preview.all_equal"))

    def test_reject_and_return(self):
        """«Отклонить»: вариант помечен (файл rejected.json), выбор переходит на другой;
        «Вернуть» снимает отметку."""
        self.open("preview")
        first, second = self.variants(STAGE)["variants"]

        self.act(lambda: self.page.locator(".week-head button", has_text=t("web.preview.reject")).click())
        self.assertEqual(self.load(f"stages/{STAGE}.variants/rejected.json"), {"numbers": [first["number"]]})
        expect(self.week()).to_have_text(self.chosenTitle(second["number"]))
        head = self.page.locator("table.variants th.variant-head", has_text=f"{t('menu.main.tab.run.variant')} {first['number']}")
        expect(head.locator(".badge", has_text=t("web.preview.rejected"))).to_be_visible()
        expect(head).to_have_class(re.compile(r"(^| )rejected( |$)"))

        self.page.locator(".week-head .stage-tab", has_text=f"{t('menu.main.tab.run.variant')} {first['number']}").click()
        expect(self.week()).to_have_text(self.chosenTitle(first["number"]))
        # Отклонённый вариант нельзя принять, пока его не вернули
        expect(self.page.locator(".week-head button", has_text=t("menu.main.tab.preview.accept"))).to_be_disabled()
        self.act(lambda: self.page.locator(".week-head button", has_text=t("web.preview.unreject")).click())

        self.assertEqual(self.load(f"stages/{STAGE}.variants/rejected.json"), {"numbers": []})
        expect(head.locator(".badge", has_text=t("web.preview.rejected"))).to_have_count(0)

    def test_accept_variant(self):
        """«Принять вариант»: после подтверждения уроки варианта — в принятом расписании,
        метка accepted.json, у варианта значок «принят», кнопка неактивна."""
        self.open("preview")
        chosen = self.variants(STAGE)["variants"][0]
        versions = len(self.state()["versions"])

        # Если вариант переставляет уже принятые уроки или ставит преподавателя на два урока сразу,
        # сервер переспрашивает (окно «Принять»)
        asks = bool(chosen["moved"] or chosen["metrics"]["teacherClash"])
        self.act(lambda: self.page.locator(".week-head button", has_text=t("menu.main.tab.preview.accept")).click(), idle=not asks)

        if asks:
            expect(self.page.locator(".dialog")).to_be_visible()
            self.act(lambda: self.dialogButton(t("web.accept_yes")).click())

        self.toast(t("web.preview.accepted_toast").replace("{number}", str(chosen["number"])))
        self.assertEqual(self.load(f"stages/{STAGE}.variants/accepted.json"), {"number": chosen["number"]})
        answer = self.state()["answer"]
        for name, week in chosen["answer"].items():
            self.assertEqual(lessonsOf(answer[name]), lessonsOf(week), name)

        head = self.page.locator("table.variants th.variant-head", has_text=f"{t('menu.main.tab.run.variant')} {chosen['number']}")
        expect(head.locator(".badge", has_text=t("menu.main.tab.preview.accepted"))).to_be_visible()
        expect(self.page.locator(".week-head button", has_text=t("menu.main.tab.preview.accept"))).to_be_disabled()
        expect(self.page.locator(".card-foot")).to_contain_text(t("menu.main.tab.preview.in_schedule"))
        # Перед принятием сохранена версия «Перед: …»
        self.assertEqual(len(self.state()["versions"]), versions + 1)

    def test_export_variants(self):
        """«Скачать варианты»: книга Excel с названием потока в имени файла."""
        self.open("preview")

        with self.page.expect_download() as info:
            self.page.locator("button", has_text=t("web.export_variants.button")).click()

        download = info.value
        self.assertEqual(download.suggested_filename, f"{self.NAME}-{t('web.export_variants.file')}-Поток 2.xlsx")
        with open(download.path(), "rb") as file:
            book = openpyxl.load_workbook(io.BytesIO(file.read()))  # у скачанного файла нет расширения

        self.assertTrue(book.sheetnames)

    def routeTeachers(self, changed=True):
        """Подменяет ответ /variants полями «кто ведёт» (DATA_CONTRACT §7.6), как их даст сервер.

        Курс X — первый курс первого варианта, у которого есть уроки и в варианте, и в принятом расписании;
        A — его преподаватель в расписании, B — преподаватель проекта с другой фамилией. При ``changed``
        в первом варианте все уроки X ведёт B (``teachers``, ``teacherChanges``), в остальных — A,
        и X — в ``teacherCourses``; без ``changed`` везде A и ``teacherCourses`` пуст.
        Возвращает (X, A, B, число уроков X в первом варианте).
        """
        answer = self.state()["answer"]
        first = self.variants(STAGE)["variants"][0]
        course, subject, old = next((name, cell["subject"], cell["teachers"][0]) for name, week in first["answer"].items()
                                    if lessonsOf(week) and name in answer for _, _, cell in lessonsOf(answer[name]) if cell.get("teachers"))
        new = next(name for name in self.load("settings.json")["teachers"] if surname(name) != surname(old))

        def change(data):
            for item in data["variants"]:
                mine = changed and item["number"] == first["number"]

                for _, _, cell in lessonsOf(item["answer"].get(course, [])):
                    cell["teachers"] = [new if mine else old]

                item["teachers"] = {name: sorted({teacher for _, _, cell in lessonsOf(week) for teacher in cell.get("teachers", [])})
                                    for name, week in item["answer"].items() if lessonsOf(week)}
                item["teacherChanges"] = [{"course": course, "subject": subject, "before": [old], "after": [new]}] if mine else []

            data["teacherCourses"] = [course] if changed else []

        self.routeVariants(change)

        return course, old, new, len(lessonsOf(first["answer"][course]))

    def variantsCard(self):
        """Карточка «Варианты» (таблица сравнения и пометки под ней)."""
        return self.page.locator("section.card").filter(has=self.page.locator("table.variants"))

    def test_teacher_change_is_visible(self):
        """AC-17: вариант 1 меняет преподавателя курса X (A → B). В таблице сравнения блок «Кто ведёт»
        (web.preview.teachers_head); ячейка варианта 1 с фамилией B выделена (класс teacher-changed),
        в подсказке — фамилия A («Сейчас ведёт: A»). У варианта значок web.preview.teacher_changes «… 1 курс».
        На неделе варианта 1 у каждого урока X метка web.preview.teacher_new с фамилией B и подсказкой
        с фамилией A; у уроков других курсов метки нет.
        """
        for key in ("web.preview.teachers_head", "web.preview.teacher_changes", "web.preview.teacher_new"):
            self.assertNotEqual(t(key), key, f"в ru.hjson нет текста {key}")

        course, old, new, count = self.routeTeachers()
        self.open("preview")

        expect(self.page.locator("table.variants")).to_contain_text(t("web.preview.teachers_head"))
        changed = self.page.locator("table.variants td.teacher-changed")
        expect(changed).to_have_count(1)
        expect(changed).to_contain_text(surname(new))
        self.assertIn(surname(old), changed.evaluate(TIPS_JS))

        expect(self.variantsCard()).to_contain_text(keyPattern("web.preview.teacher_changes"))
        expect(self.variantsCard()).to_contain_text("1 курс")

        marked = self.page.locator(".preview-week .lesson").filter(has_text=t("web.preview.teacher_new"))
        expect(marked).to_have_count(count)
        self.assertEqual(marked.locator(".l-meta").all_inner_texts(), [surname(new)] * count)

        for index in range(count):
            self.assertIn(surname(old), marked.nth(index).evaluate(TIPS_JS), course)

    def test_no_teacher_block_without_changes(self):
        """AC-17: ``teacherCourses`` пуст и ни один вариант не меняет преподавателей — блока «Кто ведёт»,
        выделенных ячеек, значка «Сменится преподаватель» и меток «новый преподаватель» нет.
        """
        for key in ("web.preview.teachers_head", "web.preview.teacher_changes", "web.preview.teacher_new"):
            self.assertNotEqual(t(key), key, f"в ru.hjson нет текста {key}")

        self.routeTeachers(changed=False)
        self.open("preview")

        expect(self.page.locator("table.variants th.variant-head")).to_have_count(2)
        expect(self.page.locator("table.variants")).not_to_contain_text(t("web.preview.teachers_head"))
        expect(self.page.locator("table.variants td.teacher-changed")).to_have_count(0)
        expect(self.variantsCard()).not_to_contain_text(keyPattern("web.preview.teacher_changes"))
        expect(self.page.locator(".preview-week .lesson").filter(has_text=t("web.preview.teacher_new"))).to_have_count(0)

    def test_no_new_teacher_label_without_teacher(self):
        """Вариант 1 оставляет курс X без преподавателя (у уроков X преподавателей нет, в ``teacherChanges``
        «after» пуст — ranking.changedTeachers). Ячейка X в «Кто ведёт» по-прежнему выделена, с подсказкой
        «Сейчас ведёт: A», а на карточках уроков X метки web.preview.teacher_new нет: нового преподавателя у них нет.
        """
        answer = self.state()["answer"]
        first = self.variants(STAGE)["variants"][0]
        course, subject, old = next((name, cell["subject"], cell["teachers"][0]) for name, week in first["answer"].items()
                                    if lessonsOf(week) and name in answer for _, _, cell in lessonsOf(answer[name]) if cell.get("teachers"))

        def change(data):
            for item in data["variants"]:
                mine = item["number"] == first["number"]

                for _, _, cell in lessonsOf(item["answer"].get(course, [])):
                    cell["teachers"] = [] if mine else [old]

                item["teachers"] = {name: sorted({teacher for _, _, cell in lessonsOf(week) for teacher in cell.get("teachers", [])})
                                    for name, week in item["answer"].items() if lessonsOf(week)}
                item["teachers"] = {name: names for name, names in item["teachers"].items() if names}
                item["teacherChanges"] = [{"course": course, "subject": subject, "before": [old], "after": []}] if mine else []

            data["teacherCourses"] = [course]

        self.routeVariants(change)
        self.open("preview")

        changed = self.page.locator("table.variants td.teacher-changed")
        expect(changed).to_have_count(1)
        expect(changed).to_have_text("—")
        self.assertIn(surname(old), changed.evaluate(TIPS_JS))

        expect(self.week()).to_have_text(self.chosenTitle(first["number"]))
        expect(self.page.locator(".preview-week .lesson .l-meta", has_text="—").first).to_be_visible()
        expect(self.page.locator(".preview-week .lesson").filter(has_text=t("web.preview.teacher_new"))).to_have_count(0)


class StaleStartedVariantTest(JointCase):
    """«Предпросмотр» Потока 1 проекта ``builders.jointProject``. Поток 1 идёт; у ``MATH_1`` нагрузку подняли
    до 3 уроков: курс идёт, но ему не хватает урока. Вариант 1 собран, пока курс ещё не шёл: у курса другие
    часы и преподаватель (сервер его не примет, web.error.variant_stale_started, и отдаёт курс
    в ``staleStarted``). Вариант 2 собран как свежая сборка (уроки из расписания на месте, тот же
    преподаватель) — его принять можно, но у «Математика #1» в часы его уроков отметка «может»: по оценке
    вариант 2 хуже варианта 1.
    """

    def setUp(self):
        super().setUp()
        settings, answer = self.useJoint(mark=False)
        setHours(settings, MATH_1, 3)
        teacherAvailability(settings["teachers"]["Математика #1"], "1")["possible"] += [[0, 0], [2, 0], [4, 0]]
        self.save("settings.json", settings)
        saveVariant(self.folder, "1", 1, stageVariant(settings, answer, **{MATH_1: courseWeek("Математика", "Математика #3", (1, 0), (3, 0), (4, 0))}))
        saveVariant(self.folder, "1", 2, stageVariant(settings, answer, **{MATH_1: courseWeek("Математика", "Математика #1", (0, 0), (2, 0), (4, 0))}))

    def openStream(self):
        """«Предпросмотр», Поток 1."""
        self.open("preview")
        self.page.locator(".segmented button", has_text=STREAM_1).click()
        expect(self.page.locator(".segmented button.active")).to_have_text(STREAM_1)

    def chooseVariant(self, number):
        """«Предпросмотр» Потока 1, выбран вариант ``number``."""
        self.page.locator(".week-head .stage-tab", has_text=f"{t('menu.main.tab.run.variant')} {number}").click()
        expect(self.page.locator(".preview-week .week-head h2")).to_contain_text(f"{t('menu.main.tab.run.variant')} {number}")

    def acceptButton(self):
        return self.page.locator(".week-head button", has_text=t("menu.main.tab.preview.accept"))

    def test_stale_variant_cannot_be_accepted(self):
        """Вариант 1: «Принять» неактивна, пометка web.preview.stale_started называет курс (коротко, как
        в блоке «Кто ведёт»), и то же — в подсказке кнопки. Вариант 2: «Принять» активна, пометки нет.
        """
        data = {item["number"]: item for item in self.variants("1")["variants"]}
        self.assertEqual(data[1]["staleStarted"], [MATH_1])
        self.assertEqual(data[2]["staleStarted"], [])
        self.known("web.preview.stale_started")

        self.openStream()
        note = keyPattern("web.preview.stale_started", courses=self.course(MATH_1)["short"])

        self.chooseVariant(1)
        expect(self.acceptButton()).to_be_disabled()
        expect(self.page.locator(".card-foot")).to_contain_text(note)
        self.assertRegex(self.acceptButton().get_attribute("data-tip") or "", note)

        self.chooseVariant(2)
        expect(self.acceptButton()).to_be_enabled()
        expect(self.page.locator(".card-foot")).not_to_contain_text(keyPattern("web.preview.stale_started"))

    def test_stale_variant_marks(self):
        """Шапка столбца варианта 1 и его вкладка над неделей — «нельзя принять» (web.export_variants.stale, как
        в Excel), у варианта 2 этой пометки нет. Под таблицей у варианта 1 нет пометок «если принять…»
        (переезд уроков, смена преподавателя), а длинная пометка web.preview.stale_started при ширине окна
        1100 переносится по строкам: не выходит за карточку, у страницы нет горизонтальной прокрутки.
        """
        self.newContext({"width": 1100, "height": 800})
        self.openStream()
        stale = t("web.export_variants.stale")
        variant = t("menu.main.tab.run.variant")
        heads = self.page.locator("th.variant-head")

        expect(heads.filter(has_text=f"{variant} 1")).to_contain_text(stale)
        expect(heads.filter(has_text=f"{variant} 2")).not_to_contain_text(stale)
        expect(self.page.locator(".week-head .stage-tab", has_text=f"{variant} 1")).to_contain_text(stale)

        self.chooseVariant(1)
        foot = self.page.locator(".card-foot", has=self.page.locator(".badge", has_text=keyPattern("web.preview.stale_started")))
        expect(foot).not_to_contain_text(keyPattern("web.preview.moved"))
        expect(foot).not_to_contain_text(keyPattern("web.preview.teacher_changes"))

        note = foot.locator(".badge", has_text=keyPattern("web.preview.stale_started")).bounding_box()
        box = foot.bounding_box()
        self.assertLessEqual(note["x"] + note["width"], box["x"] + box["width"])
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"), 0)

    def test_moved_started_variant_cannot_be_accepted(self):
        """Курс шёл уже при сборке (started.json): вариант 1 не «собран до начала», но сдвинул урок идущего
        курса (поле ``movedStarted``, stages.movedStarted). Шапка его столбца — «нельзя принять», «Принять»
        неактивна, пометка web.preview.moved_started называет курс коротко и урок с причиной (у прежнего
        места помехи нет — menu.main.tab.classes.slot_unplaced); то же — в подсказке кнопки.
        """
        saveBuildStarted(self.folder, "1", {MATH_1})
        data = {item["number"]: item for item in self.variants("1")["variants"]}
        self.assertEqual(data[1]["staleStarted"], [])
        self.assertEqual([entry["course"] for entry in data[1]["movedStarted"]], [MATH_1])
        self.assertEqual(data[2]["movedStarted"], [])
        self.known("web.preview.moved_started")

        self.openStream()
        variant = t("menu.main.tab.run.variant")
        expect(self.page.locator("th.variant-head").filter(has_text=f"{variant} 1")).to_contain_text(t("web.export_variants.stale"))

        self.chooseVariant(1)
        short = re.escape(self.course(MATH_1)["short"])
        reason = re.escape(t("menu.main.tab.classes.slot_unplaced"))
        expect(self.acceptButton()).to_be_disabled()
        expect(self.page.locator(".card-foot")).to_contain_text(re.compile(f"{short} — .*{reason}"))
        expect(self.page.locator(".card-foot")).to_contain_text(keyPattern("web.preview.moved_started"))
        # «Этот вариант нельзя принять: …» — общая рамка обеих причин (web.preview.cannot_accept)
        expect(self.page.locator(".card-foot")).to_contain_text(keyPattern("web.preview.cannot_accept"))
        self.assertRegex(self.acceptButton().get_attribute("data-tip") or "", keyPattern("web.preview.moved_started"))

    def test_stale_variant_is_not_best(self):
        """Вариант 1 с лучшей оценкой идёт после варианта 2 и не «лучший»; страница сама выбирает вариант 2."""
        data = {item["number"]: item for item in self.variants("1")["variants"]}
        self.assertLess(data[1]["metrics"]["total"], data[2]["metrics"]["total"])
        self.assertEqual([item["number"] for item in self.variants("1")["variants"]], [2, 1])

        self.openStream()

        expect(self.page.locator(".preview-week .week-head h2")).to_contain_text(f"{t('menu.main.tab.run.variant')} 2")
        expect(self.page.locator(".week-head .stage-tab", has_text=f"{t('menu.main.tab.run.variant')} 1")).not_to_contain_text(t("menu.main.tab.preview.best"))
