"""Действия вкладки «Курсы» (`src/web/tabs/classes.py`).

* ``SectionTests`` — потоки и блоки, линейки и курсы: создание, копирование линейки в другие
  потоки, даты, удаление с вопросом и версией «Перед: …» (курс с пустой неделей — без уроков),
  отказ для неизвестных разделов, новый поток без отметок «не может» пропавшего потока;
* ``HoursAndPinsTests`` — часы курса и закреплённые уроки: ограничение нагрузкой, перенос уроков
  в расписании, два урока в один день, занятое время, часы зафиксированного курса не растут;
* ``CourseTeacherTests`` — преподаватель курса: курс, который ещё не начался, курс, который уже
  идёт (только свободный преподаватель), лимит курсов, замена в расписании и вариантах;
* ``JointLineTests`` — «Линейка присоединяется к Потоку N» (.spec/joint-lines/SPEC.md): действие
  setJoint (включение, вопрос и версия, снятие, отказы), закрытые поля курса-копии, изменения
  источника, которые переходят в копию, новый курс и новый поток, удаление источника.
  Основа — проект ``builders.jointProject`` вместо данных 2026/27 (``RealProjectCase.useProject``);
* ``JointConflictTests`` — то же после проверки: отметка, при которой уроки источника мешают
  урокам потока-копии (вопрос с помехами), и сообщение об отметке;
* ``JointCannotTests`` — AC-39: отметка, при которой общие уроки встают в часы, где у их
  преподавателя на этапе потока-копии «не может», — не запрет, а вопрос;
* ``JointCopyLineTests`` — «Скопировать в другие потоки» в присоединённую линейку (новым копиям —
  уроки источника, без новых копий answer.json не переписывается) и смена источника, при которой
  общие уроки переезжают в часы «не может»;
* ``JointQuestionTests`` — вопрос setJoint: курсы, уроки которых уберутся (источник без уроков, бывшие
  копии при смене источника), этапы, варианты которых составить заново (помеха в другом потоке),
  и отказ, если в линейке источника нет ни одного такого же предмета;
* ``StartedSourceTests`` — источник, который «идёт» только через свою копию: удаление и «Скопировать
  в другие потоки» не называют его поток начавшимся.

Основа — `RealProjectCase` из `tests/real_project.py`: копия реального проекта 2026/27, «сегодня»
04.10.2026, действия идут через сервер, как со страницы (POST /api/project/<имя>/action).
Проверяется, что сервер защищает курсы, которые уже идут, переспрашивает (ответ с "confirm")
перед опасными действиями, сохраняет версии «Перед: …» и при отказе не портит файлы проекта.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import os

from src.modules.translate import tr, translate
from src.modules.functions.courses import addCourse, removeCourses, setSectionEnd, setTeacherSubjects
from src.modules.functions.model import hasLessons
from src.modules.functions.variants import loadVariants, saveVariant, variantsDir
from src.web.project import lessonsText, slotText
from tests.builders import JOINT_LINE, JOINT_PIN_TEACHER, LEVEL_LINE, OWN_LINE, courseWeek, jointCourse, jointProject, markCannot, markJoint, shiftStream
from tests.real_project import (
    keyPattern,
    CHEM_10_2, CHEM_OGE_2, PHYS_PRO_1, RUS_8_2, RUS_BASE_1, RUS_BASE_2, RUS_PRO_2, RealProjectCase, emptied, lessons
)

# Курсы проекта builders.jointProject: источники в Потоке 1 и будущие копии в Потоке 2
MATH_1, MATH_2 = jointCourse(1, "Математика"), jointCourse(2, "Математика")
RUS_1, RUS_2 = jointCourse(1, "Русский язык"), jointCourse(2, "Русский язык")
BIO_1, BIO_2 = jointCourse(1, "Биология"), jointCourse(2, "Биология")
INF_2 = jointCourse(2, "Информатика")
MATH_3, MATH_LEVEL_1, OWN_3 = jointCourse(3, "Математика"), jointCourse(1, "Математика", LEVEL_LINE), jointCourse(3, "Математика", OWN_LINE)
OLD_TEACHER, NEW_TEACHER = "Математика #1", "Математика #3"
# Поток 1 кончается до начала Потока 3 (11.01.2027), а Поток 2 (с 23.11.2026, без конца) — нет
STREAM_1_END = "2026-12-31"

# Даты начала потока относительно «сегодня» тестов (04.10.2026): ещё не начался / уже идёт
FUTURE, PAST = "2026-10-12", "2026-09-14"


def part(key, before="{"):
    """Неизменная часть перевода `key` до первой подстановки — чтобы искать её в тексте ответа."""
    return translate(key).split(before)[0]


class SectionTests(RealProjectCase):
    """Потоки и блоки, линейки, курсы и их даты."""
    NAME = "__test_sections__"

    def names(self):
        """Имена всех курсов проекта."""
        return [item["name"] for item in self.state()["courses"]]

    def test_new_stream_copies_lines_and_starts_on_monday(self):
        """Новый поток: через 7 недель после последнего, с понедельника, с линейками предыдущего потока."""
        body = self.ok("newStream")
        self.assertEqual(body["section"], 3)
        self.assertIn("Поток 3", body["message"])
        self.assertIn("Поток 2", body["message"])

        section = next(item for item in self.state()["sections"] if item["key"] == 3)
        self.assertEqual(section["start"], "2027-01-11")  # 23.11.2026 + 7 недель, понедельник
        lines = next(item for item in self.state()["sections"] if item["key"] == 2)["lines"]
        self.assertEqual(sorted(section["lines"]), sorted(lines))

    def test_new_line_and_course_validation(self):
        """Новая линейка: нужно имя, не повторяющее линейку раздела, и хотя бы один известный предмет.
        Новый курс добавляется в линейку с одним уроком в неделю; неизвестный предмет — отказ.
        """
        self.refused("newLine", section=2, name="  ", subjects=["Химия"])
        self.refused("newLine", section=2, name="ОГЭ", subjects=["Химия"])
        self.refused("newLine", section=2, name="Интенсив", subjects=[])
        self.refused("newLine", section=2, name="Интенсив", subjects=["Астрология"])

        self.ok("newLine", section=2, name=" Интенсив ", subjects=["Химия", "Биология"])
        created = [item for item in self.state()["courses"] if item["line"] == "Интенсив"]
        self.assertEqual(sorted(item["subject"] for item in created), ["Биология", "Химия"])
        self.assertTrue(all(item["section"] == 2 for item in created))

        self.refused("newCourse", section=2, line="Интенсив", subject="Астрология")
        self.ok("newCourse", section=2, line="Интенсив", subject="Физика")
        physics = next(item for item in self.state()["courses"] if item["line"] == "Интенсив" and item["subject"] == "Физика")
        self.assertEqual(physics["hours"], 1)

    def test_delete_course_asks_then_cleans_everything(self):
        """Удаление курса: сначала вопрос; после согласия курс уходит из настроек, расписания,
        вариантов и правил, а версия «Перед: …» позволяет откатить.
        """
        answer = self.load("answer.json")
        self.assertIn(RUS_PRO_2, answer)
        saveVariant(self.folder, "2", 1, {RUS_PRO_2: answer[RUS_PRO_2]})
        self.ok("savePenalty", penalty={"name": "Курс", "template": "adjacent", "weight": 5, "params": {"target": "course", "value": RUS_PRO_2}})

        body = self.ok("deleteCourse", course=RUS_PRO_2)
        self.assertTrue(body.get("danger"))
        self.assertIn(RUS_PRO_2, self.names())

        self.ok("deleteCourse", course=RUS_PRO_2, force=True)
        self.assertNotIn(RUS_PRO_2, self.names())
        self.assertNotIn(RUS_PRO_2, self.load("answer.json"))
        self.assertNotIn(RUS_PRO_2, dict(loadVariants(self.folder, "2"))[1])
        self.assertEqual(self.load("settings.json")["custom_penalties"], [])
        self.assertNotIn(RUS_PRO_2, self.load("settings.json")["classes"]["lessons"])
        self.assertTrue(any(name.startswith("Перед:") for name in self.versions()))

    def test_delete_line_warns_about_started_courses(self):
        """Удаление линейки идущего потока: в вопросе перечислены курсы, которые уже идут;
        после согласия удаляются все её курсы.
        """
        body = self.ok("deleteLine", section=1, line="8 класс")
        self.assertIn("Поток 1 — 8 класс", body["confirm"])

        self.ok("deleteLine", section=1, line="8 класс", force=True)
        self.assertFalse([name for name in self.names() if name.startswith("Поток 1 — 8 класс")])
        self.assertFalse([name for name in self.load("answer.json") if name.startswith("Поток 1 — 8 класс")])

    def test_vanished_stage_loses_its_variants(self):
        """Удалены все линейки потока 2 — поток пропал, и его варианты стёрты вместе с ним
        (иначе старые варианты с удалёнными курсами снова показались бы, когда этап появится опять);
        варианты потока 1 не тронуты."""
        saveVariant(self.folder, "1", 1, self.stageVariant("1"))
        saveVariant(self.folder, "2", 1, self.stageVariant("2"))

        for line in next(item["lines"] for item in self.state()["sections"] if item["key"] == 2):
            self.ok("deleteLine", section=2, line=line, force=True)

        self.assertNotIn(2, [item["key"] for item in self.state()["sections"]])
        self.assertFalse(os.path.isdir(variantsDir(self.folder, "2")))
        self.assertEqual(len(loadVariants(self.folder, "1")), 1)

    def test_copy_line_skips_started_streams(self):
        """«Скопировать в другие потоки» (линейку) не трогает поток, который уже идёт, и сообщает об этом."""
        self.ok("newStream")
        self.ok("newLine", section=2, name="Интенсив", subjects=["Химия"])

        body = self.ok("copyLine", section=2, line="Интенсив")
        self.assertIn("Поток 1", body["message"])
        lines = {item["key"]: item["lines"] for item in self.state()["sections"]}
        self.assertIn("Интенсив", lines[3])
        self.assertNotIn("Интенсив", lines[1])

    def test_unknown_line_is_refused(self):
        """Линейки нет (её удалили в другой вкладке): удаление, новый курс и копирование — отказ
        «Этой линейки больше нет», файл настроек не переписан и новой линейки не появилось."""
        before = self.raw("settings.json")
        subject = self.load("settings.json")["subjects"][0][0]

        for action, args in (("deleteLine", {"force": True}), ("newCourse", {"subject": subject}), ("copyLine", {})):
            self.assertEqual(self.refused(action, section=1, line="Нет такой", **args), translate("web.error.no_line"))

        self.assertEqual(self.raw("settings.json"), before)

    def test_copy_line_of_block_is_refused(self):
        """Копировать линейку («Скопировать в другие потоки») можно только из потока: у блока кнопка выключена, ручной запрос — отказ,
        и курсов «Поток N — Семинар …» не появляется.
        """
        before = self.raw("settings.json")

        self.assertEqual(self.refused("copyLine", section="extra", line="Семинар ОГЭ"), translate("web.error.generic"))
        self.assertEqual(self.raw("settings.json"), before)

    def test_block_dates_without_courses(self):
        """Даты блока без курсов («Майские марафоны») сохраняются; конец раньше начала — отказ."""
        self.ok("setDates", section="may", start="2027-05-03")
        self.ok("setDates", section="may", end="2027-05-28")
        may = next(item for item in self.state()["sections"] if item["key"] == "may")
        self.assertEqual((may["start"], may["end"]), ("2027-05-03", "2027-05-28"))

        self.refused("setDates", section="may", end="2027-04-01")

    def test_unknown_block_is_refused(self):
        """Несуществующий блок в setDates и newLine отклоняется (как и несуществующий поток):
        в settings.json не появляются ни block_dates["нет такого"], ни курсы с таким блоком.
        """
        self.refused("setDates", section="нет такого", start="2027-05-03")
        self.assertNotIn("нет такого", self.load("settings.json").get("block_dates", {}))
        self.refused("newLine", section="нет такого", name="Интенсив", subjects=["Химия"])

    def test_delete_unknown_line_or_course_is_refused(self):
        """Удаление линейки несуществующего раздела или несуществующего курса (устаревшая вкладка) —
        понятный отказ ещё до вопроса, проект не меняется.
        """
        before = self.raw("settings.json")

        self.assertEqual(self.refused("deleteLine", section=9, line="ОГЭ"), translate("web.error.generic"))
        self.assertEqual(self.refused("deleteLine", section=9, line="ОГЭ", force=True), translate("web.error.generic"))
        self.assertEqual(self.refused("deleteCourse", course="Поток 2 — ОГЭ — Нет такого"), translate("web.error.no_course"))
        self.assertEqual(self.refused("deleteCourse", course="Поток 2 — ОГЭ — Нет такого", force=True), translate("web.error.no_course"))
        self.assertEqual(self.raw("settings.json"), before)

    def test_new_stream_after_broken_date_starts_next_monday(self):
        """Дата начала последнего потока испорчена: новый поток начинается с ближайшего понедельника
        после «сегодня» (04.10.2026, воскресенье; ближайший понедельник — 05.10.2026) и копирует линейки потока 2.
        """
        settings = self.load("settings.json")
        for group in settings["classes"]["custom_groups"]:
            if group.get("stream_id") == 2:
                group["start_date"] = "когда-нибудь"

        self.save("settings.json", settings)

        body = self.ok("newStream")

        self.assertEqual(body["section"], 3)
        self.assertIn(translate("web.classes.stream_copied").replace("{source}", "Поток 2"), body["message"])
        section = next(item for item in body["state"]["sections"] if item["key"] == 3)
        self.assertEqual(section["start"], "2026-10-05")
        self.assertEqual(section["lines"], next(item for item in body["state"]["sections"] if item["key"] == 2)["lines"])

    def test_new_stream_without_streams_comes_from_template(self):
        """Потоков нет совсем: «Поток 1» получает курсы стандартной программы по предметам проекта,
        старые варианты этапа «1» стираются; без единого предмета поток не создаётся.
        """
        settings = self.load("settings.json")
        settings["classes"]["custom_groups"] = [group for group in settings["classes"]["custom_groups"] if group.get("stream_id") is None]
        self.save("settings.json", settings)
        saveVariant(self.folder, "1", 1, {"старый": []})

        body = self.ok("newStream")

        self.assertEqual(body["section"], 1)
        self.assertIn(translate("web.classes.stream_from_template"), body["message"])
        courses = [course for course in body["state"]["courses"] if course["section"] == 1]
        self.assertTrue(courses)
        self.assertTrue({course["subject"] for course in courses} <= set(body["state"]["subjects"]))
        self.assertTrue(all(course["start"] == "2026-10-05" for course in courses))
        self.assertEqual(loadVariants(self.folder, "1"), [])

        # Ни одного предмета: пустой поток не появится, файл не меняется
        settings = self.load("settings.json")
        settings["classes"]["custom_groups"] = [group for group in settings["classes"]["custom_groups"] if group.get("stream_id") is None]
        settings["subjects"] = []
        self.save("settings.json", settings)
        before = self.raw("settings.json")

        self.assertEqual(self.refused("newStream"), translate("web.classes.stream_no_subjects"))
        self.assertEqual(self.raw("settings.json"), before)

    def test_blocks_cannot_be_deleted(self):
        """Блок (доп. курсы) удалить как поток нельзя — ни с вопросом, ни с force."""
        before = self.raw("settings.json")

        self.assertEqual(self.refused("deleteStream", section="extra"), translate("web.error.generic"))
        self.assertEqual(self.refused("deleteStream", section="extra", force=True), translate("web.error.generic"))
        self.assertEqual(self.raw("settings.json"), before)

    def test_deleting_unscheduled_course_needs_no_version(self):
        """Курс без уроков в расписании: вопрос без напоминания о версии; после удаления версия
        не создаётся, answer.json не переписывается, варианты без этого курса не трогаются,
        а из варианта с ним курс убирается.
        """
        answer = self.load("answer.json")
        saveVariant(self.folder, "2", 1, {CHEM_OGE_2: answer[CHEM_OGE_2]})
        saveVariant(self.folder, "2", 2, {CHEM_OGE_2: answer[CHEM_OGE_2], RUS_8_2: answer[CHEM_OGE_2]})
        first = self.raw(os.path.join(variantsDir(self.folder, "2"), "1.json"))
        answer_before = self.raw("answer.json")
        versions = self.versions()

        body = self.ok("deleteCourse", course=RUS_8_2)
        self.assertTrue(body["danger"])
        self.assertIn(RUS_8_2, body["confirm"])
        self.assertNotIn(translate("web.confirm_remove_version"), body["confirm"])

        self.ok("deleteCourse", course=RUS_8_2, force=True)

        self.assertNotIn(RUS_8_2, [course["name"] for course in self.state()["courses"]])
        self.assertEqual(self.versions(), versions)
        self.assertEqual(self.raw("answer.json"), answer_before)
        self.assertEqual(self.raw(os.path.join(variantsDir(self.folder, "2"), "1.json")), first)
        self.assertEqual(dict(loadVariants(self.folder, "2"))[2], {CHEM_OGE_2: answer[CHEM_OGE_2]})

    def test_copy_line_to_streams_that_have_not_started(self):
        """Новая линейка потока 1 копируется в поток 2 (он ещё не начался) без сообщения о пропуске."""
        self.ok("newLine", section=1, name="Олимпиада", subjects=["Химия", "Физика"])

        body = self.ok("copyLine", section=1, line="Олимпиада")

        self.assertNotIn("message", body)
        copied = sorted(course["subject"] for course in body["state"]["courses"] if course["section"] == 2 and course["line"] == "Олимпиада")
        self.assertEqual(copied, ["Физика", "Химия"])

    def test_delete_stream_asks_and_clears_its_variants(self):
        """Удаление потока требует подтверждения и стирает его варианты, так что новый поток с тем же
        номером не получает чужие варианты.
        """
        saveVariant(self.folder, "2", 1, {})
        self.assertIn("confirm", self.act("deleteStream", section=2)[1])
        self.assertEqual(self.act("deleteStream", section=2, force=True)[0], 200)
        self.assertEqual(loadVariants(self.folder, "2"), [])

        # Новый поток с освободившимся номером начинается без вариантов
        self.act("newStream")
        self.assertEqual(loadVariants(self.folder, "2"), [])

    def test_dates(self):
        """Неверные даты потока (конец раньше начала, мусор) отклоняются, а перенос начала уже идущего
        потока в будущее (курсы перестанут «идти») требует подтверждения.
        """
        self.assertEqual(self.act("setDates", section=2, start="2027-05-01", end="2027-01-01")[0], 400)
        self.assertEqual(self.act("setDates", section=2, start="garbage")[0], 400)
        # Перенос начала потока 1 в будущее делает его курсы «не начавшимися»: сначала спрашиваем
        self.assertIn("confirm", self.act("setDates", section=1, start="2099-01-01", end="2099-06-30")[1])

    def test_one_day_course_dates(self):
        """Начало и конец потока в один день — допустимо, обе даты сохраняются; конец на день раньше — отказ."""
        self.ok("setDates", section=2, start="2026-12-01", end="2026-12-01")

        section = next(item for item in self.state()["sections"] if item["key"] == 2)
        self.assertEqual((section["start"], section["end"]), ("2026-12-01", "2026-12-01"))
        groups = [group for group in self.load("settings.json")["classes"]["custom_groups"] if group.get("stream_id") == 2]
        self.assertTrue(groups)
        self.assertTrue(all((group["start_date"], group["end_date"]) == ("2026-12-01", "2026-12-01") for group in groups))

        before = self.raw("settings.json")
        self.assertEqual(self.refused("setDates", section=2, end="2026-11-30"), translate("web.error.dates_order"))
        self.assertEqual(self.raw("settings.json"), before)

    def test_removal_question_mentions_version_for_scheduled_courses(self):
        """Удаление курса, линейки или потока с уроками в расписании: в вопросе — напоминание о версии;
        без force ничего не меняется.
        """
        before = (self.raw("settings.json"), self.raw("answer.json"))
        reminder = translate("web.confirm_remove_version")

        for action, args in (("deleteCourse", {"course": CHEM_OGE_2}), ("deleteLine", {"section": 2, "line": "ОГЭ"}), ("deleteStream", {"section": 2})):
            body = self.ok(action, **args)
            self.assertIn(reminder, body["confirm"], action)
            self.assertTrue(body["danger"], action)

        self.assertEqual((self.raw("settings.json"), self.raw("answer.json")), before)

    def test_unknown_stream_is_refused(self):
        """Несуществующий поток в newCourse / copyLine — общий отказ, файлы проекта не меняются;
        настоящие разделы (блок «extra») работают.
        """
        before = {name: self.raw(name) for name in ("settings.json", "answer.json")}

        self.assertEqual(self.refused("newCourse", section=99, line="ОГЭ", subject="Химия"), translate("web.error.generic"))
        self.assertEqual(self.refused("copyLine", section=99, line="ОГЭ"), translate("web.error.generic"))
        self.assertEqual({name: self.raw(name) for name in before}, before)
        self.assertNotIn(99, [section["key"] for section in self.state()["sections"]])

        self.ok("setDates", section="extra", start="2026-10-05")
        extra = next(section for section in self.state()["sections"] if section["key"] == "extra")
        self.assertEqual(extra["start"], "2026-10-05")

    def test_new_stream_drops_marks_of_vanished_stream(self):
        """Поток 2 пропал без «Удалить поток» (удалили все его линейки), его отметки остались.
        Кнопка «+ Поток» снова даёт номер 2, и у нового потока чужих «не может» нет.
        """
        settings = self.load("settings.json")
        teacher = next(iter(settings["teachers"]))
        settings["teachers"][teacher].setdefault("availability", {})["2"] = {"free": [[0, 0]], "possible": [[1, 1]]}
        self.save("settings.json", settings)

        for line in next(item for item in self.state()["sections"] if item["key"] == 2)["lines"]:
            self.ok("deleteLine", section=2, line=line, force=True)

        self.assertNotIn(2, [item["key"] for item in self.state()["sections"] if not item["block"]])
        self.assertIn("2", self.load("settings.json")["teachers"][teacher]["availability"])

        self.assertEqual(self.ok("newStream")["section"], 2)
        self.assertNotIn("2", self.load("settings.json")["teachers"][teacher]["availability"])

    def test_new_first_stream_from_template_drops_old_marks(self):
        """Все потоки пропали (удалены все линейки): новый «Поток 1» из стандартной программы
        тоже не получает старые отметки потока 1.
        """
        settings = self.load("settings.json")
        teacher = next(iter(settings["teachers"]))
        settings["teachers"][teacher].setdefault("availability", {})["1"] = {"free": [[0, 0]], "possible": []}
        self.save("settings.json", settings)

        for key in (1, 2):
            for line in next(item for item in self.state()["sections"] if item["key"] == key)["lines"]:
                self.ok("deleteLine", section=key, line=line, force=True)

        self.assertEqual(self.ok("newStream")["section"], 1)
        self.assertNotIn("1", self.load("settings.json")["teachers"][teacher]["availability"])

    def test_empty_week_is_not_lessons_for_delete(self):
        """Курс есть в answer.json, но с пустой неделей: удаление спрашивает без напоминания
        о версии и версию «Перед: …» не сохраняет.
        """
        answer = self.load("answer.json")
        answer[RUS_PRO_2] = emptied(answer[RUS_PRO_2])
        self.save("answer.json", answer)
        versions = self.versions()

        question = self.ok("deleteCourse", course=RUS_PRO_2)["confirm"]
        self.assertNotIn(translate("web.confirm_remove_version"), question)

        self.ok("deleteCourse", course=RUS_PRO_2, force=True)
        self.assertEqual(self.versions(), versions)


class HoursAndPinsTests(RealProjectCase):
    """Часы курса и закреплённые уроки."""
    NAME = "__test_pins__"

    def test_hours_are_clamped_and_extra_pins_dropped(self):
        """Часы: от 1 до числа дней с уроками; при уменьшении лишние закрепления отбрасываются."""
        self.ok("setHours", course=RUS_BASE_2, subject="Русский язык", hours="0")
        self.assertEqual(self.course(RUS_BASE_2)["hours"], 1)
        self.ok("setHours", course=RUS_BASE_2, subject="Русский язык", hours="99")
        self.assertEqual(self.course(RUS_BASE_2)["hours"], 7)

        self.ok("setHours", course=RUS_BASE_2, subject="Русский язык", hours=2)
        self.ok("setPins", course=RUS_BASE_2, subject="Русский язык", slots=[[0, 0], [2, 0]])
        self.assertEqual(self.course(RUS_BASE_2)["pinned"], [[0, 0], [2, 0]])

        self.ok("setHours", course=RUS_BASE_2, subject="Русский язык", hours=1)
        self.assertEqual(len(self.course(RUS_BASE_2)["pinned"]), 1)

        # Чужой предмет или удалённый курс — понятная ошибка
        self.refused("setHours", course=RUS_BASE_2, subject="Химия", hours=1)
        self.refused("setHours", course="Нет такого курса", subject="Химия", hours=1)

    def test_pins_validation(self):
        """Закрепления: только существующие ячейки сетки; повтор ячейки — это два урока в один день."""
        self.ok("setHours", course=RUS_BASE_2, subject="Русский язык", hours=2)
        self.assertEqual(self.refused("setPins", course=RUS_BASE_2, subject="Русский язык", slots=[[6, 5]]),  # в воскресенье 2 урока
                         translate("web.error.no_slot"))
        self.assertEqual(self.refused("setPins", course=RUS_BASE_2, subject="Русский язык", slots=[[0, 0], [0, 0]]),
                         translate("web.error.pins_same_day"))
        self.ok("setPins", course=RUS_BASE_2, subject="Русский язык", slots=[])
        self.assertEqual(self.course(RUS_BASE_2)["pinned"], [])

    def test_pins_move_scheduled_lessons_when_free(self):
        """Курс уже в расписании: закрепление на свободное время переносит урок туда сразу (с сообщением);
        на занятое — сначала вопрос, и расписание не меняется.
        """
        course = self.course(RUS_PRO_2)
        slots = course["slots"]
        busy_days = {day for day, _ in slots}
        # Пробуем разные свободные дни будней, пока не найдём время, где переносу ничто не мешает
        moved = False

        for day in [d for d in range(5) if d not in busy_days]:
            for lesson in range(3):
                target = [[day, lesson]] + slots[1:]
                code, body = self.act("setPins", course=RUS_PRO_2, subject="Русский язык", slots=target)
                self.assertEqual(code, 200, body)

                if "confirm" in body:
                    # Вопрос — расписание не тронуто
                    self.assertEqual(sorted(self.course(RUS_PRO_2)["slots"]), sorted(slots))
                    continue

                self.assertIn("message", body)
                self.assertIn([day, lesson], self.course(RUS_PRO_2)["slots"])
                moved = True
                break

            if moved:
                break

        self.assertTrue(moved)

    def test_pins_on_current_place_change_only_settings(self):
        """Закрепление урока там, где он уже стоит: переносить нечего — сообщения нет, расписание то же."""
        answer_before = self.raw("answer.json")

        body = self.ok("setPins", course=CHEM_OGE_2, subject="Химия", slots=[[3, 1]])

        self.assertNotIn("message", body)
        self.assertEqual(self.course(CHEM_OGE_2)["pinned"], [[3, 1]])
        self.assertEqual(self.raw("answer.json"), answer_before)

    def test_pins_on_busy_time_are_asked_and_kept_with_force(self):
        """Закрепление на время, когда преподаватель ведёт другой курс: вопрос с причиной; без force
        ничего не меняется; с force закрепление сохраняется, а урок в расписании остаётся на месте.
        """
        answer_before = self.raw("answer.json")

        body = self.ok("setPins", course=CHEM_OGE_2, subject="Химия", slots=[[0, 1]])
        self.assertTrue(body["confirm"].startswith(translate("menu.main.tab.classes.slot_conflicts")))
        self.assertIn(CHEM_10_2, body["confirm"])
        self.assertEqual(body["yes"], translate("web.pin_yes"))
        self.assertEqual(self.course(CHEM_OGE_2)["pinned"], [])

        self.assertNotIn("message", self.ok("setPins", course=CHEM_OGE_2, subject="Химия", slots=[[0, 1]], force=True))
        course = self.course(CHEM_OGE_2)
        self.assertEqual((course["pinned"], course["slots"]), ([[0, 1]], [[3, 1]]))
        self.assertEqual(self.raw("answer.json"), answer_before)

    def test_pins_wrong_shape_is_refused(self):
        """Закрепление не из двух чисел или вне сетки — понятный отказ, настройки не меняются."""
        before = self.raw("settings.json")

        for slots in ([[0]], [[0, 9]], [[9, 0]], [[0, 1, 2]], [["пн", 0]], [None], None):
            self.assertEqual(self.refused("setPins", course=RUS_8_2, subject="Русский язык", slots=slots), translate("web.error.no_slot"), slots)

        self.assertEqual(self.raw("settings.json"), before)

    def test_pins_from_strings_are_stored_as_numbers(self):
        """Закрепления строками из цифр («0», «1») сохраняются числами — как от страницы."""
        self.ok("setPins", course=RUS_8_2, subject="Русский язык", slots=[["0", "1"]])

        self.assertEqual(self.course(RUS_8_2)["pinned"], [[0, 1]])
        self.assertEqual(self.load("settings.json")["constants"][RUS_8_2], {"0-1": "Русский язык"})

    def test_hours_of_started_course_down_to_placed_lessons(self):
        """Идущему курсу с 2 уроками в расписании можно поставить ровно 2 урока; 1 — отказ."""
        self.ok("setHours", course=RUS_BASE_1, subject="Русский язык", hours=2)
        self.assertEqual(self.load("settings.json")["classes"]["lessons"][RUS_BASE_1]["Русский язык"], 2)

        self.assertEqual(self.refused("setHours", course=RUS_BASE_1, subject="Русский язык", hours=1),
                         translate("web.error.hours_below_started").replace("{lessons}", "2 урока"))
        self.assertEqual(self.load("settings.json")["classes"]["lessons"][RUS_BASE_1]["Русский язык"], 2)

    def test_locked_course_hours_cannot_grow(self):
        """У зафиксированного курса (идёт, все уроки стоят) увеличение числа уроков — отказ
        «курс уже идёт», settings.json не меняется; то же самое число принимается.
        """
        name = "Поток 1 — ЕГЭ основной — Химия"
        course = self.course(name)
        self.assertTrue(course["locked"])
        before = self.raw("settings.json")

        self.assertEqual(self.refused("setHours", course=name, subject="Химия", hours=course["hours"] + 1), translate("web.error.course_locked"))
        self.assertEqual(self.raw("settings.json"), before)

        self.ok("setHours", course=name, subject="Химия", hours=course["hours"])
        self.assertEqual(self.course(name)["hours"], course["hours"])

    def test_two_pins_on_one_day_are_refused(self):
        """Два закрепления курса в один день — отказ «в один день нельзя», настройки не меняются."""
        before = self.raw("settings.json")

        self.assertEqual(self.refused("setPins", course=RUS_BASE_2, subject="Русский язык", slots=[[0, 0], [0, 1]]),
                         translate("web.error.pins_same_day"))
        self.assertEqual(self.raw("settings.json"), before)
        self.assertEqual(self.course(RUS_BASE_2)["pinned"], [])

    def test_pins_are_limited_by_hours(self):
        """Курсу с 2 уроками в неделю нельзя закрепить 3 (раньше сервер принимал сколько угодно):
        отказ с числом уроков, settings.json не меняется; 2 закрепления проходят.
        """
        self.ok("setHours", course=RUS_BASE_2, subject="Русский язык", hours=2)
        before = self.raw("settings.json")

        error = self.refused("setPins", course=RUS_BASE_2, subject="Русский язык", slots=[[0, 0], [2, 0], [4, 0]])
        self.assertEqual(error, tr("web.error.pins_too_many", lessons=lessonsText(2)))
        self.assertEqual(self.raw("settings.json"), before)
        self.assertEqual(self.course(RUS_BASE_2)["pinned"], [])

        self.ok("setPins", course=RUS_BASE_2, subject="Русский язык", slots=[[0, 0], [2, 0]])
        self.assertEqual(self.course(RUS_BASE_2)["pinned"], [[0, 0], [2, 0]])


class CourseTeacherTests(RealProjectCase):
    """Преподаватель курса."""
    NAME = "__test_course_teacher__"

    def test_teacher_of_course_that_has_not_started(self):
        """Преподаватель курса, который ещё не начался: только преподаватель этого предмета; снять можно;
        если курс уже в расписании и новый свободен — он сразу встаёт на уроки и в варианты этапа.
        """
        self.refused("setTeacher", course=RUS_BASE_2, subject="Русский язык", teacher="Баранникова Анна")
        self.ok("setTeacher", course=RUS_BASE_2, subject="Русский язык", teacher=None)
        self.assertEqual(self.course(RUS_BASE_2)["assigned"], [])

        answer = self.load("answer.json")
        saveVariant(self.folder, "2", 1, {RUS_PRO_2: answer[RUS_PRO_2]})
        course = self.course(RUS_PRO_2)
        others = [name for name in course["options"] if name not in course["scheduled"]]
        replaced = None

        for name in others:
            body = self.ok("setTeacher", course=RUS_PRO_2, subject="Русский язык", teacher=name)

            if "confirm" not in body:
                self.assertIn("message", body)
                replaced = name
                break

        self.assertIsNotNone(replaced, "ни один другой преподаватель русского не свободен")
        teachers = {tuple(cell["teachers"]) for _, _, cell in lessons(self.load("answer.json")[RUS_PRO_2])}
        self.assertEqual(teachers, {(replaced,)})
        variant = dict(loadVariants(self.folder, "2"))[1][RUS_PRO_2]
        self.assertEqual({tuple(cell["teachers"]) for _, _, cell in lessons(variant)}, {(replaced,)})

    def test_teacher_over_course_limit_is_asked_and_kept_with_force(self):
        """Преподаватель превысил бы лимит курсов: вопрос с объяснением про лимит; с force он закрепляется
        за курсом, а принятое расписание не меняется (учтётся при следующей сборке).
        """
        self.ok("setLimit", key="max_courses_per_teacher", value=1)
        answer_before = self.raw("answer.json")

        body = self.ok("setTeacher", course=CHEM_OGE_2, subject="Химия", teacher="Логвинов Даниил")
        self.assertIn(part("menu.main.tab.classes.conflict_limit"), body["confirm"])
        self.assertIn("Логвинов Даниил", body["confirm"])
        self.assertEqual(self.course(CHEM_OGE_2)["assigned"], ["Баранникова Анна"])

        body = self.ok("setTeacher", course=CHEM_OGE_2, subject="Химия", teacher="Логвинов Даниил", force=True)
        self.assertNotIn("message", body)
        course = self.course(CHEM_OGE_2)
        self.assertEqual(course["assigned"], ["Логвинов Даниил"])
        self.assertEqual(course["scheduled"], ["Баранникова Анна"])
        self.assertEqual(self.raw("answer.json"), answer_before)

    def test_free_teacher_replaces_lessons_in_answer_and_variants(self):
        """Свободный преподаватель сразу заменяет прежнего в расписании и в вариантах с этим курсом;
        вариант без курса не переписывается.
        """
        self.ok("newTeacher", name="Новикова Ольга", subjects=["Химия"])
        answer = self.load("answer.json")
        saveVariant(self.folder, "2", 1, {CHEM_OGE_2: answer[CHEM_OGE_2]})
        saveVariant(self.folder, "2", 2, {CHEM_10_2: answer[CHEM_10_2]})
        untouched = self.raw(os.path.join(variantsDir(self.folder, "2"), "2.json"))

        body = self.ok("setTeacher", course=CHEM_OGE_2, subject="Химия", teacher="Новикова Ольга")

        self.assertEqual(body["message"], translate("menu.main.tab.classes.replaced").replace("{teacher}", "Новикова Ольга"))
        self.assertEqual({tuple(cell["teachers"]) for _, _, cell in lessons(self.load("answer.json")[CHEM_OGE_2])}, {("Новикова Ольга",)})
        variant = dict(loadVariants(self.folder, "2"))[1]
        self.assertEqual({tuple(cell["teachers"]) for _, _, cell in lessons(variant[CHEM_OGE_2])}, {("Новикова Ольга",)})
        self.assertEqual(self.raw(os.path.join(variantsDir(self.folder, "2"), "2.json")), untouched)

    def test_started_course_without_teacher(self):
        """Идущий курс без преподавателя: снять «никого» нельзя; свободному — вопрос, с force —
        версия «Перед: …», преподаватель ставится на все уроки курса.
        """
        self.assertEqual(self.refused("setTeacher", course=PHYS_PRO_1, subject="Физика", teacher=None), translate("web.error.course_locked_teacher"))

        self.ok("newTeacher", name="Новиков Пётр", subjects=["Физика"])
        versions = self.versions()

        body = self.ok("setTeacher", course=PHYS_PRO_1, subject="Физика", teacher="Новиков Пётр")
        self.assertEqual(body["confirm"], translate("web.confirm_assign_started").replace("{teacher}", "Новиков Пётр").replace("{course}", PHYS_PRO_1))
        self.assertEqual(body["yes"], translate("web.assign_yes"))
        self.assertEqual(self.course(PHYS_PRO_1)["scheduled"], [])

        body = self.ok("setTeacher", course=PHYS_PRO_1, subject="Физика", teacher="Новиков Пётр", force=True)
        self.assertIn("Новиков Пётр", body["message"])
        cells = lessons(self.load("answer.json")[PHYS_PRO_1])
        self.assertEqual(len(cells), 2)
        self.assertTrue(all(cell["teachers"] == ["Новиков Пётр"] for _, _, cell in cells))
        self.assertEqual(len(self.versions()), len(versions) + 1)
        self.assertTrue(self.versions()[0].startswith("Перед:"))

        # Теперь у курса есть преподаватель — менять его нельзя
        self.assertEqual(self.refused("setTeacher", course=PHYS_PRO_1, subject="Физика", teacher="Передерин Дмитрий"), translate("web.error.course_locked"))

    def test_started_course_keeps_teacher_times_and_hours(self):
        """Если курс уже идёт и зафиксирован, нельзя изменить ни его часы, ни закреплённое время,
        ни учителя — сервер отвечает 400, и у учеников ничего не съезжает.
        """
        name = "Поток 1 — ЕГЭ основной — Химия"
        course = self.course(name)
        self.assertTrue(course["started"] and course["locked"])

        self.assertEqual(self.act("setHours", course=name, subject="Химия", hours=1)[0], 400)
        self.assertEqual(self.act("setPins", course=name, subject="Химия", slots=[[0, 0], [2, 0]])[0], 400)
        self.assertEqual(self.act("setTeacher", course=name, subject="Химия", teacher="Логвинов Даниил")[0], 400)

    def test_started_course_without_teacher_gets_only_a_free_one(self):
        """Курсу, который уже идёт и стоит в расписании без преподавателя, можно назначить только учителя,
        свободного в его время; если учитель занят, приходит уведомление и ничего не меняется.
        """
        name = PHYS_PRO_1
        # На уроках курса в расписании пока нет преподавателя
        self.assertFalse(self.course(name)["scheduled"])

        # Единственный физик занят в это время: уведомление, ничего не меняется
        code, body = self.act("setTeacher", course=name, subject="Физика", teacher="Передерин Дмитрий")
        self.assertEqual(code, 200)
        self.assertIn("notice", body)
        self.assertFalse(self.course(name)["scheduled"])


class JointLineTests(RealProjectCase):
    """«Линейка присоединяется к Потоку N»: действие setJoint и курсы-копии на вкладке «Курсы».

    Проект — ``builders.jointProject``: Поток 1 идёт и принят, у «ЕГЭ основной» Потока 2 уроков
    нет, у «Поток 2 — ЕГЭ основной — Математика» до отметки свои «ведёт» и закрепление.
    """
    NAME = "__test_joint_line__"

    def groups(self):
        """Курсы проекта из settings.json: имя -> группа."""
        return {group["name"]: group for group in self.load("settings.json")["classes"]["custom_groups"]}

    def marked(self, section=2, line=JOINT_LINE):
        """{курс: together_with} курсов линейки ``line`` потока ``section``, у которых стоит отметка."""
        return {name: group["together_with"] for name, group in self.groups().items()
                if group.get("stream_id") == section and group.get("program") == line and "together_with" in group}

    def test_set_joint_puts_source_lessons_into_copies(self):
        """AC-2, AC-3: setJoint у «ЕГЭ основной» Потока 2 без уроков — без вопроса. Отметку получают
        курсы, чей предмет есть в той же линейке Потока 1 (Информатика — нет, Биология в Потоке 2
        не появляется); часы копии как у источника, закрепления и «ведёт» сняты, уроки источника
        скопированы (у источника без уроков ключа копии нет), варианты этапа «2» удалены.
        """
        settings, answer = jointProject()
        answer.pop(RUS_1)
        self.openProject(settings, answer)
        saveVariant(self.folder, "2", 1, {})

        body = self.ok("setJoint", section=2, line=JOINT_LINE, source=1)

        self.assertNotIn("confirm", body)
        self.assertEqual(self.marked(), {MATH_2: 1, RUS_2: 1})
        self.assertNotIn(BIO_2, self.groups())
        settings, answer = self.load("settings.json"), self.load("answer.json")

        for copy_, source in ((MATH_2, MATH_1), (RUS_2, RUS_1)):
            self.assertEqual(settings["classes"]["lessons"][copy_], settings["classes"]["lessons"][source], copy_)

        self.assertEqual(answer[MATH_2], answer[MATH_1])
        self.assertNotIn(RUS_2, answer)
        self.assertNotIn(MATH_2, settings.get("constants", {}))
        self.assertFalse([name for name, data in settings["teachers"].items() for item in data["subjects"]
                          if {MATH_2, RUS_2} & set(item.get("assigned", []))])
        self.assertFalse(hasLessons(answer, INF_2))
        self.assertEqual(loadVariants(self.folder, "2"), [])

    def test_set_joint_refusals_leave_project_unchanged(self):
        """AC-1 (действие): setJoint для блока, для Потока N не раньше своего (тот же, более поздний,
        несуществующий) и для линейки, которой нет в Потоке N, — отказ, файлы не переписаны;
        допустимая отметка «Поток 2 вместе с Потоком 1» проходит.
        """
        settings, answer = jointProject()
        addCourse(settings, "extra", "Семинар", "Математика", 1)
        self.openProject(settings, answer)
        before = self.files()

        for args in ({"section": "extra", "line": "Семинар", "source": 1}, {"section": 2, "line": JOINT_LINE, "source": 2},
                     {"section": 2, "line": JOINT_LINE, "source": 3}, {"section": 1, "line": JOINT_LINE, "source": 1},
                     {"section": 2, "line": JOINT_LINE, "source": 9}, {"section": 2, "line": OWN_LINE, "source": 1}):
            self.refused("setJoint", **args)
            self.assertEqual(self.files(), before, args)

        self.ok("setJoint", section=2, line=JOINT_LINE, source=1)
        self.assertEqual(self.marked(), {MATH_2: 1, RUS_2: 1})

    def test_set_joint_over_other_lessons_asks_and_saves_version(self):
        """AC-5: у «ЕГЭ основной» Потока 2 свои уроки — без force вопрос web.classes.joint_confirm,
        файлы и версии не меняются («Отмена»); с force — версия «Перед: …» с текстом web.version.joint,
        отметка стоит, уроки копии — как у источника.
        """
        settings, answer = jointProject()
        answer[MATH_2] = courseWeek("Математика", JOINT_PIN_TEACHER, (1, 0), (4, 0))
        self.openProject(settings, answer)
        before, versions = self.files(), self.versions()

        body = self.ok("setJoint", section=2, line=JOINT_LINE, source=1)

        self.assertIn("confirm", body)
        self.assertText("web.classes.joint_confirm", body["confirm"])
        self.assertIn(JOINT_LINE, body["confirm"])
        self.assertEqual(self.files(), before)
        self.assertEqual(self.versions(), versions)

        self.ok("setJoint", section=2, line=JOINT_LINE, source=1, force=True)

        self.assertEqual(len(self.versions()), len(versions) + 1)
        self.assertTrue(self.versions()[0].startswith(part("web.version.before")))
        self.assertText("web.version.joint", self.versions()[0])
        self.assertEqual(self.marked(), {MATH_2: 1, RUS_2: 1})
        answer = self.load("answer.json")
        self.assertEqual(answer[MATH_2], answer[MATH_1])

    def test_set_joint_when_lessons_already_match(self):
        """AC-6: уроки «ЕГЭ основной» Потока 2 уже стоят в тех же слотах с теми же преподавателями
        (до отметки это накладки) — setJoint без вопроса и без версии, расписание не меняется,
        после отметки накладок по этим курсам нет.
        """
        settings, answer = jointProject()

        for subject in ("Математика", "Русский язык"):
            answer[jointCourse(2, subject)] = copy.deepcopy(answer[jointCourse(1, subject)])

        settings["classes"]["lessons"][RUS_2] = copy.deepcopy(settings["classes"]["lessons"][RUS_1])
        self.openProject(settings, answer)
        self.assertTrue([courses for *_, courses in self.state()["clashes"] if MATH_2 in courses])
        answer, versions = self.load("answer.json"), self.versions()

        body = self.ok("setJoint", section=2, line=JOINT_LINE, source=1)

        self.assertNotIn("confirm", body)
        self.assertEqual(self.versions(), versions)
        self.assertEqual(self.load("answer.json"), answer)
        self.assertEqual(self.marked(), {MATH_2: 1, RUS_2: 1})
        self.assertFalse([courses for *_, courses in self.state()["clashes"] if {MATH_2, RUS_2} & set(courses)])

    def test_unset_joint_returns_line_to_own_schedule(self):
        """AC-7: setJoint(source=None) у линейки, курсы которой не идут: отметки нет ни у одного
        курса, уроков копий в расписании нет, часы прежние, версия «Перед: …» сохранена (уроки были),
        варианты этапа удалены, сообщение web.classes.joint_off.
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        saveVariant(self.folder, "2", 1, {})
        hours, versions = self.load("settings.json")["classes"]["lessons"], self.versions()

        body = self.ok("setJoint", section=2, line=JOINT_LINE, source=None)

        self.assertText("web.classes.joint_off", body.get("message", ""))
        self.assertIn(JOINT_LINE, body["message"])
        self.assertEqual(self.marked(), {})
        answer = self.load("answer.json")
        self.assertFalse(hasLessons(answer, MATH_2) or hasLessons(answer, RUS_2))
        self.assertEqual(self.load("settings.json")["classes"]["lessons"], hours)
        self.assertEqual(len(self.versions()), len(versions) + 1)
        self.assertTrue(self.versions()[0].startswith(part("web.version.before")))
        self.assertEqual(loadVariants(self.folder, "2"), [])

    def test_started_copies_cannot_change_mark(self):
        """AC-8: Поток 2 уже идёт. Снять отметку, когда копии идут, и поставить её, когда идёт курс
        с другими уроками, — отказ web.error.joint_started, файлы не переписаны. Если уроки идущих
        курсов совпадают с Потоком 1 (AC-6), отметка ставится.
        """
        settings, answer = jointProject()
        shiftStream(settings, 2, PAST)
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        before = self.files()

        self.assertEqual(self.refused("setJoint", section=2, line=JOINT_LINE, source=None), translate("web.error.joint_started"))
        self.assertEqual(self.files(), before)

        settings, answer = jointProject()
        shiftStream(settings, 2, PAST)
        answer[MATH_2] = courseWeek("Математика", JOINT_PIN_TEACHER, (1, 0), (4, 0))
        self.openProject(settings, answer)
        before = self.files()

        self.assertEqual(self.refused("setJoint", section=2, line=JOINT_LINE, source=1), translate("web.error.joint_started"))
        self.assertEqual(self.files(), before)

        settings, answer = jointProject()
        shiftStream(settings, 2, PAST)

        for subject in ("Математика", "Русский язык"):
            answer[jointCourse(2, subject)] = copy.deepcopy(answer[jointCourse(1, subject)])

        settings["classes"]["lessons"][RUS_2] = copy.deepcopy(settings["classes"]["lessons"][RUS_1])
        self.openProject(settings, answer)

        self.assertNotIn("confirm", self.ok("setJoint", section=2, line=JOINT_LINE, source=1))
        self.assertEqual(self.marked(), {MATH_2: 1, RUS_2: 1})

    def test_chains_are_refused(self):
        """AC-9: Поток 2 идёт вместе с Потоком 1 — Поток 3 не может идти вместе с Потоком 2
        (web.error.joint_chain), а с Потоком 1 может. Поток 3 идёт вместе с Потоком 2 — Поток 2
        не может стать копией (web.error.joint_has_copies). При отказе файлы не переписаны.
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        before = self.files()

        error = self.refused("setJoint", section=3, line=JOINT_LINE, source=2)
        self.assertText("web.error.joint_chain", error)
        self.assertEqual(self.files(), before)

        self.ok("setJoint", section=3, line=JOINT_LINE, source=1)
        self.assertEqual(self.marked(3), {jointCourse(3, "Математика"): 1, jointCourse(3, "Русский язык"): 1})

        settings, answer = jointProject()
        markJoint(settings, 3, JOINT_LINE, 2, answer)
        self.openProject(settings, answer)
        before = self.files()

        error = self.refused("setJoint", section=2, line=JOINT_LINE, source=1)
        self.assertText("web.error.joint_has_copies", error)
        self.assertIn("3", error)
        self.assertEqual(self.files(), before)

    def test_copy_fields_are_closed(self):
        """AC-10: у курса-копии часы, преподаватель (назначить и снять) и закрепления не меняются —
        отказ web.error.joint_locked («Курс присоединён к Потоку 1: …»), файлы не переписаны.
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        before = self.files()

        for action, args in (("setHours", {"hours": 1}), ("setTeacher", {"teacher": JOINT_PIN_TEACHER}), ("setTeacher", {"teacher": None}),
                             ("setPins", {"slots": [[1, 0], [4, 0]]})):
            error = self.refused(action, course=MATH_2, subject="Математика", **args)
            self.assertText("web.error.joint_locked", error)
            self.assertIn("1", error)
            self.assertEqual(self.files(), before, action)

    def test_source_changes_reach_copies(self):
        """AC-11, AC-16: Поток 1 ещё не начался. Новый преподаватель, закрепление (перенос урока)
        и часы курса-источника сразу переходят в курс-копию Потока 2.
        """
        settings, answer = jointProject()
        shiftStream(settings, 1, FUTURE)
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)

        self.ok("setTeacher", course=MATH_1, subject="Математика", teacher=JOINT_PIN_TEACHER)
        answer = self.load("answer.json")
        self.assertEqual(answer[MATH_2], answer[MATH_1])
        self.assertEqual({tuple(cell["teachers"]) for _, _, cell in lessons(answer[MATH_2])}, {(JOINT_PIN_TEACHER,)})

        self.ok("setPins", course=MATH_1, subject="Математика", slots=[[1, 0], [2, 0]])
        answer = self.load("answer.json")
        self.assertEqual(answer[MATH_2], answer[MATH_1])
        self.assertIn((1, 0), [(day, lesson) for day, lesson, _ in lessons(answer[MATH_2])])

        self.ok("setHours", course=RUS_1, subject="Русский язык", hours=1)
        self.assertEqual(self.load("settings.json")["classes"]["lessons"][RUS_2], {"Русский язык": 1})

    def test_copy_line_keeps_copy_hours(self):
        """AC-11: «Скопировать в другие потоки» из Потока 3 (там у русского 1 урок) не делает часы
        копии в Потоке 2 отличными от источника (2 урока).
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)

        self.ok("copyLine", section=3, line=JOINT_LINE)

        hours = self.load("settings.json")["classes"]["lessons"]
        self.assertEqual(hours[RUS_2], hours[RUS_1])

    def test_started_copy_locks_source(self):
        """AC-11: «курс уже идёт» у источника проверяется по группе «источник + копии»: Поток 1 ещё
        не начался, а копии Потока 2 уже идут — преподаватель, закрепления и часы источника не
        меняются (отказ), файлы не переписаны.
        """
        settings, answer = jointProject()
        shiftStream(settings, 1, FUTURE)
        shiftStream(settings, 2, PAST)
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        before = self.files()

        self.refused("setTeacher", course=MATH_1, subject="Математика", teacher=JOINT_PIN_TEACHER)
        self.refused("setPins", course=MATH_1, subject="Математика", slots=[[1, 0], [2, 0]])
        self.refused("setHours", course=RUS_1, subject="Русский язык", hours=1)
        self.assertEqual(self.files(), before)

    def test_source_pins_check_copy_neighbours(self):
        """AC-16: закрепление источника на время, где в линейке копии (Поток 2) стоит предмет пары
        «нельзя одновременно», — вопрос о конфликте, в нём назван курс Потока 2; файлы не переписаны.
        """
        settings, answer = jointProject()
        shiftStream(settings, 1, FUTURE)
        settings.setdefault("joint_subject_pairs", []).append(["Математика", "Информатика"])
        answer[INF_2] = courseWeek("Информатика", "Информатика #1", (1, 0))
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        before = self.files()

        body = self.ok("setPins", course=MATH_1, subject="Математика", slots=[[1, 0], [2, 0]])

        self.assertTrue(body.get("confirm", "").startswith(translate("menu.main.tab.classes.slot_conflicts")), body.get("message"))
        self.assertIn(INF_2, body["confirm"])
        self.assertEqual(self.files(), before)

    def test_new_course_in_joint_line(self):
        """AC-4: «Добавить предмет» в отмеченной линейке Потока 2: предмет из линейки Потока 1
        (Биология) — сразу копия с часами и уроками источника; предмета нет в Потоке 1
        (Информатика) — обычный курс без уроков. Предмет, добавленный в Поток 1, в Поток 2 сам
        не добавляется.
        """
        settings, answer = jointProject()
        removeCourses(settings, [INF_2])
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)

        self.ok("newCourse", section=2, line=JOINT_LINE, subject="Биология")

        self.assertEqual(self.groups()[BIO_2].get("together_with"), 1)
        settings, answer = self.load("settings.json"), self.load("answer.json")
        self.assertEqual(settings["classes"]["lessons"][BIO_2], settings["classes"]["lessons"][BIO_1])
        self.assertEqual(answer[BIO_2], answer[BIO_1])

        self.ok("newCourse", section=2, line=JOINT_LINE, subject="Информатика")
        self.assertNotIn("together_with", self.groups()[INF_2])
        self.assertFalse(hasLessons(self.load("answer.json"), INF_2))

        streams = {name for name, group in self.groups().items() if group.get("stream_id") == 2}
        self.ok("newCourse", section=1, line=JOINT_LINE, subject="Информатика")
        self.assertEqual({name for name, group in self.groups().items() if group.get("stream_id") == 2}, streams)

    def test_new_stream_does_not_inherit_mark(self):
        """AC-12: новый поток после Потока 2 с отметкой — курсы Потока 3 без together_with;
        Поток 3 можно отметить «вместе с Потоком 1», но не «вместе с Потоком 2».
        """
        settings, answer = jointProject(streams=2)
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)

        self.assertEqual(self.ok("newStream")["section"], 3)

        third = [group for group in self.groups().values() if group.get("stream_id") == 3]
        self.assertTrue(third)
        self.assertFalse([group["name"] for group in third if "together_with" in group])
        self.assertText("web.error.joint_chain", self.refused("setJoint", section=3, line=JOINT_LINE, source=2))
        self.ok("setJoint", section=3, line=JOINT_LINE, source=1)
        self.assertEqual(self.marked(3), {jointCourse(3, "Математика"): 1, jointCourse(3, "Русский язык"): 1})

    def checkSourceRemoval(self, action, args, copies):
        """AC-19: удаление источника действием ``action``: в вопросе — абзац
        web.classes.joint_remove_note; после удаления у бывших копий ``copies`` нет отметки,
        их уроки в расписании те же, что были, состояние проекта читается.
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        kept = {name: answer[name] for name in copies}

        body = self.ok(action, **args)
        self.assertText("web.classes.joint_remove_note", body.get("confirm", ""))
        self.assertIn(JOINT_LINE, body["confirm"])

        self.ok(action, force=True, **args)

        groups, answer = self.groups(), self.load("answer.json")

        for name in copies:
            self.assertNotIn("together_with", groups[name], name)
            self.assertEqual(answer[name], kept[name], name)

        self.assertEqual(self.client.get(f"/api/project/{self.NAME}").status_code, 200)

        return groups

    def test_deleting_source_course_keeps_copy_lessons(self):
        """AC-19: удаление курса-источника (Математика Потока 1): копия становится обычным курсом
        со своими уроками; копия другого предмета (Русский язык) остаётся копией.
        """
        groups = self.checkSourceRemoval("deleteCourse", {"course": MATH_1}, [MATH_2])
        self.assertEqual(groups[RUS_2].get("together_with"), 1)

    def test_deleting_source_line_keeps_copy_lessons(self):
        """AC-19: удаление линейки «ЕГЭ основной» Потока 1 — все копии становятся обычными курсами со своими уроками."""
        self.checkSourceRemoval("deleteLine", {"section": 1, "line": JOINT_LINE}, [MATH_2, RUS_2])

    def test_deleting_source_stream_keeps_copy_lessons(self):
        """AC-19: удаление Потока 1 — все копии становятся обычными курсами со своими уроками."""
        self.checkSourceRemoval("deleteStream", {"section": 1}, [MATH_2, RUS_2])


