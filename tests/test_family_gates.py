"""Карта гейтов семьи: исход клетки, три очереди и файл по сводке каталога (#1425)."""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("family_gates.py")

OURS = "ArtVsMark/Engineering-Pipeline-Mechanisms"


def summary() -> dict[str, Any]:
    """Сводка трёх проектов: мы, сосед с переписанным нашим и сосед со своим гейтом."""
    return {
        "schema": "1.7",
        "generated_at": "2026-10-25T12:00:00+00:00",
        "consumers": [
            {
                "repo": OURS,
                "rules": {
                    "001": "active",
                    "002": "active",
                    "003": "active",
                    "004": "not-applicable",
                },
                "holds": {
                    "001": {"mechanism": "gate", "where": "scripts/a.py"},
                    "002": {"mechanism": "document", "where": "AGENTS.md"},
                    "003": {"mechanism": "document", "where": "AGENTS.md"},
                },
            },
            {
                "repo": "o/сосед",
                "rules": {"001": "active", "002": "active", "003": "active"},
                "holds": {
                    "001": {
                        "mechanism": "gate",
                        "where": "scripts/b.py",
                        "origin": f"{OURS}:scripts/a.py@v1.0.0",
                        "origin_kind": "adapted",
                    },
                    "002": {"mechanism": "gate", "where": "scripts/c.py"},
                    "003": {"mechanism": "none", "where": ""},
                },
            },
        ],
    }


@pytest.mark.parametrize(
    ("answer", "status", "said"),
    [
        (
            {"origin": f"{OURS}:x@v1", "origin_kind": "called", "mechanism": "pipeline"},
            "active",
            "TAKEN",
        ),
        (
            {"origin": f"{OURS}:x@v1", "origin_kind": "copied", "mechanism": "gate"},
            "active",
            "TAKEN",
        ),
        ({"origin": f"{OURS}:x@v1", "mechanism": "gate"}, "active", "UNDECLARED"),
        (
            {"origin": f"{OURS}:x@v1", "origin_kind": "adapted", "mechanism": "document"},
            "active",
            "PROSE",
        ),
        (
            {"origin": f"{OURS}:x@v1", "origin_kind": "adapted", "mechanism": "gate"},
            "active",
            "REWRITTEN",
        ),
        ({"mechanism": "gate"}, "active", "OWN"),
        ({"mechanism": "skill"}, "active", "PROSE"),
        ({"mechanism": "none"}, "active", "NOTHING"),
        ({"mechanism": "gate"}, "not-applicable", "INAPPLICABLE"),
    ],
    ids=[
        "вызов",
        "копия",
        "вид-не-объявлен",
        "документ-с-нашим-origin",
        "переписан",
        "свой",
        "навык-проза",
        "никак",
        "неприменимо",
    ],
)
def test_held_names_each_outcome(answer: dict[str, Any], status: str, said: str) -> None:
    """Каждый исход клетки различим; происхождение решает только у машинного ответа."""
    assert module.held(answer, status) == getattr(module, said)


def test_the_three_queues_come_from_the_map() -> None:
    """Переписанное — к нам; свой гейт соседа, где у нас проза, — раздать; никто — каталогу."""
    found = module.cells(summary())
    assert found["004"][OURS]["held"] == module.INAPPLICABLE, "неприменимое из `rules` пропало"
    said = module.queues(found, OURS)
    assert said["rework"] == [
        {
            "rule": "001",
            "repo": "o/сосед",
            "where": "scripts/b.py",
            "origin": f"{OURS}:scripts/a.py@v1.0.0",
        }
    ]
    assert said["spread"] == [{"rule": "002", "repo": "o/сосед", "where": "scripts/c.py"}]
    assert said["propose"] == ["003"], "правило без машины у всех — кандидат каталогу"


def test_the_map_file_counts_and_names_its_source(tmp_path: Path) -> None:
    """Файл карты: форма, источник, счёт исходов, очереди и сама карта; отказ входа — код 2."""
    where = tmp_path / "where.json"
    where.write_text(json.dumps(summary()), encoding="utf-8")
    out = tmp_path / "out" / "family-gates.json"
    assert module.main(["--summary", str(where), "--out", str(out), "--repo", OURS]) == 0
    said = json.loads(out.read_text(encoding="utf-8"))
    assert said["schema"] == module.SCHEMA and said["source"]["summary"] == "1.7"
    assert said["held"][module.REWRITTEN] == 1 and said["held"][module.INAPPLICABLE] == 1
    assert set(said["queues"]) == set(module.QUEUES) and "001" in said["rules"]
    assert module.document(summary(), OURS)["queues"] == said["queues"]
    assert module.main(["--summary", str(tmp_path / "нет.json"), "--out", str(out)]) == 2


