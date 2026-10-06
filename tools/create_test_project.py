"""Создаёт (или пересоздаёт) тестовый проект «Тест_26_27» из `tests/fixtures/school_26_27.json`.

Запуск (из корня проекта):
    python tools/create_test_project.py [имя проекта]

Проект появляется в списке проектов приложения. Он каждый раз собирается с нуля
(старая папка с этим именем удаляется целиком!), поэтому ничего не нужно вводить
вручную. Принятого расписания (`answer.json`) в нём нет — только настройки
(`settings.json`, собранные `tools/school_26_27.buildSettings`) и стандартные
веса штрафов (`weights.json`); расписание затем строится в приложении.
"""

import json
import os
import shutil
import sys

# Корень проекта и папка tools в путь импорта, чтобы работали `src.…` и `school_26_27`.
# Пакет tests здесь импортировать нельзя: он подменяет папку данных на временную
# (и удаляет её при выходе), и проект пропал бы сразу после создания
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from school_26_27 import buildSettings  # noqa: E402
from src.variables import PATH_TO_FOLDER  # noqa: E402


def main():
    """Точка входа: пересоздаёт папку проекта и пишет в неё settings.json и weights.json.

    Имя проекта — первый аргумент командной строки, по умолчанию «Тест_26_27».
    Папка проекта — `PATH_TO_FOLDER/projects/<имя>/`; прежняя папка с этим именем
    удаляется без вопроса. Печатает путь к созданному проекту.
    """
    name = sys.argv[1] if len(sys.argv) > 1 else "Тест_26_27"
    path = f"{PATH_TO_FOLDER}/projects/{name}"

    # Удаляем прежнюю версию проекта, если была, и создаём папку заново
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)

    with open(f"{path}/settings.json", "w", encoding="utf-8") as file:
        json.dump(buildSettings(), file, indent=4, ensure_ascii=False)

    # Веса штрафов решателя — стандартные из поставки программы
    shutil.copy(os.path.join(ROOT, "src", "files", "weights.json"), f"{path}/weights.json")

    print(f"project {name}: {path}")


# Импорт модуля (например, из теста) ничего не создаёт: проект собирается только при запуске
if __name__ == "__main__":
    main()