class JointConflictTests(RealProjectCase):
    """«Линейка присоединяется к Потоку N» после проверки: включение отметки, когда уроки источника встают
    туда, где мешают урокам потока-копии, и сообщение об отметке. Проект — ``builders.jointProject``.
    """
    NAME = "__test_joint_conflicts__"

    def marked(self):
        """{курс: together_with} курсов «ЕГЭ основной» Потока 2, у которых стоит отметка."""
        groups = self.load("settings.json")["classes"]["custom_groups"]

        return {group["name"]: group["together_with"] for group in groups
                if group.get("stream_id") == 2 and group.get("program") == JOINT_LINE and "together_with" in group}

    def test_set_joint_names_conflicts_in_copy_stream(self):
        """Поток 2 уже принят: «Информатика» «ЕГЭ основной» стоит в пн 1-м уроком, там же Математика
        Потока 1, а «Математика» и «Информатика» — пара «нельзя». Отметка без force — вопрос
        web.classes.joint_conflicts с «Информатикой», файлы не меняются; с force отметка стоит (своих
        уроков у копий не было — версии нет) и сообщение web.classes.joint_on.
        """
        settings, answer = jointProject()
        settings.setdefault("joint_subject_pairs", []).append(["Математика", "Информатика"])
        answer[INF_2] = courseWeek("Информатика", "Информатика #1", (0, 0))
        self.openProject(settings, answer)
        files, versions = (self.raw("settings.json"), self.raw("answer.json")), self.versions()

        body = self.ok("setJoint", section=2, line=JOINT_LINE, source=1)

        self.assertRegex(body.get("confirm", ""), keyPattern("web.classes.joint_conflicts"))
        self.assertIn(INF_2, body["confirm"])
        self.assertNotRegex(body["confirm"], keyPattern("web.classes.joint_confirm"))
        self.assertEqual((self.raw("settings.json"), self.raw("answer.json")), files)

        body = self.ok("setJoint", section=2, line=JOINT_LINE, source=1, force=True)

        self.assertRegex(body.get("message", ""), keyPattern("web.classes.joint_on"))
        self.assertEqual(self.marked(), {MATH_2: 1, RUS_2: 1})
        self.assertEqual(self.load("answer.json")[MATH_2], self.load("answer.json")[MATH_1])
        self.assertEqual(self.versions(), versions)

    def test_conflicts_and_own_lessons_are_one_question(self):
        """У «Математики» «ЕГЭ основной» Потока 2 свои уроки, и уроки источника ещё и мешают
        «Информатике»: один вопрос с обоими абзацами (web.classes.joint_confirm и joint_conflicts),
        с force — версия «Перед: …».
        """
        settings, answer = jointProject()
        settings.setdefault("joint_subject_pairs", []).append(["Математика", "Информатика"])
        answer[INF_2] = courseWeek("Информатика", "Информатика #1", (2, 0))
        answer[MATH_2] = courseWeek("Математика", JOINT_PIN_TEACHER, (1, 0), (4, 0))
        self.openProject(settings, answer)
        versions = self.versions()

        body = self.ok("setJoint", section=2, line=JOINT_LINE, source=1)

        self.assertRegex(body.get("confirm", ""), keyPattern("web.classes.joint_confirm"))
        self.assertRegex(body["confirm"], keyPattern("web.classes.joint_conflicts"))

        self.ok("setJoint", section=2, line=JOINT_LINE, source=1, force=True)
        self.assertEqual(len(self.versions()), len(versions) + 1)

    def test_lessons_already_matching_are_no_conflict(self):
        """AC-6 вместе с проверкой помех: уроки «ЕГЭ основной» Потока 2 уже как в Потоке 1, и рядом с ними
        «Информатика» в пн 1-м уроком (пара «нельзя», так уже было до отметки). Новых часов у копий нет —
        отметка без вопроса.
        """
        settings, answer = jointProject()
        settings.setdefault("joint_subject_pairs", []).append(["Математика", "Информатика"])

        for subject in ("Математика", "Русский язык"):
            answer[jointCourse(2, subject)] = copy.deepcopy(answer[jointCourse(1, subject)])

        settings["classes"]["lessons"][RUS_2] = copy.deepcopy(settings["classes"]["lessons"][RUS_1])
        answer[INF_2] = courseWeek("Информатика", "Информатика #1", (0, 0))
        self.openProject(settings, answer)

        body = self.ok("setJoint", section=2, line=JOINT_LINE, source=1)

        self.assertNotIn("confirm", body)
        self.assertEqual(self.marked(), {MATH_2: 1, RUS_2: 1})


