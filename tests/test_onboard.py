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
import yaml

from tests.conftest import (
    FAKE_VERSION,
    ROOT,
    RunScript,
    load_script,
    needs_history,
    walk_deep,
)

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
#: Заготовки данных: состав читается из `kit/data/`, а не списком (#1386).
#: Заготовки данных поддельного дерева — каждая своего рода: JSON-заготовку
#: заход разбирает, чтобы поставить в неё поле лицензии (#1470).
DATA = {
    str(one): (
        json.dumps({"_": f"заготовка {one.name}"}, ensure_ascii=False) + "\n"
        if one.suffix == ".json"
        else f"заготовка {one.name}\n"
    )
    for one in module.DATA_KITTED
}
#: Наша таблица областей: из неё заготовка берёт имена областей.
AREAS = '{"areas": {"gates": {"paths": ["tests/*"]}, "docs": {"paths": ["docs/*"]}}}\n'


#: Наш сводный гейт в поддельном дереве: джоб зовёт действие внутренним путём.
SUMMARY = (
    f"jobs:\n  ci-complete:\n    name: ci-complete\n    steps:\n      - {module.SUMMARY_CALL}\n"
)


def tree(tmp_path: Path, *, tagged: str = "v2.5.0", **runs: str) -> Path:
    """Дерево с прогонами и тегом выпуска — настоящим, а не подделанным.

    Тег читается разбором механизма версии, и тот спрашивает ЖИВОЙ git: на
    подделке проверка подтверждала бы согласие кода с нашим представлением о
    тегах, а не с git (170).
    """
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    # Сводный гейт лежит в каждом дереве поставщика (#1385): заготовка кладёт
    # его тонким прогоном и без него не собирается.
    runs.setdefault(Path(module.SUMMARY_FLOW).stem, SUMMARY)
    for name, body in runs.items():
        (tmp_path / ".github" / "workflows" / f"{name}.yml").write_text(body, encoding="utf-8")
    (tmp_path / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    (tmp_path / "kit").mkdir()
    for name, text in KIT.items():
        (tmp_path / "kit" / name).write_text(text, encoding="utf-8")
    for name, text in DATA.items():
        (tmp_path / module.DATA_KIT / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / module.DATA_KIT / name).write_text(text, encoding="utf-8")
    (tmp_path / ".rules").mkdir(exist_ok=True)
    (tmp_path / ".rules" / "area-paths.json").write_text(AREAS, encoding="utf-8")
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
    said = module.answer(["lint", "debt"], span=">=9.9,<9.10")
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


def test_a_yaml_run_is_read_as_a_run(tmp_path: Path) -> None:
    """Свой прогон под `.yaml` — тот же прогон, а `ci.yaml` — тот же `ci.yml` (`e8e7fb3`).

    Обе половины: вызывающий под `.yaml` найден, а `ci.yaml`, зовущий шаг
    конвейера, вызывающим не считается — как и `ci.yml`.
    """
    root = tree(tmp_path, **{"step-план": MANAGED, "step-пример": MARKED})
    flows = root / ".github" / "workflows"
    (flows / "план.yaml").write_text(OWN_CALLER, encoding="utf-8")
    (flows / "ci.yaml").write_text(CI_CALLER, encoding="utf-8")
    assert module.own_callers(root, module.steps(root)) == {"план": flows / "план.yaml"}


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


def test_the_laid_answer_is_read_by_the_mechanism(tmp_path: Path) -> None:
    """Положенный ответ читает разбор механизма: схема и окно контракта на месте.

    Найдено замером на клоне `Claude-Code_Usage-Token` (#1388): заготовка
    клала только проверки, и `pipeline_checks.load` отказывал ей схемой, а
    `span_of` — окном. Потребитель краснел бы шагом `pipeline` с первого же
    прогона после подключения.
    """
    root = tree(tmp_path / "наше", tagged="v2.5.0", **{"step-пример": MARKED})
    consumer = tmp_path / "потребитель"
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OK
    said = consumer / module.paths.PIPELINE
    policy.load(said)
    assert policy.compatible(policy.span(said), FAKE_VERSION)


@pytest.mark.parametrize(
    ("contract", "span", "inside", "outside"),
    # Двузначный минор взят далёким от живого контракта: литерал, совпавший с ним,
    # гейт версии принимает за вписанный рукой (#1514, выпуск v1.8.0).
    [("9.9.0", ">=9.9,<9.10", "9.9.4", "9.10.0"), ("0.42.2", ">=0.42,<0.43", "0.42.0", "1.0.0")],
    ids=["минор", "двузначный-минор"],
)
def test_the_answer_window_is_the_minor_of_the_release(
    contract: str, span: str, inside: str, outside: str
) -> None:
    """Окно заготовки — минор выпуска: патч внутри, следующий минор зовёт перечитать ответы."""
    assert module.contract_span(contract) == span
    assert policy.compatible(span, inside) and not policy.compatible(span, outside)


@pytest.mark.parametrize(
    "contract", ["9.9", "v9.9.0", "9.9.0-rc"], ids=["короче", "с-приставкой", "хвост"]
)
def test_a_contract_not_of_the_form_is_refused_in_our_words(contract: str) -> None:
    """Не версия X.Y.Z — отказ `onboard`, а не чужое исключение; разбор — `version.digits` (214)."""
    with pytest.raises(module.NotRun, match="версия контракта"):
        module.contract_span(contract)


def test_the_contract_is_read_at_the_pin_not_the_work_tree(tmp_path: Path) -> None:
    """Версия контракта — с дерева выпуска: рабочее дерево поставщика бывает впереди."""
    root = tree(tmp_path / "наше", tagged="v2.5.0", **{"step-пример": MARKED})
    (root / "CONTRACT_VERSION").write_text("9.10.0\n", encoding="utf-8")
    assert module.contract_at(root, "v2.5.0") == FAKE_VERSION
    with pytest.raises(module.NotRun):
        module.contract_at(root, "v9.9.9")


def test_write_never_overwrites_what_is_there(tmp_path: Path) -> None:
    """Занятый путь — отказ, и не кладётся ни один файл: половина заготовки хуже никакой."""
    root = tree(tmp_path / "наше", tagged="v2.5.0", **{"step-пример": MARKED})
    consumer = tmp_path / "потребитель"
    (consumer / ".github" / "workflows").mkdir(parents=True)
    (consumer / ".pipeline.yml").write_text("свой ответ\n", encoding="utf-8")
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OCCUPIED
    assert (consumer / ".pipeline.yml").read_text("utf-8") == "свой ответ\n"
    assert not (consumer / ".github" / "workflows" / "ci.yml").exists()


def cloned_with_trunk(where: Path, trunk: str) -> Path:
    """Дерево потребителя, чей клон знает общую ветку по `origin/HEAD`."""
    where.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(where)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(where),
            "symbolic-ref",
            "refs/remotes/origin/HEAD",
            f"refs/remotes/origin/{trunk}",
        ],
        check=True,
    )
    return where


def test_write_refuses_a_foreign_trunk(tmp_path: Path) -> None:
    """Общая ветка потребителя не `paths.TRUNK` — отказ до записи, а не чужая база (#1220)."""
    root = tree(tmp_path / "наше", tagged="v2.5.0", **{"step-пример": MARKED})
    consumer = cloned_with_trunk(tmp_path / "потребитель", "master")
    called = ["--root", str(root), "--write", str(consumer)]
    assert module.main(called) == module.EXIT_FOREIGN_TRUNK
    assert not (consumer / ".pipeline.yml").exists(), "положено в дерево с чужой веткой"


