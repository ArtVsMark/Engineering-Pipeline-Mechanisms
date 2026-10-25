#!/usr/bin/env python3
"""Гейт: в прогонах и составных действиях нет опасных форм, которые разъехались бы по семье.

Мы поставщик: шаги `step-*.yml` зовёт каждый потребитель, и опасная форма в
нашем прогоне исполняется у всех. Такие формы держались ПОРОЗНЬ и только для
нашего дерева: `${{ }}` в `run:`, `pull_request_target` и закрепление по `sha` —
`tests/test_review_safety.py`, семейная прибивка — `tests/test_family_pinning.py`
(взгляд на #1634, `6116853`). Гейт сводит пять форм в одну проверку, которую
шаг `pipeline` гоняет и у потребителя; `${{ }}` в `run:` сюда не дублируется.
Приём взят у ECC (разбор #1424), код свой.

СПРОСИЛИ СЕМЬЮ (162), 24.10.2026: у каталога есть свой гейт прогонов —
`check_workflows.py`, — но он держит ручную кнопку, предел времени работы и
группы отмены, а этих пяти форм нет ни у каталога, ни у витрины, ни у
счётчика токенов. Приём взят у стороннего ECC, у семьи его не нашли.

ПЕРЕЧЕНЬ УТВЕРДИЛ ВЛАДЕЛЕЦ (24.10.2026, #1430) по замеру 61 файла:

1. `actions/checkout` в джобе с правом записи называет `persist-credentials`
   явно, а `true` несёт причину комментарием на той же строке. Без ключа
   токен остаётся в `.git/config`, и его читает всякий код после выгрузки
   (135, #12). Замер: 22 джоба с правом записи, ни один не говорил явно.
2. `pull_request_target` — только в файле, названном исключением с причиной.
   Замер: 0.
3. У каждого джоба со своими шагами есть `permissions` — свои или файла.
   Умолчание площадки шире нужного. Замер: 0.
4. `permissions: write-all` — нигде. Замер: 0.
5. Стороннее действие — на полном `sha`. Своё семейное (`FAMILY_OWNER`) — по
   тегу выпуска или `sha`: прибивка выпуска — договор подключения, а не дыра;
   по ветке — только исключением с причиной. Замер: стороннего не на `sha` 0,
   семейного по ветке 1 — взгляд на `main` (исключение, слово владельца).

Формы 2–5 сегодня на нуле: гейт по ним — страж от возврата, а не починка.

ИСКЛЮЧЕНИЯ — ДАННЫЕ ПРОЕКТА (`.rules/workflow-forms.json`), И ПЕРЕЖИВШЕЕ СВОЁ
МЕСТО КРАСНЕЕТ (195): иначе перечень копил бы
разрешения на то, чего уже нет, и первое же новое место под старым именем
прошло бы молча.

ПРЕДЕЛ НАЗВАН. Право записи судится по тексту `permissions` джоба и файла;
вызванный прогон (`workflow_call`) без своих прав получает права зовущего,
и тогда форма 1 судит то, что объявлено в нём самом, а не то, что придёт.
Составное действие прав не объявляет вовсе — его выгрузка судится как в
джобе с правом записи.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

import catalogue
import check_deadline
import paths
import yaml

EXIT_OK: Final = 0
EXIT_REJECTED: Final = 1
EXIT_BROKEN: Final = 2

WORKFLOWS: Final = paths.WORKFLOWS
ACTIONS: Final = paths.ACTIONS
CHECKOUT: Final = "actions/checkout"
PERSIST: Final = "persist-credentials"
#: Владелец семьи — по адресу каталога, а не буквами: у соседа своё имя
#: репозитория, а владелец семьи тот же.
FAMILY_OWNER: Final = catalogue.REPO.partition("/")[0].lower()
SHA_RE: Final = re.compile(r"[0-9a-f]{40}")
#: Тег выпуска — полная версия `vN.N.N`: мажорный алиас `@v1` подвижен, как ветка.
#: Один признак на гейт и на `tests/test_family_pinning.py` (находка на #1634).
RELEASE_RE: Final = re.compile(r"v\d+\.\d+\.\d+")
#: `true` на СТРОКЕ КЛЮЧА — блочной, в кавычках, в строку `{…: true}` (взгляд на
#: #1634, `016a18a`): начало строки — ключ, пункт шага или `with: {`, а не
#: комментарий и не тело `run:`. Судится строка, только если разобранное
#: значение у выгрузки и правда `true`: строка ищет причину, а не решает, есть
#: ли запись. ГРАНИЦА НАЗВАНА: такая же строка в теле `run:` файла, где
#: настоящий `true` тоже есть, причины потребует и от неё.
TRUE_RE: Final = re.compile(
    rf"^\s*(?:-\s*)?(?:with\s*:\s*\{{[^}}]*?)?[\"']?{PERSIST}[\"']?\s*:\s*[\"']?true\b",
    re.IGNORECASE,
)
#: Выражение площадки вместо значения: `${{ inputs.x }}` даёт `true`, не неся
#: причины, и форма 1 по ключу его не видела (взгляд на #1634, `c4b082e`).
EXPRESSION: Final = "${{"
#: Причина — комментарий со словами после значения, а не голый `#` (взгляд на #1634).
REASON_RE: Final = re.compile(r"#\s*\w")
#: Образ контейнера закреплён по digest: метка подвижна, как тег действия.
DIGEST_RE: Final = re.compile(r"@sha256:[0-9a-f]{64}")


class NotRun(RuntimeError):
    """Гейт не отработал: файл не прочитан или не разобран."""


def allowed(root: Path) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Исключения проекта: `pull_request_target` по файлу и семейное по ветке — с причиной.

    ДАННЫЕ ПРОЕКТА, А НЕ КОД (`paths.WORKFLOW_FORMS`): исключение одного дерева
    у другого не имеет места и краснело бы «пережившим». Файла нет — исключений
    нет; запись без причины или не той формы — отказ, а не тихое разрешение.
    """
    path = root / paths.WORKFLOW_FORMS
    if not path.is_file():
        return {}, {}
    try:
        said = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NotRun(f"{paths.WORKFLOW_FORMS} не разобран: {exc}") from exc
    target: dict[str, str] = {}
    branch: dict[tuple[str, str], str] = {}
    for kind, keys in (("target", ("file",)), ("branch", ("file", "uses"))):
        for one in said.get(kind, []) if isinstance(said, dict) else [None]:
            if not isinstance(one, dict) or not all(
                isinstance(one.get(key), str) and one[key] for key in (*keys, "why")
            ):
                raise NotRun(f"{paths.WORKFLOW_FORMS}: «{kind}» — запись без {keys} и `why`")
            if kind == "target":
                target[one["file"]] = one["why"]
            else:
                branch[(one["file"], one["uses"])] = one["why"]
    return target, branch


