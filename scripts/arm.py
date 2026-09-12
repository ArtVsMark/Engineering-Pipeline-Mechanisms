#!/usr/bin/env python3
"""Взведение слияния у площадки: одна мутация, одна обратная и один замер.

ЧТО ЭТО ЗА ШАГ. Решение
`docs/decisions/011-merging-is-handed-to-the-platform.md` отдаёт площадке само
слияние: очередь решает, КОГО взвести, а ждёт зелёного и сливает площадка.
Порядок вставки остаётся нашим целиком — отдаётся только последнее действие.

ПЕРЕД ДОВЕРИЕМ — ЗАМЕР, И ОН ЗДЕСЬ ЖЕ. Решение назвало непроверенным ровно
одно: принимает ли мутация ТЕЛО уплотнения (``commitHeadline`` и
``commitBody``). Поля объявлены её входом, но в семье их не передаёт никто —
значит проверено это не было, а на непроверенной премисе смена уже трижды
ловила себя
([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
Режим ``--probe`` взводит и СРАЗУ снимает, ничего не сливая, и пишет ответ
площадки туда, где его прочтёт человек.

ПРЕДМЕТ ЗАМЕРА — ИЗМЕНЕНИЕ, КОТОРОЕ ВЗВЕСТИ МОЖНО, А СЛИТЬ НЕЛЬЗЯ. Между
взведением и снятием проходят миллисекунды, но окно всё же есть, и брать под
замер готовое к слиянию значило бы рисковать чужой работой. Состояние
``blocked`` даёт ровно то, что нужно: мутация его принимает, а площадка не
сольёт — обязательные проверки не пройдены. Конфликтное (``dirty``) и черновик
мутация отвергает сама, и это тоже ответ, но не про тело.

ТОКЕН — ВЛАДЕЛЬЦА. Взведение это запись, несущая личность: на токене прогона
слияние в общей ветке подписало бы приложение
([131](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/131-no-writes-from-a-cloud-session.md)).

Исходы (правило 039): ``0`` заход отработал · ``2`` шаг не отработал ·
``3`` не настроено — нет токена владельца.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Final

import ghrest
import report

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_UNSET: Final = 3

#: Токен владельца — тот же, что у очереди. Имя общее намеренно: два имени для
#: одного секрета разошлись бы при первой же смене.
ENV_TOKEN: Final = "MERGE_QUEUE_TOKEN"

#: Способ слияния. Уплотнение, и это решение, а не умолчание:
#: `docs/decisions/006-merge-by-squash.md`.
METHOD: Final = "SQUASH"

#: Состояние, годное под замер: взвести можно, слить нельзя.
ARMABLE_UNMERGEABLE: Final = "blocked"

ARM: Final = """
mutation($id: ID!, $method: PullRequestMergeMethod!, $headline: String!, $body: String!) {
  enablePullRequestAutoMerge(
    input: {
      pullRequestId: $id
      mergeMethod: $method
      commitHeadline: $headline
      commitBody: $body
    }
  ) {
    pullRequest { number autoMergeRequest { enabledAt commitHeadline commitBody } }
  }
}
"""
"""Взведение с ТЕЛОМ. Ответ просят вернуть тело обратно: так видно, принято
оно или проглочено молча — разница между «поля есть» и «поля работают»."""

DISARM: Final = """
mutation($id: ID!) {
  disablePullRequestAutoMerge(input: {pullRequestId: $id}) {
    pullRequest { number autoMergeRequest { enabledAt } }
  }
}
"""
"""Обратная. Без неё согласие нельзя отозвать, а согласие без отзыва — не
согласие (126): заморозка обязана снимать взведение, а не только не выдавать
новое."""


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «взводить некого»."""


def armable(repo: str, token: str) -> dict[str, Any] | None:
    """Живое изменение, которое взвести можно, а слить нельзя; иначе ``None``."""
    for payload in ghrest.paginate(f"repos/{repo}/pulls?state=open", token):
        number = int(payload.get("number") or 0)
        if not number or payload.get("draft"):
            continue
        full = ghrest.request("GET", f"repos/{repo}/pulls/{number}", token) or {}
        if str(full.get("mergeable_state") or "") == ARMABLE_UNMERGEABLE:
            return full
    return None


def arm(node: str, headline: str, body: str, token: str) -> dict[str, Any]:
    """Взводит слияние у площадки и отдаёт, что она ответила про тело."""
    data = ghrest.graphql(
        ARM, {"id": node, "method": METHOD, "headline": headline, "body": body}, token
    )
    request = (data.get("enablePullRequestAutoMerge") or {}).get("pullRequest") or {}
    return dict(request.get("autoMergeRequest") or {})


