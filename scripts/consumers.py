#!/usr/bin/env python3
"""Сверка потребителей: кто подключён, на какой версии стоит и что обошёл.

ОТДАЁТСЯ НАРУЖУ: этим заходом потребитель проверяет, что его видно.

ФАКТЫ О ПОТРЕБИТЕЛЕ ЧИТАЮТСЯ У НЕГО, А НЕ ВЕДУТСЯ У НАС. Версия, на которой он
стоит, и то, какие шаги он обошёл, лежат в ЕГО `.pipeline.yml`: факты о проекте
публикует сам проект (174). Реестр, ведомый за потребителя, разошёлся бы с ним
молча — и разошёлся бы в ту сторону, где мы считаем, что всё хорошо.

АДРЕСА ВСЁ ЖЕ НАШИ. Прочитать чужой ответ можно только зная, у кого спрашивать,
и за то, кого оповещать при смене версии контракта, отвечаем мы
([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)).
Поэтому в `.rules/consumers.json` лежат адреса, и только они.

ПОДКЛЮЧЁННЫЙ МОЛЧА ТОЖЕ ПОДКЛЮЧЁН (решение владельца 16.10.2026, #1389).
Взять шаг проще, чем сказать о взятом: замер 16.10.2026 — в реестре ни одной
записи, а обход семьи застаёт проекты, зовущие наши шаги по тегу. Поэтому к
объявленным адресам добавляются те, кого застал обход (`family_uptake.py
--out`, ключ `--uptake`); имена сравниваются без учёта регистра, как у обхода.
Обход не передан или прочитал семью не всю — это сказано: молча подключившиеся
тогда видны не все, и пустота не значит «никого» (045).

ОБХОД — ГЛАВНОЕ, ЧТО ЗДЕСЬ ВИДНО. Потребитель, обошедший общий механизм, —
сильнейшее свидетельство пробела, и оно невидимо, пока не объявлено: снаружи
обход неотличим от «шаг не подключён»
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).

ПУСТОЙ СПИСОК — СОСТОЯНИЕ, А НЕ ОТКАЗ. До 22.10.2026 подключённых не было, и
заход говорил это словом; первым объявлен каталог (#1579). Считать пустоту
поломкой значило бы требовать наличия потребителей, а считать её тишиной —
выдавать незнание за «всё хорошо»
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ЧЕГО ЗАХОД НЕ ДЕЛАЕТ: не заводит потребителей и не правит их деревья.
Подключение — их решение, и след ведёт его владелец
([185](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/185-a-trail-is-an-address-and-its-owner-keeps-it-alive.md)).

Исходы (правило 039): ``0`` сверка прочитана · ``2`` не отработал ·
``3`` часть не прочитана — ответов потребителей или самих потребителей: обход
не передан или прочитал семью не всю. Сказано, а не выдано за «все на свежей».
"""

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any, Final

import ghrest
import paths
import pipeline_checks as policy

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_UNREAD: Final = 3

#: Ключ со списком записей. Прочее в файле — пояснения, и читать их нечем.
CONNECTED: Final = "connected"
#: Что обязана назвать запись. Список разрешительный: поле, которого здесь нет,
#: в запись не попадает молча (068).
REQUIRED: Final = ("repo", "since", "why")
#: Как читается «подключённых нет»: состояние, а не тишина.
NOBODY: Final = "подключённых потребителей нет"
#: Итог захода без обхода семьи — ОДНОЙ строкой и одним текстом: вступлением и
#: итогом она печаталась дважды (находка `f4a5c14`), и тест по началу строки их
#: не различал (`d380055`).
NO_SWEEP: Final = (
    "обход семьи не передан (--uptake): молча подключённые НЕ ВИДНЫ — сверка идёт "
    "только по объявившимся и потому неполна (045)"
)
#: Итог захода без токена площадки: ответы лежат в деревьях потребителей.
NO_TOKEN: Final = (
    "ответы потребителей НЕ ПРОЧИТАНЫ: токена площадки нет, а лежат они в их деревьях."
    " Это не «все на свежей версии» (045)"
)


class NotRun(RuntimeError):
    """Заход не отработал: третий исход, а не пустая сверка."""


