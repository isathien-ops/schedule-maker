"""Общая заготовка браузерных тестов «линейки, которая присоединяется к Потоку N» (сама тестов не содержит).

``JointCase`` — база классов с проектом ``builders.jointProject`` вместо данных 2026/27 и помощниками
вкладок; рядом — имена курсов проекта, селекторы и помощники разбора недель. Её используют
``test_joint.py`` и ``test_joint_edges.py``. Лежит отдельно, а не в ``test_joint.py``: модуль тестов,
импортированный другим модулем, при ``discover tests`` загружается второй раз под другим именем
(``tests.ui.test_joint`` рядом с ``ui.test_joint``) — это запрещает tests/test_structure.py
(ImportOrderTests.test_test_modules_do_not_import_each_other).
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import os
import shutil

from src.modules.functions.courses import courseName
from src.modules.functions.model import courseSubject
from src.modules.translate import translate
from tests.builders import JOINT_LINE, LEVEL_LINE, OWN_LINE, courseWeek, jointCourse, jointProject, markJoint
from tests.real_project import lessons as lessonsOf
from tests.ui.base import UICase, expect, plain, t


# Выбор «Присоединяется к» — в шапке карточки курсов линейки, не в строках таблицы
JOINT_SELECT = ".sticky-card select:not(tbody select)"

STREAM_1, STREAM_2 = f"{t('stage.stream')} 1", f"{t('stage.stream')} 2"

# Курсы проекта jointProject: источники в Потоке 1 и копии в Потоке 2 (после markJoint)
MATH_1, MATH_2 = jointCourse(1, "Математика"), jointCourse(2, "Математика")
RUS_1, RUS_2 = jointCourse(1, "Русский язык"), jointCourse(2, "Русский язык")
INFO_2 = jointCourse(2, "Информатика")

# Свои уроки обычных курсов Потока 2 (все курсы, кроме «ЕГЭ основной», стоят полностью)
OWN_STREAM_2 = {
    INFO_2: courseWeek("Информатика", "Информатика #1", (4, 1)),
    jointCourse(2, "Математика", LEVEL_LINE): courseWeek("Математика", "Математика #2", (1, 0), (3, 0)),
    jointCourse(2, "Русский язык", LEVEL_LINE): courseWeek("Русский язык", "Русский язык #2", (0, 2), (2, 2)),
    jointCourse(2, "Математика", OWN_LINE): courseWeek("Математика", "Математика #3", (4, 0)),
}

# Карточки уроков недели (вкладки «Расписание» и «Предпросмотр»)
LESSONS = ".sticky-card .lesson"
PREVIEW_LESSONS = ".preview-week .lesson"


def jointCopies(settings):
    """{копия: источник} по полю ``together_with`` курсов (имя источника — через courseName)."""
    return {
        group["name"]: courseName(group["together_with"], group["program"], courseSubject(group))
        for group in settings["classes"]["custom_groups"] if "together_with" in group
    }


def cells(week):
    """Уроки недели: {(день, урок): (предмет, преподаватели)}."""
    return {(day, lesson): (cell["subject"], tuple(cell.get("teachers", []))) for day, lesson, cell in lessonsOf(week or [])}


class JointCase(UICase):
    """База: проект ``builders.jointProject`` вместо данных 2026/27 и помощники вкладок."""

    def useJoint(self, accepted=True, mark=True, own=None):
        """Подменяет данные тестового проекта на jointProject: Поток 1 принят (``accepted``), «ЕГЭ
        основной» Потока 2 присоединяется к Потоку 1 (``mark``, копии согласованы), ``own`` — ещё
        уроки {курс: неделя}. Варианты удаляются, тщательность и число вариантов — как в шаблоне.
        Возвращает (settings, answer); ``self.copies`` — {копия: источник}.
        """
        settings, answer = jointProject(accepted=accepted)
        self.copies = markJoint(settings, 2, JOINT_LINE, 1, answer) if mark else {}
        answer.update(copy.deepcopy(own or {}))
        settings["iterations"], settings["variants"] = 1000000, 2
        self.save("settings.json", settings)
        self.save("answer.json", answer)
        shutil.rmtree(f"{self.folder}/stages", ignore_errors=True)

        return settings, answer

    def known(self, key):
        """Текст ``key`` есть в ru.hjson (иначе страница показала бы сам ключ)."""
        self.assertNotEqual(translate(key), key, f"в ru.hjson нет текста {key}")

    def raw(self, name):
        """Файл тестового проекта байтами — чтобы проверить, что его не переписали."""
        with open(os.path.join(self.folder, name), "rb") as file:
            return file.read()

    def groups(self):
        """Курсы из settings.json: имя -> группа."""
        return {group["name"]: group for group in self.load("settings.json")["classes"]["custom_groups"]}

    def marks(self, section=2, line=JOINT_LINE):
        """{курс: together_with} курсов линейки ``line`` потока ``section``, у которых стоит отметка."""
        return {name: group["together_with"] for name, group in self.groups().items()
                if group.get("stream_id") == section and group.get("program") == line and "together_with" in group}

    # ------------------------------------------------------------------ «Курсы»

    def jointSelect(self):
        """Выбор «Присоединяется к» в шапке карточки курсов."""
        return self.page.locator(JOINT_SELECT)

    def chosenLabel(self):
        """Подпись выбранного пункта в «Присоединяется к»."""
        return plain(self.jointSelect().evaluate("(select) => select.selectedOptions[0]?.textContent ?? ''"))

    # ------------------------------------------------------------------ «Расписание»

    def mode(self, key):
        """Выбирает режим просмотра «Расписания»."""
        self.page.locator(".view-list .card-head select").select_option(key)
        expect(self.page.locator(".view-list .card-head select")).to_have_value(key)

    def choose(self, mode, key):
        """Режим ``mode`` «Расписания» и в нём пункт списка с ключом ``key`` (как его запоминает страница)."""
        self.mode(mode)
        self.page.evaluate("([mode, key]) => { remember(`view.${mode}`, key); render(); }", [mode, key])
