"""Гейт разметки: метки изменения и связь с задачей.

Правило 064: метки — вход механизма, а не украшение, поэтому они проверяются
машиной. Правило 068: список разрешительный — метка, которой нет в
``.github/labels.yml``, механизмом не читается, и стоять на изменении она не
должна: иначе появляется вторая, необъявленная классификация.

Связь с задачей обязательна: без неё задача не закроется при слиянии, а
приоритет очереди наследовать неоткуда.

Зона выводится из тронутых файлов по полю ``paths`` состава — но только для
зон, у которых оно есть. Зона без ``paths`` ставится человеком при разборе, и
требовать её машинно нечем; молчаливо считать такое изменение размеченным
нельзя, поэтому хотя бы одна зона обязана стоять всегда.

Исходы (правило 039): ``0`` разметка на месте · ``1`` изменение отвергнуто ·
``2`` гейт не отработал.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Final

import agent_pr
import changerefs
import ghrest
import items
import labels
import squash_body

#: Незакрытый пункт чек-листа задачи в её теле.
OPEN_ITEM_RE: Final = re.compile(r"^\s*[-*]\s*\[ \]\s*(\S.*?)\s*$", re.MULTILINE)

#: Отказ по слову закрытия вне строки связи — константой: на него ссылаются
#: тесты, а переписанные буквы разошлись бы с ним молча (209).
STRAY_CLOSING: Final = (
    "стоит слово закрытия с номером задачи вне строки связи — при слиянии площадка "
    "молча закроет эту задачу. Перепишите строку без этого слова; связь с задачей "
    "пишется отдельной строкой вида «Closes #N»"
)
#: Пропуск проверки сообщений коммитов называется вслух (045).
MESSAGES_UNREAD: Final = "сообщения коммитов не переданы — слово закрытия в них не проверено"

EXIT_OK: Final = 0
EXIT_REJECTED: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «прошло»."""


def load_event() -> dict[str, Any]:
    """Читает событие площадки: предмет проверки — изменение, а не ветка."""
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not path or not Path(path).is_file():
        raise NotRun("нет события площадки (GITHUB_EVENT_PATH) — предмет проверки не найден (075)")
    try:
        event = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NotRun(f"событие не читается: {exc}") from exc
    pull = event.get("pull_request")
    if not isinstance(pull, dict):
        raise NotRun("событие не об изменении — гейту нечего проверять")
    return pull


def fresh(pull: dict[str, Any], repo: str, token: str) -> dict[str, Any]:
    """Отдаёт изменение, каким оно ЕСТЬ, а не каким было в снимке события.

    Снимок события — это состояние на момент срабатывания, и на `opened` меток
    в нём нет по построению: их проставляет шаг открытия, и делает это через
    доли секунды ПОСЛЕ. Гейт, читающий снимок, выносит вердикт по прошлому:
    замер 09.09 — изменение #38 отвергнуто за «ни одной зоны», когда все три
    зоны на нём уже стояли.

    Без токена или номера остаётся снимок — и это объявлено, а не подменено
    тихо (045): вердикт по снимку возможен, просто он может отстать.
    """
    number = pull.get("number")
    if not token or not repo or not number:
        print(
            "состояние изменения не перечитано: нет токена или номера — вердикт по снимку\n"
            "события, и он может отставать от площадки",
            file=sys.stderr,
        )
        return pull
    try:
        current = ghrest.request("GET", f"repos/{repo}/pulls/{int(number)}", token)
    except ghrest.TransportError as exc:
        print(f"состояние изменения не перечитано: {exc} — вердикт по снимку", file=sys.stderr)
        return pull
    return current if isinstance(current, dict) else pull


def open_items(body: str) -> list[str]:
    """Незакрытые пункты чек-листа задачи, как они в ней записаны."""
    return [item.strip() for item in OPEN_ITEM_RE.findall(body or "")]


