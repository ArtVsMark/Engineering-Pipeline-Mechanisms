"""Публикация фактов на ветку `badges` проверяется прогоном на настоящем git.

Прежде публикация жила сценарием оболочки, и гейт узнавал публикуемое разбором
этого сценария; три захода взгляда подряд находили новую форму записи (решение
владельца 08.10.2026, #639). Теперь запись — `scripts/publish_facts.py`, и
проверяется её поведение: что легло на ветку, что на ней уцелело, куда и как
ушёл толчок.
"""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, load_script

module = load_script("publish_facts.py")


def git(*args: str, cwd: Path) -> str:
    """Вызов git в каталоге стенда; отказ — падение теста."""
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return done.stdout


@pytest.fixture
def stand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Голый удалённый репозиторий, клон потребителя и собранный facts.json."""
    remote = tmp_path / "remote.git"
    git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    clone = tmp_path / "clone"
    git("init", "-q", "-b", "main", str(clone), cwd=tmp_path)
    for key, value in (("user.name", "t"), ("user.email", "t@t")):
        git("config", key, value, cwd=clone)
    (clone / "x").write_text("x", encoding="utf-8")
    git("add", "x", cwd=clone)
    git("commit", "-q", "-m", "x", cwd=clone)
    git("remote", "add", "origin", str(remote), cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)
    source = tmp_path / "facts.json"
    source.write_text('{"a": 1}\n', encoding="utf-8")
    # Значок проекта шаг рисует рядом с фактами (#1282) — стенд кладёт его так же.
    (tmp_path / "project.svg").write_text("<svg/>\n", encoding="utf-8")
    (tmp_path / "family-check.json").write_text('{"links": []}\n', encoding="utf-8")
    monkeypatch.chdir(clone)
    return {"remote": remote, "clone": clone, "source": source, "tmp": tmp_path}


#: Ветка и путь, куда публикация ОБЯЗАНА писать, — литералами вне модуля. Сверка со
#: своей же константой `publish_facts.BRANCH` проверяла намерение, а не факт:
#: `BRANCH = "main"` проходил бы зелёным (взгляд на #1233), и то же с путём
#: `PUBLISHES` (взгляд на #1240).
PUBLISHED_TO = "badges"
PUBLISHED_PATH = ".github/badges/facts.json"
PUBLISHED_PICTURE = ".github/badges/project.svg"
#: Разбор семьи — по адресу, который читает каталог (`РАЗБОР_АДРЕС`, #1532).
PUBLISHED_FAMILY = ".github/badges/family-check.json"


def on_branch(remote: Path, path: str) -> str:
    """Содержимое файла на ветке `badges` удалённого репозитория."""
    return git("show", f"{PUBLISHED_TO}:{path}", cwd=remote)


def test_the_first_publication_starts_the_branch(stand: dict[str, Path]) -> None:
    """Ветки нет — публикация начинает её сиротой и кладёт ровно `PUBLISHES`."""
    assert module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")
    assert module.PUBLISHES == (PUBLISHED_PATH, PUBLISHED_PICTURE, PUBLISHED_FAMILY)
    assert on_branch(stand["remote"], PUBLISHED_PATH) == '{"a": 1}\n'
    assert on_branch(stand["remote"], PUBLISHED_PICTURE) == "<svg/>\n"
    assert on_branch(stand["remote"], PUBLISHED_FAMILY) == '{"links": []}\n'


def test_a_missing_picture_keeps_the_old_one(
    stand: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Значка рядом нет — факты едут, на ветке прежний значок, пропуск назван (#1422).

    Значок рисует действие каталога, и не собрать его оно вправе: площадка не
    ответила о прогонах. Отказ всей публикации из-за него оставил бы витрину
    со вчерашними фактами.
    """
    assert module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")
    (stand["tmp"] / "project.svg").unlink()
    stand["source"].write_text('{"a": 2}\n', encoding="utf-8")
    assert module.publish(stand["source"], stand["tmp"] / "w2", sha="def")
    assert on_branch(stand["remote"], PUBLISHED_PATH) == '{"a": 2}\n'
    assert on_branch(stand["remote"], PUBLISHED_PICTURE) == "<svg/>\n"
    assert "project.svg" in capsys.readouterr().out


