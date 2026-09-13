#!/usr/bin/env python3
"""Гейт: инструмент, отданный наружу, назван на входе — и пустота названа тоже.

Проект отдаёт наружу МЕХАНИЗМЫ, а не только текст, и правило каталога
[163](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/163-a-shipped-tool-is-named-at-the-entrance.md)
требует, чтобы вход описывался ими: список инструментов один, и читатель входа
доходит до него, не открывая журнала изменений.

ИНСТРУМЕНТ ОБЪЯВЛЯЕТ СЕБЯ САМ. Что файл «для потребителя» — решение автора, а
не свойство кода: наши гейты тоже говорят о потребителях, оставаясь нашими
самопроверками. Догадка по тексту дала бы ложные отказы, а они приучают
пропускать красное
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)),
поэтому предмет здесь — МАРКЕР в шапке файла, а не слова вокруг него.

ПУСТОЙ ПРЕДМЕТ ЗДЕСЬ ЗАКОНЕН, И ИМЕННО ПОЭТОМУ ГЕЙТ НЕ МОЛЧИТ. Замер
13.09.2026: помеченных инструментов ноль — ни одного шага с ``workflow_call``,
ни одного действия, ни собираемого пакета; передача отложена целиком до того
дня, когда конвейер закроет собственные вопросы (#196). Гейт, который на таком
предмете просто зеленел бы, не проверял бы ничего
([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md));
поэтому он судит ВХОД: пока отдавать нечего, README обязан говорить это словом,
а не умалчивать
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md),
[046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
Появится первый помеченный — вход обязан назвать его и перестать говорить
«брать нечего»: расхождение объявления с деревом краснеет в тот же день, а не
через смену
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).

ЧЕГО ГЕЙТ НЕ СУДИТ. Полноту описания — как подключают, каким тегом, что
делать тому, кому механизмы недоступны, — машине не выразить: это связность
текста, а не наличие строки. Гейт держит одно: НАЗВАН ЛИ инструмент на входе.
Сосед у сужения назван
([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).

Исходы (правило 039): ``0`` вход сходится с деревом · ``1`` расходится ·
``2`` гейт не отработал.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

import paths
import report

EXIT_OK: Final = 0
EXIT_REJECTED: Final = 1
EXIT_BROKEN: Final = 2

#: Маркер объявления: им инструмент говорит «меня берут наружу». Прописными —
#: чтобы не совпасть с прозой о передаче, которой в дереве хватает.
MARK: Final = "ОТДАЁТСЯ НАРУЖУ"

#: Маркер ищется в ШАПКЕ файла — в докстроке модуля или в комментарии над
#: прогоном. Ниже по файлу он был бы словом внутри разбора, а не объявлением.
HEAD_LINES: Final = 40

#: Чем строку открывают в докстроке, комментарии Python и комментарии YAML.
#: Объявление — НАЧАЛО строки: иначе сам этот файл, называющий маркер в
#: определении и в сообщениях, объявил бы наружу себя.
OPENERS: Final = ('"""', "#:", "#", "*", "-")

#: Где живут кандидаты. Список разрешительный (068): каталог, которого здесь
#: нет, гейт не читает — иначе пометка в чужом дереве прогона стала бы
#: объявлением.
LOOK_AT: Final = (paths.SCRIPTS, paths.WORKFLOWS)
SUFFIXES: Final = frozenset({".py", ".yml", ".yaml"})