def premature(repo: str, token: str, links: list[Any], declared: list[str]) -> list[str]:
    """Задачи, которые изменение закрывает целиком, не доделав.

    ПОЧЕМУ ЭТО ГЕЙТ, А НЕ ВНИМАНИЕ АВТОРА. Площадка умеет только полное
    закрытие: `Closes #N` закрывает задачу вместе с несделанными этапами, и
    они теряются молча — задача уходит из списка открытых, и туда больше никто
    не смотрит. Проверка полноты, а не непустоты (128), на новом предмете.

    Пункт, названный закрытым в теле самого изменения, из счёта уходит: иначе
    последний этап закрыть было бы нечем — отметить его до слияния негде, а
    после слияния задача уже закрыта.

    Задача БЕЗ чек-листа проходит: отмечать в ней нечего, и требовать список
    там, где этап один, значило бы заводить ритуал (154). Требование к
    заведению задачи с этапами записано в AGENTS.md.
    """
    problems: list[str] = []
    for link in links:
        if not link.closes:
            continue
        try:
            issue = ghrest.request("GET", f"repos/{repo}/issues/{link.number}", token) or {}
        except ghrest.TransportError as exc:
            raise NotRun(f"задача #{link.number} не прочитана: {exc}") from exc
        left = [
            item
            for item in open_items(str(issue.get("body") or ""))
            if changerefs.normalise(item) not in declared
        ]
        if left:
            problems.append(
                f"#{link.number} закрывается целиком, а в ней осталось незакрытых пунктов: "
                f"{len(left)} — первый «{left[0]}». Либо связь «Refs», либо строка "
                f"«{changerefs.CLOSED_ITEM_KEY} <текст>» на каждый доделанный"
            )
    return problems


def read_files(inline: str, from_path: str) -> list[str]:
    """Читает список тронутых путей: из файла по NUL либо из строки по строкам.

    Путь с пробелом или не-ASCII git без `-z` отдаёт экранированным, и такой
    путь молча выпадает из отбора зон: метка не выставится, а гейт останется
    зелёным. Поэтому прогон передаёт список ФАЙЛОМ (`--files-from`), а не
    строкой: оболочка вырезает NUL из подстановки.
    """
    if from_path:
        raw = Path(from_path).read_bytes().decode("utf-8")
        return [name for name in raw.split("\0") if name]
    return [line.strip() for line in inline.splitlines() if line.strip()]


