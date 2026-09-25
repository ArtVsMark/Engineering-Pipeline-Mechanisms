"""Архив находок взгляда в ветке `badges`: дописывается, связывает находку с родом (#778)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import load_script

module = load_script("findings_archive.py")

KINDS: dict[str, Any] = {
    "каскад по одному месту": {
        "признак": "…",
        "встречен": ["aaaaaaa", "окно: tests/x.py — не отпечаток"],
        "закрыт": "нет — причина",
        "каталогу": "предложено — a-second-finding-on-one-place-stops-the-patching",
    },
    "тихий род": {"признак": "…", "встречен": [], "закрыт": "нет — причина"},
}

#: Ответы верификатора в живом реестре для стенда.
VERIFIED: dict[str, str] = {}


def look(*titles: str) -> dict[str, Any]:
    """Комментарий взгляда с находками."""
    lines = "\n".join(f"НАХОДКА[риск · механик]: {title}" for title in titles)
    return {"user": {"type": "Bot"}, "body": f"{lines}\n\nВЕРДИКТ: находок {len(titles)}"}


def mark(title: str) -> str:
    """Отпечаток находки тем же разбором, что у реестра."""
    return str(module.review_findings.fingerprint(title))


def empty() -> dict[str, Any]:
    """Архив без записей — вход `add_change`."""
    return {"findings": {}, "resolutions": {}}


def test_a_resolution_line_is_read_with_its_twin() -> None:
    """`Разобрано: <отпечаток>` и `… дубль <отпечаток>` — тот же ключ, что у реестра."""
    said = "тело\nРазобрано: abc1234\nРазобрано: `def5678` дубль abc1234\nпроза Разобрано: 1\n"
    assert module.resolved_in(said) == {"abc1234": "", "def5678": "abc1234"}


def test_only_fingerprints_link_a_finding_to_its_kind() -> None:
    """Встреча «окно: …» отпечатком не является и находку с родом не связывает."""
    assert module.kinds_by_mark(KINDS) == {"aaaaaaa": "каскад по одному месту"}


def test_a_change_adds_findings_repeats_and_resolutions() -> None:
    """Новая находка заводится, повтор — звено, снятие — одно, первое."""
    archive = empty()
    module.add_change(archive, 10, [look("a.py:1 — первая")], "")
    one = mark("a.py:1 — первая")
    assert archive["findings"][one]["place"] == "a.py"
    module.add_change(archive, 11, [look("a.py:1 — первая")], f"Разобрано: {one}")
    module.add_change(archive, 12, [], f"Разобрано: {one}")
    module.settle(archive)
    assert archive["findings"][one]["seen_on"] == [10, 11]
    assert archive["findings"][one]["resolved_by"] == 11, "снятие переписано поздним повтором"


def test_a_resolution_counted_before_its_finding_is_kept() -> None:
    """Снятие, учтённое раньше находки, прикладывается к ней потом (взгляд на #788)."""
    archive = empty()
    one = mark("b.py:1 — позже")
    module.add_change(archive, 20, [], f"Разобрано: {one}")
    module.add_change(archive, 30, [look("b.py:1 — позже")], "")
    module.settle(archive)
    assert archive["findings"][one]["resolved_by"] == 20


def test_a_repeat_seen_earlier_moves_the_birth_back() -> None:
    """Изменения учитываются по времени слияния: повтор на меньшем номере — рождение раньше."""
    archive = empty()
    module.add_change(archive, 40, [look("c.py:1 — раз")], "")
    module.add_change(archive, 35, [look("c.py:1 — раз")], "")
    assert archive["findings"][mark("c.py:1 — раз")]["pr"] == 35


def test_a_finding_carries_its_kind_and_the_rule_it_bore() -> None:
    """Находка знает свой род и что из рода родилось — ответ каталогу и выросшее."""
    findings: dict[str, dict[str, Any]] = {"aaaaaaa": {"pr": 1}, "bbbbbbb": {"pr": 2}}
    summary = module.with_kinds(findings, KINDS)
    assert findings["aaaaaaa"]["род"] == "каскад по одному месту"
    assert findings["aaaaaaa"]["правило"]["каталогу"] == {
        "вид": "предложено",
        "сказано": "a-second-finding-on-one-place-stops-the-patching",
    }
    assert findings["bbbbbbb"]["род"] is None and findings["bbbbbbb"]["правило"] is None
    assert summary["каскад по одному месту"]["встреч"] == 1
    assert summary["тихий род"]["каталогу"] is None


def test_rule_of_names_the_catalogue_answer_and_what_grew() -> None:
    """`rule_of`: ответ каталогу разобран, выросшее перечислено; без ответа — пусто."""
    grown = {**KINDS["каскад по одному месту"], "породил": ["tests/x.py — гейт"]}
    assert module.rule_of(grown)["породил"] == ["tests/x.py — гейт"]
    assert module.rule_of(KINDS["тихий род"]) == {"каталогу": None, "породил": []}


def test_the_previous_archive_is_a_file_or_a_start(tmp_path: Path) -> None:
    """Файла нет — начало с нуля; файл не разбирается — отказ, а не чистый лист (045)."""
    assert module.previous(None) == {}
    broken = tmp_path / "prev.json"
    broken.write_text("{не json", encoding="utf-8")
    with pytest.raises(module.NotRun):
        module.previous(broken)


def platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка: закрытые изменения в порядке номеров, слиты — не по порядку."""
    pulls = [
        {"number": 5, "merged_at": "2026-09-24T10:00:00Z", "merge_commit_sha": "s5"},
        {"number": 6, "merged_at": None},
        {"number": 7, "merged_at": "2026-09-24T12:00:00Z", "merge_commit_sha": "s7"},
        {"number": 8, "merged_at": "2026-09-24T11:00:00Z", "merge_commit_sha": "s8"},
    ]
    feeds = {5: [look("a.py:1 — раз")], 7: [look("b.py:2 — два")], 8: []}
    bodies = {"s5": "", "s7": "", "s8": "Разобрано: " + mark("a.py:1 — раз")}

    def paginate(path: str, *_: Any, **__: Any) -> Any:
        if "/pulls?" in path:
            return iter(pulls)
        return iter(feeds[int(path.split("/")[-2])])

    def request(method: str, path: str, *_: Any, **__: Any) -> Any:
        return {"commit": {"message": bodies[path.rsplit("/", 1)[-1]]}}

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    monkeypatch.setattr(module.ghrest, "request", request)
    monkeypatch.setattr(module, "verdicts", lambda repo, token: dict(VERIFIED))


def test_pending_changes_are_taken_by_merge_time_and_skip_the_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Учтённое — множество, а не отметка: слитое позже с меньшим номером не теряется (#788)."""
    platform(monkeypatch)
    assert [one["number"] for one in module.merged_pending("o/r", "t", set())] == [5, 8, 7]
    assert [one["number"] for one in module.merged_pending("o/r", "t", {5, 7})] == [8]
    # Учтён больший номер, а меньший слит позже и ещё нет — отметка его бы потеряла.
    assert [one["number"] for one in module.merged_pending("o/r", "t", {7})] == [5, 8]


def test_the_archive_is_appended_within_budget_and_names_what_is_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Дописывается не больше бюджета; недошедшее до головы названо в `gaps`."""
    platform(monkeypatch)
    kept = {"zzzzzzz": {"pr": 1, "seen_on": [1], "title": "старая", "checked": ""}}
    archive = module.build("o/r", "t", 1, KINDS, {"counted": [5], "findings": kept})
    assert archive["counted"] == [5, 8]
    assert "zzzzzzz" in archive["findings"], "прежняя история потеряна"
    assert any("не учтено слитых изменений — 1" in one for one in archive["gaps"])
    assert module.VERIFIER_GAP in archive["gaps"]


def test_a_first_run_counts_everything_and_settles_resolutions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Архива нет — учитывается всё слитое, снятия прикладываются к находкам."""
    platform(monkeypatch)
    archive = module.build("o/r", "t", 10, KINDS, {})
    assert archive["counted"] == [5, 7, 8] and archive["schema"] == module.SCHEMA
    assert archive["findings"][mark("a.py:1 — раз")]["resolved_by"] == 8
    assert not any("не учтено" in one for one in archive["gaps"])


def test_the_verifier_answer_is_kept_once_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ответ верификатора берётся из реестра и не теряется, когда запись снята."""
    platform(monkeypatch)
    one = mark("b.py:2 — два")
    VERIFIED.clear()
    VERIFIED[one] = "премиса подтверждена 24.09.2026"
    archive = module.build("o/r", "t", 10, KINDS, {})
    assert archive["findings"][one]["checked"] == "премиса подтверждена 24.09.2026"
    VERIFIED.clear()
    again = module.build("o/r", "t", 10, KINDS, archive)
    assert again["findings"][one]["checked"] == "премиса подтверждена 24.09.2026", "ответ потерян"


def test_verdicts_are_read_from_the_live_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """`verdicts` читает живой реестр и берёт только записи с ответом о премисе."""
    body = (
        "- `aaaaaaa` · #7 · риск · премиса подтверждена — a.py:1 — раз\n"
        "- `bbbbbbb` · #7 · риск — b.py:1 — два\n"
    )
    monkeypatch.setattr(module.registry, "live_issue", lambda repo, token: (23, body))
    assert module.verdicts("o/r", "t") == {"aaaaaaa": "премиса подтверждена"}


def test_an_unreadable_history_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Прежний архив не разбирается — файла нет и код отказа (045); без токена — тоже."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    broken = tmp_path / "prev.json"
    broken.write_text("{", encoding="utf-8")
    out = tmp_path / "findings.json"
    args = ["--repo", "o/r", "--out", str(out), "--previous", str(broken)]
    assert module.main(args) == module.EXIT_BROKEN
    assert not out.exists()
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    assert module.main(["--repo", "o/r", "--out", str(out)]) == module.EXIT_BROKEN


def test_a_run_writes_the_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Заход кладёт архив по названному адресу."""
    platform(monkeypatch)
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    out = tmp_path / "deep" / "findings.json"
    assert module.main(["--repo", "o/r", "--out", str(out)]) == module.EXIT_OK
    assert json.loads(out.read_text(encoding="utf-8"))["repo"] == "o/r"


FAKE_GIT = """#!/bin/bash
case "$1" in
  fetch) exit "${FAKE_FETCH:-0}" ;;
  ls-tree)
    [ "${FAKE_TREE:-0}" -ne 0 ] && exit "$FAKE_TREE"
    [ -n "${FAKE_PREV:-}" ] && echo ".github/badges/findings.json"
    exit 0 ;;
  show)
    [ "${FAKE_SHOW:-0}" -ne 0 ] && exit "$FAKE_SHOW"
    printf '%s' "$FAKE_PREV"; exit 0 ;;
  ls-remote) exit "${FAKE_REMOTE:-0}" ;;
esac
exit 99
"""

FAKE_PYTHON = """#!/bin/bash
echo "$@" > "$FAKE_ARGS"
exit "${FAKE_RC:-0}"
"""


def run_archive_step(tmp_path: Path, **fake: str) -> tuple[int, str, str, str]:
    """Исполняет шаг архива под `bash -e`, как площадка, с подменёнными git и python.

    Возвращает код шага, выход в $GITHUB_OUTPUT, аргументы скрипта и вывод.
    Подстроки не отличают ветвление от текста рядом с ним — исполнение отличает.
    """
    flow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/badges.yml").read_text(encoding="utf-8")
    )
    steps = flow["jobs"]["badges"]["steps"]
    run = next(step["run"] for step in steps if step.get("id") == "archive")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("git", FAKE_GIT), ("python", FAKE_PYTHON)):
        (bin_dir / name).write_text(body, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    (tmp_path / "badges/.github/badges").mkdir(parents=True)
    output, args = tmp_path / "output", tmp_path / "args"
    output.touch()
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REPOSITORY": "o/r",
        "GH_TOKEN": "t",
        "FAKE_ARGS": str(args),
        **fake,
    }
    done = subprocess.run(
        ["bash", "-e", "-c", run],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    said = args.read_text(encoding="utf-8") if args.exists() else ""
    return done.returncode, output.read_text(encoding="utf-8"), said, done.stdout


@pytest.mark.parametrize(("remote", "starts"), [("2", True), ("128", False), ("0", False)])
def test_only_an_absent_branch_starts_the_archive_from_zero(
    tmp_path: Path, remote: str, starts: bool
) -> None:
    """Непрочитанная ветка: с нуля — только на коде 2, отказ сети (128) и прочее — стоп."""
    code, _, said, _ = run_archive_step(tmp_path, FAKE_FETCH="1", FAKE_REMOTE=remote)
    if starts:
        assert code == 0 and said and "--previous" not in said
    else:
        assert code == 1, f"ls-remote {remote}: архив собрался бы с нуля поверх истории"
        assert not said, "скрипт архива не должен был запускаться"


def test_a_read_branch_hands_the_previous_archive_on(tmp_path: Path) -> None:
    """Прочитанный архив уходит скрипту, и переноса нет."""
    code, output, said, _ = run_archive_step(tmp_path, FAKE_PREV="{}")
    assert code == 0 and "--previous" in said
    assert "carried" not in output


def test_a_failed_script_carries_the_archive_and_says_so(tmp_path: Path) -> None:
    """Отказ скрипта переносит прежний файл и оставляет выход, на котором краснеет прогон."""
    code, output, _, _ = run_archive_step(tmp_path, FAKE_PREV='{"old": 1}', FAKE_RC="3")
    assert code == 0, "перенос не должен останавливать публикацию фактов"
    kept = tmp_path / "badges/.github/badges/findings.json"
    assert kept.read_text(encoding="utf-8") == '{"old": 1}'
    assert "carried=3" in output, "перенос без следа — архив замер бы молча"


def test_a_carried_archive_turns_the_run_red_after_publishing() -> None:
    """Последний шаг — после публикации — краснеет на выходе переноса."""
    flow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/badges.yml").read_text(encoding="utf-8")
    )
    steps = flow["jobs"]["badges"]["steps"]
    names = [step.get("name") for step in steps]
    # Шаги берутся по имени, а не по месту: «последний шаг» ломался бы от
    # любого шага, добавленного после (взгляд на #791).
    guard = steps[names.index("архив не замер")]
    assert names.index("опубликовать в ветку badges") < names.index("архив не замер")
    assert guard.get("if") == "steps.archive.outputs.carried != ''"
    assert "exit 1" in guard["run"], "замерший архив зеленел бы вместе с прогоном"


