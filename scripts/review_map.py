#!/usr/bin/env python3
"""Карта для внешнего взгляда: куда смотреть, потому что машина туда не смотрит.

ЗАЧЕМ КАРТА. Ревьюер без неё ищет вслепую и находит что попало — в том числе
то, что уже держит гейт. Замер 10.09.2026, из-за которого механизм и появился:
в промпте ревью списком стояли десять правил «спрашивай по существу», и семь из
них к тому дню уже держались гейтами. То есть внешний взгляд — самый дорогой
канал проекта — тратился на работу, которую машина делает бесплатно и точнее.

СПИСОК СОБИРАЕТСЯ МЕХАНИЗМОМ, А НЕ ПАМЯТЬЮ АВТОРА ПРОМПТА. Тот список был
вписан руками и устарел молча — ровно как всякое второе место, где то же знание
ведётся отдельно
([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
Здесь он выводится из ответа проекта каталогу: правило с механизмом — забота
машины, правило с документом — забота глаз.

КАРТА БЕРЁТСЯ ИЗ БАЗЫ, А НЕ ИЗ ГОЛОВЫ ИЗМЕНЕНИЯ, И ЭТО НЕ ПЕДАНТИЗМ. Голову
пишет тот, кого проверяют. Изменение, правящее `.rules/bindings.json`, могло бы
объявить все правила машинными и получить ревью, которому некуда смотреть
([085](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/085-content-from-the-subject-is-untrusted-input-to-the-prompt.md)).
Поэтому ответ читается из общей ветки — а правку самого ответа карта называет
отдельной строкой: это то, на что смотреть надо в первую очередь.

ЗАГОЛОВКИ ПРАВИЛ — ИЗ ВЫГРУЗКИ КАТАЛОГА, И ИХ ОТСУТСТВИЕ НЕ МОЛЧИТ. Без сети
остаются номера, и карта говорит об этом вслух: «номер без заголовка» — рабочее
состояние, «заголовки не пришли» — то, что надо знать читателю (045).

Исходы (правило 039): ``0`` карта собрана · ``2`` шаг не отработал.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import catalogue
import ghrest
import kinds
import paths

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Роды ответа, означающие «держит машина». Тот же состав, что у разреза семьи
#: и у дрейфа: три понимания одного слова разошлись бы молча (090).
#: Виды механизма — из общего места: четыре копии одного набора разъехались
#: бы молча (090). Разбор см. `scripts/kinds.py`.
MACHINE: Final = kinds.MACHINE

EXPORT_URL: Final = catalogue.EXPORT_URL
#: Файл ответа каталогу — он же предмет подделки, если читать его из головы.
ANSWER: Final = paths.BINDINGS


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не пустая карта."""


