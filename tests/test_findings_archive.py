"""Архив находок взгляда в ветке `badges`: дописывается, связывает находку с родом (#778)."""

from __future__ import annotations

import base64
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


def look(*titles: str) -> dict[str, Any]:
    """Комментарий взгляда с находками."""
    lines = "\n".join(f"НАХОДКА[риск · механик]: {title}" for title in titles)
    return {"user": {"type": "Bot"}, "body": f"{lines}\n\nВЕРДИКТ: находок {len(titles)}"}


def test_a_resolution_line_is_read_with_its_twin() -> None:
    """`Разобрано: <отпечаток>` и `… дубль <отпечаток>` — тот же ключ, что у реестра."""
    said = "тело\nРазобрано: abc1234\nРазобрано: `def5678` дубль abc1234\nпроза Разобрано: 1\n"
    assert module.resolved_in(said) == {"abc1234": "", "def5678": "abc1234"}


def test_only_fingerprints_link_a_finding_to_its_kind() -> None:
    """Встреча «окно: …» отпечатком не является и находку с родом не связывает."""
    assert module.kinds_by_mark(KINDS) == {"aaaaaaa": "каскад по одному месту"}


def test_a_change_adds_findings_repeats_and_resolutions() -> None:
    """Новая находка заводится, повтор на другом изменении — звено, снятие — один раз."""
    findings: dict[str, Any] = {}
    module.add_change(findings, 10, [look("a.py:1 — первая")], "")
    mark = next(iter(findings))
    assert findings[mark]["place"] == "a.py" and findings[mark]["role"] == "механик"
    module.add_change(findings, 11, [look("a.py:1 — первая")], f"Разобрано: {mark}")
    assert findings[mark]["seen_on"] == [10, 11]
    assert findings[mark]["resolved_by"] == 11
    module.add_change(findings, 12, [], f"Разобрано: {mark}")
    assert findings[mark]["resolved_by"] == 11, "снятие переписано поздним повтором"


def test_a_finding_carries_its_kind_and_the_rule_it_bore() -> None:
    """Находка знает свой род и что из рода родилось — ответ каталогу и выросшее."""
    findings: dict[str, dict[str, Any]] = {"aaaaaaa": {"pr": 1}, "bbbbbbb": {"pr": 2}}
    summary = module.with_kinds(findings, KINDS)
    born = findings["aaaaaaa"]["правило"]
    assert findings["aaaaaaa"]["род"] == "каскад по одному месту"
    assert born["каталогу"] == {
        "вид": "предложено",
        "сказано": "a-second-finding-on-one-place-stops-the-patching",
    }
    assert findings["bbbbbbb"]["род"] is None and findings["bbbbbbb"]["правило"] is None
    assert summary["каскад по одному месту"]["встреч"] == 1
    assert summary["тихий род"]["каталогу"] is None


