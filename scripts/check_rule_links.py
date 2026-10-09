#!/usr/bin/env python3
"""Гейт: ссылка на правило каталога ведёт туда, куда обещает.

ПОЧЕМУ ЭТО ВАЖНЕЕ, ЧЕМ ВЫГЛЯДИТ. Ссылками на правила этот проект обосновывает
решения: почти каждый механизм называет правило, из которого вырос. Ссылка,
ведущая в никуда, обесценивает обоснование дважды — читатель не может проверить
довод и не может отличить «правило есть, адрес переврали» от «правила нет».

Замер 10.09.2026, из-за которого гейт и появился: битых ссылок в дереве
оказалось **двадцать девять**. Семнадцать — промежуточный счёт первого прохода;
он остался здесь, когда обход расширили на всё дерево, и расходился с записью
об инциденте, которую этот же гейт и породил. Имя файла правила писалось по памяти — номер верный,
а название придумано близко к смыслу: `046-a-red-must-name-its-cause.md` вместо
`046-name-the-gaps-do-not-level-them.md`. На площадке такая ссылка отдаёт 404, и
ни один прогон об этом не говорил. Нашёл первую из них внешний взгляд на #130.

ИМЯ СВЕРЯЕТСЯ С ВЫГРУЗКОЙ КАТАЛОГА, А НЕ С ПАМЯТЬЮ. Каталог публикует `id` и
`slug` каждого правила; второй список того же разошёлся бы с первым молча
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

ВЫГРУЗКА НЕ ПРИШЛА — ЭТО ТРЕТИЙ ИСХОД. «Не спросили» и «всё сошлось» снаружи
одинаковы, и молчаливое «чисто» здесь было бы тихим запасным ответом
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

Исходы (правило 039): ``0`` чисто · ``1`` есть находки · ``2`` не отработал
(пустое дерево и перечисленный, но не прочитанный с диска файл — при любой
сети: дерево читается раньше выгрузки) · ``4`` каталог молчит. Кодировка файла
исход не решает: ссылка ищется в байтах (`links`). У соседа
`check_foreign_why` чужая кодировка — «не отработал», и это не расхождение, а
разный предмет: он сравнивает прозу, а прозу без раскодирования не прочесть.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Final

import catalogue
import gitcall

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2
#: КАТАЛОГ НЕ ОТВЕТИЛ — свой исход, и он НЕ красный. Предмет проверки лежит в
#: чужой выгрузке: молчание канала говорит о сети, а не о нашем дереве, и держать
#: слияние оно не вправе (084). Зелёным это тоже не считается — иначе гейт молча
#: выключался бы ровно тогда, когда перестал работать (045). Разбор и условие
#: пересмотра — docs/decisions/027-a-silent-catalogue-is-its-own-outcome.md.
EXIT_SILENT: Final = 4

EXPORT_URL: Final = catalogue.EXPORT_URL
#: Ссылка на файл правила: `rules/ru/<номер>-<имя>.md`. Ловится и в прозе, и в
#: докстроке — форма одна, и разбирать её по видам файлов незачем. Образец
#: БАЙТОВЫЙ: в ссылке только латиница, цифры и знаки ASCII, и в любой
#: кодировке, совместимой с ASCII, она лежит теми же байтами (`links`).
LINK_RE: Final = re.compile(rb"rules/ru/(?P<number>\d{3})-(?P<slug>[a-z0-9-]+)\.md")
SUFFIXES: Final = frozenset({".py", ".md", ".yml", ".yaml", ".json"})


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «чисто»."""


def known() -> dict[str, str]:
    """Номер → имя файла правила, как их публикует каталог."""
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
        number, slug = str(rule.get("id") or ""), str(rule.get("slug") or "")
        if number and slug:
            found[number] = slug
    if not found:
        raise NotRun("в выгрузке каталога нет ни одного правила — сверять не с чем (075)")
    return found


