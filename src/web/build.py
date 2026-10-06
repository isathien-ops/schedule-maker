"""Фоновая сборка вариантов: служба, которой пользуется вкладка «Запуск».

Здесь путь к решателю solve.exe и параметры сборки по умолчанию, задания JOBS в памяти,
привязка решателя к процессу программы, нить сборки runJob, запуск и остановка задания
(startJob, stopJob), ход сборки для страницы (jobState) и забывание задания удалённого
проекта (forget). Маршрутов (@app.route) и действий (@action) здесь нет.

Как идёт одна сборка (runJob)
-----------------------------
1. Под LOCK читаются настройки, расписание и веса проекта; открывается журнал сборки
   (_openJournal).
2. Во временную папку (_tempFolder) один раз пишутся вход решателя и веса (_prepareInput), поэтому
   все варианты одной сборки строятся по одним и тем же данным, даже если человек их тем временем
   меняет. Заранее выбираются идущие курсы и курсы-копии («линейка идёт вместе с Потоком N»),
   чьи уроки переходят в каждый вариант (_fixedCourses), и до первого варианта пишется, сколько
   уроков закрепится и что переходит как есть (_explainPins).
3. Каждый вариант — отдельный запуск solve.exe (_runSolver); его вывод построчно идёт в ход
   сборки и в журнал. Удачный результат сохраняется в папку вариантов этапа (_storeVariant),
   если он не совпал с вариантом, уже сохранённым этой сборкой.
4. Временная папка удаляется (_removeFolder: сразу после снятия решателя Windows ещё держит его
   файлы, поэтому удаление повторяется, а неудача только записывается в журнал программы).
5. Итоговая строка (_summaryLine); что бы ни случилось, задание помечается законченным,
   а журнал закрывается (_finishJob).

Имена с «_» — внутренние шаги этого модуля (правило — в шапке src/web/server.py). Остальные
модули пользуются только открытыми: startJob, stopJob, running, jobState, forget, closeWithProgram
и константами (SOLVER, JOBS, параметры сборки).

Ход сборки (job["log"]) — строки {"text", "level"}: уровень строки определяет сервер, страница
только выбирает по нему оформление (LOG_LEVELS).

Зависимости: core (app, log, LOCK), project (папка и файлы проекта) и предметные модули.
Остальные модули берут его только как модуль (`from src.web import build`) и обращаются
build.SOLVER, build.JOBS…: SOLVER подменяют тесты, а JOBS изменяемый.
"""

import contextlib
import ctypes
import os
import shutil
import subprocess
import tempfile
import threading
import time
from ctypes import wintypes

from src.modules.translate import tr, translate
from src.modules.functions.files import readJson, writeJson
from src.modules.functions.journal import openBuildLog, short
from src.modules.functions.solver_input import buildStageSettings, droppedLessons, keepCourses, pinForecast
from src.modules.functions.stages import movedStarted, stageCopies, stageCourses, stageExists, stageLabel, staleStarted, startedCourses
from src.modules.functions.variants import buildStarted, clearVariants, loadVariants, saveBuildStarted, saveVariant
from src.web.core import LOCK, app, log
from src.web.project import loadAnswer, loadSettings, loadWeights, projectPath


# Путь к решателю относительный: сервер должен быть запущен из корня проекта (так делает web.py)
SOLVER = os.path.join("src", "modules", "solve.exe")

# Деления ползунка «Тщательность» на вкладке «Запуск» — шагов решателя на один вариант (примерно
# 4 с, 12 с, 36 с и 2 мин на вариант). Страница получает их в состоянии проекта (iterationLevels)
ITERATION_LEVELS = (3000000, 10000000, 30000000, 100000000)
# Шагов на вариант по умолчанию — второе деление: 10 миллионов (около 12 с на вариант)
DEFAULT_ITERATIONS = ITERATION_LEVELS[1]
# Границы числа шагов, которые можно задать (setNumber): снизу — чтобы вариант вообще успел
# сложиться, сверху — максимум 32-битного int решателя
MIN_ITERATIONS = 100000
MAX_ITERATIONS = 2147483647
DEFAULT_VARIANTS = 5  # сколько вариантов строить за одну сборку по умолчанию
MAX_VARIANTS = 50  # верхняя граница поля «Сколько вариантов»

