"""Гейт правила 153: чужое «почему» — ссылка, а не копия.

ЧТО ЗДЕСЬ ПРЕДМЕТ. Разбор правила живёт в каталоге, и мы на него ССЫЛАЕМСЯ.
Переписанный к себе, он расходится с источником с первой же правкой каталога —
и расходится молча: копия выглядит так же, как была, а правило под ней уже
другое
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

ЦИТАТА НЕ ЗАПРЕЩЕНА — ЗАПРЕЩЕНА КОПИЯ БЕЗ АДРЕСА. Привести чужие слова, чтобы
довод читался на месте, законно: правило требует, чтобы читатель мог дойти до
источника. Поэтому находка здесь — дословный кусок разбора в документе, рядом
с которым НЕТ ссылки на то самое правило.

ПОЧЕМУ НЕ ПРОВЕРЯЕТСЯ НАБОРОМ, А ХОДИТ К КАТАЛОГУ. Тексты правил живут в
каталоге, а не у нас: свериться с ними можно только спросив. Набор при этом
остаётся офлайновым — гейт идёт отдельным шагом прогона, как и сверка ссылок.

Исходы (правило 039): ``0`` чисто · ``1`` есть находки · ``2`` не отработал.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import catalogue

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2
#: КАТАЛОГ НЕ ОТВЕТИЛ — свой исход, и он НЕ красный. Предмет проверки лежит в
#: чужой выгрузке: молчание канала говорит о сети, а не о нашем дереве, и держать
#: слияние оно не вправе (084). Зелёным это тоже не считается — иначе гейт молча
#: выключался бы ровно тогда, когда перестал работать (045). Разбор и условие
#: пересмотра — docs/decisions/027-a-silent-catalogue-is-its-own-outcome.md.
EXIT_SILENT: Final = 4

#: Откуда берётся разбор правил — из общего объявления адресов каталога: пятый
#: читатель одной строки и стал поводом поднять её вверх (090).
EXPORT_URL: Final = catalogue.EXPORT_URL

#: Сколько слов подряд считать КОПИЕЙ. Короче — совпадают обороты речи: «и это
#: не мелочь оформления» встречается у всех, и гейт на такой длине ловил бы
#: язык, а не заимствование. Замер 13.09.2026 на живом дереве: при десяти
#: словах нашлось четыре места, и все четыре — настоящие цитаты из правил.
WINDOW: Final = 10

#: Как документ ссылается НА ПРАВИЛО: адрес файла в каталоге. Отсюда берётся
#: номер — это опознание, а не вычистка; сосед по имени называется ниже.
RULE_LINK_RE: Final = re.compile(r"rules/ru/(?P<rule>\d{3})-")

WORD_RE: Final = re.compile(r"\w+")

#: Адрес — НЕ СЛОВА, и разбирать его как слова нельзя: этим образцом адреса
#: ВЫЧИЩАЮТСЯ перед разбором. Имя не сокращается до соседского `RULE_LINK_RE`
#: намеренно — предметы разные: тот опознаёт правило, этот убирает любой адрес,
#: и перепутать их при правке стоило бы тихой дыры (нашёл внешний взгляд на
#: #318).
#:
#: Замер 13.09.2026: из 2592 кусков `AGENTS.md` 343 состоят из разобранной по
#: словам ссылки, и два документа, ссылающиеся на одно правило, выглядели бы
#: копиями друг друга. Здесь это ещё не вредит — в разборах каталога ссылок нет
#: вовсе, — но класс закрыт заранее, а не после первого совпадения
#: ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
#:
#: ГРАНИЦА АДРЕСА — НЕ ЛЮБОЙ НЕ-ПРОБЕЛ. Жадное `\S+` съедает всё до следующего
#: пробела, и две ссылки подряд без разделителя вычистились бы вместе с прозой
#: между ними: гейт молча перестал бы видеть там копию. В дереве такого пока
#: нет, и находка названа риском, а не дефектом (внешний взгляд на #318).
#: Поэтому адрес кончается на закрывающей скобке разметки — там, где его
#: заканчивает сам markdown.
ADDRESS_RE: Final = re.compile(r"https?://[^\s)\]]+")


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def claims() -> dict[str, str]:
    """Номер правила → его разбор, как публикует каталог."""
    try:
        export = catalogue.read(EXPORT_URL)
    except catalogue.Silent:
        # Молчание канала НЕ превращается в «не отработал»: у него свой исход,
        # и поднимается он до точки входа нетронутым (039).
        raise
    found: dict[str, str] = {}
    for rule in export.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        number = str(rule.get("id") or "")
        # ФОРМА ЧУЖОГО ПОЛЯ ПРОВЕРЯЕТСЯ, А НЕ ПРЕДПОЛАГАЕТСЯ. `claim` приходит
        # из выгрузки каталога, и `(… or {}).get("ru")` бросал AttributeError
        # на любом не-словаре: гейт падал трассировкой вместо объявленного
        # третьего исхода, то есть давал ЧЕТВЁРТЫЙ (039). Отклонение формы —
        # это «каталог сказал не то», и оно пропускается вместе с правилом, а
        # не роняет разбор остальных (нашёл внешний взгляд на #315).
        claim = rule.get("claim")
        said = claim.get("ru") if isinstance(claim, dict) else ""
        if number and isinstance(said, str) and said:
            found[number] = said
    if not found:
        raise NotRun("в выгрузке каталога нет ни одного разбора — сверять не с чем (075)")
    return found


def documents(root: Path) -> list[Path]:
    """Отслеживаемые документы дерева: предмет проверки."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    if listed.returncode != 0:
        raise NotRun(f"список документов не получен: {listed.stderr.strip()}")
    found = [root / name for name in listed.stdout.split("\0") if name]
    if not found:
        raise NotRun("в дереве нет ни одного документа — проверять нечего (075)")
    return found