def links(root: Path) -> list[tuple[Path, int, str, str]]:
    """Ссылки на правила в отслеживаемых файлах: где, на какой номер и имя."""
    listed = gitcall.output(
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], NotRun, cwd=str(root)
    )
    found: list[tuple[Path, int, str, str]] = []
    for name in listed.split("\0"):
        if not name:
            continue
        path = root / name
        if path.suffix not in SUFFIXES:
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            # ПЕРЕЧИСЛЕН, НО НЕ ПРОЧИТАН — «НЕ ОТРАБОТАЛ», А НЕ ПРОПУСК (045):
            # молча выпавший файл неотличим от проверенного.
            raise NotRun(f"{name} не прочитан: {exc}") from exc
        # ССЫЛКА ИЩЕТСЯ В БАЙТАХ, А НЕ В РАСКОДИРОВАННОМ ТЕКСТЕ (взгляд на
        # #1300). Прежде файл не в UTF-8 молча выпадал, затем ронял весь гейт в
        # «не отработал» — и фикстура кодировки в любом проекте семьи, берущем
        # шаг (`step-journal.yml`), краснила бы его без способа исключить файл.
        # Ссылка — ASCII и лежит теми же байтами в любой совместимой кодировке,
        # поэтому раскодировать нечего. Предел назван: в UTF-16 и UTF-32 ASCII
        # лежит иначе, и ссылку там гейт не увидит.
        for line_number, line in enumerate(data.splitlines(), 1):
            for match in LINK_RE.finditer(line):
                number, slug = match["number"].decode(), match["slug"].decode()
                found.append((Path(name), line_number, number, slug))
    return found


def broken(found: list[tuple[Path, int, str, str]], real: dict[str, str]) -> list[str]:
    """Ссылки, которые не ведут туда, куда обещают.

    Разводятся два случая: номера нет в каталоге вовсе и имя не то. Первое
    значит «правила не существует», второе — «правило есть, адрес переврали», и
    чинятся они по-разному (154).
    """
    problems: list[str] = []
    for path, line, number, slug in found:
        if number not in real:
            problems.append(f"{path}:{line} — правила {number} в каталоге нет")
        elif real[number] != slug:
            problems.append(f"{path}:{line} — {number} зовётся «{real[number]}», а не «{slug}»")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Точка входа: сверяет ссылки дерева с выгрузкой каталога."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    args = parser.parse_args(argv)

    # ДЕРЕВО ЧИТАЕТСЯ РАНЬШЕ КАТАЛОГА. Пустое дерево, отказ `git ls-files` и
    # перечисленный файл, которого нет на диске, — «не отработал» при любой
    # сети; прежде выгрузка спрашивалась первой, и тот же
    # пустой вход отвечал «каталог молчит», стоило сети моргнуть (#1255).
    # СОСЕДИ ПО ЧТЕНИЮ ВЫГРУЗКИ НАЗВАНЫ (195, взгляд на #1258): тот же порядок у
    # `check_foreign_why` (перечень и тексты документов раньше сети); `drift`
    # спрашивает токен и репозиторий раньше любого чтения сети; `audit_profile`
    # читает ответы дерева первым; `rule_link` и `review_map.titles` дерева
    # не читают вовсе — второй молчание выгрузки называет предупреждением и
    # отдаёт пустой перечень заголовков.
    try:
        found = links(args.root)
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if not found:
        print("гейт не отработал: ссылок на правила в дереве нет (075)", file=sys.stderr)
        return EXIT_BROKEN

    try:
        real = known()
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

    problems = broken(found, real)
    if not problems:
        print(f"чисто: все ссылки на правила разрешаются; проверено {len(found)}")
        return EXIT_OK
    print(f"ссылок, ведущих не туда: {len(problems)} из {len(found)}")
    for said in problems:
        print(f"  {said}")
    return EXIT_FOUND


if __name__ == "__main__":
    raise SystemExit(main())
