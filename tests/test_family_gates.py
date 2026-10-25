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
            "CALLED",
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
    ids=["вызов", "переписан", "свой", "навык-проза", "никак", "неприменимо"],
)
def test_held_names_each_outcome(answer: dict[str, Any], status: str, said: str) -> None:
    """Каждый исход клетки различим; происхождение сильнее вида механизма."""
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
