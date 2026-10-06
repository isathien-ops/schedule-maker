"""Вкладка «Экспорт»: все скачивания (GET /api/project/<p>/export/<kind>) — ZIP проекта, Excel
по курсам, по преподавателям, календарь, список преподавателей и варианты этапа.
Пара на странице — static/tabs/export.js.

Маршрут export выбирает по kind функцию: книги по принятому расписанию (SCHEDULE_BOOKS), архив
проекта, список преподавателей и варианты этапа; книги Excel отдаются одной функцией sendWorkbook.
Сами книги собирает src/modules/functions/export.py.

Зависимости: core (app, LOCK, UserError), project (файлы проекта), ranking (варианты этапа
с оценками) и предметные модули (export — книги Excel, tree — архив проекта, stages,
penalties, variants).
"""

import io
import os
import tempfile

from flask import request, send_file

from src.modules.translate import translate
from src.modules.functions.export import (
    CourseDatesError, calendarWorkbook, coursesWorkbook, teacherListWorkbook, teachersWorkbook, variantsWorkbook
)
from src.modules.functions.penalties import customKey, penalties
from src.modules.functions.stages import getStages, stageLabel
from src.modules.functions.tree import exportProjectArchive
from src.modules.functions.variants import METRICS
from src.web.core import LOCK, UserError, app
from src.web.project import loadAnswer, loadAnswerOrEmpty, loadSettings, projectPath, requireStage
from src.web.ranking import rankedVariants

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Книги по принятому расписанию: kind -> (функция книги, ключ ru.hjson с именем файла)
SCHEDULE_BOOKS = {
    "courses": (coursesWorkbook, "menu.main.tab.export.courses_file"),
    "teachers": (teachersWorkbook, "menu.main.tab.export.teachers_file"),
    "calendar": (calendarWorkbook, "menu.main.tab.export.calendar_file"),
}


def sendWorkbook(book, filename):
    """Отдаёт книгу Excel (openpyxl) как скачиваемый файл `filename`."""
    data = io.BytesIO()
    book.save(data)
    data.seek(0)

    return send_file(data, as_attachment=True, download_name=filename, mimetype=XLSX)


def projectZip(project):
    """ZIP-архив всего проекта (его можно загрузить через «Импорт проекта»)."""
    with tempfile.TemporaryDirectory() as folder:
        archive = os.path.join(folder, f"{project}.zip")
        exportProjectArchive(projectPath(project), archive)

        with open(archive, "rb") as file:
            data = io.BytesIO(file.read())

    return send_file(data, as_attachment=True, download_name=f"{project}.zip", mimetype="application/zip")


def teacherList(project):
    """Преподаватели: курсы и отметки времени по этапам. Расписание для этого не обязательно,
    поэтому оно читается терпимо (loadAnswerOrEmpty).
    """
    settings = loadSettings(project)
    stages = [(item["key"], stageLabel(item["key"], translate)) for item in getStages(settings)]
    book = teacherListWorkbook(settings, loadAnswerOrEmpty(project), translate, stages)

    return sendWorkbook(book, f"{project}-{translate('menu.main.tab.export.teacher_list_file')}.xlsx")


def variantsBook(project, stage):
    """Варианты этапа ``stage`` с «Предпросмотра» (адрес …/export/variants?stage=<этап>).

    Строки сравнения — как на странице: итог, встроенные правила, свои правила. Без stage
    или с неизвестным этапом — общая ошибка (такой адрес страница не строит). Этап без
    вариантов — понятная ошибка «Вариантов пока нет — составьте их на шаге «Запуск»» (тот же
    текст, что вкладка показывает вместо кнопки): так бывает, если варианты стёрли в другой вкладке.
    """
    requireStage(loadSettings(project), stage)
    settings, ranked = rankedVariants(project, stage)

    if not ranked:
        raise UserError(translate("web.export_variants.none"))

    columns = [("total", translate("menu.main.tab.preview.column.total"))]
    columns += [(key, translate(f"menu.main.tab.preview.column.{key}").replace("\n", " ")) for key, _ in METRICS]
    columns += [(customKey(item["id"]), item["name"]) for item in penalties(settings)]
    title = stageLabel(stage, translate)
    book = variantsWorkbook(settings, ranked, columns, translate, f"{translate('web.export_variants.title')}: {title}")

    return sendWorkbook(book, f"{project}-{translate('web.export_variants.file')}-{title}.xlsx")


def scheduleBook(project, kind):
    """Книга по принятому расписанию (courses, teachers или calendar): «<проект>-курсы.xlsx» и т. п.

    Нужно непустое принятое расписание. Неверные даты курсов (export.CourseDatesError, её бросает
    только calendarWorkbook: книги courses и teachers даты не разбирают) — понятная ошибка;
    другие ошибки сборки книги так не маскируются. try общий для трёх книг.
    """
    makeBook, filename = SCHEDULE_BOOKS[kind]
    answer = loadAnswer(project)

    if not answer:
        raise UserError(translate("web.common.no_schedule"))

    try:
        book = makeBook(loadSettings(project), answer, translate)

    except CourseDatesError:
        raise UserError(translate("menu.main.tab.export.invalid_course_dates"))

    return sendWorkbook(book, f"{project}-{translate(filename)}.xlsx")


# Скачивания без параметров: kind -> функция от имени проекта
DOWNLOADS = {"project": projectZip, "teacher_list": teacherList}


@app.route("/api/project/<project>/export/<kind>")
def export(project, kind):
    """Файл для скачивания.

    kind:
      "project"  — ZIP-архив всего проекта (его можно загрузить через «Импорт проекта»);
      "courses"  — Excel: расписание по курсам;
      "teachers" — Excel: расписание по преподавателям;
      "calendar" — Excel: календарь занятий по датам;
      "teacher_list" — Excel: преподаватели, их курсы и отметки времени (расписание не нужно);
      "variants" — Excel: варианты этапа с «Предпросмотра», адрес …/export/variants?stage=<этап>;
                   без stage или с неизвестным этапом — общая ошибка (requireStage), без вариантов —
                   понятная «Вариантов пока нет» (см. variantsBook).
    Только для courses, teachers и calendar нужно непустое принятое расписание. Неверные даты
    курсов бывают только у calendar, и сервер показывает понятную ошибку (см. scheduleBook).
    Неизвестный kind — общая ошибка.
    """
    with LOCK:
        if kind == "variants":
            return variantsBook(project, request.args.get("stage"))

        if kind in DOWNLOADS:
            return DOWNLOADS[kind](project)

        if kind in SCHEDULE_BOOKS:
            return scheduleBook(project, kind)

        raise UserError(translate("web.error.generic"))
