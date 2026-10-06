"""Запуск программы (`web.py`): защита от второго экземпляра и выбор порта.

Порт 8765 (DEFAULT_PORT) и запущенная программа пользователя не трогаются: тесты занимают
только порты, которые выдаёт система (bind на порт 0), а перебор портов ограничивают подменой
candidatePorts. Браузер, сервер Flask и таймер в main() подменяются.
"""

import tests  # первым: папка данных тестов вместо %APPDATA% (см. tests/__init__.py)
tests.requireIsolation()

import gc
import http.server
import io
import socket
import threading
import unittest
import warnings
from contextlib import redirect_stdout
from unittest import mock

import web


def freeSystemPort():
    """Порт, который система только что выдала и сразу отпустила: сейчас он свободен."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((web.HOST, 0))
        return probe.getsockname()[1]


class MetaHandler(http.server.BaseHTTPRequestHandler):
    """Сервер «как программа»: /api/meta отвечает 200, остальные адреса — 404."""
    def do_GET(self):
        self.send_response(200 if self.path == "/api/meta" else 404)
        self.end_headers()

    def log_message(self, *args):
        pass


class ForeignHandler(MetaHandler):
    """Чужой веб-сервер на порту: на /api/meta отвечает 404."""
    def do_GET(self):
        self.send_response(404)
        self.end_headers()


class LocalServer:
    """HTTP-сервер в отдельной нити на свободном порту 127.0.0.1 (контекстный менеджер)."""
    def __init__(self, handler):
        self.server = http.server.HTTPServer((web.HOST, 0), handler)
        self.port = self.server.server_address[1]

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *errors):
        self.server.shutdown()
        self.server.server_close()


class PortTests(unittest.TestCase):
    """portTaken, candidatePorts, freePort."""
    def test_port_taken_while_someone_listens(self):
        """Порт, который слушает другой сокет, занят; после закрытия сокета — свободен."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind((web.HOST, 0))
        listener.listen()
        port = listener.getsockname()[1]

        try:
            self.assertTrue(web.portTaken(port))
        finally:
            listener.close()

        self.assertFalse(web.portTaken(port))

    def test_candidate_ports(self):
        """Перебираются PORT_COUNT портов подряд начиная с предпочтительного; по умолчанию — с 8765."""
        self.assertEqual(web.candidatePorts(40000), range(40000, 40000 + web.PORT_COUNT))
        self.assertEqual(web.candidatePorts()[0], web.DEFAULT_PORT)

    def test_free_port_skips_taken(self):
        """Первые порты заняты — берётся первый свободный после них."""
        taken = {40000, 40001, 40003}

        with mock.patch.object(web, "portTaken", side_effect=lambda port: port in taken) as probe:
            self.assertEqual(web.freePort(40000), 40002)

        self.assertEqual([call.args[0] for call in probe.call_args_list], [40000, 40001, 40002])

    def test_no_free_port_exits_with_message(self):
        """Все PORT_COUNT портов заняты — выход с сообщением, где назван весь перебранный диапазон."""
        with mock.patch.object(web, "portTaken", return_value=True):
            with self.assertRaises(SystemExit) as caught:
                web.freePort(40000)

        self.assertIn(f"40000–{40000 + web.PORT_COUNT - 1}", str(caught.exception))


class RunningTests(unittest.TestCase):
    """runningCopyUrl: уже запущенная копия программы находится по ответу /api/meta."""
    def test_copy_on_far_port_is_found(self):
        """Предпочтительный порт свободен, копия программы — на следующем по перебору: её адрес."""
        with LocalServer(MetaHandler) as server, \
                mock.patch.object(web, "candidatePorts", return_value=[freeSystemPort(), server.port]):
            self.assertEqual(web.runningCopyUrl(), f"http://{web.HOST}:{server.port}/")

    def test_free_ports_are_not_asked(self):
        """Свободные порты не опрашиваются по HTTP (иначе проверка тянулась бы секундами)."""
        with mock.patch.object(web, "candidatePorts", return_value=[freeSystemPort()]), \
                mock.patch("urllib.request.urlopen") as urlopen:
            self.assertIsNone(web.runningCopyUrl())

        urlopen.assert_not_called()

    def test_foreign_server_or_silent_port_is_not_program(self):
        """Порт занят чужим сервером (404 на /api/meta) или сокетом, который не отвечает, —
        это не программа: None, и запуск пойдёт на свободный порт.
        """
        silent = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        silent.bind((web.HOST, 0))
        silent.listen()

        # runningCopyUrl() не закрывает ответ с ошибкой (HTTPError 404), и при его удалении Python
        # предупреждает ResourceWarning — здесь это не ошибка теста, предупреждение глушится
        try:
            with LocalServer(ForeignHandler) as server, warnings.catch_warnings(), \
                    mock.patch.object(web, "candidatePorts", return_value=[server.port, silent.getsockname()[1]]):
                warnings.simplefilter("ignore", ResourceWarning)
                self.assertIsNone(web.runningCopyUrl())
                gc.collect()
        finally:
            silent.close()


class MainTests(unittest.TestCase):
    """main(): второй запуск открывает уже работающую копию, первый — запускает сервер."""
    def test_second_copy_opens_running_one(self):
        """Копия уже работает: открывается её адрес, сервер не запускается; с --no-browser — без браузера."""
        address = f"http://{web.HOST}:40000/"

        for argv, opened in ((["web.py"], [mock.call(address)]), (["web.py", "--no-browser"], [])):
            with mock.patch.object(web, "runningCopyUrl", return_value=address), mock.patch.object(web, "freePort") as freePort, \
                    mock.patch.object(web.webbrowser, "open") as browser, mock.patch.object(web.sys, "argv", argv), \
                    redirect_stdout(io.StringIO()) as output:
                web.main()

            self.assertEqual(browser.call_args_list, opened, argv)
            self.assertIn(address, output.getvalue())
            freePort.assert_not_called()

    def test_first_copy_starts_server_on_free_port(self):
        """Копии нет: сервер Flask запускается на свободном порту только для этого компьютера,
        без отладчика и автоперезапуска; браузер открывается по таймеру (с --no-browser — нет).
        """
        from src.web.server import app

        for argv, timers in ((["web.py"], 1), (["web.py", "--no-browser"], 0)):
            with mock.patch.object(web, "runningCopyUrl", return_value=None), mock.patch.object(web, "freePort", return_value=40000), \
                    mock.patch.object(app, "run") as run, mock.patch.object(web.threading, "Timer") as timer, \
                    mock.patch.object(web.sys, "argv", argv), redirect_stdout(io.StringIO()) as output:
                web.main()

            run.assert_called_once_with(host="127.0.0.1", port=40000, threaded=True, debug=False, use_reloader=False)
            self.assertIn(f"http://{web.HOST}:40000/", output.getvalue())
            self.assertEqual(timer.call_count, timers, argv)

            if timers:
                timer.return_value.start.assert_called_once_with()

                # Таймер открывает в браузере адрес запущенного сервера
                with mock.patch.object(web.webbrowser, "open") as browser:
                    timer.call_args.args[1]()

                browser.assert_called_once_with(f"http://{web.HOST}:40000/")
