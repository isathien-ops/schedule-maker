"""Открытый проект глазами обработчиков: где лежит его папка, чтение и запись его файлов,
версия «Перед: …», проверка аргументов, пришедших со страницы, и общие формулировки
сообщений (списки «• пункт», «N уроков»).

Зависимости: core (UserError) и предметные модули (files, grid, model, stages, courses, joint, variants, versions).
Импортируют его build, state, ranking, projects и модули вкладок.

Разделы модуля
--------------
1. Папка и файлы проекта: projectPath, load/save Settings, Weights, Answer. saveSettings и saveAnswer —
   единственная точка записи настроек и расписания, поэтому здесь курсы-копии «линейки, которая идёт
   вместе с Потоком N» догоняют свои источники (joint.syncJointSettings, joint.syncJointAnswer).
2. Изменения расписания: saveBeforeVersion, rewriteVariants.
3. Проверка аргументов: requireCourse, requireOwnCourse (курс, но не копия: отказ web.error.joint_locked),
   requireStage, requireSection, requireLine (раздел и линейка в нём есть: отказ web.error.no_line),
   requireSubjects, requireTeacher, requireVersion, requireVariant, number.
4. Формулировки: bullets, lessonsText, slotText (день и час урока), conflictLines (помехи уроку
   в готовом расписании: «Вторник, 16:20 - 17:50: …»), movedStartedItems (уроки идущих курсов,
   которые вариант сдвинул или сборка не сможет оставить как в расписании: «Предпросмотр», отказ
   в принятии, предупреждение «Запуска»), conflictStages (этапы, где стоят мешающие уроки, — чьи
   варианты составить заново), cannotParagraphs (общие уроки во время «не может», joint.copyCannot:
   абзац на преподавателя потока-копии).

Файлы проекта
-------------
* `settings.json` — всё, что ввёл человек: сетка времени уроков по дням, потоки и блоки,
  линейки, курсы (`classes.custom_groups`; у курса-копии — `together_with`) и уроки в неделю (`classes.lessons`),
  преподаватели с предметами и отметками доступности, закреплённые уроки (`constants`),
  правила-штрафы (`custom_penalties`), ограничение курсов на преподавателя и параметры
  сборки; поле `format` — номер формата проекта. Проект, архив или версия другого формата
  не открываются (tree.isCurrentFormat).
* `answer.json` — «принятое расписание»: {курс: неделя}; неделя — список дней, день —
  список ячеек-уроков {"subject", "teachers"}. Пустая ячейка имеет subject "#".
* `weights.json` — веса встроенных штрафов решателя (вкладка «Запуск»).
* папка вариантов каждого этапа (variants.variantsDir) — построенные варианты
  (файлы 1.json, 2.json, …), `accepted.json` с номером последнего принятого,
  `rejected.json` с номерами отклонённых и `started.json` с курсами, которые уже шли
  при сборке (функции меток — в variants.py);
* версии (versions.py) — снимки проекта: «Сохранить версию» и автоматические «Перед: …»,
  которые сервер делает перед каждым заметным изменением расписания, чтобы его можно было
  откатить.
"""

import os

from src.variables import FORBIDDEN_NAME_CHARS, PROJECTS_DIR
from src.modules.translate import tr, translate
from src.modules.functions.courses import BLOCKS, copyRoot, sectionLines, streamIds
from src.modules.functions.files import readAnswer, readJson, writeJson
from src.modules.functions.grid import dayGrid
from src.modules.functions.joint import jointCopies, jointSource, syncJointAnswer, syncJointSettings
from src.modules.functions.model import courseGroups, groupsByName, sectionOf, stageKey
from src.modules.functions.stages import acceptedStages, getStages, stageExists, stageLabel
from src.modules.functions.variants import loadVariants, saveVariant
from src.modules.functions.versions import listVersions, saveVersion
from src.web.core import UserError


# ---------------------------------------------------------------- 1. папка и файлы проекта

def projectPath(project):
    """Папка проекта по его имени; заодно проверка, что имя безопасно и проект существует.

    Имя приходит из адреса запроса, поэтому запрещены разделители пути, двоеточие (имя «C:»
    в Windows — это папка диска, через «..» или «C:» можно было бы выйти за пределы папки
    projects) и начальная точка. Итоговый путь дополнительно сверяется: он должен лежать прямо
    внутри папки projects. Несуществующий проект (например, удалён в другой вкладке) —
    UserError «нет такого проекта».
    """
    root = os.path.realpath(PROJECTS_DIR)
    path = os.path.join(PROJECTS_DIR, project)

    if (not project or any(char in project for char in FORBIDDEN_NAME_CHARS) or project.startswith(".")
            or os.path.dirname(os.path.realpath(path)) != root or not os.path.isdir(path)):
        raise UserError(translate("web.error.no_project"), code="no_project")

    return path


