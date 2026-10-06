"""Проект из реальных данных школы (потоки 1 и 2 учебного года 2026/27) — для тестов.

Сами настройки собирает `tools/school_26_27.py` (`buildSettings`, `loadFixture`, `SUBJECTS`,
`FIXTURE`): этот модуль общий для тестов и скриптов tools (`create_test_project.py`,
`create_school_project.py`), поэтому код сборки живёт в одном месте.

Здесь только изоляция данных: модуль сначала импортирует пакет `tests` (папка данных
подменяется на временную раньше, чем загрузится `src`), а затем повторно экспортирует имена
из `tools.school_26_27`. Импортировать `tools.school_26_27` в тестах напрямую не нужно:
так легко забыть про `import tests` первым.

`tools` — пакет без `__init__.py` (namespace-пакет): он находится, потому что корень проекта
есть в пути импорта при `python -m unittest discover tests` из корня.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

from tools.school_26_27 import FIXTURE, SUBJECTS, buildSettings, loadFixture

# Имена, которые модуль отдаёт тестам. Список нужен и pyflakes: без него импорт выше,
# не используемый в самом модуле, он посчитал бы лишним
__all__ = ["FIXTURE", "SUBJECTS", "buildSettings", "loadFixture"]
