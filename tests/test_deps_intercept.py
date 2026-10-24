"""Перехват подъёма: Dependabot — датчик, конвейер — исполнитель (#1387).

Сеть и толчок здесь подделаны: набор держит разбор сигнала, подъём строк по
дереву и исходы захода, а не площадку.
"""

import json
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
    """Коммит несёт связь с планом и подпись механизма, фрагмент — сигнал и план."""
    said = module.message("actions/checkout", "v7.1.0", 41, 7)
    assert "Refs #7" in said and f"Co-Authored-By: {module.CO_AUTHOR}" in said and "#41" in said
    note = module.fragment("actions/checkout", "v7.1.0", 41, 7)
    assert "#41" in note and note.rstrip().splitlines()[-1] == "#7"


def test_the_intercept_names_no_task_of_ours() -> None:
    """Номер нашей задачи в тексте перехвата у потребителя назвал бы его чужую задачу (#1387)."""
    said = module.message("a/b", "v1", 41, 7) + module.fragment("a/b", "v1", 41, 7)
    assert "#1387" not in said and "#639" not in said


@pytest.mark.parametrize(
    ("found", "number"),
    [((7, "тело"), 7), ((None, ""), None)],
    ids=["план-есть", "плана-нет"],
)
def test_the_plan_is_found_by_its_marker(
    monkeypatch: pytest.MonkeyPatch, found: tuple[int | None, str], number: int | None
) -> None:
    """План — по маркеру сборщика плана; плана нет — «не отработал», а не подъём без связи."""
    asked: list[str] = []

    def live(repo: str, token: str, marker: str) -> tuple[int | None, str]:
        asked.append(marker)
        return found

    monkeypatch.setattr(module.findings, "live_issue", live)
    if number is None:
        with pytest.raises(module.NotRun, match="плана работ нет"):
            module.plan_number("o/r", "t")
    else:
        assert module.plan_number("o/r", "t") == number
    assert asked == [module.findings.PLAN_MARKER]


def test_an_unread_plan_does_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка не отдала список задач — «не отработал» с причиной (039)."""

    def silent(*_: object, **__: object) -> None:
        raise module.ghrest.TransportError("сети нет")

    monkeypatch.setattr(module.findings, "live_issue", silent)
    with pytest.raises(module.NotRun, match="не прочитан"):
        module.plan_number("o/r", "t")


@pytest.mark.parametrize(
    ("said", "who"),
    [
        ({"login": "Owner", "id": 5}, ("Owner", "5+Owner@users.noreply.github.com")),
        ({"login": "", "id": 5}, None),
        ({"login": "Owner"}, None),
        (module.ghrest.TransportError("сети нет"), None),
    ],
    ids=["владелец", "без-имени", "без-номера", "площадка-молчит"],
)
def test_the_author_is_the_owner_of_the_token(
    monkeypatch: pytest.MonkeyPatch, said: Any, who: tuple[str, str] | None
) -> None:
    """Подпись — владельца токена, спрошенного у площадки; не назван — «не отработал» (131)."""

    def ask(method: str, path: str, token: str, body: Any = None) -> Any:
        assert (method, path) == ("GET", "user")
        if isinstance(said, Exception):
            raise said
        return said

    monkeypatch.setattr(module.ghrest, "request", ask)
    if who is None:
        with pytest.raises(module.NotRun):
            module.identity("t")
    else:
        assert module.identity("t") == who


def git(cwd: Path, *args: str) -> str:
    """git в подготовленном дереве теста."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


#: Подпись коммита подъёма в сквозных заходах — владелец токена, как его назвала бы площадка.
WHO = ("Owner", "5+Owner@users.noreply.github.com")