#: Как вход называет пустоту. Строка взята из самого README и здесь — предмет
#: сверки, а не второй канонический текст (022): гейт спрашивает «сказано ли»,
#: а говорит это README.
SAYS_EMPTY: Final = "брать пока нечего"


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «вход сходится»."""


def bare(line: str) -> str:
    """Строка без открывающей разметки: голое начало объявления."""
    said = line.strip()
    while True:
        for opener in OPENERS:
            if said.startswith(opener):
                said = said[len(opener) :].strip()
                break
        else:
            return said


def declares(path: Path) -> bool:
    """Объявляет ли файл себя отдаваемым наружу.

    Судится НАЧАЛО строки в шапке, а не вхождение слов: этот гейт называет
    маркер и в определении, и в каждом своём сообщении — по вхождению он
    объявил бы наружу сам себя, а такой гейт неотличим от сломанного.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise NotRun(f"{path} не читается: {exc}") from exc
    return any(bare(line).startswith(MARK) for line in lines[:HEAD_LINES])


def shipped(root: Path) -> list[str]:
    """Пути помеченных инструментов, по одному адресу на инструмент.

    Отсутствие ОБОИХ каталогов поиска — третий исход: на обрезанном или чужом
    дереве «ничего не помечено» было бы выводом из незнания (045).
    """
    seen: list[str] = []
    looked = 0
    for where in LOOK_AT:
        folder = root / where
        if not folder.is_dir():
            continue
        looked += 1
        for path in sorted(folder.glob("*")):
            if path.suffix in SUFFIXES and declares(path):
                seen.append(str(path.relative_to(root)))
    if not looked:
        raise NotRun(
            f"ни одного каталога из {[str(at) for at in LOOK_AT]} нет: искать пометки негде (075)"
        )
    # Порядок — адресный, а не по очерёдности каталогов поиска: сообщение гейта
    # читает человек, и перечень, меняющийся от порядка LOOK_AT, читался бы как
    # разный ответ на один и тот же вопрос.
    return sorted(seen)


def entrance(root: Path) -> str:
    """Текст входа. Без него судить нечего — третий исход."""
    path = root / paths.ENTRANCE
    if not path.is_file():
        raise NotRun(f"входа {paths.ENTRANCE} нет: сверять дерево не с чем")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise NotRun(f"{path} не читается: {exc}") from exc


def apart(said: str, tools: list[str]) -> str:
    """Пусто, если вход сходится с деревом; иначе — чем именно расходится."""
    empty_said = SAYS_EMPTY in said
    if not tools:
        if empty_said:
            return ""
        return (
            f"наружу не помечено ни одного инструмента, а вход {paths.ENTRANCE} об этом молчит: "
            f"отсутствующий механизм и молчащий снаружи неотличимы (046). Скажите словом — "
            f"строкой «{SAYS_EMPTY}» с причиной и сроком — либо пометьте инструмент "
            f"маркером «{MARK}»"
        )
    nameless = [at for at in tools if at not in said]
    if empty_said:
        return (
            f"вход {paths.ENTRANCE} говорит «{SAYS_EMPTY}», а маркером «{MARK}» помечено "
            f"{len(tools)}: {', '.join(tools)}. Либо снимите объявление пустоты, либо "
            f"пометки — вход, отстающий от дерева, читают как дерево (005)"
        )
    if nameless:
        return (
            f"на входе {paths.ENTRANCE} не названо: {', '.join(nameless)} — "
            f"инструмент, отданный наружу, называют на входе, а не в журнале изменений. "
            f"Неназванное берут копированием, потому что другого пути читателю не оставили"
        )
    return ""


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сверяет объявление входа с помеченным в дереве."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="корень дерева; по умолчанию текущий")
    args = parser.parse_args(argv)

    root = Path(args.root)
    try:
        tools = shipped(root)
        said = entrance(root)
    except NotRun as exc:
        print(f"гейт не отработал: {report.cut(str(exc))}", file=sys.stderr)
        return EXIT_BROKEN

    apart_said = apart(said, tools)
    if apart_said:
        print(f"отвергнуто: {apart_said}")
        return EXIT_REJECTED
    print(
        f"вход сходится с деревом: помечено наружу {len(tools)}"
        + (f" ({', '.join(tools)})" if tools else f", и вход говорит «{SAYS_EMPTY}»")
    )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
