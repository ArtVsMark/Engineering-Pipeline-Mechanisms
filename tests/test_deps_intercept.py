"""Перехват подъёма: Dependabot — датчик, конвейер — исполнитель (#1387).

Сеть и толчок здесь подделаны: набор держит разбор сигнала, подъём строк по
дереву и исходы захода, а не площадку.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script, walk

module = load_script("deps_intercept.py")

SHA_OLD = "3d3c42e5aac5ba805825da76410c181273ba90b1"
SHA_NEW = "a" * 40
#: Адрес шагов своей семьи — длинный, поэтому собран один раз.
OWN = "ArtVsMark/Engineering-Pipeline-Mechanisms/.github/workflows"


@pytest.mark.parametrize(
    ("title", "dep", "new"),
    [
        ("Bump actions/checkout from 7.0.1 to 7.1.0", "actions/checkout", "7.1.0"),
        ("Bump github/codeql-action/init from 3 to 4", "github/codeql-action", "4"),
        (
            "Bump ArtVsMark/Engineering-Pipeline-Mechanisms from 1.5.0 to 1.6.0",
            "ArtVsMark/Engineering-Pipeline-Mechanisms",
            "1.6.0",
        ),
    ],
    ids=["пин-по-sha", "действие-с-путём", "своя-семья"],
)
def test_the_signal_is_read_from_the_title_only(title: str, dep: str, new: str) -> None:
    """Из изменения бота берётся одно: что и до какой версии — по заголовку."""
    bump = module.parse({"number": 7, "title": title})
    assert (bump.number, bump.dep, bump.new) == (7, dep, new)


@pytest.mark.parametrize(
    "title",
    [
        "Bump the actions group with 3 updates",
        "Bump actions/checkout from 7.0.1 to main",
        "Обновить всё",
        "",
    ],
    ids=["группа", "не-версия", "чужая-форма", "пусто"],
)
def test_a_signal_of_another_form_is_refused_by_name(title: str) -> None:
    """Иная форма заголовка — отказ с причиной: угадывать подъём нельзя."""
    with pytest.raises(module.Refused):
        module.parse({"number": 7, "title": title})


@pytest.mark.parametrize(
    ("line", "bumped"),
    [
        (
            f"      - uses: actions/checkout@{SHA_OLD} # v7.0.1",
            f"      - uses: actions/checkout@{SHA_NEW} # v7.1.0",
        ),
        (
            f"    uses: {OWN}/step-lint.yml@v1.5.0",
            f"    uses: {OWN}/step-lint.yml@v7.1.0",
        ),
        (
            f"    uses: {OWN}/step-review.yml@main",
            f"    uses: {OWN}/step-review.yml@main",
        ),
        (
            f"      - uses: actions/checkout-extra@{SHA_OLD} # v1",
            f"      - uses: actions/checkout-extra@{SHA_OLD} # v1",
        ),
    ],
    ids=["пин-по-sha", "пин-по-тегу", "общая-ветка-не-трогается", "соседнее-имя"],
)
def test_a_line_is_bumped_in_its_own_form(line: str, bumped: str) -> None:
    """Пин по sha получает sha и комментарий, пин по тегу — тег; `@main` и сосед не тронуты."""
    dep = "ArtVsMark/Engineering-Pipeline-Mechanisms" if "ArtVsMark" in line else "actions/checkout"
    assert module.bump_line(line, dep, "v7.1.0", SHA_NEW) == bumped


def test_a_catalogue_origin_follows_the_call() -> None:
    """У действий каталога тег поднимается и в `origin` ответа — их сверяет набор."""
    text = (
        '"origin": "ArtVsMark/Engineering-Incidents-Playbook:'
        '.github/actions/answer/action.yml@v1.13.0",\n'
        '"origin": "ArtVsMark/Other:.github/x/action.yml@v1.13.0",'
    )
    after = module.bump_origins(text, "ArtVsMark/Engineering-Incidents-Playbook", "v1.14.0")
    assert "answer/action.yml@v1.14.0" in after
    assert "Other:.github/x/action.yml@v1.13.0" in after


def test_the_whole_tree_is_bumped_at_once() -> None:
    """Подъём берёт ВСЕ строки действия: половинный покрасил бы «одну версию на дерево»."""
    planned = module.plan(ROOT, "actions/checkout", "v7.1.0", SHA_NEW)
    total = sum(
        path.read_text(encoding="utf-8").count("uses: actions/checkout@")
        for path in walk(ROOT / module.WORKFLOWS, "*.yml")
    )
    assert total, "строк checkout в дереве нет — предмет проверки не найден (075)"
    bumped = sum(text.count(f"actions/checkout@{SHA_NEW} # v7.1.0") for text in planned.values())
    assert bumped == total


def test_the_catalogue_bump_carries_its_answers() -> None:
    """Подъём каталога в том же плане правит `.rules/bindings.json`."""
    planned = module.plan(ROOT, "ArtVsMark/Engineering-Incidents-Playbook", "v9.9.9", SHA_NEW)
    assert module.paths.BINDINGS in planned
    assert "@v9.9.9" in planned[module.paths.BINDINGS]


def test_the_branch_is_named_by_its_subject() -> None:
    """Ветка — по предмету и с приставкой `agent/`: её изменение откроет конвейер (003)."""
    assert module.branch_of("ArtVsMark/Engineering-Pipeline-Mechanisms", "v1.6.0") == (
        "agent/deps-artvsmark-engineering-pipeline-mechanisms-v1.6.0"
    )


def test_the_co_author_is_declared() -> None:
    """Подпись механизма объявлена в списке авторов: иначе `attribution` отвергнет коммит."""
    assert module.CO_AUTHOR in (ROOT / module.paths.AUTHORS).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("answers", "tag"),
    [
        ([{"sha": SHA_NEW}], "v7.1.0"),
        ([module.ghrest.NotFound("нет"), {"sha": SHA_NEW}], "7.1.0"),
    ],
    ids=["тег-с-v", "тег-без-v"],
)
def test_the_tag_is_asked_with_and_without_v(
    monkeypatch: pytest.MonkeyPatch, answers: list[Any], tag: str
) -> None:
    """Тег ищется в обеих формах: бот пишет версию без `v`, а тег её может нести."""

    def ask(method: str, path: str, token: str, body: Any = None) -> Any:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(module.ghrest, "request", ask)
    assert module.resolve("actions/checkout", "7.1.0", "t") == (tag, SHA_NEW)


def test_a_missing_tag_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тега нет ни в одной форме — отказ с причиной, а не подъём на пустоту."""

    def missing(*_: object, **__: object) -> None:
        raise module.ghrest.NotFound("нет")

    monkeypatch.setattr(module.ghrest, "request", missing)
    with pytest.raises(module.Refused):
        module.resolve("actions/checkout", "7.1.0", "t")


