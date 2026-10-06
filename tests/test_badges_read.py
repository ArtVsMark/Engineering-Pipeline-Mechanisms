"""Производное с ветки `badges` читается API площадки блобом (#1158, #1162)."""

import base64
import json
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("badges_read.py")


def blob_of(said: Any) -> str:
    """Содержимое блоба так, как его отдаёт площадка: base64 с переносами."""
    raw = base64.b64encode(json.dumps(said).encode()).decode()
    return "\n".join(raw[i : i + 60] for i in range(0, len(raw), 60))


def test_a_file_is_read_as_a_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сначала `sha` из `contents` ветки `badges`, затем блоб по нему."""
    asked: list[str] = []

    def request(method: str, path: str, token: str, body: Any = None) -> Any:
        asked.append(path)
        return {"sha": "b10b"} if "/contents/" in path else {"content": blob_of({"a": 1})}

    monkeypatch.setattr(module.ghrest, "request", request)
    assert module.by_api("o/r", "facts.json", "t") == {"a": 1}
    assert asked == [
        "repos/o/r/contents/.github/badges/facts.json?ref=badges",
        "repos/o/r/git/blobs/b10b",
    ]


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param([{}], id="блоб не назван"),
        pytest.param([{"sha": "b"}, {"content": "не base64!"}], id="не разбирается"),
        pytest.param([{"sha": "b"}, {"content": blob_of([1, 2])}], id="не словарь"),
    ],
)
def test_an_unreadable_file_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch, answers: list[dict[str, Any]]
) -> None:
    """Нечитаемое — отказ транспорта, а не пустой словарь (045)."""
    said = iter(answers)
    monkeypatch.setattr(module.ghrest, "request", lambda *_a, **_k: next(said))
    with pytest.raises(module.ghrest.TransportError):
        module.by_api("o/r", "facts.json", "t")
