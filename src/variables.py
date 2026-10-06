"""Общие пути программы.

``PATH_TO_FOLDER`` — папка с данными пользователя: ``%APPDATA%/Schedule-Maker-1``.
Внутри неё ``PROJECTS_DIR`` (``projects/<имя проекта>/``) — по папке на каждый проект
(см. ``tree.py``) и ``logs/`` — журналы (см. ``journal.py``). При импорте модуля папка
``projects`` создаётся, если её ещё нет.

``FORBIDDEN_NAME_CHARS`` — символы, которых не может быть в имени файла или папки Windows:
их нет в именах проектов и журналов сборки.

``DEFAULT_WEIGHTS`` — шаблон весов встроенных правил в папке программы: из него новый
проект получает свой weights.json, а вкладка «Запуск» — «обычные» значения ползунков.

Пути относительно папки программы (``src/...``) работают, потому что web.py делает её
текущей папкой перед запуском сервера.
"""

import os

# Переменная окружения, которая заменяет %APPDATA%: её задают автотесты (tests/__init__.py),
# чтобы тестовые проекты никогда не попали в настоящую папку пользователя, даже если модуль
# тестов запущен отдельно и подменить APPDATA до импорта src не успели
DATA_DIR_VARIABLE = "SCHEDULE_DATA_DIR"

DEFAULT_WEIGHTS = os.path.join("src", "files", "weights.json")


def getAppDataDir():
    """Папка, внутри которой лежат данные программы.

    По порядку: переменная SCHEDULE_DATA_DIR (если задана и не пустая), %APPDATA% в Windows,
    иначе текущая рабочая папка (на других системах).
    """
    return os.getenv(DATA_DIR_VARIABLE) or os.getenv("APPDATA") or os.getcwd()


PATH_TO_FOLDER = f"{getAppDataDir()}/Schedule-Maker-1"

# Папка проектов: в ней по папке на каждый проект, имя папки — имя проекта
PROJECTS_DIR = os.path.join(PATH_TO_FOLDER, "projects")

# Символы, которых Windows не разрешает в именах файлов и папок; «\», «/» и «:» к тому же
# позволили бы имени проекта выйти из папки projects
FORBIDDEN_NAME_CHARS = '\\/:*?"<>|'

os.makedirs(PROJECTS_DIR, exist_ok=True)
