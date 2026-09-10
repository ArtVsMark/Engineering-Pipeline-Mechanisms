"""Отказ площадки по токену отличается от отсутствия токена.

Истёкший секрет и незаданный дают одинаковую картину снаружи — «PR перестали
открываться», — и если механизм их не различает, искать будут в скрипте, а
искать надо в сроке токена (#16).

Живая площадка для этой проверки не годится: в агентском окне запросы идут
через прокси, который подставляет собственные учётные данные, и подделанный
токен до отказа не доводит. Поэтому здесь поднимается свой сервер, отвечающий
ровно так, как ответила бы площадка на негодный токен.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tests.conftest import load_script

agent_pr = load_script("agent_pr.py")
transport = load_script("ghrest.py")


class Refusing(BaseHTTPRequestHandler):
    """Отвечает отказом по учётным данным, как площадка на истёкший токен."""

    code = 401

    def do_GET(self) -> None:
        body = b'{"message":"Bad credentials"}'
        self.send_response(self.code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """Молчит: вывод сервера не нужен в отчёте теста."""


@pytest.fixture
def refusing_server() -> Iterator[str]:
    """Поднимает сервер, отвечающий отказом, и отдаёт его адрес."""
    server = HTTPServer(("127.0.0.1", 0), Refusing)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/pulls"
    finally:
        server.shutdown()
        server.server_close()


def test_refused_token_names_the_expiry(refusing_server: str) -> None:
    """Отказ по учётным данным называет срок и права, а не только код.

    Проверка живёт здесь, у транспорта: разбор отказа сведён в один модуль
    именно затем, чтобы истёкший токен читался одинаково во всех механизмах.
    Раньше каждый разбирал его сам, и в одном месте он выглядел как «не
    настроено», а в другом — как поломка.
    """
    with pytest.raises(transport.TransportError) as caught:
        # Значение ASCII: заголовки HTTP кириллицу не несут, и настоящий
        # токен площадки её тоже не содержит.
        transport.request("GET", refusing_server, "ghp_expired000000000000000000000000000")
    message = str(caught.value)
    assert "токен задан" in message
    assert "истёкший" in message
    assert "401" in message


def test_missing_token_is_a_different_outcome() -> None:
    """Отсутствие секрета — «не настроено», и это другой исход, а не отказ.

    Спрашивается НЕ сухой прогон: он на площадку не ходит вовсе, и токен ему
    не нужен — предмет у него дерево, а не изменение.
    """
    code = agent_pr.main(["--repo", "o/r", "--branch", "agent/x"])
    assert code == agent_pr.EXIT_NOT_CONFIGURED
