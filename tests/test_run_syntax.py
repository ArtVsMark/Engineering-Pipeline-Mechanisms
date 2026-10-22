"""Каждый сценарий `run:` разбирается оболочкой, которой его исполнит площадка.

ЗАЧЕМ (находка взгляда на #1423). Шаг сверки архива переехал из `badges.yml`
в `step-facts.yml` без строки `esac`, и полный набор остался зелёным: ни одна
проверка не спрашивала у `bash`, разбирается ли сценарий вообще. Площадка
узнала бы об этом первым заходом с `archive: true` — и он не опубликовал бы
ни фактов, ни архива. Замер 16.10.2026: сценариев `bash` в дереве 207, не
разбирался ровно один — этот.

ГРАНИЦА НАЗВАНА (195). Проверяется только разбор (`bash -n`), а не исполнение;
выражения площадки `${{ … }}` заменяются словом, потому что их значение
известно только в прогоне. Сценарии с иной оболочкой (`shell: python` и
подобные) не проверяются — их в дереве нет, и это сверяет сам тест. Оболочка
берётся так же, как её берёт площадка: у шага, иначе из `defaults.run.shell`
джоба, иначе прогона (взгляд на #1423) — умолчание выше шага прежде не
читалось, и такой сценарий ушёл бы в `bash -n`.

СОСЕД ЧИТАЕТ ТО ЖЕ ПОЛЕ ИНАЧЕ, И ЭТО НЕ СПОР (195, взгляд на #1479).
`tests/test_python_after_setup.py::unparsed` умолчание `defaults.run.shell`
отвергает: тот гейт ищет вызов `python` по строкам шагов и чужую оболочку не
разбирает, поэтому прогон с умолчанием для него — отказ, а не предмет. Здесь
то же умолчание разрешается, чтобы шаг ушёл в свою оболочку, а не в `bash -n`.
Прогон с умолчанием, таким образом, отвергнет первый гейт, а этот уведёт в
«иную оболочку». Замер 17.10.2026: умолчаний оболочки в прогонах и действиях
дерева ноль — оба прочтения сегодня держат пустоту.

ЗАПАСНАЯ ОБОЛОЧКА «bash» ВЕРНА ДЛЯ LINUX И MACOS (поздний взгляд на #1479). На
раннере `windows-*` площадка без `shell` берёт `pwsh`, и `bash -n` судил бы не
ту оболочку. Таких `runs-on` в дереве нет — это держит
`test_no_step_runs_on_windows`, а не слово здесь.

МАССИВ ПОД `set -u` РАСКРЫВАЕТСЯ ФОРМОЙ `${a[@]+"${a[@]}"}` (поздний взгляд на
#1530). `"${a[@]}"` у пустого массива под `set -u` в bash ниже 4.4 — «unbound
variable», а сценарии шагов гоняет и предполётная локального окна, где на
macOS bash 3.2. Граница названа: гейт судит форму, а не исполняет сценарий на
старом bash — его в окружении проверки нет.
"""

import re
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from tests.conftest import ROOT, walk, walk_deep

#: Выражение площадки: его значение известно только в прогоне.
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


def default_shell(holder: Any) -> str:
    """`defaults.run.shell` прогона или джоба; нет — пусто."""
    defaults = (holder or {}).get("defaults") if isinstance(holder, dict) else None
    run = (defaults or {}).get("run") if isinstance(defaults, dict) else None
    return str((run or {}).get("shell") or "") if isinstance(run, dict) else ""


