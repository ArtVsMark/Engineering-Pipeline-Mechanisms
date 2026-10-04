#!/usr/bin/env python3
"""Гейт: запись решения называет судьбу правила, а не молчит о ней.

ПРАВИЛА РОЖДАЮТСЯ ЗДЕСЬ, И КАНАЛ ДЛЯ ЭТОГО ЕСТЬ. `.rules/proposals.json` —
очередь на приём в общий каталог, и она РАБОТАЛА: 11.09.2026 каталог принял
четыре наших предложения, и они стали правилами 198–201.

ЧЕГО НЕТ — МОМЕНТА, В КОТОРЫЙ ВОПРОС ЗАДАЮТ. У всякой другой обязанности
проекта момент есть: слияние, расписание, прогон. А «не родилось ли здесь
правило» не спрашивается никогда и ни у кого — это решалось наитием.

ЗАМЕР 16.09.2026: записей решений в дереве 27, из них **16 появились после
12.09.2026**, и предложений каталогу за то же время — **ноль**. Число само по
себе ничего не доказывает: почти все те решения и правда свои. Доказывает
другое — пустая очередь НЕОТЛИЧИМА от «никто не спросил», а такое состояние
правило
[045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)
и запрещает. Сам файл объявляет пустоту законной — и законной она остаётся; речь
не о ней, а о том, что за ней не видно ответа.

ГЕЙТ НЕ РЕШАЕТ, ПРАВИЛО ЭТО ИЛИ НЕТ. Из дерева это не следует, и решать за
человека он не берётся
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
Он требует ОТВЕТА — любого из двух, — и отвергает молчание.

СУДИТ ТОЛЬКО ДОБАВЛЕННЫЕ ЗАПИСИ. Двадцать семь прежних строки не несут, и
требовать её от них значило бы переписывать принятые решения задним числом —
ровно то, что запрещает
[043](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/043-decisions-are-superseded-not-edited.md).
Тот же приём у гейта «новое приезжает со своим прогоном»: предмет — прирост, а не
дерево целиком.

ВТОРОЙ ПРЕДМЕТ — РОД НАХОДКИ У ПОРОГА ПОВТОРА (#650). Класс ошибки,
встреченный трижды, спрашивается о правиле в том изменении, которым дошёл до
порога; ответ живёт в самом роде (`.rules/finding-kinds.json`, поле
`каталогу`). ГРАНИЦА: инциденты источников 0–2 — краснота общей ветки,
конфликт и красное на своём изменении — живут в реестре красноты, а у его
записей нет рода: повтор там узнаётся по имени задания, и мигающее задание
уходит в список перезапуска со своей причиной (`.rules/rerun.json`).
Спрашивать правило у мигания площадки — не про то, и гейт этого не делает
(`d4ae968`).

Исходы (правило 039): ``0`` ответ есть у каждой новой записи и у каждого рода,
дошедшего до порога · ``1`` запись или род молчит · ``2`` гейт не отработал.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import check_journal
import finding_kinds
import paths
import trunk_log

EXIT_OK: Final = 0
EXIT_FOUND: Final = 1
EXIT_BROKEN: Final = 2

#: Строка ответа. Два вида, и оба названы: «предложено» несёт слаг предложения,
#: «своё» — причину, почему каталогу это не нужно. Третьего вида нет намеренно:
#: «потом посмотрим» — это и есть молчание, только записанное.
FATE_RE: Final = re.compile(
    r"^\*\*Каталогу:\*\*\s+(?P<kind>предложено|своё)\s+—\s+(?P<said>\S.*)$", re.M
)


class NotRun(RuntimeError):
    """Гейт не отработал: третий исход, а не «ответ есть»."""


def added(base: str, head: str = "HEAD", root: Path = Path()) -> list[str]:
    """Записи решений, ДОБАВЛЕННЫЕ этим изменением.

    Список путей читается по NUL: без него git экранирует имена с не-ASCII, и
    такой путь молча выпадает из отбора
    ([165](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/165-git-file-list-needs-nul.md)).

    Список берётся у того же дерева, что и тексты записей (`text_at` с
    `cwd=root`): прежде git звался в текущем каталоге, и при `--root`, отличном
    от него, список записей шёл из одного репозитория, а их тексты — из другого
    (`5204a74`).
    """
    try:
        done = subprocess.run(
            ["git", "diff", "--diff-filter=A", "--name-only", "-z", f"{base}..{head}"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise NotRun(f"состав изменения не прочитан ({base}..{head}): {exc}") from exc
    return [
        path
        for path in done.stdout.split("\0")
        if path.startswith(f"{paths.DECISIONS}/") and path.endswith(".md") and "README" not in path
    ]


def fate(text: str) -> tuple[str, str] | None:
    """Ответ записи о судьбе правила: вид и сказанное; ``None`` — ответа нет."""
    found = FATE_RE.search(text)
    return (found["kind"], found["said"].strip()) if found else None


def text_at(ref: str, path: str, root: Path = Path()) -> str | None:
    """Текст файла у состояния `ref`; ``None`` — файла у этого состояния нет.

    ВСЁ, ЧТО СУДИТ ГЕЙТ, ЧИТАЕТСЯ У ОДНОГО СОСТОЯНИЯ. Роды, записи решений и
    очередь предложений прежде брались кто откуда: роды — у головы через git,
    записи и очередь — с диска корня. При голове, отличной от выгруженного
    дерева, род с неотправленным предложением проходил по чужой очереди, а
    закоммиченная правка записи не судилась вовсе (`bd9fa54`, `d5151c5`).

    ФАЙЛА НЕТ — ЭТО ОТВЕТ, А НЕ ОТКАЗ; всё прочее — неизвестное состояние,
    битый клон — отказ. Формы отказа git берутся у шага журнала, а не пишутся
    второй раз (`493815f`, `783fb08`).
    """
    try:
        done = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise NotRun(f"{path} у {ref} не прочитан: {exc}") from exc
    if done.returncode == 0:
        return done.stdout
    if any(said in done.stderr for said in check_journal.NO_SUCH_PATH):
        return None
    raise NotRun(f"{path} у {ref} не прочитан: {done.stderr.strip()}")


def queued(head: str, root: Path = Path()) -> str:
    """Очередь предложений у головы изменения; её нет — отказ, как у плана.

    Как ищется слаг — у словаря родов (`finding_kinds.queued`): ищется
    вхождением, а очереди нет — отказ, а не пустая очередь.
    """
    where = paths.PROPOSALS.as_posix()
    text = text_at(head, where, root)
    if text is None:
        raise NotRun(f"очередь предложений не прочитана: {where} у {head} нет")
    return text


#: Слаг ответа разбирает словарь родов — одна разборка на решения и роды (022).
#: История разборки переехала вместе с функцией: `finding_kinds.slug_of`.
slug_of = finding_kinds.slug_of


def missing(paths_: list[str], queue: str, head: str = "HEAD", root: Path = Path()) -> list[str]:
    """Записи, чей ответ отсутствует или не сходится с очередью; читаются у головы."""
    told: list[str] = []
    for one in paths_:
        text = text_at(head, one, root)
        if text is None:
            raise NotRun(f"{one} добавлен изменением, а у {head} его нет")
        said = fate(text)
        if said is None:
            told.append(
                f"  {one}: нет строки «**Каталогу:** предложено — <слаг>» "
                "или «**Каталогу:** своё — <причина>»"
            )
            continue
        kind, what = said
        if kind != "предложено":
            continue
        slug = slug_of(what)
        # ПУСТОЙ СЛАГ — НЕ СОВПАДЕНИЕ, А ОТСУТСТВИЕ ИМЕНИ. Сверка идёт вхождением
        # в текст очереди, а пустая строка входит в ЛЮБОЙ текст: ответ
        # «предложено — ``» проходил гейт целиком. Нашёл внешний взгляд на #428;
        # соседний тест даже держал, что `slug_of("``")` даёт пустую строку, —
        # и последствия этого не замечал.
        if not slug:
            told.append(
                f"  {one}: ответ «предложено», а имени предложения нет — "
                "пустое имя совпадает с любой очередью и потому не ответ (045)"
            )
        elif slug not in queue:
            told.append(
                f"  {one}: назван слаг «{slug}», а в очереди предложений "
                f"({paths.PROPOSALS}) его нет — ответ обещает то, чего не отправили"
            )
    return told


def kinds_at(ref: str, root: Path = Path()) -> dict[str, Any]:
    """Роды находок у состояния `ref` — базы или головы; файла нет — родов не было.

    Разбор общий со словарём родов (`finding_kinds.kinds_in`): не та форма —
    отказ у любого читателя, а не трасса у одного (`948f893`).
    """
    where = paths.FINDING_KINDS.as_posix()
    text = text_at(ref, where, root)
    # ФАЙЛА НЕТ У СОСТОЯНИЯ — ЭТО «РОДОВ НЕ БЫЛО», А НЕ ОТКАЗ: молча принять
    # пустоту при битом клоне значило бы объявить новыми все роды разом, и
    # этот случай отличает `text_at`.
    if text is None:
        return {}
    return finding_kinds.kinds_in(text, f"{where} у {ref}")


def crossed(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Роды, которые дошли до порога повтора ЭТИМ изменением.

    ВТОРОЙ МОМЕНТ ВОПРОСА, И ОН О ИНЦИДЕНТАХ (#650). Запись решения спрашивали
    о правиле с 16.09.2026, а класс ошибки, повторившийся трижды, — никогда:
    род чинили, закрывали механизмом, и на этом всё. Замер 23.09.2026: родов у
    порога восемь, ответа каталогу нет ни у одного. Спрашивается ПРИРОСТ, как и
    у решений: род, дошедший до порога раньше, требовать ответа задним числом
    не заставляет — его называет план, разделом 5.

    Встречи здесь — уже сведённые со строками `Род:` истории
    (`with_history`, #1022): прирост бывает и правкой словаря, и строкой в
    коммите ветки.
    """
    at = finding_kinds.REPEATED_AT

    def times(kinds: dict[str, Any], name: str) -> int:
        return len((kinds.get(name) or {}).get("встречен") or [])

    return sorted(name for name in after if times(after, name) >= at > times(before, name))


