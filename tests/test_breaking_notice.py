"""Оповещение о несовместимом выпуске (#1387): повод, адресаты, повтор, исходы.

Дерево выпусков подделывается настоящим git с тегами: мажор контракта читается
с дерева тега, и подделка `contract_at` проверяла бы не механизм, а её саму.
Площадка и обход семьи подменяются — клонировать соседей тест не ходит.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FAKE_VERSION, git, load_script

module = load_script("breaking_notice.py")

#: Версии контракта подделки — от общей `FAKE_VERSION`, а не своим литералом:
#: предмет здесь не число, а шаг между выпусками — минор, мажор, минор.
_MAJOR, _MINOR, _ = module.version.digits(FAKE_VERSION)
MINOR_UP: str = f"{_MAJOR}.{_MINOR + 1}.0"
MAJOR_UP: str = f"{_MAJOR + 1}.0.0"
AFTER: str = f"{_MAJOR + 1}.1.0"

#: Выпуски подделки по возрастанию: тег → версия контракта на его дереве.
#: `v1.10.0` стоит последним нарочно — строковая сортировка поставила бы его
#: перед `v1.6.0`, и «предыдущим» для `v1.8.0` оказался бы чужой выпуск.
LINE: tuple[tuple[str, str], ...] = (
    ("v1.6.0", FAKE_VERSION),
    ("v1.7.0", MINOR_UP),
    ("v1.8.0", MAJOR_UP),
    ("v1.10.0", AFTER),
)

#: Сосед, позвавший наш шаг выпуска по тегу.
TOOK = module.family_uptake.Took("o/взял", (("step-release", "v1.7.0"),), ">=1.3,<1.4")
#: Сосед, не позвавший ничего из отдаваемого.
SKIPPED = module.family_uptake.Took("o/не-взял", (), None)


def releases(root: Path, line: tuple[tuple[str, str], ...] = LINE) -> Path:
    """Дерево, где каждый выпуск — коммит со своей версией контракта и тегом."""
    git(root, "init", "-q")
    git(root, "config", "user.email", "a@b")
    git(root, "config", "user.name", "выпуск")
    for tag, contract in line:
        (root / "CONTRACT_VERSION").write_text(f"{contract}\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-qm", tag)
        git(root, "tag", "-a", tag, "-m", tag)
    return root


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Дерево выпусков как текущий каталог: git и пути механизм берёт от него."""
    root = releases(tmp_path)
    monkeypatch.chdir(root)
    return root


def test_the_marker_names_the_release() -> None:
    """Метка задачи несёт тег: по ней повтор узнаёт оповещение своего выпуска."""
    assert module.marker("v2.0.0") == "<!-- breaking-notice: v2.0.0 -->"
    assert module.marker("v2.0.0") != module.marker("v3.0.0")


def test_release_tags_are_ordered_by_number_not_by_text(tree: Path) -> None:
    """Порядок выпусков — числовой, а посторонний тег выпуском не считается."""
    git(tree, "tag", "v1.8")
    git(tree, "tag", "draft")
    assert module.release_tags() == [tag for tag, _ in LINE]


def test_the_previous_release_is_the_one_before_by_number(tree: Path) -> None:
    """Предыдущий — соседний по номеру; у первого выпуска предыдущего нет."""
    tags = module.release_tags()
    assert module.previous("v1.10.0", tags) == "v1.8.0"
    assert module.previous("v1.7.0", tags) == "v1.6.0"
    assert module.previous("v1.6.0", tags) is None


def test_a_missing_tag_is_refused_not_taken_for_the_first(tree: Path) -> None:
    """Тега в дереве нет — отказ, а не «первый выпуск, оповещать не о чем» (075)."""
    with pytest.raises(module.NotRun, match=r"v9\.0\.0"):
        module.previous("v9.0.0", module.release_tags())


