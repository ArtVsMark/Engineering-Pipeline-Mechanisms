"""Перепись отдачи после выпуска: что своё, что сдвинулось с прошлого выпуска, что не прогнано.

РЕШЕНИЕ ВЛАДЕЛЬЦА 25.10.2026 (#1635, вариант А; задача #1658). Анализ отдачи
делается после каждого выпуска, чтобы ничего не забывать передавать, — и
делает его механизм, а не память окна. Раздел ложится в заметки выпуска
(`release.py --page`) и выпуск не держит: он совещательный.

ЧЕГО ОН НЕ ПОВТОРЯЕТ. Что у каждого механизма есть ответ, что `as-is` доходит
до потребителя и что `configured` называет своё наполнение, держит набор на
каждом изменении (`tests/test_portable.py`). Набор не держит другое: что
`ours` пересматривают, а не копят, и что сдвинулось с прошлого выпуска. Это
и печатает перепись — счёт по шкале с разницей, `ours` по причинам с
пришедшими с прошлого тега первыми (их перечитывают по мерке «своё», #1652),
сменившие шкалу ответы и каналы проверки переноса, которых не прогоняли.

НЕ СОБРАЛАСЬ — СКАЗАНО (045). Прошлый тег не прочитан, перепись не
разобралась — `NotRun` с причиной; страница выпуска печатает её строкой,
а не молчит.
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import gitcall
import paths
import report
import version as project_version

#: Шкала ответов переписи — в порядке, в каком её печатает раздел.
SCALE: Final = ("as-is", "configured", "ours")
#: Предел причины `ours` в строке раздела: причина словами бывает абзацем, а
#: полная — в переписи, по адресу механизма.
REASON_LIMIT: Final = 120
#: Метка канала, который назван, но не прогнан (`verified_by`).
UNPROVEN: Final = "none"

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2


class NotRun(RuntimeError):
    """Перепись не собрана: третий исход, а не пустой раздел (039)."""


@dataclass(frozen=True)
class Census:
    """Ответы переписи по механизму и каналы проверки переноса."""

    answers: dict[str, dict[str, Any]]
    verified: dict[str, dict[str, Any]]


def parsed(text: str, where: str) -> Census:
    """Перепись из текста `.rules/portable.json`; не та форма — `NotRun` с местом."""
    try:
        said = json.loads(text)
    except ValueError as exc:
        raise NotRun(f"{where}: перепись не разобрана — {exc}") from exc
    answers = said.get("answers") if isinstance(said, dict) else None
    if not isinstance(answers, dict):
        raise NotRun(f"{where}: в переписи нет словаря `answers`")
    verified = said.get("verified_by") or {}
    return Census(
        {key: one for key, one in answers.items() if isinstance(one, dict)},
        {key: one for key, one in verified.items() if isinstance(one, dict)},
    )


def at(ref: str, root: Path) -> Census:
    """Перепись на дереве ссылки `ref` — тега или головы."""
    text = gitcall.output(["show", f"{ref}:{paths.PORTABLE.as_posix()}"], NotRun, cwd=str(root))
    return parsed(text, f"{ref}:{paths.PORTABLE.as_posix()}")


def previous_tag(tag: str, root: Path) -> str | None:
    """Выпуск, предшествующий `tag` в его истории; первого выпуска — `None`."""
    out = gitcall.output(
        ["tag", "--merged", tag, "--list", project_version.RELEASE_TAG_GLOB],
        NotRun,
        cwd=str(root),
    )
    earlier = [one for one in out.split() if project_version.is_release_tag(one) and one != tag]
    if not earlier:
        return None
    return max(earlier, key=lambda one: project_version.digits(project_version.bare(one)))


def scale_of(census: Census) -> Counter[str]:
    """Счёт ответов по шкале."""
    return Counter(str(one.get("answer") or "") for one in census.answers.values())


def section(now: Census, before: Census | None, since: str | None) -> list[str]:
    """Раздел заметок выпуска: счёт с разницей, `ours` по причинам, сдвиги и не прогнанное."""
    counted = scale_of(now)
    was = scale_of(before) if before is not None else Counter()
    lines = ["### Перепись отдачи", ""]
    lines.append(
        f"Ответов в переписи: **{len(now.answers)}**"
        + (f" (на `{since}` — {len(before.answers)})." if before is not None else ".")
    )
    lines += ["", "| ответ | сейчас | разница |", "|---|---|---|"]
    for answer in SCALE:
        delta = counted[answer] - was[answer] if before is not None else 0
        lines.append(f"| `{answer}` | {counted[answer]} | {delta:+d} |")
    ours = {key: one for key, one in now.answers.items() if one.get("answer") == "ours"}
    fresh = {
        key
        for key in ours
        if before is None or (before.answers.get(key) or {}).get("answer") != "ours"
    }
    by_reason: dict[str, list[str]] = {}
    for key, one in sorted(ours.items()):
        by_reason.setdefault(str(one.get("why") or "без причины"), []).append(key)
    lines += ["", "**`ours` по причинам** — пришедшие с прошлого выпуска отмечены ★:", ""]
    for reason, keys in sorted(by_reason.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        named = ", ".join(f"`{key}`" + (" ★" if key in fresh else "") for key in keys)
        lines.append(f"- {report.cut(reason, REASON_LIMIT)} — {len(keys)}: {named}")
    if before is not None:
        moved = [
            (key, str((before.answers.get(key) or {}).get("answer") or "—"), str(one.get("answer")))
            for key, one in sorted(now.answers.items())
            if (before.answers.get(key) or {}).get("answer") != one.get("answer")
        ]
        gone = sorted(before.answers.keys() - now.answers.keys())
        lines += ["", f"**Сменили шкалу с `{since}`:** {len(moved)}" + (":" if moved else ".")]
        lines += [f"- `{key}`: {was_said} → {now_said}" for key, was_said, now_said in moved]
        if gone:
            lines.append(f"- ушли из переписи: {', '.join(f'`{one}`' for one in gone)}")
    unproven = sorted(key for key, one in now.verified.items() if one.get("where") == UNPROVEN)
    lines += [
        "",
        "**Каналы переноса без прогона:** "
        + (", ".join(f"`{one}`" for one in unproven) if unproven else "нет."),
    ]
    return lines


def present(ref: str, root: Path) -> bool:
    """Лежит ли перепись на дереве `ref`: у проекта без неё предмета нет."""
    listed = gitcall.output(
        ["ls-tree", "-z", "--name-only", ref, "--", paths.PORTABLE.as_posix()],
        NotRun,
        cwd=str(root),
    )
    return bool(listed.strip("\0"))


def for_release(tag: str, root: Path) -> list[str]:
    """Раздел для страницы выпуска `tag`: перепись на теге против прошлого выпуска.

    ПЕРЕПИСИ НЕТ — РАЗДЕЛА НЕТ. Шаг выпуска зовёт и потребитель, а перепись
    отдачи ведёт поставщик: у проекта без неё предмета нет, и строка «не
    собрана» на каждом его выпуске была бы шумом, а не отказом. Перепись,
    которая есть, но не читается, — отказ, как прежде.
    """
    if not present(tag, root):
        return []
    since = previous_tag(tag, root)
    if since is not None and not present(since, root):
        since = None
    before = at(since, root) if since else None
    return section(at(tag, root), before, since)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: раздел переписи для тега или головы против прошлого выпуска."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="HEAD", help="тег выпуска; по умолчанию голова")
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    args = parser.parse_args(argv)
    try:
        print("\n".join(for_release(args.tag, args.root)))
    except NotRun as exc:
        print(f"перепись отдачи не собрана: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
