"""Вынесенные шаги: дубль шапки объявлен намеренным — и потому держится.

Площадка требует от переиспользуемого прогона ОТДЕЛЬНОГО ФАЙЛА, и пояснение в
их шапках неизбежно одно на всех: вынести его нечем — комментарий не
подключается, а прогон зовут по адресу файла. Намеренный дубль законен, когда
объявлен
([071](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/071-deliberate-duplication-is-signed.md)),
но объявление без механизма — обещание: копии расходятся молча, и узнают об
этом по разному поведению двух шагов, а не по красному
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ЧТО ЗДЕСЬ ДЕРЖИТСЯ: что шапки СОВПАДАЮТ дословно, что каждая объявляет дубль
намеренным, и что каждый вынесенный шаг — действительно вызываемый. Чего НЕ
держится: полезности самого пояснения — это суждение о смысле (057).
"""

from __future__ import annotations

import re
from typing import Final

import pytest
import yaml

from tests.conftest import ROOT, load_script, walk

policy = load_script("pipeline_checks.py")
preflight = load_script("preflight.py")

STEPS: Final = ROOT / ".github" / "workflows"
#: Приставка вынесенного шага.
PREFIX: Final = "step-"
#: Слова, которыми дубль объявляется намеренным. Не «похоже на объявление», а
#: ровно эта строка: признак, принимающий любую прозу о дублях, принял бы и
#: рассуждение о них (166).
DECLARED: Final = "ДУБЛЬ ЭТОЙ ШАПКИ НАМЕРЕННЫЙ"
#: Где кончается общая шапка и начинается своё: строка имени прогона.
UNTIL: Final = "name: "


def steps() -> dict[str, str]:
    """Вынесенные шаги дерева: имя файла → его текст."""
    return {path.name: path.read_text(encoding="utf-8") for path in walk(STEPS, f"{PREFIX}*.yml")}


def head_of(said: str) -> str:
    """Общая шапка: всё до строки имени прогона."""
    return said.split(f"\n{UNTIL}", 1)[0]


def test_the_steps_exist() -> None:
    """Вынесенные шаги в дереве есть — иначе проверка держит пустоту (075)."""
    assert steps(), "вынесенных шагов нет ни одного — сверять нечего"


@pytest.mark.parametrize("name", sorted(steps()), ids=lambda one: one)
def test_every_step_declares_its_duplication(name: str) -> None:
    """Каждый шаг объявляет дубль шапки намеренным (071).

    Необъявленный дубль неотличим от копипасты, и следующая правка починит
    один файл из девяти.
    """
    assert DECLARED in head_of(steps()[name]), f"{name}: дубль шапки не объявлен намеренным"


def test_all_the_heads_are_the_same() -> None:
    """Шапки совпадают ДОСЛОВНО: объявленный дубль обязан быть дублем.

    Объявить дубль и дать копиям разойтись — хуже, чем не объявлять: читатель
    первой копии считает, что прочёл все девять
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    """
    heads = {name: head_of(said) for name, said in steps().items()}
    first = sorted(heads)[0]
    apart = sorted(name for name, said in heads.items() if said != heads[first])
    assert not apart, (
        f"шапки разошлись с «{first}»: {apart} — объявленный дубль перестал быть дублем"
    )


@pytest.mark.parametrize("name", sorted(steps()), ids=lambda one: one)
def test_every_step_is_actually_callable(name: str) -> None:
    """Файл с приставкой шага — действительно ВЫЗЫВАЕМЫЙ прогон.

    Приставка имени — объявление, а не свойство: прогон без `workflow_call`
    площадка звать откажется, и узнает об этом потребитель, а не мы (045).
    """
    said = yaml.safe_load(steps()[name])
    events = said.get("on", said.get(True)) or {}
    names = set(events) if isinstance(events, dict) else set(events or [])
    assert policy.CALLED in {str(one) for one in names}, (
        f"{name}: приставка обещает вызываемый прогон, а события «{policy.CALLED}» нет"
    )


#: Каталог, куда общий шаг кладёт код конвейера (#990): имя переменной — у
#: предполётной, которая ставит её же локально (209).
MECHANISMS: Final = f"${preflight.MECHANISMS}/"
#: Наш код в дереве: путь к нему без `MECHANISMS` значит «из дерева вызывающего».
OUR_CODE: Final = re.compile(r"(?<![\w$/])(\./)?(scripts|packages)/")
#: Источник кода у второго checkout: репозиторий и коммит ВЫЗВАННОГО файла.
#: Замер прогоном 01.10.2026 (#997): `github.job_workflow_sha` у вызванного
#: шага пуст, а `job.workflow_*` называют сам вызванный файл.
OUR_REPO: Final = "${{ job.workflow_repository }}"
OUR_SHA: Final = "${{ job.workflow_sha }}"
#: Шаг, чей предмет — КОД ПОТРЕБИТЕЛЯ, а не наш: линтер проверяет дерево
#: вызывающего, и его пути — наполнение проекта (шов, #992), а не адрес нашего
#: кода. Исключение названо, а не выведено из текста (046).
SUBJECT_IS_THE_CALLER: Final = frozenset({"step-lint.yml"})