def test_a_copy_is_not_rework_and_a_prose_origin_is_not_a_machine() -> None:
    """Копия — не в «доработать»; документ с нашим origin не снимает правило с «предложить»."""
    data = summary()
    neighbour = data["consumers"][1]["holds"]
    neighbour["001"]["origin_kind"] = "copied"
    neighbour["003"] = {"mechanism": "document", "origin": f"{OURS}:AGENTS.md", "where": ""}
    said = module.queues(module.cells(data), OURS)
    assert said["rework"] == [] and said["propose"] == ["003"]


def test_a_repo_missing_from_the_summary_is_a_refusal(tmp_path: Path) -> None:
    """Нас в сводке нет — код 2, а не правдоподобная очередь «раздать»."""
    with pytest.raises(module.family.NotRun, match="в сводке семьи нет"):
        module.document(summary(), "o/чужой")
    where = tmp_path / "where.json"
    where.write_text(json.dumps(summary()), encoding="utf-8")
    out = tmp_path / "family-gates.json"
    assert module.main(["--summary", str(where), "--out", str(out), "--repo", "o/чужой"]) == 2


def test_the_live_issue_names_each_queue_with_its_addresses() -> None:
    """Тело живой задачи: метка, источник, счёт и три очереди с адресами (шаг 2 #1425)."""
    said = module.document(summary(), OURS)
    body = module.render_issue(said)
    assert body.startswith(module.MARKER)
    assert "доработать у нас" in body and "o/сосед · `scripts/b.py` · от `" in body
    assert "- 002 · o/сосед · `scripts/c.py`" in body and "- 003" in body
    empty = {**said, "queues": {"rework": [], "spread": [], "propose": []}}
    assert module.render_issue(empty).count("Пусто на ") == 3


def test_the_live_issue_is_patched_in_place_and_not_opened_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Задача есть — правится по месту; нет и очереди пусты — не заводится; иначе заводится."""
    sent: list[tuple[str, str]] = []

    def request(method: str, path: str, *_a: object, **_k: object) -> dict[str, object]:
        sent.append((method, path))
        return {}

    monkeypatch.setattr(module.ghrest, "request", request)
    said = module.document(summary(), OURS)
    monkeypatch.setattr(module.findings, "live_issue", lambda *_: (7, "прежнее"))
    module.save("o/r", "t", said, apply=True)
    assert sent == [("PATCH", "repos/o/r/issues/7")]
    sent.clear()
    monkeypatch.setattr(module.findings, "live_issue", lambda *_: (None, ""))
    empty = {**said, "queues": {"rework": [], "spread": [], "propose": []}}
    module.save("o/r", "t", empty, apply=True)
    assert sent == [] and "не завожу" in capsys.readouterr().out
    module.save("o/r", "t", said, apply=True)
    assert sent == [("POST", "repos/o/r/issues")]
    sent.clear()
    module.save("o/r", "t", said, apply=False)
    assert sent == []


def test_the_live_issue_mode_names_its_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Без токена, без файла карты и при отказе площадки — исход 2, а не молчание (039)."""
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    out = tmp_path / "map.json"
    out.write_text(json.dumps(module.document(summary(), OURS)), encoding="utf-8")
    assert module.main(["--map", str(out)]) == module.EXIT_BROKEN
    monkeypatch.setenv("GH_TOKEN", "t")
    assert module.main(["--map", str(tmp_path / "нет.json")]) == module.EXIT_BROKEN

    def refuse(*_a: object, **_k: object) -> None:
        raise module.ghrest.TransportError("площадка молчит")

    monkeypatch.setattr(module.findings, "live_issue", refuse)
    assert module.main(["--map", str(out), "--apply"]) == module.EXIT_BROKEN
    with pytest.raises(SystemExit):
        module.main(["--out", str(out)])


def test_write_issue_reads_the_built_map_and_saves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`write_issue` читает файл карты и отдаёт его `save`; без токена — исход 2."""
    out = tmp_path / "map.json"
    out.write_text(json.dumps(module.document(summary(), OURS)), encoding="utf-8")
    seen: list[bool] = []
    monkeypatch.setattr(module, "save", lambda repo, token, said, *, apply: seen.append(apply))
    monkeypatch.setenv("GH_TOKEN", "t")
    assert module.write_issue(out, OURS, apply=True) == module.EXIT_OK and seen == [True]
    monkeypatch.delenv("GH_TOKEN")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert module.write_issue(out, OURS, apply=False) == module.EXIT_BROKEN
