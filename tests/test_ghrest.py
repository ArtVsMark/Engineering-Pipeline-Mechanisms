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
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar, Final

import pytest

from tests.conftest import ROOT, load_script

transport = load_script("ghrest.py")
SCRIPTS = ROOT / "scripts"


class Fake(BaseHTTPRequestHandler):
    """Отвечает так, как договорено в теле запроса теста."""

    code = 200
    payload: bytes = b"[]"
    extra: ClassVar[dict[str, str]] = {}

    def do_GET(self) -> None:
        self.send_response(self.code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.payload)))
        for name, value in self.extra.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(self.payload)

    def do_POST(self) -> None:
        """GraphQL ходит только POST — отвечаем ему тем же, что и GET."""
        self.do_GET()

    def log_message(self, *args: object) -> None:
        """Молчит: вывод сервера не нужен в отчёте теста."""


def serve(code: int, payload: bytes, extra: dict[str, str] | None = None) -> Iterator[str]:
    """Поднимает сервер с заданным ответом и отдаёт его адрес."""
    handler = type("Once", (Fake,), {"code": code, "payload": payload, "extra": extra or {}})
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


#: Кому положено разбирать YAML самому — и почему. Список РАЗРЕШЁННОГО, а не
#: запрещённого (068): предмет у каждого свой, и ни у одного это не состав
#: меток. Новое имя добавляется сюда осознанно, вместе с причиной, — иначе
#: гейт превращается в «кто первым сломался, тот и исключение».
YAML_READERS: Final = {
    "check_required_context.py": "джобы прогона, чтобы сверить имя обязательного контекста",
    "pipeline_checks.py": "ответ проекта по классам проверок и джобы прогонов",
    "preflight.py": "КОМАНДЫ шагов прогона: их надо запустить так же, как площадка",
    "contract.py": "поверхность контракта: имена джобов, события и входы прогонов",
}


@pytest.mark.parametrize(
    "path",
    # `paths.py` назван здесь по той же причине, что и `labels.py`: он ЯКОРЬ, а
    # не читатель. Адрес состава объявлен в нём одном, и требовать от него
    # ходить за адресом в разборщик значило бы завести круг.
    sorted(p for p in SCRIPTS.glob("*.py") if p.name not in {"labels.py", "ghrest.py", "paths.py"}),
    ids=lambda p: p.name,
)
def test_no_mechanism_parses_the_label_config_itself(path: Path) -> None:
    """Состав меток разбирает один модуль, а не каждый по-своему.

    Читателей у файла трое, и читали они его по-разному: один с проверкой цвета
    и описания, другой без неё, третий не читал вовсе — и открывал изменение,
    которое второй тут же отвергал. Это дрейф на данных, и ловится он так же,
    как дрейф на транспорте.
    """
    text = path.read_text(encoding="utf-8")
    assert "labels.yml" not in text or "labels.load" in text or "import labels" in text, (
        f"{path.name} обращается к составу меток мимо общего модуля"
    )
    assert "yaml.safe_load" not in text or path.name in YAML_READERS, (
        f"{path.name} разбирает YAML сам, а его нет среди тех, кому это положено: "
        f"{', '.join(sorted(YAML_READERS))}"
    )


def test_quote_escapes_the_slash_in_a_path_segment() -> None:
    """Отрезок пути экранируется целиком, включая слэш.

    Реальные метки проекта — `area/docs`, `difficulty/easy` — содержат слэш, и
    без экранирования он уходит в адрес разделителем пути.

    ЗАМЕР: площадка сегодня принимает ОБА вида — и `area/docs`, и `area%2Fdocs`
    отвечают одной меткой. То есть поломки здесь не было, и закрепляется не
    починка, а независимость от недокументированного поведения: разбор чужого
    неэкранированного пути — не то, на чём стоит держать механизм.
    """
    assert transport.quote("area/docs") == "area%2Fdocs"
    assert transport.quote("difficulty/easy") == "difficulty%2Feasy"
    assert transport.quote("bug") == "bug"


# --- квота -------------------------------------------------------------------


def test_exhausted_quota_is_its_own_kind() -> None:
    """Исчерпанная квота — отдельный род отказа, а не «почини права».

    Это единственное состояние, в котором верный ответ «подожди»: счётчик
    обращений растёт и после нуля, поэтому повтор только отдаляет сброс.
    """
    reset = int(time.time()) + 120
    headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)}
    url = next(gen := serve(403, b'{"message":"rate limit"}', headers))
    try:
        with pytest.raises(transport.RateLimited) as caught:
            transport.request("GET", url, "t")
        assert caught.value.wait_seconds() > 0
        assert "ждать" in caught.value.describe().lower()
    finally:
        next(gen, None)