def test_a_silent_platform_is_not_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка не ответила — «не отработал», а не «тега нет»: это разные починки (154)."""

    def silent(*_: object, **__: object) -> None:
        raise module.ghrest.TransportError("сети нет")

    monkeypatch.setattr(module.ghrest, "request", silent)
    with pytest.raises(module.NotRun):
        module.resolve("actions/checkout", "7.1.0", "t")


def test_the_message_and_fragment_carry_the_signal() -> None:
    """Коммит несёт связь и подпись механизма, фрагмент — номер сигнала."""
    said = module.message("actions/checkout", "v7.1.0", 41)
    assert module.REFS in said and f"Co-Authored-By: {module.CO_AUTHOR}" in said and "#41" in said
    assert "#41" in module.fragment("actions/checkout", "v7.1.0", 41)


def git(cwd: Path, *args: str) -> str:
    """git в подготовленном дереве теста."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


@pytest.fixture
def stand(tmp_path: Path) -> Path:
    """Пара «площадка — клон»: голый репозиторий и рабочее дерево с одним прогоном."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(remote))
    work = tmp_path / "work"
    git(tmp_path, "clone", "--quiet", str(remote), str(work))
    git(work, "config", "user.email", "t@example.invalid")
    git(work, "config", "user.name", "t")
    flows = work / module.paths.WORKFLOWS
    flows.mkdir(parents=True)
    (flows / "ci.yml").write_text(
        f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{SHA_OLD} # v7.0.1\n",
        encoding="utf-8",
    )
    (work / module.paths.FRAGMENTS).mkdir()
    git(work, "add", "-A")
    git(work, "commit", "--quiet", "-m", "база")
    git(work, "push", "--quiet", "origin", "HEAD:main")
    return work


def fake_platform(monkeypatch: pytest.MonkeyPatch, said: list[tuple[str, str]]) -> None:
    """Площадка: тег находится сразу, запись — в `said`."""

    def ask(method: str, path: str, token: str, body: Any = None) -> Any:
        if method == "GET":
            return {"sha": SHA_NEW}
        said.append((method, path))
        return {}

    monkeypatch.setattr(module.ghrest, "request", ask)


def test_an_intercept_pushes_our_branch_and_closes_the_signal(
    stand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Заход целиком: ветка `agent/` на площадке с подъёмом и фрагментом, сигнал закрыт."""
    said: list[tuple[str, str]] = []
    fake_platform(monkeypatch, said)
    bump = module.Bump(41, "actions/checkout", "7.0.1", "7.1.0")
    branch = module.intercept(stand, "o/r", "t", bump, dry_run=False)
    tree = git(stand, "show", f"origin/{branch}:.github/workflows/ci.yml")
    assert f"actions/checkout@{SHA_NEW} # v7.1.0" in tree
    files = git(stand, "show", "--name-only", "-z", "--format=", f"origin/{branch}").split("\0")
    assert "changelog.d/deps-actions-checkout-v7.1.0.changed.md" in files
    assert ("PATCH", "repos/o/r/pulls/41") in said