@pytest.mark.parametrize(
    ("tag", "jump"),
    [
        ("v1.6.0", None),
        ("v1.7.0", None),
        ("v1.8.0", (MINOR_UP, MAJOR_UP)),
        ("v1.10.0", None),
    ],
    ids=["первый выпуск", "минор", "мажор", "минор после мажора"],
)
def test_only_a_grown_major_is_breaking(tree: Path, tag: str, jump: tuple[str, str] | None) -> None:
    """Повод — только мажор контракта, прочитанный с дерева тега и предыдущего."""
    assert module.breaking(tag) == jump


def test_a_contract_not_of_the_form_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Версия контракта не `X.Y.Z` — отказ своими словами, а не трасса (214)."""
    monkeypatch.chdir(releases(tmp_path, (("v1.0.0", FAKE_VERSION), ("v1.1.0", "2.0"))))
    with pytest.raises(module.NotRun, match="версия контракта"):
        module.breaking("v1.1.0")


def test_changes_name_every_contract_heading_of_the_release(tree: Path) -> None:
    """Названы все `###` фрагментов `contract` выпуска; прочие роды — нет."""
    kept = tree / "changelog.d" / "released" / "1.8.0"
    kept.mkdir(parents=True)
    (kept / "two.contract.md").write_text(
        "### Первая правка\n\nтекст\n\n### Вторая правка\n\nтекст\n\n#1\n", encoding="utf-8"
    )
    (kept / "bare.contract.md").write_text("без заголовка\n\n#2\n", encoding="utf-8")
    (kept / "other.added.md").write_text("### Не поверхность\n\n#3\n", encoding="utf-8")
    assert module.changes("1.8.0") == ["bare", "Первая правка", "Вторая правка"]


def test_changes_of_a_release_without_records_are_empty(tree: Path) -> None:
    """Каталога выпуска нет — изменений не названо, и тело говорит об этом."""
    assert module.changes("1.8.0") == []
    body = module.body_of("v1.8.0", "1.3.0", "2.0.0", TOOK, [])
    assert "записи рода `contract` в выпуске не найдены" in body


def test_the_body_names_the_jump_the_steps_and_the_changes() -> None:
    """Тело несёт метку, переход версий, позванное соседом и изменившееся."""
    body = module.body_of("v1.8.0", "1.3.0", "2.0.0", TOOK, ["Первая правка"])
    assert body.startswith(module.marker("v1.8.0"))
    assert "`1.3.0` → `2.0.0`" in body
    assert "`step-release`" in body
    assert "`v1.7.0`" in body
    assert "- Первая правка" in body
    assert f"/blob/v1.8.0/{module.paths.RELEASE_DOC}" in body


def issues_of(found: list[dict[str, Any]]) -> Any:
    """Подделка постраничного чтения задач соседа."""

    def paginate(path: str, token: str, key: str | None = None) -> Iterator[dict[str, Any]]:
        assert "state=all" in path
        assert "creator=владелец" in path
        return iter(found)

    return paginate


def test_a_notice_already_there_is_not_opened_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Задача с меткой выпуска уже есть — открытая или закрытая — второй нет."""
    monkeypatch.setattr(
        module.ghrest, "paginate", issues_of([{"body": f"{module.marker('v1.8.0')}\n…"}])
    )
    monkeypatch.setattr(
        module.ghrest, "request", lambda *_: pytest.fail("второе оповещение заведено")
    )
    said = module.notify("o/взял", "v1.8.0", "тело", "т", "владелец", dry_run=False)
    assert "уже есть" in said


def test_a_notice_of_another_release_does_not_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Метка чужого выпуска — не «оповещён»: повод у каждого мажора свой."""
    monkeypatch.setattr(
        module.ghrest, "paginate", issues_of([{"body": module.marker("v1.0.0")}, {"body": None}])
    )
    assert not module.notified("o/взял", "v1.8.0", "т", "владелец")


def test_a_dry_run_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пробный заход называет задачу, но не заводит её."""
    monkeypatch.setattr(module.ghrest, "paginate", issues_of([]))
    monkeypatch.setattr(module.ghrest, "request", lambda *_: pytest.fail("пробный заход записал"))
    said = module.notify("o/взял", "v1.8.0", "тело", "т", "владелец", dry_run=True)
    assert said.startswith(module.report.DRY)
    assert "не спрошено" not in said


