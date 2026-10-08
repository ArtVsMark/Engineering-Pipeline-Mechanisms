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

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Final

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


#: Наш скрипт из checkout в ЛЮБОЙ записи переменной: `$MECHANISMS`, `${MECHANISMS}`,
#: `"$MECHANISMS"` — перед `/scripts/`.
SCRIPT_FROM_CHECKOUT: Final = re.compile(rf"\$\{{?{preflight.MECHANISMS}\}}?\"?/scripts/")


def odd_calls(said: str) -> list[str]:
    """Вызовы нашего скрипта из checkout не той формой, что читает предполётная.

    Правило строгое, а не разбор форм (навык `build-a-gate`, шаг 3а): в строке
    команды ОДНО упоминание, и оно — её начало. Второй вызов после
    каноничного `plain` не приведёт, а `NEEDS_PLATFORM` сверяет только начало
    строки (взгляд на #1015).
    """
    return [
        line.strip()
        for line in commands_of(said)
        if (found := len(SCRIPT_FROM_CHECKOUT.findall(line)))
        and (found > 1 or not line.strip().startswith(preflight.FROM_CHECKOUT))
    ]


@pytest.mark.parametrize(
    ("line", "is_odd"),
    [
        (f"{preflight.FROM_CHECKOUT}debt.py || rc=$?", False),
        ('python "$MECHANISMS"/scripts/debt.py', True),
        ("python ${MECHANISMS}/scripts/debt.py", True),
        ("python3 $MECHANISMS/scripts/debt.py", True),
        (f"rc=0; {preflight.FROM_CHECKOUT}debt.py", True),
        ("python -m pip install $MECHANISMS/packages/transport", False),
        (f"{preflight.FROM_CHECKOUT}debt.py && {preflight.FROM_CHECKOUT}x.py", True),
    ],
    ids=[
        "каноничная",
        "в кавычках",
        "в скобках",
        "python3",
        "не в начале",
        "пакет",
        "второй вызов после каноничного",
    ],
)
def test_an_odd_call_form_is_told(line: str, is_odd: bool) -> None:
    """Обе половины: иная форма вызова краснеет, каноничная и установка пакета — нет."""
    said = yaml.safe_dump({"jobs": {"a": {"steps": [{"run": line}]}}}, allow_unicode=True)
    assert bool(odd_calls(said)) is is_odd


