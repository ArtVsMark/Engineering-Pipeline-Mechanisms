"""Команда подключения: заготовка выводится из дерева, а не пишется руками.

Порядок подключения, живущий прозой, исполняется по-разному каждым, кто его
прочёл, — и ровно так разошлись пять конвейеров семьи. Проверяется здесь то,
без чего заход был бы распечаткой памяти:

* состав шагов берётся из ПОМЕТОК дерева: список руками отстал бы на первом же
  вынесенном шаге, и отстал бы молча (022, 049);
* прибивка — тег ВЫПУСКА, а не версия поверхности: это разные числа, и
  вторая указала бы на тег, которого нет;
* имя записи проверки СОСТАВНОЕ: голое имя оставило бы потребителя со сводным
  гейтом, ждущим записи, которой никто не выдаст (045);
* класс проверки заход не решает: это свойство потребителя (174).
"""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FAKE_VERSION, ROOT, RunScript, load_script, needs_history

module = load_script("onboard.py")
policy = load_script("pipeline_checks.py")

#: Шаг, помеченный отдаваемым наружу, — минимальный, какой признаёт разбор.
MARKED = (
    "# ОТДАЁТСЯ НАРУЖУ: пример\n"
    "name: step-пример\non:\n  workflow_call:\njobs:\n  x:\n    steps: []\n"
)
#: Тот же файл БЕЗ пометки: помеченность объявляет автор, а не имя файла.
PLAIN = "name: step-молчун\non:\n  workflow_call:\njobs:\n  x:\n    steps: []\n"


#: Заготовка свода: состав читается из `kit/`, а не списком (#995).
KIT = {"AGENTS.md": "# ядро\n", "CLAUDE.md": "# окно\n"}


