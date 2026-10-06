"""Запускает веб-приложение «Расписание занятий» на этом компьютере и открывает его в браузере.

Как это работает:
1. Если программа уже запущена (exe открыли второй раз), просто открываем её адрес
   в браузере и выходим — два сервера правили бы одни и те же файлы проектов.
2. Иначе ищем свободный порт начиная с 8765, запускаем Flask-сервер
   (``src/web/server.py``) и через секунду открываем страницу в браузере.

Сервер доступен только с этого компьютера (127.0.0.1). Чтобы остановить его, закройте
окно консоли. Параметр командной строки ``--no-browser`` — не открывать браузер.
"""

import os
import socket
import sys
import threading
import urllib.request
import webbrowser

# Файлы программы, решатель и тексты ищутся относительно папки приложения
# (в готовой сборке они распакованы рядом с exe, в sys._MEIPASS)
os.chdir(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

# Только локальный адрес: снаружи сервер недоступен
HOST = "127.0.0.1"

# Первый порт, который пробует программа, и сколько портов подряд она перебирает
DEFAULT_PORT = 8765
PORT_COUNT = 50


def portTaken(port):
    """Занят ли порт: пробуем сами занять его (bind) и сразу отпускаем.

    Это мгновенно. Подключаться к порту для проверки нельзя: в Windows подключение
    к закрытому порту ждёт около 2 секунд, и проверка PORT_COUNT портов растянулась бы на минуты.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
            return False

        except OSError:
            return True


def candidatePorts(preferred=DEFAULT_PORT):
    """Порты, которые перебирает программа: ``preferred``…``preferred + PORT_COUNT - 1``."""
    return range(preferred, preferred + PORT_COUNT)


def freePort(preferred=DEFAULT_PORT):
    """Первый свободный порт из candidatePorts; если все заняты — выход с сообщением."""
    for port in candidatePorts(preferred):
        if not portTaken(port):
            return port

    raise SystemExit(f"Нет свободного порта {preferred}–{preferred + PORT_COUNT - 1}: закройте другие окна программы.")


def runningCopyUrl(preferred=DEFAULT_PORT):
    """Программа уже отвечает на этом компьютере (exe запустили дважды): её адрес, иначе None.

    Проверяются те же порты, что и в ``freePort``: занятые порты (их мало, проверка быстрая)
    получают запрос к ``/api/meta`` с коротким таймаутом. Так находится и копия на дальнем порту.
    """
    for port in candidatePorts(preferred):
        if not portTaken(port):
            continue

        try:
            urllib.request.urlopen(f"http://{HOST}:{port}/api/meta", timeout=0.5)
            return f"http://{HOST}:{port}/"

        except OSError:
            continue

    return None


def main():
    """Точка входа: найти уже запущенную копию или запустить сервер и открыть браузер."""
    # Одна программа за раз: два сервера правили бы одни и те же файлы проектов
    url = runningCopyUrl()

    if url:
        print(f"Программа уже запущена: {url}")

        if "--no-browser" not in sys.argv:
            webbrowser.open(url)

        return

    # Сервер импортируется здесь, а не в начале файла, по двум причинам: при загрузке он читает
    # файлы по относительным путям (папка программы становится текущей выше, при загрузке web.py)
    # и подключает журнал программы — второму запуску exe, который только открывает браузер,
    # ни то ни другое не нужно
    from src.web.server import app, log

    port = freePort()
    url = f"http://{HOST}:{port}/"

    log.info("Программа запущена: %s (папка программы: %s)", url, os.getcwd())
    print(f"Расписание занятий: {url}")
    print("Чтобы остановить, закройте это окно.")

    # Браузер открывается с задержкой, чтобы сервер успел начать слушать порт
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # Работает до закрытия окна. Отладчик и автоперезапуск выключены: перезапуск запустил бы
    # процесс второй раз, а отладчик не нужен пользователю. threaded — запросы обслуживаются параллельно
    app.run(host=HOST, port=port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
