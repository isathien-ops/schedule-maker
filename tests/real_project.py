"""Общая заготовка для тестов, которые работают с копией реального проекта 2026/27 через сервер.

Основа для тестов сервера `test_web_*.py` (``RealProjectCase``): «сегодня» зафиксировано как
04.10.2026 (поток 1 уже идёт, доп. курсы с 05.10 и поток 2 с 23.11 ещё не начались), архив
`Расписание_2026-27.zip` импортируется во временную папку проектов (папка данных подменена
в `tests/__init__.py`) под служебным именем класса (``NAME``, вида ``__test_…__``), а после
теста удаляется. Здесь же — имена курсов и преподавателей этого проекта, на которых построены
проверки, и поддельный решатель (``FakeSolver``: подмена subprocess.Popen для сборки через сервер,
им пользуются и тесты сервера, и браузерные тесты). Модуль не начинается с `test_`, поэтому сам
тестов не содержит. Ещё здесь ``unstaffed`` (курс, который никто не может вести) и
``forecastText`` (подпись прогноза закреплений) — для тестов прогноза сервера и страницы,
``keyPattern`` (текст по ключу ru.hjson как регулярное выражение — им пользуются и тесты сервера,
и браузерные тесты), а у ``RealProjectCase`` — ``assertText`` / ``assertNoText`` (есть / нет текста
по ключу в ответе сервера).
Для функции «Линейка присоединяется к потоку» у ``RealProjectCase`` есть ``markJoint`` (отметка прямо
в файлах проекта), ``useProject`` (подменить данные проекта, например, на ``builders.jointProject``)
и ``openProject`` (подменить данные и открыть проект на сервере заново).
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import copy
import datetime
import io
import json
import os
import re
import shutil
import time
import unittest
from unittest import mock

from src.variables import PATH_TO_FOLDER
from src.modules.functions.courses import setTeacherCourseState
from src.modules.functions.stages import stageCourses
from src.modules.functions.tree import importProjectArchive
from src.web import build
from src.modules.translate import tr, translate
from src.web.server import app
from tests.builders import markJoint as markJointData

ARCHIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Расписание_2026-27.zip")

# Курсы и преподаватели проекта Расписание_2026-27.zip, на которых построены проверки
# («сегодня» 04.10.2026: поток 1 идёт, доп. курсы и поток 2 ещё не начались)
RUS_BASE_1 = "Поток 1 — ЕГЭ основной — Русский язык"     # идёт, 2 урока стоят: [0, 1], [3, 1]
PHYS_PRO_1 = "Поток 1 — ЕГЭ продвинутый — Физика"        # идёт, уроки [1, 1], [4, 1] без преподавателя
PHYS_BASE_TEACHER = "Передерин Дмитрий"                  # в те же часы ведёт «Поток 1 — ЕГЭ основной — Физика»
GEO_1 = "Поток 1 — ОГЭ — География"                      # Тюгалева, 1 урок
CHEM_OGE_2 = "Поток 2 — ОГЭ — Химия"                     # стоит в расписании: Баранникова, [3, 1], 1 урок
CHEM_10_2 = "Поток 2 — 10 класс — Химия"                 # стоит: Баранникова, [0, 1]
RUS_8_2 = "Поток 2 — 8 класс — Русский язык"             # нет в расписании, 1 урок
RUS_PRO_2 = "Поток 2 — ЕГЭ продвинутый — Русский язык"   # стоит в расписании
RUS_BASE_2 = "Поток 2 — ЕГЭ основной — Русский язык"     # нет в расписании, 2 урока
GEO_2 = "Поток 2 — ОГЭ — География"                      # Тюгалева, 1 урок
SEM_RUS = "Семинар ЕГЭ продвинутый: Русский язык"        # доп. курсы, урок [6, 0]
SEM_MATH = "Семинар ЕГЭ продвинутый: Математика"         # доп. курсы, урок [6, 1]
CHEMIST = "Баранникова Анна"                             # ведёт химию в потоках 1 и 2


def unstaffed(settings, course, subject):
    """Курс ``course`` никто не «может вести» и не «ведёт» (как новый курс, пока преподаватели не
    отмечены): решатель его уроки не ставит. Меняет и возвращает ``settings``.
    """
    for name in settings["teachers"]:
        setTeacherCourseState(settings, name, subject, course, "no")

    return settings


def forecastText(forecast):
    """Подпись прогноза закреплений (поле forecast этапа): с хвостом «без преподавателя», если такие уроки есть."""
    return tr("web.run.pin_forecast_no_teacher" if forecast["noTeacher"] else "web.run.pin_forecast", **forecast)


def keyPattern(key, **values):
    """Текст ``key`` из ru.hjson как регулярное выражение (re.S: текст может быть в несколько строк).

    Подстановка ``{имя}`` — значение ``values[имя]`` (как в тексте, через str), если оно передано,
    иначе любой непустой текст. Так ответ сервера или текст страницы сверяется с текстом по ключу,
    а не с переписанной в тест фразой: поправили формулировку в ru.hjson — тест её подхватит.
    """
    pattern = ""

    # re.split с группой: чётные части — неизменный текст, нечётные — имена подстановок
    for index, part in enumerate(re.split(r"\{(\w+)\}", translate(key))):
        if index % 2 == 0:
            pattern += re.escape(part)
        else:
            pattern += re.escape(str(values[part])) if part in values else ".+?"

    return re.compile(pattern, re.S)


class FrozenDate(datetime.date):
    """Подмена `datetime.date`, у которой «сегодня» всегда 04.10.2026."""
    @classmethod
    def today(cls):
        """Фиксированная дата «сегодня» для тестов."""
        return cls(2026, 10, 4)


def lessons(week):
    """Занятые ячейки недели: [(день, урок, ячейка)] для всех ячеек, где subject не «#»."""
    return [(day, lesson, cell) for day, cells in enumerate(week) for lesson, cell in enumerate(cells) if cell.get("subject", "#") != "#"]


