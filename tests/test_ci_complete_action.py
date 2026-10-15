"""Сводный гейт-действие находит свой код от СВОЕГО каталога, а не от дерева вызывающего (#1385).

Потребитель зовёт `.github/actions/ci-complete` адресом с тегом. Площадка
кладёт репозиторий действия по этому тегу ЦЕЛИКОМ, и `github.action_path`
указывает в его каталог действия. Значит, корень поставщика —
`<action_path>/../../..`, а рабочее дерево — чужое. У нас же действие зовётся
`./`, и там оба корня совпадают: прогон здесь разницы не видит (находка
`3fb4725` внешнего взгляда на #1400, правило 107).

Поэтому проверяется само отношение, которое у потребителя другое:

* каждый путь, который действие строит от своего каталога, существует от
  каталога действия в этом дереве — а тег несёт дерево целиком, и тест,
  прошедший на коммите тега, держит согласие путей у тега (находка `c2bf0b3`);
* скрипт гейта заводится, когда рабочий каталог — не наше дерево.

ГРАНИЦА НАЗВАНА (195). Настоящий вызов адресом с тегом в чужом дереве — дело
пробы передачи (#1388): здесь его не воспроизвести, выкачки по тегу у теста нет.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import yaml

from tests.conftest import ROOT

ACTION: Final = ROOT / ".github" / "actions" / "ci-complete" / "action.yml"

#: Корень поставщика, как его строит действие: от своего каталога вверх.
ROOT_FROM_ACTION: Final = re.compile(
    r"(?:\$GITHUB_ACTION_PATH|\$\{\{ github\.action_path \}\})/((?:\.\./)*\.\.)"
)

#: Путь, который действие берёт от корня поставщика.
FROM_ROOT: Final = re.compile(r"(?:\$GITHUB_ACTION_PATH/(?:\.\./)*\.\.|\$MECHANISMS)/([\w./-]+)")


def action_text() -> str:
    """Текст действия целиком: пути стоят и в `run:`, и в `env:`."""
    return ACTION.read_text(encoding="utf-8")


def roots(text: str) -> set[Path]:
    """Каталоги, которые действие называет корнем поставщика, — от каталога действия."""
    return {(ACTION.parent / up).resolve() for up in ROOT_FROM_ACTION.findall(text)}


def wanted(text: str) -> set[str]:
    """Пути от корня поставщика, которые действие исполняет или ставит."""
    return {one.rstrip("/") for one in FROM_ROOT.findall(text)}


def test_the_action_names_one_supplier_root_and_it_is_the_tree() -> None:
    """Каждое «вверх от каталога действия» ведёт в корень репозитория, а не мимо."""
    named = roots(action_text())
    assert named, "действие не строит корень от своего каталога — предмета нет (075)"
    assert named == {ROOT.resolve()}, f"корень поставщика у действия — не корень дерева: {named}"


def test_every_path_the_action_takes_from_its_root_exists() -> None:
    """Скрипт гейта и пакет транспорта лежат там, куда действие за ними идёт."""
    paths = wanted(action_text())
    assert {"scripts/ci_complete.py", "packages/transport"} <= paths, paths
    missing = sorted(one for one in paths if not (ROOT / one).exists())
    assert not missing, f"действие идёт за тем, чего у тега не будет: {missing}"


def test_the_gate_script_starts_outside_our_tree(tmp_path: Path) -> None:
    """Скрипт гейта заводится, когда рабочий каталог — чужое дерево, как у потребителя."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ci_complete.py"), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stderr


def test_the_patterns_catch_a_root_and_a_path() -> None:
    """Образцы ловят обе формы корня и не ловят путь от рабочего дерева."""
    text = yaml.safe_dump(
        {
            "a": "pip install $GITHUB_ACTION_PATH/../../../packages/transport",
            "b": "${{ github.action_path }}/../..",
            "c": 'python "$MECHANISMS/scripts/x.py"',
            "d": "python scripts/y.py",
        },
        width=1000,
    )
    assert wanted(text) == {"packages/transport", "scripts/x.py"}
    assert len(ROOT_FROM_ACTION.findall(text)) == 2
