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
    declared: list[str] | None = None,
) -> list[str]:
    """Подменяет семью, обход, реестр, отдаваемые шаги и токен; отдаёт, к кому шло оповещение.

    Токен окружения снимается: с `GH_TOKEN` в среде прогона `main` шёл бы к
    площадке, и исход зависел бы от среды, а не от дерева (107; поздний взгляд
    на #1497). Тест, которому токен нужен, ставит его сам.
    """
    notified: list[str] = []
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    monkeypatch.setattr(module.family_uptake, "family", lambda: ["o/взял", "o/не-взял"])
    monkeypatch.setattr(module.family_uptake, "sweep", lambda repos, where: (seen, unread or []))
    monkeypatch.setattr(module.onboard, "steps", lambda root: ["release", "review"])
    monkeypatch.setattr(
        module.consumers, "registry", lambda root: [{"repo": one} for one in declared or []]
    )

    def notify(repo: str, tag: str, body: str, token: str, login: str, **_: object) -> str:
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


#: Окно, покрывающее минор подделки, и окно, прибитое к прежнему минору.
COVERING: str = f">={_MAJOR}.{_MINOR},<{_MAJOR}.{_MINOR + 2}"
PINNED: str = f">={_MAJOR}.{_MINOR},<{_MAJOR}.{_MINOR + 1}"


def took(repo: str, span: str | None) -> Any:
    """Взявший наш шаг выпуска с данным окном `contract:`."""
    return module.family_uptake.Took(repo, (("step-release", "v1.6.0"),), span)