@pytest.mark.parametrize(
    ("fake", "why"), [({"FAKE_TREE": "128"}, "ls-tree"), ({"FAKE_SHOW": "128"}, "show")]
)
def test_an_unread_archive_on_a_read_branch_stops_publishing(
    tmp_path: Path, fake: dict[str, str], why: str
) -> None:
    """Ветка прочитана, а архив в ней — нет: стоп, а не сборка с нуля (взгляд на #791)."""
    code, _, said, _ = run_archive_step(tmp_path, FAKE_PREV="{}", **fake)
    assert code == 1, f"отказ {why} собрал бы архив с нуля поверх истории"
    assert not said, "скрипт архива не должен был запускаться"


def test_an_absent_archive_on_a_read_branch_starts_from_zero(tmp_path: Path) -> None:
    """Файла на ветке нет (пустой ответ `ls-tree`) — наполнение с начала."""
    code, _, said, _ = run_archive_step(tmp_path)
    assert code == 0 and said and "--previous" not in said


def test_real_git_names_an_absent_branch_by_code_two(tmp_path: Path) -> None:
    """Посылка развилки — у настоящего git, а не у подмены: нет ветки — код 2.

    Подмена в тестах шага отдаёт коды сама, и без этой сверки вся починка
    держалась бы на коде, который тест назначил (взгляд на #791).
    """
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(bare)], check=True)
    done = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", str(bare), "badges"],
        capture_output=True,
        check=False,
    )
    assert done.returncode == 2
    missing = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", str(tmp_path / "нет.git"), "badges"],
        capture_output=True,
        check=False,
    )
    assert missing.returncode not in (0, 2), "недоступный адрес дал бы «ветки нет»"


