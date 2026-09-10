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
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any, Final

import report

API_ROOT: Final = "https://api.github.com"
API_VERSION: Final = "2022-11-28"
TIMEOUT: Final = 30
PER_PAGE: Final = 100

#: Останавливаться надо ДО нуля: на нуле операция уже брошена на середине, а
#: счётчик обращений продолжает расти. Значение — порог соседа, выведенный из
#: цены его самых дорогих операций; у нас запросы дешевле, но запас тот же.
QUOTA_FLOOR: Final = 600
ENV_QUOTA_FLOOR: Final = "GHREST_QUOTA_FLOOR"

#: Предупреждение печатается один раз на процесс: смысл в сигнале, а не в шуме
#: на каждый запрос пакетной операции.
_warned: set[str] = set()


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


class RateLimited(TransportError):
    """Квота исчерпана: повторять бессмысленно, надо ждать сброса.

    Отдельный род, а не текст отказа: это единственное состояние, в котором
    верный ответ — «подожди», а не «почини». Смешивать его с отказом по правам
    значит советовать чинить то, что чинится временем.

    Замер соседа, из-за которого это выделено: ``used=10 435`` при лимите 5000 —
    окна обращались и после нуля, а счётчик рос, отдаляя сброс.
    """

    def __init__(self, message: str, *, reset_at: int = 0, resource: str = "core") -> None:
        super().__init__(message)
        self.reset_at = reset_at
        self.resource = resource

    def wait_seconds(self, *, now: float | None = None) -> int:
        """Сколько секунд осталось до сброса квоты (0 — уже можно)."""
        moment = time.time() if now is None else now
        return max(0, int(self.reset_at - moment))

    def describe(self, *, now: float | None = None) -> str:
        """Человеческая строка: что исчерпано и когда отпустит."""
        seconds = self.wait_seconds(now=now)
        when = time.strftime("%H:%M:%S", time.localtime(self.reset_at)) if self.reset_at else "?"
        return (
            f"квота площадки ({self.resource}) исчерпана — сброс в {when}, "
            f"через {seconds // 60} мин {seconds % 60} с. Ждать, а не повторять: "
            "счётчик обращений растёт и после нуля"
        )


def token_from_env() -> str:
    """Токен из окружения прогона; пусто — если его нет."""
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


def _url(path: str) -> str:
    """Достраивает адрес: принимает и путь от корня API, и полный URL."""
    if path.startswith(("http://", "https://")):
        return path
    return f"{API_ROOT}/{path.lstrip('/')}"


def quota_floor() -> int:
    """Порог остатка, ниже которого длинную операцию начинать нечего."""
    raw = os.environ.get(ENV_QUOTA_FLOOR, "")
    try:
        return int(raw) if raw else QUOTA_FLOOR
    except ValueError:
        return QUOTA_FLOOR


def _quota_from(headers: Any) -> tuple[int | None, int, str]:
    """Остаток, время сброса и ресурс — из заголовков ответа (бесплатно)."""
    if headers is None:
        return None, 0, "core"

    def number(name: str) -> int:
        try:
            return int(headers.get(name) or 0)
        except (TypeError, ValueError):
            return 0

    raw = headers.get("x-ratelimit-remaining")
    remaining = None if raw is None else number("x-ratelimit-remaining")
    return remaining, number("x-ratelimit-reset"), headers.get("x-ratelimit-resource") or "core"


def _note_quota(headers: Any) -> None:
    """Предупреждает о низком остатке — один раз на ресурс за процесс."""
    remaining, reset, resource = _quota_from(headers)
    if remaining is None or remaining > quota_floor() or resource in _warned:
        return
    _warned.add(resource)
    when = time.strftime("%H:%M:%S", time.localtime(reset)) if reset else "?"
    print(
        f"ВНИМАНИЕ: квота площадки ({resource}) на исходе — осталось {remaining} "
        f"при пороге {quota_floor()}, сброс в {when}. Длинную операцию лучше не "
        "начинать: брошенная на середине дороже отложенной.",
        file=sys.stderr,
    )


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
            _note_quota(response.headers)
            payload = response.read()
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        # Тело читается ОДИН раз и ДО разбора: поток одноразовый, а именно в нём
        # приходит настоящая причина отказа.
        detail = report.cut(exc.read().decode(errors="replace"))
        remaining, reset, resource = _quota_from(exc.headers)
        retry_after = exc.headers.get("retry-after") if exc.headers else None
        # Квота — ТОЛЬКО когда площадка о ней сказала: остаток равен нулю либо
        # пришёл retry-after. Отсутствие заголовков означает «причина другая», и
        # советовать ждать сброса там, где ждать нечего, хуже, чем молчать.
        if exc.code in (403, 429) and (remaining == 0 or retry_after):
            reset_at = reset
            if not reset_at and retry_after:
                try:
                    reset_at = int(time.time()) + int(retry_after)
                except (TypeError, ValueError):
                    reset_at = 0
            raise RateLimited(
                f"{method} {path} → лимит исчерпан", reset_at=reset_at, resource=resource
            ) from exc
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


def raw_json(url: str, timeout: int = 30) -> dict[str, Any]:
    """Читает ЧУЖОЙ снимок по прямой ссылке: не API площадки, но тот же транспорт.

    Отдельный вход, а не `request`: у снимка нет ни токена, ни квоты, ни
    страниц — это статический файл, который сосед собрал своим прогоном. А
    место одно, потому что второй транспорт вырастает не файлом, а фразой «мне
    нужен всего один запрос»: у соседей так и выросли 2436 строк против 131
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

    Отказ — исключение, а не пустой словарь: пустой снимок читался бы как
    «ничего не изменилось», то есть тихий запасной ответ на месте поломки (045).
    """
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            snapshot = json.loads(answer.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise TransportError(f"снимок не прочитан ({url}): {exc}") from exc
    if not isinstance(snapshot, dict):
        raise TransportError(f"снимок не словарь ({url}): читать нечего")
    return snapshot


#: Сколько последних закрытых изменений спрашивается за раз. Окно — не история:
#: механизмы, которые смотрят «что недавно слито», догоняют пропущенное событие,
#: а не переобходят прошлое. Значение одно на всех: разъехавшиеся окна означали
#: бы, что три механизма по-разному понимают слово «недавно»
#: ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
MERGED_WINDOW: Final = 30


def merged_changes(repo: str, token: str, limit: int = MERGED_WINDOW) -> list[dict[str, Any]]:
    """Последние СЛИТЫЕ изменения: закрытые без слияния сюда не попадают.

    Копий этого запроса было три — у реестра непросмотренного, у находок и у
    отметки пунктов, — и отличались они только окном, причём разница нигде не
    объяснялась. Разбор слитого нашёл это в #109.
    """
    items = request("GET", f"repos/{repo}/pulls?state=closed&per_page={limit}", token) or []
    return [item for item in items if isinstance(item, dict) and item.get("merged_at")]


def quote(value: str) -> str:
    """Экранирует отрезок пути: имя метки может содержать что угодно."""
    return urllib.parse.quote(value, safe="")
