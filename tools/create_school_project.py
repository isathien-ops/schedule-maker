"""Создание готового проекта для передачи руководителю по текущему расписанию школы.

Строит проект приложения «Расписание занятий» из выгрузки таблицы
«Расписание и программы 26/27»: потоки 1, 2 и дополнительные курсы (семинары).

Запуск (из корня проекта):
    python tools/create_school_project.py <выгрузка .xlsx> [имя проекта] [архив .zip]

Листы таблицы разбирает `tools/import_26_27.py` (функция `parse`), настройки проекта
собирает `tools/school_26_27.buildSettings`. В проекте получается:
- каждый курс со своими недельными уроками и датой начала;
- учитель, указанный в таблице, — «ведёт» курс; все остальные учителя этого предмета —
  «может вести» (см. `mayTeachAll`);
- уроки на их реальных днях и времени записываются как принятое расписание
  (`answer.json`), поэтому проект сразу открывается на вкладке «Расписание»;
- исключение — курсы более позднего потока, уроки которых — точная копия потока 1
  (те же дни, время и учитель): в таблице их скопировали, пока поток ещё не спланирован,
  поэтому они не ставятся, а остаются программе на составление;
- сохранённая версия «Передано руководителю», чтобы первое изменение можно было откатить.

Проект создаётся только под новым именем (существующий проект никогда не перезаписывается).
Если передан третий аргумент, проект дополнительно упаковывается в .zip для кнопки
«Импорт проекта» на другом компьютере.

Файлы проекта лежат в `PATH_TO_FOLDER/projects/<имя>/`: `settings.json` (курсы, учителя,
сетка), `answer.json` (принятое расписание), `weights.json` (веса штрафов решателя).
"""

import json
import os
import shutil
import sys

# Корень проекта; добавляем его и папку tools в путь импорта, чтобы скрипт
# можно было запускать напрямую, без установки пакета.
# Пакет tests здесь импортировать нельзя: он подменяет папку данных на временную
# (и удаляет её при выходе), поэтому настройки берутся из tools/school_26_27.py
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from import_26_27 import parse  # noqa: E402
from school_26_27 import buildSettings  # noqa: E402
from src.variables import PATH_TO_FOLDER  # noqa: E402
from src.modules.functions.courses import courseName  # noqa: E402
from src.modules.functions.model import emptyCell, lessonEntries  # noqa: E402
from src.modules.functions.stages import acceptedStages, teacherClashes  # noqa: E402
from src.modules.functions.tree import exportProjectArchive, prepareProject  # noqa: E402
from src.modules.functions.versions import saveVersion  # noqa: E402
from src.modules.translate import translate  # noqa: E402


def mayTeachAll(settings):
    """Разрешает каждому учителю предмета вести любой курс этого предмета («может вести»).

    Так же поступает приложение с новыми учителями. Изменяет `settings` на месте:
    в `settings["teachers"][имя]["subjects"][i]["classes"]` добавляются имена всех
    курсов (`custom_groups`), где есть этот предмет. Ничего не возвращает.
    """
    # Предмет -> список курсов, в которых он преподаётся
    courses = {}

    for group in settings["classes"]["custom_groups"]:
        for subject in group.get("subjects", []):
            courses.setdefault(subject, []).append(group["name"])

    for teacher in settings["teachers"].values():
        for entry in teacher["subjects"]:
            for course in courses.get(entry["subject"], []):
                if course not in entry["classes"]:
                    entry["classes"].append(course)