def test_a_dry_run_without_a_token_says_it_did_not_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без владельца токена «есть ли уже» не спрошено — и сказано, а не угадано."""
    monkeypatch.setattr(
        module.ghrest, "paginate", lambda *_: pytest.fail("искал среди задач всех авторов")
    )
    said = module.notify("o/взял", "v1.8.0", "тело", "", "", dry_run=True)
    assert "не спрошено: токена нет" in said


def test_an_applied_notice_is_opened_in_the_neighbour(monkeypatch: pytest.MonkeyPatch) -> None:
    """Боевой заход заводит задачу у соседа с телом оповещения."""
    sent: list[tuple[str, str, dict[str, str]]] = []

    def request(method: str, path: str, token: str, data: dict[str, str]) -> dict[str, int]:
        sent.append((method, path, data))
        return {"number": 7}

    monkeypatch.setattr(module.ghrest, "paginate", issues_of([]))
    monkeypatch.setattr(module.ghrest, "request", request)
    said = module.notify("o/взял", "v1.8.0", "тело", "т", "владелец", dry_run=False)
    assert said == "o/взял: задача заведена #7"
    assert [(method, path) for method, path, _ in sent] == [("POST", "repos/o/взял/issues")]
    assert sent[0][2]["body"] == "тело"
    assert "v1.8.0" in sent[0][2]["title"]


def family_of(
    monkeypatch: pytest.MonkeyPatch,
    seen: list[Any],
    unread: list[str] | None = None,
) -> list[str]:
    """Подменяет семью, обход и отдаваемые шаги; отдаёт, к кому шло оповещение."""
    notified: list[str] = []
    monkeypatch.setattr(module.family_uptake, "family", lambda: ["o/взял", "o/не-взял"])
    monkeypatch.setattr(module.family_uptake, "sweep", lambda repos, where: (seen, unread or []))
    monkeypatch.setattr(module.onboard, "steps", lambda root: ["release", "review"])

    def notify(repo: str, tag: str, body: str, token: str, login: str, *, dry_run: bool) -> str:
        notified.append(repo)
        return f"{repo}: оповещён"

    monkeypatch.setattr(module, "notify", notify)
    return notified


OURS = ["--repo", module.family_uptake.OURS]


def test_a_consumer_notifies_nobody(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Шаг выпуска общий: у потребителя заход отвечает «некого», а не шлёт наш мажор."""
    notified = family_of(monkeypatch, [TOOK])
    assert module.main(["--tag", "v1.8.0", "--repo", "o/взял"]) == module.EXIT_OK
    assert notified == []