@pytest.fixture
def stand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Пара «площадка — клон»: голый репозиторий и рабочее дерево с одним прогоном.

    План работ у стенда — #7: его поиск по маркеру держат свои тесты, а здесь
    он подставлен, как и токен, которым его спросили бы.
    """
    monkeypatch.setattr(module, "plan_number", lambda repo, token: 7)
    monkeypatch.setenv("GH_TOKEN", "t")
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
    branch = module.intercept(stand, "o/r", "t", bump, dry_run=False, plan_issue=7, who=WHO)
    tree = git(stand, "show", f"origin/{branch}:.github/workflows/ci.yml")
    assert f"actions/checkout@{SHA_NEW} # v7.1.0" in tree
    files = git(stand, "show", "--name-only", "-z", "--format=", f"origin/{branch}").split("\0")
    assert "changelog.d/deps-actions-checkout-v7.1.0.changed.md" in files
    assert ("PATCH", "repos/o/r/pulls/41") in said
    author = git(stand, "log", "-1", "--format=%an <%ae>", f"origin/{branch}").strip()
    assert author == f"{WHO[0]} <{WHO[1]}>"
    assert "Refs #7" in git(stand, "log", "-1", "--format=%B", f"origin/{branch}")


def test_an_intercept_without_its_author_does_not_write(
    stand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Заход с записью без подписи владельца — отказ до записи, а не коммит от окружения (131)."""
    said: list[tuple[str, str]] = []
    fake_platform(monkeypatch, said)
    bump = module.Bump(41, "actions/checkout", "7.0.1", "7.1.0")
    with pytest.raises(module.NotRun, match="подписи"):
        module.intercept(stand, "o/r", "t", bump, dry_run=False, plan_issue=7)
    assert git(stand, "status", "--porcelain") == "" and said == []


def test_a_repeated_intercept_does_not_bump_twice(
    stand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ветка уже на площадке — подъём не повторяется, сигнал только закрывается."""
    said: list[tuple[str, str]] = []
    fake_platform(monkeypatch, said)
    bump = module.Bump(41, "actions/checkout", "7.0.1", "7.1.0")
    branch = module.intercept(stand, "o/r", "t", bump, dry_run=False, plan_issue=7, who=WHO)
    before = git(stand, "rev-parse", f"origin/{branch}")
    module.intercept(stand, "o/r", "t", bump, dry_run=False, plan_issue=7, who=WHO)
    git(stand, "fetch", "--quiet", "origin")
    assert git(stand, "rev-parse", f"origin/{branch}") == before


def test_a_dry_run_touches_nothing(stand: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Сухой заход не переключает ветку, не пишет файлов и не закрывает сигнал."""
    said: list[tuple[str, str]] = []
    fake_platform(monkeypatch, said)
    bump = module.Bump(41, "actions/checkout", "7.0.1", "7.1.0")
    module.intercept(stand, "o/r", "t", bump, dry_run=True, plan_issue=7)
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
        module.intercept(
            stand,
            "o/r",
            "t",
            module.Bump(41, "x/y", "1", "2"),
            dry_run=False,
            plan_issue=7,
            who=WHO,
        )
    assert said == []


def run_main(
    monkeypatch: pytest.MonkeyPatch, changes: list[dict[str, Any]], asked: list[str] | None = None
) -> int:
    """Заход `main` на подделанной площадке: открытые изменения — `changes`."""
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, token, **_: iter(changes))
    monkeypatch.setattr(module, "intercept", lambda *a, **k: "agent/x")

    def plan(repo: str, token: str) -> int:
        (asked if asked is not None else []).append(repo)
        return 7

    monkeypatch.setattr(module, "plan_number", plan)
    monkeypatch.setattr(module, "git", lambda *a, **k: "")
    return int(module.main(["--repo", "o/r"]))