def registry(root: Path) -> list[dict[str, Any]]:
    """Объявленные адреса потребителей — из реестра, а не из памяти."""
    path = root / paths.CONSUMERS
    if not path.is_file():
        raise NotRun(f"нет {path}: у кого спрашивать, взять неоткуда (075)")
    try:
        said = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NotRun(f"{path} не разбирается: {exc}") from exc
    # ФОРМА ПРОВЕРЯЕТСЯ СВЕРХУ ВНИЗ, И КАЖДЫЙ ПРОМАХ — ОБЪЯВЛЕННЫЙ ИСХОД.
    # Прежде верх реестра и его записи принимались на веру: список вместо
    # словаря или строка вместо записи роняли `AttributeError` МИМО `NotRun` —
    # то есть мимо исхода, который модуль сам и объявляет (039). Снаружи такой
    # сбой неотличим от поломки механизма, а не от ошибки входа (075).
    # Нашёл внешний взгляд (`0612be4`).
    if not isinstance(said, dict):
        raise NotRun(f"{path}: реестр не словарь — читать нечего")
    rows = said.get(CONNECTED)
    if not isinstance(rows, list):
        raise NotRun(f"{path}: раздел «{CONNECTED}» не список — читать нечего")
    for one in rows:
        if not isinstance(one, dict):
            raise NotRun(f"{path}: запись «{one}» не словарь — адрес из неё не прочесть")
        missing = [field for field in REQUIRED if not str(one.get(field, "")).strip()]
        if missing:
            raise NotRun(f"{path}: запись {one} не называет {', '.join(missing)}")
    return [dict(one) for one in rows]


def swept(path: Path) -> tuple[list[str], list[str]]:
    """Кого обход семьи застал зовущим наши шаги — и кого он не прочитал.

    Форма файла — его, а не наша: раздел `by` со строкой на взявшего и
    `projects.unread_repos` — проекты, чьё дерево обход не прочитал. Другая
    форма — отказ, а не пустой список: пустота значила бы «никто не взял» (045).
    Непрочитанные отдаются вторым списком: без них «найден обходом» о части
    семьи читался бы как обо всей.
    """
    try:
        said = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NotRun(f"обход семьи {path} не прочитан: {exc}") from exc
    rows = said.get("by") if isinstance(said, dict) else None
    if not isinstance(rows, list):
        raise NotRun(f"{path}: раздела «by» нет — это не файл обхода семьи")
    # Повторы — без регистра, как и сверка с объявленными (находка `e775d7d`):
    # регистр имени у площадки не значим, и одно слово в двух смыслах здесь
    # давало бы `Owner/Repo` и `owner/repo` двумя найденными. Первое написание
    # остаётся.
    spelled: dict[str, str] = {}
    for one in rows:
        if isinstance(one, dict) and one.get("repo"):
            spelled.setdefault(str(one["repo"]).casefold(), str(one["repo"]))
    found = sorted(spelled.values())
    projects = said.get("projects")
    unread = projects.get("unread_repos") if isinstance(projects, dict) else None
    # Непрочитанные сводятся так же (взгляд на #1483): иначе повтор в другом
    # регистре давал бы две строки и лишнюю единицу в счёте непрочитанных.
    unspelled: dict[str, str] = {}
    for one in unread or []:
        if one:
            unspelled.setdefault(str(one).casefold(), str(one))
    return found, sorted(unspelled.values())


def answer_of(repo: str, token: str) -> dict[str, Any]:
    """Ответ потребителя по проверкам — из ЕГО дерева, а не из нашего реестра.

    Читается общая ветка: она и есть то, что у него работает. Отказ здесь —
    третий исход захода, а не пустой ответ: «файла не видно» и «обходов нет»
    снаружи неотличимы (045).
    """
    got = ghrest.request("GET", f"repos/{repo}/contents/{paths.PIPELINE}", token)
    if not isinstance(got, dict) or "content" not in got:
        raise NotRun(f"{repo}: ответ по проверкам не прочитан")
    raw = base64.b64decode(str(got["content"])).decode("utf-8")
    # РАЗБОР ФОРМЫ — У ТОГО, КТО ФОРМОЙ ВЛАДЕЕТ. Свой разбор YAML здесь был
    # бы вторым пониманием ответа по проверкам, и разошлись бы они молча (090).
    try:
        return policy.answer_text(raw, repo)
    except policy.BadPolicy as exc:
        raise NotRun(str(exc)) from exc