@pytest.mark.parametrize("name", sorted(steps()), ids=lambda one: one)
def test_our_script_is_called_in_the_one_form(name: str) -> None:
    """Скрипт из checkout зовётся ровно формой `preflight.FROM_CHECKOUT` (взгляд на #997).

    Предполётная приводит к прямому вызову только её; иную форму она потеряла
    бы молча — та самая потеря (045), от которой заведён `plain`. Замер
    01.10.2026 (`SCRIPT_FROM_CHECKOUT` по `commands_of` всех шагов): вызовов
    скриптов из checkout 20, иной формы — ноль.
    """
    assert not odd_calls(steps()[name]), f"{name}: вызов не той формой — {odd_calls(steps()[name])}"


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
    # ПО ДЖОБУ, А НЕ ПО ФАЙЛУ (#993): у шага взгляда джобов семь, и каждый
    # исполняется на своей машине — выкачка одного джоба другому не видна.
    for job_id, job in (yaml.safe_load(said).get("jobs") or {}).items():
        alone = yaml.safe_dump({"jobs": {job_id: job}}, allow_unicode=True)
        if not any(MECHANISMS in line for line in commands_of(alone)):
            continue
        taken = code_checkouts(alone)
        assert len(taken) == 1, (
            f"{name}:{job_id}: код конвейера зовётся, а checkout нашего репозитория — {len(taken)}"
        )
        assert taken[0].get("ref") == OUR_SHA, (
            f"{name}:{job_id}: код берётся не на коммите вызова — прибивка к тегу его не прибьёт"
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


#: Вход пробы переноса (#990): одно имя у всех шагов, зовущих наш код.
STRIP_INPUT: Final = "strip-ours"
#: Команда стирания нашего кода из дерева вызывающего — под входом и только.
STRIP_COMMAND: Final = "rm -rf scripts packages tests"


def test_every_step_with_our_code_takes_the_probe_input() -> None:
    """Шаг, зовущий наш код, объявляет вход `strip-ours`: логический, по умолчанию выключен (#990).

    Решение владельца 04.10.2026, вариант 2: проба переноса зовёт шаги со
    входом, стирающим наш код из дерева вызывающего. Потребитель вход не
    задаёт, поэтому умолчание — выключен: иначе шаг стирал бы его `scripts/`.
    """
    carrying = {
        name: said
        for name, said in steps().items()
        if any(MECHANISMS in line for line in commands_of(said))
    }
    assert carrying, "ни один шаг не зовёт наш код — сверять нечего (075)"
    wrong = []
    for name, said in sorted(carrying.items()):
        trigger = yaml.safe_load(said)[True]["workflow_call"] or {}
        declared = (trigger.get("inputs") or {}).get(STRIP_INPUT)
        if declared is None or declared.get("type") != "boolean" or declared.get("default"):
            wrong.append(name)
    assert not wrong, f"вход {STRIP_INPUT} не объявлен как выключенный логический: {wrong}"


def test_the_strip_happens_after_our_code_is_taken_and_only_under_the_input() -> None:
    """Стирание — в общем блоке, ПОСЛЕ выноса нашего кода и только под входом (#990).

    Раньше выноса оно стёрло бы и сам взятый код; без входа — дерево каждого
    потребителя.
    """
    block = next(
        code_block(said)
        for said in steps().values()
        if any(MECHANISMS in line for line in commands_of(said))
    )
    assert STRIP_COMMAND in block, "стирание под входом в блоке не найдено"
    assert "STRIP_OURS: ${{ inputs.strip-ours }}" in block, "входу не передан флаг шага"
    taken = block.index('mv .pipeline-mechanisms "$RUNNER_TEMP/mechanisms"')
    assert taken < block.index(STRIP_COMMAND), "наш код стирается раньше, чем вынесен"


def strip_step(said: str) -> dict[str, Any]:
    """Шаг блока кода, который выносит наш код и стирает его под входом."""
    for job in yaml.safe_load(said)["jobs"].values():
        for step in job.get("steps", []):
            if STRIP_COMMAND in str(step.get("run") or ""):
                return dict(step)
    raise AssertionError("шага со стиранием нет")


PROVIDER: Final = "ArtVsMark/Engineering-Pipeline-Mechanisms"
PROBE: Final = f"{PROVIDER}/.github/workflows/handover-probe.yml@refs/heads/main"
NEIGHBOUR: Final = "сосед/его-проект"
NEIGHBOUR_CI: Final = f"{NEIGHBOUR}/.github/workflows/ci.yml@refs/heads/main"


@pytest.mark.parametrize(
    ("strip", "caller", "frm", "flow", "code", "left"),
    [
        ("true", PROVIDER, PROVIDER, PROBE, 0, False),
        ("true", PROVIDER.lower(), PROVIDER, PROBE, 0, False),
        ("true", NEIGHBOUR, PROVIDER, NEIGHBOUR_CI, 1, True),
        ("true", NEIGHBOUR, NEIGHBOUR, NEIGHBOUR_CI, 1, True),
        (
            "true",
            PROVIDER,
            PROVIDER,
            f"{PROVIDER}/.github/workflows/ci.yml@refs/heads/main",
            1,
            True,
        ),
        ("false", NEIGHBOUR, PROVIDER, NEIGHBOUR_CI, 0, True),
    ],
    ids=["проба", "проба-иным-регистром", "чужой", "копия-у-соседа", "не-проба", "выключен"],
)
def test_the_strip_runs_only_in_the_providers_own_repository(
    tmp_path: Path, strip: str, caller: str, frm: str, flow: str, code: int, left: bool
) -> None:
    """Стирание по именам папок идёт только у поставщика; у соседа — отказ (взгляд на #1113).

    Исполняется сам шаг блока, а не сверяется его текст: у соседа под
    `scripts/` лежит его код, и словами «потребитель вход не задаёт» он не
    защищён.
    """
    step = strip_step(
        next(
            said
            for said in steps().values()
            if any(MECHANISMS in line for line in commands_of(said))
        )
    )
    for folder in ("scripts", "packages", "tests", ".pipeline-mechanisms"):
        (tmp_path / folder).mkdir()
    env = {
        **os.environ,
        "STRIP_OURS": strip,
        # «копия-у-соседа»: площадка называет репозиторием шага самого соседа.
        "FROM": frm,
        "GITHUB_REPOSITORY": caller,
        "CALLER": flow,
        "RUNNER_TEMP": str(tmp_path / "runner"),
        "GITHUB_ENV": str(tmp_path / "github-env"),
    }
    (tmp_path / "runner").mkdir()
    done = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == code, done.stderr or done.stdout
    assert (tmp_path / "scripts").exists() is left
    assert step["env"]["FROM"] == "${{ job.workflow_repository }}"
    assert step["env"]["CALLER"] == "${{ github.workflow_ref }}"


def queued_callers() -> list[tuple[str, str, bool, dict[str, Any], dict[str, Any]]]:
    """Вызовы наших шагов, стоящие в группе: (файл, джоб, группа прогона?, вызов, шаг).

    ГРУППА ПРОГОНА — НЕ ТО ЖЕ, ЧТО ГРУППА ДЖОБА. Прогон занимает свою группу
    ещё до того, как вычислен `if` любого его джоба, — условие у вызова от
    вытеснения там не защищает (взгляд на #1208). Поэтому место группы
    передаётся дальше, а не сливается с группой джоба.
    """
    found = []
    for path in walk(STEPS, "*.yml"):
        flow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in (flow.get("jobs") or {}).items():
            uses = str(job.get("uses") or "")
            if not uses.startswith("./") or not (job.get("concurrency") or flow.get("concurrency")):
                continue
            step = yaml.safe_load((ROOT / uses).read_text(encoding="utf-8"))
            found.append((path.name, name, not job.get("concurrency"), job, step))
    return found


def test_a_queued_caller_is_measured() -> None:
    """Предмет есть: вызов шага в группе джоба есть — иначе проверка пуста (075)."""
    assert any(not whole for _, _, whole, _, _ in queued_callers()), (
        "вызовов шага в группе джоба не найдено — предмет проверки пропал"
    )


@pytest.mark.parametrize(
    ("caller", "job", "whole", "called", "step"),
    [pytest.param(*one, id=f"{one[0]}:{one[1]}") for one in queued_callers()],
)
def test_a_queue_does_not_take_what_the_step_skips(
    caller: str, job: str, whole: bool, called: dict[str, Any], step: dict[str, Any]
) -> None:
    """Условие шага стоит и у вызова в группе — до группы, а не только внутри неё.

    Группа держит одно ожидающее место, и новый ожидающий вытесняет прежнего.
    Событие, которое шаг всё равно пропустит, вставшее в очередь, снимало бы
    ожидающий настоящий прогон: так было у `task-items` — незлитое закрытие
    против разбора слитого (взгляд на #1186). У группы ПРОГОНА условие джоба
    не спасает вовсе: шаг с условием там — красное, условие уходит в события.
    """
    said = " ".join(str(called.get("if") or "").split())
    for name, inner in step["jobs"].items():
        wanted = " ".join(str(inner.get("if") or "").split())
        if not wanted:
            continue
        assert not whole, (
            f"{caller}:{job} — шаг `{name}` с условием «{wanted}» стоит в группе ПРОГОНА: "
            "её занимают до условия джоба — сузьте события или перенесите группу в джоб"
        )
        assert wanted == said, (
            f"{caller}:{job} — у шага `{name}` условие «{wanted}», у вызова «{said}»"
        )


def test_a_run_group_does_not_pass_on_a_matching_condition() -> None:
    """Совпавшее условие не спасает группу прогона: её занимают до `if` джоба (#1208)."""
    condition = "github.event.pull_request.merged == true"
    step = {"jobs": {"inner": {"if": condition}}}
    with pytest.raises(AssertionError, match="группе ПРОГОНА"):
        test_a_queue_does_not_take_what_the_step_skips("x.yml", "j", True, {"if": condition}, step)
    test_a_queue_does_not_take_what_the_step_skips("x.yml", "j", False, {"if": condition}, step)