def test_an_absent_archive_is_a_start_and_an_unread_one_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """404 — архива ещё нет; любой другой отказ — история есть, но не прочитана (045)."""

    def gone(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("GET … → 404: Not Found")

    monkeypatch.setattr(module.ghrest, "request", gone)
    assert module.previous("o/r", "t") is None

    def down(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("GET … → 503: Unavailable")

    monkeypatch.setattr(module.ghrest, "request", down)
    with pytest.raises(module.NotRun):
        module.previous("o/r", "t")
    monkeypatch.setattr(module.ghrest, "request", lambda *_a, **_k: {"content": "не base64 json"})
    with pytest.raises(module.NotRun):
        module.previous("o/r", "t")


#: Ответы верификатора в живом реестре для стенда.
VERIFIED: dict[str, str] = {}


def platform(monkeypatch: pytest.MonkeyPatch, before: dict[str, Any] | None) -> None:
    """Площадка: прежний архив, три закрытых изменения, ленты и тела слияний."""
    pulls = [
        {"number": 5, "merged_at": "x", "merge_commit_sha": "s5"},
        {"number": 6, "merged_at": None},
        {"number": 7, "merged_at": "x", "merge_commit_sha": "s7"},
        {"number": 8, "merged_at": "x", "merge_commit_sha": "s8"},
    ]
    feeds = {5: [look("a.py:1 — раз")], 7: [look("b.py:2 — два")], 8: []}

    def paginate(path: str, *_: Any, **__: Any) -> Any:
        if "/pulls?" in path:
            return iter(pulls)
        return iter(feeds[int(path.split("/")[-2])])

    def request(method: str, path: str, *_: Any, **__: Any) -> Any:
        if "/contents/" in path:
            if before is None:
                raise module.ghrest.TransportError("→ 404")
            return {"content": base64.b64encode(json.dumps(before).encode()).decode()}
        return {
            "commit": {
                "message": "Разобрано: " + module.review_findings.fingerprint("a.py:1 — раз")
            }
        }

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    monkeypatch.setattr(module.ghrest, "request", request)
    monkeypatch.setattr(module, "verdicts", lambda repo, token: dict(VERIFIED))


def test_the_archive_is_appended_after_its_mark_within_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Дописывается слитое после отметки, по возрастанию и не больше бюджета."""
    kept = {"zzzzzzz": {"pr": 1, "seen_on": [1], "resolved_by": None}}
    platform(monkeypatch, {"last_pr": 5, "findings": kept})
    archive = module.build("o/r", "t", 1, KINDS)
    assert archive["last_pr"] == 7, "несмерженное или старое взято, либо бюджет не соблюдён"
    assert "zzzzzzz" in archive["findings"], "прежняя история потеряна"
    assert {one["pr"] for one in archive["findings"].values()} == {1, 7}


def test_a_first_run_starts_from_the_beginning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Архива нет — наполнение с начала, и снятия читаются из тел слияний."""
    platform(monkeypatch, None)
    archive = module.build("o/r", "t", 10, KINDS)
    assert archive["last_pr"] == 8 and archive["schema"] == module.SCHEMA
    first = next(one for one in archive["findings"].values() if one["pr"] == 5)
    assert first["resolved_by"] == 5


def test_an_unread_history_writes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Прежний архив не прочитан — файла нет и код отказа, а не свежий архив (045)."""

    def down(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("→ 503")

    monkeypatch.setattr(module.ghrest, "request", down)
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    out = tmp_path / "findings.json"
    assert module.main(["--repo", "o/r", "--out", str(out)]) == module.EXIT_BROKEN
    assert not out.exists()
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    assert module.main(["--repo", "o/r", "--out", str(out)]) == module.EXIT_BROKEN


def test_a_run_writes_the_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Заход кладёт архив по названному адресу."""
    platform(monkeypatch, None)
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    out = tmp_path / "deep" / "findings.json"
    assert module.main(["--repo", "o/r", "--out", str(out)]) == module.EXIT_OK
    assert json.loads(out.read_text(encoding="utf-8"))["repo"] == "o/r"


def test_the_verifier_answer_is_kept_once_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ответ верификатора берётся из реестра и не теряется, когда запись снята."""
    mark = module.review_findings.fingerprint("b.py:2 — два")
    VERIFIED.clear()
    VERIFIED[mark] = "премиса подтверждена 24.09.2026"
    platform(monkeypatch, None)
    archive = module.build("o/r", "t", 10, KINDS)
    assert archive["findings"][mark]["checked"] == "премиса подтверждена 24.09.2026"
    VERIFIED.clear()
    platform(monkeypatch, archive)
    again = module.build("o/r", "t", 10, KINDS)
    assert again["findings"][mark]["checked"] == "премиса подтверждена 24.09.2026", "ответ потерян"


def test_verdicts_are_read_from_the_live_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """`verdicts` читает живой реестр и берёт только записи с ответом о премисе."""
    body = (
        "- `aaaaaaa` · #7 · риск · премиса подтверждена — a.py:1 — раз\n"
        "- `bbbbbbb` · #7 · риск — b.py:1 — два\n"
    )
    monkeypatch.setattr(module.registry, "live_issue", lambda repo, token: (23, body))
    assert module.verdicts("o/r", "t") == {"aaaaaaa": "премиса подтверждена"}


def test_merged_after_takes_merged_changes_past_the_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    """`merged_after`: только слитые, только после отметки, по бюджету."""
    platform(monkeypatch, None)
    assert [one["number"] for one in module.merged_after("o/r", "t", 5, 10)] == [7, 8]
    assert [one["number"] for one in module.merged_after("o/r", "t", 0, 1)] == [5]


def test_rule_of_names_the_catalogue_answer_and_what_grew() -> None:
    """`rule_of`: ответ каталогу разобран, выросшее перечислено; без ответа — пусто."""
    grown = {**KINDS["каскад по одному месту"], "породил": ["tests/x.py — гейт"]}
    assert module.rule_of(grown)["породил"] == ["tests/x.py — гейт"]
    assert module.rule_of(KINDS["тихий род"]) == {"каталогу": None, "породил": []}