def test_write_takes_the_required_trunk(tmp_path: Path) -> None:
    """Общая ветка совпала — заготовка кладётся (#1220)."""
    root = tree(tmp_path / "наше", tagged="v2.5.0", **{"step-пример": MARKED})
    consumer = cloned_with_trunk(tmp_path / "потребитель", module.paths.TRUNK)
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OK
    assert module.trunk_of(consumer) == module.paths.TRUNK


def test_an_unknown_trunk_is_named_not_assumed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Клон без `origin/HEAD` — «не проверено», а не молчаливое совпадение (045, #1220)."""
    root = tree(tmp_path / "наше", tagged="v2.5.0", **{"step-пример": MARKED})
    consumer = tmp_path / "потребитель"
    consumer.mkdir()
    subprocess.run(["git", "init", "-q", str(consumer)], check=True)
    assert module.trunk_of(consumer) == ""
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OK
    assert "общая ветка дерева не проверена" in capsys.readouterr().out


def test_a_tree_inside_a_foreign_clone_is_not_checked_by_it(tmp_path: Path) -> None:
    """Каталог без своего `.git` внутри чужого клона — не его ветка (#1220)."""
    outer = cloned_with_trunk(tmp_path / "чужой", module.paths.TRUNK)
    inner = outer / "вложенный"
    inner.mkdir()
    assert module.trunk_of(outer) == module.paths.TRUNK
    assert module.trunk_of(inner) == "", "сверена ветка внешнего репозитория"


def test_the_thin_ci_carries_only_calls(tmp_path: Path) -> None:
    """В тонком `ci.yml` нет своих шагов: каждый джоб — вызов по тегу."""
    import yaml

    flow = yaml.safe_load(module.thin_ci(["а", "б"], "o/r", "v1.0.0"))
    assert set(flow["jobs"]) == {"а", "б"}
    assert all("steps" not in job and "@v1.0.0" in job["uses"] for job in flow["jobs"].values())


def test_a_kept_path_is_left_alone_and_its_check_goes_off(tmp_path: Path) -> None:
    """`--keep` оставляет путь проекту: заход его не пишет, проверка прогона — `off` (#1503).

    Обе половины: без ключа занятый путь — прежний отказ, с ключом — свой файл
    цел, а запись его прогона в ответе несёт класс `off` и причину. Ключ
    называет двойник `.yaml` — это тот же путь заготовки.
    """
    root = tree(
        tmp_path / "наше",
        **{"step-пример": MARKED, "step-план": MANAGED, "план": OWN_CALLER, "ci": CI_CALLER},
    )
    consumer = tmp_path / "потребитель"
    flows = consumer / ".github" / "workflows"
    flows.mkdir(parents=True)
    (flows / "план.yaml").write_text("своё\n", encoding="utf-8")
    argv = ["--root", str(root), "--write", str(consumer)]
    assert module.main(argv) == module.EXIT_OCCUPIED, "занятый путь без ключа — отказ, как прежде"
    assert module.main([*argv, "--keep", ".github/workflows/план.yaml"]) == module.EXIT_OK
    assert (flows / "план.yaml").read_text(encoding="utf-8") == "своё\n"
    assert not (flows / "план.yml").exists()
    answer = (consumer / module.paths.PIPELINE).read_text(encoding="utf-8")
    said = module.policy.answer_text(answer, str(module.paths.PIPELINE))
    entries = {
        str(name): module.policy.entry_of(item)
        for part in ("checks", module.policy.BEYOND)
        for name, item in (said.get(part) or {}).items()
    }
    names, _ = module.own_records(root / ".github" / "workflows" / "план.yml", "план")
    assert names, "у прогона нет записей — судить нечего"
    for name in names:
        klass, why, _ = entries[name]
        assert klass == module.policy.OFF and "--keep" in why, entries[name]


def test_a_kept_key_is_matched_to_the_kit_path_and_its_twin() -> None:
    """Ключ сводится к пути заготовки, двойник YAML — в любую сторону (взгляд на #1508)."""
    flows = module.paths.WORKFLOWS
    known = {flows / "план.yaml", flows / "ci.yml", module.paths.PIPELINE}
    keep, unknown = module.kept_on_the_kit(
        [flows / "план.yml", flows / "ci.yaml", module.paths.PIPELINE, flows / "нет.yml"], known
    )
    assert keep == [flows / "план.yaml", flows / "ci.yml", module.paths.PIPELINE]
    assert unknown == [str(flows / "нет.yml")]


@pytest.mark.parametrize("kept", ["ci.yml", "ci-complete.yml"])
def test_a_kept_pipeline_path_is_named_and_its_checks_stay(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kept: str
) -> None:
    """`--keep` на путь вне прогонов механизмов: не положен, проверки не тронуты (взгляд на #1508).

    Своё проект сводит с печатью захода, и вывод не обещает `off`, которого нет.
    """
    root = tree(tmp_path / "наше", **{"step-пример": MARKED, "ci": CI_CALLER})
    consumer = tmp_path / "потребитель"
    argv = ["--root", str(root), "--write", str(consumer), "--keep", f".github/workflows/{kept}"]
    assert module.main(argv) == module.EXIT_OK
    out = capsys.readouterr().out
    assert not (consumer / ".github" / "workflows" / kept).exists()
    assert "не положено по --keep" in out and "off с причиной" not in out, out
    said = module.policy.answer_text(
        (consumer / module.paths.PIPELINE).read_text(encoding="utf-8"), str(module.paths.PIPELINE)
    )
    classes = {module.policy.entry_of(item)[0] for item in (said.get("checks") or {}).values()}
    assert classes == {module.policy.UNREVIEWED}, said


def test_a_kept_answer_says_where_the_off_rows_are(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ответ и прогон механизма оставлены оба: `off` — в печати, а не в неположенном файле."""
    root = tree(
        tmp_path / "наше",
        **{"step-пример": MARKED, "step-план": MANAGED, "план": OWN_CALLER, "ci": CI_CALLER},
    )
    consumer = tmp_path / "потребитель"
    argv = ["--root", str(root), "--write", str(consumer)]
    keys = ["--keep", ".github/workflows/план.yml", "--keep", str(module.paths.PIPELINE)]
    assert module.main([*argv, *keys]) == module.EXIT_OK
    out = capsys.readouterr().out
    assert not (consumer / module.paths.PIPELINE).exists()
    assert "не положен (--keep)" in out, out


def test_a_suppliers_yaml_flow_is_kept_by_either_name(tmp_path: Path) -> None:
    """Свой прогон поставщика под `.yaml` оставляется ключом и под `.yml` (взгляд на #1508)."""
    root = tree(tmp_path / "наше", **{"step-пример": MARKED, "step-план": MANAGED, "ci": CI_CALLER})
    (root / ".github" / "workflows" / "план.yaml").write_text(OWN_CALLER, encoding="utf-8")
    run = ["git", "-C", str(root)]
    subprocess.run([*run, "add", "-A"], check=True, capture_output=True, timeout=30)
    subprocess.run([*run, "commit", "--quiet", "-m", "yaml"], check=True, timeout=30)
    subprocess.run([*run, "tag", "-f", "v2.5.0"], check=True, capture_output=True, timeout=30)
    for key in ("план.yml", "план.yaml"):
        consumer = tmp_path / f"потребитель-{key}"
        argv = ["--root", str(root), "--write", str(consumer), "--keep"]
        assert module.main([*argv, f".github/workflows/{key}"]) == module.EXIT_OK, key
        assert not (consumer / ".github" / "workflows" / "план.yaml").exists()


def test_kept_records_name_the_checks_of_a_kept_flow_only() -> None:
    """Причина `off` — у записей прогона по оставленному пути, и только у них."""
    own = {"план": Path("x/план.yml"), "обход": Path("x/обход.yml")}
    records = {"план": (["план / план"], False), "обход": (["обход / обход"], True)}
    kept = module.kept_records([module.paths.WORKFLOWS / "план.yml"], own, records)
    assert list(kept) == ["план / план"] and "--keep" in kept["план / план"]
    assert module.kept_records([], own, records) == {}


def test_a_kept_path_the_kit_does_not_lay_is_refused(tmp_path: Path) -> None:
    """Ключ на путь, которого заготовка не кладёт, — отказ до записи, а не молчание (045)."""
    root = tree(tmp_path / "наше", **{"step-пример": MARKED})
    consumer = tmp_path / "потребитель"
    argv = ["--root", str(root), "--write", str(consumer), "--keep", ".github/workflows/нет.yml"]
    assert module.main(argv) == module.EXIT_BROKEN
    assert not consumer.exists() or not any(consumer.iterdir()), "положено до отказа"


def test_keep_belongs_to_the_first_connection() -> None:
    """`--keep` без `--write` — ошибка вызова: обновлению и печати ключ не нужен."""
    with pytest.raises(SystemExit):
        module.main(["--keep", ".github/workflows/план.yml"])


def test_occupied_names_only_what_exists(tmp_path: Path) -> None:
    """`occupied` называет занятые пути, `lay` кладёт все."""
    files = {Path("a/x.yml"): "x\n", Path("y.yml"): "y\n"}
    (tmp_path / "y.yml").write_text("было\n", encoding="utf-8")
    assert module.occupied(tmp_path, files) == [Path("y.yml")]
    module.lay(tmp_path / "новое", files, "o/r")
    assert (tmp_path / "новое" / "a" / "x.yml").read_text("utf-8").endswith("\nx\n")


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
    summary = (consumer / module.paths.WORKFLOWS / module.SUMMARY_FLOW).read_text("utf-8")
    assert "/.github/actions/ci-complete@v2.5.0" in summary, "сводный гейт положен не вызовом"


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
        laid = (consumer / name).read_text("utf-8")
        assert laid.endswith(text) and module.LICENSE_ID in laid.splitlines()[0], laid


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
    assert (consumer / "AGENTS.md").read_text("utf-8").endswith(KIT["AGENTS.md"])
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
    for one in (root / "kit").glob("*.md"):
        one.unlink()
    assert module.main(["--root", str(root)]) == module.EXIT_BROKEN


def test_the_live_kit_is_what_onboard_lays() -> None:
    """Живое дерево: заход кладёт ровно файлы свода, у которых есть заготовка."""
    rulebook = load_script("check_rulebook_fresh.py").RULEBOOK
    assert sorted(str(one) for one in module.rulebook_kit(ROOT)) == sorted(rulebook)


# --- заготовки данных взгляда (#1386) ---------------------------------------


def test_data_kit_reads_the_tree_and_derives_the_areas(tmp_path: Path) -> None:
    """Состав — файлы `kit/data/`, таблица областей — из наших областей с пустыми путями."""
    root = tree(tmp_path, **{"step-пример": MARKED})
    kit = module.data_kit(root)
    assert sorted(map(str, kit)) == sorted([*DATA, ".rules/area-paths.json"])
    assert module.paths.BINDINGS not in kit, "ответ каталогу ушёл заготовкой"


def test_the_area_kit_names_every_area_with_a_reason(tmp_path: Path) -> None:
    """Каждая наша область у потребителя — любой путь и пояснение, что заполнять."""
    root = tree(tmp_path, **{"step-пример": MARKED})
    areas = json.loads(module.area_kit(root))["areas"]
    assert sorted(areas) == ["docs", "gates"]
    want = {"paths": list(module.AREA_ANY), "why": module.AREA_FILL}
    assert all(one == want for one in areas.values())


def test_an_unreadable_area_table_is_a_refusal(tmp_path: Path) -> None:
    """Нашей таблицы областей нет — отказ, а не заготовка без областей (075)."""
    root = tree(tmp_path, **{"step-пример": MARKED})
    (root / ".rules" / "area-paths.json").unlink()
    with pytest.raises(module.NotRun):
        module.area_kit(root)


def test_an_empty_data_kit_is_a_refusal(tmp_path: Path) -> None:
    """Пустой `kit/data/` — отказ: заход назвал бы подключение полным без данных взгляда."""
    root = tree(tmp_path, **{"step-пример": MARKED})
    for one in sorted((root / module.DATA_KIT).rglob("*"), reverse=True):
        one.unlink() if one.is_file() else one.rmdir()
    assert module.main(["--root", str(root)]) == module.EXIT_BROKEN


def test_lay_free_keeps_what_is_there(tmp_path: Path) -> None:
    """Занятый путь не тронут и не назван положенным; свободный положен."""
    (tmp_path / "a.md").write_text("своё", encoding="utf-8")
    kit = {Path("a.md"): "заготовка", Path("b/c.md"): "заготовка"}
    laid = module.lay_free(tmp_path, kit, "o/r")
    assert laid == [Path("b/c.md")]
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "своё"


def test_a_yaml_twin_of_a_run_takes_its_place_at_both_doors(tmp_path: Path) -> None:
    """Свой `ci.yaml` занимает место `ci.yml` у `--write` и правится у `--update` (`1f2ca12`).

    Площадка читает прогон под обоими расширениями: второй файл рядом — два
    прогона на одно событие.
    """
    flows = tmp_path / ".github" / "workflows"
    flows.mkdir(parents=True)
    # Двойник с нашим вызовом на старом теге: обновлению есть что править, и
    # «не положило рядом» отличается от «промолчало» (находка `52e29e5`).
    mine = "name: ci\non: [push]\njobs:\n" + module.caller("а", "o/r", "v8.0.0")
    (flows / "ci.yaml").write_text(mine, encoding="utf-8")
    run = module.paths.WORKFLOWS / module.PIPELINE_FLOW
    assert module.standing(tmp_path, run) == run.with_suffix(".yaml")
    assert module.occupied(tmp_path, {run: "заготовка"}) == [run]
    plan = module.Update()
    module.plan_ci(plan, tmp_path, ["а", "б"], "o/r", "v9.0.0")
    assert run not in plan.write, "обновление положило бы ci.yml рядом с ci.yaml"
    assert "@v9.0.0" in plan.write[run.with_suffix(".yaml")], (
        "двойник не поднят — обновление молчит"
    )
    # Заметка о новом шаге называет файл, который у потребителя есть (`a137a27`).
    assert any("вашего `ci.yaml`" in note for note in plan.notes), plan.notes


def test_a_twin_of_our_own_data_takes_no_place(tmp_path: Path) -> None:
    """Свои файлы механизмов читаются точным именем: `.pipeline.yaml` места не занимает."""
    assert module.read_by_the_platform(module.paths.WORKFLOWS / "ci.yml")
    assert module.read_by_the_platform(module.paths.DEPENDABOT.with_suffix(".yaml"))
    assert not module.read_by_the_platform(module.paths.PIPELINE)
    (tmp_path / ".pipeline.yaml").write_text("своё", encoding="utf-8")
    assert module.standing(tmp_path, module.paths.PIPELINE) == module.paths.PIPELINE
    assert module.occupied(tmp_path, {module.paths.PIPELINE: "заготовка"}) == []


def test_a_dormant_area_table_is_named_until_the_role_is_declared(tmp_path: Path) -> None:
    """Таблица областей без объявленной роли — названная спячка; роль объявлена — тишина."""
    assert module.dormant_areas_note(tmp_path) == "", "таблицы нет — и говорить не о чем"
    module.lay(tmp_path, module.data_kit(ROOT), "o/r")
    said = module.dormant_areas_note(tmp_path)
    assert "спит" in said and module.ROLE_PILOT in said
    roles = tmp_path / module.paths.REVIEW_ROLES
    table = json.loads(roles.read_text(encoding="utf-8"))
    table["by_path"] = [{"paths": ["**/*"], "roles": [module.review_map.CATALOGUE_ROLE]}]
    roles.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    assert module.dormant_areas_note(tmp_path) == ""


def test_a_yaml_twin_takes_the_path(tmp_path: Path) -> None:
    """`dependabot.yaml` потребителя занимает место `dependabot.yml`: второго конфига нет."""
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "dependabot.yaml").write_text("своё", encoding="utf-8")
    assert module.taken_by_twin(tmp_path, module.paths.DEPENDABOT)
    assert module.lay_free(tmp_path, {module.paths.DEPENDABOT: "заготовка"}, "o/r") == []
    assert not (tmp_path / module.paths.DEPENDABOT).exists()


def test_bindings_note_speaks_only_when_the_answer_is_missing(tmp_path: Path) -> None:
    """Ответа каталогу нет — названо; есть — тишина."""
    assert "карта взгляда не собирается" in module.bindings_note(tmp_path)
    (tmp_path / ".rules").mkdir()
    (tmp_path / ".rules" / "bindings.json").write_text("{}", encoding="utf-8")
    assert module.bindings_note(tmp_path) == ""


def test_write_lays_the_data_kits_and_keeps_the_projects_own(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--write`: заготовки — в свободное, занятая — не тронута и отказа не даёт."""
    root = tree(tmp_path / "наше", **{"step-пример": MARKED})
    consumer = tmp_path / "потребитель"
    (consumer / "docs" / "agent").mkdir(parents=True)
    (consumer / "docs" / "agent" / "roles.md").write_text("свои роли", encoding="utf-8")
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OK
    assert (consumer / "docs" / "agent" / "roles.md").read_text(encoding="utf-8") == "свои роли"
    assert (consumer / ".rules" / "review-roles.json").is_file()
    assert (consumer / ".rules" / "area-paths.json").is_file()
    said = capsys.readouterr().out
    assert "положены заготовки данных" in said and "bindings.json" in said


def test_update_lays_a_missing_data_kit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--update`: удалённая заготовка ложится снова, своё не тронуто."""
    root = tree(tmp_path / "наше", **{"step-пример": MARKED})
    consumer = tmp_path / "потребитель"
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OK
    (consumer / ".rules" / "review-roles.json").unlink()
    (consumer / "docs" / "agent" / "roles.md").write_text("свои роли", encoding="utf-8")
    capsys.readouterr()
    assert module.main(["--root", str(root), "--update", str(consumer)]) == module.EXIT_OK
    assert (consumer / ".rules" / "review-roles.json").is_file()
    assert (consumer / "docs" / "agent" / "roles.md").read_text(encoding="utf-8") == "свои роли"
    assert "положены заготовки данных: .rules/review-roles.json" in capsys.readouterr().out


def test_the_live_data_kit_holds_exactly_the_declared_paths() -> None:
    """`kit/data/` несёт ровно `DATA_KITTED`: лишний файл не лёг бы, недостающий — отказ."""
    base = ROOT / module.DATA_KIT
    found = {one.relative_to(base) for one in walk_deep(base) if one.is_file()}
    assert found == set(module.DATA_KITTED)


def test_the_live_data_kit_is_what_the_review_map_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Живое дерево: каждая заготовка той формы, что принимает карта взгляда.

    Иначе карта у нового потребителя отказывала бы на нашей же заготовке, и
    «карта работает с первого дня» было бы словом, а не свойством (107).
    """
    review_map = load_script("review_map.py")
    findings = load_script("findings.py")
    kit = module.data_kit(ROOT)
    table = review_map.table_shape(json.loads(kit[Path(".rules/review-roles.json")]))
    # ПУТЬ ЦЕЛИКОМ: заготовка → `role_declared` → `area_table` → `narrow`
    # (находки `5f1a15d`, `72d2c49`). Скелет роль не объявляет — её пилот у
    # механизмов (#1277), — и таблица спит; объявленная роль будит её.
    shown = dict(kit)
    monkeypatch.setattr(review_map, "shown_from_base", lambda _, path: shown[Path(path)])
    assert not review_map.role_declared("main"), "скелет объявил роль до раскатки (#1277)"
    declared = {**table, "required": [*table["required"], review_map.CATALOGUE_ROLE]}
    shown[Path(".rules/review-roles.json")] = json.dumps(declared, ensure_ascii=False)
    assert review_map.role_declared("main"), "объявленная роль не видна карте"
    assert review_map.declares_role({"by_path": [{"roles": [review_map.CATALOGUE_ROLE]}]})
    assert not review_map.declares_role(table), "скелет объявил роль"
    table_of_areas = review_map.area_table("main")
    # НЕЗАПОЛНЕННАЯ ЗАГОТОВКА НЕ СУЖАЕТ РОЛЬ (взгляд на #1455): правило с любой
    # областью заготовки отдаётся роли на любом пути — как без таблицы.
    areas_of = {"1": [next(iter(table_of_areas))]}
    for files in (["README.md"], ["scripts/deep/x.py"]):
        said = review_map.narrow(["1"], [], areas_of, table_of_areas, files)
        assert said.eyes == ["1"], f"заготовка отсеяла правило на {files}: {said}"
    assert review_map.SUBJECT in kit[Path("docs/agent/review.md")]
    roles = tmp_path / "roles.md"
    roles.write_text(kit[Path("docs/agent/roles.md")], encoding="utf-8")
    named = findings.roles.__wrapped__(roles)
    assert set(table["required"]) <= named, "обязательная роль заготовки без профиля"
    bot = yaml.safe_load(kit[Path(".github/dependabot.yml")])
    assert [one["package-ecosystem"] for one in bot["updates"]] == ["github-actions"]


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


# --- значок проекта в README (#1282, шаг 3) ----------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Владелец/репо.git",
        "git@github.com:Владелец/репо.git",
        "http://proxy@127.0.0.1:8080/git/Владелец/репо",
        "ssh://git@github.com/Владелец/репо.git",
        "https://x-access-token:секрет@github.com/Владелец/репо.git",
        "http://github.com/Владелец/репо",
        "https://www.github.com/Владелец/репо",
    ],
)
def test_the_repo_is_read_from_origin_in_every_form(tmp_path: Path, url: str) -> None:
    """Имя `владелец/репо` берётся из `origin` в любой форме адреса, а не угадывается."""
    consumer = cloned_with_trunk(tmp_path / "потребитель", module.paths.TRUNK)
    subprocess.run(["git", "-C", str(consumer), "remote", "add", "origin", url], check=True)
    assert module.repo_of(consumer) == "Владелец/репо"


@pytest.mark.parametrize(
    "url",
    [
        "/srv/git/Владелец/репо",
        "https://gitlab.com/Владелец/репо.git",
        "git@ghe.example.com:Владелец/репо.git",
        "https://github.com/Владелец",
    ],
    ids=["локальный-путь", "чужой-хост", "свой-сервер-площадки", "без-репо"],
)
def test_a_foreign_origin_names_no_repo(tmp_path: Path, url: str) -> None:
    """Не адрес площадки — пусто, и заход печатает заглушку, а не битую ссылку (`d3639d2`)."""
    consumer = cloned_with_trunk(tmp_path / "потребитель", module.paths.TRUNK)
    subprocess.run(["git", "-C", str(consumer), "remote", "add", "origin", url], check=True)
    assert module.repo_of(consumer) == ""


def test_the_badge_line_names_the_published_branch() -> None:
    """Ветка в строке значка — та, куда публикует общий шаг (`df6d81f`)."""
    line = module.badge_line("o/r")
    assert f"/o/r/{module.publish_facts.BRANCH}/" in line


def test_a_tree_without_its_own_origin_names_no_repo(tmp_path: Path) -> None:
    """Нет `origin` или дерево внутри чужого клона — пусто, а не имя внешнего (045)."""
    outer = cloned_with_trunk(tmp_path / "чужой", module.paths.TRUNK)
    assert module.repo_of(outer) == ""
    url = "https://github.com/Чужой/репо.git"
    subprocess.run(["git", "-C", str(outer), "remote", "add", "origin", url], check=True)
    inner = outer / "вложенный"
    inner.mkdir()
    assert module.repo_of(inner) == "", "назван репозиторий внешнего клона"


def test_the_badge_is_what_the_shared_step_publishes() -> None:
    """Строка ведёт на файл, который КЛАДЁТ общий шаг фактов, а не на рисунок нашей витрины.

    Сверка с `build_facts.PICTURES` была зелёной и тогда, когда шаг значка не
    публиковал: она сверяла сборку поставщика, а не путь потребителя (взгляд на
    #1328, 044). Здесь — с перечнем публикации шага, `publish_facts.PUBLISHES`.
    """
    published = load_script("publish_facts.py").PUBLISHES
    assert module.BADGE.as_posix() in published, (
        f"строка ведёт на {module.BADGE.as_posix()}, а общий шаг кладёт {published}"
    )
    line = module.badge_line("o/r")
    assert (
        line == "![проект](https://raw.githubusercontent.com/o/r/badges/.github/badges/project.svg)"
    )


def test_both_kits_print_the_badge_line_and_leave_readme_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Печать — строка с заглушкой; `--write` — с именем из `origin`; README не создан (#1282)."""
    root = tree(tmp_path / "наше", tagged="v2.5.0", **{"step-пример": MARKED})
    assert module.main(["--root", str(root)]) == module.EXIT_OK
    printed = capsys.readouterr().out
    assert module.badge_line(module.REPO_PLACEHOLDER) in printed
    assert module.PRIVATE_NOTE in printed, "условие закрытого репозитория не названо"
    consumer = cloned_with_trunk(tmp_path / "потребитель", module.paths.TRUNK)
    url = "https://github.com/Владелец/репо.git"
    subprocess.run(["git", "-C", str(consumer), "remote", "add", "origin", url], check=True)
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OK
    written = capsys.readouterr().out
    assert module.badge_line("Владелец/репо") in written
    assert module.PRIVATE_NOTE in written, "условие закрытого репозитория не названо"
    assert not (consumer / "README.md").exists(), "заход положил README"


def test_the_summary_kit_calls_the_action_by_its_pin() -> None:
    """Тонкий сводный гейт потребителя — наш прогон с адресом действия вместо `./` (#1385)."""
    kit = module.summary_kit(ROOT, "o/r", "v9.9.9")
    assert f"uses: o/r/{module.paths.SUMMARY_ACTION.parent.as_posix()}@v9.9.9" in kit
    assert module.SUMMARY_CALL not in kit
    assert "name: ci-complete" in kit, "имя в защите ветки обязано остаться прежним"


def test_a_summary_flow_without_its_call_is_not_guessed(tmp_path: Path) -> None:
    """Вызова действия в прогоне нет — третий исход, а не подмена наугад (075)."""
    flows = tmp_path / module.paths.WORKFLOWS
    flows.mkdir(parents=True)
    (flows / module.SUMMARY_FLOW).write_text("jobs: {}\n", encoding="utf-8")
    with pytest.raises(module.NotRun):
        module.summary_kit(tmp_path, "o/r", "v1")


# --- обновление (#1386) --------------------------------------------------------


def released(root: Path, tag: str, **runs: str) -> None:
    """Следующий выпуск поставщика: прогоны меняются, коммит помечается тегом."""
    for name, body in runs.items():
        (root / ".github" / "workflows" / f"{name}.yml").write_text(body, encoding="utf-8")
    run = ["git", "-C", str(root)]
    subprocess.run([*run, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*run, "commit", "--quiet", "-m", tag], check=True)
    subprocess.run([*run, "tag", tag], check=True)


def connected(tmp_path: Path) -> tuple[Path, Path]:
    """Поставщик с шагом конвейера и управляющим механизмом и потребитель на v2.5.0."""
    root = tree(
        tmp_path / "наше",
        **{"step-пример": MARKED, "step-план": MANAGED, "план": OWN_CALLER, "ci": CI_CALLER},
    )
    consumer = tmp_path / "потребитель"
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OK
    return root, consumer


@pytest.mark.parametrize(("step", "said"), [("minor", True), ("patch", False)])
def test_an_update_past_the_contract_window_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], step: str, said: bool
) -> None:
    """Подъём прибивки за окно `contract:` назван обновлением, а не толчком (`b923c76`).

    Минор контракта вырос — окно ответа потребителя его не покрывает, и
    обновление говорит это до записи (`d9b9a4f`, `4962cb3`). Патч поверхности
    не трогает: о нём обновление молчит.
    """
    root, consumer = connected(tmp_path)
    major, minor, patch = (int(one) for one in FAKE_VERSION.split("."))
    bumped = f"{major}.{minor + 1}.0" if step == "minor" else f"{major}.{minor}.{patch + 1}"
    (root / "CONTRACT_VERSION").write_text(f"{bumped}\n", encoding="utf-8")
    released(root, "v2.6.0", план=OWN_CALLER_NEXT)
    capsys.readouterr()
    assert module.main(["--root", str(root), "--update", str(consumer)]) == module.EXIT_OK
    out = capsys.readouterr().out
    assert ("не покрывает контракт" in out and bumped in out) is said, out