def test_targets_name_only_what_lies_beside(tmp_path: Path) -> None:
    """Факты — всегда; значок и архив — только если лежат рядом, архив — ещё и по входу."""
    source = tmp_path / "facts.json"
    assert module.targets(source, archive=True) == (PUBLISHED_PATH,)
    (tmp_path / "project.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "findings.json").write_text("{}", encoding="utf-8")
    assert module.targets(source, archive=False) == (PUBLISHED_PATH, PUBLISHED_PICTURE)
    (tmp_path / "family-check.json").write_text("{}", encoding="utf-8")
    assert module.targets(source, archive=False) == (
        PUBLISHED_PATH,
        PUBLISHED_PICTURE,
        PUBLISHED_FAMILY,
    )
    assert module.targets(source, archive=True)[-1] == module.ARCHIVE
    # Разбор без значка не едет: он едет только с ним (взгляд на #1534).
    (tmp_path / "project.svg").unlink()
    assert module.targets(source, archive=False) == (PUBLISHED_PATH,)


def test_a_picture_without_the_family_check_drops_the_old_one(
    stand: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Значок собран, разбора нет — прежний разбор снят: по адресу он неотличим от живого."""
    assert module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")
    (stand["tmp"] / "family-check.json").unlink()
    (stand["tmp"] / "project.svg").write_text("<svg>2</svg>\n", encoding="utf-8")
    assert module.publish(stand["source"], stand["tmp"] / "w2", sha="def")
    assert on_branch(stand["remote"], PUBLISHED_PICTURE) == "<svg>2</svg>\n"
    with pytest.raises(subprocess.CalledProcessError):
        on_branch(stand["remote"], PUBLISHED_FAMILY)
    assert "прежний разбор снимается" in capsys.readouterr().out


def test_no_picture_keeps_both_old_files(
    stand: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Значка нет — прежние значок и разбор остаются, даже если новый разбор лежит рядом."""
    assert module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")
    (stand["tmp"] / "project.svg").unlink()
    (stand["tmp"] / "family-check.json").write_text('{"links": [1]}\n', encoding="utf-8")
    stand["source"].write_text('{"a": 2}\n', encoding="utf-8")
    assert module.publish(stand["source"], stand["tmp"] / "w2", sha="def")
    assert on_branch(stand["remote"], PUBLISHED_PICTURE) == "<svg/>\n"
    assert on_branch(stand["remote"], PUBLISHED_FAMILY) == '{"links": []}\n'
    # Причина названа своя: разбор лежит рядом, но без значка не берётся (#1546).
    assert "family-check.json: без значка не публикуется" in capsys.readouterr().out


#: Тег действия каталога `project-badge`, о котором сверено, что он кладёт
#: `family-check.json` (взгляд на #1534). Сверка по `action.yml` тега:
#: `family_check.py` пишет разбор в `out-dir`, а `project_badge.py` читает его
#: оттуда же (`--family-json "$dir/family-check.json"`) — на v2.0.0 и, повторно
#: 22.10.2026 при подъёме (#1561), на v2.1.0: между тегами в `action.yml`
#: тронуто только закрепление `setup-python`. Новый тег — повторить сверку и
#: сдвинуть это значение тем же изменением.
FAMILY_CHECK_VERIFIED_AT: Final = "v2.1.0"


def test_the_badge_pin_was_checked_for_the_family_check() -> None:
    """Прибивка `project-badge` — та, о которой сверено, что разбор семьи она кладёт."""
    step = (ROOT / ".github" / "workflows" / "step-facts.yml").read_text(encoding="utf-8")
    pins = re.findall(r"/\.github/actions/project-badge@(\S+)", step)
    assert pins, "шаг фактов не зовёт project-badge — предмета у сверки нет (075)"
    assert set(pins) == {FAMILY_CHECK_VERIFIED_AT}, (
        f"project-badge прибит к {pins}, а разбор семьи сверен на {FAMILY_CHECK_VERIFIED_AT}: "
        "проверьте, что новый тег кладёт family-check.json, и сдвиньте сверку"
    )


def test_a_publication_lays_over_and_keeps_the_rest(stand: dict[str, Path]) -> None:
    """Поверх ветки: свой файл потребителя на ней уцелел, факты обновились."""
    module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")
    other = stand["tmp"] / "other"
    git("clone", "-q", "-b", PUBLISHED_TO, str(stand["remote"]), str(other), cwd=stand["tmp"])
    for key, value in (("user.name", "t"), ("user.email", "t@t")):
        git("config", key, value, cwd=other)
    (other / "own.svg").write_text("<svg/>", encoding="utf-8")
    git("add", "own.svg", cwd=other)
    git("commit", "-q", "-m", "свой значок", cwd=other)
    git("push", "-q", "origin", PUBLISHED_TO, cwd=other)
    stand["source"].write_text('{"a": 2}\n', encoding="utf-8")
    assert module.publish(stand["source"], stand["tmp"] / "w2", sha="def")
    assert on_branch(stand["remote"], "own.svg") == "<svg/>"
    assert on_branch(stand["remote"], PUBLISHED_PATH) == '{"a": 2}\n'


def test_unchanged_facts_make_no_commit(stand: dict[str, Path]) -> None:
    """Те же факты — коммита нет, и это не отказ."""
    module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")
    assert not module.publish(stand["source"], stand["tmp"] / "w2", sha="abc")


def test_an_unreadable_branch_is_not_overwritten(stand: dict[str, Path]) -> None:
    """Ветка не прочитана не потому, что её нет, — отказ, а не сирота поверх."""
    git("remote", "set-url", "origin", str(stand["tmp"] / "нет.git"), cwd=stand["clone"])
    with pytest.raises(module.NotPublished, match="не прочитана"):
        module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")


def test_a_racing_branch_is_refused_not_overwritten(
    stand: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ветка сдвинулась между выборкой и толчком — толчок без `--force` отказан."""
    module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")
    real = module.checkout

    def checkout_then_race(workdir: Path) -> None:
        real(workdir)
        other = stand["tmp"] / "racer"
        git("clone", "-q", "-b", PUBLISHED_TO, str(stand["remote"]), str(other), cwd=stand["tmp"])
        for key, value in (("user.name", "t"), ("user.email", "t@t")):
            git("config", key, value, cwd=other)
        (other / "race").write_text("r", encoding="utf-8")
        git("add", "race", cwd=other)
        git("commit", "-q", "-m", "гонка", cwd=other)
        git("push", "-q", "origin", PUBLISHED_TO, cwd=other)

    monkeypatch.setattr(module, "checkout", checkout_then_race)
    stand["source"].write_text('{"a": 3}\n', encoding="utf-8")
    with pytest.raises(module.NotPublished, match="push"):
        module.publish(stand["source"], stand["tmp"] / "w2", sha="ghi")
    assert on_branch(stand["remote"], "race") == "r", "толчок затёр чужое"


def test_the_exit_names_the_refusal(
    stand: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ — код 2 и `::error::` с причиной; успех — код 0 и адрес файла."""
    argv = [
        str(stand["source"]),
        "--workdir",
        str(stand["tmp"] / "w1"),
        "--sha",
        "a",
        "--repo",
        "o/r",
    ]
    assert module.main(argv) == module.EXIT_OK
    assert (
        "raw.githubusercontent.com/o/r/badges/.github/badges/facts.json" in capsys.readouterr().out
    )
    git("remote", "set-url", "origin", str(stand["tmp"] / "нет.git"), cwd=stand["clone"])
    argv[2] = str(stand["tmp"] / "w2")
    assert module.main(argv) == module.EXIT_BROKEN
    assert "::error::факты не опубликованы" in capsys.readouterr().out


def test_a_missing_source_is_a_refusal_not_a_traceback(
    stand: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Нет `facts.json` — код 2 и `::error::`, а не трейсбек с кодом 1 (039, взгляд на #1233)."""
    argv = [str(stand["tmp"] / "нет.json"), "--workdir", str(stand["tmp"] / "w1")]
    argv += ["--sha", "a", "--repo", "o/r"]
    assert module.main(argv) == module.EXIT_BROKEN
    assert "::error::факты не опубликованы" in capsys.readouterr().out


def test_a_refused_signature_is_a_refusal(
    stand: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отказ `git config` — «не опубликовано», а не коммит под чужой подписью (взгляд на #1233)."""
    real: Callable[..., subprocess.CompletedProcess[str]] = module.git

    def refusing(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        if args[:1] == ("config",):
            return subprocess.CompletedProcess(list(args), 1, "", "нет прав")
        return real(*args, cwd=cwd)

    monkeypatch.setattr(module, "git", refusing)
    with pytest.raises(module.NotPublished, match="подпись"):
        module.publish(stand["source"], stand["tmp"] / "w1", sha="a")


def call_key(args: tuple[str, ...]) -> str:
    """Чем вызов git отличается от соседних: подкоманда и все её флаги.

    По одной подкоманде два вызова `worktree` — поверх ветки (`--detach`) и
    сиротой (`--orphan`) — сливались в один ключ, и отказ первого не
    прогонялся вовсе (взгляд на #1257). Флаги различают и их, и новый вызов
    знакомой подкоманды (`worktree remove`, второй `diff` с иными флагами).
    Предел назван: вызов, повторяющий подкоманду с ТЕМИ ЖЕ флагами, ключа не
    добавит.
    """
    flags = sorted(one for one in args[1:] if one.startswith("-") and one != "--")
    return " ".join([args[0], *flags])


#: Отказ каждого вызова git: ключ (`call_key`) → код отказа и нужна ли ветка
#: заранее. Набор сверяется с ключами вызовов, которые публикация делает на
#: деле (`test_the_refusals_cover_every_git_step`): вызов без строки краснеет.
#: `ls-remote` отказывает вместе с `fetch` — порознь он не зовётся; путь
#: «поверх» (`--detach`) требует ветки, поэтому ей предшествует публикация.
REFUSALS: Final[dict[str, tuple[int, bool]]] = {
    "fetch --quiet": (1, False),
    "ls-remote --exit-code --heads": (128, False),
    "worktree --orphan --quiet -b": (1, False),
    "worktree --detach --quiet": (1, True),
    "config": (1, False),
    "add": (1, False),
    "diff --cached --quiet": (128, False),
    "commit -m -q": (1, False),
    "push -q": (1, False),
}
#: Что отказавший вызов говорит в `stderr` — уникально по ключу, чтобы видеть,
#: ЧЬЯ причина дошла.
SAID_BY = "причина-{}"
FETCH: Final = "fetch --quiet"
LS_REMOTE: Final = "ls-remote --exit-code --heads"


@pytest.mark.parametrize("step", sorted(set(REFUSALS) - {LS_REMOTE}))
def test_every_git_step_refuses_with_its_reason(
    stand: dict[str, Path], monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """Отказ любого вызова git несёт его код и `stderr` (взгляды на #1249, #1257, 210).

    Причину чинили по шагу за заход; перечень всех вызовов закрывает круг.
    `fetch` отказывает вместе с `ls-remote`: ветка есть, но не прочитана, и в
    отказе обе причины. `diff --quiet` с кодом не 0 и не 1 — отказ git.
    """
    real: Callable[..., subprocess.CompletedProcess[str]] = module.git
    if REFUSALS[step][1]:
        assert module.publish(stand["source"], stand["tmp"] / "w0", sha="0")
        stand["source"].write_text('{"a": 2}\n', encoding="utf-8")
    failing = {step, LS_REMOTE} if step == FETCH else {step}

    def refusing(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        key = call_key(args)
        if key in failing:
            return subprocess.CompletedProcess(
                list(args), REFUSALS[key][0], "", SAID_BY.format(key)
            )
        return real(*args, cwd=cwd)

    monkeypatch.setattr(module, "git", refusing)
    with pytest.raises(module.NotPublished) as refused:
        module.publish(stand["source"], stand["tmp"] / "w1", sha="a")
    for one in failing:
        assert f"код {REFUSALS[one][0]}: {SAID_BY.format(one)}" in str(refused.value)


def test_the_refusals_cover_every_git_step(
    stand: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Перечень отказов равен ключам вызовов, которые публикация делает на деле.

    Вызовы записываются прогоном, а не разбором текста: и первая публикация
    (ветки нет), и публикация поверх. Новый вызов git без строки в
    `REFUSALS` краснеет здесь — отказ без причины не пройдёт молча (210).
    """
    real: Callable[..., subprocess.CompletedProcess[str]] = module.git
    called: set[str] = set()

    def recording(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        called.add(call_key(args))
        return real(*args, cwd=cwd)

    monkeypatch.setattr(module, "git", recording)
    assert module.publish(stand["source"], stand["tmp"] / "w1", sha="a")
    stand["source"].write_text('{"a": 2}\n', encoding="utf-8")
    assert module.publish(stand["source"], stand["tmp"] / "w2", sha="b")
    assert called == set(REFUSALS)


#: Архив находок — литералом вне модуля, как факты (взгляд на #1240).
PUBLISHED_ARCHIVE = ".github/badges/findings.json"


def test_the_archive_rides_the_same_commit_when_asked(stand: dict[str, Path]) -> None:
    """С входом `archive` архив находок ложится тем же коммитом, что факты (#1414)."""
    (stand["tmp"] / "findings.json").write_text('{"f": 1}\n', encoding="utf-8")
    assert module.publish(stand["source"], stand["tmp"] / "w1", sha="abc", archive=True)
    assert module.ARCHIVE == PUBLISHED_ARCHIVE
    assert on_branch(stand["remote"], PUBLISHED_ARCHIVE) == '{"f": 1}\n'
    assert on_branch(stand["remote"], PUBLISHED_PATH) == '{"a": 1}\n'
    touched = [
        one
        for one in git(
            "show", "--name-only", "-z", "--format=", PUBLISHED_TO, cwd=stand["remote"]
        ).split("\0")
        if one.strip()
    ]
    assert sorted(touched) == sorted(
        [PUBLISHED_PATH, PUBLISHED_PICTURE, PUBLISHED_FAMILY, PUBLISHED_ARCHIVE]
    )


def test_without_the_archive_input_a_foreign_archive_lives(stand: dict[str, Path]) -> None:
    """Без входа шаг архив не трогает: свой файл потребителя по этому пути уцелел."""
    (stand["tmp"] / "findings.json").write_text('{"f": "наш"}\n', encoding="utf-8")
    module.publish(stand["source"], stand["tmp"] / "w1", sha="abc")
    assert git("ls-tree", "--name-only", "-r", "-z", PUBLISHED_TO, cwd=stand["remote"]).split("\0")[
        :-1
    ] == sorted([PUBLISHED_PATH, PUBLISHED_PICTURE, PUBLISHED_FAMILY])


def test_a_missing_archive_does_not_hold_the_facts(
    stand: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Вход есть, а архива нет — факты публикуются, пропуск архива назван (взгляд на #1423)."""
    assert module.publish(stand["source"], stand["tmp"] / "w1", sha="abc", archive=True)
    assert on_branch(stand["remote"], PUBLISHED_PATH) == '{"a": 1}\n'
    assert "findings.json" in capsys.readouterr().out


def test_our_badges_run_asks_the_shared_step_for_the_archive() -> None:
    """Наш `badges.yml` пишет архив тем же общим шагом, что потребитель, а не своим джобом."""
    import yaml

    from tests.conftest import ROOT

    flow = yaml.safe_load((ROOT / ".github/workflows/badges.yml").read_text(encoding="utf-8"))
    assert flow["jobs"]["facts"]["with"]["archive"] is True
    assert "findings_archive.py" not in (ROOT / ".github/workflows/badges.yml").read_text(
        encoding="utf-8"
    )