def test_real_git_names_an_absent_file_by_an_empty_listing(tmp_path: Path) -> None:
    """Вторая посылка — тоже у настоящего git: нет файла — пустой вывод и код 0.

    Подмена `FAKE_GIT` отдаёт этот ответ сама, и без сверки развилка «архива
    нет» держалась бы на выводе, который назначил тест (второй взгляд на #791).
    """
    repo = tmp_path / "r"

    def run(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=check,
        )

    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    run(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "--quiet",
        "--allow-empty",
        "-m",
        "пусто",
        check=True,
    )
    path = ".github/badges/findings.json"
    empty = run("ls-tree", "-z", "--name-only", "HEAD", "--", path)
    assert (empty.returncode, empty.stdout) == (0, ""), "отсутствие файла не пустой ответ"
    (repo / ".github/badges").mkdir(parents=True)
    (repo / path).write_text("{}", encoding="utf-8")
    run("add", path, check=True)
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "архив", check=True)
    listed = run("ls-tree", "-z", "--name-only", "HEAD", "--", path)
    assert listed.returncode == 0 and listed.stdout.rstrip("\0") == path
    broken = run("ls-tree", "-z", "--name-only", "нет-такой-ревизии", "--", path)
    assert broken.returncode != 0, "сбой ls-tree неотличим от отсутствия файла"


