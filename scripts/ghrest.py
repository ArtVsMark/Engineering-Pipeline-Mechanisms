"""Транспорт к площадке: REST одним модулем, а не копией в каждом механизме.

ПОЧЕМУ ЭТО ПЕРВЫЙ ОБЩИЙ МЕХАНИЗМ. Он самый дешёвый и самый ценный: у пяти
проектов семьи один и тот же `gh_rest.py` разошёлся от 131 строки до 2436, и
ни одна пара копий не совпала. Начинать сведение надо с дома — здесь копий
было **пять**, с четырьмя разными сигнатурами и четырьмя разными разборами
отказа. Общий помощник поднимают вверх, а не тянут вбок
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ПОЧЕМУ REST, А НЕ GRAPHQL. Самый дешёвый транспорт из доступных, и цена
операции проверяется до того, как на ней построен конвейер
([001](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/001-transport-rest-not-graphql.md)).
У соседа исчерпание квоты GraphQL однажды уронило дежурного и заморозило
очередь целиком.

ПОЧЕМУ СТАНДАРТНАЯ БИБЛИОТЕКА. Прогон не ставит зависимостей ради шести
запросов, а `gh` есть не везде: в агентском окне его нет вовсе.

ОТКАЗ РАЗБИРАЕТСЯ ЗДЕСЬ, А НЕ У КАЖДОГО. Пять копий разбирали его по-разному, и
истёкший токен в одном месте выглядел как «не настроено», а в другом — как
поломка. Теперь у отказа один разбор и один текст.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any, Final

API_ROOT: Final = "https://api.github.com"
API_VERSION: Final = "2022-11-28"
TIMEOUT: Final = 30
PER_PAGE: Final = 100


class TransportError(RuntimeError):
    """Запрос не отработал: сеть, отказ площадки или неразбираемый ответ.

    Механизмы ловят это и превращают в свой третий исход: транспорт не знает,
    что для зовущего значит отказ, и решать за него не должен.
    """


class NotFound(TransportError):
    """Площадка ответила «нет такого».

    Отдельный класс, потому что для части механизмов это не отказ, а ответ:
    защиты ветки может не быть, живой задачи может не существовать.
    """


def token_from_env() -> str:
    """Токен из окружения прогона; пусто — если его нет."""
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


def _url(path: str) -> str:
    """Достраивает адрес: принимает и путь от корня API, и полный URL."""
    if path.startswith(("http://", "https://")):
        return path
    return f"{API_ROOT}/{path.lstrip('/')}"


def request(
    method: str,
    path: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> Any:
    """Один запрос к площадке. Отдаёт разобранный ответ или None на пустой.

    Отказ по учётным данным называется отдельно: истёкший токен и незаданный
    выглядят снаружи одинаково — «перестало работать», — и если их не
    различить, искать будут в механизме, а искать надо в сроке секрета.
    """
    data = json.dumps(body).encode() if body is not None else None
    prepared = urllib.request.Request(_url(path), data=data, method=method)
    prepared.add_header("Authorization", f"Bearer {token}")
    prepared.add_header("Accept", "application/vnd.github+json")
    prepared.add_header("X-GitHub-Api-Version", API_VERSION)
    if data is not None:
        prepared.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(prepared, timeout=TIMEOUT) as response:
            payload = response.read()
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        if exc.code == 404:
            raise NotFound(f"{method} {path} → 404: {detail}") from exc
        if exc.code in (401, 403):
            raise TransportError(
                f"{method} {path} → {exc.code}: токен задан, но площадка его отвергла. "
                "Обычно это истёкший или отозванный секрет, либо у него нет нужных "
                f"прав на этот репозиторий. Ответ площадки: {detail}"
            ) from exc
        raise TransportError(f"{method} {path} → {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise TransportError(f"{method} {path} → площадка недоступна: {exc.reason}") from exc
    except ValueError as exc:
        raise TransportError(f"{method} {path} → ответ не разобран: {exc}") from exc


def paginate(path: str, token: str, key: str | None = None) -> Iterator[dict[str, Any]]:
    """Идёт по страницам, пока они есть, и отдаёт записи по одной.

    Цикл со счётчиком страниц был переписан в трёх механизмах, и каждый раз
    заново: остановка по короткой странице — то место, где легко ошибиться и
    получить бесконечный обход или потерянный хвост.

    ``key`` — имя поля, если площадка кладёт список внутрь объекта
    (например, ``check_runs``).
    """
    page = 1
    separator = "&" if "?" in path else "?"
    while True:
        payload = request("GET", f"{path}{separator}per_page={PER_PAGE}&page={page}", token)
        chunk = payload.get(key, []) if key else payload
        if not chunk:
            return
        yield from chunk
        if len(chunk) < PER_PAGE:
            return
        page += 1


def quote(value: str) -> str:
    """Экранирует отрезок пути: имя метки может содержать что угодно."""
    return urllib.parse.quote(value, safe="")