def loadSettings(project):
    """Читает settings.json проекта и возвращает его как словарь.

    Повреждённый файл — ошибка для человека (web.error.settings_broken_open), а не пустые
    настройки (см. комментарий ниже).
    """
    settings = readJson(os.path.join(projectPath(project), "settings.json"), None)

    # Повреждённый файл никогда не подменяется пустым словарём: иначе следующее же сохранение
    # записало бы пустой проект поверх данных, которые ещё можно восстановить руками.
    # Здесь копия файла не делается, поэтому и текст свой: «закройте и откройте снова».
    # При повторном открытии tree.prepareProject отложит копию и покажет web.error.broken_settings
    # («проект не открылся, копия сохранена рядом») — тогда этот текст будет верен
    if not isinstance(settings, dict):
        raise UserError(translate("web.error.settings_broken_open"))

    return settings


def saveSettings(project, settings):
    """Записывает settings.json проекта целиком.

    Перед записью отметки «идёт вместе с Потоком N» приводятся к правилам (joint.syncJointSettings):
    у копий часы источника (их могли поменять у источника или «Скопировать линейку»), нет закреплений
    и «ведёт», а отметка без источника (его удалили) убирается. Так ни одно действие не держит это
    правило само. ``settings`` меняются на месте, чтобы вызывающий дальше работал с тем, что записано.
    """
    writeJson(os.path.join(projectPath(project), "settings.json"), syncJointSettings(settings))


def loadWeights(project):
    """Веса встроенных штрафов решателя (weights.json); нет файла — пустой словарь."""
    return readJson(os.path.join(projectPath(project), "weights.json"), {})


def saveWeights(project, weights):
    """Записывает weights.json проекта целиком."""
    writeJson(os.path.join(projectPath(project), "weights.json"), weights)


def loadAnswer(project):
    """Принятое расписание проекта (answer.json).

    Нет файла — пустой словарь; файл испорчен — ValueError("web.error.broken_answer"), которую
    сервер показывает человеку как понятную ошибку (см. files.readAnswer).
    """
    return readAnswer(os.path.join(projectPath(project), "answer.json"))


def loadAnswerOrEmpty(project):
    """Принятое расписание, а если файл испорчен — пустое (терпимое чтение).

    Только для мест, которые расписание не меняют и где отказ хуже пустого списка: сохранение
    версии вручную и перед восстановлением версии (восстановление — как раз способ выбраться
    из испорченного состояния) и выгрузка списка преподавателей (расписание ей не обязательно).
    Всё, что расписание меняет, читает его через loadAnswer: иначе испорченный файл тихо стал бы
    пустым и следующее сохранение стёрло бы его насовсем.
    """
    answer = readJson(os.path.join(projectPath(project), "answer.json"), {})

    return answer if isinstance(answer, dict) else {}


def saveAnswer(project, answer, settings=None):
    """Записывает «принятое расписание» (answer.json) целиком.

    Перед записью курсы-копии получают уроки своих источников, а копия источника без уроков —
    без ключа («ждёт Поток N»; joint.syncJointAnswer). Поэтому копии сами поспевают за принятием
    варианта, закреплениями и преподавателем источника, «Убрать из расписания» и удалением
    преподавателя. ``settings`` — настройки, по которым искать копии; None — с диска: действие,
    которое меняет и настройки, записывает их первым. ``answer`` меняется на месте.
    """
    syncJointAnswer(settings if settings is not None else loadSettings(project), answer)
    writeJson(os.path.join(projectPath(project), "answer.json"), answer)


# ---------------------------------------------------------------- 2. изменения расписания

def saveBeforeVersion(project, settings, answer, action):
    """Сохраняет автоматическую версию «Перед: <action>» — снимок проекта до изменения.

    Вызывается прямо перед тем, как действие меняет расписание (или то, что потом нельзя
    вернуть руками), чтобы изменение можно было откатить на вкладке «Версии».
    `action` — уже готовый текст («удаление потока «Поток 2»»), `answer` — текущее расписание:
    по нему версия запоминает, какие этапы были приняты.
    """
    saveVersion(projectPath(project), tr("web.version.before", action=action), "", acceptedStages(settings, answer))