# Удаление временной папки сборки: сколько раз пробовать и пауза между попытками в секундах.
# Сразу после того, как «Остановить» снимает решатель, Windows ещё мгновение держит его файлы
CLEANUP_ATTEMPTS = 10
CLEANUP_PAUSE = 0.2

# Сборки, идущие в фоне: имя проекта -> job (словарь, см. startJob()). Поля job:
#   stage    — ключ этапа; keep — режим «оставить принятое»;
#   number   — номер запуска решателя (варианта), который идёт сейчас; total — сколько всего строить;
#   saved    — сколько вариантов уже сохранено (под номерами 1..saved подряд);
#   repeats  — сколько вариантов совпали с уже сохранёнными в этой сборке и не сохранены;
#   stopped  — человек нажал «Остановить»; running — нить ещё работает;
#   started / finished — время начала и конца (time.time());
#   log      — ход сборки: строки {"text", "level"} (служебные строки и вывод решателя, см. LOG_LEVELS);
#   process  — текущий процесс solve.exe (чтобы его можно было прервать);
#   journal  — файл журнала этой сборки (journal.openBuildLog; None, если файл создать не удалось);
#              его заводит runJob, в конце сборки файл закрывается и поле обнуляется.
# Хранится только в памяти: после перезапуска сервера сведения о сборках пропадают.
JOBS = {}

# Объект задания Windows (Job Object), к которому привязываются процессы solve.exe; см. closeWithProgram
_SOLVER_JOB = None

# Сколько последних строк вывода решателя хранить в памяти (долгие сборки не должны съедать
# память) и сколько из них отдавать странице
LOG_KEEP = 2000
LOG_SHOWN = 400

# Уровни строк хода сборки (поле "level"): по ним страница выбирает оформление строки
#   head     — служебная строка «=== … ===»: начало варианта, чем закончился запуск решателя,
#              совпавший вариант, «Сохранён как вариант K», итог;
#   done     — итог удачной сборки («Готово вариантов: N»);
#   warn     — предупреждение решателя («[Внимание] …», «[WARNING] …»);
#   progress — строка хода отжига «Шаг N из M | …»;
#   text     — остальной вывод решателя и пояснения сервера до первого варианта (_explainPins)
LOG_LEVELS = ("head", "done", "warn", "progress", "text")

# Начала строк вывода решателя (src/modules/solve.cpp) и их уровни
SOLVER_LINE_LEVELS = (("[Внимание]", "warn"), ("[WARNING]", "warn"), ("Шаг ", "progress"))


# Структуры Windows для Job Object (поля — как JOBOBJECT_BASIC_LIMIT_INFORMATION и
# JOBOBJECT_EXTENDED_LIMIT_INFORMATION в документации WinAPI); нужны closeWithProgram
class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", ctypes.c_uint64 * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


# Флаг «завершить все процессы, когда объект задания закрывается» и номер класса сведений
# JobObjectExtendedLimitInformation для SetInformationJobObject
_KILL_ON_JOB_CLOSE = 0x2000
_EXTENDED_LIMIT_INFORMATION = 9


def closeWithProgram(process):
    """Привязывает процесс решателя к программе: закроется программа — завершится и он.

    Windows сама не завершает дочерние процессы. Без привязки solve.exe, запущенный сборкой,
    дорабатывал свой вариант (до минуты) после закрытия окна программы, держал занятым файл
    solve.exe в папке программы — и пересборка программы (build.bat) в это время падала.
    Процесс добавляется в общий Job Object с флагом «завершить всё при закрытии»: объект
    закрывается вместе с программой (как бы она ни завершилась), и Windows снимает решатель.
    Не на Windows или при ошибке — ничего не делает (сборке это не мешает).
    """
    global _SOLVER_JOB

    if os.name != "nt":
        return

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

        if _SOLVER_JOB is None:
            job = kernel32.CreateJobObjectW(None, None)
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE

            if not job or not kernel32.SetInformationJobObject(job, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)):
                return

            _SOLVER_JOB = job

        kernel32.AssignProcessToJobObject(_SOLVER_JOB, int(process._handle))
    except Exception:
        log.exception("Не удалось привязать решатель к программе")