def test_a_minor_release_notifies_nobody(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Минор не повод: окно контракта у соседа примет его само."""
    notified = family_of(monkeypatch, [TOOK])
    assert module.main(["--tag", "v1.7.0", *OURS]) == module.EXIT_OK
    assert notified == []


def test_a_major_release_notifies_only_who_took_our_steps(
    tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Мажор: оповещён взявший отдаваемый шаг, не взявший — нет."""
    notified = family_of(monkeypatch, [TOOK, SKIPPED])
    assert module.main(["--tag", "v1.8.0", *OURS]) == module.EXIT_OK
    assert notified == ["o/взял"]
    assert "взяли наши шаги 1 из 2" in capsys.readouterr().out


def test_an_unread_neighbour_makes_the_outcome_partial(
    tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Непрочитанный клон — не «не взял»: назван, и исход частичный (045)."""
    notified = family_of(monkeypatch, [TOOK], unread=["o/закрыт"])
    assert module.main(["--tag", "v1.8.0", *OURS]) == module.EXIT_PARTIAL
    assert notified == ["o/взял"]
    assert "o/закрыт" in capsys.readouterr().out


def test_a_failed_notice_makes_the_outcome_partial(
    tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ площадки у одного соседа не уносит остальных и назван поимённо."""
    family_of(monkeypatch, [TOOK])

    def refused(*_: object, **__: object) -> str:
        raise module.ghrest.TransportError("403")

    monkeypatch.setattr(module, "notify", refused)
    assert module.main(["--tag", "v1.8.0", *OURS]) == module.EXIT_PARTIAL
    assert "не оповещены: o/взял" in capsys.readouterr().out


def test_a_missing_tag_is_the_third_outcome(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Тега нет — «не отработал», а не «оповещать не о чем» (039)."""
    family_of(monkeypatch, [TOOK])
    assert module.main(["--tag", "v9.0.0", *OURS]) == module.EXIT_BROKEN


def test_an_unread_family_is_the_third_outcome(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Сводка семьи не прочитана — «не отработал», а не «взявших нет»."""
    family_of(monkeypatch, [TOOK])

    def broken() -> list[str]:
        raise module.family_uptake.NotRun("сводка семьи не прочитана")

    monkeypatch.setattr(module.family_uptake, "family", broken)
    assert module.main(["--tag", "v1.8.0", *OURS]) == module.EXIT_BROKEN


def test_an_applied_run_without_a_token_is_refused(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Боевой заход без токена — отказ до обхода соседей, а не тихий пропуск."""
    notified = family_of(monkeypatch, [TOOK])
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    assert module.main(["--tag", "v1.8.0", *OURS, "--apply"]) == module.EXIT_BROKEN
    assert notified == []


def test_an_applied_run_notifies_as_the_owner_of_the_token(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Задачи заводятся от имени владельца токена, спрошенного у площадки (131)."""
    seen: list[tuple[str, str]] = []
    family_of(monkeypatch, [TOOK])
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "т")
    monkeypatch.setattr(module.ghrest, "request", lambda *_: {"login": "владелец"})

    def notify(repo: str, tag: str, body: str, token: str, login: str, *, dry_run: bool) -> str:
        seen.append((login, str(dry_run)))
        return repo

    monkeypatch.setattr(module, "notify", notify)
    assert module.main(["--tag", "v1.8.0", *OURS, "--apply"]) == module.EXIT_OK
    assert seen == [("владелец", "False")]


def test_a_notice_without_a_number_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка не назвала номер — отказ транспорта, а не «заведена #None» (039)."""
    monkeypatch.setattr(module.ghrest, "paginate", issues_of([]))
    monkeypatch.setattr(module.ghrest, "request", lambda *_: [])
    with pytest.raises(module.ghrest.TransportError, match="номер"):
        module.notify("o/взял", "v1.8.0", "тело", "т", "владелец", dry_run=False)


@pytest.mark.parametrize(
    "said", [{}, {"login": ""}, [], None], ids=["пусто", "без имени", "список", "ничего"]
)
def test_an_unnamed_owner_is_refused(monkeypatch: pytest.MonkeyPatch, said: object) -> None:
    """Владелец токена не назван — отказ своими словами, а не трасса (039)."""
    monkeypatch.setattr(module.ghrest, "request", lambda *_: said)
    with pytest.raises(module.NotRun, match="владельца токена"):
        module.owner_of("т")


def test_no_token_has_no_owner_and_asks_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без токена владельца не спрашивают: пробный заход идёт и без него."""
    monkeypatch.setattr(module.ghrest, "request", lambda *_: pytest.fail("спросил без токена"))
    assert module.owner_of("") == ""


def test_an_unreadable_tag_list_is_the_third_outcome(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Git не ответил о тегах — «не отработал», а не трасса с кодом 1 (039)."""
    family_of(monkeypatch, [TOOK])

    def silent(*_: str) -> str:
        raise module.release.NotRun("git не ответил")

    monkeypatch.setattr(module.release, "git", silent)
    assert module.main(["--tag", "v1.8.0", *OURS]) == module.EXIT_BROKEN
