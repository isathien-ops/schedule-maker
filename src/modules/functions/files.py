"""Чтение и запись JSON-файлов проекта.

Запись идёт через временный файл, который заменяет старый одним действием
(«атомарная запись»): читатель (поток построения, вторая вкладка браузера) или сбой
программы никогда не увидит наполовину записанный файл.

Здесь же — чтение принятого расписания (answer.json) с проверкой: испорченный файл
расписания не должен молча считаться пустым (см. readAnswer).

Зависимости: ничего из предметного слоя (нижний слой).
"""

import json
import os
import time

# Сколько раз пробовать подменить целевой файл, если Windows держит его занятым
REPLACE_ATTEMPTS = 10


def readJson(path, default):
    """Данные файла; ``default``, если файла нет или его не прочитать."""
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    except (OSError, ValueError):
        return default


def writeJson(path, data, indent=4):
    """Атомарно записывает ``data`` в ``path`` как JSON (UTF-8, кириллица без экранирования).

    Сначала пишется ``<path>.tmp``, затем он одним шагом подменяет целевой файл.
    ``indent=None`` — компактная запись в одну строку (для больших файлов вариантов).
    Если подменить файл так и не удалось, исключение PermissionError пробрасывается дальше.
    """
    temp = f"{path}.tmp"

    with open(temp, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=indent, ensure_ascii=False)

    # В Windows целевой файл может быть на мгновение открыт (читатель, проверка антивирусом):
    # пробуем ещё несколько раз с короткой паузой. Последняя попытка — вне цикла, её ошибка
    # уходит вызывающему
    for _ in range(REPLACE_ATTEMPTS - 1):
        try:
            os.replace(temp, path)
            return

        except PermissionError:
            time.sleep(0.05)

    os.replace(temp, path)


def readAnswer(path):
    """Принятое расписание из файла ``path`` (answer.json проекта или его версии).

    Нет файла — пустой словарь (расписание ещё не составлялось). Файл есть, но испорчен или
    в нём не словарь — ``ValueError("web.error.broken_answer")`` (ключ перевода для сообщения
    человеку): испорченное расписание никогда не считается пустым, иначе следующее сохранение
    стёрло бы его насовсем.
    """
    if not os.path.exists(path):
        return {}

    answer = readJson(path, None)

    if not isinstance(answer, dict):
        raise ValueError("web.error.broken_answer")

    return answer
