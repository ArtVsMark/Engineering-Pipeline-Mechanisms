#!/usr/bin/env python3
"""Выпуск, сменивший контракт, оповещает тех, кого смена касается (#1387, #1586).

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

ПОВОД — МАЖОР ВСЕГДА, МИНОР — ВНЕ ОКНА (#1586, решение владельца 23.10.2026).
Мажор ломает подключение, и о нём говорится каждому взявшему. Минор касается
только того, чьё окно `contract:` в `.pipeline.yml` нового минора не покрывает:
окно прибито к минору выпуска (`docs/use/onboarding.md`), и следующий минор
приносит джоб, по которому нужен его ответ. Чьё окно минор покрывает — тому
перечитывать нечего, и он не оповещается.

АДРЕСАТЫ МИНОРА — ВЗЯВШИЕ И ОБЪЯВЛЕННЫЕ. К обходу семьи добавляется реестр
`.rules/consumers.json`, читатель у него один — `consumers.py`. Окно взявшего
застаёт обход в его клоне; окно объявившегося, которого обход не застал, —
`consumers.answer_of` у площадки. Окно не прочитано — не «покрывает»: такой
назван, и исход частичный (045). Прочитано, но не объявлено или не разобрано —
состояние соседа, повтор хвоста его не исправит: сосед оповещается, и тело
просит объявить окно (взгляд на #1591). У мажора адресаты прежние:
тело называет позванные шаги, а у объявленного без обхода их не знает никто.

ПРОБНЫЙ ЗАХОД ДО ВЫПУСКА — `--to X.Y.Z`. Тег ещё не поставлен, и версия «после»
называется словом: «до» — контракт последнего выпуска дерева. Боевой заход с
`--to` не начинается: писать соседям о невыпущенном нечем проверить.

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
* Сосед, не объявившийся и не застанный обходом, о миноре не узнает: адреса нет.
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
import consumers
import family_uptake
import ghrest
import main_guard
import onboard
import paths
import pipeline_checks
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


def jump(tag: str) -> tuple[str, str] | None:
    """Версии контракта до и после выпуска, если вырос мажор или минор; иначе `None`.

    Патч поверхности не трогает по построению (`pipeline_checks.compatible`
    сравнивает MAJOR.MINOR), и о нём не говорится.
    """
    before = previous(tag, release_tags())
    if before is None:
        return None
    try:
        was, now = release.contract_at(before), release.contract_at(tag)
    except release.NotRun as exc:
        raise NotRun(str(exc)) from exc
    return grown(was, now)


def grown(was: str, now: str) -> tuple[str, str] | None:
    """`(was, now)`, если MAJOR.MINOR вырос; иначе `None`. Разбор — `version.digits` (214)."""
    try:
        before, after = version.digits(was)[:2], version.digits(now)[:2]
    except version.NotRun as exc:
        raise NotRun(f"версия контракта: {exc}") from exc
    return (was, now) if after > before else None


def breaking(tag: str) -> tuple[str, str] | None:
    """Версии контракта до и после выпуска, если мажор вырос; иначе `None`."""
    moved = jump(tag)
    return moved if moved and major(moved[1]) > major(moved[0]) else None


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


def minor_body_of(
    tag: str, was: str, now: str, span: str | None, changed: list[str], why: str = ""
) -> str:
    """Тело оповещения о миноре: переход, окно соседа, которое его не покрывает, и изменившееся.

    Окна нет (`span` — `None`) или оно не разобрано (`why`) — тело так и говорит:
    судить о покрытии может только сосед, объявив окно.
    """
    if span is None or why:
        window = (
            f"Окно `contract:` в вашем `.pipeline.yml` {why or 'не объявлено'} — "
            f"покрывает ли оно `{now}`, судить нечем. Объявите окно вида "
            '`">=X.Y,<A.B"`: тогда о миноре внутри него оповещений не будет.'
        )
    else:
        window = f'Окно `contract: "{span}"` в вашем `.pipeline.yml` версию `{now}` не покрывает.'

    tree = f"https://github.com/{family_uptake.OURS}/blob/{tag}"
    lines = [
        marker(tag),
        "",
        f"Механизмы выпустили `{tag}`: версия контракта `{was}` → `{now}`.",
        "",
        f"{window} "
        "Новый минор приносит то, по чему нужен ваш ответ: подъём тега — это "
        "перечитать ответы и сдвинуть окно, а не поднять число (157).",
        "",
        "Что изменилось на поверхности:",
        "",
    ]
    lines += [f"- {one}" for one in changed] or ["- записи рода `contract` в выпуске не найдены"]
    lines += [
        "",
        f"Записи выпуска — [`changelog.d/released/{version.bare(tag)}/`]"
        f"({tree}/changelog.d/released/{version.bare(tag)}); окно контракта — "
        f"[`docs/use/onboarding.md`]({tree}/docs/use/onboarding.md).",
    ]
    return "\n".join(lines) + "\n"


def addressees(took: list[family_uptake.Took], declared: list[str]) -> list[family_uptake.Took]:
    """Взявшие и объявленные — один раз каждый, без учёта регистра имени.

    Объявленный, которого обход не застал, идёт без окна: его окно читается
    у площадки (`window_of`). Первое написание имени остаётся.
    """
    seen = {one.repo.casefold() for one in took}
    extra = []
    for repo in declared:
        if repo.casefold() not in seen:
            seen.add(repo.casefold())
            extra.append(family_uptake.Took(repo))
    return [*took, *extra]


def window_of(one: family_uptake.Took, token: str) -> str | None:
    """Окно `contract:` соседа: из обхода, иначе из его дерева у площадки.

    Не прочитано — `NotRun` с причиной: «окна не видно» не значит «покрывает»,
    и повтор хвоста может его прочитать. Прочитано, но окна нет — `None`: это
    состояние соседа, повтором его не исправить, и сосед оповещается (взгляд
    на #1591). ТОТ ЖЕ КЛАСС — НА УРОВНЕ ФАЙЛА: `.pipeline.yml` нет у соседа
    (`NotFound`) или он не разбирается (`BadAnswer`) — тоже его состояние, и
    без оповещения шаг выпуска краснел бы на каждом миноре (взгляд на #1591,
    195).

    404 НА ФАЙЛ — ЕЩЁ НЕ «ФАЙЛА НЕТ». Площадка отдаёт его и на репозиторий,
    закрытый для токена или удалённый: тогда это сбой доступа, а не состояние
    соседа, и оповещать некого. Различает второй запрос — к самому
    репозиторию (`seen`): виден он — файла нет; не виден — `NotRun`.
    """
    if one.span:
        return one.span
    if not token:
        raise NotRun("окно не прочитано: обход его не застал, а токена площадки нет")
    try:
        span = consumers.answer_of(one.repo, token).get("contract")
    except ghrest.NotFound:
        seen(one.repo, token)
        return None
    except consumers.BadAnswer:
        return None
    except (consumers.NotRun, ghrest.TransportError, ValueError) as exc:
        # ValueError — битый base64 или не UTF-8 в чужом файле: тоже «не прочитано» (039).
        raise NotRun(f"окно не прочитано: {exc}") from exc
    return str(span) if span else None


def seen(repo: str, token: str) -> None:
    """Виден ли токену сам репозиторий соседа; не виден — `NotRun`, а не «файла нет»."""
    try:
        ghrest.request("GET", f"repos/{repo}", token)
    except ghrest.NotFound as exc:
        raise NotRun(
            f"окно не прочитано: {repo} не виден токену — закрыт или удалён, а не без файла"
        ) from exc
    except ghrest.TransportError as exc:
        raise NotRun(f"окно не прочитано: {exc}") from exc


def covers(span: str, now: str) -> bool:
    """Покрывает ли окно соседа новую версию; неразборное окно — `NotRun`, а не «нет»."""
    try:
        return pipeline_checks.compatible(span, now)
    except pipeline_checks.BadPolicy as exc:
        raise NotRun(f"окно «{span}» не разобрано: {exc}") from exc


def notified(repo: str, tag: str, token: str, login: str) -> bool:
    """Есть ли у соседа задача-оповещение этого выпуска — открытая или закрытая."""
    said = marker(tag)
    return any(
        said in str(one.get("body") or "")
        for one in ghrest.paginate(f"repos/{repo}/issues?state=all&creator={login}", token)
    )


def notify(
    repo: str,
    tag: str,
    body: str,
    token: str,
    login: str,
    *,
    dry_run: bool,
    title: str = "",
) -> str:
    """Открывает задачу у соседа, если её ещё нет. Отдаёт, что сделано.

    Без владельца токена «есть ли уже» не спросить: искать пришлось бы среди
    задач всех авторов. Это бывает только в пробном заходе, и тогда он так и
    говорит — боевой без владельца не начинается.
    """
    if login and notified(repo, tag, token, login):
        return f"{repo}: оповещение о {tag} уже есть — второго не заводим"
    title = title or f"Механизмы {tag}: несовместимый контракт — перечитать ответы"
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


def asked_owner(token: str) -> str:
    """Владелец токена для ПРОБНОГО захода; не назван — пустая строка и слово об этом.

    Пробный заход ничего не пишет, и «есть ли уже задача» для него — сведение,
    а не условие. Токен приложения (`GITHUB_TOKEN`) на `GET /user` получает 403,
    и прежде пробный заход с ним кончался «не отработал» там, где без токена
    говорил «не спрошено» (поздний взгляд на #1497). Боевой заход зовёт
    `owner_of` и без владельца не начинается.
    """
    try:
        return owner_of(token)
    except (NotRun, ghrest.TransportError) as exc:
        print(f"владелец токена не назван — есть ли уже, не спрошено: {report.cut(str(exc))}")
        return ""


def minor_title(tag: str, now: str) -> str:
    """Заголовок оповещения о миноре вне окна соседа."""
    return f"Механизмы {tag}: контракт {now} вне вашего окна — перечитать ответы"


def main(argv: list[str] | None = None) -> int:
    """Точка входа: решает, есть ли повод, и оповещает тех, кого смена касается."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="тег выпуска, vX.Y.Z")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--apply", action="store_true", help="завести задачи, а не показать")
    parser.add_argument(
        "--to", default="", help="пробно до выпуска: версия контракта, до которой он поднимет"
    )
    args = parser.parse_args(argv)
    report.announce(not args.apply)
    if args.repo.casefold() != family_uptake.OURS.casefold():
        here = args.repo or "?"
        print(f"оповещает поставщик ({family_uptake.OURS}); здесь {here} — оповещать некого")
        return EXIT_OK
    try:
        if args.to and args.apply:
            raise NotRun("--to — пробный заход до выпуска: писать о невыпущенном соседям нельзя")
        if args.to:
            tags = release_tags()
            if not tags:
                raise NotRun("выпусков в дереве нет — «до» для --to взять не у чего (075)")
            moved = grown(release.contract_at(tags[-1]), args.to)
        else:
            moved = jump(args.tag)
        if moved is None:
            print(f"мажор и минор контракта на {args.tag} не выросли — оповещать не о чем")
            return EXIT_OK
        was, now = moved
        breaks = major(now) > major(was)
        changed = changes(version.bare(args.tag))
        offered = onboard.steps(Path())
        declared = [] if breaks else [str(one["repo"]) for one in consumers.registry(Path())]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            seen, unread = family_uptake.sweep(family_uptake.family(), Path(tmp))
        took = family_uptake.takers(seen, offered)
        token = ghrest.token_from_env()
        if args.apply and not token:
            raise NotRun("токена нет — завести задачи соседям нечем")
        login = owner_of(token) if args.apply else asked_owner(token)
    except (
        NotRun,
        release.NotRun,
        build_changelog.NotRun,
        check_shipped.NotRun,
        consumers.NotRun,
        family_uptake.NotRun,
        ghrest.TransportError,
    ) as exc:
        print(f"оповещение не отработало: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN
    unread = list(unread)
    if breaks:
        print(f"контракт {was} → {now}: взяли наши шаги {len(took)} из {len(seen)} прочитанных")
        targets = [(one.repo, body_of(args.tag, was, now, one, changed), "") for one in took]
    else:
        targets = []
        reached = addressees(took, declared)
        print(f"контракт {was} → {now}: минор; взявших и объявленных {len(reached)}")
        for one in reached:
            try:
                span = window_of(one, token)
            except NotRun as exc:
                print(f"{one.repo}: {report.cut(str(exc), SHOWN)}")
                unread.append(one.repo)
                continue
            why = "" if span else "не объявлено"
            if span:
                try:
                    if covers(span, now):
                        print(f"{one.repo}: окно {span} покрывает {now} — не оповещается")
                        continue
                except NotRun:
                    why = f"«{span}» не разбирается"
            if why:
                print(f"{one.repo}: окно {why} — оповещается: исправить его может только он")
            body = minor_body_of(args.tag, was, now, span, changed, why)
            targets.append((one.repo, body, minor_title(args.tag, now)))
    failed: list[str] = []
    for repo, body, title in targets:
        try:
            print(notify(repo, args.tag, body, token, login, dry_run=not args.apply, title=title))
        except ghrest.TransportError as exc:
            print(
                f"::warning::{repo}: не оповещён — {report.cut(str(exc), SHOWN)}", file=sys.stderr
            )
            failed.append(repo)
    # Сосед бывает непрочитан дважды — клоном у обхода и окном у площадки, и в
    # разном регистре: назван он один раз (взгляд на #1591).
    spelled: dict[str, str] = {}
    for name in unread:
        spelled.setdefault(name.casefold(), name)
    unread = list(spelled.values())
    if unread or failed:
        print(f"не прочитаны: {', '.join(unread) or '—'}; не оповещены: {', '.join(failed) or '—'}")
        return EXIT_PARTIAL
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main_guard.run(main, EXIT_BROKEN))