def emptied(week):
    """Та же неделя, но все ячейки пустые («#») — так решатель пишет курс без уроков."""
    return [[{"subject": "#", "teachers": []} for _ in day] for day in week]


def relocated(week, day, lesson):
    """Неделя курса с одним уроком: тот же урок, но в ячейке (day, lesson); остальные ячейки пустые."""
    result = emptied(week)
    result[day][lesson] = copy.deepcopy(lessons(week)[0][2])

    return result


class FakeProcess:
    """Поддельный процесс решателя: вывод — заранее заданные строки, код выхода — solver.code."""

    def __init__(self, solver, args):
        self.solver = solver
        self.args = args
        self.killed = False
        self._handle = 0
        self.stdout = io.BytesIO("".join(line + "\n" for line in solver.lines).encode("utf-8"))

    def wait(self):
        if self.solver.on_wait:
            self.solver.on_wait(self)

        return -1 if self.killed else self.solver.code

    def poll(self):
        return self.solver.code

    def kill(self):
        self.killed = True


class FakeSolver:
    """Подмена subprocess.Popen: каждый вызов — один «запуск решателя».

    output — что записать в output.json (словарь или функция от номера запуска), code — код выхода.
    calls — список по каждому запуску: {"args" (командная строка целиком), "options" (её пары
    «--ключ значение»), "input", "weights" (прочитанные входные файлы), "process" (``FakeProcess``),
    "kwargs" (остальные аргументы Popen: stdout, creationflags…)}.
    """

    def __init__(self, output=None, code=0, lines=("решатель работает",), on_start=None, on_wait=None):
        self.output, self.code, self.lines = output, code, list(lines)
        self.on_start, self.on_wait = on_start, on_wait
        self.calls = []

    def __call__(self, args, **kwargs):
        options = dict(zip(args[1::2], args[2::2]))

        with open(options["--input"], encoding="utf-8") as file:
            source = json.load(file)

        with open(options["--weights"], encoding="utf-8") as file:
            weights = json.load(file)

        process = FakeProcess(self, args)
        self.calls.append({"args": args, "options": options, "input": source, "weights": weights, "process": process, "kwargs": kwargs})

        output = self.output(len(self.calls)) if callable(self.output) else self.output

        if self.code == 0 and output is not None:
            with open(options["--output"], "w", encoding="utf-8") as file:
                json.dump(output, file, ensure_ascii=False)

        if self.on_start:
            self.on_start(process)

        return process


