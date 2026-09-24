"""Архив находок взгляда в ветке `badges`: дописывается, связывает находку с родом (#778)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

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


def test_the_workflow_carries_the_archive_over_a_failure() -> None:
    """Отказ шага переносит прежний архив, непрочитанная ветка останавливает публикацию."""
    flow = (Path(__file__).parents[1] / ".github/workflows/badges.yml").read_text(encoding="utf-8")
    step = flow[flow.index("- name: дописать архив находок") :]
    step = step[: step.index("- name: опубликовать в ветку badges")]
    assert 'git show FETCH_HEAD:.github/badges/findings.json > "$prev"' in step
    assert 'cp "$prev" "$out"' in step, "отказ шага снял бы архив с перезаписанной ветки"
    assert "exit 1" in step, "непрочитанная ветка перезаписалась бы без архива"