def steps_with_shells(document: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Шаги с `run:` и оболочкой, которой их исполнит площадка: шаг → джоб → прогон."""
    found: list[tuple[dict[str, Any], str]] = []
    top = default_shell(document)
    for job in (document.get("jobs") or {}).values():
        own = default_shell(job) or top
        found += [
            (step, str(step.get("shell") or own or "bash"))
            for step in (job or {}).get("steps") or []
            if step.get("run")
        ]
    runs = document.get("runs")
    if isinstance(runs, dict):
        found += [
            (step, str(step.get("shell") or "bash"))
            for step in runs.get("steps") or []
            if step.get("run")
        ]
    return found


def scripts() -> list[tuple[str, str, str]]:
    """Сценарии `run:` всех прогонов и действий: файл, имя шага, оболочка."""
    found: list[tuple[str, str, str]] = []
    for path in walk_deep(ROOT / ".github", "*.yml"):
        document: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        for step, shell in steps_with_shells(document):
            name = f"{path.relative_to(ROOT)}: {step.get('name') or step.get('id') or '?'}"
            found.append((name, str(step["run"]), shell))
    return found


def test_the_shell_is_taken_where_the_platform_takes_it() -> None:
    """Оболочка — у шага, иначе умолчание джоба, иначе прогона (взгляд на #1423)."""
    document = {
        "defaults": {"run": {"shell": "pwsh"}},
        "jobs": {
            "a": {"defaults": {"run": {"shell": "python"}}, "steps": [{"run": "x"}]},
            "b": {"steps": [{"run": "y"}, {"run": "z", "shell": "bash"}]},
        },
    }
    assert [shell for _, shell in steps_with_shells(document)] == ["python", "pwsh", "bash"]
    assert [
        shell for _, shell in steps_with_shells({"jobs": {"c": {"steps": [{"run": "w"}]}}})
    ] == ["bash"]


def test_every_bash_script_parses() -> None:
    """`bash -n` разбирает каждый сценарий; незакрытый `case` или `if` — отказ."""
    found = scripts()
    assert found, "сценариев `run:` не нашлось — обход не туда (075)"
    others = sorted({shell for _, _, shell in found if not shell.startswith("bash")})
    assert not others, f"сценарии с иной оболочкой этот тест не проверяет: {others}"
    broken = []
    for name, body, _ in found:
        done = subprocess.run(
            ["bash", "-n"],
            input=EXPRESSION.sub("X", body),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if done.returncode:
            broken.append(f"{name} — {done.stderr.strip()}")
    assert not broken, "сценарий не разбирается оболочкой:\n" + "\n".join(broken)


#: Флаг `-u` в строке `set`: `set -u`, `set -euo pipefail`, `set -uo …`.
SET_U: Final = re.compile(r"^\s*set\s+-[a-z]*u", re.MULTILINE)
#: Раскрытие массива без защиты пустого: `"${a[@]}"`, а не `${a[@]+"${a[@]}"}`.
BARE_ARRAY: Final = re.compile(r'(?<!\+)"\$\{\w+\[@\]\}"')


def shell_sources() -> list[tuple[str, str]]:
    """Сценарии bash: шаги `run:` с этой оболочкой и хуки окна `.sh`."""
    found = [(name, text) for name, text, shell in scripts() if shell == "bash"]
    hooks = walk(ROOT / ".claude" / "hooks", "*.sh")
    found += [(str(Path(one).relative_to(ROOT)), one.read_text(encoding="utf-8")) for one in hooks]
    return found


def bare_arrays(text: str) -> list[str]:
    """Раскрытия массива без защиты пустого — только там, где стоит `set -u`."""
    return BARE_ARRAY.findall(text) if SET_U.search(text) else []


def test_an_array_under_set_u_survives_old_bash() -> None:
    """Под `set -u` массив раскрывается формой, которую принимает и bash 3.2."""
    seen = shell_sources()
    assert any(SET_U.search(text) for _, text in seen), (
        "сценариев с set -u нет — предмета нет (075)"
    )
    bad = {name: found for name, text in seen if (found := bare_arrays(text))}
    assert not bad, (
        f'массив под set -u раскрыт без защиты пустого: {bad} — пишите ${{a[@]+"${{a[@]}}"}}'
    )


@pytest.mark.parametrize(
    ("text", "bad"),
    [
        ('set -euo pipefail\ncmd "${args[@]}"\n', 1),
        ('set -euo pipefail\ncmd ${args[@]+"${args[@]}"}\n', 0),
        ('set -e\ncmd "${args[@]}"\n', 0),
        ('  set -uo pipefail\ncmd "${a[@]}" "${b[@]}"\n', 2),
    ],
    ids=["голый-под-u", "защищённый", "без-u", "два-голых"],
)
def test_the_bare_array_predicate(text: str, bad: int) -> None:
    """Предикат различает форму и видит `-u` в любой связке флагов."""
    assert len(bare_arrays(text)) == bad


def test_no_step_runs_on_windows() -> None:
    """Раннеров `windows-*` в дереве нет: запасная оболочка «bash» верна (взгляд на #1479)."""
    windows = [
        f"{path.relative_to(ROOT)}: {name}"
        for path in walk_deep(ROOT / ".github", "*.yml")
        if isinstance(document := yaml.safe_load(path.read_text(encoding="utf-8")), dict)
        for name, job in (document.get("jobs") or {}).items()
        if "windows" in str((job or {}).get("runs-on") or "").lower()
    ]
    assert not windows, f"джоб на windows: {windows} — там площадка берёт pwsh, а не bash"