def files(root: Path) -> list[Path]:
    """Прогоны и составные действия дерева, от корня."""
    found = [*(root / WORKFLOWS).glob("*.y*ml"), *(root / ACTIONS).glob("*/action.y*ml")]
    return sorted(path.relative_to(root) for path in found)


def parsed(root: Path, path: Path) -> tuple[str, dict[str, Any]]:
    """Текст и разбор файла; не читается или не словарь — `NotRun`."""
    try:
        text = (root / path).read_text(encoding="utf-8")
        said = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise NotRun(f"{path} не разобран: {exc}") from exc
    if not isinstance(said, dict):
        raise NotRun(f"{path}: не словарь, а {type(said).__name__}")
    return text, said


def events(said: dict[Any, Any]) -> set[str]:
    """События `on:` — YAML 1.1 читает ключ `on` как `True`."""
    on = said.get("on", said.get(True))
    if isinstance(on, str):
        return {on}
    return {str(one) for one in on} if isinstance(on, (list, dict)) else set()


def writes(permissions: object) -> bool:
    """Даёт ли объявление прав запись хоть на что-то."""
    if permissions == "write-all":
        return True
    return isinstance(permissions, dict) and "write" in permissions.values()


def jobs_of(path: Path, said: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Джобы прогона; у составного действия — один безымянный с его шагами."""
    if path.name.startswith("action."):
        runs = said.get("runs")
        if not isinstance(runs, dict):
            runs = {}
        return {"(составное)": {"steps": runs.get("steps") or [], "permissions": "write-all"}}
    jobs = said.get("jobs")
    return (
        {str(k): v for k, v in jobs.items() if isinstance(v, dict)}
        if isinstance(jobs, dict)
        else {}
    )


def uses_of(job: dict[str, Any]) -> list[str]:
    """Все `uses:` джоба — вызов прогона и шаги."""
    found = [str(job["uses"])] if "uses" in job else []
    steps = job.get("steps")
    if not isinstance(steps, list):
        steps = []
    return found + [
        str(step["uses"]) for step in steps if isinstance(step, dict) and "uses" in step
    ]


def pin_problem(uses: str) -> str:
    """Что не так с закреплением `uses:`; пусто — законно или своё по пути."""
    if uses.startswith("./"):
        return ""
    if uses.startswith("docker://"):
        return "" if DIGEST_RE.search(uses) else "образ контейнера не по digest"
    name, _, ref = uses.partition("@")
    if SHA_RE.fullmatch(ref):
        return ""
    if name.split("/")[0].lower() == FAMILY_OWNER:
        return "" if RELEASE_RE.fullmatch(ref) else "семейное не по тегу выпуска и не по sha"
    return "стороннее действие не на полном sha"


def judge(
    path: Path,
    text: str,
    said: dict[str, Any],
    exceptions: tuple[dict[str, str], dict[tuple[str, str], str]] = ({}, {}),
) -> tuple[list[str], set[tuple[str, str]]]:
    """Находки файла и исключения, которые в нём встретились."""
    found: list[str] = []
    met: set[tuple[str, str]] = set()
    # КЛЮЧ ИСКЛЮЧЕНИЯ — ПУТЬ ОТ КОРНЯ, А НЕ ИМЯ: у всех составных действий имя
    # `action.yml`, и исключение одного разрешило бы форму в каждом (взгляд на #1634).
    name = path.as_posix()
    target_allowed, branch_allowed = exceptions
    trues = 0
    if "pull_request_target" in events(said) and name not in target_allowed:
        found.append(f"{path}: pull_request_target — исполняет голову изменения с правами базы")
    top = said.get("permissions")
    if top == "write-all":
        found.append(f"{path}: permissions: write-all у файла")
    for job_name, job in jobs_of(path, said).items():
        where = f"{path}:{job_name}"
        rights = job.get("permissions", top)
        if job.get("permissions") == "write-all" and not path.name.startswith("action."):
            found.append(f"{where}: permissions: write-all у джоба")
        if "steps" in job and rights is None:
            found.append(f"{where}: прав не объявлено ни у джоба, ни у файла")
        for step in job.get("steps") or []:
            if not isinstance(step, dict) or not str(step.get("uses", "")).startswith(CHECKOUT):
                continue
            given = step.get("with")
            value = given.get(PERSIST) if isinstance(given, dict) else None
            if str(value).strip().lower() == "true":
                trues += 1
            if not writes(rights):
                continue
            if not isinstance(given, dict) or PERSIST not in given:
                found.append(f"{where}: {CHECKOUT} в джобе с правом записи без явного {PERSIST}")
            elif EXPRESSION in str(value):
                found.append(
                    f"{where}: {PERSIST}: {value} — выражение вместо значения: "
                    "явное false либо true с причиной комментарием"
                )
        for uses in uses_of(job):
            problem = pin_problem(uses)
            if not problem:
                continue
            if (name, uses) in branch_allowed:
                met.add((name, uses))
                continue
            found.append(f"{where}: {uses} — {problem}")
    lines = 0
    for number, line in enumerate(text.splitlines() if trues else [], 1):
        value = TRUE_RE.search(line)
        if not value:
            continue
        lines += 1
        if not REASON_RE.search(line[value.end() :]):
            found.append(f"{path}:{number}: {PERSIST}: true без причины комментарием на строке")
    # СВЕРКА СЧЁТОМ, А НЕ ЕЩЁ ОДНОЙ ФОРМОЙ СТРОКИ (210: второй круг по
    # `TRUE_RE`, #1634 → #1650). Разбор знает, сколько выгрузок держат `true`;
    # строк ключа найдено меньше — шаг записан в строку, значение стоит на
    # другой строке или задано якорем YAML, и причину искать негде. Это отказ,
    # а не молчание: запишите ключ блочно, с причиной на его строке.
    if lines < trues:
        found.append(
            f"{path}: {PERSIST}: true у выгрузок {trues}, а строк ключа найдено {lines} — "
            "запись, где причину не найти строкой (шаг в строку, значение на другой "
            "строке, якорь); запишите ключ блочно с причиной комментарием"
        )
    return found, met


def look(root: Path) -> list[str]:
    """Все находки по дереву, включая исключения, пережившие своё место."""
    found: list[str] = []
    met: set[tuple[str, str]] = set()
    target_allowed, branch_allowed = exceptions = allowed(root)
    for path in files(root):
        text, said = parsed(root, path)
        told, seen = judge(path, text, said, exceptions)
        found += told
        met |= seen
        if path.as_posix() in target_allowed and "pull_request_target" in events(said):
            met.add((path.as_posix(), "pull_request_target"))
    for key in sorted(branch_allowed.keys() - met):
        found.append(f"исключение пережило место: {key[0]} → {key[1]}")
    for name in target_allowed.keys() - {one for one, what in met if what == "pull_request_target"}:
        found.append(f"исключение пережило место: {name} → pull_request_target")
    return found


def main(argv: list[str] | None = None) -> int:
    """Точка входа: обходит прогоны и объявляет исход."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    parser.add_argument(
        "--enforce", action="store_true", help="найденное — отказ, а не предупреждение"
    )
    args = parser.parse_args(argv)
    try:
        found = look(args.root)
    except NotRun as exc:
        print(f"гейт не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if found:
        # У ПОТРЕБИТЕЛЯ — ПРЕДУПРЕЖДЕНИЕ, ОТКАЗ — КЛЮЧОМ `--enforce` (взгляд на
        # #1634, `c6f9696`): шаг `pipeline` судит дерево потребителя, писанное
        # без гейта, и без выключателя краснел бы с первым подъёмом тега (051).
        # Приём и вход — те же, что у дедлайна (`mechanism-gates-enforce`).
        level = "error" if args.enforce else "warning"
        for one in found:
            print(f"::{level}::{check_deadline.escaped(one, prop=False)}")
        verdict = "отвергнуто" if args.enforce else "предупреждено"
        print(
            f"{verdict}: опасных форм прогонов {len(found)} — они уехали бы к каждому потребителю"
        )
        for one in found:
            print(f"  {one}")
        print("Перечень форм и исключения — шапка scripts/check_workflow_forms.py (#1430).")
        return EXIT_REJECTED if args.enforce else EXIT_OK
    print(f"опасных форм в прогонах нет ({len(files(args.root))} файлов)")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
