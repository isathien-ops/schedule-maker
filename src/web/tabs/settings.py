"""Вкладка «Настройки»: сетка времени уроков, ограничение курсов на преподавателя, пары предметов
«в одно время можно / нежелательно / нельзя». Пара на странице — static/tabs/settings.js.

Предметная часть правки сетки (разбор времени, что переезжает и что теряется, перенос
закреплений и отметок) — в src/modules/functions/grid.py; здесь — проверка, вопрос, версия
«Перед: …» и сохранение.

Зависимости: actions (@action), core (UserError), project (файлы проекта, проверки аргументов,
версия «Перед: …», формулировки) и предметные модули (grid, joint, pairs, stages,
penalties, variants).
"""

from src.modules.translate import tr, translate
from src.modules.functions.grid import (
    DAYS, GridError, columnMapping, dayGrid, keepsColumns, lostPins, parseGrid, remapAnswer, remapSettings, renamedTimes,
    setDayGrid
)
from src.modules.functions.joint import jointCopies
from src.modules.functions.pairs import nextSubjectPairState, setSubjectPairState, subjectPairState
from src.modules.functions.penalties import renamePenaltyTimes
from src.modules.functions.stages import getStages, startedCourses
from src.modules.functions.variants import clearVariants
from src.web.actions import action
from src.web.core import UserError
from src.web.project import (
    bullets, loadAnswer, loadSettings, number, projectPath, requireSubjects, saveAnswer, saveBeforeVersion, saveSettings
)


# Действия вкладки «Настройки»: сетка времени, ограничения, пары предметов. Всё это — вход сборки:
# пока она идёт, менять нельзя (blocking=True)

def readGrid(days):
    """Сетка из формы в нормальной форме (grid.parseGrid); ошибка разбора — UserError с понятным текстом."""
    try:
        return parseGrid(days)

    except GridError as error:
        if error.kind == "invalid":
            raise UserError(f"{translate('menu.main.tab.settings.grid_invalid')}: {error.details['text']}")

        raise UserError(tr("web.error.grid_order", day=translate(f"day.{error.details['day']}"),
                           first=error.details["first"], second=error.details["second"]))


@action(blocking=True)
def setGrid(project, days, force=False):
    """Сохраняет сетку времени уроков (вкладка «Настройки»).

    days  — список дней (пн…вс), в каждом — тексты ячеек «16:20 - 17:50»; пустая ячейка
            означает «урока в этом месте нет». Время разбирается терпимо (grid.parseTime).
    force — человек уже подтвердил потерю уроков / закреплений.

    Ячейки правятся по месту: урок, закрепление и отметки доступности остаются в своём столбце
    («2-й урок вторника»), даже если время в нём поменяли. Очищенная ячейка забирает свои уроки:
     * если среди них есть уроки идущих курсов — отказ (их расписание менять нельзя);
     * иначе без force — вопрос «удалится N уроков и M закреплений» (общий урок курса-копии и его
       источника — один урок: копия теряет его вместе с источником);
     * с force — сначала версия «Перед: изменение сетки», затем изменение.
    Переписанное время подхватывают правила «Не ставить уроки в выбранное время». При любом сдвиге столбцов
    варианты всех этапов удаляются: они построены на старой сетке.
    Изменяет settings.json и answer.json.
    """
    settings = loadSettings(project)
    grid = readGrid(days)
    old_grid = dayGrid(settings)
    # {(день, старый урок): новый урок}; уроков очищенных ячеек в нём нет
    mapping = columnMapping(old_grid, grid)
    answer = loadAnswer(project)
    weeks, lost = remapAnswer(answer, mapping, grid)
    copies = jointCopies(settings)
    lost_lessons, lost_pins = sum(count for course, count in lost.items() if course not in copies), lostPins(settings, mapping)

    # Идущие курсы, которые потеряли бы уроки: такое изменение сетки запрещено совсем.
    # shared=False — в отказе завучу называются только курсы, которые начались сами (их ученики уже
    # ходят). Источник, который идёт только через свою копию, не называется: копия теряет те же
    # уроки (общий урок — один) и сама даёт отказ, а иначе один общий урок был бы назван дважды
    running = sorted(startedCourses(settings, answer, [course for course, count in lost.items() if count], complete=False, shared=False))

    if running:
        raise UserError(tr("web.error.grid_started", courses=bullets(running)))

    if lost_lessons or lost_pins:
        if not force:
            return {"confirm": tr("web.confirm_grid_remove", lessons=lost_lessons, pins=lost_pins), "danger": True,
                    "yes": translate("web.grid_remove_yes")}

        # Версия нужна и когда пропадают только закрепления: их тоже можно будет вернуть
        saveBeforeVersion(project, settings, answer, translate("web.version.grid"))

    renamePenaltyTimes(settings, renamedTimes(old_grid, grid))

    # Столбцы сдвинулись: закрепления, отметки доступности и расписание — на новые номера уроков,
    # а варианты, построенные на старой сетке, больше не годятся
    if not keepsColumns(old_grid, mapping):
        remapSettings(settings, mapping)
        saveAnswer(project, weeks)

        for stage in getStages(settings):
            clearVariants(projectPath(project), stage["key"])

    setDayGrid(settings, grid)
    saveSettings(project, settings)


@action(blocking=True)
def copyMonday(project, force=False):
    """Время уроков понедельника копируется во все рабочие дни (вт–пт), в которых есть уроки.

    Выходные сохраняют своё время (там уроки утром), пустые будни остаются пустыми.
    Работает через setGrid, поэтому уроки, закрепления и правила следуют за своим столбцом,
    у идущих курсов ничего не теряется, а при потере уроков так же задаётся вопрос.
    """
    grid = dayGrid(loadSettings(project))

    return setGrid(project, [list(grid[0]) if 0 < day < 5 and grid[day] else list(grid[day]) for day in range(DAYS)], force)


@action(blocking=True)
def setLimit(project, key, value):
    """Ограничение из «Настроек»: key — "max_courses_per_teacher" (сколько курсов может
    вести один преподаватель, не меньше 1). Других ограничений нет.
    """
    if key != "max_courses_per_teacher":
        raise UserError(translate("web.error.generic"))

    settings = loadSettings(project)
    settings[key] = number(value, 1)
    saveSettings(project, settings)


@action(blocking=True)
def cyclePair(project, first, second):
    """Клик по клетке таблицы пар предметов: следующее состояние «в одно время можно / нежелательно /
    нельзя» для предметов first и second.

    Оба предмета должны быть в проекте: устаревшая вкладка или ручной запрос с неизвестным
    предметом получают отказ, и пара в settings.json не попадает.
    """
    settings = loadSettings(project)
    requireSubjects(settings, [first, second])
    setSubjectPairState(settings, first, second, nextSubjectPairState(subjectPairState(settings, first, second)))
    saveSettings(project, settings)