def commands_of(said: str) -> list[str]:
    """Строки команд `run:` всех шагов, без комментариев."""
    document = yaml.safe_load(said)
    found: list[str] = []
    for job in (document.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            for line in str(step.get("run") or "").splitlines():
                if line.strip() and not line.strip().startswith("#"):
                    found.append(line)
    return found


def code_checkouts(said: str) -> list[dict[str, object]]:
    """Шаги checkout, которые берут НАШ репозиторий, а не дерево вызывающего."""
    document = yaml.safe_load(said)
    return [
        step.get("with") or {}
        for job in (document.get("jobs") or {}).values()
        for step in job.get("steps") or []
        if str(step.get("uses") or "").startswith("actions/checkout@")
        and (step.get("with") or {}).get("repository") == OUR_REPO
    ]


@pytest.mark.parametrize(
    ("line", "is_ours"),
    [
        ("python scripts/debt.py", True),
        ("pip install ./packages/transport", True),
        (f"python {MECHANISMS}scripts/debt.py", False),
        (f"pip install {MECHANISMS}packages/transport", False),
        ("git diff --name-only -- docs/", False),
    ],
    ids=[
        "скрипт из дерева",
        "пакет из дерева",
        "скрипт из checkout",
        "пакет из checkout",
        "чужой путь",
    ],
)
def test_our_code_from_the_callers_tree_is_told(line: str, is_ours: bool) -> None:
    """Путь к нашему коду из дерева вызывающего отличается от пути из checkout."""
    assert bool(OUR_CODE.search(line)) is is_ours


@pytest.mark.parametrize("name", sorted(steps()), ids=lambda one: one)
def test_a_step_takes_our_code_by_its_own_checkout(name: str) -> None:
    """Общий шаг берёт наш код своим checkout на коммите вызова, а не из дерева (#990).

    У потребителя нашего `scripts/` и `packages/` нет: шаг, зовущий их из дерева
    вызывающего, у него падает на первом прогоне, а у нас зеленеет — потому что
    наше дерево и есть код. Так и было до #990: девять шагов, ни одного второго
    checkout, а проба по внешнему адресу шла в нашем дереве и этого не видела.
    """
    said = steps()[name]
    if name in SUBJECT_IS_THE_CALLER:
        assert not code_checkouts(said), f"{name}: предмет шага — код вызывающего, наш ему не нужен"
        return
    stray = [line.strip() for line in commands_of(said) if OUR_CODE.search(line)]
    assert not stray, f"{name}: наш код зовётся из дерева вызывающего — {stray}"
    if not any(MECHANISMS in line for line in commands_of(said)):
        return
    taken = code_checkouts(said)
    assert len(taken) == 1, (
        f"{name}: код конвейера зовётся, а checkout нашего репозитория — {len(taken)}"
    )
    assert taken[0].get("ref") == OUR_SHA, (
        f"{name}: код берётся не на коммите вызова — прибивка к тегу его не прибьёт"
    )


#: Начало и конец блока, которым общий шаг берёт наш код (#990).
BLOCK_FROM: Final = "      # КОД КОНВЕЙЕРА — СВОИМ CHECKOUT"
BLOCK_TO: Final = '>>"$GITHUB_ENV"'
#: Слова, которыми дубль блока объявлен намеренным.
BLOCK_DECLARED: Final = "ДУБЛЬ ЭТОГО БЛОКА НАМЕРЕННЫЙ"


def code_block(said: str) -> str:
    """Блок шагов, которым общий шаг берёт наш код: от шапки до экспорта каталога."""
    start = said.index(BLOCK_FROM)
    return said[start : said.index(BLOCK_TO, start) + len(BLOCK_TO)]


def test_the_code_block_is_one_in_every_step() -> None:
    """Блок «код конвейера своим checkout» один во всех шагах и полон (взгляд на #997).

    Блок стоит в каждом шаге, зовущем наш код, — площадка не подключает шаги
    внутрь шага, — и дубль объявлен (071). Совпадение держится здесь, а с ним и
    то, ради чего блок заведён: охрана пустого коммита вызова (045) перед
    checkout и вынос кода из дерева потребителя под ту же переменную, что
    ставит предполётная. Снять охрану или вынос в одном файле — значит
    разойтись с остальными, во всех — нарушить признаки ниже.
    """
    blocks = {
        name: code_block(said)
        for name, said in steps().items()
        if any(MECHANISMS in line for line in commands_of(said))
    }
    assert blocks, "ни один шаг не зовёт наш код — сверять нечего (075)"
    first = sorted(blocks)[0]
    apart = sorted(name for name, block in blocks.items() if block != blocks[first])
    assert not apart, f"блок кода конвейера разошёлся с «{first}»: {apart}"
    block = blocks[first]
    assert BLOCK_DECLARED in block, "дубль блока не объявлен намеренным (071)"
    checkout = block.index("uses: actions/checkout@")
    # Охраны две, по обоим доводам checkout: пустой коммит не берёт код, а
    # пустой репозиторий молча берёт дерево вызывающего (взгляд на #997).
    for variable, said in (("AT", OUR_SHA), ("FROM", OUR_REPO)):
        assert f"{variable}: {said}" in block, f"охране не передан {said}"
        guard = block.index(f'if [ -z "${variable}" ]')
        assert guard < checkout, f"охрана пустого {said} стоит не перед checkout (045)"
    assert 'mv .pipeline-mechanisms "$RUNNER_TEMP/mechanisms"' in block, "код не уносится из дерева"
    assert f'echo "{preflight.MECHANISMS}=' in block, (
        "шаг ставит не ту переменную, что предполётная"
    )