class JointCopyLineTests(RealProjectCase):
    """«Скопировать в другие потоки» и смена источника у присоединённой линейки (проект ``builders.jointProject``)."""
    NAME = "__test_joint_copy_line__"

    def test_copy_line_gives_new_copy_source_lessons(self):
        """«Скопировать в другие потоки» из Потока 1: в присоединённой линейке Потока 2 появляется
        «Биология» — копия; её уроки в answer.json сразу как у источника.
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)

        self.ok("copyLine", section=1, line=JOINT_LINE)

        answer = self.load("answer.json")
        self.assertTrue(hasLessons(answer, BIO_1))
        self.assertEqual(answer[BIO_2], answer[BIO_1])

    def test_copy_line_without_new_copies_keeps_answer(self):
        """Без новых копий (копирование из Потока 3: в Поток 1 добавляется обычный курс) answer.json
        не переписывается.
        """
        settings, answer = jointProject()
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)
        before = self.raw("answer.json")

        self.ok("copyLine", section=3, line=JOINT_LINE)

        self.assertEqual(self.raw("answer.json"), before)

    def test_switch_source_names_cannot_hours(self):
        """Поток 3 был с Потоком 1; у Потока 2 «Математика» стоит (1, 2), (3, 2) у «Математика #2», а у неё
        на этапе Потока 3 в (1, 2) «не может». Переключение на Поток 2 без force — вопрос с абзацем
        web.classes.joint_cannot: копии те же по имени, но их уроки переезжают в часы нового источника.
        """
        settings, answer = jointProject()
        answer[MATH_2] = courseWeek("Математика", "Математика #2", (1, 2), (3, 2))
        markJoint(settings, 3, JOINT_LINE, 1, answer)
        markCannot(settings, "Математика #2", "3", (1, 2))
        self.openProject(settings, answer)

        body = self.ok("setJoint", section=3, line=JOINT_LINE, source=2)

        self.assertText("web.classes.joint_cannot", body["confirm"])


class JointCannotTests(RealProjectCase):
    """AC-39: «не может» преподавателя в потоке-копии. Общие уроки встают в часы источника; если у их
    преподавателя на этапе потока-копии в эти часы «не может», отметка не запрещается, а в вопросе
    setJoint есть абзац web.classes.joint_cannot: преподаватель, дни и часы. Проект — ``builders.jointProject``
    (у «Математика #1» общие уроки в пн и ср 1-м уроком, у «Русский язык #1» — во вт и чт 2-м).
    """
    NAME = "__test_joint_cannot__"

    def marked(self):
        """{курс: together_with} курсов «ЕГЭ основной» Потока 2, у которых стоит отметка."""
        groups = self.load("settings.json")["classes"]["custom_groups"]

        return {group["name"]: group["together_with"] for group in groups
                if group.get("stream_id") == 2 and group.get("program") == JOINT_LINE and "together_with" in group}

    def test_set_joint_names_cannot_hours(self):
        """У «Математика #1» на этапе «Поток 2» в пн 1-м уроком «не может», а там встанет общий урок.
        Без force — вопрос web.classes.joint_cannot с преподавателем и этим днём и часом (среда, где
        отметки нет, не названа; своих уроков у копий нет — абзаца web.classes.joint_confirm нет),
        файлы не меняются. С force отметка стоит, копия — как источник (не запрет), версии нет.
        """
        settings, answer = jointProject()
        markCannot(settings, "Математика #1", "2", (0, 0))
        self.openProject(settings, answer)
        files, versions = (self.raw("settings.json"), self.raw("answer.json")), self.versions()

        body = self.ok("setJoint", section=2, line=JOINT_LINE, source=1)

        self.assertTrue(body.get("confirm"), f"вопроса нет, ответ: {body.get('message')}")
        grid = self.load("settings.json")
        self.assertIn("Математика #1", body["confirm"])
        self.assertIn(slotText(grid, 0, 0), body["confirm"])
        self.assertNotIn(slotText(grid, 2, 0), body["confirm"])
        self.assertText("web.classes.joint_cannot", body["confirm"])
        self.assertNotRegex(body["confirm"], keyPattern("web.classes.joint_confirm"))
        self.assertEqual((self.raw("settings.json"), self.raw("answer.json")), files)

        body = self.ok("setJoint", section=2, line=JOINT_LINE, source=1, force=True)

        self.assertRegex(body.get("message", ""), keyPattern("web.classes.joint_on"))
        self.assertEqual(self.marked(), {MATH_2: 1, RUS_2: 1})
        self.assertEqual(self.load("answer.json")[MATH_2], self.load("answer.json")[MATH_1])
        self.assertEqual(self.versions(), versions)

    def test_cannot_hours_and_conflicts_are_one_question(self):
        """«Не может» вместе с помехами соседей: общая «Математика» встаёт в пн 1-м уроком к «Информатике»
        (пара «нельзя»), а у «Русский язык #1» на этапе «Поток 2» во вт 2-м уроком «не может». Один вопрос
        с обоими абзацами: web.classes.joint_conflicts и web.classes.joint_cannot (преподаватель, день и час).
        """
        settings, answer = jointProject()
        settings.setdefault("joint_subject_pairs", []).append(["Математика", "Информатика"])
        answer[INF_2] = courseWeek("Информатика", "Информатика #1", (0, 0))
        markCannot(settings, "Русский язык #1", "2", (1, 1))
        self.openProject(settings, answer)

        body = self.ok("setJoint", section=2, line=JOINT_LINE, source=1)

        self.assertRegex(body.get("confirm", ""), keyPattern("web.classes.joint_conflicts"))
        self.assertIn("Русский язык #1", body["confirm"])
        self.assertIn(slotText(self.load("settings.json"), 1, 1), body["confirm"])
        self.assertText("web.classes.joint_cannot", body["confirm"])

    def test_cannot_under_lesson_that_already_stood_is_named(self):
        """У «Математика #1» на этапе «Поток 2» в пн 1-м уроком «не может», а урок курса Потока 2 у него
        там уже стоит — до отметки курс обычный, предупреждения о нём не было. Отметка всё равно
        спрашивает про «не может» (без помех и без «не может» вопроса нет, иначе — есть):
        * «уроки как у источника» — те же, что у «Математика #1» Потока 1;
        * «один урок там же» — другие уроки, но пн 1-й урок у того же преподавателя уже стоял.
        """
        for title, slots in (("уроки как у источника", ((0, 0), (2, 0))), ("один урок там же", ((0, 0), (4, 2)))):
            with self.subTest(title):
                settings, answer = jointProject()
                answer[MATH_2] = courseWeek("Математика", "Математика #1", *slots)
                markCannot(settings, "Математика #1", "2", (0, 0))
                self.openProject(settings, answer)

                body = self.ok("setJoint", section=2, line=JOINT_LINE, source=1)

                self.assertTrue(body.get("confirm"), f"вопроса нет, ответ: {body.get('message')}")
                self.assertIn("Математика #1", body["confirm"])
                self.assertIn(slotText(self.load("settings.json"), 0, 0), body["confirm"])
                self.assertText("web.classes.joint_cannot", body["confirm"])

    def test_cannot_of_source_stage_or_other_hours_asks_nothing(self):
        """Сторож: «не может» на этапе потока-источника (у «Математика #1» в пн 1-м уроком на «Поток 1»)
        и «не может» на этапе «Поток 2» не в часы общих уроков (пт 3-м уроком) вопроса не дают —
        отметка ставится сразу, как раньше.
        """
        settings, answer = jointProject()
        markCannot(settings, "Математика #1", "1", (0, 0))
        markCannot(settings, "Математика #1", "2", (4, 2))
        self.openProject(settings, answer)

        body = self.ok("setJoint", section=2, line=JOINT_LINE, source=1)

        self.assertNotIn("confirm", body)
        self.assertEqual(self.marked(), {MATH_2: 1, RUS_2: 1})


class JointQuestionTests(RealProjectCase):
    """Вопрос setJoint: какие уроки уберутся и чьи варианты составлять заново."""
    NAME = "__test_joint_question__"

    def test_disjoint_source_refused(self):
        """Ручной запрос к потоку без единого такого же предмета — отказ web.error.joint_source, файлы те же."""
        settings, answer = jointProject()
        addCourse(settings, 1, "Новая", "Математика", 1, "2026-09-07")
        addCourse(settings, 2, "Новая", "Информатика", 1, "2026-11-23")
        self.openProject(settings, answer)
        before = self.files()

        self.assertText("web.error.joint_source", self.refused("setJoint", section=2, line="Новая", source=1))
        self.assertEqual(self.files(), before)

    def test_conflict_names_other_stage(self):
        """Общий урок встанет туда, где преподаватель ведёт курс Потока 3: абзац web.classes.joint_conflicts
        с этим курсом, а составить заново советует варианты Потока 3.
        """
        settings, answer = jointProject()
        setSectionEnd(settings, 1, STREAM_1_END)
        answer[OWN_3] = courseWeek("Математика", OLD_TEACHER, (0, 0))
        self.openProject(settings, answer)

        confirm = self.ok("setJoint", section=2, line=JOINT_LINE, source=1).get("confirm", "")
        paragraph = self.paragraph("web.classes.joint_conflicts", confirm)

        self.assertIn(tr("menu.main.tab.classes.slot_busy", detail=OWN_3), paragraph)
        self.assertRegex(paragraph, keyPattern("web.classes.joint_conflicts", stages="Поток 3"))

    def test_source_without_lessons_removes_copy_lessons(self):
        """У Потока 1 уроков нет, у Математики Потока 2 свои: вопрос не обещает «поставить в те же часы»
        (web.classes.joint_confirm), а называет курс в web.classes.joint_confirm_waiting. После «Да» уроков
        у копии нет, сохранена версия.
        """
        settings, answer = jointProject(accepted=False)
        answer[MATH_2] = courseWeek("Математика", NEW_TEACHER, (1, 0), (4, 0))
        self.openProject(settings, answer)
        versions = len(self.versions())

        confirm = self.ok("setJoint", section=2, line=JOINT_LINE, source=1).get("confirm", "")

        self.assertNoText("web.classes.joint_confirm", confirm)
        self.assertIn(MATH_2, self.paragraph("web.classes.joint_confirm_waiting", confirm))
        self.assertText("web.classes.joint_version", confirm)

        self.ok("setJoint", section=2, line=JOINT_LINE, source=1, force=True)

        self.assertNotIn(MATH_2, self.load("answer.json"))
        self.assertEqual(len(self.versions()), versions + 1)

    def test_switch_names_dropped_courses(self):
        """«ЕГЭ основной» Потока 3 была с Потоком 1, выбрали Поток 2. «Истории» в Потоке 2 нет — она
        названа в web.classes.joint_confirm_dropped; у Потока 2 уроков нет — Математика Потока 3 названа
        в web.classes.joint_confirm_waiting. Абзаца web.classes.joint_confirm («поставить в те же часы») нет.
        """
        settings, answer = jointProject()
        settings["subjects"].append(["История", 1])
        setTeacherSubjects(settings, "История #1", ["История"])
        history_1 = addCourse(settings, 1, JOINT_LINE, "История", 1, "2026-09-07")
        history_3 = addCourse(settings, 3, JOINT_LINE, "История", 1, "2027-01-11")
        answer[history_1] = courseWeek("История", "История #1", (4, 1))
        markJoint(settings, 3, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)

        confirm = self.ok("setJoint", section=3, line=JOINT_LINE, source=2).get("confirm", "")

        self.assertNoText("web.classes.joint_confirm", confirm)
        self.assertIn(history_3, self.paragraph("web.classes.joint_confirm_dropped", confirm))
        self.assertNotIn(history_3, self.paragraph("web.classes.joint_confirm_waiting", confirm))
        self.assertIn(MATH_3, self.paragraph("web.classes.joint_confirm_waiting", confirm))


class StartedSourceTests(RealProjectCase):
    """Поток 1 ещё не начался, а его копии в Потоке 2 уже идут (что видит страница — test_web_state,
    StartedSourceStateTests)."""
    NAME = "__test_joint_started_source__"

    def setUp(self):
        super().setUp()
        settings, answer = jointProject()
        shiftStream(settings, 1, FUTURE)
        shiftStream(settings, 2, PAST)
        markJoint(settings, 2, JOINT_LINE, 1, answer)
        self.openProject(settings, answer)

    def test_delete_source_does_not_call_it_running(self):
        """Удаление ``MATH_1``: в вопросе нет «курсы уже идут — уроки пропадут» (ученики Потока 1 ещё
        не ходят, а уроки копии останутся), а копия названа в web.classes.joint_remove_note.
        """
        confirm = self.ok("deleteCourse", course=MATH_1).get("confirm", "")

        self.assertNoText("web.confirm_remove_started", confirm)
        self.assertIn(MATH_2, self.paragraph("web.classes.joint_remove_note", confirm))

    def test_copy_line_names_streams_apart(self):
        """«Скопировать в другие потоки» из Потока 3: Поток 2 идёт сам (web.classes.copy_skipped), а Поток 1 —
        только через присоединённые курсы (web.classes.copy_skipped_joint). Оба не тронуты.
        """
        message = self.ok("copyLine", section=3, line=OWN_LINE).get("message", "")

        self.assertRegex(message, keyPattern("web.classes.copy_skipped", streams="Поток 2"))
        self.assertRegex(message, keyPattern("web.classes.copy_skipped_joint", streams="Поток 1"))
        self.assertNotIn(OWN_LINE, [group.get("program") for group in self.load("settings.json")["classes"]["custom_groups"]
                                    if group.get("stream_id") == 1])
