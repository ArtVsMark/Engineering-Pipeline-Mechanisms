#!/usr/bin/env python3
"""Собирает `CHANGELOG.md` из фрагментов.

Правило 030: журнал собирается из фрагментов, а не правится общим файлом. Два
файла с разными именами не конфликтуют никогда, а на конфликтном изменении
площадка не создаёт проверок вовсе.

Правило 125: генератор читает **источники, а не свой вывод**. Поэтому выпущенные
фрагменты не исчезают в собранный файл, а переезжают в
``changelog.d/released/<версия>/`` и остаются источником. `CHANGELOG.md`
производный целиком: его можно удалить и собрать заново, ничего не потеряв.

СОБРАННЫЙ ЖУРНАЛ — ДЕЛО ВЫПУСКА, А НЕ КАЖДОГО ИЗМЕНЕНИЯ
([030](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/030-changelog-from-fragments.md)):
«запись приезжает вместе с изменением, отдельным файлом; сборка — при выпуске».
Инцидент, записанный в самом правиле, мы успели повторить: общий файл, который
трогает каждая ветка, даёт конфликт на каждом втором изменении — за десять
минут 9 сентября он случился дважды.

Поэтому на изменении проверяются ФРАГМЕНТЫ (``--fragments``): имя разбирается,
тело не пусто, ссылка на задачу последней строкой. Совпадение собранного файла
со сборкой (``--check``) остаётся, но спрашивают его при выпуске.

Исходы (правило 039): ``0`` собрано · ``1`` собранное расходится с файлом на
диске при ``--check`` · ``2`` собрать не удалось.
"""

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import journal
import paths
import version as project_version

FRAGMENTS: Final = paths.FRAGMENTS
RELEASED: Final = paths.RELEASED
OUTPUT: Final = paths.CHANGELOG
#: Формат номера версии общий (214) и живёт уровнем выше (090).
VERSION_RE: Final = paths.VERSION_RE
LINK_LINE_RE: Final = journal.LINK_LINE_RE

KINDS: Final = journal.KINDS

#: Сколько ВЫПУСКОВ разворачивается в собранном журнале. Остальные остаются
#: источником и называются ссылкой на каталог выпуска.
#:
#: ПОЧЕМУ ПРЕДЕЛ ЕСТЬ. Вышедшее из окна переезжает дословно и не сокращается —
#: фрагменты уходят в `changelog.d/released/<версия>/` целиком. Но собранный
#: файл читает человек, и без предела он растёт линейно по числу выпусков:
#: к сотому читатель ищет свежее прокруткой. Предел — у ПРЕДСТАВЛЕНИЯ, не у
#: источника: ни одна запись не пропадает, она перестаёт быть развёрнутой.
#:
#: ПОЧЕМУ ТРИ (решение владельца 06.10.2026, #1172). Прежде стояло пять «как у
#: соседа», а грейдер держит три — довод устарел молча. При пяти предел не
#: сработал ни разу: выпусков было ровно пять, и журнал дорос до 2,1 МБ.
#: Число небольшое намеренно: предел, выбранный «с запасом», не срабатывает
#: годами и потому не проверен ничем.
UNFOLDED_RELEASES: Final = 3
#: Предел ТЕЛА нового фрагмента: непустые строки без заголовка `###` и без
#: строки ссылки на задачу. Договор — «одна-три строки о том, что изменилось
#: для потребителя» (`changelog.d/README.md`), а держался он одной прозой:
#: медиана выпуска 1.2.0 — 38 строк, и журнал дорос до 2,1 МБ (#1172). Десять —
#: с запасом над договором, но не над эссе: разбор и замер едут в задачу, а
#: во фрагменте остаётся ссылка на неё.
FRAGMENT_LINES: Final = 10
#: Предел ТЕЛА в знаках — та же граница, но против абзаца, записанного одной
#: длинной строкой: предел строк объёма не держит, а гейт заведён ради
#: объёма (взгляд на #1174). Замер 06.10.2026: у невыпущенных фрагментов
#: наибольшее тело — 645 знаков, медиана выпуска 1.4.0 — 524, у прежних
#: выпусков медиана 1000–1900. Восемьсот — с запасом над нынешней формой.
FRAGMENT_CHARS: Final = 800
#: Забор блока кода по CommonMark: три и больше обратных кавычек или тильд.
#: Внутри него `#` — комментарий примера, а не заголовок; закрывает его забор
#: того же знака не короче открывшего. У забора кавычками в строке сведений
#: кавычки нет — иначе это код в строке, а не забор.
FENCE_RE: Final = re.compile(r"^(?:(`{3,})[^`]*|(~{3,}).*)$")
#: Отступ, с которого строка — блок кода или ленивое продолжение абзаца, а не
#: начало блока: ни заголовком, ни забором, ни цитатой она не бывает.
CODE_INDENT: Final = 4
#: Заголовок выше `###`: в собранном журнале он встаёт в ряд с версиями (`##`)
#: и ломает навигацию по выпускам — таких в выпущенном 16 (#1172).
TOO_HIGH_RE: Final = re.compile(r"^#{1,2}\s")