def pieces(text: str) -> set[str]:
    """Все куски текста длиной в окно — по словам, а не по буквам.

    По словам потому, что перенос строки и лишний пробел — оформление, а не
    заимствование: разбор, чувствительный к ним, ловил бы вёрстку.
    """
    words = WORD_RE.findall(ADDRESS_RE.sub(" ", text).lower())
    return {" ".join(words[at : at + WINDOW]) for at in range(len(words) - WINDOW + 1)}


def copied(text: str, said: dict[str, str]) -> set[str]:
    """Правила, чей разбор дословно лежит в этом тексте."""
    have = pieces(text)
    return {rule for rule, claim in said.items() if pieces(claim) & have}


def linked(text: str) -> set[str]:
    """Правила, на которые этот текст ссылается."""
    return {found["rule"] for found in RULE_LINK_RE.finditer(text)}


def main(argv: list[str] | None = None) -> int:
    """Точка входа: ищет копии чужого разбора без ссылки на источник."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    args = parser.parse_args(argv)

    try:
        said = claims()
        docs = documents(args.root)
    except catalogue.Silent as exc:
        # ОТКАЗ КАНАЛА НАЗЫВАЕТСЯ И НЕ КРАСИТ. Печатается в поток вывода, а не
        # ошибок: это не находка и не поломка шага, а состояние сети. Адресата
        # даёт сам шаг прогона — он превращает этот исход в предупреждение на
        # изменении, видимое автору (084, 154).
        print(f"каталог молчит — не проверено: {exc}")
        return EXIT_SILENT
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    problems: list[str] = []
    quoted = 0
    for path in docs:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # НЕ-UTF8 В ДЕРЕВЕ — ЭТО ТОЖЕ «НЕ ПРОЧИТАН», а не падение. Ловился
            # только OSError, и документ в чужой кодировке ронял гейт
            # трассировкой мимо всех трёх объявленных исходов (039, находка
            # внешнего взгляда на #315).
            print(f"гейт не отработал: {path} не прочитан: {exc}", file=sys.stderr)
            return EXIT_BROKEN
        here = copied(text, said)
        quoted += len(here)
        for rule in sorted(here - linked(text)):
            problems.append(f"  {path}: разбор правила {rule} переписан, а ссылки на него нет")

    # ОХВАТ НАЗЫВАЕТСЯ ВСЕГДА: проверка, читающая сотни документов, без числа
    # неотличима от той, что не прочитала ни одного (165).
    print(f"документов прочитано: {len(docs)}, дословных цитат найдено: {quoted}")
    if not problems:
        print("чисто: чужой разбор всюду приведён со ссылкой на источник")
        return EXIT_OK
    print(f"копий чужого разбора без ссылки: {len(problems)}", file=sys.stderr)
    for one in problems:
        print(one, file=sys.stderr)
    return EXIT_FOUND


if __name__ == "__main__":
    raise SystemExit(main())