def disarm(node: str, token: str) -> None:
    """Снимает взведение. Отказ здесь громкий: взведённое обязано быть снято."""
    ghrest.graphql(DISARM, {"id": node}, token)


def kept_the_body(answer: dict[str, Any], headline: str, body: str) -> list[str]:
    """Чего площадка НЕ сохранила из переданного тела.

    Пустой список — тело принято целиком. Непустой — поля объявлены входом, но
    не работают, и решение 011 пересматривается по названному в нём условию.
    """
    missing: list[str] = []
    if str(answer.get("commitHeadline") or "") != headline:
        missing.append(f"commitHeadline: отдано «{answer.get('commitHeadline')}»")
    if str(answer.get("commitBody") or "") != body:
        missing.append(f"commitBody: отдано «{answer.get('commitBody')}»")
    return missing


def probe(repo: str, token: str, *, dry_run: bool) -> str:
    """Взводит и сразу снимает; отдаёт человеческий ответ о теле."""
    change = armable(repo, token)
    if change is None:
        raise NotRun(
            f"изменения в состоянии «{ARMABLE_UNMERGEABLE}» нет — предмета замера не найдено. "
            "Готовое к слиянию под замер не берётся: площадка сольёт его между взведением и "
            "снятием (075)"
        )
    number = int(change["number"])
    node = str(change.get("node_id") or "")
    headline = f"замер взведения: тело передано явно (#{number})"
    body = "Разобрано: замер\nClaude-Session: проверка полей commitHeadline и commitBody"
    if dry_run:
        return f"(пробный заход) взвёл бы #{number} и сразу снял"
    answer = arm(node, headline, body, token)
    try:
        missing = kept_the_body(answer, headline, body)
    finally:
        # Снятие идёт ВСЕГДА, даже если разбор ответа упал: взведённое
        # изменение площадка сольёт сама, как только проверки позеленеют.
        disarm(node, token)
    if missing:
        return (
            f"#{number}: взведение принято, а ТЕЛО НЕТ — {'; '.join(missing)}. "
            "Условие пересмотра решения 011 наступило"
        )
    return (
        f"#{number}: взведение принято ВМЕСТЕ с телом — площадка вернула и заголовок, "
        "и тело дословно. Решение 011 строится на проверенном"
    )


def say(repo: str, task: str, said: str, token: str) -> None:
    """Пишет ответ замера туда, где его прочтёт человек.

    ЭТО НЕ ПОБОЧНЫЙ КАНАЛ, А САМ ЗАМЕР. Логи прогонов окну недоступны — прокси
    режет хранилище, — и ответ, оставшийся только в логе, не прочтёт никто.
    Поэтому отказ записи делает заход неотработавшим, а не «почти удачей»
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    ghrest.request(
        "POST",
        f"repos/{repo}/issues/{task}/comments",
        token,
        {"body": f"## Замер взведения\n\n{said}\n"},
    )


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает ответ площадки и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--probe", action="store_true", help="взвести и сразу снять — замер")
    parser.add_argument("--apply", action="store_true", help="делать, а не показывать")
    parser.add_argument("--say-to", default="", help="номер задачи, куда записать ответ замера")
    args = parser.parse_args(argv)

    token = os.environ.get(ENV_TOKEN, "") or ""
    if not token:
        print(f"не настроено: нет {ENV_TOKEN} — взводить нечем", file=sys.stderr)
        return EXIT_UNSET

    code = EXIT_OK
    try:
        if not args.repo:
            raise NotRun("репозиторий не назван: --repo или GITHUB_REPOSITORY")
        if not args.probe:
            raise NotRun("предмет не назван: пока у шага есть только --probe")
        said = probe(args.repo, token, dry_run=not args.apply)
        print(said)
    except (NotRun, ghrest.TransportError) as exc:
        said = f"замер не отработал: {report.cut(str(exc))}"
        print(said, file=sys.stderr)
        code = EXIT_BROKEN

    # ОТКАЗ ЗАМЕРА ТОЖЕ ЗАПИСЫВАЕТСЯ. «Не отработал» — такой же ответ на вопрос
    # решения 011, как и «тело принято»: молчание же неотличимо от «не
    # запускали» (154).
    if args.say_to.isdigit() and args.apply:
        try:
            say(args.repo, args.say_to, said, token)
        except ghrest.TransportError as exc:
            print(f"ответ замера не записан: {report.cut(str(exc))}", file=sys.stderr)
            code = EXIT_BROKEN
    return code


if __name__ == "__main__":
    raise SystemExit(main())
