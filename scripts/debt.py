#!/usr/bin/env python3
"""Долг, который идёт перед планом: находки и незакрытая работа по правилам.

Порядок источников работы — `docs/behaviour.md`, контур 1. Перед новой работой
стоят два долга, и оба по УЖЕ сделанному:

* **находки внешнего взгляда, пережившие слияние** — часть работы, помеченной
  закрытой, не сделана
  ([142](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/142-a-scheduled-red-needs-an-addressee.md));
* **незакрытая работа по правилам каталога** — правило без ответа, правило
  «действует, но не держится ничем», разошедшийся контракт с неперечитанными
  ответами. Этого требует сам каталог
  ([177](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/177-unfinished-rule-work-comes-first.md)).

ЧИСЛА ЗДЕСЬ НЕ СЧИТАЮТСЯ, А ЧИТАЮТСЯ. По правилам их считает ночной прогон
действия каталога и кладёт в задачу-«входящие»; по находкам — механизм ревью в
свою живую задачу. Второй счёт того же разошёлся бы с первым молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)),
и разошёлся бы незаметно: оба числа выглядят одинаково правдоподобно.

Шаг **не краснеет от долга**: красное здесь стало бы проверкой, которую
приучаются обходить
([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)),
а долг бывает больше одного изменения. Его дело — не пускать долг в невидимое.

Исходы (правило 039): ``0`` остаток прочитан и напечатан · ``2`` не отработало ·
``3`` источник не прочитан — сказано, а не выдано за «долга нет».
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Final

import findings
import ghrest

#: Строка, которую пишет ночной прогон каталога. Три числа правила 177 в одном
#: месте — читаются целиком, а не собираются заново.
STATS_RE: Final = re.compile(
    r"Задач по правилам:\s*(\d+)\..*?«не рассмотрено»:\s*(\d+)\..*?держится ничем:\s*(\d+)",
    re.S,
)
CONTRACT_RE: Final = re.compile(r"\*\*Контракт разошёлся\.\*\*\s*(.+)")

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_PARTIAL: Final = 3


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «долга нет»."""


def rules_debt(body: str) -> tuple[int, int, int] | None:
    """Три числа правила 177 из задачи-«входящие»: задачи, очередь, «ничем»."""
    match = STATS_RE.search(body or "")
    if match is None:
        return None
    tasks, queue, unheld = (int(value) for value in match.groups())
    return tasks, queue, unheld


def contract_note(body: str) -> str | None:
    """Расхождение контракта каталога, если оно объявлено во «входящих»."""
    match = CONTRACT_RE.search(body or "")
    return match.group(1).strip() if match else None


def findings_debt(repo: str, token: str) -> list[tuple[str, int, str]]:
    """Неразобранные находки из живой задачи-адресата."""
    _, body = findings.live_issue(repo, token)
    return [(mark, pr, title) for mark, (pr, title) in findings.parse_entries(body).items()]


def rules_left(numbers: tuple[int, int, int] | None, note: str | None) -> bool:
    """Есть ли незакрытая работа по правилам — по ТРЁМ видам 177, а не по счёту задач.

    Первое из трёх чисел — сколько задач по правилам заведено в трекере, и
    долгом оно не является: задача может быть открыта и разобрана, а долг —
    это правило без ответа, правило «действует и не держится ничем» и
    разошедшийся контракт. Считать долгом любое ненулевое из трёх значило
    объявлять долг ВСЕГДА: задачи по правилам у проекта есть постоянно, и
    напоминание в таком виде перестаёт что-либо значить (051).

    Третий вид — расхождение контракта — печатался, но в решение не входил
    ([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)):
    поднявшийся контракт означает, что ответы надо перечитать, и молчать об
    этом нельзя.

    Числа не прочитаны — долг НЕИЗВЕСТЕН, а не равен нулю (045): неизвестность
    считается долгом, потому что снимать приоритет с непроверенного источника
    хуже, чем напомнить лишний раз.
    """
    if numbers is None:
        return True
    _, queue, unheld = numbers
    return bool(queue or unheld or note)


def remind(has_debt: bool) -> None:
    """Ведёт к договору, а не пересказывает его."""
    if has_debt:
        print(
            "\nЭто идёт ПЕРЕД планом: docs/behaviour.md, контур 1, источники 3 и 5.\n"
            "Правило каталога — 177: пока незакрытая работа по правилам есть, новую не начинают."
        )
    else:
        print("\nдолга нет: оба источника пусты, работа берётся по плану")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает остаток долга и возвращает исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)

    token = ghrest.token_from_env()
    if not token or not args.repo:
        print(
            "остаток не прочитан: нет токена или репозитория. Долг НЕИЗВЕСТЕН — это\n"
            "сказано, а не выдано за «долга нет» (045).",
            file=sys.stderr,
        )
        # Напоминание печатается и здесь: окно, увидевшее «не прочитано»,
        # должно знать, где записан порядок, — иначе оно решит за себя само.
        remind(True)
        return EXIT_PARTIAL

    try:
        left = findings_debt(args.repo, token)
        _, inbox = findings.live_issue(args.repo, token, findings.INBOX_MARKER)
    except ghrest.TransportError as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    print(f"находки, пережившие слияние: {len(left)}")
    for mark, pr, title in left:
        print(f"  {mark} · #{pr} — {title}")

    partial = False
    numbers = rules_debt(inbox)
    note = contract_note(inbox)
    if numbers is None:
        partial = True
        print(
            "правила: «входящие» не найдены или без строки счёта — ночной прогон каталога\n"
            "не отработал. Долг по правилам НЕИЗВЕСТЕН, а не равен нулю (045, 075).",
            file=sys.stderr,
        )
    else:
        tasks, queue, unheld = numbers
        print(
            f"правила (считает каталог): задач {tasks}, без ответа {queue}, держится ничем {unheld}"
        )
    # Расхождение контракта печатается и тогда, когда счёта нет: это отдельный
    # вид долга, и от строки со счётом он не зависит.
    if note:
        print(f"  контракт разошёлся: {note}")

    remind(bool(left) or rules_left(numbers, note))
    return EXIT_PARTIAL if partial else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