def read_messages(from_path: str) -> list[str]:
    """Сообщения коммитов изменения, каждое отдельно; без файла — пусто, и это сказано.

    Отдельно, а не склейкой: у каждого сообщения своя разметка, и склеенные
    заборы кода разбор счёл бы парой (`changerefs.links_in_all`). Порядок — от
    старых к новым, как их читают `agent_pr` и `squash_body`: первая задержка
    и заголовок берутся у первого коммита.
    """
    if not from_path:
        print(MESSAGES_UNREAD, file=sys.stderr)
        return []
    raw = Path(from_path).read_bytes().decode("utf-8")
    return [one for one in raw.split("\0") if one.strip()]


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", default="", help="тронутые файлы через перевод строки")
    parser.add_argument(
        "--files-from",
        default="",
        help="файл со списком тронутых путей, разделённых NUL (git diff -z)",
    )
    parser.add_argument(
        "--messages-from",
        default="",
        help="файл с сообщениями коммитов изменения, разделёнными NUL (git log %%B%%x00)",
    )
    args = parser.parse_args(argv)

    try:
        pull = load_event()
        declared = labels.load()
    except (NotRun, labels.BadConfig) as exc:
        print(f"проверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    # Метки — вход механизма, и читать их надо у площадки, а не у снимка.
    pull = fresh(pull, os.environ.get("GITHUB_REPOSITORY", ""), ghrest.token_from_env())

    on_pr = {str(label["name"]) for label in pull.get("labels", [])}
    body = pull.get("body") or ""
    title = pull.get("title") or ""
    files = read_files(args.files, args.files_from)
    # Охват печатается всегда: проверка, читающая список путей, без числа
    # неотличима от чистого результата — слепота выглядит как «нечего держать»
    # (165).
    print(f"тронутых путей прочитано: {len(files)}")

    problems: list[str] = []

    # СЛОВО ЗАКРЫТИЯ ВНЕ СТРОКИ СВЯЗИ (#928). Судится ТОТ ТЕКСТ, что доедет до
    # общей ветки или будет прочитан площадкой при слиянии, — и ничего сверх:
    #
    # * заголовок изменения — БЕЗ исключения для строки связи. Он становится
    #   заголовком коммита слияния (`automerge.py`), и `Fixes #5` там закроет
    #   задачу, которой в описании может не быть;
    # * описание изменения — площадка читает его целиком;
    # * из коммитов — только то, что отберёт `squash_body.compose_from`:
    #   заголовки, строки связи, «Разобрано», трейлеры. Проза тела коммита в
    #   общую ветку не едет, и отвергать её значило бы требовать переписать
    #   историю ветки ради слова, которое никуда не попадёт.
    #
    # Заголовки коммитов берутся так же, как их отдаёт git (`subject_of`), и
    # среди них есть подтягивания базы, которые `compose` отбрасывает
    # (`--no-merges`). Это строже площадки на заголовке слияния базы — его
    # пишет git — и ни на чём больше: будущее описание ниже судится только
    # там, где его действительно допишут.
    #
    # ОПИСАНИЕ СУДИТСЯ И БУДУЩЕЕ. Его дописывает `agent_pr` после толчка, и
    # строки, которые он переносит из коммитов («Закрывает пункт», «Ждёт:»),
    # площадка прочтёт при слиянии. Перезаход проверки по правке описания
    # (`edited`) бывает, но на него не опереться: зависит от токена, которым
    # правили (#929). Поэтому будущее описание судится уже сейчас — той же
    # `agent_pr.describe_from`, что его соберёт, и в том же порядке коммитов,
    # от старых к новым (`--reverse` в прогоне). Это более ранний отказ, а не
    # единственный: перезаход, если он будет, решит то же самое.
    #
    # Судится оно ТОЛЬКО там, где `agent_pr` его допишет: на ветке с его
    # приставкой и в описании с его отметкой. Человеческое описание он не
    # трогает, и строка из коммита туда не доедет — отвергать её значило бы
    # судить то, чего не будет.
    messages = read_messages(args.messages_from)
    subjects = [squash_body.subject_of(one) for one in messages]
    landing = squash_body.compose_from(subjects, messages)
    head = str((pull.get("head") or {}).get("ref") or "")
    rewritten = head.startswith(agent_pr.PREFIXES) and agent_pr.MARK in body
    coming = agent_pr.describe_from(subjects, messages) if messages and rewritten else None
    for heading in dict.fromkeys([title, *([coming.title] if coming else [])]):
        if changerefs.CLOSING_KEYWORD_RE.search(heading):
            problems.append(f"в заголовке «{heading}» {STRAY_CLOSING}")
    said = "\n".join([body, landing, coming.body if coming else ""])
    for line in dict.fromkeys(changerefs.stray_closing_words(said)):
        problems.append(f"в строке «{line}» {STRAY_CLOSING}")

    undeclared = sorted(on_pr - {label.name for label in declared})
    if undeclared:
        problems.append(
            "на изменении метки, которых не объявляет .github/labels.yml: "
            + ", ".join(undeclared)
            + " — список разрешительный (068)"
        )

    zones_on_pr = {name for name in on_pr if labels.zone_named(name)}
    if not zones_on_pr:
        problems.append("не поставлена ни одна зона (area/*) — изменение не разобрано")

    expected = labels.zones_for(declared, files)
    missing = sorted(expected - zones_on_pr)
    if missing:
        problems.append(
            "тронуты файлы зон, которых нет на изменении: "
            + ", ".join(missing)
            + " — зона выведена из путей состава, а не угадана"
        )

    # СВЯЗЬ И ЗАКРЫТЫЕ ПУНКТЫ ЧИТАЮТСЯ И ИЗ КОММИТОВ (#929). Тело изменения
    # дописывает `agent-pr` токеном прогона — после толчка и без нового захода
    # проверок, — и гейт, читавший одно тело, судил по прошлому: #927 отвергнут
    # за незакрытые пункты, которые строки коммита уже закрыли. Коммиты — тот
    # же источник, из которого тело собирается, и они едут в тело слияния
    # (`squash_body.compose`). Тело читается по-прежнему: его правит человек.
    #
    # У СВЯЗИ И У ПУНКТОВ РАЗНЫЕ ЧИТАТЕЛИ, и граница у них разная — сосед
    # условия `rewritten` выше (195). Связь из коммита доедет до общей ветки
    # всегда: её переносит тело слияния. Закрытый пункт отмечает `items.py`
    # только по ТЕЛУ изменения, а туда строку из коммита переносит лишь
    # `agent_pr` — там, где он тело пишет. В чужом теле пункт из коммита не
    # отметится никем, и засчитывать его значило бы пропустить закрытие задачи
    # с неотмеченным пунктом.
    #
    # ПУНКТЫ СЧИТАЮТСЯ ПО ИТОГОВОМУ ТЕЛУ И ТЕМ ЖЕ ЧТЕНИЕМ, что у `items.py`
    # (`items.declared_in`). Итоговое тело — то, что соберёт `agent_pr`, где он
    # пишет, и нынешнее — где нет. Не заголовок: его `items.py` не читает. Не
    # склейка нынешнего с будущим: `agent_pr` нынешнее ЗАМЕНИТ, и пункт, убранный
    # из коммитов перезаписью ветки, засчитался бы по устаревшему тексту.
    texts = [f"{title}\n{body}", *messages]
    links = changerefs.links_in_all(texts)
    final = coming.body if coming else body
    _, marked = items.declared_in(final)
    token = ghrest.token_from_env()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if token and repo:
        try:
            problems += premature(
                repo,
                token,
                links,
                [changerefs.normalise(item) for item in marked],
            )
        except NotRun as exc:
            # Отказ чтения задачи — объявленный третий исход, а не трассировка:
            # необработанное исключение отдаёт единицу, а единица здесь значит
            # «изменение отвергнуто», то есть сломанный гейт читался бы как
            # сработавший (039, 068).
            #
            # НАЙДЕННОЕ ДО ОТКАЗА НЕ ПРОПАДАЕТ. Метки и связь уже разобраны, и
            # находки по ним верны независимо от того, прочиталась ли задача.
            # Молча их выбросить значило бы отдать автору «проверка не
            # отработала» там, где у него на изменении настоящий дефект
            # разметки: он починит недоступность площадки, а не свою метку.
            print(f"проверка не отработала: {exc}", file=sys.stderr)
            if problems:
                print(
                    f"до отказа найдено ({len(problems)}) — их чинить всё равно:",
                    file=sys.stderr,
                )
                for problem in problems:
                    print(f"  {problem}", file=sys.stderr)
            return EXIT_BROKEN
    else:
        # Пропуск объявляется, а не молчит — тем же приёмом, что у соседней
        # `fresh()`: «проверено и чисто» и «не проверено» снаружи одинаковы (045).
        print(
            "полнота чек-листа не проверена: нет токена или репозитория — "
            "преждевременное закрытие задачи этот заход не поймает",
            file=sys.stderr,
        )

    if not links:
        problems.append(
            "нет связи с задачей: ни «Closes #N», ни «Refs #N» — "
            "без неё задача не закроется при слиянии, а приоритет очереди наследовать неоткуда"
        )

    if problems:
        print(f"отвергнуто ({len(problems)}):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return EXIT_REJECTED

    print(f"разметка на месте: {', '.join(sorted(on_pr)) or '—'}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
