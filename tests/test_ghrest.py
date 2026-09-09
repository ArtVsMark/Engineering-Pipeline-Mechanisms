"""Общий транспорт и гейт на дрейф.

Транспорт сведён в один модуль затем, чтобы отказ разбирался одинаково во всех
механизмах. Значит проверять надо две вещи: что разбор верен — и что мимо него
никто не ходит. Вторая половина и есть гейт на дрейф: без неё общий модуль
через месяц обрастает частными копиями, ровно как `gh_rest.py` у соседей
разошёлся от 131 строки до 2436.
"""

from __future__ import annotations

import ast
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from tests.conftest import ROOT, load_script

transport = load_script("ghrest.py")
SCRIPTS = ROOT / "scripts"


class Fake(BaseHTTPRequestHandler):
    """Отвечает так, как договорено в теле запроса теста."""

    code = 200
    payload: bytes = b"[]"

    def do_GET(self) -> None:
        self.send_response(self.code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args: object) -> None:
        """Молчит: вывод сервера не нужен в отчёте теста."""


def serve(code: int, payload: bytes) -> Iterator[str]:
    """Поднимает сервер с заданным ответом и отдаёт его адрес."""
    handler = type("Once", (Fake,), {"code": code, "payload": payload})
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/x"
    finally:
        server.shutdown()
        server.server_close()


def test_not_found_is_its_own_kind() -> None:
    """404 — отдельный род отказа: для части механизмов это ответ, а не поломка."""
    url = next(gen := serve(404, b'{"message":"Not Found"}'))
    try:
        with pytest.raises(transport.NotFound):
            transport.request("GET", url, "t")
    finally:
        next(gen, None)


def test_server_error_is_a_transport_error() -> None:
    """Отказ площадки, не связанный с токеном, называется своим кодом."""
    url = next(gen := serve(500, b'{"message":"boom"}'))
    try:
        with pytest.raises(transport.TransportError) as caught:
            transport.request("GET", url, "t")
        assert "500" in str(caught.value)
        assert "токен задан" not in str(caught.value)
    finally:
        next(gen, None)


def test_unparsable_answer_is_named() -> None:
    """Ответ не разобрался — это отказ транспорта, а не пустой результат."""
    url = next(gen := serve(200, b"not json at all"))
    try:
        with pytest.raises(transport.TransportError) as caught:
            transport.request("GET", url, "t")
        assert "не разобран" in str(caught.value)
    finally:
        next(gen, None)


def test_short_page_stops_the_walk() -> None:
    """Короткая страница завершает обход — иначе он бесконечен."""
    url = next(gen := serve(200, json.dumps([{"n": 1}, {"n": 2}]).encode()))
    try:
        assert list(transport.paginate(url, "t")) == [{"n": 1}, {"n": 2}]
    finally:
        next(gen, None)


def test_nested_list_is_taken_by_key() -> None:
    """Площадка кладёт часть списков внутрь объекта — обход это учитывает."""
    body = json.dumps({"check_runs": [{"name": "lint"}]}).encode()
    url = next(gen := serve(200, body))
    try:
        assert list(transport.paginate(url, "t", key="check_runs")) == [{"name": "lint"}]
    finally:
        next(gen, None)


def test_path_and_full_url_both_work() -> None:
    """Адрес принимается и путём от корня, и целиком: механизмы зовут по-разному."""
    assert transport._url("repos/o/r").startswith(transport.API_ROOT)
    assert transport._url("https://example.test/x") == "https://example.test/x"


# --- гейт на дрейф -----------------------------------------------------------


def imports_of(path: Path) -> set[str]:
    """Имена модулей, которые файл импортирует."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize(
    "path", sorted(p for p in SCRIPTS.glob("*.py") if p.name != "ghrest.py"), ids=lambda p: p.name
)
def test_no_mechanism_talks_to_the_platform_directly(path: Path) -> None:
    """Мимо общего транспорта в площадку не ходят.

    Это и есть дрейф на нашем этаже: вторая реализация появляется не сразу
    целым файлом, а одним «мне нужен всего один запрос». У соседей так и
    выросли 2436 строк против 131.
    """
    direct = {name for name in imports_of(path) if name.startswith("urllib.request")}
    assert not direct, f"{path.name} ходит в площадку мимо ghrest: {direct}"


@pytest.mark.parametrize(
    "path", sorted(p for p in SCRIPTS.glob("*.py") if p.name != "ghrest.py"), ids=lambda p: p.name
)
def test_no_mechanism_builds_its_own_authorization(path: Path) -> None:
    """Заголовок с токеном собирается в одном месте, а не в каждом механизме."""
    text = path.read_text(encoding="utf-8")
    assert "Authorization" not in text, f"{path.name} собирает заголовок токена сам"