def test_forbidden_without_quota_headers_is_not_rate_limit() -> None:
    """403 без заголовков квоты — «причина другая», а не исчерпанный лимит.

    Советовать ждать сброса там, где ждать нечего, хуже, чем не советовать
    ничего: настоящая причина (обычно права токена) при этом теряется.
    """
    url = next(gen := serve(403, b'{"message":"Resource not accessible"}'))
    try:
        with pytest.raises(transport.TransportError) as caught:
            transport.request("GET", url, "t")
        assert not isinstance(caught.value, transport.RateLimited)
        assert "токен задан" in str(caught.value)
    finally:
        next(gen, None)


def test_retry_after_alone_is_enough_for_rate_limit() -> None:
    """`retry-after` без счётчика остатка — тоже сказанная площадкой квота."""
    url = next(gen := serve(429, b"{}", {"retry-after": "30"}))
    try:
        with pytest.raises(transport.RateLimited) as caught:
            transport.request("GET", url, "t")
        assert 0 < caught.value.wait_seconds() <= 30
    finally:
        next(gen, None)


def test_quota_floor_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Порог настраивается окружением, а битое значение не роняет запрос."""
    monkeypatch.setenv(transport.ENV_QUOTA_FLOOR, "42")
    assert transport.quota_floor() == 42
    monkeypatch.setenv(transport.ENV_QUOTA_FLOOR, "не число")
    assert transport.quota_floor() == transport.QUOTA_FLOOR


# --- GraphQL: дверь одна, и она спрашивает -----------------------------------


def test_the_operation_name_is_read_from_the_query() -> None:
    """Имя операции берут ИЗ запроса, а не передают рядом с ним.

    Переданное рядом рассогласуется с телом при первой же правке запроса, и
    проверка списком станет проверкой подписи под ним.
    """
    assert transport.operation_of("mutation($id: ID!) {\n enablePullRequestAutoMerge(") == (
        "enablePullRequestAutoMerge"
    )
    assert transport.operation_of("query { viewer { login } }") == "", (
        "форма без вызова разобралась"
    )


def test_an_operation_outside_the_allowlist_never_reaches_the_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отказ наступает ДО запроса: иначе список стал бы отчётом, а не гейтом."""

    def unreached(*args: object, **kwargs: object) -> None:
        raise AssertionError("запрос ушёл в площадку, хотя операции нет в списке")

    monkeypatch.setattr(transport, "request", unreached)
    with pytest.raises(transport.TransportError) as caught:
        transport.graphql("mutation { createRef(input: {}) { ref { name } } }", {}, "t")
    assert "createRef" in str(caught.value)
    assert "REST" in str(caught.value), "отказ не назвал причину: дешевле можно"


def test_the_allowlist_names_a_reason_for_every_entry() -> None:
    """Каждое имя в списке — утверждение «дешевле нельзя», и оно записано словами."""
    assert transport.NO_REST, "закрытый список пуст — дверь открыта всем"
    for name, why in transport.NO_REST.items():
        assert len(why) > 20, f"{name} внесён в список без причины"


def test_errors_at_two_hundred_are_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ GraphQL приходит с кодом 200 — и читается телом, а не кодом (045)."""
    payload = b'{"data": null, "errors": [{"message": "Resource not accessible"}]}'
    url = next(gen := serve(200, payload))
    try:
        monkeypatch.setattr(transport, "GRAPHQL", url)
        with pytest.raises(transport.TransportError) as caught:
            transport.graphql(
                "mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }", {}, "t"
            )
        assert "Resource not accessible" in str(caught.value)
        assert "отвергнут площадкой" in str(caught.value)
    finally:
        next(gen, None)


def test_neither_data_nor_errors_is_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ни данных, ни ошибок — форма ответа изменилась, и это не «чисто»."""
    url = next(gen := serve(200, b'{"whatever": 1}'))
    try:
        monkeypatch.setattr(transport, "GRAPHQL", url)
        with pytest.raises(transport.TransportError) as caught:
            transport.graphql(
                "mutation { disablePullRequestAutoMerge(input: {}) { clientMutationId } }", {}, "t"
            )
        assert "читать нечего" in str(caught.value)
    finally:
        next(gen, None)


def test_the_data_comes_back_unwrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Удача отдаёт `data` — обёртку разбирает дверь, а не каждый механизм."""
    payload = b'{"data": {"enablePullRequestAutoMerge": {"pullRequest": {"number": 7}}}}'
    url = next(gen := serve(200, payload))
    try:
        monkeypatch.setattr(transport, "GRAPHQL", url)
        got = transport.graphql(
            "mutation { enablePullRequestAutoMerge(input: {}) { pullRequest { number } } }",
            {},
            "t",
        )
        assert got["enablePullRequestAutoMerge"]["pullRequest"]["number"] == 7
    finally:
        next(gen, None)
