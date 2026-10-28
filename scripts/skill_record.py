#!/usr/bin/env python3
"""Сырая запись о слитом изменении: какие навыки ждали и какие вызваны (#1694).

ЗАЧЕМ. Решение владельца 26.10.2026: вместо задачи на каждый замер копятся
СЫРЫЕ ЗАПИСИ, а выводы делаются по ним. Свод отвечает только на вопрос, под
который его собрали; сырые записи перечитываются с вопросом, которого сегодня
нет. Прецедент — архив находок на ветке `badges`, запись на находку.

ЗАПИСЬ НА СЛИТОЕ ИЗМЕНЕНИЕ, ТОЛЬКО ДОПИСЫВАЕТСЯ. Поля:

* `pr`, `merged_at`, `commit` — какое изменение и когда слито;
* `touched`, `added` — пути, тронутые и заведённые уплотнённым коммитом;
* `expected` — навыки, которых изменение ждало, машинно по признакам в шапке
  каждого `SKILL.md` (`skill_signals`);
* `invoked` — навыки из строк `Навык:` тела слитого коммита
  (`changerefs.skills_in_all`); `source` говорит, откуда сведение.

`INVOKED` — САМООТЧЁТ, И ЭТО НАЗВАНО ПОЛЕМ. Забытая строка неотличима от
невызванного навыка; хук журнала был бы машинным, но в облачном окне журнал
живёт с контейнером, а в окне с корнем вне проекта хуки проекта не грузятся
(#1449). Поэтому `source` пишется в каждую запись: читающий ряд видит, что
`invoked` — со слов окна.

ФАЙЛ — `skills.json` НА ВЕТКЕ `badges`, СЛОВАРЁМ, А НЕ `.jsonl` ИЗ ТЕКСТА
ЗАДАЧИ. Файлы ветки семья читает одним читателем, `badges_read.by_api`, и он
ждёт JSON-словарь: построчный формат завёл бы ему второго соседа (090).
Пишется он поверх ветки, без `--force`, тем же приёмом, что факты
(`publish_facts.checkout`): гонка с публикацией фактов — повтор с новой
выборки, а не перезапись чужого.

ПРОШЛОЕ ЗАДНИМ ЧИСЛОМ НЕ РАЗМЕЧАЕТСЯ: до строки `Навык:` (#1701) `invoked`
неизвестен, а не пуст, и такие изменения не записываются — ни по слиянию, ни
по кнопке (`named_skills_yet`). Граница — первая строка `Навык:` в истории
САМОГО проекта, а не наш коммит: механизм отдаётся потребителю, и в его
истории нашего коммита нет (поздний взгляд на #1715).

СПЕРВА СПРОСИЛИ СЕМЬЮ (162): у каталога есть журнал вызовов навыков окна, а
записи на слитое изменение с ожиданием по признакам нет ни у кого из семьи —
строим своё. Форма хранения взята у нашего же архива находок.

Исходы (правило 039): ``0`` запись дописана, уже есть или записывать нечего
(коммит — не уплотнение изменения или строки `Навык:` в истории ещё не было)
· ``2`` не отработал — git, признаки навыков, таблица путей или ветка
`badges` отказали.
"""

import argparse
import json
import re
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import changerefs
import gitcall
import main_guard
import paths
import publish_facts
import skill_signals

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Файл записей на ветке `badges`.
RECORDS: Final = (paths.BADGES_DIR / "skills.json").as_posix()
#: Номер формы файла записей.
SCHEMA: Final = 1
#: Откуда сведение о вызове: строка тела, которую пишет окно.
SOURCE: Final = "строка «Навык:» тела слитого коммита"
#: Номер изменения в заголовке уплотнения: «… (#1707)».
PR_RE: Final = re.compile(r"\(#(?P<pr>\d+)\)\s*$")
#: Сколько раз повторить толчок, если ветку сдвинули между выборкой и толчком.
TRIES: Final = 3
#: ХУДШАЯ ПОПЫТКА — ТРИ СЕТЕВЫХ ВЫЗОВА GIT: выборка ветки, при её отказе — опрос
#: `ls-remote`, и толчок; у каждого дедлайн `gitcall.NETWORK`.
ATTEMPT_WORST: Final = 3 * gitcall.NETWORK
#: БЮДЖЕТ ВСЕХ ПОПЫТОК — МЕНЬШЕ ПРЕДЕЛА ДЖОБА `record` (`step-skills.yml`, 25 мин)
#: с запасом на выкладку и установку (100): следующая попытка начинается,
#: только если её худший случай укладывается в остаток.
BUDGET: Final = 20 * 60


