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

ПРЕДМЕТ НАЗЫВАЕТ ЧЕЛОВЕК, А НЕ ВЫБИРАЕТ ЗАХОД. Прежде шаг обходил живые
изменения и брал первое подходящее — то есть трогал ЧУЖУЮ работу, выбранную за
владельца порядком ответа площадки. Нашёл внешний взгляд на #231 (`47c0b03`,
`5d076a7`). Теперь номер приходит входом кнопки, а заход лишь проверяет, что
названное слить нельзя.

ЕСЛИ ЗАХОД УМРЁТ МЕЖДУ ВЗВЕДЕНИЕМ И СНЯТИЕМ, значок снимет ОЧЕРЕДЬ: шаг 8
держит взведённой ровно одну голову и снимает всё прочее — брошенное замером в
том числе. Это и есть терминальный выход из промежуточного состояния
([109](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/109-every-exit-from-a-transient-state-must-be-terminal.md)),
и он не зависит от того, дочитал ли упавший заход свой ответ.

ПРЕДМЕТ ЗАМЕРА — ИЗМЕНЕНИЕ, КОТОРОЕ СЛИТЬ НЕЛЬЗЯ. Между взведением и снятием
проходят миллисекунды, но окно всё же есть, и брать под замер готовое к
слиянию значило бы рисковать чужой работой. Поэтому предмет выбирается из
состояний, в которых площадка слить не может ВООБЩЕ, и выбирается по старшинству
(:data:`UNMERGEABLE`): конфликтное надёжнее закрытого проверками.

ЗАМЕР 12.09.2026 ПОКАЗАЛ, ЧТО ОДНОГО СОСТОЯНИЯ МАЛО. Первый заход искал только
``blocked`` — и не нашёл ничего: живых изменений было два, одно конфликтное
(``dirty``), другое отставшее (``behind``). Шаг сказал «предмета нет» вместо
того, чтобы взять конфликтное, потому что шапка утверждала «конфликтное мутация
отвергает сама». Премиса не проверялась
([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)),
и проверяет её теперь сам заход: отказ площадки приходит её словами в задачу.

``behind`` в список НЕ входит намеренно. Отставшее площадка сливать умеет — она
сама подтянет базу и сольёт, как только проверки позеленеют, — и это ровно тот
риск, которого замер избегает. Мало предмета лучше, чем слитая без спроса чужая
работа.

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

#: Состояния, годные под замер, ПО СТАРШИНСТВУ. Общее у них одно: площадка
#: такое изменение слить не может, и потому не сольёт в зазоре между взведением
#: и снятием. Порядок — от самого безопасного:
#:
#: * ``dirty`` — конфликт. Слить нечем до правки руками: риск нулевой.
#: * ``blocked`` — обязательные проверки не пройдены. Слить нельзя, пока они
#:   красные или не шли, а позеленеть за миллисекунды зазора им нечем.
#:
#: ``behind`` здесь отсутствует НЕ по забывчивости: отставшее площадка умеет
#: подтянуть и слить сама, и это тот самый риск, от которого весь отбор.
UNMERGEABLE: Final = ("dirty", "blocked")

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


def subject(repo: str, number: int, token: str) -> dict[str, Any]:
    """Названное изменение, годное под замер; иначе отказ с причиной.

    Проверяются два условия, и оба — про безопасность чужой работы: изменение
    не черновик и площадка слить его НЕ МОЖЕТ. Всё остальное она сольёт в
    зазоре между взведением и снятием, и замер стал бы слиянием без спроса.
    """
    full = ghrest.request("GET", f"repos/{repo}/pulls/{number}", token) or {}
    if not full:
        raise NotRun(f"#{number}: изменения нет — предмет замера не найден (075)")
    if full.get("draft"):
        raise NotRun(f"#{number}: черновик, и мутация отвергнет его сама — замер не о том")
    state = str(full.get("mergeable_state") or "")
    if state not in UNMERGEABLE:
        raise NotRun(
            f"#{number}: состояние «{state or '—'}» под замер не годится — годны только "
            f"{' и '.join(UNMERGEABLE)}, потому что их площадка слить не может. Остальное "
            "она сольёт между взведением и снятием (075)"
        )
    return full


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


def probe(repo: str, number: int, token: str, *, dry_run: bool) -> str:
    """Взводит НАЗВАННОЕ изменение и сразу снимает; отдаёт ответ о теле."""
    change = subject(repo, number, token)
    node = str(change.get("node_id") or "")
    state = str(change.get("mergeable_state") or "")
    headline = f"замер взведения: тело передано явно (#{number})"
    body = "Разобрано: замер\nClaude-Session: проверка полей commitHeadline и commitBody"
    if dry_run:
        return f"(пробный заход) взвёл бы #{number} — состояние «{state}» — и сразу снял"
    answer = arm(node, headline, body, token)
    try:
        missing = kept_the_body(answer, headline, body)
    finally:
        # Снятие идёт ВСЕГДА, даже если разбор ответа упал: взведённое
        # изменение площадка сольёт сама, как только проверки позеленеют.
        disarm(node, token)
    if missing:
        return (
            f"#{number} («{state}»): взведение принято, а ТЕЛО НЕТ — {'; '.join(missing)}. "
            "Условие пересмотра решения 011 наступило"
        )
    return (
        f"#{number} («{state}»): взведение принято ВМЕСТЕ с телом — площадка вернула "
        "и заголовок, "
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
    parser.add_argument("--pr", type=int, default=0, help="номер изменения под замер")
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
        if not args.pr:
            raise NotRun(
                "изменение не названо: --pr. Замер трогает ЧУЖУЮ работу, и выбирать её за "
                "человека нечем — порядок ответа площадки решением не является (053)"
            )
        said = probe(args.repo, args.pr, token, dry_run=not args.apply)
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