FRAGMENT_RE: Final = journal.NAME_RE

EXIT_OK: Final = 0
EXIT_DIFFERS: Final = 1
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Сборка не отработала: третий исход, а не пустой журнал."""


@dataclass(frozen=True, slots=True)
class Fragment:
    """Один фрагмент журнала: род, слаг имени, текст.

    Поле звалось `task` от прежнего правила именования — по номеру задачи.
    Правило снято вместе с потерянной записью, и имя поля шло за ним следом:
    слаг говорит, ЧТО изменилось, а не какая задача.
    """

    kind: str
    slug: str
    body: str


#: Ссылка Markdown: `[текст](адрес)`. Разбор один на оба переезда — в
#: собранный журнал и в каталог выпуска.
LINK_RE: Final = re.compile(r"\[[^\]]*\]\((?P<target>[^)\s]+)\)")

#: Схемы и формы, которые переездом не задеваются: внешний адрес и якорь
#: указывают не на файл дерева, а путь от корня («/x») от места не зависит.
KEEPS_ITS_SHAPE: Final = ("http://", "https://", "mailto:", "tel:", "#", "/")


def relink(text: str, *, was: Path, now: Path) -> str:
    """Пересчитывает относительные ссылки текста, переехавшего из `was` в `now`.

    ЗАЧЕМ. Фрагмент пишется, лёжа в `changelog.d/`, и адресует соседей
    оттуда — `../docs/decisions/008-…`. Собранный журнал живёт в КОРНЕ, а сам
    фрагмент уезжает на два уровня вниз, в `changelog.d/released/<версия>/`:
    та же строка ведёт уже выше корня и в пустоту. Выпуск 1.0.0 обнаружил это
    разом в семнадцати документах — до него журнал не собирался ни разу, и
    предмета у гейта ссылок просто не было
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

    ПЕРЕСЧИТЫВАЕТСЯ ТОЛЬКО ТО, ЧТО РАЗРЕШАЕТСЯ В ФАЙЛ ДЕРЕВА, и предел назван
    честно: адрес площадки (`../../pull/183`) выглядит относительным, но
    разрешается не в дереве, а на сайте — трогать его вслепую значит менять
    работающее на угаданное. Такой адрес остаётся как есть
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
    """
    if was.resolve() == now.resolve():
        return text

    def moved(match: re.Match[str]) -> str:
        target = match["target"]
        if target.startswith(KEEPS_ITS_SHAPE):
            return match.group(0)
        path, _, anchor = target.partition("#")
        if not path or not (was / path).exists():
            return match.group(0)
        fresh = Path(os.path.relpath((was / path).resolve(), now.resolve())).as_posix()
        said = fresh + (f"#{anchor}" if anchor else "")
        # ЗАМЕНЯЕТСЯ ИМЕННО АДРЕС, А НЕ ПЕРВОЕ ПОХОЖЕЕ МЕСТО. Поиск по строке
        # правил видимый текст, когда тот совпадал с адресом: из
        # `[../docs/x.md](../docs/x.md)` выходила ссылка с новым текстом и
        # старым адресом — то есть ровно наоборот. Позиция группы такой
        # двусмысленности не имеет. Нашёл внешний взгляд на #297.
        start, end = match.span("target")
        whole = match.group(0)
        head = whole[: start - match.start()]
        tail = whole[end - match.start() :]
        return head + said + tail

    return LINK_RE.sub(moved, text)


def read_fragments(directory: Path) -> list[Fragment]:
    """Читает ВСЕ фрагменты каталога: предмет выпуска, а не изменения."""
    if not directory.is_dir():
        return []
    return parse_fragments(sorted(directory.glob("*.md")))


def parse_fragments(paths: list[Path]) -> list[Fragment]:
    """Разбирает названные файлы, отвергая неразбираемые имена и пустые.

    Разбор один на оба читателя — выпуск и гейт изменения. Двумя копиями он
    разошёлся бы молча: один принял бы фрагмент, который второй отвергает
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    """
    fragments: list[Fragment] = []
    unnamed: list[str] = []
    for path in paths:
        if path.name == "README.md" or not path.is_file():
            continue
        match = FRAGMENT_RE.match(path.name)
        if match is None:
            unnamed.append(path.name)
            continue
        # Тело едет в собранный журнал, а тот лежит в корне: ссылки,
        # написанные из каталога фрагментов, пересчитываются под новое место.
        body = relink(path.read_text(encoding="utf-8").strip(), was=path.parent, now=OUTPUT.parent)
        if not body:
            unnamed.append(f"{path.name} (пустой)")
            continue
        if not LINK_LINE_RE.match(body.splitlines()[-1].strip()):
            unnamed.append(f"{path.name} (ссылка на задачу не последней строкой)")
            continue
        # Причина у `internal` проверяется ЗДЕСЬ, а не у гейта изменения: разбор
        # фрагментов один на обоих читателей, и вторая копия правила разошлась
        # бы с первой молча (090).
        if match["kind"] == journal.INTERNAL and not journal.REASON_LINE_RE.match(
            body.splitlines()[0].strip()
        ):
            unnamed.append(f"{path.name} (род `internal` без причины первой строкой)")
            continue
        fragments.append(Fragment(match["kind"], match["slug"], body))

    if unnamed:
        raise NotRun(
            "фрагменты с неразбираемым именем, пустые или без ссылки в конце:\n  "
            + "\n  ".join(unnamed)
            + "\n\nИмя: <слаг-по-смыслу>.<род>.md, род — "
            + " · ".join(KINDS)
            + "\nПоследняя строка — ссылка на задачу: «#12» или «#12 #13»"
            + "\nУ рода `internal` ПЕРВАЯ строка — причина: "
            + "«> **Потребителю безразлично:** …» (154)"
        )
    return fragments


def fragments_of(paths: list[str]) -> list[Fragment]:
    """Разбирает фрагменты, которые тронуло ИЗМЕНЕНИЕ, и только их.

    Берутся все `.md` под `changelog.d/`, а не только правильно названные:
    иначе файл с негодным именем выпал бы из отбора ровно потому, что негоден,
    и гейт зазеленел бы на том, что обязан отвергнуть (075).
    """
    touched = [
        FRAGMENTS / name.rsplit("/", 1)[-1]
        for name in paths
        if name.startswith(f"{FRAGMENTS}/") and name.endswith(".md") and name.count("/") == 1
    ]
    fragments = parse_fragments(touched)
    # ФОРМА — ТОЛЬКО У НОВОГО (#1172). Выпущенное — источник журнала, и править
    # его задним числом запрещено: предел, применённый к нему, требовал бы ровно
    # этого. Поэтому форму судит гейт изменения, а не общий разбор.
    faults = [f"{one.slug}.{one.kind}.md — {why}" for one in fragments if (why := shape_fault(one))]
    if faults:
        raise NotRun(
            "фрагменты не той формы:\n  "
            + "\n  ".join(faults)
            + f"\n\nТело — не длиннее {FRAGMENT_LINES} строк и {FRAGMENT_CHARS} знаков о том, "
            "что изменилось для потребителя; разбор и замеры — в задачу, во фрагменте — "
            "ссылка на неё. "
            "Заголовок — `###` и ниже: `##` в журнале — уровень версии"
        )
    return fragments


def shape_fault(fragment: Fragment) -> str:
    """Чем фрагмент нарушает форму: заголовок выше `###` или размер тела; пусто — ничем.

    ТЕЛО — все непустые строки, кроме строки-заголовка и последней строки
    ссылки на задачу: подзаголовки `####`, строки блоков кода и строка причины
    рода `internal` в счёт идут. Заголовок ищется только вне заборов блоков
    кода: `# …` в примере shell — комментарий, а не заголовок (взгляд на
    #1174). Всё прочее судится строго, по `content` — см. там.

    ЗАГОЛОВОК НЕ СЧИТАЕТСЯ И У `internal`, где он стоит под причиной; где
    именно он стоит, решает `heading_at` по перечню форм.
    Ссылка снимается, только если она ссылка: разбор отвергает фрагмент без
    неё раньше, но предел не должен молча расти на строку, если сюда придёт
    иной (взгляд на #1174).
    """
    raw = fragment.body.splitlines()
    for one in outside_fences(raw):
        if TOO_HIGH_RE.match(one):
            return f"заголовок выше `###`: «{one}»"
    heading = heading_at(raw)
    lines = [kept for index, one in enumerate(raw) if (kept := one.strip()) and index != heading]
    body = lines[:-1] if lines and LINK_LINE_RE.match(lines[-1]) else lines
    if len(body) > FRAGMENT_LINES:
        return f"тело {len(body)} строк, предел {FRAGMENT_LINES}"
    size = sum(len(one) for one in body)
    if size > FRAGMENT_CHARS:
        return f"тело {size} знаков, предел {FRAGMENT_CHARS}"
    return ""


def opening(line: str) -> str | None:
    """Строка без отступа, если она может начать блок; отступ 4+ — None.

    По CommonMark блок начинается с отступом до трёх пробелов, табуляция —
    до следующей позиции, кратной четырём. Строка глубже — блок кода с
    отступом или ленивое продолжение абзаца, и `# x` в ней не заголовок.
    """
    expanded = line.expandtabs(CODE_INDENT)
    stripped = expanded.lstrip(" ")
    if len(expanded) - len(stripped) >= CODE_INDENT:
        return None
    return stripped.rstrip()


#: Приставка контейнера: цитата `>` или маркер пункта списка. Заголовок
#: внутри контейнера — тот же заголовок: `> # Раздел` и `- # Раздел` в журнале
#: дают h1 (взгляд на #1207).
CONTAINER_RE: Final = re.compile(r"^(?:>\s?|[-*+]\s+|\d{1,9}[.)]\s+)")


def content(line: str) -> str:
    """Строка без отступа и без приставок контейнеров — то, что судит гейт.

    СТРОГОЕ ПРАВИЛО, А НЕ ОЧЕРЕДНАЯ ФОРМА (210). Место получило находки в
    четвёртом заходе подряд: каждый взгляд называл новую вложенность —
    тильды, отступ 4+, пункт списка, цитату. Отступ здесь не решает ничего:
    он снимается целиком, как и `>` и маркеры пунктов, и `# x` под любым из
    них — заголовок. Цена названа: пример кода, отбитый отступом, а не
    забором, отвергается, если в нём `# ` или `## ` в начале строки. Код во
    фрагменте пишется в заборе — ```` ``` ```` или `~~~`.
    """
    one = line.strip()
    while mark := CONTAINER_RE.match(one):
        one = one[mark.end() :].lstrip()
    return one


def outside_fences(raw: list[str]) -> list[str]:
    """Содержимое строк (`content`) вне заборов блоков кода.

    Забор открывают и закрывают оба вида (`FENCE_RE`), закрывает — тот же
    знак не короче открывшего и без строки сведений; незакрытый забор длится
    до конца фрагмента, как в CommonMark. Забор узнаётся и внутри контейнера:
    пункт списка и цитата его несут.
    """
    kept: list[str] = []
    fence = ""
    for line in raw:
        one = content(line)
        if fence:
            if one.startswith(fence) and not one.strip(fence[0]):
                fence = ""
            continue
        if mark := FENCE_RE.match(one):
            fence = mark.group(1) or mark.group(2)
            continue
        kept.append(one)
    return kept


#: Имена HTML-блока вида 6 по CommonMark 0.31 (§4.6), альтернативой выражения:
#: только они и виды 1–5 прерывают абзац. Вид 7 — любой иной тег — абзаца не
#: прерывает, и автоссылка `<https://…>` тоже.
HTML_BLOCK_NAMES: Final = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|"
    "details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h1|"
    "h2|h3|h4|h5|h6|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|"
    "noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|"
    "thead|title|tr|track|ul"
)
#: Начало HTML-блока видов 1–6: `script`/`pre`/`style`/`textarea`, комментарий,
#: инструкция обработки, объявление, CDATA и блочный тег из `HTML_BLOCK_NAMES`.
HTML_BREAKER: Final = (
    r"<(?:(?:script|pre|style|textarea)(?:\s|>|$)|!--|\?|![A-Za-z]|!\[CDATA\["
    r"|/?(?:" + HTML_BLOCK_NAMES + r")(?:\s|/?>|$))"
)
#: ATX-заголовок: от одной до шести решёток и пробел или конец строки. `#1`
#: и `#тег` — абзац, а не заголовок.
ATX_RE: Final = re.compile(r"^#{1,6}(?:\s|$)")
#: Что прерывает абзац цитаты по CommonMark, а не продолжает его лениво:
#: ATX-заголовок, тематический разрыв, НЕпустой
#: пункт маркированного списка, непустой пункт нумерованного с единицы,
#: HTML-блок видов 1–6 — и забор блока кода, но его знает один `FENCE_RE`.
#: Сверяется строка без отступа (`opening`): с отступом 4+ ничто из этого
#: абзаца не прерывает.
PARAGRAPH_BREAKERS: Final = re.compile(
    r"^(?:#{1,6}(?:\s|$)|(?:-[ \t]*){3,}$|(?:\*[ \t]*){3,}$|(?:_[ \t]*){3,}$"
    r"|[-*+]\s+\S|1[.)]\s+\S|" + HTML_BREAKER + ")",
    re.IGNORECASE,
)


def breaks(one: str) -> bool:
    """Прерывает ли строка без отступа абзац: блок из перечня или забор кода."""
    return bool(PARAGRAPH_BREAKERS.match(one) or FENCE_RE.match(one))


def heading_at(raw: list[str]) -> int | None:
    """Индекс строки-заголовка фрагмента среди его СЫРЫХ строк; нет заголовка — None.

    Заголовок — первая непустая строка после ведущего АБЗАЦА цитаты причины.
    Абзац читается по правилам Markdown, а не по приставке строк: строка с
    `>` его продолжает, строка без `>` — тоже, лениво, если только она не
    начинает блок, прерывающий абзац (`PARAGRAPH_BREAKERS`); пустая строка его
    кончает. Строки сырые, с отступом: пустые нужны разбору, а отступ 4+
    решает, начало ли это блока (`opening`).

    ПЕРЕЧЕНЬ ФОРМ, а не очередная. Место получило находки в трёх заходах
    (взгляды на #1181 — жёсткий индекс, затем ленивое продолжение; на #1188 —
    блок кода под цитатой; ещё раз на #1188 — забор тильдами, отступ, HTML
    вида 7), и абзац причины читается по CommonMark (210). Контейнеры здесь
    не разбираются: причина — абзац цитаты верхнего уровня, а высокий
    заголовок внутри контейнера ловит `shape_fault` строго, через `content`.
    Формы: причины
    нет; причина в одну строку `>`; в несколько; с ленивым продолжением, в том
    числе с отступом 4+; вплотную под цитатой — заголовок, забор обоих видов,
    разрыв, непустой пункт списка, HTML видов 1–6; не прерывают — пустой
    пункт, HTML вида 7, автоссылка; цитатой открыт фрагмент не-`internal`;
    заголовка нет; `#1` — не заголовок. Каждая — строкой таблицы в
    `tests/test_journal_fragments.py`.
    """
    lines = [opening(one) for one in raw]
    at = next((index for index, one in enumerate(raw) if one.strip()), len(raw))
    if at < len(raw) and (lines[at] or "").startswith(">"):
        while at < len(raw) and raw[at].strip():
            one = lines[at]
            if one is not None and not one.startswith(">") and breaks(one):
                break
            at += 1
    at = next((index for index in range(at, len(raw)) if raw[index].strip()), len(raw))
    return at if at < len(raw) and ATX_RE.match(lines[at] or "") else None


def render_section(title: str, fragments: list[Fragment]) -> str:
    """Собирает один раздел журнала, группируя фрагменты по роду."""
    lines = [f"## {title}", ""]
    if not fragments:
        lines += ["Пусто.", ""]
        return "\n".join(lines)

    for kind, heading in KINDS.items():
        chosen = [f for f in fragments if f.kind == kind]
        if not chosen:
            continue
        lines += [f"### {heading}", ""]
        for fragment in chosen:
            lines += [fragment.body, ""]
    return "\n".join(lines)


def render(version: str) -> str:
    """Собирает журнал целиком: не выпущенное, затем выпуски от новых к старым."""
    parts = [
        "# Журнал изменений",
        "",
        "> Файл производный: собирается `scripts/build_changelog.py` из фрагментов",
        "> в `changelog.d/`. Руками не правится — правка потеряется при следующей",
        "> сборке (правило 125).",
        "",
        f"Версия контракта — `{version}`, источник `CONTRACT_VERSION`. Что означают",
        f"разряды и что делает потребитель — [`{paths.RELEASE_DOC}`]({paths.RELEASE_DOC}).",
        "",
        render_section("Не выпущено", read_fragments(FRAGMENTS)),
    ]

    released = releases()
    for directory in released[:UNFOLDED_RELEASES]:
        parts.append(render_section(directory.name, read_fragments(directory)))

    folded = released[UNFOLDED_RELEASES:]
    if folded:
        parts.append(render_folded(folded))

    return "\n".join(parts).rstrip() + "\n"


def releases() -> list[Path]:
    """Каталоги выпусков от новых к старым."""
    if not RELEASED.is_dir():
        return []
    return sorted(
        (p for p in RELEASED.iterdir() if p.is_dir()),
        key=lambda p: project_version.digits(p.name) if VERSION_RE.match(p.name) else (0, 0, 0),
        reverse=True,
    )


def render_folded(directories: list[Path]) -> str:
    """Свёрнутые выпуски: строка со ссылкой на источник, а не пропажа.

    Запись не исчезает и не сокращается — она остаётся в каталоге выпуска
    целиком. Свёрнуто только представление, и сказано об этом прямо: раздел,
    молча оборванный на пятом выпуске, читался бы как «раньше ничего не было».
    """
    lines = [
        f"## Выпуски {directories[0].name} и раньше",
        "",
        "Записи не сокращены: каждая лежит в своём каталоге выпуска целиком.",
        f"Развёрнутыми здесь собираются {UNFOLDED_RELEASES} последних — предел у",
        "представления, а не у источника.",
        "",
    ]
    lines += [
        f"- [{directory.name}]({directory.as_posix()}/) — записей: {len(read_fragments(directory))}"
        for directory in directories
    ]
    return "\n".join(lines) + "\n"


def do_release(version: str) -> None:
    """Переносит текущие фрагменты в каталог выпуска, оставляя их источником."""
    if not VERSION_RE.match(version):
        raise NotRun(f"версия выпуска «{version}» не вида МАЖОР.МИНОР.ПАТЧ")
    target = RELEASED / version
    if target.exists():
        raise NotRun(f"выпуск {version} уже собран: {target}")

    moving = [p for p in FRAGMENTS.glob("*.md") if p.name != "README.md"]
    if not moving:
        raise NotRun("выпускать нечего: ни одного фрагмента — это ошибка входа, а не пустой выпуск")

    target.mkdir(parents=True)
    for path in moving:
        # Переезд МЕНЯЕТ АДРЕС ФАЙЛА, а значит и смысл его относительных
        # ссылок. Перенести текст дословно значит увезти рабочие ссылки в
        # пустоту — ровно это и случилось на выпуске 1.0.0.
        text = relink(path.read_text(encoding="utf-8"), was=path.parent, now=target)
        shutil.move(str(path), str(target / path.name))
        (target / path.name).write_text(text, encoding="utf-8")
    print(f"в выпуск {version} перенесено фрагментов: {len(moving)}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собирает журнал, сверяет его или закрывает выпуск."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="сверить, не записывая")
    parser.add_argument(
        "--fragments",
        action="store_true",
        help="проверить только фрагменты: имя, непустоту, ссылку в конце",
    )
    parser.add_argument("--release", metavar="ВЕРСИЯ", help="закрыть выпуск: перенести фрагменты")
    parser.add_argument("--base", default="", help="ветка сравнения для --fragments")
    args = parser.parse_args(argv)

    try:
        if args.fragments:
            # ПРЕДМЕТ ПРОВЕРКИ — ТО, ЧТО ПРИЕЗЖАЕТ С ИЗМЕНЕНИЕМ, и раньше это
            # было сказано комментарием, а сделано наоборот: разбирался весь
            # каталог целиком. Разница не отвлечённая. Выпуск переносит
            # фрагменты в `changelog.d/released/`, и сразу после него каталог
            # пуст — гейт валился третьим исходом на первом же изменении, хотя
            # своё оно принесло. Ни версия, ни собранный файл здесь не нужны:
            # их спрашивает выпуск, а изменение отвечает за свой фрагмент.
            mine = fragments_of(journal.changed_files(journal.base_from_env(args.base)))
            if not mine:
                # Законное состояние, а не «нечего проверять»: нужен ли
                # изменению фрагмент вообще, решает `check_journal.py` — он и
                # отвергает изменение без него. Краснеть здесь вторым разом
                # значило бы завести второй источник того же решения (022).
                print("изменение не несёт фрагментов — их наличие спрашивает check_journal")
                return EXIT_OK
            print(f"фрагменты изменения разбираются: {len(mine)}")
            return EXIT_OK

        if args.release:
            do_release(args.release)
        version = project_version.declared()
        assembled = render(version)

        if args.check:
            current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
            if current != assembled:
                print(
                    f"{OUTPUT} расходится со сборкой из фрагментов.\n"
                    "Соберите заново: python scripts/build_changelog.py",
                    file=sys.stderr,
                )
                return EXIT_DIFFERS
            print(f"{OUTPUT} совпадает со сборкой")
            return EXIT_OK

        OUTPUT.write_text(assembled, encoding="utf-8")
        print(f"{OUTPUT} собран, версия контракта {version}")
        return EXIT_OK
    except (NotRun, journal.NotRun, project_version.NotRun) as exc:
        print(f"сборка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    raise SystemExit(main())
