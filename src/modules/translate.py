"""Тексты интерфейса: перевод ключей вида «menu.main.tab.export.day» в русские строки.

Все надписи программы лежат в ``src/files/bundles/ru.hjson``. Файл читается один раз
при импорте модуля (путь относительный — текущей папкой должна быть папка программы,
это обеспечивает web.py).

* ``translate(ключ)`` — текст как есть;
* ``tr(ключ, имя=значение, …)`` — текст с подставленными значениями: в ru.hjson места для
  них записаны как ``{имя}`` (например, web.problem.free_hours: «{name} — свободных уроков: {count}»,
  вызов ``tr("web.problem.free_hours", name=…, count=…)``);
* ``fill(текст, имя=значение, …)`` — та же подстановка в уже готовый текст (например, в шаблон,
  полученный через переданную функцию перевода).
"""

import re

import hjson

# Программа только на русском
with open("src/files/bundles/ru.hjson", "r", encoding="utf-8") as file:
    BUNDLE = hjson.load(file)

# Место для значения в тексте: {имя}
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def translate(name) -> str:
    """Текст для ключа ``name``; если ключа нет в ru.hjson — сам ключ (так пропуск сразу виден)."""
    return BUNDLE.get(name, name)


def fill(text, /, **values) -> str:
    """Текст ``text`` с подставленными значениями: ``{имя}`` → ``str(values["имя"])``.

    Подстановка идёт за один проход, поэтому фигурные скобки внутри подставленного значения
    (например, в названии курса) не принимаются за новое место для подстановки. Места,
    для которых значение не передано, остаются в тексте как есть.
    """
    return PLACEHOLDER.sub(lambda match: str(values[match.group(1)]) if match.group(1) in values else match.group(0), text)


def tr(key, /, **values) -> str:
    """Текст для ключа ``key`` с подставленными значениями (см. ``fill``)."""
    return fill(translate(key), **values)