class NotRun(RuntimeError):
    """Запись не собрана или не опубликована: третий исход, а не «нечего»."""


def git(*args: str, root: Path = Path()) -> str:
    """Ответ git в репозитории `root`; отказ — `NotRun` с причиной."""
    return gitcall.output(args, NotRun, cwd=str(root))


def named_skills_yet(commit: str, root: Path = Path()) -> bool:
    """Была ли строка `Навык:` в теле коммита или его предков; нет — `invoked` неизвестен.

    Пустой `invoked` до первой такой строки выглядел бы «не вызван», а это
    «не сказано»: строки ещё не было в договоре проекта (045).
    """
    found = gitcall.output(
        ["log", "-1", "--format=%H", "--grep=^Навык:", commit],
        NotRun,
        cwd=str(root),
        timeout=skill_signals.READ,
    )
    return bool(found.strip())


def record_of(
    commit: str, table: dict[str, skill_signals.Signals], root: Path = Path()
) -> dict[str, Any] | None:
    """Запись о слитом коммите; не уплотнение изменения — `None`, записывать нечего."""
    head, day, body = (
        [*git("show", "-s", "--format=%s%x00%cs%x00%B", commit, root=root).split("\0"), "", ""]
    )[:3]
    found = PR_RE.search(head.strip())
    if not found:
        return None
    touched: list[str] = []
    added: list[str] = []
    # Пути — по NUL (165): без `-z` имя с пробелом или не-ASCII пришло бы
    # экранированным и не совпало бы ни с одним шаблоном признака.
    words = git(
        "diff-tree", "-z", "--no-commit-id", "--name-status", "-r", "--root", commit, root=root
    )
    parts = [one for one in words.split("\0") if one]
    at = 0
    while at < len(parts):
        status = parts[at]
        # Переименование и копия несут два пути: старый и новый — берётся новый.
        width = 2 if status[:1] in "RC" else 1
        path = parts[at + width] if at + width < len(parts) else ""
        at += width + 1
        if not path:
            continue
        touched.append(path)
        if status.startswith("A"):
            added.append(path)
    return {
        "pr": int(found["pr"]),
        "merged_at": day.strip(),
        "commit": git("rev-parse", commit, root=root).strip(),
        "touched": sorted(touched),
        "added": sorted(added),
        "expected": skill_signals.expected(table, touched, added, body),
        "invoked": sorted(changerefs.skills_in_all([body])),
        "source": SOURCE,
    }


def merged(store: Any, record: dict[str, Any]) -> dict[str, Any] | None:
    """Файл записей с новой записью; запись этого изменения уже есть — `None`.

    Файл не той формы — `NotRun`: дописать в него — значит закрепить чужую форму,
    а начать заново — потерять ряд (045).
    """
    if store is None:
        store = {"schema": SCHEMA, "records": []}
    if not isinstance(store, dict) or store.get("schema") != SCHEMA:
        raise NotRun(f"{RECORDS}: форма не та — ждётся schema {SCHEMA}")
    records = store.get("records")
    if not isinstance(records, list):
        raise NotRun(f"{RECORDS}: records — список записей")
    if any(isinstance(one, dict) and one.get("pr") == record["pr"] for one in records):
        return None
    return {"schema": SCHEMA, "records": [*records, record]}


