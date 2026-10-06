"""Журналы программы — чтобы потом можно было разобраться, что происходило.

Всё пишется в папку ``%APPDATA%/Schedule-Maker-1/logs``:

* ``app.log`` — общий журнал: запуск программы, каждое действие на странице (какой проект,
  что сделано, с какими данными, чем кончилось), ошибки с подробностями. Файл ограничен
  2 МБ; старые части сохраняются как ``app.log.1`` … ``app.log.5`` и потом удаляются.
* ``builds/<дата-время> <проект> <этап>.log`` — каждое составление вариантов целиком:
  настройки сборки (этап, «оставить принятые», тщательность, веса, свои правила) и полный
  вывод решателя по каждому варианту. Хранятся последние 50 сборок.

Журналы пишутся только на этом компьютере и никуда не отправляются.

Зависимости: только src.variables (папка данных, запрещённые в именах файлов символы).
"""

import datetime
import logging
import logging.handlers
import os
import re

from src.variables import FORBIDDEN_NAME_CHARS, PATH_TO_FOLDER

LOG_DIR = os.path.join(PATH_TO_FOLDER, "logs")
BUILDS_DIR = os.path.join(LOG_DIR, "builds")
KEEP_BUILDS = 50

logger = logging.getLogger("schedule")


def setupLogging():
    """Подключает файл ``app.log`` к журналу программы (один раз; повторный вызов ничего не делает).

    Возвращает журнал ``logger``; в него же стоит направить журнал Flask (см. src/web/core.py).
    """
    if any(isinstance(handler, logging.handlers.RotatingFileHandler) for handler in logger.handlers):
        return logger

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(os.path.join(LOG_DIR, "app.log"), maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    except OSError:
        # Нет доступа к папке — программа работает и без журнала
        pass

    return logger


def short(value, limit=400):
    """Текст для журнала: значение одной строкой, обрезанное до ``limit`` символов."""
    text = re.sub(r"\s+", " ", repr(value))

    return text if len(text) <= limit else text[:limit] + "…"


def openBuildLog(project, stage):
    """Новый файл журнала одной сборки (открыт на запись) или None, если файл создать нельзя.

    Перед созданием удаляет самые старые журналы сборок, чтобы их оставалось не больше KEEP_BUILDS.
    """
    try:
        os.makedirs(BUILDS_DIR, exist_ok=True)
        old = sorted(name for name in os.listdir(BUILDS_DIR) if name.endswith(".log"))

        for name in old[:max(0, len(old) - KEEP_BUILDS + 1)]:
            os.remove(os.path.join(BUILDS_DIR, name))

        # Имя файла без символов, которые Windows не разрешает
        safe = re.sub(f"[{re.escape(FORBIDDEN_NAME_CHARS)}]+", "_", f"{project} {stage}")
        name = f"{datetime.datetime.now():%Y-%m-%d %H-%M-%S} {safe}.log"

        return open(os.path.join(BUILDS_DIR, name), "w", encoding="utf-8", buffering=1)

    except OSError:
        return None