def buildAnswer(data):
    """Строит принятое расписание из реальных уроков таблицы.

    Формат такой же, как пишет решатель: `answer[курс][день][урок]` — ячейка
    {"subject", "teachers"}; пустая ячейка имеет subject "#".

    `data` — результат `import_26_27.parse`. Возвращает пару `(answer, notes)`, где
    `notes` — список предупреждений для печати (лишние слоты, пропущенные копии потока 1).
    """
    grid = data["day_grid"]
    answer = {}
    notes = []

    for item in data["courses"]:
        course = courseName(item["stream"], item["line"], item["subject"])
        week = answer.setdefault(course, [[emptyCell() for _ in day] for day in grid])
        # Семинар общий для потоков: на листах разных потоков у него может стоять разное
        # время, а уроков в неделю — максимум по одному потоку (у обычного курса слотов
        # ровно столько, сколько уроков); берём первые по порядку
        slots = item["slots"][:item["hours"]]

        if len(item["slots"]) > item["hours"]:
            notes.append(f"{course}: в листах {len(item['slots'])} разных времени на {item['hours']} урок в неделю, взято первое")

        # Ставим урок с первым (основным) учителем курса
        for day, lesson in slots:
            week[day][lesson] = {"subject": item["subject"], "teachers": item["teachers"][:1]}

    # Более поздний поток, который урок в урок повторяет поток 1, ещё не спланирован:
    # убираем его из принятого расписания, программа составит его сама
    def lessons(course):
        """Отсортированный список (день, урок, учителя) всех уроков курса — для сравнения потоков."""
        return sorted((day, lesson, tuple(cell["teachers"])) for day, lesson, cell in lessonEntries(answer, course))

    for item in data["courses"]:
        # Семинары (поток None) и сам поток 1 сравнивать не с чем
        if item["stream"] in (None, 1):
            continue

        # Такой же курс в потоке 1 строится из тех же линейки и предмета: имя курса
        # не разбирается (см. courses.courseName), а собирается заново
        course = courseName(item["stream"], item["line"], item["subject"])
        first = courseName(1, item["line"], item["subject"])

        if first in answer and lessons(course) == lessons(first):
            del answer[course]
            notes.append(f"{course}: в таблице копия потока 1 — уроки не поставлены, программа соберёт их сама")

    return answer, notes


def clashNotes(settings, answer):
    """Накладки учителей в виде строк-предупреждений для печати.

    Сами накладки ищет `stages.teacherClashes` — так же, как их видит программа:
    два урока учителя в одно время считаются накладкой, только если даты курсов
    пересекаются (курсы разных потоков могут идти в разные месяцы).
    Одна строка — на один слот учителя (день и урок), в ней все курсы этого слота.
    Ничего не меняет.
    """
    return [
        f"{teacher}: {' и '.join(courses)} в одно время (день {day + 1}, урок {lesson + 1})"
        for teacher, day, lesson, courses in teacherClashes(settings, answer)
    ]


def main():
    """Точка входа: разбирает аргументы, создаёт папку проекта и все его файлы.

    Пишет в `PATH_TO_FOLDER/projects/<имя>/` файлы settings.json, answer.json,
    weights.json и версию «Передано руководителю»; печатает предупреждения
    и при необходимости создаёт .zip-архив. Если проект с таким именем уже есть —
    завершается с ошибкой, ничего не трогая.
    """
    workbook = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else "Расписание_2026_27"
    archive = sys.argv[3] if len(sys.argv) > 3 else None
    path = f"{PATH_TO_FOLDER}/projects/{name}"

    # Никогда не перезаписываем существующий проект пользователя
    if os.path.exists(path):
        sys.exit(f"project {name} already exists: choose another name")

    data = parse(workbook)
    settings = buildSettings(data=data)
    mayTeachAll(settings)
    answer, notes = buildAnswer(data)

    os.makedirs(path)

    with open(f"{path}/settings.json", "w", encoding="utf-8") as file:
        json.dump(settings, file, indent=4, ensure_ascii=False)

    with open(f"{path}/answer.json", "w", encoding="utf-8") as file:
        json.dump(answer, file, indent=4, ensure_ascii=False)

    # Веса штрафов решателя — стандартные из поставки программы
    shutil.copy(os.path.join(ROOT, "src/files/weights.json"), f"{path}/weights.json")

    # Значения по умолчанию (например, пары «нежелательно») — так же, как при открытии проекта в приложении
    prepareProject(name)

    # Первая сохранённая версия: к ней можно вернуться после любых правок. Имя — текст
    # web.save.handover_name из ru.hjson («Передано руководителю»): по этому имени state.py
    # узнаёт исходное расписание (поле handover) и перед его удалением предупреждает особо,
    # поэтому имя берётся из того же места, а не пишется здесь второй раз
    saveVersion(path, translate("web.save.handover_name"),"Расписание из таблицы «Расписание и программы 26/27»", acceptedStages(settings, answer))

    # Предупреждения для того, кто готовит проект: что взято не целиком и где накладки
    for line in notes + clashNotes(settings, answer):
        print("!", line)

    if archive:
        exportProjectArchive(path, archive)
        print("archive:", archive)

    print(f"project {name}: {len(data['courses'])} courses, {len(settings['teachers'])} teachers")


if __name__ == "__main__":
    main()