def rewriteVariants(project, settings, change, stages=None):
    """Применяет `change` ко всем построенным вариантам и сохраняет те, что изменились.

    change(variant) меняет вариант ({курс: неделя}) на месте и возвращает True, если что-то
    поменяла. stages — ключи этапов, варианты которых смотреть; None — всех этапов проекта.
    Нужна, чтобы принятие старого варианта не вернуло то, что человек уже убрал: удалённый
    курс, снятого или заменённого преподавателя.
    """
    path = projectPath(project)

    for stage in stages if stages is not None else [item["key"] for item in getStages(settings)]:
        for number, variant in loadVariants(path, stage):
            if change(variant):
                saveVariant(path, stage, number, variant)


# ---------------------------------------------------------------- 3. проверка аргументов со страницы

def requireCourse(settings, course, subject=None):
    """Группа курса (элемент `classes.custom_groups`) по имени курса.

    Если курс тем временем удалили (например, в другой вкладке) или предмет `subject`
    не принадлежит этому курсу — понятная ошибка UserError вместо падения дальше по коду.
    """
    group = next((item for item in courseGroups(settings) if item["name"] == course), None)

    if group is None or (subject is not None and subject not in group.get("subjects", [])):
        raise UserError(translate("web.error.no_course"))

    return group


def requireOwnCourse(settings, course, subject=None):
    """То же, что ``requireCourse``, но курс-копия — отказ web.error.joint_locked (меняется только у Потока N).

    Время, преподавателя и число уроков копии задаёт её курс-источник, а копия получает их при
    записи проекта: менять их у самой копии — и на «Курсах», и на «Преподавателях» — нельзя.
    """
    group = requireCourse(settings, course, subject)

    if jointSource(settings, group) is not None:
        raise UserError(tr("web.error.joint_locked", number=group["together_with"]))

    return group


def requireStage(settings, stage):
    """Проверяет, что этап с ключом `stage` существует в проекте; иначе — общая ошибка."""
    if not stageExists(settings, stage):
        raise UserError(translate("web.error.generic"))


def requireSection(settings, section):
    """Проверяет, что раздел `section` есть: номер существующего потока или известный блок
    (доп. курсы, май, лето, либо блок, в котором уже есть курсы). Иначе — UserError.

    Без проверки устаревший или ручной запрос с несуществующим разделом молча создавал
    новый «блок» с курсами и непонятным этапом.
    """
    known = set(streamIds(settings)) | set(BLOCKS) | {sectionOf(group) for group in courseGroups(settings)}

    if section not in known:
        raise UserError(translate("web.error.generic"))


def requireLine(settings, section, line):
    """Проверяет раздел `section` (requireSection) и что в нём есть линейка `line`. Иначе — UserError.

    Линейка существует только своими курсами. Без проверки устаревший запрос (линейку тем
    временем удалили в другой вкладке) отвечал бы «готово», ничего не сделав, а «Добавить
    предмет» создал бы курс в линейке, которой на странице уже нет.
    """
    requireSection(settings, section)

    if line not in sectionLines(settings, section):
        raise UserError(translate("web.error.no_line"))


def requireSubjects(settings, subjects):
    """Проверяет список предметов из формы: выбран хотя бы один, и каждый есть в списке проекта."""
    if not subjects:
        raise UserError(translate("web.error.teacher_no_subjects"))

    known = {name for name, _ in settings.get("subjects", [])}

    if any(subject not in known for subject in subjects):
        raise UserError(translate("web.error.generic"))


def requireTeacher(settings, name):
    """Проверяет, что преподаватель ``name`` есть в проекте; удалён (например, в другой вкладке) —
    понятная ошибка UserError.
    """
    if name not in settings.get("teachers", {}):
        raise UserError(translate("web.error.no_teacher"))


def requireVersion(project, version):
    """Описание (meta.json) сохранённой версии проекта; нет такой версии — UserError."""
    meta = dict(listVersions(projectPath(project))).get(version)

    if meta is None:
        raise UserError(translate("web.error.no_version"))

    return meta


def requireVariant(project, stage, number):
    """(номер, вариант) построенного варианта этапа по номеру со страницы.

    Номер приходит числом или строкой из цифр («3»); другой номер или варианта с таким
    номером нет (например, варианты тем временем перестроили) — UserError «нет такого варианта».
    """
    number = int(str(number)) if str(number).isdigit() else None
    variant = dict(loadVariants(projectPath(project), stage)).get(number)

    if variant is None:
        raise UserError(translate("web.error.no_variant"))

    return number, variant