def publish(
    record: dict[str, Any],
    workdir: Path,
    clock: Callable[[], float] = time.monotonic,
    deadline: float | None = None,
    root: Path = Path(),
) -> bool:
    """Дописывает запись поверх ветки `badges`; ``False`` — запись уже была.

    Ветку сдвинула публикация фактов между выборкой и толчком — повтор с новой
    выборки, до `TRIES` раз и пока худшая попытка укладывается в `BUDGET`;
    потом — отказ с причиной, а не `--force`. `deadline` — конец бюджета всего
    захода по `clock` (`main` отсчитывает его от входа, 100); не дан — от начала
    публикации.
    """
    last = ""
    if deadline is None:
        deadline = clock() + BUDGET
    # ОДНО МЕСТО ДЛЯ GIT И ДЛЯ ЗАПИСИ (взгляд на #1724, `c065808`): `git
    # worktree add` считает относительный путь от `root`, а запись и `git -C` —
    # от текущего каталога, и при `--root` ≠ cwd они расходились бы: дерево под
    # `root`, а запись и толчок — во внешний репозиторий.
    workdir = workdir.resolve()
    for attempt in range(TRIES):
        if deadline - clock() < ATTEMPT_WORST:
            raise NotRun(
                f"запись не опубликована: на попытку {attempt + 1} бюджета {BUDGET} с не хватит"
                + (f" — прежний отказ: {last}" if last else "")
            )
        tree = workdir / f"try-{attempt}"
        try:
            publish_facts.checkout(tree, repo=root)
        except publish_facts.NotPublished as exc:
            raise NotRun(str(exc)) from exc
        target = tree / RECORDS
        try:
            store = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else None
        except (OSError, ValueError) as exc:
            raise NotRun(f"{RECORDS} на ветке не прочитан: {exc}") from exc
        fresh = merged(store, record)
        if fresh is None:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(fresh, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        steps = [
            ("config", "user.name", publish_facts.BOT_NAME),
            ("config", "user.email", publish_facts.BOT_EMAIL),
            ("add", "--", RECORDS),
            ("commit", "-q", "-m", f"навыки изменения #{record['pr']}"),
        ]
        for step in steps:
            done = publish_facts.git(*step, cwd=tree)
            if done.returncode != 0:
                raise NotRun(f"git {step[0]} отказал: {publish_facts.reason(done)}")
        pushed = publish_facts.git(
            "push", "-q", "origin", f"HEAD:refs/heads/{publish_facts.BRANCH}", cwd=tree
        )
        if pushed.returncode == 0:
            return True
        last = publish_facts.reason(pushed)
        print(f"::notice::ветку {publish_facts.BRANCH} сдвинули — повтор ({attempt + 1}): {last}")
        publish_facts.git("worktree", "remove", "--force", str(tree), cwd=root)
        shutil.rmtree(tree, ignore_errors=True)
    raise NotRun(f"запись не опубликована за {TRIES} захода: {last}")


def main(argv: list[str] | None = None) -> int:
    """Точка входа: запись о слитом коммите — на ветку `badges` или на печать."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD", help="слитый коммит общей ветки")
    parser.add_argument(
        "--root", type=Path, default=Path(), help="репозиторий: история, навыки и ветка badges"
    )
    parser.add_argument("--workdir", type=Path, help="каталог для дерева ветки badges")
    args = parser.parse_args(argv)
    # БЮДЖЕТ — ОТ ВХОДА, А НЕ ОТ ПУБЛИКАЦИИ (100): чтение признаков на коммите
    # идёт до неё, и предел джоба держит сумму, а не одну публикацию.
    deadline = time.monotonic() + BUDGET
    try:
        # ОДИН РЕПОЗИТОРИЙ НА ВСЁ — `--root` (взгляд на #1724): граница `Навык:`,
        # признаки, коммит и ветка `badges` читались бы иначе из разных историй.
        if not named_skills_yet(args.commit, args.root):
            print(
                f"{args.commit}: строки «Навык:» в истории ещё не было — "
                "вызванные навыки неизвестны, записывать нечего"
            )
            return EXIT_OK
        try:
            table = skill_signals.signals_at(args.commit, args.root)
        except skill_signals.NoSignals as exc:
            print(
                f"{args.commit}: признаков навыков на нём ещё не было ({exc}) — записывать нечего"
            )
            return EXIT_OK
        record = record_of(args.commit, table, args.root)
        if record is None:
            print(f"{args.commit}: не уплотнение изменения — записывать нечего")
            return EXIT_OK
        print(json.dumps(record, ensure_ascii=False))
        if args.workdir is None:
            return EXIT_OK
        if publish(record, args.workdir, deadline=deadline, root=args.root):
            print(f"запись изменения #{record['pr']} дописана в {RECORDS}")
        else:
            print(f"запись изменения #{record['pr']} уже есть — второй не будет")
    except (NotRun, skill_signals.BadSignals, paths.BadPaths, OSError) as exc:
        print(f"запись навыков не собрана: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main_guard.run(main, EXIT_BROKEN))
