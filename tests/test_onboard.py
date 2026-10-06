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

import subprocess
from pathlib import Path

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