#: Следующий выпуск меняет вызывающий: у механизма появилось событие.
OWN_CALLER_NEXT = OWN_CALLER.replace("  workflow_dispatch:\n", "  workflow_dispatch:\n  push:\n")


def test_update_lifts_ours_and_keeps_the_projects_own(tmp_path: Path) -> None:
    """Наше переписано на новый выпуск, `.pipeline.yml` проекта не тронут ни байтом."""
    root, consumer = connected(tmp_path)
    answer = (consumer / ".pipeline.yml").read_bytes()
    released(root, "v2.6.0", план=OWN_CALLER_NEXT)
    assert module.main(["--root", str(root), "--update", str(consumer)]) == module.EXIT_OK
    flows = consumer / ".github" / "workflows"
    plan = (flows / "план.yml").read_text("utf-8")
    assert "step-план.yml@v2.6.0" in plan and "push" in plan
    assert "step-пример.yml@v2.6.0" in (flows / "ci.yml").read_text("utf-8")
    assert "/.github/actions/ci-complete@v2.6.0" in (flows / "ci-complete.yml").read_text("utf-8")
    assert (consumer / ".pipeline.yml").read_bytes() == answer


def test_update_ignores_the_form_and_reads_the_substance(tmp_path: Path) -> None:
    """Комментарий и порядок ключей — форма записи: файл остаётся нашим и обновляется."""
    root, consumer = connected(tmp_path)
    flow = consumer / ".github" / "workflows" / "план.yml"
    flow.write_text("# свой комментарий\n" + flow.read_text("utf-8"), encoding="utf-8")
    released(root, "v2.6.0", план=OWN_CALLER_NEXT)
    assert module.main(["--root", str(root), "--update", str(consumer)]) == module.EXIT_OK
    assert "step-план.yml@v2.6.0" in flow.read_text("utf-8")