def test_a_minor_within_the_window_notifies_nobody(
    tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Минор, который окно соседа покрывает, — не повод: перечитывать ему нечего (#1586)."""
    notified = family_of(monkeypatch, [took("o/взял", COVERING)])
    assert module.main(["--tag", "v1.7.0", *OURS]) == module.EXIT_OK
    assert notified == []
    assert "покрывает" in capsys.readouterr().out


def test_a_minor_outside_the_window_notifies_its_owner(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Минор вне окна: оповещён тот, чьё окно его не покрывает, и только он (#1586)."""
    notified = family_of(monkeypatch, [took("o/взял", PINNED), took("o/шире", COVERING), SKIPPED])
    assert module.main(["--tag", "v1.7.0", *OURS]) == module.EXIT_OK
    assert notified == ["o/взял"]


def test_a_declared_consumer_is_judged_by_the_window_in_its_tree(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Объявленный, которого обход не застал, судится окном из его дерева у площадки."""
    notified = family_of(monkeypatch, [], declared=["o/объявлен", "o/покрыт"])
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "т")
    monkeypatch.setattr(module, "asked_owner", lambda token: "владелец")
    windows = {"o/объявлен": PINNED, "o/покрыт": COVERING}
    monkeypatch.setattr(
        module.consumers, "answer_of", lambda repo, token: {"contract": windows[repo]}
    )
    assert module.main(["--tag", "v1.7.0", *OURS]) == module.EXIT_OK
    assert notified == ["o/объявлен"]


def test_an_unread_window_makes_the_minor_partial(
    tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Окно не прочитано — не «покрывает»: сосед назван один раз, и исход частичный (045)."""
    notified = family_of(
        monkeypatch, [took("o/взял", None)], unread=["O/ВЗЯЛ"], declared=["O/ВЗЯЛ"]
    )
    assert module.main(["--tag", "v1.7.0", *OURS]) == module.EXIT_PARTIAL
    assert notified == []
    out = capsys.readouterr().out
    assert "окно не прочитано" in out
    assert "не прочитаны: O/ВЗЯЛ;" in out


@pytest.mark.parametrize(
    ("said", "why"),
    [({}, "не объявлено"), ({"contract": "любое"}, "не разбирается")],
    ids=["окна нет", "окно не разобрано"],
)
def test_a_window_only_the_neighbour_can_fix_is_notified_not_red(
    tree: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    said: dict[str, str],
    why: str,
) -> None:
    """Окна нет или оно не разобрано — сосед оповещён, а шаг не красный на каждом миноре."""
    notified = family_of(monkeypatch, [], declared=["o/объявлен"])
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "т")
    monkeypatch.setattr(module, "asked_owner", lambda token: "владелец")
    monkeypatch.setattr(module.consumers, "answer_of", lambda repo, token: said)
    assert module.main(["--tag", "v1.7.0", *OURS]) == module.EXIT_OK
    assert notified == ["o/объявлен"]
    assert why in capsys.readouterr().out


def test_a_major_ignores_the_window(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Мажор оповещает каждого взявшего, какое бы окно он ни держал."""
    notified = family_of(monkeypatch, [took("o/взял", f">={_MAJOR + 1}.0,<{_MAJOR + 2}.0")])
    assert module.main(["--tag", "v1.8.0", *OURS]) == module.EXIT_OK
    assert notified == ["o/взял"]


def test_a_dry_run_before_the_release_names_whom_the_minor_reaches(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--to`: «до» — контракт последнего выпуска, «после» — названная версия."""
    notified = family_of(monkeypatch, [took("o/взял", f">={_MAJOR + 1}.1,<{_MAJOR + 1}.2")])
    assert module.main(["--tag", "v1.11.0", "--to", f"{_MAJOR + 1}.2.0", *OURS]) == module.EXIT_OK
    assert notified == ["o/взял"]


def test_to_is_refused_in_an_applied_run(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Боевой заход с `--to` не начинается: о невыпущенном соседям не пишут."""
    notified = family_of(monkeypatch, [took("o/взял", PINNED)])
    argv = ["--tag", "v1.11.0", "--to", f"{_MAJOR + 1}.2.0", *OURS, "--apply"]
    assert module.main(argv) == module.EXIT_BROKEN
    assert notified == []


@pytest.mark.parametrize(
    ("was", "now", "moved"),
    [("1.2.0", "1.3.0", True), ("1.2.0", "2.0.0", True), ("1.2.0", "1.2.5", False)],
    ids=["минор", "мажор", "патч"],
)
def test_grown_sees_major_and_minor_not_patch(was: str, now: str, moved: bool) -> None:
    """`grown` — рост MAJOR.MINOR; патч поверхности не трогает."""
    assert (module.grown(was, now) is not None) is moved


def test_addressees_join_takers_and_declared_once() -> None:
    """Объявленный, уже застанный обходом, не повторяется — регистр имени не значим."""
    joined = module.addressees([took("o/Взял", PINNED)], ["o/взял", "o/новый"])
    assert [one.repo for one in joined] == ["o/Взял", "o/новый"]
    assert joined[1].span is None


def test_window_of_and_covers_name_their_refusals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Окна нет или оно не разобрано — `NotRun` с причиной, а не «покрывает»."""
    assert module.window_of(took("o/взял", PINNED), "") == PINNED
    with pytest.raises(module.NotRun, match="токена"):
        module.window_of(took("o/взял", None), "")
    monkeypatch.setattr(module.consumers, "answer_of", lambda repo, token: {})
    assert module.window_of(took("o/взял", None), "т") is None
    with pytest.raises(module.NotRun, match="не разобрано"):
        module.covers("любое", "1.0.0")
    assert module.covers(">=1.2,<1.3", "1.2.4")


def test_the_minor_body_names_the_window_it_left() -> None:
    """Тело о миноре несёт метку, переход и окно соседа, которое его не покрывает."""
    body = module.minor_body_of("v1.7.0", "1.2.0", "1.3.0", ">=1.2,<1.3", ["Правка"])
    assert body.startswith(module.marker("v1.7.0"))
    assert "`1.2.0` → `1.3.0`" in body
    assert 'contract: ">=1.2,<1.3"' in body
    assert "- Правка" in body
    assert "1.3.0" in module.minor_title("v1.7.0", "1.3.0")
    bare = module.minor_body_of("v1.7.0", "1.2.0", "1.3.0", None, [])
    assert "не объявлено" in bare
    assert "«любое» не разбирается" in module.minor_body_of(
        "v1.7.0", "1.2.0", "1.3.0", "любое", [], "«любое» не разбирается"
    )


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

    def notify(
        repo: str, tag: str, body: str, token: str, login: str, *, dry_run: bool, **_: object
    ) -> str:
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


def test_asked_owner_names_the_owner_or_says_it_did_not_ask(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`asked_owner` — владелец для пробного захода: названный или «не спрошено», без отказа."""
    monkeypatch.setattr(module.ghrest, "request", lambda *_: {"login": "владелец"})
    assert module.asked_owner("т") == "владелец"

    def forbidden(*_: object, **__: object) -> object:
        raise module.ghrest.TransportError("403")

    monkeypatch.setattr(module.ghrest, "request", forbidden)
    assert module.asked_owner("т") == ""
    assert "не спрошено" in capsys.readouterr().out


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


def test_a_dry_run_with_an_unnamed_owner_says_it_did_not_ask(
    tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Токен приложения владельца не называет — пробный заход «не спросил», а не отказал."""
    notified = family_of(monkeypatch, [TOOK])
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "приложение")

    def forbidden(*_: object, **__: object) -> object:
        raise module.ghrest.TransportError("403 Resource not accessible by integration")

    monkeypatch.setattr(module.ghrest, "request", forbidden)
    assert module.main(["--tag", "v1.8.0", *OURS]) == module.EXIT_OK
    assert notified == ["o/взял"]
    assert "не спрошено" in capsys.readouterr().out


def test_an_applied_run_with_an_unnamed_owner_is_refused(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Боевой заход без названного владельца не начинается: от чьего имени писать — неясно."""
    notified = family_of(monkeypatch, [TOOK])
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "приложение")

    def forbidden(*_: object, **__: object) -> object:
        raise module.ghrest.TransportError("403 Resource not accessible by integration")

    monkeypatch.setattr(module.ghrest, "request", forbidden)
    assert module.main(["--tag", "v1.8.0", *OURS, "--apply"]) == module.EXIT_BROKEN
    assert notified == []


def test_jump_names_a_grown_minor_and_skips_the_first(tree: Path) -> None:
    """`jump` видит и минор, и мажор; у первого выпуска перехода нет."""
    assert module.jump("v1.7.0") == (FAKE_VERSION, MINOR_UP)
    assert module.jump("v1.8.0") == (MINOR_UP, MAJOR_UP)
    assert module.jump("v1.6.0") is None


def test_a_minor_notice_carries_its_own_title(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заголовок, переданный зовущим, идёт в задачу вместо заголовка мажора."""
    monkeypatch.setattr(module.ghrest, "paginate", issues_of([]))
    said = module.notify("o/взял", "v1.7.0", "тело", "т", "владелец", dry_run=True, title="свой")
    assert "«свой»" in said