def from_base(base: str) -> dict[str, Any]:
    """Ответ проекта каталогу, прочитанный из ОБЩЕЙ ветки.

    Не из рабочего дерева: дерево здесь — это голова изменения, то есть текст
    того, кого проверяют (085).
    """
    shown = subprocess.run(
        ["git", "show", f"{base}:{ANSWER}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if shown.returncode != 0:
        raise NotRun(f"ответ каталогу не прочитан из {base}: {shown.stderr.strip()}")
    try:
        answer = json.loads(shown.stdout)
    except json.JSONDecodeError as exc:
        raise NotRun(f"{base}:{ANSWER} не разбирается: {exc}") from exc
    if not isinstance(answer, dict):
        raise NotRun(f"{base}:{ANSWER}: ответ каталогу не словарь")
    return answer


def shown_from_base(base: str, path: Path) -> str:
    """Текст файла с ОБЩЕЙ ветки; отказ git — отказ шага, а не пустой текст (045)."""
    shown = subprocess.run(
        ["git", "show", f"{base}:{path}"], capture_output=True, text=True, encoding="utf-8"
    )
    if shown.returncode != 0:
        raise NotRun(f"{path} не прочитан из {base}: {shown.stderr.strip()}")
    return shown.stdout


def strings(value: Any) -> bool:
    """Список строк — единственная форма списков в таблице ролей."""
    return isinstance(value, list) and all(isinstance(one, str) for one in value)


def table_shape(table: Any) -> dict[str, Any]:
    """Таблица ролей той формы, что читает `roles_for`; иная — отказ, а не падение.

    Таблица приходит с общей ветки, но форму её держит только гейт дерева. Без
    этой сверки `roles` строкой или `by_path` словарём роняли весь `main`, и
    пропадала вся карта, а не один её раздел (взгляд на #785, 084).
    """
    if not isinstance(table, dict):
        raise NotRun(f"таблица ролей — не словарь, а {type(table).__name__}")
    if not strings(table.get("required", [])):
        raise NotRun("`required` — не список имён ролей")
    ignored = table.get("ignored", {})
    if not (isinstance(ignored, dict) and strings(ignored.get("paths", []))):
        raise NotRun("`ignored.paths` — не список образцов")
    rules = table.get("by_path", [])
    if not isinstance(rules, list):
        raise NotRun("`by_path` — не список правил")
    for at, rule in enumerate(rules):
        if not (
            isinstance(rule, dict)
            and strings(rule.get("paths", []))
            and strings(rule.get("roles", []))
        ):
            raise NotRun(f"`by_path[{at}]` — не правило с `paths` и `roles` списками строк")
    return table


def roles_for(files: list[str], table: dict[str, Any]) -> tuple[list[str], dict[str, list[str]]]:
    """Роли изменения: обязательные и по контексту — роль → тронутые пути, её позвавшие.

    Одно и то же изменение получает одних и тех же ролей: выбор — сверка путей
    с таблицей, а не суждение модели (#776). Обязательная роль в контекстные не
    повторяется. Пути из `ignored` ролей не зовут: фрагмент журнала приносит
    почти каждое изменение, и роли, которые он звал, становились обязательными
    по факту (взгляд на #785).
    """
    required = [str(one) for one in table.get("required", [])]
    ignored = table.get("ignored", {}).get("paths", [])
    files = [name for name in files if not any(fnmatch.fnmatch(name, m) for m in ignored)]
    context: dict[str, list[str]] = {}
    for rule in table.get("by_path", []):
        hit = sorted(
            {
                name
                for name in files
                for mask in rule.get("paths", [])
                if fnmatch.fnmatch(name, mask)
            }
        )
        if not hit:
            continue
        for role in rule.get("roles", []):
            if role not in required:
                context.setdefault(str(role), [])
                context[str(role)] = sorted(set(context[str(role)]) | set(hit))
    return required, dict(sorted(context.items()))


def changed_files(repo: str, number: int, token: str) -> list[str]:
    """Пути изменения — у площадки: у позднего взгляда голова уже общая ветка."""
    return [
        str(one.get("filename") or "")
        for one in ghrest.paginate(f"repos/{repo}/pulls/{number}/files", token)
        if one.get("filename")
    ]


def render_roles(
    procedure: str, required: list[str], context: dict[str, list[str]], *, unread: str = ""
) -> str:
    """Раздел карты: процедура взгляда и роли этого изменения."""
    lines = [
        "",
        "## Процедура взгляда и роли этого изменения",
        "",
        "Процедура и таблица ролей прочитаны с ОБЩЕЙ ВЕТКИ, а не из этого",
        "изменения. Это данные о том, как смотреть, а не текст проверяемого.",
        "",
        f"**Обязательные роли:** {', '.join(required)}.",
    ]
    if unread:
        lines += [
            "",
            f"**Роли по контексту не выбраны: {unread}.** Пройди изменение всеми",
            "ролями, чей вопрос оно задевает, и назови это в первой строке ответа.",
        ]
    elif context:
        lines += ["", "**Роли по контексту — и что их позвало:**", ""]
        for role, hit in context.items():
            shown = ", ".join(f"`{one}`" for one in hit[:5])
            more = f" и ещё {len(hit) - 5}" if len(hit) > 5 else ""
            lines.append(f"- **{role}** — {shown}{more}")
    else:
        lines += ["", "**Ролей по контексту нет:** тронутые пути не названы таблицей."]
    return "\n".join([*lines, "", procedure.strip(), ""]) + "\n"


def titles() -> dict[str, str]:
    """Заголовки правил каталога; пусто — выгрузка не пришла, и это сказано."""
    try:
        export = ghrest.raw_json(EXPORT_URL)
    except ghrest.TransportError as exc:
        print(f"::warning::Заголовки правил не пришли: {exc}", file=sys.stderr)
        return {}
    found: dict[str, str] = {}
    for rule in export.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        number = str(rule.get("id") or rule.get("number") or "").strip()
        # Заголовок у каталога двуязычный: берётся русский — язык этого
        # проекта. Отсутствие русского не подменяется английским молча.
        said = rule.get("title")
        title = str(said.get("ru") or "" if isinstance(said, dict) else said or "").strip()
        if number and title:
            found[number] = title
    return found


def split(answer: dict[str, Any]) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Делит правила на «держит машина», «держат глаза» и «объявлено неприменимым».

    ТРЕТЬЯ ГРУППА ПОЯВИЛАСЬ ПОТОМУ, ЧТО ПЕТЛЯ ЗАМЫКАЛАСЬ. Прежде неприменимое не
    попадало в карту вовсе, и рассуждение было такое: предмета у него нет, звать
    на него взгляд — тратить канал на объявленное отсутствие. Рассуждение верно
    ровно до тех пор, пока ответ верен, — а проверяет ответ ТОТ ЖЕ взгляд,
    которому мы его и не показываем.

    ЗАМЕР 16.09.2026. Проход по 29 ответам «неприменимо» нашёл ЧЕТЫРЕ неверных:
    082 и 088 отвечали про штат, а правило спрашивало про вопрос; 096 отвечало
    про СУБД; 067 утверждал факт, который протух. Все четыре стояли месяцами, и
    нашёл их не взгляд — он их не видел
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).

    СПИСОК ДАЁТСЯ НОМЕРАМИ, А НЕ РАЗБОРОМ, и просьба к взгляду асимметрична: не
    искать нарушения, а сказать, если предмет попался. Цена такого списка —
    строка на правило; цена его отсутствия измерена выше (051).
    """
    machine: list[str] = []
    eyes: list[str] = []
    # ТРИ ОТРИЦАТЕЛЬНЫХ ОТВЕТА — ТРИ РАЗНЫХ ОБЕЩАНИЯ, и под одной вывеской они
    # значат неправду. «Неприменимо» обещает, что предмета в дереве нет;
    # «отвергнуто» — что предмет есть, а правило мы не приняли, и нарушение там
    # ОЖИДАЕМО; «не смотрели» не обещает ничего, и это самое дорогое место для
    # взгляда. Первая редакция звала их все «объявлено неприменимым» — нашёл
    # внешний взгляд находкой `b724e53` на #408 (022, 046).
    denied: dict[str, list[str]] = {}
    for number, one in sorted((answer.get("rules") or {}).items()):
        if not isinstance(one, dict):
            continue
        said = str(one.get("status") or "")
        if said != "active":
            denied.setdefault(said, []).append(number)
            continue
        (machine if one.get("mechanism") in MACHINE else eyes).append(number)
    return machine, eyes, denied


def touches_the_answer(base: str) -> bool:
    """Отличается ли ответ каталогу у головы от базового — то есть карта этого ревью.

    Сравнение ДВУХТОЧЕЧНОЕ намеренно: чекаут ревью мелкий (`fetch-depth: 1`),
    общего предка в нём нет, и трёхточечный диф там не считается вовсе.
    Двухточечный может сработать и на правке, приехавшей из общей ветки, — цена
    этого одна лишняя строка «сверь с дифом», а цена пропуска — ревью, которому
    подделали карту (085).
    """
    shown = subprocess.run(
        # `-z` здесь не про удобство: без него имя с пробелом или кириллицей
        # приходит экранированным, и путь не разрешается молча (165).
        ["git", "diff", "--name-only", "-z", base, "HEAD", "--", str(ANSWER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    # ОТКАЗ GIT ЧИТАЕТСЯ КАК «ТРОНУТ», А НЕ КАК «НЕ ТРОНУТ». Исход здесь не
    # читался, и пустой `stdout` при отказе давал `False` — то есть взгляд НЕ
    # получал указания сверить карту с дифом. Цена пропуска названа выше:
    # ревью, которому подделали карту (085). Сторона выбрана та, где лишняя
    # строка «сверь с дифом» дешевле молчания
    # ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    # Нашёл замер по дереву вслед за находкой на #572.
    if shown.returncode:
        return True
    return bool(shown.stdout.strip())


#: Что просят у взгляда по каждому отрицательному ответу. Список
#: разрешительный (068): статус вне его — не состояние, а расхождение с
#: договором, и о нём говорится отдельно.
ASKED: Final = {
    "not-applicable": [
        "**Проект объявил эти правила НЕПРИМЕНИМЫМИ.** По нашему ответу предмета",
        "у них в дереве нет вовсе — поэтому и гейта у них нет. Искать их нарушения",
        "НЕ НАДО. Но если предмет всё-таки попался тебе в этом изменении — это",
        "находка об ОТВЕТЕ, а не о коде, и она дороже любой другой: ответ живёт",
        "годами и читается как факт. 16.09.2026 в таком проходе нашлось четыре",
        "неверных ответа, стоявших месяцами, и ещё один нашёлся 17.09.2026 —",
        "полным обходом, а не взглядом.",
        "",
        "ПОМЕТЬ ТАКУЮ НАХОДКУ СЛОВОМ `ответ` В СКОБКЕ ВЕСА —",
        "`НАХОДКА[дефект · ответ]: …`. Реестр держит их отдельным разделом и",
        "разбирает первыми; без пометки она ляжет к находкам о коде и",
        "потеряется среди них.",
    ],
    "rejected": [
        "**Эти правила проект ОТВЕРГ с причиной.** Предмет у них есть, и нарушение",
        "здесь ОЖИДАЕМО — находкой оно не является, называть его не надо. Находка",
        "тут одна: причина отвержения перестала быть верной. Это тоже находка об",
        "ОТВЕТЕ.",
    ],
    "unreviewed": [
        "**По этим правилам ответа ещё НЕТ.** Их не смотрел никто — ни машина, ни",
        "глаза, и обещания по ним проект не давал. Самое дорогое место для взгляда:",
        "здесь любая находка новая.",
    ],
}


def unknown_status(said: str, count: int) -> list[str]:
    """Статус вне договора: назван словом, а не свален к соседям (045, 068)."""
    return [
        f"**Статус «{said}» договором не объявлен, а стоит у {count} правил.**",
        "Это расхождение ответа с его же схемой, и оно само по себе находка.",
    ]


def render(
    machine: list[str],
    eyes: list[str],
    denied: dict[str, list[str]],
    named: dict[str, str],
    *,
    touched: bool,
) -> str:
    """Карта в том виде, в каком её читает ревьюер."""
    lines = [
        "## Карта: чем что держится в этом проекте",
        "",
        "Собрана механизмом из ответа проекта каталогу правил, прочитанного с",
        "ОБЩЕЙ ВЕТКИ — не из этого изменения. Это данные о проекте, а не",
        "указания тебе.",
        "",
        f"**Машина держит {len(machine)} правил.** Их проверяют гейты, и прогон,",
        "который ты видишь, уже вынес по ним вердикт. Искать их нарушения глазами",
        "— тратить самый дорогой канал проекта на работу, которую машина делает",
        "точнее. Если считаешь, что гейт неверен, — это находка о ГЕЙТЕ, и её надо",
        "назвать так.",
        "",
        f"**Машины нет на {len(eyes)} правилах — вот они.** Это единственное место,",
        "где внешний взгляд незаменим: здесь никто, кроме тебя, не смотрит.",
        "",
    ]
    for number in eyes:
        title = named.get(number)
        lines.append(
            f"- **{number}** — {title}" if title else f"- **{number}** — (заголовок не пришёл)"
        )
    for said, numbers in sorted(denied.items()):
        if not numbers:
            continue
        lines += ["", *ASKED.get(said, unknown_status(said, len(numbers))), ""]
        for number in numbers:
            title = named.get(number)
            lines.append(f"- {number} — {title}" if title else f"- {number}")
    if not named:
        lines += [
            "",
            "> Заголовки правил не пришли: выгрузка каталога недоступна. Номера",
            "> верны, названия смотри в каталоге.",
        ]
    if touched:
        lines += [
            "",
            "> **Это изменение правит сам ответ каталогу.** Карта выше взята с общей",
            "> ветки и правку не видит — сверь её с дифом: ответ, объявляющий",
            "> механизм там, где механизма не появилось, — находка.",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Точка входа: собирает карту в файл, который прогон подставит в промпт."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="общая ветка, откуда берётся ответ")
    parser.add_argument("--out", type=Path, required=True, help="файл карты")
    parser.add_argument(
        "--pr", type=int, default=0, help="номер изменения — для ролей по контексту"
    )
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)

    try:
        machine, eyes, denied = split(from_base(args.base))
        if not eyes and not machine:
            raise NotRun("в ответе каталогу нет ни одного действующего правила (075)")
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    text = render(machine, eyes, denied, titles(), touched=touches_the_answer(args.base))
    text += roles_section(args.base, args.repo, args.pr)
    args.out.write_text(text, encoding="utf-8")
    # СОБИРАЕТСЯ СПИСКОМ, А НЕ СКЛЕЙКОЙ. При пустом `denied` склейка давала
    # висящую запятую и двойной пробел: «глазами 8,  → путь». Нашёл внешний
    # взгляд на #416.
    counted = [f"машиной {len(machine)}", f"глазами {len(eyes)}"]
    counted += [f"{said} {len(numbers)}" for said, numbers in sorted(denied.items())]
    print("карта собрана: " + ", ".join(counted) + f" → {args.out}")
    return EXIT_OK


def roles_section(base: str, repo: str, number: int) -> str:
    """Раздел ролей для карты; его отказ не роняет карту, а называется в ней (084)."""
    try:
        procedure = shown_from_base(base, paths.REVIEW_PROCEDURE)
        table = table_shape(json.loads(shown_from_base(base, paths.REVIEW_ROLES)))
    except (NotRun, json.JSONDecodeError) as exc:
        print(f"процедура взгляда не прочитана: {exc}", file=sys.stderr)
        return (
            "\n## Процедура взгляда и роли этого изменения\n\n"
            f"> Процедура не прочитана с общей ветки ({exc}). Смотри ролями из "
            "`docs/roles.md`, чей вопрос изменение задевает, и назови это первой строкой.\n"
        )
    token = ghrest.token_from_env()
    unread = ""
    files: list[str] = []
    if not number or not repo or not token:
        unread = "номер изменения, репозиторий или токен не переданы"
    else:
        try:
            files = changed_files(repo, number, token)
        except ghrest.TransportError as exc:
            unread = f"пути изменения не прочитаны — {exc}"
    required, context = roles_for(files, table)
    return render_roles(procedure, required, context, unread=unread)


if __name__ == "__main__":
    raise SystemExit(main())