def test_main_with_no_signal_is_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сигналов бота нет — чисто; чужие изменения не трогаются, план не спрашивается."""
    human = {"number": 3, "title": "Bump x/y from 1 to 2", "user": {"login": "someone"}}
    asked: list[str] = []
    assert run_main(monkeypatch, [human], asked) == module.EXIT_OK
    assert asked == []


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
    run = (ROOT / ".github" / "workflows" / "step-deps-intercept.yml").read_text(encoding="utf-8")
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
    # Цвет у кодов 1 и 2 один, и различает их ТОЛЬКО текст (предел 195 в шаге):
    # слитые в одну ветку `case` с одним текстом прошли бы проверку цвета
    # (взгляд на #1417).
    told = {0: "", 1: "не разобран", 2: "не отработал"}[rc]
    assert told in done.stdout, done.stdout
    assert {1: "не отработал", 2: "не разобран"}.get(rc, "—") not in done.stdout, done.stdout


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
    branch = module.self_bump(stand, "o/r", "v2.0.0", dry_run=False, token="t")
    assert branch == "agent/deps-self-v2.0.0"
    tree = git(stand, "show", f"origin/{branch}:.github/workflows/handover-probe.yml")
    assert tree.count("@v2.0.0") == 2 and "@v1.0.0" not in tree
    assert "step-review.yml@main" in tree
    files = git(stand, "show", "--name-only", "-z", "--format=", f"origin/{branch}").split("\0")
    assert "changelog.d/deps-self-v2.0.0.internal.md" in files


def test_a_consumer_release_has_nothing_of_its_own_to_lift(stand: Path) -> None:
    """У потребителя своих шагов по тегу нет — пустота законна, ветки нет, выпуск не краснеет."""
    git(stand, "tag", "v2.0.0")
    # Без токена: потребителю поднимать нечего, и плана у него спрашивать незачем.
    assert module.self_bump(stand, "o/r", "v2.0.0", dry_run=False) == ""
    assert git(stand, "ls-remote", "--heads", "origin", "agent/deps-self-v2.0.0") == ""
    assert module.main(["--root", str(stand), "--repo", "o/r", "--self", "v2.0.0"]) == 0


def test_a_release_lift_without_a_token_refuses_before_the_switch(stand: Path) -> None:
    """Поднимать есть что, а токена нет — отказ до смены ветки: план спросить нечем."""
    with_own_calls(stand)
    with pytest.raises(module.NotRun, match="токена нет"):
        module.self_bump(stand, "o/r", "v2.0.0", dry_run=False)
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert git(stand, "ls-remote", "--heads", "origin", "agent/deps-self-v2.0.0") == ""


def test_a_release_lift_is_tied_to_the_plan(stand: Path) -> None:
    """Коммит и фрагмент подъёма своих шагов ссылаются на план работ, а не на литерал."""
    with_own_calls(stand)
    branch = module.self_bump(stand, "o/r", "v2.0.0", dry_run=False, token="t")
    assert "Refs #7" in git(stand, "log", "-1", "--format=%B", f"origin/{branch}")
    note = git(stand, "show", f"origin/{branch}:changelog.d/deps-self-v2.0.0.internal.md")
    assert note.rstrip().splitlines()[-1] == "#7"


def test_a_repeated_release_lift_does_not_push_twice(stand: Path) -> None:
    """Ветка подъёма уже на площадке — повтор выпуска её не перезаписывает."""
    with_own_calls(stand)
    branch = module.self_bump(stand, "o/r", "v2.0.0", dry_run=False, token="t")
    before = git(stand, "rev-parse", f"origin/{branch}")
    module.self_bump(stand, "o/r", "v2.0.0", dry_run=False, token="t")
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
    text = module.self_fragment("v2.0.0", [Path(".github/workflows/handover-probe.yml")], 7)
    assert text.startswith("> **Потребителю безразлично:**")
    assert "`.github/workflows/handover-probe.yml`" in text
    assert text.rstrip().endswith("#7")


def test_the_fragment_names_what_the_plan_touched(stand: Path) -> None:
    """Фрагмент называет файлы, которые поднял план, а не пробу буквами (взгляд на #1421)."""
    with_own_calls(stand)
    other = stand / module.paths.WORKFLOWS / "other.yml"
    other.write_text("jobs:\n  x:\n    uses: o/r/.github/workflows/step-x.yml@v1.0.0\n")
    git(stand, "add", "-A")
    git(stand, "commit", "--quiet", "-m", "второй")
    git(stand, "push", "--quiet", "origin", "HEAD:main")
    git(stand, "tag", "-f", "v2.0.0")
    branch = module.self_bump(stand, "o/r", "v2.0.0", dry_run=False, token="t")
    note = git(stand, "show", f"origin/{branch}:changelog.d/deps-self-v2.0.0.internal.md")
    assert "`.github/workflows/other.yml`" in note and "handover-probe.yml" in note


def test_a_dirty_tree_is_not_switched(stand: Path) -> None:
    """Незакоммиченная правка — отказ, а не молчаливый снос веткой (взгляд на #1421)."""
    with_own_calls(stand)
    (stand / "wip.txt").write_text("не сохранено", encoding="utf-8")
    with pytest.raises(module.NotRun, match="незакоммиченные"):
        module.self_bump(stand, "o/r", "v2.0.0", dry_run=False, token="t")
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
        module.intercept(stand, "o/r", "t", bump, dry_run=False, plan_issue=7, who=WHO)
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
    assert module.self_bump(stand, "o/r", "v2.0.0", dry_run=False, token="t") == ""
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert (stand / "wip.txt").exists()


def test_calls_itself_reads_the_trunk_not_the_worktree(stand: Path) -> None:
    """Вопрос «зовём ли себя» задаётся общей ветке: правка в рабочем дереве ответа не меняет."""
    assert not module.calls_itself(stand, "o/r")
    with_own_calls(stand)
    git(stand, "fetch", "--quiet", "origin")
    assert module.calls_itself(stand, "o/r")
    assert not module.calls_itself(stand, "chuzhoj/repo")


def test_restore_keeps_a_dirty_tree(stand: Path) -> None:
    """Возврат после захода правок не стирает: дерево с правками не трогается (`4885891`)."""
    git(stand, "checkout", "--quiet", "-B", "agent/x")
    tracked = stand / ".github" / "workflows" / "ci.yml"
    tracked.write_text(tracked.read_text("utf-8") + "# своё\n", encoding="utf-8")
    module.restore(stand, f"{module.BRANCH_REF}main")
    assert tracked.read_text("utf-8").endswith("# своё\n")
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "agent/x"
    git(stand, "checkout", "--quiet", "--", ".")
    module.restore(stand, f"{module.BRANCH_REF}main")
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


# --- переключение ветки и возврат (взгляды на #1434 и #1441) -------------------


def test_a_tracked_edit_stops_the_switch(stand: Path) -> None:
    """Правка ОТСЛЕЖИВАЕМОГО файла — отказ, и правка цела (взгляд на #1434).

    Неотслеживаемый файл `checkout -B` не трогает и с `--force`, поэтому проба
    на нём проходила бы и без защиты.
    """
    tracked = stand / ".github" / "workflows" / "ci.yml"
    tracked.write_text(tracked.read_text("utf-8") + "# своё\n", encoding="utf-8")
    with pytest.raises(module.NotRun, match="незакоммиченные"):
        module.switch_clean(stand, "agent/x")
    assert tracked.read_text("utf-8").endswith("# своё\n")
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


def bot_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка с одним сигналом бота: тег находится, запись ничего не делает."""
    signal = {
        "number": 41,
        "title": "Bump actions/checkout from 7.0.1 to 7.1.0",
        "user": {"login": module.BOT},
    }
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, token, **_: iter([signal]))
    fake_platform(monkeypatch, [])
    # План и подпись — свои вопросы к площадке, их держат отдельные тесты.
    monkeypatch.setattr(module, "plan_number", lambda repo, token: 7)
    monkeypatch.setattr(module, "identity", lambda token: WHO)


def test_main_apply_with_a_refused_switch_keeps_the_edits(
    stand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Боевой заход `main` на дереве с правкой: отказ, возврат её не стирает (взгляд на #1441)."""
    bot_signal(monkeypatch)
    tracked = stand / ".github" / "workflows" / "ci.yml"
    tracked.write_text(tracked.read_text("utf-8") + "# своё\n", encoding="utf-8")
    said = module.main(["--root", str(stand), "--repo", "o/r", "--apply"])
    assert said == module.EXIT_BROKEN
    assert tracked.read_text("utf-8").endswith("# своё\n")
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


def test_restore_names_both_owners_of_the_edits(
    stand: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Чьи правки — не угадывается: названы оба случая и ветка (взгляд на #1441)."""
    git(stand, "checkout", "--quiet", "-B", "agent/x")
    (stand / ".github" / "workflows" / "ci.yml").write_text("недописано\n", encoding="utf-8")
    module.restore(stand, f"{module.BRANCH_REF}main")
    out = capsys.readouterr().out
    assert "agent/x" in out and "человека" in out and "недописанный подъём" in out


def test_a_self_bump_returns_the_tree(stand: Path) -> None:
    """Подъём своих шагов возвращает дерево с ветки подъёма, как перехват (взгляд на #1441)."""
    with_own_calls(stand)
    assert module.main(["--root", str(stand), "--repo", "o/r", "--self", "v2.0.0", "--apply"]) == 0
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert git(stand, "status", "--porcelain") == ""


# --- возврат — туда, где застал, и только если сдвинул (взгляд на #1468) ------


def on_own_branch(work: Path) -> None:
    """Человек работает в своей ветке, дерево чистое."""
    git(work, "checkout", "--quiet", "-b", "feature")


def test_a_self_bump_with_nothing_to_lift_keeps_the_branch(stand: Path) -> None:
    """Потребитель себя не зовёт: подъём ветку не трогал — и возврат её не трогает."""
    git(stand, "tag", "v2.0.0")
    on_own_branch(stand)
    assert module.main(["--root", str(stand), "--repo", "o/r", "--self", "v2.0.0", "--apply"]) == 0
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "feature"


def test_a_self_bump_with_its_branch_already_there_keeps_the_branch(stand: Path) -> None:
    """Ветка подъёма уже есть: заход не переключал — человек остаётся в своей ветке."""
    with_own_calls(stand)
    git(stand, "push", "--quiet", "origin", "HEAD:refs/heads/agent/deps-self-v2.0.0")
    on_own_branch(stand)
    assert module.main(["--root", str(stand), "--repo", "o/r", "--self", "v2.0.0", "--apply"]) == 0
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "feature"


def test_an_intercept_with_its_branch_already_there_keeps_the_branch(
    stand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Перехват, чья ветка уже есть, ничего не переключал — и возврат не снимает с ветки."""
    bot_signal(monkeypatch)
    branch = module.branch_of("actions/checkout", "v7.1.0")
    git(stand, "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")
    on_own_branch(stand)
    assert module.main(["--root", str(stand), "--repo", "o/r", "--apply"]) == module.EXIT_OK
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "feature"


def test_a_lift_returns_to_the_branch_it_found(stand: Path) -> None:
    """Сдвинул — возвращает на ветку человека, а не на отвязанную общую."""
    with_own_calls(stand)
    on_own_branch(stand)
    assert module.main(["--root", str(stand), "--repo", "o/r", "--self", "v2.0.0", "--apply"]) == 0
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "feature"
    assert git(stand, "ls-remote", "--heads", "origin", "agent/deps-self-v2.0.0").strip()


def test_restore_returns_a_detached_tree_to_its_commit(stand: Path) -> None:
    """Отвязанное дерево — место по sha: возврат приходит на тот же коммит отвязанным."""
    git(stand, "checkout", "--quiet", "--detach", "HEAD")
    start = module.spot(stand)
    module.switch_clean(stand, "agent/x")
    module.restore(stand, start)
    assert module.spot(stand) == start
    assert git(stand, "rev-parse", "--abbrev-ref", "HEAD").strip() == "HEAD"


def test_a_branch_named_like_a_tag_returns_as_a_branch(stand: Path) -> None:
    """Ветка с одноимённым тегом — место полным именем, возврат на ветку (взгляд на #1474).

    Короткое имя здесь неоднозначно: `--abbrev-ref` отдаёт `heads/<имя>`, а
    `checkout` по полному имени отвязывает дерево. Тест различает оба отката.
    """
    on_own_branch(stand)
    git(stand, "tag", "feature")
    start = module.spot(stand)
    assert start == f"{module.BRANCH_REF}feature"
    module.switch_clean(stand, "agent/x")
    module.restore(stand, start)
    assert git(stand, "symbolic-ref", "--quiet", "HEAD").strip() == start


def test_a_failed_return_names_the_branch_as_restore_does(
    stand: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ возврата называет ветку, как `restore`, — без `refs/heads/` (взгляд на #1513)."""
    git(stand, "tag", "v2.0.0")
    on_own_branch(stand)

    def broken(root: Path, start: str) -> None:
        raise module.NotRun("сломано")

    monkeypatch.setattr(module, "restore", broken)
    said = module.main(["--root", str(stand), "--repo", "o/r", "--self", "v2.0.0", "--apply"])
    assert said == module.EXIT_BROKEN
    err = capsys.readouterr().err
    assert "дерево на feature не возвращено" in err and module.BRANCH_REF not in err, err


def test_an_already_lifted_action_is_named_so(stand: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Строки уже на версии сигнала — причина «уже поднято», а не «строк нет» (взгляд на #1397)."""
    fake_platform(monkeypatch, [])
    flows = stand / module.paths.WORKFLOWS
    (flows / "ci.yml").write_text(
        f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{SHA_NEW} # v7.1.0\n",
        encoding="utf-8",
    )
    git(stand, "commit", "--quiet", "-am", "поднято")
    git(stand, "push", "--quiet", "origin", "HEAD:main")
    assert module.uses_lines(stand, "actions/checkout") == 1
    assert module.uses_lines(stand, "x/y") == 0
    bump = module.Bump(41, "actions/checkout", "7.0.1", "7.1.0")
    with pytest.raises(module.Refused, match=r"уже на v7\.1\.0"):
        module.intercept(stand, "o/r", "t", bump, dry_run=False, plan_issue=7, who=WHO)


# --- слежка за файлом поставщика (#1522) ---

#: Файл поставщика, за которым следит слежка стенда.
WATCHED = "src/restore.ts"


def watch_stand(work: Path, read_at: str = SHA_OLD, watched: tuple[str, ...] = (WATCHED,)) -> None:
    """Стенд со слежкой: `actions/checkout` следит за каждым из `watched` с `read_at`."""
    (work / module.paths.VENDOR_WATCH).parent.mkdir(parents=True, exist_ok=True)
    entries = ",\n".join(
        "    {\n"
        '      "dep": "actions/checkout",\n'
        f'      "path": "{one}",\n'
        f'      "read_at": "{read_at}",\n'
        '      "by": "tests/x.py::Y"\n'
        "    }"
        for one in watched
    )
    (work / module.paths.VENDOR_WATCH).write_text(
        f'{{\n  "watched": [\n{entries}\n  ]\n}}\n', encoding="utf-8"
    )
    git(work, "add", "-A")
    git(work, "commit", "--quiet", "-m", "слежка")
    git(work, "push", "--quiet", "origin", "HEAD:main")


def vendor(monkeypatch: pytest.MonkeyPatch, compare: Any, said: list[tuple[str, str]]) -> None:
    """Площадка с поставщиком: тег — `SHA_NEW`, `compare` — данный ответ, запись — в `said`."""

    def ask(method: str, path: str, token: str, body: Any = None) -> Any:
        if method == "GET" and "/compare/" in path:
            said.append((method, path))
            return compare
        if method == "GET":
            return {"sha": SHA_NEW}
        said.append((method, path))
        return {}

    monkeypatch.setattr(module.ghrest, "request", ask)


def ahead(*names: str) -> dict[str, Any]:
    """Ответ `compare`: новый коммит впереди, тронуты `names`."""
    return {"status": "ahead", "files": [{"filename": one} for one in names]}


def test_an_untouched_vendor_file_moves_the_watch_in_the_same_commit(
    stand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Файл поставщика не тронут — `read_at` сдвинут тем же коммитом подъёма, сигнал закрыт."""
    watch_stand(stand)
    said: list[tuple[str, str]] = []
    vendor(monkeypatch, ahead("package.json", "bun.lock"), said)
    bump = module.Bump(41, "actions/checkout", "7.0.1", "7.1.0")
    branch = module.intercept(stand, "o/r", "t", bump, dry_run=False, plan_issue=7, who=WHO)
    watch = git(stand, "show", f"origin/{branch}:{module.paths.VENDOR_WATCH.as_posix()}")
    assert f'"read_at": "{SHA_NEW}"' in watch and SHA_OLD not in watch
    assert ("GET", f"repos/actions/checkout/compare/{SHA_OLD}...{SHA_NEW}") in said
    assert ("PATCH", "repos/o/r/pulls/41") in said


@pytest.mark.parametrize(
    "files",
    [[{"filename": WATCHED}], [{"filename": "src/new.ts", "previous_filename": WATCHED}]],
    ids=["правлен", "переименован"],
)
def test_a_touched_vendor_file_refuses_with_its_address(
    stand: Path, monkeypatch: pytest.MonkeyPatch, files: list[dict[str, str]]
) -> None:
    """Файл поставщика тронут — отказ с адресом файла: ветки нет, сигнал открыт для человека."""
    watch_stand(stand)
    said: list[tuple[str, str]] = []
    vendor(monkeypatch, {"status": "ahead", "files": files}, said)
    bump = module.Bump(41, "actions/checkout", "7.0.1", "7.1.0")
    with pytest.raises(module.Refused, match=f"actions/checkout/blob/{SHA_NEW}/{WATCHED}"):
        module.intercept(stand, "o/r", "t", bump, dry_run=False, plan_issue=7, who=WHO)
    assert not git(stand, "ls-remote", "--heads", "origin", module.branch_of(bump.dep, "v7.1.0"))
    assert [one for one in said if one[0] != "GET"] == []


@pytest.mark.parametrize(
    ("compare", "outcome"),
    [
        ({"status": "ahead", "files": [{"filename": f"f{n}"} for n in range(300)]}, "NotRun"),
        ({"status": "ahead"}, "NotRun"),
        ({}, "NotRun"),
        ([], "NotRun"),
        ({"status": "ahead", "files": ["src/restore.ts"]}, "NotRun"),
        ({"status": "diverged", "files": []}, "Refused"),
        ({"status": "behind", "files": []}, "Refused"),
    ],
    ids=[
        "список-на-пределе",
        "без-списка",
        "без-исхода",
        "не-словарь",
        "файлы-не-записи",
        "разошлись",
        "назад",
    ],
)
def test_an_unproven_compare_is_not_untouched(
    stand: Path, monkeypatch: pytest.MonkeyPatch, compare: Any, outcome: str
) -> None:
    """Неполный ответ — заход не отработал, не-потомок — находка; «не тронут» ни там, ни там."""
    watch_stand(stand)
    said: list[tuple[str, str]] = []
    vendor(monkeypatch, compare, said)
    bump = module.Bump(41, "actions/checkout", "7.0.1", "7.1.0")
    with pytest.raises(getattr(module, outcome)):
        module.intercept(stand, "o/r", "t", bump, dry_run=False, plan_issue=7, who=WHO)
    assert [one for one in said if one[0] != "GET"] == []


def test_two_watches_from_one_pin_move_together_on_one_compare(
    stand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Две слежки с одним `read_at`: `compare` один, сдвигаются обе (взгляд на #1524)."""
    watch_stand(stand, watched=(WATCHED, "src/other.ts"))
    said: list[tuple[str, str]] = []
    vendor(monkeypatch, ahead("package.json"), said)
    planned = module.follow(stand, "actions/checkout", SHA_NEW, "t")
    text = planned[module.paths.VENDOR_WATCH]
    assert text.count(f'"read_at": "{SHA_NEW}"') == 2 and SHA_OLD not in text
    assert len([one for one in said if "/compare/" in one[1]]) == 1


def test_one_touched_watch_of_two_moves_neither(
    stand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тронут файл второй слежки — отказ, и первая не сдвинута в одиночку."""
    watch_stand(stand, watched=(WATCHED, "src/other.ts"))
    vendor(monkeypatch, ahead("src/other.ts"), [])
    with pytest.raises(module.Refused, match=r"src/other\.ts"):
        module.follow(stand, "actions/checkout", SHA_NEW, "t")


def test_a_missing_vendor_commit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Коммита `read_at` у поставщика нет — сравнивать не с чем, это находка, а не поломка."""

    def missing(method: str, path: str, token: str, body: Any = None) -> Any:
        raise module.ghrest.NotFound("404")

    monkeypatch.setattr(module.ghrest, "request", missing)
    with pytest.raises(module.Refused, match="коммита у поставщика нет"):
        module.touched("actions/checkout", SHA_OLD, SHA_NEW, "t")


def test_a_watch_already_at_the_new_commit_asks_nothing(
    stand: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Слежка уже на новом коммите — сравнивать нечего, и файл объявлений не правится."""
    watch_stand(stand, read_at=SHA_NEW)
    said: list[tuple[str, str]] = []
    vendor(monkeypatch, {}, said)
    assert module.follow(stand, "actions/checkout", SHA_NEW, "t") == {}
    assert said == []


def test_a_malformed_watch_file_does_not_run(stand: Path) -> None:
    """Файл слежки не той формы — заход не отработал, а не «слежек нет» (039)."""
    (stand / module.paths.VENDOR_WATCH).parent.mkdir(parents=True, exist_ok=True)
    (stand / module.paths.VENDOR_WATCH).write_text("[]", encoding="utf-8")
    with pytest.raises(module.NotRun, match="не список"):
        module.watches(stand, "actions/checkout")


def test_a_tree_without_watches_asks_nothing(stand: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Файла слежки нет (потребитель) — `compare` не спрашивается, подъём идёт как прежде."""
    said: list[tuple[str, str]] = []
    vendor(monkeypatch, {}, said)
    assert module.follow(stand, "actions/checkout", SHA_NEW, "t") == {}
    assert said == []


def test_every_watch_is_pinned_and_read() -> None:
    """Слежки дерева в своей форме: `read_at` — закрепление действия в прогонах, `by` — живой адрес.

    Слежка на закреплении, которого в дереве нет, сравнивала бы не то, а
    `by` в никуда не называет, что перечитывать при отказе (076).
    """
    said = module.json.loads((ROOT / module.paths.VENDOR_WATCH).read_text(encoding="utf-8"))
    assert said["watched"], f"{module.paths.VENDOR_WATCH}: слежек нет — предмета нет (075)"
    for one in said["watched"]:
        assert module.SHA_RE.match(one["read_at"]), f"{one['dep']}: `read_at` не sha"
        assert one["path"] and one["why"], f"{one['dep']}: нет `path` или `why`"
        pins = {
            found["ref"]
            for path in walk(ROOT / module.WORKFLOWS, "*.yml")
            for line in path.read_text(encoding="utf-8").split("\n")
            if (found := module.uses_re(one["dep"]).search(line))
        }
        assert one["read_at"] in pins, f"{one['dep']}: `read_at` не среди закреплений {pins}"
        file, _, name = one["by"].partition("::")
        assert name in (ROOT / file).read_text(encoding="utf-8"), f"`by` в никуда: {one['by']}"


def test_the_watch_file_is_read_where_the_table_puts_it(tmp_path: Path) -> None:
    """Объявления слежки — по таблице путей корня; битый раздел — отказ, а не умолчание (#1632)."""
    moved = Path("cfg/watch.json")
    (tmp_path / "cfg").mkdir()
    (tmp_path / moved).write_text(
        json.dumps({"watched": [{"dep": "o/a", "path": "x.ts", "read_at": SHA_OLD}]}),
        encoding="utf-8",
    )
    assert module.watches(tmp_path, "o/a") == []
    (tmp_path / ".pipeline.yml").write_text(f"paths:\n  vendor-watch: {moved}\n", encoding="utf-8")
    assert module.at_root("vendor-watch", tmp_path) == moved
    assert [one["path"] for one in module.watches(tmp_path, "o/a")] == ["x.ts"]
    (tmp_path / ".pipeline.yml").write_text("paths:\n  vendor-watch: /w.json\n", encoding="utf-8")
    with pytest.raises(module.NotRun, match="вне дерева"):
        module.watches(tmp_path, "o/a")