def test_a_repeated_intercept_does_not_bump_twice(
    stand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ветка уже на площадке — подъём не повторяется, сигнал только закрывается."""
    said: list[tuple[str, str]] = []
    fake_platform(monkeypatch, said)
    bump = module.Bump(41, "actions/checkout", "7.0.1", "7.1.0")
    branch = module.intercept(stand, "o/r", "t", bump, dry_run=False)
    before = git(stand, "rev-parse", f"origin/{branch}")
    module.intercept(stand, "o/r", "t", bump, dry_run=False)
    git(stand, "fetch", "--quiet", "origin")
    assert git(stand, "rev-parse", f"origin/{branch}") == before


def test_a_dry_run_touches_nothing(stand: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Сухой заход не переключает ветку, не пишет файлов и не закрывает сигнал."""
    said: list[tuple[str, str]] = []
    fake_platform(monkeypatch, said)
    bump = module.Bump(41, "actions/checkout", "7.0.1", "7.1.0")
    module.intercept(stand, "o/r", "t", bump, dry_run=True)
    assert git(stand, "status", "--porcelain") == ""
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert said == []


def test_a_bump_with_nothing_to_lift_is_refused(
    stand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Действия в дереве нет — отказ с причиной, сигнал остаётся открытым для человека."""
    said: list[tuple[str, str]] = []
    fake_platform(monkeypatch, said)
    with pytest.raises(module.Refused):
        module.intercept(stand, "o/r", "t", module.Bump(41, "x/y", "1", "2"), dry_run=False)
    assert said == []


def run_main(monkeypatch: pytest.MonkeyPatch, changes: list[dict[str, Any]]) -> int:
    """Заход `main` на подделанной площадке: открытые изменения — `changes`."""
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, token, **_: iter(changes))
    monkeypatch.setattr(module, "intercept", lambda *a, **k: "agent/x")
    monkeypatch.setattr(module, "git", lambda *a, **k: "")
    return int(module.main(["--repo", "o/r"]))


def test_main_with_no_signal_is_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сигналов бота нет — чисто; чужие изменения не трогаются."""
    human = {"number": 3, "title": "Bump x/y from 1 to 2", "user": {"login": "someone"}}
    assert run_main(monkeypatch, [human]) == module.EXIT_OK


def test_main_names_an_unreadable_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сигнал не той формы — находка для человека, исход 1."""
    group = {"number": 4, "title": "Bump the group", "user": {"login": module.BOT}}
    assert run_main(monkeypatch, [group]) == module.EXIT_FOUND


def test_main_without_a_token_does_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Токена нет — «не отработал», а не «чисто»."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert module.main(["--repo", "o/r"]) == module.EXIT_BROKEN


@pytest.mark.parametrize(
    ("text", "said"),
    [("ArtVsMark/Engineering", "artvsmark-engineering"), ("v1.6.0", "v1.6.0"), ("A__b", "a-b")],
    ids=["владелец-и-имя", "тег", "склейка"],
)
def test_slug_keeps_only_safe_marks(text: str, said: str) -> None:
    """Часть имени ветки — строчные буквы, цифры, точки и дефисы."""
    assert module.slug(text) == said


def test_uses_re_takes_the_action_and_not_its_neighbour() -> None:
    """Образец строки берёт само действие с путём, но не соседа с общим началом имени."""
    pattern = module.uses_re("actions/checkout")
    assert pattern.search(f"- uses: actions/checkout@{SHA_OLD} # v7.0.1")
    assert pattern.search(f'- uses: "actions/checkout/sub@{SHA_OLD}"')
    assert not pattern.search(f"- uses: actions/checkout-extra@{SHA_OLD}")


def test_bump_text_lifts_every_line_and_keeps_the_rest() -> None:
    """Весь файл: каждая строка действия поднята, прочие строки — как были."""
    text = f"a: 1\n- uses: actions/checkout@{SHA_OLD} # v7.0.1\nb: 2\n- uses: actions/checkout@v7"
    after = module.bump_text(text, "actions/checkout", "v7.1.0", SHA_NEW)
    assert after.split("\n") == [
        "a: 1",
        f"- uses: actions/checkout@{SHA_NEW} # v7.1.0",
        "b: 2",
        "- uses: actions/checkout@v7.1.0",
    ]


def test_signals_are_only_the_bot_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сигнал — только изменение бота; изменение человека с тем же заголовком им не считается."""
    changes = [
        {"number": 1, "user": {"login": module.BOT}},
        {"number": 2, "user": {"login": "ArtVsMark"}},
        {"number": 3},
    ]
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, token, **_: iter(changes))
    assert [one["number"] for one in module.signals("o/r", "t")] == [1]


@pytest.mark.parametrize(("rc", "red"), [(0, False), (1, True), (2, True)])
def test_an_unresolved_signal_reddens_the_run(rc: int, red: bool) -> None:
    """Исход «сигнал не разобран» краснит прогон: так обещает `.pipeline.yml` дежурному.

    Зелёный прогон с предупреждением прятал сигнал в списке прогонов (находка
    `22ae144` на #1397). Разбор кодов шага ИСПОЛНЯЕТСЯ оболочкой, а не ищется
    подстрокой: `# exit 1` в комментарии или слово в `echo` текстовую проверку
    обходили (находка взгляда на #1417). Обе стороны: ноль — зелёный, прочее —
    красный с ошибкой.
    """
    run = (ROOT / ".github" / "workflows" / "deps-intercept.yml").read_text(encoding="utf-8")
    start = run.index('          case "$rc" in')
    block = run[start : run.index("esac", start) + len("esac")]
    done = subprocess.run(
        ["bash", "-c", f"set -uo pipefail\nrc={rc}\nreason=x\n{block}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert (done.returncode != 0) == red, (rc, done.returncode, done.stdout)
    assert ("::error::" in done.stdout) == red, done.stdout


# --- подъём своих шагов после выпуска (#1387) ---------------------------------


def with_own_calls(work: Path) -> None:
    """Проба зовёт свои шаги по тегу, взгляд — по общей ветке; выпуск помечен тегом."""
    probe = work / module.paths.WORKFLOWS / "handover-probe.yml"
    probe.write_text(
        "jobs:\n"
        "  probe-lint:\n    uses: o/r/.github/workflows/step-lint.yml@v1.0.0\n"
        "  probe-debt:\n    uses: o/r/.github/workflows/step-debt.yml@v1.0.0\n"
        "  review:\n    uses: o/r/.github/workflows/step-review.yml@main\n",
        encoding="utf-8",
    )
    git(work, "add", "-A")
    git(work, "commit", "--quiet", "-m", "проба")
    git(work, "push", "--quiet", "origin", "HEAD:main")
    git(work, "tag", "v2.0.0")


def test_a_release_lifts_its_own_steps_in_one_branch(stand: Path) -> None:
    """Выпуск поднимает все свои вызовы по тегу разом; `@main` — не версия и не трогается."""
    with_own_calls(stand)
    branch = module.self_bump(stand, "o/r", "v2.0.0", dry_run=False)
    assert branch == "agent/deps-self-v2.0.0"
    tree = git(stand, "show", f"origin/{branch}:.github/workflows/handover-probe.yml")
    assert tree.count("@v2.0.0") == 2 and "@v1.0.0" not in tree
    assert "step-review.yml@main" in tree
    files = git(stand, "show", "--name-only", "-z", "--format=", f"origin/{branch}").split("\0")
    assert "changelog.d/deps-self-v2.0.0.internal.md" in files


def test_a_consumer_release_has_nothing_of_its_own_to_lift(stand: Path) -> None:
    """У потребителя своих шагов по тегу нет — пустота законна, ветки нет, выпуск не краснеет."""
    git(stand, "tag", "v2.0.0")
    assert module.self_bump(stand, "o/r", "v2.0.0", dry_run=False) == ""
    assert git(stand, "ls-remote", "--heads", "origin", "agent/deps-self-v2.0.0") == ""
    assert module.main(["--root", str(stand), "--repo", "o/r", "--self", "v2.0.0"]) == 0


def test_a_repeated_release_lift_does_not_push_twice(stand: Path) -> None:
    """Ветка подъёма уже на площадке — повтор выпуска её не перезаписывает."""
    with_own_calls(stand)
    branch = module.self_bump(stand, "o/r", "v2.0.0", dry_run=False)
    before = git(stand, "rev-parse", f"origin/{branch}")
    module.self_bump(stand, "o/r", "v2.0.0", dry_run=False)
    git(stand, "fetch", "--quiet", "origin")
    assert git(stand, "rev-parse", f"origin/{branch}") == before


def test_a_dry_release_lift_touches_nothing(stand: Path) -> None:
    """Сухой подъём называет ветку и не пишет ни файла, ни ветки."""
    with_own_calls(stand)
    assert module.self_bump(stand, "o/r", "v2.0.0", dry_run=True) == "agent/deps-self-v2.0.0"
    assert git(stand, "status", "--porcelain") == ""
    assert git(stand, "ls-remote", "--heads", "origin", "agent/deps-self-v2.0.0") == ""


def test_the_self_fragment_says_why_it_does_not_matter_to_the_consumer() -> None:
    """Фрагмент — `internal` с причиной первой строкой, тронутым по плану и адресом последней."""
    text = module.self_fragment("v2.0.0", [Path(".github/workflows/handover-probe.yml")])
    assert text.startswith("> **Потребителю безразлично:**")
    assert "`.github/workflows/handover-probe.yml`" in text
    assert text.rstrip().endswith("#1387")


def test_the_fragment_names_what_the_plan_touched(stand: Path) -> None:
    """Фрагмент называет файлы, которые поднял план, а не пробу буквами (взгляд на #1421)."""
    with_own_calls(stand)
    other = stand / module.paths.WORKFLOWS / "other.yml"
    other.write_text("jobs:\n  x:\n    uses: o/r/.github/workflows/step-x.yml@v1.0.0\n")
    git(stand, "add", "-A")
    git(stand, "commit", "--quiet", "-m", "второй")
    git(stand, "push", "--quiet", "origin", "HEAD:main")
    git(stand, "tag", "-f", "v2.0.0")
    branch = module.self_bump(stand, "o/r", "v2.0.0", dry_run=False)
    note = git(stand, "show", f"origin/{branch}:changelog.d/deps-self-v2.0.0.internal.md")
    assert "`.github/workflows/other.yml`" in note and "handover-probe.yml" in note


def test_a_dirty_tree_is_not_switched(stand: Path) -> None:
    """Незакоммиченная правка — отказ, а не молчаливый снос веткой (взгляд на #1421)."""
    with_own_calls(stand)
    (stand / "wip.txt").write_text("не сохранено", encoding="utf-8")
    with pytest.raises(module.NotRun, match="незакоммиченные"):
        module.self_bump(stand, "o/r", "v2.0.0", dry_run=False)
    assert (stand / "wip.txt").read_text(encoding="utf-8") == "не сохранено"
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


def test_an_intercept_does_not_wipe_a_dirty_tree(
    stand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Перехват с правками в дереве — отказ, а не снос веткой (`7f52cb1`)."""
    fake_platform(monkeypatch, [])
    (stand / "wip.txt").write_text("не сохранено", encoding="utf-8")
    bump = module.Bump(41, "actions/checkout", "7.0.1", "7.1.0")
    with pytest.raises(module.NotRun, match="незакоммиченные"):
        module.intercept(stand, "o/r", "t", bump, dry_run=False)
    assert (stand / "wip.txt").read_text(encoding="utf-8") == "не сохранено"
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


def test_switch_clean_cuts_from_the_trunk_on_a_clean_tree(stand: Path) -> None:
    """Чистое дерево — ветка режется от общей; правка в дереве — отказ."""
    module.switch_clean(stand, "agent/x")
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "agent/x"
    (stand / "wip.txt").write_text("своё", encoding="utf-8")
    with pytest.raises(module.NotRun, match="незакоммиченные"):
        module.switch_clean(stand, "agent/y")


def test_a_consumer_branch_is_not_switched(stand: Path) -> None:
    """Поднимать нечего — ветка человека не переключается (взгляд на #1421)."""
    git(stand, "tag", "v2.0.0")
    (stand / "wip.txt").write_text("своё", encoding="utf-8")
    assert module.self_bump(stand, "o/r", "v2.0.0", dry_run=False) == ""
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert (stand / "wip.txt").exists()


def test_calls_itself_reads_the_trunk_not_the_worktree(stand: Path) -> None:
    """Вопрос «зовём ли себя» задаётся общей ветке: правка в рабочем дереве ответа не меняет."""
    assert not module.calls_itself(stand, "o/r")
    with_own_calls(stand)
    git(stand, "fetch", "--quiet", "origin")
    assert module.calls_itself(stand, "o/r")
    assert not module.calls_itself(stand, "chuzhoj/repo")