def tree(tmp_path: Path, *, tagged: str = "v2.5.0", **runs: str) -> Path:
    """Дерево с прогонами и тегом выпуска — настоящим, а не подделанным.

    Тег читается разбором механизма версии, и тот спрашивает ЖИВОЙ git: на
    подделке проверка подтверждала бы согласие кода с нашим представлением о
    тегах, а не с git (170).
    """
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    for name, body in runs.items():
        (tmp_path / ".github" / "workflows" / f"{name}.yml").write_text(body, encoding="utf-8")
    (tmp_path / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    (tmp_path / "kit").mkdir()
    for name, text in KIT.items():
        (tmp_path / "kit" / name).write_text(text, encoding="utf-8")
    run = ["git", "-C", str(tmp_path)]
    subprocess.run([*run, "init", "--quiet", "-b", "main"], check=True)
    subprocess.run([*run, "config", "user.email", "т@т"], check=True)
    subprocess.run([*run, "config", "user.name", "т"], check=True)
    subprocess.run([*run, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*run, "commit", "--quiet", "-m", "дерево"], check=True)
    if tagged:
        subprocess.run([*run, "tag", tagged], check=True)
    return tmp_path


def test_the_steps_come_from_the_marks(tmp_path: Path) -> None:
    """Состав — помеченные шаги, и только они."""
    root = tree(tmp_path, **{"step-пример": MARKED, "step-молчун": PLAIN})
    assert module.steps(root) == ["пример"]


def test_a_marked_tool_that_is_not_a_step_is_not_called(tmp_path: Path) -> None:
    """Помечен бывает и не шаг — пакет, действие. Заготовку вызова он не даёт.

    Вторая половина: без неё заход сочинил бы `uses:` на файл, который звать
    нечем, и потребитель узнал бы об этом отказом у себя (045).
    """
    root = tree(tmp_path, **{"step-пример": MARKED})
    (root / "scripts" / "раздача.py").write_text('"""ОТДАЁТСЯ НАРУЖУ: не шаг."""\n', "utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    assert module.steps(root) == ["пример"]


def test_the_pin_is_the_release_tag_not_the_contract_version(tmp_path: Path) -> None:
    """Прибивка — тег ВЫПУСКА, а не версия поверхности: они разные.

    В дереве теста `CONTRACT_VERSION` — подделка из общей константы, а выпуск
    помечен `v2.5.0`.
    Прибивка к первому указала бы на тег, которого нет, и вызов отказал бы у
    потребителя — там, где чинить его некому.
    """
    root = tree(tmp_path, tagged="v2.5.0", **{"step-пример": MARKED})
    assert module.pin_of(root) == "v2.5.0"
    assert FAKE_VERSION not in module.pin_of(root)


def test_without_a_release_the_kit_refuses(tmp_path: Path) -> None:
    """Выпусков нет — прибиваться не к чему, и это отказ, а не подвижная метка.

    Метка меняла бы у потребителя исполняемый код без его ведома (152), а
    молчаливая подстановка `@main` сделала бы это незаметно.
    """
    root = tree(tmp_path, tagged="", **{"step-пример": MARKED})
    with pytest.raises(module.NotRun, match=module.NO_RELEASE):
        module.pin_of(root)


def test_the_check_name_is_composed(tmp_path: Path) -> None:
    """Имя записи составное — то, которое выдаст площадка."""
    assert module.check_name("lint") == f"lint{policy.COMPOSED}lint"


def test_the_answer_leaves_the_class_to_the_consumer(tmp_path: Path) -> None:
    """Класс проверки заход не решает: это свойство потребителя (174).

    И не молчит о нём: `unreviewed` — объявленная очередь разбора. Молча
    обязательной проверка не становится, и молча совещательной тоже.
    """
    said = module.answer(["lint", "debt"])
    assert f'"lint{policy.COMPOSED}lint": {policy.UNREVIEWED}' in said
    assert policy.REQUIRED not in said and policy.ADVISORY not in said


def test_the_caller_pins_and_never_floats(tmp_path: Path) -> None:
    """Заготовка вызова несёт версию, а не подвижную метку."""
    said = module.caller("lint", "o/r", "v2.5.0")
    assert "@v2.5.0" in said
    assert "@main" not in said and "@latest" not in said


def test_nothing_shipped_is_its_own_outcome(tmp_path: Path, run_script: RunScript) -> None:
    """Не помечено ничего — «отдавать нечего», а не пустая заготовка (075).

    Пустая заготовка читалась бы как «подключили и ничего не пришло»: снаружи
    она неотличима от успеха.
    """
    root = tree(tmp_path, **{"step-молчун": PLAIN})
    (root / "README.md").write_text("# П\n\n## брать пока нечего\n", encoding="utf-8")
    assert module.main(["--root", str(root)]) == module.EXIT_NOTHING


def test_a_tree_without_runs_does_not_run(tmp_path: Path) -> None:
    """Каталогов поиска нет — заход не отработал, а не «нечего отдавать»."""
    assert module.main(["--root", str(tmp_path)]) == module.EXIT_BROKEN


#: Помеченный шаг, у которого в дереве есть СВОЙ вызывающий прогон.
MANAGED = (
    "# ОТДАЁТСЯ НАРУЖУ: пример\n"
    "name: step-план\non:\n  workflow_call:\njobs:\n  план:\n    steps: []\n"
)
#: Его вызывающий: свои события, внутренний путь к шагу.
OWN_CALLER = (
    "name: план\non:\n  workflow_dispatch:\n"
    "jobs:\n  план:\n    uses: ./.github/workflows/step-план.yml\n"
)
#: `ci.yml`, который зовёт шаг конвейера, — его вызывающим он не считается.
CI_CALLER = (
    "name: ci\non: [push]\njobs:\n  пример:\n    uses: ./.github/workflows/step-пример.yml\n"
)


def test_a_step_with_its_own_caller_is_printed_as_that_caller(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Управляющий механизм — своим прогоном с адресом по тегу, а не джобом `ci.yml` (#993).

    Джобом в `ci.yml` план шёл бы на каждом изменении и без права записи в
    задачу. Вторая половина: шаг, который зовёт `ci.yml`, остаётся джобом.
    """
    root = tree(
        tmp_path,
        **{"step-пример": MARKED, "step-план": MANAGED, "план": OWN_CALLER, "ci": CI_CALLER},
    )
    assert module.own_callers(root, module.steps(root)) == {
        "план": root / ".github" / "workflows" / "план.yml"
    }
    kit = module.own_kit(root / ".github" / "workflows" / "план.yml", "план", "О/Р", "v2.5.0")
    assert "uses: О/Р/.github/workflows/step-план.yml@v2.5.0" in kit
    assert "workflow_dispatch" in kit, "свои события вызывающего потерялись"
    assert module.main(["--root", str(root), "--repo", "О/Р"]) == module.EXIT_OK
    out = capsys.readouterr().out
    assert "uses: О/Р/.github/workflows/step-план.yml@v2.5.0" in out
    assert "uses: ./.github/workflows/step-план.yml" not in out, "внутренний путь ушёл в заготовку"
    assert "  пример:\n    name: пример\n" in out, "шаг конвейера перестал быть джобом ci.yml"
    assert "  план:\n    name: план\n" not in out, "управляющий механизм напечатан джобом ci.yml"
    checks, _, beyond = out.partition(f"{policy.BEYOND}:")
    assert '"пример / пример"' in checks and '"план / план"' in beyond


def test_the_answer_of_a_mechanism_follows_its_flow_not_its_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Имя записи — по джобам прогона, раздел — по его событиям (#993).

    Обход застрявших зовётся `stuck-prs` при шаге `step-stuck.yml`, и имя из
    файла назвало бы запись, которой площадка не выдаст. Очередь идёт и на
    изменении: ответ по ней в `checks`, а не вне изменения.
    """
    step = MANAGED.replace("step-план", "step-обход").replace("  план:", "  обход-всех:")
    flow = (
        "name: обход\non:\n  pull_request:\n"
        "jobs:\n  обход-всех:\n    uses: ./.github/workflows/step-обход.yml\n"
    )
    root = tree(tmp_path, **{"step-обход": step, "обход": flow, "ci": CI_CALLER})
    assert module.own_records(root / ".github" / "workflows" / "обход.yml") == (
        ["обход-всех / обход-всех"],
        True,
    )
    assert module.main(["--root", str(root), "--repo", "О/Р"]) == module.EXIT_OK
    checks, _, beyond = capsys.readouterr().out.partition(f"{policy.BEYOND}:")
    assert '"обход-всех / обход-всех"' in checks, "запись механизма на изменении ушла не туда"
    assert '"обход / обход"' not in checks + beyond, "имя записи собрано из имени файла"


def test_a_step_called_by_ci_stays_a_pipeline_step(tmp_path: Path) -> None:
    """Шаг, которого зовёт `ci.yml`, — шаг конвейера, кто бы ещё его ни звал (взгляд на #1050)."""
    also = (
        "name: сосед\non:\n  workflow_dispatch:\n"
        "jobs:\n  пример:\n    uses: ./.github/workflows/step-пример.yml\n"
    )
    root = tree(tmp_path, **{"step-пример": MARKED, "ci": CI_CALLER, "сосед": also})
    assert module.own_callers(root, module.steps(root)) == {}, "шаг ci.yml ушёл из его джобов"


def test_two_own_callers_are_a_refusal(tmp_path: Path) -> None:
    """Два своих прогона у одного шага — неоднозначность, а не выбор первого."""
    second = OWN_CALLER.replace("name: план", "name: второй")
    root = tree(tmp_path, **{"step-план": MANAGED, "план": OWN_CALLER, "второй": second})
    with pytest.raises(module.NotRun, match="несколько своих прогонов"):
        module.own_callers(root, module.steps(root))


def test_a_call_the_kit_cannot_rewrite_is_a_refusal(tmp_path: Path) -> None:
    """Вызов в кавычках разбор признаёт, а подмена бы пропустила — отказ, а не внутренний путь."""
    quoted = OWN_CALLER.replace(
        "uses: ./.github/workflows/step-план.yml", 'uses: "./.github/workflows/step-план.yml"'
    )
    root = tree(tmp_path, **{"step-план": MANAGED, "план": quoted})
    flow = root / ".github" / "workflows" / "план.yml"
    assert module.own_callers(root, module.steps(root)) == {"план": flow}
    with pytest.raises(module.NotRun, match="не перепишет"):
        module.own_kit(flow, "план", "О/Р", "v2.5.0")


def test_an_unreadable_flow_does_not_turn_a_mechanism_into_a_job(tmp_path: Path) -> None:
    """Нечитаемый прогон — третий исход, а не «своего вызывающего нет» (045)."""
    root = tree(tmp_path, **{"step-план": MANAGED, "сломан": "jobs: [\n"})
    with pytest.raises(module.NotRun):
        module.own_callers(root, module.steps(root))


def tagged_before(tmp_path: Path, *, tag: str = "v2.5.0") -> Path:
    """Дерево, где тег нарезан РАНЬШЕ помеченного файла.

    Это и есть предмет: у нас файл лежит, по названной потребителю ссылке —
    нет. Дерево строится настоящим git, а не подделкой ответа: на подделке
    проверка подтверждала бы согласие кода с нашим представлением о тегах,
    а не с git (170).
    """
    root = tree(tmp_path, tagged=tag, **{"step-молчун": PLAIN})
    (root / ".github" / "workflows" / "step-пример.yml").write_text(MARKED, encoding="utf-8")
    run = ["git", "-C", str(root)]
    subprocess.run([*run, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*run, "commit", "--quiet", "-m", "шаг после выпуска"], check=True)
    return root


def test_a_pin_that_does_not_carry_the_step_is_refused(tmp_path: Path) -> None:
    """Прибивка есть, шага в ней нет — отказ, а не заготовка (045).

    Напечатанную заготовку забирают целиком, и вызов по тегу, которого этот
    файл не несёт, отказал бы У ПОТРЕБИТЕЛЯ: чинить его там некому.
    """
    root = tagged_before(tmp_path)
    assert module.main(["--root", str(root)]) == module.EXIT_UNREACHABLE


def test_a_pin_that_carries_the_step_prints_the_kit(tmp_path: Path) -> None:
    """Вторая половина: тег несёт помеченное — заготовка печатается.

    Без неё предикат был бы неотличим от «всегда отказывать», а такой учат
    обходить (051).
    """
    root = tree(tmp_path, tagged="v2.5.0", **{"step-пример": MARKED})
    assert module.main(["--root", str(root)]) == module.EXIT_OK


@needs_history
def test_the_kit_agrees_with_the_live_release(run_script: RunScript) -> None:
    """Живое дерево: исход захода СХОДИТСЯ с тем, что несёт живой выпуск (139).

    ЦВЕТ ЗДЕСЬ НЕ ЗАКРЕПЛЁН, И ЭТО НЕ ПОБЛАЖКА. «Выпуск отстаёт от дерева» —
    законное состояние проекта между слиянием и нарезкой тега, и требовать от
    набора зелёного именно в нём значило бы держать красное, которое снимает
    не правка, а выпуск (051). Проверяется другое и более сильное: заход
    говорит ровно то, что есть на самом деле, — обе ветки названы.

    ИДЁТ ПО ЖИВОЙ ИСТОРИИ и потому помечен: прибивка читается из тега ВЫПУСКА,
    а в мелком чекауте теги не приезжают. Без маркера прогон падал бы там, где
    предмета нет вовсе, — то есть красное говорило бы о глубине клона, а не о
    дереве (045). Нашёл внешний взгляд (`f02d34e`).
    """
    shipped = load_script("check_shipped.py")
    behind = shipped.unreleased(module.pin_of(ROOT), ROOT)
    done = run_script("onboard.py")
    if behind:
        assert done.code == module.EXIT_UNREACHABLE, done.err or done.out
        for one in behind:
            assert one in done.err, f"отказ не назвал «{one}» поимённо (046)"
        return
    assert done.code == module.EXIT_OK, done.err or done.out
    assert "uses:" in done.out and "checks:" in done.out
    for name in module.steps(ROOT):
        assert f"step-{name}.yml@" in done.out, f"шаг «{name}» в заготовку не попал"


# --- заход кладёт заготовку сам (#992, вариант 3) ----------------------------


def test_write_lays_a_thin_ci_and_the_answer(tmp_path: Path) -> None:
    """С `--write` заход кладёт тонкий `ci.yml` и заготовку `.pipeline.yml` (#992).

    `ci.yml` — только вызовы шагов по тегу; класс каждой проверки — в
    `.pipeline.yml`, и он «в очереди разбора»: решает потребитель (174).
    """
    import yaml

    root = tree(tmp_path / "наше", tagged="v2.5.0", **{"step-пример": MARKED})
    consumer = tmp_path / "потребитель"
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OK
    flow = yaml.safe_load((consumer / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    job = flow["jobs"]["пример"]
    assert job["uses"].endswith("/.github/workflows/step-пример.yml@v2.5.0"), job
    said = yaml.safe_load((consumer / ".pipeline.yml").read_text("utf-8"))
    assert said["checks"] == {module.check_name("пример"): policy.UNREVIEWED}


def test_write_never_overwrites_what_is_there(tmp_path: Path) -> None:
    """Занятый путь — отказ, и не кладётся ни один файл: половина заготовки хуже никакой."""
    root = tree(tmp_path / "наше", tagged="v2.5.0", **{"step-пример": MARKED})
    consumer = tmp_path / "потребитель"
    (consumer / ".github" / "workflows").mkdir(parents=True)
    (consumer / ".pipeline.yml").write_text("свой ответ\n", encoding="utf-8")
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OCCUPIED
    assert (consumer / ".pipeline.yml").read_text("utf-8") == "свой ответ\n"
    assert not (consumer / ".github" / "workflows" / "ci.yml").exists()


def test_the_thin_ci_carries_only_calls(tmp_path: Path) -> None:
    """В тонком `ci.yml` нет своих шагов: каждый джоб — вызов по тегу."""
    import yaml

    flow = yaml.safe_load(module.thin_ci(["а", "б"], "o/r", "v1.0.0"))
    assert set(flow["jobs"]) == {"а", "б"}
    assert all("steps" not in job and "@v1.0.0" in job["uses"] for job in flow["jobs"].values())


def test_occupied_names_only_what_exists(tmp_path: Path) -> None:
    """`occupied` называет занятые пути, `lay` кладёт все."""
    files = {Path("a/x.yml"): "x\n", Path("y.yml"): "y\n"}
    (tmp_path / "y.yml").write_text("было\n", encoding="utf-8")
    assert module.occupied(tmp_path, files) == [Path("y.yml")]
    module.lay(tmp_path / "новое", files)
    assert (tmp_path / "новое" / "a" / "x.yml").read_text("utf-8") == "x\n"


def test_the_thin_ci_runs_on_the_trunk_and_keeps_the_last_word_by_head() -> None:
    """`push` на общую ветку и голова в группе очереди — как у нашего `ci.yml` (#1114).

    Без `push` заготовка дежурного (`main-red.yml`) не получила бы сигнала
    ни разу; без головы в группе последнее слово досталось бы устаревшему
    коммиту (179).
    """
    import yaml

    flow = yaml.safe_load(module.thin_ci(["а"], "o/r", "v1.0.0"))
    events = flow[True] if True in flow else flow["on"]
    assert events["push"] == {"branches": [module.paths.TRUNK]}
    ours = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    assert flow["concurrency"] == ours["concurrency"], "очередь разошлась с нашим ci.yml"


def test_no_pipeline_steps_is_a_refusal_not_an_empty_flow() -> None:
    """Все шаги управляющие — тонкий `ci.yml` был бы без джобов: отказ (#1114)."""
    with pytest.raises(module.NotRun, match="без джобов"):
        module.thin_ci([], "o/r", "v1.0.0")


def test_write_lays_the_own_flows_and_names_the_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--write` кладёт и прогоны управляющих механизмов, а сводный гейт называет (#1114)."""
    root = tree(
        tmp_path / "наше",
        **{"step-пример": MARKED, "step-план": MANAGED, "план": OWN_CALLER, "ci": CI_CALLER},
    )
    consumer = tmp_path / "потребитель"
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OK
    kit = (consumer / ".github" / "workflows" / "план.yml").read_text("utf-8")
    assert "step-план.yml@v2.5.0" in kit
    assert module.SUMMARY_FLOW in capsys.readouterr().out


def test_write_refuses_a_kit_it_cannot_rewrite_and_lays_nothing(tmp_path: Path) -> None:
    """Вызов, который заготовка не перепишет, — отказ, и не кладётся ни один файл (#1114)."""
    quoted = OWN_CALLER.replace(
        "uses: ./.github/workflows/step-план.yml", 'uses: "./.github/workflows/step-план.yml"'
    )
    root = tree(
        tmp_path / "наше",
        **{"step-пример": MARKED, "step-план": MANAGED, "план": quoted, "ci": CI_CALLER},
    )
    consumer = tmp_path / "потребитель"
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_BROKEN
    assert not consumer.exists() or not any(consumer.rglob("*.yml"))


@pytest.mark.parametrize(
    ("said", "name"),
    [
        ("./.github/workflows/step-план.yml", "план"),
        ("О/Р/.github/workflows/step-план.yml@main", "план"),
        ("О/Р/.github/workflows/step-план.yml@v2.5.0", ""),
        ("./.github/workflows/план.yml", ""),
        ("actions/checkout@v7", ""),
    ],
    ids=["внутренний путь", "адрес с общей веткой", "адрес с тегом", "не шаг", "действие"],
)
def test_a_step_is_called_by_its_path_or_by_the_trunk_address(said: str, name: str) -> None:
    """Свой шаг узнаётся и по адресу с общей веткой, а по тегу — нет (#993).

    Адрес с общей веткой — свой вызов взгляда, прибитый к ней, чтобы карта не
    исполняла код головы; адрес с тегом — вызов выпуска, как у пробы передачи.
    """
    assert module.step_called(said) == name


def test_a_caller_by_the_trunk_address_is_printed_with_the_tag(tmp_path: Path) -> None:
    """Вызывающий по адресу с общей веткой уходит в заготовку адресом по тегу (#993)."""
    by_address = OWN_CALLER.replace(
        "uses: ./.github/workflows/step-план.yml", "uses: О/Р/.github/workflows/step-план.yml@main"
    )
    root = tree(tmp_path, **{"step-план": MANAGED, "план": by_address})
    flow = root / ".github" / "workflows" / "план.yml"
    assert module.own_callers(root, module.steps(root)) == {"план": flow}
    kit = module.own_kit(flow, "план", "О/Р", "v2.5.0")
    assert "uses: О/Р/.github/workflows/step-план.yml@v2.5.0" in kit
    assert "@main" not in kit, "адрес общей ветки ушёл в заготовку"


# --- вызывающий со своими джобами (#1001, шаг 2) ------------------------------

#: Вызывающий, у которого перед вызовом шага свой джоб на наших скриптах.
MIXED_CALLER = (
    "name: план\non:\n  workflow_dispatch:\npermissions:\n  contents: write\n"
    "jobs:\n"
    "  своё:\n    runs-on: x\n    steps:\n      - run: python scripts/наше.py\n"
    "  план:\n    needs: своё\n    uses: ./.github/workflows/step-план.yml\n"
    "    with:\n      вход: данные\n"
)


def test_a_caller_with_its_own_jobs_ships_only_the_call(tmp_path: Path) -> None:
    """Свои джобы вызывающего в заготовку не едут; вызов — по тегу, без `needs` на снятое.

    Наш `badges.yml` перед общим шагом фактов собирает свои разделы нашими
    скриптами: целиком напечатанный, он вёл бы потребителя в пустоту.
    """
    import yaml

    root = tree(tmp_path, **{"step-пример": MARKED, "step-план": MANAGED, "план": MIXED_CALLER})
    flow = root / ".github" / "workflows" / "план.yml"
    kit = module.own_kit(flow, "план", "О/Р", "v2.5.0")
    said = yaml.safe_load(kit)
    assert list(said["jobs"]) == ["план"], kit
    job = said["jobs"]["план"]
    assert job["uses"] == "О/Р/.github/workflows/step-план.yml@v2.5.0"
    assert "needs" not in job and job["with"] == {"вход": "данные"}
    assert said["permissions"] == {"contents": "write"}
    assert "scripts/наше.py" not in kit


def test_the_answer_of_a_mixed_caller_names_only_the_call(tmp_path: Path) -> None:
    """Ответ по проверкам — только о джобе вызова: о своём джобе поставщика у потребителя нечего."""
    root = tree(tmp_path, **{"step-план": MANAGED, "план": MIXED_CALLER})
    flow = root / ".github" / "workflows" / "план.yml"
    names, _ = module.own_records(flow, "план")
    assert names == ["план / план"]
    every, _ = module.own_records(flow)
    assert "своё" in every, "без имени шага ответ сужаться не должен"


def test_calling_part_keeps_the_events_and_the_call() -> None:
    """Часть вызова несёт события и права вызывающего — и только джобы вызова."""
    document = {
        "name": "значки",
        True: {"push": {"branches": ["main"]}},
        "permissions": {"contents": "write"},
        "jobs": {
            "своё": {"runs-on": "x", "steps": []},
            "план": {"needs": "своё", "uses": "./.github/workflows/step-план.yml"},
        },
    }
    import yaml

    kit = module.calling_part("значки.yml", document, "план", "uses: О/Р/x.yml@v1")
    said = yaml.safe_load(kit)
    # Ключ событий пишется строкой в кавычках: голое `on` YAML 1.1 читает как «истину».
    assert said["on"] == {"push": {"branches": ["main"]}}
    assert said["jobs"] == {"план": {"uses": "О/Р/x.yml@v1"}}


def test_a_dropped_need_hands_its_guard_to_the_call() -> None:
    """Условие снятого джоба переходит на вызов — транзитивно; своё условие вызова стоит первым.

    Взгляд на #1183: у нас фильтр будящих событий стоит на `inputs`, и без
    переноса `facts` с правом записи у потребителя шёл бы на любое `ci`.
    """
    jobs = {
        "дальний": {"if": "в"},
        "ближний": {"needs": "дальний", "if": "б"},
        "вызов": {"needs": ["ближний"], "if": "а", "uses": "./x.yml"},
        "свой": {"if": "г"},
    }
    gone = {"дальний", "ближний", "свой"}
    assert module.inherited_guard(jobs, "вызов", gone) == "(а) && (б) && (в)"
    assert module.inherited_guard({"вызов": {"uses": "x"}}, "вызов", set()) == ""
    assert (
        module.inherited_guard({"н": {"if": "б"}, "вызов": {"needs": "н"}}, "вызов", {"н"}) == "б"
    )


def test_needs_are_read_in_both_forms() -> None:
    """`needs` строкой и списком читаются одинаково; без `needs` — пусто."""
    jobs = {"а": {"needs": "б"}, "в": {"needs": ["б", "г"]}, "д": {}}
    assert module.needed_by(jobs, "а") == ["б"]
    assert module.needed_by(jobs, "в") == ["б", "г"]
    assert module.needed_by(jobs, "д") == []


def test_an_input_naming_a_dropped_artifact_does_not_ship() -> None:
    """Вход, называющий артефакт снятого джоба, не едет; прочие входы — данные — едут."""
    import yaml

    document = {
        "name": "значки",
        True: {"push": None},
        "jobs": {
            "inputs": {
                "if": "фильтр",
                "steps": [{"uses": "actions/upload-artifact@x", "with": {"name": "сырьё"}}],
            },
            "facts": {
                "needs": "inputs",
                "uses": "./.github/workflows/step-план.yml",
                "with": {"inputs-artifact": "сырьё", "ci-workflow": "ci.yml"},
            },
        },
    }
    said = yaml.safe_load(module.calling_part("значки.yml", document, "план", "uses: О/Р/x.yml@v1"))
    job = said["jobs"]["facts"]
    assert job["with"] == {"ci-workflow": "ci.yml"}
    assert job["if"] == "фильтр"
    assert module.artifacts_of(document["jobs"], {"inputs"}) == {"сырьё"}
    assert module.artifacts_of(document["jobs"], set()) == set()


@pytest.mark.parametrize(
    ("jobs", "said"),
    [
        ({"н": {"if": "${{ б }}"}, "в": {"needs": "н", "if": "${{ а }}"}}, "(а) && (б)"),
        ({"н": {"if": "б"}, "в": {"needs": "н", "if": "always()"}}, None),
        ({"н": {"if": "needs.д.result == 'success'"}, "в": {"needs": "н"}}, None),
        ({"н": {}, "в": {"needs": "н", "if": "failure()"}}, None),
        ({"в": {"if": "always()"}}, "always()"),
        ({"н": {"if": "failure()"}, "в": {"needs": "н"}}, None),
    ],
    ids=[
        "обёртка снимается до склейки",
        "статусная функция вызова — отказ",
        "условие снятого ссылается на needs — отказ",
        "статусная функция при снятом needs без переноса — отказ",
        "статусная функция без снятого needs — как есть",
        "статусная функция в перенесённом — отказ",
    ],
)
def test_the_guard_forms_are_carried_or_refused(jobs: dict[str, Any], said: str | None) -> None:
    """Перечень форм переноса условия: что переносится, а что честно не переносится (#1189)."""
    if said is None:
        with pytest.raises(module.NotRun):
            module.inherited_guard(jobs, "в", {"н"})
    else:
        assert module.inherited_guard(jobs, "в", {"н"}) == said


@pytest.mark.parametrize(
    "field",
    [
        {"if": "needs.inputs.outputs.go == 'true'"},
        {"secrets": {"K": "${{ needs.inputs.outputs.k }}"}},
        {"strategy": {"matrix": {"x": "${{ fromJSON(needs.inputs.outputs.list) }}"}}},
        {"concurrency": "g-${{ needs.inputs.outputs.id }}"},
    ],
    ids=["своё условие", "секреты", "матрица", "очередь"],
)
def test_any_needs_left_on_the_call_is_refused(field: dict[str, Any]) -> None:
    """Ссылка на СНЯТЫЙ джоб на вызове — отказ, где бы она ни стояла (#1189, #1195)."""
    document = {
        "name": "значки",
        True: {"push": None},
        "jobs": {
            "inputs": {"steps": []},
            "facts": {"needs": "inputs", "uses": "./.github/workflows/step-план.yml", **field},
        },
    }
    with pytest.raises(module.NotRun):
        module.calling_part("значки.yml", document, "план", "uses: О/Р/x.yml@v1")


def test_a_need_on_another_call_stays_and_may_be_read() -> None:
    """`needs` на другой джоб вызова не снимается: порядок двух вызовов держится (#1195)."""
    import yaml

    step = "./.github/workflows/step-план.yml"
    document = {
        "name": "значки",
        True: {"push": None},
        "jobs": {
            "inputs": {"steps": []},
            "первый": {"needs": "inputs", "uses": step},
            "второй": {
                "needs": ["inputs", "первый"],
                "uses": step,
                "if": "needs.первый.result == 'success'",
            },
        },
    }
    jobs = yaml.safe_load(
        module.calling_part("значки.yml", document, "план", "uses: О/Р/x.yml@v1")
    )["jobs"]
    assert "needs" not in jobs["первый"]
    assert jobs["второй"]["needs"] == "первый"
    assert jobs["второй"]["if"] == "needs.первый.result == 'success'"


def test_expressions_are_found_at_any_depth_and_only_inside_the_wrapper() -> None:
    """`expressions` отдаёт содержимое каждого `${{ }}` в строках, списках и словарях (#1195)."""
    value = {"a": ["x ${{ needs.н.outputs.p }} y", {"b": "${{ github.sha }}"}], "c": "needs.н"}
    assert module.expressions(value) == [" needs.н.outputs.p ", " github.sha "]
    assert module.expressions("needs.н") == []


def test_order_through_a_dropped_middle_job_is_kept() -> None:
    """Вызов стоит на снятом посреднике, тот — на другом вызове: порядок сохраняется (#1195)."""
    import yaml

    step = "./.github/workflows/step-план.yml"
    document = {
        "name": "значки",
        True: {"push": None},
        "jobs": {
            "первый": {"uses": step},
            "посредник": {"needs": "первый", "steps": []},
            "второй": {"needs": "посредник", "uses": step},
        },
    }
    jobs = yaml.safe_load(
        module.calling_part("значки.yml", document, "план", "uses: О/Р/x.yml@v1")
    )["jobs"]
    assert jobs["второй"]["needs"] == "первый"
    assert module.kept_needs(document["jobs"], "второй", {"посредник"}) == ["первый"]


def test_a_literal_needs_word_outside_an_expression_is_not_a_reference() -> None:
    """Слово `needs.` вне `${{ }}` во входе или секрете — литерал, а не ссылка (#1195)."""
    import yaml

    document = {
        "name": "значки",
        True: {"push": None},
        "jobs": {
            "inputs": {"steps": []},
            "facts": {
                "needs": "inputs",
                "uses": "./.github/workflows/step-план.yml",
                "with": {"путь": "docs/needs.inputs.md"},
                "secrets": {"K": "needs.inputs"},
            },
        },
    }
    job = yaml.safe_load(module.calling_part("значки.yml", document, "план", "uses: О/Р/x.yml@v1"))[
        "jobs"
    ]["facts"]
    assert job["with"] == {"путь": "docs/needs.inputs.md"}
    assert job["secrets"] == {"K": "needs.inputs"}


def test_an_input_leaning_on_a_dropped_job_does_not_ship_and_is_named() -> None:
    """Вход с выходом снятого джоба не едет и назван в шапке; вход без `needs` — едет."""
    import yaml

    document = {
        "name": "значки",
        True: {"push": None},
        "jobs": {
            "inputs": {"steps": []},
            "facts": {
                "needs": "inputs",
                "uses": "./.github/workflows/step-план.yml",
                "with": {
                    "сырьё": "${{ needs.inputs.outputs.path }}",
                    "соседнее": "${{ github.ref_name }}",
                },
            },
        },
    }
    kit = module.calling_part("значки.yml", document, "план", "uses: О/Р/x.yml@v1")
    head = kit.split("\nname:", 1)[0]
    assert "facts.сырьё" in head and "соседнее" not in head, head
    job = yaml.safe_load(kit)["jobs"]["facts"]
    assert job["with"] == {"соседнее": "${{ github.ref_name }}"}


def test_the_real_facts_caller_ships_its_filter_and_not_its_artifact() -> None:
    """Наш `badges.yml`: в заготовке у `facts` фильтр будящих событий есть, артефакта нет (107)."""
    import yaml

    flow = ROOT / ".github" / "workflows" / "badges.yml"
    said = yaml.safe_load(module.own_kit(flow, "facts", "О/Р", "v9.9.9"))
    job = said["jobs"]["facts"]
    assert "workflow_run.event" in job["if"], job
    assert "inputs-artifact" not in (job.get("with") or {}), job


def test_a_condition_and_a_lean_are_read_as_expressions() -> None:
    """Обёртка снимается только целая; ссылка на снятый джоб — по имени целиком."""
    assert module.bare_condition("${{ а == б }}") == "а == б"
    assert module.bare_condition("  а == б ") == "а == б"
    assert module.bare_condition("${{ а }} && б") == "${{ а }} && б"
    assert module.leans_on("${{ needs.inputs.outputs.x }}", {"inputs"})
    assert not module.leans_on("${{ needs.inputs2.outputs.x }}", {"inputs"})
    assert not module.leans_on("ci.yml", {"inputs"})


# --- заготовка свода окна (#995, пункт 1) ------------------------------------


def test_write_lays_the_rulebook_kit(tmp_path: Path) -> None:
    """`--write` кладёт `kit/<имя>` под `<имя>`: окну потребителя есть по чему работать."""
    root = tree(tmp_path / "наше", **{"step-пример": MARKED})
    consumer = tmp_path / "потребитель"
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OK
    for name, text in KIT.items():
        assert (consumer / name).read_text("utf-8") == text


def test_an_existing_rulebook_is_kept_and_does_not_stop_the_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Свод — наполнение владельца: занятый не пишется и называется, а вызов кладётся."""
    root = tree(tmp_path / "наше", **{"step-пример": MARKED})
    consumer = tmp_path / "потребитель"
    consumer.mkdir()
    (consumer / "CLAUDE.md").write_text("свой свод\n", encoding="utf-8")
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OK
    assert (consumer / "CLAUDE.md").read_text("utf-8") == "свой свод\n"
    assert (consumer / "AGENTS.md").read_text("utf-8") == KIT["AGENTS.md"]
    assert (consumer / ".github" / "workflows" / "ci.yml").exists()
    assert "CLAUDE.md" in capsys.readouterr().out


def test_the_printed_kit_carries_the_rulebook(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Без `--write` заготовка свода печатается целиком, с именем, под которым она ложится."""
    root = tree(tmp_path, **{"step-пример": MARKED})
    assert module.main(["--root", str(root)]) == module.EXIT_OK
    out = capsys.readouterr().out
    for name, text in KIT.items():
        assert f"`{name}`" in out and text in out


def test_no_rulebook_kit_is_a_refusal(tmp_path: Path) -> None:
    """Пустой `kit/` — отказ: подключение без свода заход назвал бы полным (045)."""
    root = tree(tmp_path, **{"step-пример": MARKED})
    for one in (root / "kit").iterdir():
        one.unlink()
    assert module.main(["--root", str(root)]) == module.EXIT_BROKEN


def test_the_live_kit_is_what_onboard_lays() -> None:
    """Живое дерево: заход кладёт ровно файлы свода, у которых есть заготовка."""
    rulebook = load_script("check_rulebook_fresh.py").RULEBOOK
    assert sorted(str(one) for one in module.rulebook_kit(ROOT)) == sorted(rulebook)


# --- данные потребителя (#996) -----------------------------------------------


def test_the_consumer_data_follows_imports_and_skips_what_is_laid() -> None:
    """Перечень данных выводится из дерева: через импорт и без того, что кладёт заготовка.

    `.github/labels.yml` читает не `agent_pr`, которого зовёт шаг, а импортированный
    им `labels`: без обхода импорта перечень терял бы его молча. Крюк окна
    `.claude/hooks/floor.sh` настраивается потребителем, но шаги его не зовут.
    """
    paths = load_script("paths.py")
    names = module.steps(ROOT)
    data = module.consumer_data(ROOT, names, {paths.PIPELINE})
    assert data is not None
    assert ".github/labels.yml" in data, data
    assert ".claude/hooks/floor.sh" not in data, data
    assert not [one for one in data if one.startswith(("scripts/", ".github/workflows/"))], data
    laid = module.consumer_data(ROOT, names, {paths.PIPELINE, Path(".github/labels.yml")})
    assert laid is not None and ".github/labels.yml" not in laid


def test_without_an_inventory_the_list_is_not_derived(tmp_path: Path) -> None:
    """Инвентаря нет — перечень не выведен (`None`), а не пуст: пустой значил бы «не нужно»."""
    assert module.consumer_data(tmp_path, [], set()) is None


@pytest.mark.parametrize("text", ["{не json", "{}", '{"answers": []}'])
def test_a_broken_inventory_is_a_refusal_not_a_traceback(tmp_path: Path, text: str) -> None:
    """Битый инвентарь — отказ захода (`NotRun`), а не трейсбек после положенного (#996)."""
    (tmp_path / ".rules").mkdir()
    (tmp_path / ".rules" / "portable.json").write_text(text, encoding="utf-8")
    with pytest.raises(module.NotRun):
        module.consumer_data(tmp_path, [], set())


@pytest.mark.parametrize(
    "answers",
    [
        {".github/workflows/step-план.yml": "configured"},
        {".github/workflows/step-план.yml": {"answer": "configured", "where": ".github/a.txt"}},
    ],
    ids=["ответ не словарь", "where строкой"],
)
def test_an_answer_of_a_wrong_shape_is_a_refusal(tmp_path: Path, answers: dict[str, Any]) -> None:
    """Ответ инвентаря не той формы — отказ, а не трейсбек и не перечень по буквам (#1196)."""
    (tmp_path / ".rules").mkdir()
    (tmp_path / ".rules" / "portable.json").write_text(
        json.dumps({"answers": answers}), encoding="utf-8"
    )
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "step-план.yml").write_text(
        "jobs: {}\n", encoding="utf-8"
    )
    with pytest.raises(module.NotRun):
        module.consumer_data(tmp_path, ["план"], set())


def test_a_step_answer_brings_its_own_data(tmp_path: Path) -> None:
    """Данные, которые шаг читает мимо скриптов, приходят из ответа самого шага (#1196)."""
    (tmp_path / ".rules").mkdir()
    answers = {
        ".github/workflows/step-план.yml": {"answer": "configured", "where": [".github/a.txt"]}
    }
    (tmp_path / ".rules" / "portable.json").write_text(
        json.dumps({"answers": answers}), encoding="utf-8"
    )
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "step-план.yml").write_text(
        "jobs: {}\n", encoding="utf-8"
    )
    assert module.consumer_data(tmp_path, ["план"], set()) == [".github/a.txt"]


def test_step_texts_count_run_and_inputs_but_not_comments(tmp_path: Path) -> None:
    """Вызов — `run:` и вход действия (агент зовёт по разрешениям); комментарий — нет (#1201)."""
    flow = tmp_path / "step.yml"
    flow.write_text(
        "# коммент: $MECHANISMS/scripts/коммент.py\n"
        "jobs:\n  j:\n    steps:\n      - uses: a/b@v1\n        with:\n"
        "          allowed: Bash(python ${{ env.MECHANISMS }}/scripts/агент.py)\n"
        "      - run: python $MECHANISMS/scripts/вызов.py\n",
        encoding="utf-8",
    )
    found = sorted(
        m.group(1) for line in module.step_texts(flow) for m in module.CALLED_SCRIPT.finditer(line)
    )
    assert found == ["агент", "вызов"]


def test_called_scripts_walk_our_imports_only(tmp_path: Path) -> None:
    """Обход идёт по нашему `scripts/` транзитивно; чужой модуль и стандартная библиотека — нет."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "step-план.yml").write_text(
        "jobs:\n  j:\n    steps:\n      - run: python $MECHANISMS/scripts/верх.py\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "верх.py").write_text("import os\nimport низ\n", encoding="utf-8")
    (tmp_path / "scripts" / "низ.py").write_text("from yaml import safe_load\n", encoding="utf-8")
    assert module.called_scripts(tmp_path, ["план"]) == {"верх", "низ"}