def bypassed(answer: dict[str, Any]) -> list[str]:
    """Шаги, которые потребитель ОБОШЁЛ, — по его же объявлению.

    Обход объявляется классом `off` с причиной. Без причины это не состояние,
    а молчание, и такую запись заход называет отдельно.
    """
    found: list[str] = []
    for name, said in (answer.get("checks") or {}).items():
        # ЗАПИСЬ РАЗБИРАЕТ ТОТ, КТО ВЛАДЕЕТ ФОРМОЙ. Форм у неё две — голый класс
        # и словарь, — а YAML 1.1 вдобавок читает `off` БУЛЕВЫМ. Свой разбор был
        # бы вторым пониманием: разошлись бы они молча, а объявленный обход стал
        # бы невидимым ровно там, где он и объявлен (090, 022).
        klass, why, _ = policy.entry_of(said)
        if klass != policy.OFF:
            continue
        found.append(f"{name}" + ("" if why else " — БЕЗ ПРИЧИНЫ"))
    return sorted(found)


def gaps_of(*, swept_given: bool, unswept: int, unread: int, total: int, token: bool) -> list[str]:
    """Итоги неполноты захода — все разом, в stdout; пусто — сверка полна.

    ВСЕ ИСХОДЫ НЕПОЛНОТЫ — ОДНИМ ПУТЁМ (взгляд на #1483, правило 210). Прежде
    каждый выход захода называл свою неполноту сам: ранний выход без токена или
    с непрочитанными ответами молчал о том, что обход не передан, а итог «НЕ
    ПРОЧИТАНЫ» шёл в stderr, хотя однородные с ним — в stdout. Это была уже
    вторая находка о потоке и полноте итога (после `9695b0a`), поэтому выходы
    говорят через одну функцию, а не каждый своё.
    """
    said: list[str] = []
    if not token:
        said.append(NO_TOKEN)
    if unread:
        said.append(f"не прочитано ответов: {unread} из {total}")
    if unswept:
        said.append(f"обход семьи не прочитал проектов: {unswept} — список выше неполон")
    if not swept_given:
        said.append(NO_SWEEP)
    return said


def finish(gaps: list[str]) -> int:
    """Печатает итоги неполноты и отдаёт исход: есть они — 3, нет — 0."""
    for one in gaps:
        print(one)
    return EXIT_UNREAD if gaps else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает сверку по каждому объявленному потребителю."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень ЭТОГО дерева")
    parser.add_argument("--uptake", type=Path, help="файл обхода семьи (`family_uptake.py --out`)")
    args = parser.parse_args(argv)

    try:
        rows = registry(args.root)
        found, unswept = swept(args.uptake) if args.uptake else ([], [])
    except NotRun as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    # Регистр имени у площадки не значим: обход сравнивает через `casefold`,
    # и `Owner/Repo` в реестре с `owner/repo` из обхода — один проект.
    declared = {str(one["repo"]).casefold() for one in rows}
    for repo in found:
        if repo.casefold() not in declared:
            print(f"  {repo}: найден обходом семьи, не объявлялся")
            rows.append({"repo": repo})
    for repo in unswept:
        print(f"  {repo}: обход семьи его дерево не прочитал — подключён ли он, не видно")

    swept_given = args.uptake is not None
    if not rows:
        if not swept_given or unswept:
            print(f"{NOBODY} среди тех, кого видно, — молча подключённые видны не все (045)")
            return finish(
                gaps_of(
                    swept_given=swept_given, unswept=len(unswept), unread=0, total=0, token=True
                )
            )
        print(f"{NOBODY} — сверять не с кем, и это состояние, а не тишина (154)")
        return EXIT_OK

    token = ghrest.token_from_env()
    if not token:
        return finish(
            gaps_of(
                swept_given=swept_given,
                unswept=len(unswept),
                unread=0,
                total=len(rows),
                token=False,
            )
        )

    unread = 0
    for one in rows:
        repo = str(one["repo"])
        try:
            answer = answer_of(repo, token)
        except (NotRun, ghrest.TransportError) as exc:
            print(f"  {repo}: не прочитан — {exc}", file=sys.stderr)
            unread += 1
            continue
        span = str(answer.get("contract") or "не объявлен")
        skipped = bypassed(answer)
        print(f"  {repo}: диапазон {span} · обойдено {len(skipped)}")
        for name in skipped:
            print(f"      обойдено: {name}")
    # ИТОГ НЕПОЛНОТЫ — В ОДНОМ ПОТОКЕ (находка `9695b0a`) и ОДНИМ ПУТЁМ
    # (`gaps_of`): итоговые строки — в stdout, где и остальные исходы; отказ по
    # отдельному проекту — диагностика, она остаётся в stderr. Без обхода
    # список неполон и при непустом реестре (поздний взгляд на #1443).
    return finish(
        gaps_of(
            swept_given=swept_given,
            unswept=len(unswept),
            unread=unread,
            total=len(rows),
            token=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
