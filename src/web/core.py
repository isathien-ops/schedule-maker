"""Каркас веб-приложения: то, на чём стоят все остальные модули сервера.

Здесь единственный объект Flask `app`, журнал программы `log`, защита «отвечать только этому
компьютеру», общая блокировка LOCK, ошибка для человека UserError и обработчики ошибок,
а также маршруты, не связанные с проектом: сама страница, её файлы, тексты интерфейса
и справочник /api/meta.

Зависимости: из src.web ничего не импортирует (нижний слой сервера). Берёт тексты
(src.modules.translate), журнал (journal.setupLogging) и справочные константы предметных
модулей для /api/meta. Импортируют его все остальные модули сервера.
"""

import os
import threading

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from src.modules.translate import BUNDLE, translate
from src.modules.functions.grid import DAYS
from src.modules.functions.journal import setupLogging
from src.modules.functions.model import EXTRA_BLOCK
from src.modules.functions.penalties import MEDIUM_WEIGHT, TARGETS, TEMPLATES
from src.modules.functions.variants import SHORT_LINES, WEIGHT_ORDER


# Папка со страницей (index.html, app.css и скрипты страницы)
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Статику Flask сам не раздаёт (static_folder=None): для неё есть свой маршрут /static/<name>
app = Flask(__name__, static_folder=None)

# Журнал программы в %APPDATA%/Schedule-Maker-1/logs/app.log (см. journal.py); туда же — ошибки Flask
log = setupLogging()

for _handler in log.handlers:
    app.logger.addHandler(_handler)


@app.before_request
def onlyThisComputer():
    """Отвечает только на адреса этого компьютера (127.0.0.1, localhost).

    Сервер и так слушает только 127.0.0.1, но чужой сайт может подменить свой адрес на
    127.0.0.1 (DNS rebinding) и тогда читать и менять проекты из браузера. У такого запроса
    в заголовке Host остаётся имя чужого сайта — его и отсекаем.
    """
    # Host — «имя:порт» («127.0.0.1:8765»); у адреса IPv6 имя в скобках («[::1]:8765»)
    host = request.host or ""
    name = host.split("]")[0] + "]" if host.startswith("[") else host.rsplit(":", 1)[0]

    if name not in ("127.0.0.1", "localhost", "[::1]"):
        return jsonify({"error": translate("web.error.wrong_host")}), 403


# Одно изменение за раз: файлы проекта читаются и пишутся целиком, поэтому два одновременных
# запроса (две вкладки, фоновая сборка) не должны перемешаться. RLock — повторно входимая
# блокировка: на случай, если код под блокировкой когда-нибудь снова её возьмёт. Сейчас
# вложенных захватов нет: state() и rankedVariants() сами LOCK не берут — их вызывают уже под ним.
LOCK = threading.RLock()


class UserError(Exception):
    """Ошибка, понятная человеку: её текст показывается на странице.

    Бросается в любом месте обработки запроса; обработчик userError превращает её в ответ
    {"error": текст} с кодом 400. Текст уже переведён (translate) в момент создания.
    ``code`` — необязательный код ошибки для самой страницы (например "no_project": проект
    удалён в другой вкладке): по коду страница решает, что делать, а текст только показывает.
    """

    def __init__(self, text, code=None):
        super().__init__(text)
        self.code = code


# ---------------------------------------------------------------- маршруты: страница и ошибки

@app.route("/")
def index():
    """Главная (и единственная) страница приложения."""
    return send_from_directory(STATIC, "index.html")


@app.route("/static/<path:name>")
def static_files(name):
    """Файлы страницы: скрипты, стили, картинки из папки static/."""
    return send_from_directory(STATIC, name)


@app.errorhandler(UserError)
def userError(error):
    """UserError из любого маршрута — JSON {"error": текст} с кодом 400; страница показывает текст.

    Если у ошибки есть код (UserError.code), он уходит в поле "code".
    """
    body = {"error": str(error)}

    if error.code:
        body["code"] = error.code

    return jsonify(body), 400


@app.errorhandler(Exception)
def unexpectedError(error):
    """Любая непредвиденная ошибка: записывается в журнал, а странице уходит понятное сообщение
    по-русски вместо английской HTML-страницы Flask.

    * HTTP-ошибки (404, 405…) у API отвечают JSON с общим текстом, у остальных адресов
      остаются обычными страницами Flask.
    * ValueError с ключом перевода «web.…» — это повреждённый файл проекта: показывается
      его перевод с кодом 400.
    * Всё прочее — 500 и общий текст «что-то пошло не так»; подробности в журнале сервера.
    """
    if isinstance(error, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"error": translate("web.error.generic")}), error.code or 500

        return error

    # Ключи перевода приходят в ValueError (так модули сообщают о повреждённом файле проекта)
    if isinstance(error, ValueError) and str(error).startswith("web."):
        return jsonify({"error": translate(str(error))}), 400

    app.logger.exception("unexpected error")

    return jsonify({"error": translate("web.error.generic")}), 500


@app.route("/api/i18n")
def i18n():
    """Все тексты интерфейса (ru.hjson) одним словарём: страница берёт подписи отсюда."""
    return jsonify(BUNDLE)


# Справочные данные для страницы

@app.route("/api/meta")
def meta():
    """Справочник для страницы: постоянные значения сервера, которые странице нельзя заводить
    своими копиями.

      templates / targets — виды своих правил и их возможные цели (penalties.TEMPLATES, TARGETS);
      days — число дней в неделе сетки (grid.DAYS): страница своего числа дней не держит и
             по нему перебирает дни — в сетке звонков, в выборе дней своего правила и при
             поиске дней с уроками для сеток недели (weekDays в domain.js);
      extraBlock — ключ блока доп. курсов (model.EXTRA_BLOCK);
      shortLines — короткие названия линеек для карточек уроков (variants.SHORT_LINES);
      weightOrder — порядок пунктов «Что важно в расписании» (variants.WEIGHT_ORDER);
      mediumWeight — вес «Средне» своего правила (penalties.MEDIUM_WEIGHT).
    Состояний пары предметов ("allowed" / "soft" / "hard") здесь нет: они входят в формат
    данных состояния (поле pairs, см. DATA_CONTRACT.md) и в имена CSS-классов страницы.
    По этому адресу web.py находит уже запущенную копию программы.
    """
    return jsonify({
        "templates": list(TEMPLATES),
        "targets": {key: list(value) for key, value in TARGETS.items()},
        "days": DAYS,
        "extraBlock": EXTRA_BLOCK,
        "shortLines": SHORT_LINES,
        "weightOrder": list(WEIGHT_ORDER),
        "mediumWeight": MEDIUM_WEIGHT,
    })