def running(project):
    """Идёт ли сейчас фоновая сборка вариантов для этого проекта."""
    job = JOBS.get(project)

    return job is not None and job["running"]


def jobState(project):
    """Ход сборки для страницы (None — сборок в этом проекте ещё не было с запуска сервера).

    seconds — сколько идёт (или шла) сборка; repeats — сколько вариантов совпали с уже
    сохранёнными и не сохранены; log — последние LOG_SHOWN строк хода сборки ({"text", "level"},
    см. LOG_LEVELS); unacceptable — готовые варианты есть, но ни один принять нельзя (_summaryLine).
    """
    job = JOBS.get(project)

    if job is None:
        return None

    return {
        "running": job["running"], "stage": job["stage"], "number": job["number"], "total": job["total"],
        "saved": job["saved"], "repeats": job["repeats"], "stopped": job["stopped"], "seconds": int((job["finished"] or time.time()) - job["started"]),
        "unacceptable": job.get("unacceptable", False), "log": job["log"][-LOG_SHOWN:],
    }


def runJob(project, job):
    """Строит job["total"] вариантов одного этапа; выполняется в фоновой нити (см. startJob).

    Шаги — в шапке модуля. Любая ошибка (решатель не запустился, проект сломан) завершает
    сборку строкой «не получилось» в ходе сборки и записью в журнал программы; задание
    в любом случае помечается законченным (finally). Неудачное удаление временной папки
    ошибкой сборки не считается (_removeFolder).
    """
    try:
        with LOCK:
            settings = loadSettings(project)
            answer = loadAnswer(project)
            weights = loadWeights(project)

        _openJournal(project, job, settings, weights)
        log.info("%s | сборка начата: этап %s, оставить принятые: %s", project, job["stage"], job.get("keep"))

        with _tempFolder() as folder:
            keep = keepCourses(settings, answer, job["stage"]) if job.get("keep") else ()
            paths = _prepareInput(folder, settings, answer, weights, job["stage"], keep)
            fixed = _fixedCourses(settings, answer, job["stage"])
            _explainPins(job, settings, answer, keep)
            # Варианты, уже сохранённые этой сборкой (вариант N — stored[N - 1]): с ними сравнивается новый
            stored = []

            for number in range(1, job["total"] + 1):
                if job["stopped"]:
                    break

                job["number"] = number
                _addLine(job, f"=== {stageLabel(job['stage'], translate)}: {translate('menu.main.tab.run.variant')} {number} / {job['total']} ===", "head")
                code = _runSolver(job, paths, settings.get("iterations", DEFAULT_ITERATIONS))

                if code == 0 and not job["stopped"] and os.path.exists(paths["output"]):
                    _storeVariant(project, job, number, readJson(paths["output"], {}), fixed, stored)

        summary = _summaryLine(project, job)
        # Готовые варианты, из которых принять нельзя ни один, — не успех: строка-предупреждение
        _addLine(job, "=== " + summary + " ===", "warn" if job.get("unacceptable") else "done" if job["saved"] else "head")
        log.info("%s | сборка закончена: этап %s, готово вариантов: %s, совпавших: %s%s", project, job["stage"], job["saved"], job["repeats"],
                 ", остановлена" if job["stopped"] else "")

    except Exception:
        app.logger.exception("build of %s", project)
        _addLine(job, "=== " + tr("web.run.solver_failed", code="?") + " ===", "head")

    finally:
        _finishJob(job)


@contextlib.contextmanager
def _tempFolder():
    """Временная папка для входа и выхода решателя на время одной сборки; после неё удаляется.

    Вместо tempfile.TemporaryDirectory: та при выходе удаляет папку один раз, а сразу после
    «Остановить» Windows ещё держит файлы снятого решателя (input.json) — удаление падало
    с PermissionError, и остановленная сборка заканчивалась строкой «не получилось».
    """
    folder = tempfile.mkdtemp(prefix="schedule-build-")

    try:
        yield folder

    finally:
        _removeFolder(folder)