def number(value, low=0, high=2147483647):
    """Целое число из поля формы, ограниченное диапазоном [low, high].

    Терпимо к тому, как люди вводят числа: пробелы и неразрывные пробелы между разрядами
    убираются, запятая считается десятичной точкой, дробь отбрасывается. Пустое или
    нечисловое поле — UserError «введите число». Верхняя граница по умолчанию — максимум
    32-битного int, чтобы значение поместилось в решателе (C++).
    """
    try:
        value = int(float(str(value).replace(" ", "").replace("\xa0", "").replace(",", ".")))

    except (TypeError, ValueError, OverflowError):
        raise UserError(translate("web.error.number"))

    return max(low, min(value, high))


# ---------------------------------------------------------------- 4. формулировки сообщений

def bullets(items):
    """Строки «• пункт» для списков внутри вопросов и сообщений; повторы убираются, порядок сохраняется."""
    return "\n".join(f"• {item}" for item in dict.fromkeys(items))


def lessonsText(count):
    """Число уроков с правильным окончанием: «1 урок», «2 урока», «5 уроков», «11 уроков»."""
    tens, ones = count % 100, count % 10
    word = "уроков" if 11 <= tens <= 14 else "урок" if ones == 1 else "урока" if 2 <= ones <= 4 else "уроков"

    return f"{count} {word}"


def slotText(settings, day, lesson):
    """День и час урока для вопросов и сообщений: «Вторник, 16:20 - 17:50» (или номер урока, если
    ячейки нет в сетке).
    """
    times = dayGrid(settings)[day]

    return f"{translate(f'day.{day}')}, {times[lesson] if lesson < len(times) else lesson + 1}"


def conflictLines(settings, conflicts):
    """Строки «день и час: что мешает» для помех уроку в готовом расписании, без повторов.

    ``conflicts`` — [(день, урок, причина, подробность)] из courses.slotConflicts,
    courses.peerSlotConflicts, joint.copyConflicts, stages.movedStarted или stages.blockedStarted (там есть
    и причины elsewhere, noteacher, lostsubject, unplaced, teacher); текст причины —
    menu.main.tab.classes.slot_<причина>.
    """
    lines = (f"{slotText(settings, day, lesson)}: {tr(f'menu.main.tab.classes.slot_{reason}', detail=detail)}"
             for day, lesson, reason, detail in conflicts)

    return list(dict.fromkeys(lines))


def movedStartedItems(settings, moved):
    """Курсы из stages.movedStarted для страницы, отказа в принятии и
    предупреждения «Запуска» (stages.blockedStarted, state.stagesInfo): [{"course": курс, "lines": строки
    «день и час: причина»}] (conflictLines; причины — menu.main.tab.classes.slot_<причина>).
    """
    return [{"course": course, "lines": conflictLines(settings, reasons)} for course, reasons in moved]


def conflictStages(settings, conflicts):
    """Этапы, где стоят мешающие уроки, через запятую: «Поток 2, Доп. курсы» (в порядке этапов проекта).

    ``conflicts`` — [(день, урок, причина, курс-помеха)] из joint.copyConflicts. Общие уроки копии
    задаёт поток-источник, поэтому сдвинуть можно только мешающий урок: составить заново надо варианты
    его этапа — это не обязательно поток самой копии (урок блока, семинара, другого потока).
    Мешающий урок сам может быть уроком копии (другой линейки, присоединённой к другому потоку):
    его ставит не поток этой копии, а её источник, поэтому называется этап источника (courses.copyRoot).
    Сборка этапа самой копии её уроки не двигает, а этап из одних копий «Запуск» не составляет вовсе.
    """
    by_name = groupsByName(settings)
    copies = jointCopies(settings)
    order = [stage["key"] for stage in getStages(settings)]
    stages = {stageKey(by_name[copyRoot(copies, detail)]) for _, _, _, detail in conflicts}

    return ", ".join(stageLabel(stage, translate) for stage in order if stage in stages)


def cannotParagraphs(settings, items, key, **fields):
    """Абзацы вопроса про общие уроки во время «не может» (joint.copyCannot): по абзацу ``key`` на
    каждого преподавателя каждого потока-копии.

    ``items`` — [(преподаватель, день, урок, копия)]. В абзац подставляются поток-копия ({stream}
    и {number}), преподаватель ({teacher}), его время через «; » ({slots}) и ``fields``.
    """
    by_name = groupsByName(settings)
    slots = {}

    for teacher, day, lesson, name in items:
        slots.setdefault((by_name[name]["stream_id"], teacher), []).append(slotText(settings, day, lesson))

    return [tr(key, stream=stream, number=stream, teacher=teacher, slots="; ".join(dict.fromkeys(texts)), **fields)
            for (stream, teacher), texts in slots.items()]