def thawed(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Роды, чей замороженный список `встречен` изменение тронуло (решение 038).

    СПИСОК НЕ РАСТЁТ И НЕ УБЫВАЕТ. Рост по привычке возвращает горячую точку,
    ради которой словарь заморожен: каждое слияние снова конфликтовало бы у
    всех открытых веток. Убыль молча уносит встречи до 04.10.2026 из счёта.
    Новый род приходит с пустым списком — его встречи едут строками `Род:`;
    исчезнувший род уносит свои встречи, и это тоже называется (взгляд на
    #1089).

    ПЕРЕИМЕНОВАНИЕ И СЛИЯНИЕ — ЗАКОННАЯ ПРАВКА, и у неё есть путь (взгляд на
    #1090): нынешнее имя несёт поле «прежде» со старыми именами, и его список —
    ровно их встречи. Старое имя тогда исчезает законно, а строки `Род:` со
    старым именем счёт относит к нынешнему (`finding_kinds.successor_of`).

    СВЕРЯЕТСЯ МНОЖЕСТВО ВСТРЕЧ, А НЕ СПИСОК. Снять дубль законно: встреча,
    записанная дважды, завышала счёт, и после снятия встреч не меньше
    (взгляд на #1077, `0ff657e`). Порядок записей смысла не несёт.
    """
    told: list[str] = []

    def met(kinds: dict[str, Any], name: str) -> list[str]:
        return [str(one) for one in (kinds.get(name) or {}).get("встречен") or []]

    successor = finding_kinds.successor_of(after)
    for name in sorted(before):
        if name not in after and name not in successor:
            told.append(
                f"  род «{name}» исчез — его замороженные встречи пропали бы из счёта; "
                f"переименование или слияние называется полем «{finding_kinds.PREVIOUS}» "
                "у нынешнего имени"
            )
        elif (
            name in after
            and name not in successor.values()
            and set(met(after, name)) != set(met(before, name))
        ):
            told.append(
                f"  у рода «{name}» изменён замороженный список «встречен» — новая встреча "
                "пишется строкой «Род:» под снятием в коммите"
            )
    # ПЕРЕИМЕНОВАНИЕ И СЛИЯНИЕ (взгляд на #1090): у нынешнего имени с полем
    # «прежде» список — ровно встречи прежних имён (и свои, если род был).
    for name in sorted(set(successor.values())):
        olds = [old for old, new in successor.items() if new == name]
        wanted = {one for old in [*olds, name] for one in met(before, old)}
        if set(met(after, name)) != wanted:
            told.append(
                f"  у рода «{name}» список «встречен» не равен встречам его прежних имён "
                f"({', '.join(olds)}) — при переименовании и слиянии встречи переносятся целиком"
            )
    # СТАРОЕ ИМЯ УХОДИТ, А «ПРЕЖДЕ» НЕ УБЫВАЕТ (взгляд на #1093). Имя, названное
    # в «прежде», но оставшееся в словаре, считало бы свои встречи дважды, а
    # строки `Род:` истории отдавало бы преемнику. Снятое «прежде» или цепочка
    # A→B→C без A у C уронили бы строки `Род: A` в «вне словаря».
    for old in sorted(set(successor) & set(after)):
        told.append(
            f"  род «{old}» назван в «{finding_kinds.PREVIOUS}» у «{successor[old]}», но "
            "остался в словаре — при переименовании старое имя уходит"
        )
    for old in sorted(set(finding_kinds.successor_of(before)) - set(successor)):
        told.append(
            f"  прежнее имя «{old}» выпало из «{finding_kinds.PREVIOUS}» — строки `Род: {old}` "
            "истории ушли бы из счёта; при новом переименовании оно переносится к новому имени"
        )
    for name in sorted(set(after) - set(before) - set(successor.values())):
        if met(after, name):
            told.append(
                f"  новый род «{name}» пришёл с непустым «встречен» — его встречи едут "
                "строками «Род:», а список у нового рода пуст"
            )
    return told


def known_at(head: str, root: Path = Path()) -> frozenset[str]:
    """Номера правил, на которые дерево отвечает у головы, — чем сверять ответ «есть» (#887).

    ВСЕ ОТКАЗЫ НАЧИНАЮТСЯ С `finding_kinds.ANSWERS_UNREAD`, как у `known_rules`
    (взгляды на #893, #899, 210): файла нет, git его не прочёл (`text_at`) и
    файл не разбирается или не той формы (`rule_numbers`).
    """
    where = str(paths.BINDINGS)
    try:
        text = text_at(head, where, root)
    except NotRun as exc:
        raise NotRun(f"{finding_kinds.ANSWERS_UNREAD}: {exc}") from exc
    if text is None:
        raise NotRun(f"{finding_kinds.ANSWERS_UNREAD}: {where} у {head} нет")
    try:
        return finding_kinds.rule_numbers(text)
    except ValueError as exc:
        raise NotRun(
            f"{finding_kinds.ANSWERS_UNREAD}: {where} у {head} не разбирается: {exc}"
        ) from exc


def kinds_missing(
    names: list[str], after: dict[str, Any], queue: str, known: frozenset[str] | None = None
) -> list[str]:
    """Роды у порога, чей ответ каталогу отсутствует или не сходится."""
    told: list[str] = []
    for name in names:
        problem = finding_kinds.answer_problem(after[name], queue, known)
        if problem is not None:
            told.append(f"  род «{name}» дошёл до порога: {problem}")
    return told


def main(argv: list[str] | None = None) -> int:
    """Точка входа: у каждой новой записи решения назван ответ каталогу."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="база изменения")
    parser.add_argument("--head", default="HEAD", help="голова изменения")
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    args = parser.parse_args(argv)

    try:
        new = added(args.base, args.head, args.root)
        queue = queued(args.head, args.root)
        told = missing(new, queue, args.head, args.root)
        # РОДЫ ЧИТАЮТСЯ У ТОГО ЖЕ СОСТОЯНИЯ, ЧТО ЗАПИСИ И ОЧЕРЕДЬ: «до» — у
        # базы, «после» — у головы, все через git. Прежде «после» читалось с
        # диска корня, а записи — диапазоном коммитов, и незакоммиченная правка
        # словаря судилась, а закоммиченная в другом коммите — нет (`c9a1c47`).
        # Словаря нет у головы — роды не ведутся, и это не отказ: шаг журнала
        # переносим, и у потребителя словаря может не быть вовсе.
        after = kinds_at(args.head, args.root)
        grown: list[str] = []
        frozen: list[str] = []
        if after:
            base_kinds = kinds_at(args.base, args.root)
            frozen = thawed(base_kinds, after) if base_kinds else []
            # ВСТРЕЧИ — СЛОВАРЬ ПЛЮС ИСТОРИЯ GIT, А НЕ ВЕТКА `badges` (решение
            # владельца 03.10.2026, #1022). «До» — история базы, «после» — она
            # же и коммиты изменения: строка `Род:` в них уедет в тело
            # уплотнения. Сводит та же функция, что у архива и плана; мелкий
            # клон — отказ, а не тихий недосчёт (045). ПРЕДЕЛ НАЗВАН (195):
            # слияния без уплотнения строк `Род:` в истории не оставляют
            # (`trunk_log.unseen`); прирост гейт берёт из коммитов изменения, и
            # на него этот предел не влияет.
            history = trunk_log.merged_bodies(args.root, args.base)
            own = trunk_log.branch_bodies(args.base, args.head, args.root)
            before, _ = finding_kinds.with_history(base_kinds, history)
            after, _ = finding_kinds.with_history(after, [*history, *own])
            grown = crossed(before, after)
        told += kinds_missing(
            grown, after, queue, known_at(args.head, args.root) if grown else None
        )
    except (NotRun, finding_kinds.NotRun, trunk_log.NotRun) as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    # ЗАПИСЕЙ НЕ ДОБАВЛЕНО — ЗАКОННОЕ СОСТОЯНИЕ, И ТОЛЬКО ЗДЕСЬ. Изменение без
    # решения этому правилу не подчиняется; требовать предмета от него значило бы
    # красить исправную работу. Это НЕ тот случай, где пустота подозрительна: у
    # гейта есть свой прогон на подделках, и он держит оба отказа.
    if frozen:
        print(f"замороженный словарь родов тронут ({len(frozen)}):", file=sys.stderr)
        for one in frozen:
            print(one, file=sys.stderr)
        # Отказ о каталоге не теряется за отказом о заморозке: чинить оба.
        for one in told:
            print(one, file=sys.stderr)
        return EXIT_FOUND
    if not new and not grown:
        print("записей решений не добавлено и порога род не перешёл — вопрос о правиле не встаёт")
        return EXIT_OK
    if told:
        print(
            f"новых записей решений: {len(new)}, родов у порога: {len(grown)}, "
            f"без ответа каталогу: {len(told)}",
            file=sys.stderr,
        )
        for one in told:
            print(one, file=sys.stderr)
        print(
            "\nОтвет обязан быть любым из двух, но обязан быть: правило либо "
            "предложено общему каталогу, либо объявлено своим с причиной. Гейт не "
            "решает, какое из двух, — он не даёт промолчать (154).",
            file=sys.stderr,
        )
        return EXIT_FOUND
    print(f"новых записей решений: {len(new)}, у каждой назван ответ каталогу")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