def _removeFolder(folder):
    """Удаляет временную папку сборки, повторяя попытку, пока Windows не отпустит файлы.

    Не вышло за CLEANUP_ATTEMPTS попыток — папка остаётся среди временных файлов системы,
    а в журнал программы пишется предупреждение; сборке это не мешает. Папки уже нет — удалять нечего.
    """
    for attempt in range(CLEANUP_ATTEMPTS):
        if attempt:
            time.sleep(CLEANUP_PAUSE)

        try:
            shutil.rmtree(folder)
            return

        except FileNotFoundError:
            return

        except OSError:
            continue

    log.warning("Не удалось удалить временную папку сборки %s", folder)


def _addLine(job, line, level="text"):
    """Строка в ход сборки (job["log"], его видит страница) и в журнал сборки, если он открыт.

    ``level`` — уровень строки для страницы (один из LOG_LEVELS).
    """
    job["log"].append({"text": line, "level": level})
    _journal(job, line)


def _solverLineLevel(line):
    """Уровень строки вывода решателя: предупреждение, ход отжига или обычный текст (LOG_LEVELS)."""
    return next((level for start, level in SOLVER_LINE_LEVELS if line.startswith(start)), "text")


def _journal(job, line):
    """Строка только в журнал сборки (файл); журнала нет — ничего не делает."""
    if job.get("journal"):
        job["journal"].write(line + "\n")


def _openJournal(project, job, settings, weights):
    """Открывает журнал этой сборки (job["journal"]) и пишет в него, с какими настройками составляли."""
    job["journal"] = openBuildLog(project, job["stage"])
    _journal(job, f"Проект: {project}; этап: {job['stage']}; оставить принятые уроки: {'да' if job.get('keep') else 'нет'}")
    _journal(job, f"Тщательность (шагов на вариант): {settings.get('iterations', DEFAULT_ITERATIONS)}; вариантов: {job['total']}")
    _journal(job, f"Веса: {short(weights, 2000)}")
    _journal(job, f"Свои правила: {short(settings.get('custom_penalties', []), 4000)}")


def _prepareInput(folder, settings, answer, weights, stage, keep):
    """Пишет во временную папку `folder` вход решателя этапа `stage` и веса; возвращает пути
    {"input", "output", "weights"} для запуска solve.exe.

    Остальные этапы в расписании неподвижны, поэтому вход одинаков для всех вариантов сборки.
    В режиме «оставить принятое» `keep` — курсы этапа, которые уже стоят в расписании
    (solver_input.keepCourses): решатель получает их уроки и только дополняет недостающие.
    Курсов-копий во входе нет; их соседи получают запреты и цены слотов, для цен нужны веса.
    """
    paths = {name: os.path.join(folder, f"{name}.json") for name in ("input", "output", "weights")}

    # Веса нужны и самому входу: мягкие правила с курсами-копиями решатель получает ценами слотов
    writeJson(paths["input"], buildStageSettings(settings, answer, stage, keep, weights))
    writeJson(paths["weights"], weights)

    return paths


def _explainPins(job, settings, answer, keep):
    """Строки до первого варианта: сколько уроков останется на месте, сколько подберёт программа
    и сколько не ставится, потому что курс некому вести (solver_input.pinForecast — тот же текст,
    что у галочки на «Запуске», run.js); если есть идущие курсы без преподавателя, — сколько их
    уроков переходит в варианты как есть. Сразу за ними решатель печатает, сколько закреплений
    у него на деле встало.
    """
    forecast = pinForecast(settings, answer, job["stage"], keep)
    _addLine(job, tr("web.run.pin_forecast_no_teacher" if forecast["noTeacher"] else "web.run.pin_forecast", **forecast))
    dropped = droppedLessons(settings, answer, job["stage"])

    if dropped:
        _addLine(job, tr("web.run.carried_no_teacher", count=dropped))