def test_the_archive_reads_a_twin_line_as_the_registry_does() -> None:
    """Архив снимает всю цепочку дублей тем же разбором, что реестр (взгляд на #809, 090)."""
    line = "Разобрано: aaaaaaa, ccccccc дубль bbbbbbb\nРазобрано: 1111111 дубль 22222223\n"
    said = module.resolved_in(line)
    assert said == {"aaaaaaa": "bbbbbbb", "ccccccc": "bbbbbbb", "bbbbbbb": "", "1111111": ""}
    assert set(said) == set(module.changerefs.resolved_in(line))


@pytest.mark.parametrize(
    "said",
    [
        '{"counted": 5}',
        '{"findings": []}',
        '{"resolutions": []}',
        '{"resolutions": {"abc1234": 5}}',
        '{"resolutions": {"abc1234": {"twin_of": ""}}}',
        '{"findings": {"abc1234": {"title": "x"}}}',
    ],
    ids=[
        "скаляр в counted",
        "ложная findings",
        "resolutions списком",
        "снятие числом",
        "снятие без by",
        "находка без seen_on",
    ],
)
def test_a_foreign_previous_archive_is_a_refusal(tmp_path: Path, said: str) -> None:
    """Прежний архив чужой формы — отказ сборки, а не трасса и не пустой архив (#822)."""
    path = tmp_path / "findings.json"
    path.write_text(said, encoding="utf-8")
    with pytest.raises(module.NotRun):
        module.previous(path)