@unittest.skipUnless(os.path.exists(ARCHIVE), "the 2026/27 project archive is not here")
class RealProjectCase(unittest.TestCase):
    """База: свежая копия реального проекта на каждый тест и короткие помощники для запросов."""
    NAME = "__test_real__"

    @property
    def folder(self):
        """Папка тестового проекта."""
        return f"{PATH_TO_FOLDER}/projects/{self.NAME}"

    def setUp(self):
        """Замораживает дату, заново импортирует реальный проект и открывает его на сервере."""
        frozen = mock.patch("datetime.date", FrozenDate)
        frozen.start()
        self.addCleanup(frozen.stop)

        shutil.rmtree(self.folder, ignore_errors=True)
        importProjectArchive(ARCHIVE, self.NAME)
        self.client = app.test_client()
        self.assertEqual(self.client.post(f"/api/project/{self.NAME}/open").status_code, 200)

    def tearDown(self):
        """Останавливает сборку, если она идёт, и удаляет тестовый проект."""
        job = build.JOBS.get(self.NAME)

        if job and job["running"] and not job.get("fake"):
            build.stopJob(self.NAME)
            self.waitJob(30)

        build.forget(self.NAME)
        shutil.rmtree(self.folder, ignore_errors=True)

    def waitJob(self, seconds=60):
        """Ждёт, пока фоновая сборка закончится (не дольше `seconds`)."""
        deadline = time.time() + seconds

        while build.JOBS.get(self.NAME, {}).get("running") and time.time() < deadline:
            time.sleep(0.1)

    def act(self, action, **args):
        """Вызывает действие сервера; возвращает (HTTP-код, JSON-ответ)."""
        response = self.client.post(f"/api/project/{self.NAME}/action", json={"action": action, "args": args})
        return response.status_code, response.get_json()

    def ok(self, action, **args):
        """Действие, которое должно пройти (код 200); возвращает JSON-ответ."""
        code, body = self.act(action, **args)
        self.assertEqual(code, 200, body)
        return body

    def refused(self, action, **args):
        """Действие, которое должно быть отклонено понятной ошибкой (код 400); возвращает текст ошибки."""
        code, body = self.act(action, **args)
        self.assertEqual(code, 400, body)
        self.assertTrue(body.get("error"))
        return body["error"]

    def assertText(self, key, text):
        """В ``text`` есть текст ``key`` из ru.hjson (подстановки «{…}» — любой текст, ``keyPattern``).

        Сначала проверяется, что такой ключ в ru.hjson вообще есть: иначе translate вернёт сам ключ,
        и проверка сверяла бы ответ с именем ключа.
        """
        self.assertNotEqual(translate(key), key, f"в ru.hjson нет текста {key}")
        self.assertRegex(text, keyPattern(key))

    def assertNoText(self, key, text):
        """Текста ``key`` из ru.hjson (ключ должен быть) в ``text`` нет."""
        self.assertNotEqual(translate(key), key, f"в ru.hjson нет текста {key}")
        self.assertNotRegex(text, keyPattern(key))

    def paragraph(self, key, text):
        """Абзац вопроса ``text`` с текстом ``key`` из ru.hjson (абзацы разделены пустой строкой);
        нет такого абзаца — пустая строка. Ключ должен быть в ru.hjson.
        """
        self.assertNotEqual(translate(key), key, f"в ru.hjson нет текста {key}")

        return next((part for part in text.split("\n\n") if keyPattern(key).search(part)), "")

    def raw(self, name):
        """Содержимое файла проекта байтами — чтобы проверить, что файл не переписан.

        `name` — путь внутри папки тестового проекта («settings.json») или полный путь
        (например, файл варианта из ``variantsDir``): ``os.path.join`` оставляет полный путь как есть.
        """
        with open(os.path.join(self.folder, name), "rb") as file:
            return file.read()

    def files(self):
        """settings.json и answer.json байтами — чтобы проверить, что отказ или «Отмена» их не переписали."""
        return self.raw("settings.json"), self.raw("answer.json")

    def load(self, name):
        """Читает JSON-файл `name` из папки тестового проекта."""
        with open(f"{self.folder}/{name}", encoding="utf-8") as file:
            return json.load(file)

    def save(self, name, data):
        """Записывает JSON-файл `name` в папку тестового проекта."""
        with open(f"{self.folder}/{name}", "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False)

    def state(self):
        """Состояние проекта так, как его получает страница."""
        return self.client.get(f"/api/project/{self.NAME}").get_json()

    def course(self, name):
        """Описание курса `name` из состояния проекта."""
        return next(item for item in self.state()["courses"] if item["name"] == name)

    def versions(self):
        """Имена сохранённых версий проекта (сначала новые)."""
        return [item["name"] for item in self.state()["versions"]]

    def versionList(self):
        """Сохранённые версии проекта из состояния: id -> описание (имя, комментарий, число уроков…)."""
        return {item["id"]: item for item in self.state()["versions"]}

    def stageVariant(self, stage="2"):
        """Вариант этапа `stage`, совпадающий с принятым расписанием (глубокая копия его курсов)."""
        answer = self.load("answer.json")
        return copy.deepcopy({name: answer[name] for name in stageCourses(self.load("settings.json"), stage) if name in answer})

    def variants(self, stage="2"):
        """Ответ GET /variants этапа `stage` — то, что получает «Предпросмотр»."""
        return self.client.get(f"/api/project/{self.NAME}/variants", query_string={"stage": stage}).get_json()

    def markJoint(self, section=2, line="ЕГЭ основной", source=1, sync=True):
        """Отметка «линейка `line` потока `section` присоединяется к Потоку `source`» прямо в файлах
        проекта (settings.json и answer.json), без кода программы — ``builders.markJoint``.

        Возвращает {копия: источник}. В проекте 2026/27 у «ЕГЭ основной» Потока 2 уроков нет,
        а у Потока 1 они стоят, поэтому при `sync` копии сразу получают уроки источников.
        """
        settings, answer = self.load("settings.json"), self.load("answer.json")
        copies = markJointData(settings, section, line, source, answer, sync)
        self.save("settings.json", settings)
        self.save("answer.json", answer)

        return copies

    def useProject(self, settings, answer):
        """Подменяет данные тестового проекта на `settings` и `answer` (например, ``builders.jointProject()``):
        settings.json и answer.json переписываются, построенные варианты (папка stages) удаляются.
        weights.json и версии остаются от проекта 2026/27.
        """
        self.save("settings.json", settings)
        self.save("answer.json", answer)
        shutil.rmtree(os.path.join(self.folder, "stages"), ignore_errors=True)

    def openProject(self, settings, answer):
        """Подменяет данные проекта на ``settings`` и ``answer`` (``useProject``) и открывает его на
        сервере заново (POST /open, код 200): сервер перечитывает файлы проекта.
        """
        self.useProject(settings, answer)
        self.assertEqual(self.client.post(f"/api/project/{self.NAME}/open").status_code, 200)
