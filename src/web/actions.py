"""Протокол изменений: реестр действий ACTIONS, декоратор @action и единый маршрут
POST /api/project/<p>/action.

Сами действия лежат в модулях вкладок (src/web/tabs/*.py) и попадают в реестр, когда
server.py импортирует эти модули; doAction ищет действие по имени во время запроса.

Зависимости: core (app, log, LOCK, UserError), build (идёт ли сборка — только как модуль),
state (новое состояние для ответа).

Протокол
--------
* Все изменения проекта идут через один маршрут POST /api/project/<p>/action с телом
  {"action": имя, "args": {...}}; имя — функция с декоратором `@action`. Действие возвращает:
    - {"confirm": текст, "danger": bool, "yes": надпись кнопки} — нужно подтверждение:
      страница спрашивает человека и при согласии повторяет тот же запрос с force=True;
    - {"notice": текст} — только объяснение, ничего не изменено (нужно выбрать другое);
    - {"message": текст} — изменение сделано, показать пояснение;
    - ничего — изменение сделано молча.
  К любому ответу сервер добавляет "state" — полное новое состояние для перерисовки страницы.
* Ошибка, понятная человеку, — исключение UserError; она уходит странице как
  {"error": текст} с кодом 400 и показывается как сообщение.
* Действие с пометкой `@action(blocking=True)` нельзя выполнить, пока в проекте идёт сборка
  (список таких действий — BLOCKED_WHILE_RUNNING, его собирает сам декоратор).
"""

from flask import jsonify, request

from src.modules.translate import translate
from src.modules.functions.journal import short
from src.web import build
from src.web.core import LOCK, UserError, app, log
from src.web.state import state


# Реестр действий: имя функции -> функция. Заполняется декоратором @action в модулях вкладок (src/web/tabs);
# страница вызывает действие по имени через POST /api/project/<p>/action.
ACTIONS = {}

# Действия, запрещённые, пока идёт сборка (их отмечают @action(blocking=True)).
# Пока идёт сборка, нельзя менять то, что она строит: сетку, потоки, курсы, часы, преподавателей,
# закреплённые уроки, доступность, а также сбрасывать этап, принимать и отклонять варианты
# и восстанавливать версии. Нельзя менять и то, что сборка взяла в работу: веса, свои правила,
# тщательность и число вариантов, ограничение курсов на преподавателя и пары предметов. Сборка
# копирует их в самом начале, и правка во время сборки в неё уже не попала бы, а завуч думал бы,
# что попала. Разрешены только версии (сохранить, удалить), запуск (сам отвечает «идёт сборка»)
# и остановка.
BLOCKED_WHILE_RUNNING = set()


def action(function=None, *, blocking=False):
    """Декоратор: регистрирует функцию как действие, доступное странице, под её собственным именем.

    Две формы: `@action` и `@action(blocking=True)` — второе ещё и запрещает действие, пока
    в проекте идёт сборка (BLOCKED_WHILE_RUNNING).

    Действие получает имя проекта первым аргументом и остальные аргументы из "args" запроса.
    Функция возвращается без изменений, так что её можно вызывать и напрямую из Python
    (например, copyMonday зовёт setGrid).
    """
    def register(function):
        ACTIONS[function.__name__] = function

        if blocking:
            BLOCKED_WHILE_RUNNING.add(function.__name__)

        return function

    return register(function) if function is not None else register


def _outcome(result):
    """Чем закончилось действие — для журнала программы: вопрос, сообщение или «готово»."""
    if result.get("confirm"):
        return "вопрос: " + result["confirm"]

    if result.get("notice"):
        return "сообщение: " + result["notice"]

    return "готово"


def _request():
    """(имя действия, аргументы) из тела запроса; тело не того вида — общая ошибка (400).

    Ручной или испорченный запрос может прислать вместо словаря список, а вместо имени —
    не строку; такие запросы отклоняются так же, как неизвестное действие. Тело не JSON
    отклоняет сама Flask (415 или 400, ответ — общий текст, см. core.unexpectedError).
    """
    data = request.json
    name = data.get("action") if isinstance(data, dict) else None

    if not isinstance(name, str) or name not in ACTIONS:
        raise UserError(translate("web.error.generic"))

    return name, data.get("args", {})


@app.route("/api/project/<project>/action", methods=["POST"])
def doAction(project):
    """Единая точка входа для всех изменений проекта.

    Тело запроса: {"action": имя действия, "args": {именованные аргументы}}.
    Порядок работы:
    1. тело не словарь, имя не строка или неизвестно — общая ошибка;
    2. под LOCK: если идёт сборка и действие из BLOCKED_WHILE_RUNNING — отказ «идёт сборка»;
    3. вызов действия; его ответ (словарь confirm / notice / message или None) дополняется
       полем "state" — новым состоянием проекта, чтобы страница сразу перерисовалась.
    Ошибки: UserError проходит как есть; ValueError с ключом «web.…» переводится;
    прочие ошибки «неправильных данных» (TypeError, KeyError… — например, лишний аргумент
    или устаревшая вкладка) записываются в журнал и показываются как общая ошибка.
    """
    name, args = _request()

    with LOCK:
        # Проверка под блокировкой: сборка не может начаться между проверкой и изменением
        if build.running(project) and name in BLOCKED_WHILE_RUNNING:
            log.info("%s | %s | отказ: идёт сборка", project, name)
            raise UserError(translate("web.error.busy"))

        try:
            result = ACTIONS[name](project, **args) or {}
            log.info("%s | %s %s | %s", project, name, short(args), short(_outcome(result), 300))

        except UserError as error:
            log.info("%s | %s %s | отказ: %s", project, name, short(args), short(str(error), 300))
            raise

        except ValueError as error:
            # Ключи перевода приходят в ValueError (например, повреждённый файл расписания)
            if str(error).startswith("web."):
                raise UserError(translate(str(error)))

            app.logger.exception("action %s", name)
            raise UserError(translate("web.error.generic"))

        except (TypeError, KeyError, IndexError, AttributeError):
            app.logger.exception("action %s", name)
            raise UserError(translate("web.error.generic"))

        result["state"] = state(project)

    return jsonify(result)