def test_a_null_resolutions_reads_as_empty(tmp_path: Path) -> None:
    """`resolutions: null` читается пустым, как `findings: null`: одна форма — один исход (#830)."""
    path = tmp_path / "findings.json"
    path.write_text('{"findings": null, "resolutions": null}', encoding="utf-8")
    assert module.previous(path)["resolutions"] is None


def test_a_later_twin_line_keeps_the_link() -> None:
    """«Разобрано: A», затем «A дубль B» — связь A→B не теряется (взгляд на #814)."""
    body = "\n".join(
        module.changerefs.resolutions_in_all(
            ["Разобрано: aaaaaaa", "Разобрано: aaaaaaa дубль bbbbbbb"]
        )
    )
    assert module.resolved_in(body) == {"aaaaaaa": "bbbbbbb", "bbbbbbb": ""}


def test_a_twin_named_by_a_later_change_joins_the_earlier_resolution() -> None:
    """Связь, названная следующим изменением, дописывается к раннему снятию, а снял — первый."""
    archive: dict[str, Any] = {"findings": {}, "resolutions": {}}
    module.add_change(archive, 1, [], "Разобрано: aaaaaaa")
    module.add_change(archive, 2, [], "Разобрано: aaaaaaa дубль bbbbbbb")
    assert archive["resolutions"]["aaaaaaa"] == {"by": 1, "twin_of": "bbbbbbb"}
    assert archive["resolutions"]["bbbbbbb"] == {"by": 2, "twin_of": ""}


def test_opposite_twin_lines_do_not_make_a_loop() -> None:
    """«A дубль B», затем «B дубль A» — связь остаётся первой, круга нет (взгляд на #824)."""
    body = "Разобрано: aaaaaaa дубль bbbbbbb\nРазобрано: bbbbbbb дубль aaaaaaa"
    assert module.resolved_in(body) == {"aaaaaaa": "bbbbbbb", "bbbbbbb": ""}
    archive: dict[str, Any] = {"findings": {}, "resolutions": {}}
    module.add_change(archive, 1, [], "Разобрано: aaaaaaa дубль bbbbbbb")
    module.add_change(archive, 2, [], "Разобрано: bbbbbbb дубль aaaaaaa")
    assert archive["resolutions"]["bbbbbbb"]["twin_of"] == ""


def test_loops_back_follows_the_chain() -> None:
    """Круг узнаётся и через звено посередине: C → A при A → B → C."""
    links = {"aaaaaaa": "bbbbbbb", "bbbbbbb": "ccccccc"}
    assert module.loops_back("aaaaaaa", "ccccccc", links) is True
    assert module.loops_back("ddddddd", "ccccccc", links) is False
