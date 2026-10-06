"""Вкладка «Версии»: сохранить версию проекта вручную, восстановить и удалить версию.
Пара на странице — static/tabs/save.js. Модуль маленький: одна вкладка — один модуль.

Зависимости: actions (@action), core (UserError), project (файлы проекта, проверка версии;
расписание здесь читается терпимо — loadAnswerOrEmpty, см. её описание) и предметные модули
(versions, tree, stages, files). datetime импортируется модулем: тесты подменяют datetime.date.
"""

import datetime
import os

from src.modules.translate import tr, translate
from src.modules.functions.files import readJson
from src.modules.functions.stages import acceptedStages
from src.modules.functions.tree import isCurrentFormat, prepareProject
from src.modules.functions.versions import deleteVersion, restoreVersion, saveVersion, versionsDir
from src.web.actions import action
from src.web.core import UserError
from src.web.project import loadAnswerOrEmpty, loadSettings, projectPath, requireVersion


# Версии проекта (вкладка «Версии»)

@action
def newVersion(project, name, comment=""):
    """Сохраняет версию проекта вручную; пустое имя — «Версия от дд.мм.гггг чч:мм»."""
    settings = loadSettings(project)
    name = (name or "").strip() or f"{translate('menu.main.tab.save.default_name')} {datetime.datetime.now():%d.%m.%Y %H:%M}"

    saveVersion(projectPath(project), name, comment or "", acceptedStages(settings, loadAnswerOrEmpty(project)))


@action(blocking=True)
def restore(project, version):
    """Восстанавливает версию `version`.

    Версия другого формата (сохранённая до обновления программы, см. tree.isCurrentFormat)
    не восстанавливается — понятная ошибка, проект не меняется. Перед восстановлением
    текущее состояние само сохраняется версией «Перед возвратом к версии от …», чтобы его
    можно было отменить. После — tree.prepareProject, как при открытии проекта.
    """
    meta = requireVersion(project, version)
    path = projectPath(project)

    if not isCurrentFormat(readJson(os.path.join(versionsDir(path), version, "settings.json"), None)):
        raise UserError(translate("web.error.old_version"))

    settings = loadSettings(project)

    # Текущее состояние тоже становится версией, чтобы восстановление можно было отменить. Её имя —
    # «Перед возвратом к версии от <когда>», а комментарий — имя восстановленной версии: так в списке
    # видно, к какой версии вернулись, даже если у неё не было даты
    saveVersion(path, tr("web.version.before_restore", when=versionTime(meta, version)), meta.get("name", ""),
                acceptedStages(settings, loadAnswerOrEmpty(project)))
    restoreVersion(path, version)
    prepareProject(project)


def versionTime(meta, version):
    """Когда сохранена версия, коротко: «дд.мм чч:мм» из её даты создания (meta.json, ISO-строка).

    Без даты или с неверной датой — имя версии, а без имени — её id.
    """
    try:
        return f"{datetime.datetime.fromisoformat(str(meta.get('created', ''))):%d.%m %H:%M}"

    except ValueError:
        return meta.get("name", version)


@action
def removeVersion(project, version):
    """Удаляет сохранённую версию."""
    requireVersion(project, version)
    deleteVersion(projectPath(project), version)
