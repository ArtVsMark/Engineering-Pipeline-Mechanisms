#!/usr/bin/env python3
"""Несовместимый выпуск оповещает тех, кто взял наши шаги (#1387).

ШАГ 3 «НЕСОВМЕСТИМОГО ИЗМЕНЕНИЯ» (`docs/dev/release.md`). Выпуск поднимает
мажор контракта, и каждому, кто зовёт наши шаги по тегу, уходит входящее «A→B,
перечитай ответы» с перечнем изменившегося. До этого шаг держался ничем:
объявленных потребителей не было, а зовущих молча оповещать было не о ком
узнать.

АДРЕСАТЫ — ВЗЯВШИЕ ПО ОБХОДУ СЕМЬИ, А НЕ ОБЪЯВЛЕННЫЕ (решение владельца
16.10.2026, #1387). Обход `family_uptake` клонирует прогоны соседей и
застаёт вызов наших шагов по тегу; объявившийся в `connected` — частный случай
того же. Второго обхода здесь нет: список семьи, клон и признак «взял» —
`family_uptake` целиком (022).

ПОВОД — ТОЛЬКО МАЖОР. Минор поверхности потребителю не враг: окно контракта в
его `.pipeline.yml` принимает свой минор, и подъём тега покраснит сам, если
ответы пора перечитать. Мажор ломает подключение, и о нём говорится заранее.

ЗАДАЧА В ЧУЖОМ РЕПОЗИТОРИИ — ТОКЕНОМ ВЛАДЕЛЬЦА (решение владельца 16.10.2026).
Проекты семьи — его, и задачу открывает он, а не приложение (131). Повтор не
открывает второй: задача узнаётся по маркеру выпуска среди задач владельца
токена в том репозитории, открытых и закрытых, — закрытая значит «прочитано».

СПЕРВА СПРОСИЛИ СЕМЬЮ (162): ни у кого нет. Замер 18.10.2026 по клонам каталога
и Usage-Token — оповещения соседей о несовместимом выпуске нет ни у того, ни у
другого; свой механизм, на обходе `family_uptake`.

ГРАНИЦЫ, И ОНИ НАЗВАНЫ.

* Сосед вне выгрузки семьи каталога не оповещается: обход его не видит.
* Непрочитанный клон — не «не взял»: такой сосед назван поимённо, и исход
  частичный (045).
* Оповещает только поставщик. Шаг выпуска общий, и у потребителя этот заход
  отвечает «оповещать некого», а не шлёт его соседям наш мажор.

Исходы (правило 039): ``0`` оповещать не о чем или все оповещены · ``2`` не
отработал · ``3`` часть соседей не прочитана или не оповещена — названы.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Final

import build_changelog
import check_shipped
import family_uptake
import ghrest
import onboard
import paths
import release
import report
import version

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_PARTIAL: Final = 3

#: Имя маркера задачи-оповещения; за ним — тег выпуска.
NAME: Final = "breaking-notice"
#: Род фрагмента, объявившего правку поверхности.
CONTRACT: Final = "contract"
#: Сколько знаков чужого ответа называет отказ одного соседа.
SHOWN: Final = 200


class NotRun(RuntimeError):
    """Оповещение не отработало: третий исход, а не «оповещать не о чем»."""


def marker(tag: str) -> str:
    """Метка задачи-оповещения одного выпуска: по ней повтор узнаёт своё."""
    return f"<!-- {NAME}: {tag} -->"


def release_tags() -> list[str]:
    """Теги выпусков дерева по возрастанию номера, а не по дате."""
    tags = [
        one for one in release.git("tag", "--list", "v*").split() if version.is_release_tag(one)
    ]
    return sorted(tags, key=lambda tag: version.digits(version.bare(tag)))


def previous(tag: str, tags: list[str]) -> str | None:
    """Выпуск перед `tag`; первый выпуск предыдущего не имеет."""
    if tag not in tags:
        raise NotRun(f"тега выпуска {tag} в дереве нет — судить о мажоре не по чему (075)")
    at = tags.index(tag)
    return tags[at - 1] if at else None


def major(contract: str) -> int:
    """Мажор версии контракта — разбором `version.digits`, а не нарезкой (214)."""
    try:
        return version.digits(contract)[0]
    except version.NotRun as exc:
        raise NotRun(f"версия контракта: {exc}") from exc


def breaking(tag: str) -> tuple[str, str] | None:
    """Версии контракта до и после выпуска, если мажор вырос; иначе `None`."""
    before = previous(tag, release_tags())
    if before is None:
        return None
    try:
        was, now = release.contract_at(before), release.contract_at(tag)
    except release.NotRun as exc:
        raise NotRun(str(exc)) from exc
    return (was, now) if major(now) > major(was) else None


def changes(number: str) -> list[str]:
    """Заголовки фрагментов `contract` выпуска — что изменилось на поверхности.

    Фрагмент бывает и о нескольких правках, каждая под своим `### `: названы все.
    Фрагмент без заголовка назван своим именем, а не пропущен.
    """
    titles: list[str] = []
    for one in build_changelog.read_fragments(paths.RELEASED / number):
        if one.kind != CONTRACT:
            continue
        headings = [line[4:].strip() for line in one.body.splitlines() if line.startswith("### ")]
        titles += headings or [one.slug]
    return titles


def body_of(tag: str, was: str, now: str, took: family_uptake.Took, changed: list[str]) -> str:
    """Тело задачи-оповещения: переход, что зовёт сосед и что изменилось."""
    tree = f"https://github.com/{family_uptake.OURS}/blob/{tag}"
    lines = [
        marker(tag),
        "",
        f"Механизмы выпустили `{tag}`: версия контракта `{was}` → `{now}` — "
        "несовместимое изменение поверхности.",
        "",
        f"Ваш проект зовёт наши шаги {', '.join(f'`{one}`' for one in took.steps)} по тегу "
        f"{', '.join(f'`{one}`' for one in took.refs)}. Подъём на `{tag}` — "
        "это перечитать ответы `.pipeline.yml`, а не поднять число (157).",
        "",
        "Что изменилось на поверхности:",
        "",
    ]
    lines += [f"- {one}" for one in changed] or ["- записи рода `contract` в выпуске не найдены"]
    lines += [
        "",
        f"Записи выпуска — [`changelog.d/released/{version.bare(tag)}/`]"
        f"({tree}/changelog.d/released/{version.bare(tag)}); порядок перехода — "
        f"[`{paths.RELEASE_DOC}`]({tree}/{paths.RELEASE_DOC}), раздел «Несовместимое изменение».",
    ]
    return "\n".join(lines) + "\n"


def notified(repo: str, tag: str, token: str, login: str) -> bool:
    """Есть ли у соседа задача-оповещение этого выпуска — открытая или закрытая."""
    said = marker(tag)
    return any(
        said in str(one.get("body") or "")
        for one in ghrest.paginate(f"repos/{repo}/issues?state=all&creator={login}", token)
    )


def notify(repo: str, tag: str, body: str, token: str, login: str, *, dry_run: bool) -> str:
    """Открывает задачу у соседа, если её ещё нет. Отдаёт, что сделано.

    Без владельца токена «есть ли уже» не спросить: искать пришлось бы среди
    задач всех авторов. Это бывает только в пробном заходе, и тогда он так и
    говорит — боевой без владельца не начинается.
    """
    if login and notified(repo, tag, token, login):
        return f"{repo}: оповещение о {tag} уже есть — второго не заводим"
    title = f"Механизмы {tag}: несовместимый контракт — перечитать ответы"
    if dry_run:
        asked = "" if login else " (есть ли уже — не спрошено: токена нет)"
        return f"{report.DRY} {repo}: завелась бы задача «{title}»{asked}"
    created = ghrest.request("POST", f"repos/{repo}/issues", token, {"title": title, "body": body})
    number = created.get("number") if isinstance(created, dict) else None
    if number is None:
        raise ghrest.TransportError(f"площадка не назвала номер заведённой задачи: {created!r}")
    return f"{repo}: задача заведена #{number}"


def owner_of(token: str) -> str:
    """Логин владельца токена — у площадки; пустая строка — токена нет."""
    if not token:
        return ""
    said = ghrest.request("GET", "user", token)
    login = said.get("login") if isinstance(said, dict) else None
    if not isinstance(login, str) or not login:
        raise NotRun(f"площадка не назвала владельца токена — от чьего имени оповещать: {said!r}")
    return login


def main(argv: list[str] | None = None) -> int:
    """Точка входа: решает, есть ли повод, и оповещает взявших наши шаги."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="тег выпуска, vX.Y.Z")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--apply", action="store_true", help="завести задачи, а не показать")
    args = parser.parse_args(argv)
    report.announce(not args.apply)
    if args.repo.casefold() != family_uptake.OURS.casefold():
        here = args.repo or "?"
        print(f"оповещает поставщик ({family_uptake.OURS}); здесь {here} — оповещать некого")
        return EXIT_OK
    try:
        jump = breaking(args.tag)
        if jump is None:
            print(f"мажор контракта на {args.tag} не вырос — оповещать не о чем")
            return EXIT_OK
        was, now = jump
        changed = changes(version.bare(args.tag))
        offered = onboard.steps(Path())
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            seen, unread = family_uptake.sweep(family_uptake.family(), Path(tmp))
        took = family_uptake.takers(seen, offered)
        token = ghrest.token_from_env()
        if args.apply and not token:
            raise NotRun("токена нет — завести задачи соседям нечем")
        login = owner_of(token)
    except (
        NotRun,
        release.NotRun,
        build_changelog.NotRun,
        check_shipped.NotRun,
        family_uptake.NotRun,
        ghrest.TransportError,
    ) as exc:
        print(f"оповещение не отработало: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN
    print(f"контракт {was} → {now}: взяли наши шаги {len(took)} из {len(seen)} прочитанных")
    failed: list[str] = []
    for one in took:
        try:
            print(
                notify(
                    one.repo,
                    args.tag,
                    body_of(args.tag, was, now, one, changed),
                    token,
                    login,
                    dry_run=not args.apply,
                )
            )
        except ghrest.TransportError as exc:
            print(
                f"::warning::{one.repo}: не оповещён — {report.cut(str(exc), SHOWN)}",
                file=sys.stderr,
            )
            failed.append(one.repo)
    if unread or failed:
        print(f"не прочитаны: {', '.join(unread) or '—'}; не оповещены: {', '.join(failed) or '—'}")
        return EXIT_PARTIAL
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