def _fixedCourses(settings, answer, stage):
    """Что из принятого расписания переходит в каждый вариант этапа: (courses, started, carried).

    courses — все курсы этапа (только их уроки берутся из ответа решателя);
    started — зафиксированные курсы (идут, все уроки на месте) и курсы-копии с уроками
              (stages.stageCopies: их уроки задаёт поток-источник, решатель их не получает):
              в каждом варианте они ровно как в расписании на начало сборки, что бы ни вернул
              решатель; копия, которая ждёт поток-источник, в вариант не попадает;
    carried — идущие курсы с уроками в расписании: если решатель их не вернул (например,
              у курса нет преподавателя), их уроки тоже сохраняются.
    """
    courses = set(stageCourses(settings, stage))
    fixed = startedCourses(settings, answer, courses) | set(stageCopies(settings, stage))
    started = {name: answer[name] for name in fixed if name in answer}
    carried = {name: answer[name] for name in startedCourses(settings, answer, courses, complete=False) if name in answer}

    return courses, started, carried


def _runSolver(job, paths, iterations):
    """Один запуск solve.exe; его вывод построчно идёт в ход сборки и журнал. Возвращает код выхода.

    Процесс запоминается в job["process"], чтобы «Остановить» могло его прервать, и
    привязывается к программе (closeWithProgram).
    """
    # Старый output.json от предыдущего варианта удаляем, чтобы не принять его за новый результат
    if os.path.exists(paths["output"]):
        os.remove(paths["output"])

    # Запуск решателя без окна консоли; stderr сливается в stdout, чтобы всё попало в журнал
    process = subprocess.Popen(
        [SOLVER, "--weights", paths["weights"], "--input", paths["input"], "--output", paths["output"], "--iterations", str(iterations)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    job["process"] = process
    closeWithProgram(process)

    # «Остановить» нажали, пока решатель запускался: stopJob() его ещё не видел — прерываем здесь
    if job["stopped"]:
        process.kill()

    with process.stdout:
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            _addLine(job, line, _solverLineLevel(line))
            del job["log"][:-LOG_KEEP]

    code = process.wait()
    _addLine(job, "=== " + _exitLine(job, code) + " ===", "head")

    return code


def _exitLine(job, code):
    """Чем закончился один запуск решателя: остановлен человеком, готово или ошибка с кодом."""
    if job["stopped"]:
        return translate("web.run.solver_stopped")

    if code == 0:
        return translate("web.run.solver_done")

    return tr("web.run.solver_failed", code=code)


def _storeVariant(project, job, number, stage_answer, fixed, stored):
    """Сохраняет ответ запуска номер `number` как следующий вариант этапа (под LOCK).

    Вариант — уроки курсов этапа из ответа решателя, поверх них — зафиксированные курсы и курсы-копии
    как в расписании, плюс идущие курсы, которых в ответе нет (см. _fixedCourses). Если этап тем
    временем удалили, ничего не сохраняется. Старые варианты удаляются только когда готов
    первый новый: сборка, остановленная раньше, оставляет прежние. Вместе с первым вариантом
    записывается, какие курсы этапа уже шли (variants.saveBuildStarted — идущие курсы из carried).

    `stored` — варианты, уже сохранённые этой сборкой. Совпавший с одним из них (то же
    расписание) не сохраняется: в ход сборки идёт строка «совпал», job["repeats"] растёт. Так
    номера сохранённых вариантов идут подряд и на «Предпросмотре» нет одинаковых столбцов.
    После первого совпадения номер запуска (`number`, заголовок «Вариант N / M») и номер на
    «Предпросмотре» расходятся — тогда в ход сборки идёт строка «Сохранён как вариант K».
    """
    courses, started, carried = fixed

    with LOCK:
        if not stageExists(loadSettings(project), job["stage"]):
            return

        variant = {**{name: value for name, value in stage_answer.items() if name in courses}, **started}
        variant.update({name: week for name, week in carried.items() if name not in stage_answer})

        if variant in stored:
            job["repeats"] += 1
            _addLine(job, "=== " + tr("web.run.variant_repeated", number=number, same=stored.index(variant) + 1) + " ===", "head")
            return

        path = projectPath(project)

        if not job["saved"]:
            clearVariants(path, job["stage"])
            # Какие курсы уже шли: для них вариант не «собран до начала» (stages.staleStarted),
            # а сдвиг их уроков ищет stages.movedStarted; их уроки запоминаются, чтобы узнать,
            # если расписание с тех пор поменялось (variants.buildStarted)
            saveBuildStarted(path, job["stage"], carried, carried)

        stored.append(variant)
        saveVariant(path, job["stage"], len(stored), variant)
        job["saved"] += 1

        if len(stored) != number:
            _addLine(job, "=== " + tr("web.run.variant_saved_as", number=len(stored)) + " ===", "head")


def _summaryLine(project, job):
    """Итог сборки: сколько вариантов готово (и сколько совпавших не сохранено; все совпали —
    отдельный текст, сравнивать нечего) / остановлена без новых вариантов / не получилось.

    Остановленная сборка без новых вариантов прежние варианты этапа не трогает (их стирает только
    первый новый вариант). Есть ли они, смотрится в конце сборки: «прежние варианты остались» —
    только если они правда есть, иначе «вариантов нет» (например, первую сборку остановили сразу).
    Если ни один готовый вариант принять нельзя (_noneAcceptable: каждый меняет время или преподавателя
    идущих курсов — variants.unacceptable), итог не зовёт выбирать вариант, а говорит, что принять нельзя ни один,
    и job["unacceptable"] становится True (сообщение страницы о конце сборки, run.js; уровень строки — "warn").
    """
    if job["saved"] and _noneAcceptable(project, job["stage"]):
        job["unacceptable"] = True
        return tr("menu.main.tab.run.variants_unacceptable", count=job["saved"])

    if job["saved"] == 1 and job["repeats"]:
        return translate("menu.main.tab.run.variants_all_same")

    if job["saved"] and job["repeats"]:
        return tr("menu.main.tab.run.variants_ready_repeated", count=job["saved"], repeats=job["repeats"])

    if job["saved"]:
        return tr("menu.main.tab.run.variants_ready", count=job["saved"])

    if job["stopped"]:
        with LOCK:
            kept = loadVariants(projectPath(project), job["stage"])

        return translate("web.run.stopped_kept" if kept else "web.run.stopped_none")

    return translate("menu.main.tab.run.no_variants")


def _noneAcceptable(project, stage):
    """Варианты этапа есть, но ни один принять нельзя (как variants.unacceptable у «Предпросмотра»:
    stages.staleStarted или stages.movedStarted, тот же отказ, что у preview.accept).
    """
    with LOCK:
        settings, answer = loadSettings(project), loadAnswer(project)
        path = projectPath(project)
        built = buildStarted(path, stage, answer)
        stored = loadVariants(path, stage)

    return bool(stored) and all(
        staleStarted(settings, answer, stage, variant, built) or movedStarted(settings, answer, stage, variant, built) for _, variant in stored
    )


def _finishJob(job):
    """Помечает задание законченным и закрывает журнал сборки."""
    job["running"] = False
    job["finished"] = time.time()

    if job.get("journal"):
        job["journal"].close()
        job["journal"] = None


def startJob(project, stage, keep, total):
    """Заводит задание сборки вариантов этапа `stage` и запускает runJob в фоновой нити.

    keep — режим «оставить принятое»; total — сколько вариантов строить. Проверки (не идёт ли
    уже сборка, есть ли решатель, известен ли этап) делает вызывающий — действие run
    вкладки «Запуск» (src/web/tabs/run.py).
    """
    job = {
        "stage": stage, "keep": bool(keep), "number": 0, "total": total, "saved": 0, "repeats": 0, "unacceptable": False,
        "stopped": False, "running": True, "started": time.time(), "finished": None, "log": [], "process": None,
    }
    JOBS[project] = job

    threading.Thread(target=runJob, args=(project, job), daemon=True).start()


def stopJob(project):
    """Кнопка «Остановить» на шаге «Запуск»: помечает job как остановленную и убивает текущий процесс solve.exe.

    Уже сохранённые варианты остаются; нить сама завершится, увидев флаг stopped.
    """
    job = JOBS.get(project)

    if job and job["running"]:
        job["stopped"] = True

        if job["process"] is not None and job["process"].poll() is None:
            job["process"].kill()


def forget(project):
    """Забывает задание сборки проекта (после удаления проекта: его ход сборки больше не нужен)."""
    JOBS.pop(project, None)
