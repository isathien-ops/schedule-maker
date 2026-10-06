r"""Упаковывает готовую программу в архив для передачи «Расписание_для_передачи.zip».

Запускать после build.bat из корня проекта:

    .venv\Scripts\python tools\pack_release.py

Что делает:
1. проверяет, что программа в dist собрана из нынешних исходников:
   - страница, тексты, шаблон весов и решатель сравниваются по содержимому: они лежат
     в сборке отдельными файлами;
   - код на Python (web.py и все .py в src) PyInstaller упаковывает внутрь Расписание.exe,
     сравнить его по содержимому нельзя, поэтому он проверяется по дате изменения:
     ни один такой файл не должен быть новее Расписание.exe (build.bat с --clean
     переписывает exe при каждой сборке);
   если какого-то файла в dist нет, он отличается или .py новее сборки, программа собрана
   из старых файлов: скрипт просит сначала запустить build.bat и выходит, ничего в dist
   не меняя;
2. кладёт в папку dist рядом с программой проект «Расписание_2026-27.zip» и инструкцию
   «Как запустить.txt» (из tools/release);
3. упаковывает папку dist в «Расписание_для_передачи.zip» (сначала во временный файл, чтобы
   при ошибке не остался полупустой архив).
"""

import filecmp
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
ARCHIVE = os.path.join(ROOT, "Расписание_для_передачи.zip")

# Файлы, которые должны совпадать в исходниках и в собранной программе: всё, что
# build.bat кладёт в сборку как данные, — вся папка страницы (src/web/static) и вся
# папка src/files (тексты, шаблон весов новых проектов), плюс решатель solve.exe.
# Папки обходятся целиком, чтобы новый файл в них не пришлось вписывать сюда вручную
CHECKED = sorted(os.path.relpath(os.path.join(folder, name), ROOT).replace("\\", "/")
                 for top in ("src/web/static", "src/files")
                 for folder, _, names in os.walk(os.path.join(ROOT, top))
                 for name in names) + ["src/modules/solve.exe"]

# Собранная программа: код на Python лежит внутри неё, поэтому с ней сравниваются даты .py
EXE = os.path.join(DIST, "Расписание", "Расписание.exe")


def isStale(path, inside):
    """Устарел ли файл `path` (путь от корня проекта) в собранной программе.

    `inside` — папка _internal сборки. Файл устарел, если его там нет (например,
    добавлен после последней сборки или dist ещё не собран) или содержимое
    отличается от исходника.
    """
    built = os.path.join(inside, path)

    return not os.path.isfile(built) or not filecmp.cmp(os.path.join(ROOT, path), built, shallow=False)


def pythonSources():
    """Код на Python, который PyInstaller упаковывает внутрь Расписание.exe.

    Это web.py и все файлы .py в папке src (кроме кэша __pycache__). Пути — от корня
    проекта, через «/». Папки tools и tests в программу не попадают и здесь не нужны.
    """
    paths = ["web.py"]

    for folder, folders, names in os.walk(os.path.join(ROOT, "src")):
        folders[:] = [name for name in folders if name != "__pycache__"]
        paths += [os.path.relpath(os.path.join(folder, name), ROOT).replace("\\", "/") for name in names if name.endswith(".py")]

    return sorted(paths)


def newerThanBuild(exe):
    """Файлы кода на Python, изменённые после сборки программы `exe`.

    Сравнить их с собранной программой по содержимому нельзя (они внутри exe), поэтому
    сравниваются даты: файл новее exe — значит, после него программу не пересобирали.
    Если exe нет совсем (dist не собран), возвращает путь к самому exe: собирать нужно всё.
    """
    if not os.path.isfile(exe):
        return [os.path.relpath(exe, ROOT).replace("\\", "/")]

    built = os.path.getmtime(exe)

    return [path for path in pythonSources() if os.path.getmtime(os.path.join(ROOT, path)) > built]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    inside = os.path.join(DIST, "Расписание", "_internal")

    stale = [path for path in CHECKED if isStale(path, inside)] + newerThanBuild(EXE)

    if stale:
        sys.exit("Программа в dist собрана из старых файлов (" + ", ".join(stale) + "): сначала запустите build.bat")

    shutil.copy(os.path.join(ROOT, "Расписание_2026-27.zip"), DIST)
    shutil.copy(os.path.join(ROOT, "tools", "release", "Как запустить.txt"), DIST)

    temporary = ARCHIVE + ".new"
    count = 0

    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for folder, _, names in os.walk(DIST):
            for name in names:
                path = os.path.join(folder, name)
                archive.write(path, os.path.relpath(path, DIST))
                count += 1

    os.replace(temporary, ARCHIVE)
    print(f"Готово: {ARCHIVE} — файлов {count}, {os.path.getsize(ARCHIVE) / 2 ** 20:.1f} МБ")


if __name__ == "__main__":
    main()