def test_a_hand_edit_of_ours_refuses_the_whole_update(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Правка по существу — исход 7, не записан ни один файл, разница — поставщику."""
    root, consumer = connected(tmp_path)
    flows = consumer / ".github" / "workflows"
    plan = flows / "план.yml"
    plan.write_text(
        plan.read_text("utf-8").replace("  workflow_dispatch:", "  schedule:\n  - cron: 0 1 * * *"),
        encoding="utf-8",
    )
    before = {one.name: one.read_bytes() for one in flows.iterdir()}
    released(root, "v2.6.0", план=OWN_CALLER_NEXT)
    code = module.main(["--root", str(root), "--update", str(consumer)])
    assert code == module.EXIT_HAND_EDITED
    assert {one.name: one.read_bytes() for one in flows.iterdir()} == before
    said = capsys.readouterr().err
    assert "schedule" in said and str(module.paths.GAP_TEMPLATE) in said


def test_an_own_copy_is_named_and_left_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Своя копия под нашим именем, не зовущая наш шаг, не трогается, а называется."""
    root, consumer = connected(tmp_path)
    copy = consumer / ".github" / "workflows" / "план.yml"
    copy.write_text("name: план\non: push\njobs:\n  свой:\n    steps: []\n", encoding="utf-8")
    released(root, "v2.6.0", план=OWN_CALLER_NEXT)
    assert module.main(["--root", str(root), "--update", str(consumer)]) == module.EXIT_OK
    assert "свой:" in copy.read_text("utf-8")
    assert "своя копия" in capsys.readouterr().out


def test_a_new_pipeline_step_is_printed_not_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Новый шаг выпуска — готовым джобом в выводе; `ci.yml` проекта им не дописывается."""
    root, consumer = connected(tmp_path)
    second = MARKED.replace("step-пример", "step-второй")
    released(
        root,
        "v2.6.0",
        **{
            "step-второй": second,
            "ci": CI_CALLER + "  второй:\n    uses: ./.github/workflows/step-второй.yml\n",
        },
    )
    assert module.main(["--root", str(root), "--update", str(consumer)]) == module.EXIT_OK
    out = capsys.readouterr().out
    assert "новый шаг `второй`" in out and "step-второй.yml@v2.6.0" in out
    assert "второй" not in (consumer / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    assert module.check_name("второй") in out


def test_update_and_write_are_two_doors(tmp_path: Path) -> None:
    """Первое подключение и обновление в одном заходе — ошибка вызова, а не выбор одного."""
    with pytest.raises(SystemExit):
        module.main(["--write", str(tmp_path), "--update", str(tmp_path)])


def test_essence_reads_events_in_every_form() -> None:
    """Событие строкой, списком и словарём — одно существо."""
    forms = ["on: push\n", "on: [push]\n", "on:\n  push:\n"]
    said = [module.essence(one + "jobs: {}\n", "o/r", Path("x.yml"))["on"] for one in forms]
    assert said[0] == said[1] == said[2] == {"push": None}


def test_calls_of_reads_job_and_step_calls_without_the_tag() -> None:
    """Вызов шага джобом и действия шагом — оба без тега, чужой адрес не в счёт."""
    document = {
        "jobs": {
            "a": {"uses": "o/r/.github/workflows/step-x.yml@v1.0.0", "with": {"k": 1}},
            "b": {"steps": [{"uses": "o/r/.github/actions/y@v1.0.0"}, {"uses": "other/z@v1"}]},
        }
    }
    said = module.calls_of(document, "o/r")
    assert {one["uses"] for one in said} == {
        "o/r/.github/actions/y",
        "o/r/.github/workflows/step-x.yml",
    }
    assert module.new_tag("uses: o/r/.github/workflows/step-x.yml@v1.0.0", "o/r") == "v1.0.0"


def test_a_tag_the_supplier_does_not_have_does_not_run(tmp_path: Path) -> None:
    """Файл прибит к тегу, которого у поставщика нет, — «не отработал», а не «правлен»."""
    root, consumer = connected(tmp_path)
    plan = consumer / ".github" / "workflows" / "план.yml"
    plan.write_text(
        plan.read_text("utf-8").replace("@v2.5.0", "@v9.9.9").replace("workflow_dispatch", "push"),
        encoding="utf-8",
    )
    released(root, "v2.6.0", план=OWN_CALLER_NEXT)
    assert module.main(["--root", str(root), "--update", str(consumer)]) == module.EXIT_BROKEN


def test_the_update_plan_is_decided_before_any_write(tmp_path: Path) -> None:
    """План обновления собирается целиком по частям до записи: наше, `ci.yml`, ответ."""
    root, consumer = connected(tmp_path)
    released(root, "v2.6.0", план=OWN_CALLER_NEXT)
    repo = "ArtVsMark/Engineering-Pipeline-Mechanisms"
    assert module.our_uses(repo).search(f"uses: {repo}/.github/workflows/step-x.yml@v1.0.0")
    new = module.owned(root, repo, "v2.6.0")
    old = module.owned_at(root, "v2.5.0", repo)
    assert set(new) == set(old)
    plan = module.Update()
    module.plan_owned(plan, consumer, new, root, repo)
    module.plan_ci(plan, consumer, ["пример"], repo, "v2.6.0")
    wanted = [module.check_name("пример"), "лишний / лишний"]
    module.plan_answer(plan, consumer, wanted, FAKE_VERSION, "v2.6.0")
    assert not plan.edited
    assert module.paths.WORKFLOWS / "план.yml" in plan.write
    assert module.paths.WORKFLOWS / module.PIPELINE_FLOW in plan.write
    assert any("лишний / лишний" in one for one in plan.notes)
    said = module.policy.run_text("on: push\njobs: {}\n", "x.yml")
    assert module.policy.events_raw(said) == "push"


def test_a_yaml_twin_of_an_owned_run_is_updated_in_place(tmp_path: Path) -> None:
    """Свой `.yaml` целиком нашего прогона правится на месте, а не получает соседа.

    Третья дверь двойника: `occupied` у `--write` и `plan_ci` у `--update`
    проверены соседним тестом, а `plan_owned` — нет (взгляд на #1461).
    """
    root, consumer = connected(tmp_path)
    flows = consumer / ".github" / "workflows"
    (flows / "план.yml").rename(flows / "план.yaml")
    released(root, "v2.6.0", план=OWN_CALLER_NEXT)
    repo = "ArtVsMark/Engineering-Pipeline-Mechanisms"
    plan = module.Update()
    module.plan_owned(plan, consumer, module.owned(root, repo, "v2.6.0"), root, repo)
    run = module.paths.WORKFLOWS / "план.yml"
    assert run not in plan.write, "обновление положило бы план.yml рядом с план.yaml"
    assert run.with_suffix(".yaml") in plan.write


def test_consumer_inputs_survive_the_update(tmp_path: Path) -> None:
    """Входы `with:` — данные потребителя: правка не отказ, обновление их сохраняет (#1386)."""
    import yaml

    root, consumer = connected(tmp_path)
    plan = consumer / ".github" / "workflows" / "план.yml"
    text = plan.read_text("utf-8")
    plan.write_text(
        text.replace("step-план.yml@v2.5.0", "step-план.yml@v2.5.0\n    with:\n      свой: 1"),
        encoding="utf-8",
    )
    released(root, "v2.6.0", план=OWN_CALLER_NEXT)
    assert module.main(["--root", str(root), "--update", str(consumer)]) == module.EXIT_OK
    said = yaml.safe_load(plan.read_text("utf-8"))
    job = said["jobs"]["план"]
    assert job["uses"].endswith("step-план.yml@v2.6.0") and job["with"] == {"свой": 1}
    assert "push" in module.policy.events_raw(said)


def test_keep_inputs_leaves_the_kit_as_is_when_inputs_agree() -> None:
    """Входы совпали — текст заготовки как есть, с её пояснениями."""
    new = "# пояснение\non: push\njobs:\n  a:\n    uses: o/r/.github/workflows/step-x.yml@v2\n"
    mine = "on: push\njobs:\n  a:\n    uses: o/r/.github/workflows/step-x.yml@v1\n"
    assert module.keep_inputs(new, mine, "o/r", Path("x.yml"), Path("нет")) == new
    edited = mine.replace("@v1\n", "@v1\n    with:\n      k: 2\n")
    kept = module.keep_inputs(new, edited, "o/r", Path("x.yml"), Path("нет"))
    said = module.policy.run_text(kept, "x.yml")
    assert said["jobs"]["a"] == {"uses": "o/r/.github/workflows/step-x.yml@v2", "with": {"k": 2}}
    assert module.policy.events_raw(said) == "push"


def test_callers_in_finds_job_and_step_calls_in_order() -> None:
    """Узлы вызова — джобом и шагом, в порядке записи, без тега; чужой адрес не в счёт."""
    document = {
        "jobs": {
            "a": {"uses": "o/r/.github/workflows/step-x.yml@v1"},
            "b": {"steps": [{"uses": "other/z@v1"}, {"uses": "o/r/.github/actions/y@v1"}]},
        }
    }
    said = module.callers_in(document, "o/r")
    assert [address for address, _ in said] == [
        "o/r/.github/workflows/step-x.yml",
        "o/r/.github/actions/y",
    ]


def test_an_input_added_by_the_release_is_kept(tmp_path: Path) -> None:
    """Новый вход выпуска остаётся, свой вход потребителя — поверх (взгляд на #1438)."""
    head = "on: push\njobs:\n  a:\n    uses: o/r/.github/workflows/step-x.yml"
    new = head + "@v2\n    with:\n      fresh: 2\n"
    mine = head + "@v1\n    with:\n      k: 9\n"
    said = module.policy.run_text(
        module.keep_inputs(new, mine, "o/r", Path("x.yml"), tmp_path), "x"
    )
    assert said["jobs"]["a"]["with"] == {"fresh": 2, "k": 9}


def test_inputs_are_matched_by_the_order_of_the_call(tmp_path: Path) -> None:
    """Два вызова одного адреса: правка второго не теряется в сверке (взгляд на #1438)."""
    call = "    uses: o/r/.github/workflows/step-x.yml@{tag}\n    with:\n      k: {k}\n"
    new = (
        "on: push\njobs:\n  a:\n"
        + call.format(tag="v2", k=1)
        + "  b:\n"
        + call.format(tag="v2", k=1)
    )
    mine = (
        "on: push\njobs:\n  a:\n"
        + call.format(tag="v1", k=1)
        + "  b:\n"
        + call.format(tag="v1", k=5)
    )
    said = module.policy.run_text(
        module.keep_inputs(new, mine, "o/r", Path("x.yml"), tmp_path), "x"
    )
    assert said["jobs"]["a"]["with"] == {"k": 1} and said["jobs"]["b"]["with"] == {"k": 5}


def test_an_input_the_step_does_not_declare_is_dropped_and_named(tmp_path: Path) -> None:
    """Вход, которого шаг не объявляет, снимается и называется: площадка отвергла бы вызов."""
    step = tmp_path / ".github" / "workflows" / "step-x.yml"
    step.parent.mkdir(parents=True)
    step.write_text(
        "on:\n  workflow_call:\n    inputs:\n      fresh: {}\n      k: {}\njobs: {}\n", "utf-8"
    )
    assert module.accepted_inputs(tmp_path, "o/r/.github/workflows/step-x.yml", "o/r") == {
        "fresh",
        "k",
    }
    new = "on: push\njobs:\n  a:\n    uses: o/r/.github/workflows/step-x.yml@v2\n"
    mine = new.replace("@v2\n", "@v1\n    with:\n      k: 1\n      old: 2\n")
    kept = module.keep_inputs(new, mine, "o/r", Path("x.yml"), tmp_path)
    assert module.policy.run_text(kept, "x")["jobs"]["a"]["with"] == {"k": 1}
    assert "Сняты входы" in kept and "old" in kept
    assert module.merged_inputs({"a": 1}, {"b": 2}, None) == ({"a": 1, "b": 2}, [])


def test_a_withdrawn_step_keeps_its_old_tag(tmp_path: Path) -> None:
    """Снятый выпуском шаг не переводится на тег, где его нет (взгляд на #1438)."""
    consumer = tmp_path
    flows = consumer / ".github" / "workflows"
    flows.mkdir(parents=True)
    repo = "o/r"
    (flows / "ci.yml").write_text(
        "jobs:\n  a:\n    uses: o/r/.github/workflows/step-a.yml@v1\n"
        "  b:\n    uses: o/r/.github/workflows/step-b.yml@v1\n",
        encoding="utf-8",
    )
    plan = module.Update()
    module.plan_ci(plan, consumer, ["a"], repo, "v2")
    text = plan.write[module.paths.WORKFLOWS / module.PIPELINE_FLOW]
    assert "step-a.yml@v2" in text and "step-b.yml@v1" in text
    assert any("`b`" in one and "прежнем теге" in one for one in plan.notes)


@pytest.mark.parametrize(
    ("name", "first"),
    [
        ("ci.yml", "# SPDX-License-Identifier: MIT — https://github.com/o/r\n"),
        ("ci.yaml", "# SPDX-License-Identifier: MIT — https://github.com/o/r\n"),
        ("CLAUDE.md", "<!-- SPDX-License-Identifier: MIT — https://github.com/o/r -->\n"),
    ],
    ids=["yml", "yaml", "md"],
)
def test_the_license_line_takes_the_form_of_its_kind(name: str, first: str) -> None:
    """Строка лицензии — в форме своего рода, первой строкой, и один раз (#1470)."""
    signed = module.licensed(Path(name), "тело\n", "o/r")
    assert signed == first + "тело\n"
    assert module.licensed(Path(name), signed, "o/r") == signed


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("a.yml", "# Лицензия: SPDX-License-Identifier: MIT — названа в тексте\nx: 1\n"),
        ("a.md", "Текст называет SPDX-License-Identifier: MIT, но файл не подписан.\n"),
        ("a.json", '{"note": "SPDX-License-Identifier: MIT", "x": 1}\n'),
    ],
    ids=["yml", "md", "json"],
)
def test_a_mention_of_the_license_is_not_a_signature(name: str, text: str) -> None:
    """Идентификатор, названный в теле, — не подпись: строка ставится на своё место (`c12022f`)."""
    assert not module.is_signed(Path(name), text)
    signed = module.licensed(Path(name), text, "o/r")
    assert signed != text and module.is_signed(Path(name), signed), signed


def test_the_projects_file_is_one_sign_for_every_door() -> None:
    """Файл проекта — один признак: и `ci.yml`, и его двойник `.yaml` (`215204f`)."""
    run = module.paths.WORKFLOWS / module.PIPELINE_FLOW
    assert module.of_the_project(run) and module.of_the_project(run.with_suffix(".yaml"))
    assert not module.of_the_project(module.paths.WORKFLOWS / module.SUMMARY_FLOW)
    files = {run.with_suffix(".yaml"): "x: 1\n", Path("a.yml"): "y: 2\n"}
    signed = module.signed_all(files, "o/r")
    assert signed[run.with_suffix(".yaml")] == "x: 1\n"
    assert module.is_signed(Path("a.yml"), signed[Path("a.yml")])


def test_a_json_kit_carries_the_license_as_its_first_field() -> None:
    """JSON комментариев не знает: лицензия — поле `_license`, и таблица ролей её пропускает."""
    kit = module.data_kit(ROOT)[module.paths.REVIEW_ROLES]
    table = json.loads(module.licensed(module.paths.REVIEW_ROLES, kit, "o/r"))
    assert next(iter(table)) == "_license"
    assert table["_license"] == "SPDX-License-Identifier: MIT — https://github.com/o/r"
    module.review_map.table_shape(table)


@pytest.mark.parametrize(
    ("name", "text"),
    [("a.toml", "x = 1\n"), ("a.json", "[1]\n")],
    ids=["род-без-формы", "json-не-словарь"],
)
def test_a_kit_without_a_place_for_the_license_is_refused(name: str, text: str) -> None:
    """Некуда поставить строку лицензии — отказ, а не заготовка без неё (045, #1470)."""
    with pytest.raises(module.NotRun, match="лицензии"):
        module.licensed(Path(name), text, "o/r")


def test_every_file_the_write_lays_carries_the_license(tmp_path: Path) -> None:
    """Каждая заготовка, положенная заходом, несёт строку лицензии; `ci.yml` — нет (#1470).

    Судится результат захода целиком, а не каждая заготовка порознь: путь
    записи один, и новая заготовка, прошедшая мимо него, здесь видна. Тонкий
    `ci.yml` — файл проекта (`OWN_BY_PROJECT`): в него проект дописывает свои
    джобы, и строка поставщика осталась бы в чужом файле (поздний взгляд на
    #1487, `a4c2cc0`).
    """
    root = tree(tmp_path / "наше", tagged="v2.5.0", **{"step-пример": MARKED})
    consumer = tmp_path / "потребитель"
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_OK
    laid = [one for one in walk_deep(consumer) if one.is_file()]
    # Подпись судится местом, а не упоминанием идентификатора (`e776e88`).
    signed = {
        one.relative_to(consumer): module.is_signed(one, one.read_text(encoding="utf-8"))
        for one in laid
    }
    unsigned = [
        str(path) for path, said in signed.items() if not said and not module.of_the_project(path)
    ]
    assert not unsigned, f"положено без строки лицензии: {unsigned}"
    projects = [str(path) for path, said in signed.items() if said and module.of_the_project(path)]
    assert not projects, f"файл проекта подписан строкой поставщика: {projects}"
    assert any(module.of_the_project(path) for path in signed), (
        "тонкий ci.yml не положен — судить нечего"
    )


def test_an_update_lays_the_missing_ci_as_the_projects_file(tmp_path: Path) -> None:
    """Обновление, положившее недостающий `ci.yml`, кладёт его без строки поставщика (`49976c1`)."""
    root, consumer = connected(tmp_path)
    ci = consumer / ".github" / "workflows" / "ci.yml"
    ci.unlink()
    released(root, "v2.6.0", план=OWN_CALLER_NEXT)
    assert module.main(["--root", str(root), "--update", str(consumer)]) == module.EXIT_OK
    laid = ci.read_text("utf-8")
    assert "step-пример.yml@v2.6.0" in laid and module.LICENSE_ID not in laid, laid


def test_a_kit_that_cannot_carry_the_license_stops_the_write_before_any_file(
    tmp_path: Path,
) -> None:
    """Отказ подписи — исход «не отработал» до первой записи, а не трасса и не половина (039)."""
    root = tree(tmp_path / "наше", tagged="v2.5.0", **{"step-пример": MARKED})
    (root / module.DATA_KIT / module.paths.REVIEW_ROLES).write_text("[1]\n", encoding="utf-8")
    consumer = tmp_path / "потребитель"
    assert module.main(["--root", str(root), "--write", str(consumer)]) == module.EXIT_BROKEN
    assert not consumer.exists() or not any(consumer.iterdir()), "положено до отказа"


def test_an_update_leaves_the_projects_own_ci_unsigned(tmp_path: Path) -> None:
    """Смешанный `ci.yml` — файл проекта: подъём тега не ставит в него строку лицензии.

    Взгляд на #1487: `plan_ci` кладёт в план записи свой же файл потребителя с
    поднятым тегом, и `lay` подписывал его как заготовку. Целиком наш файл рядом
    подписывается по-прежнему.
    """
    root, consumer = connected(tmp_path)
    flows = consumer / ".github" / "workflows"
    ci = flows / "ci.yml"
    # Настоящий путь «кладка → свои джобы → обновление» (`09942b2`): положенный
    # `ci.yml` строки лицензии не несёт, и вырезать из него нечего.
    laid = ci.read_text("utf-8")
    assert not module.is_signed(ci, laid) and module.LICENSE_ID not in laid, laid
    own = laid.replace(
        "jobs:\n",
        "jobs:\n  свой:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo свой\n",
        1,
    )
    ci.write_text(own, encoding="utf-8")
    released(root, "v2.6.0", план=OWN_CALLER_NEXT)
    assert module.main(["--root", str(root), "--update", str(consumer)]) == module.EXIT_OK
    lifted = ci.read_text("utf-8")
    assert "step-пример.yml@v2.6.0" in lifted and "echo свой" in lifted, lifted
    assert module.LICENSE_ID not in lifted, lifted
    assert module.is_signed(flows / "план.yml", (flows / "план.yml").read_text("utf-8"))


def test_every_whole_file_the_print_shows_carries_the_license(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Печать без ключей — второй путь заготовки: целый файл подписан, джобы вызова — нет.

    Взгляд на #1487: напечатанное копируют в чужое дерево так же, как положенное
    `lay`. Джобы вызова — строки в СВОЙ `ci.yml` потребителя, и строки
    поставщика в них нет, как и в смешанном `ci.yml` при обновлении.
    """
    root = tree(
        tmp_path / "наше",
        **{"step-пример": MARKED, "step-план": MANAGED, "план": OWN_CALLER},
    )
    assert module.main(["--root", str(root)]) == module.EXIT_OK
    out = capsys.readouterr().out
    # Целые файлы: свой прогон механизма, ответ, сводный гейт и свод окна.
    whole = 3 + len(module.rulebook_kit(root))
    # Подпись — строка в начале файла, а не упоминание (`e776e88`).
    forms = tuple(
        form.split("{line}", 1)[0] + module.LICENSE_ID for form in module.LICENSE_FORMS.values()
    )
    assert sum(line.startswith(forms) for line in out.splitlines()) == whole, out
    jobs = out.split("jobs:\n", 1)[1].split("\n# ", 1)[0]
    assert "step-пример" in jobs and module.LICENSE_ID not in jobs, jobs


def test_signed_all_signs_every_kit_or_refuses_the_whole() -> None:
    """Подпись идёт пачкой: подписаны все, а одна неподписываемая — отказ всей пачки."""
    files = {Path("a.yml"): "x\n", Path("b.md"): "y\n"}
    signed = module.signed_all(files, "o/r")
    assert set(signed) == set(files)
    # Подпись — место, а не упоминание (тот же род, что `e776e88`).
    assert all(module.is_signed(path, text) for path, text in signed.items()), signed
    with pytest.raises(module.NotRun, match="лицензии"):
        module.signed_all({**files, Path("c.toml"): "z\n"}, "o/r")
