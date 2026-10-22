"""Выпуск договора фактов (#1563): собирается и проверяется у издателя, тег не переставляется.

Переехало из каталога; своё здесь — публикация общим транспортом, а не `gh`.
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

fr = load_script("facts_release.py")


def test_the_selftest_is_two_sided() -> None:
    """Сборка проверяется у «издателя», порча и стоящий тег — отказ."""
    assert fr.selftest() == 0


def test_a_standing_tag_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Стоящий тег не переставляется — исход 1."""
    monkeypatch.setattr(fr, "tag_exists", lambda _tag: True)
    argv = ["facts_release.py", "--dist", str(tmp_path / "d"), "--notes", str(tmp_path / "n.md")]
    monkeypatch.setattr(sys, "argv", argv)
    assert fr.main() == 1


def test_without_a_dist_is_the_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без каталога выпуска шаг не отработал — исход 2."""
    monkeypatch.setattr(sys, "argv", ["facts_release.py"])
    assert fr.main() == 2


def test_the_page_names_the_source_at_the_mechanisms() -> None:
    """Страница называет источник по тегу у механизмов и сам тег."""
    text = fr.notes("2.1.0", "ArtVsMark/Engineering-Pipeline-Mechanisms")
    assert (
        "Engineering-Pipeline-Mechanisms/blob/facts-v2.1.0/export/facts/facts-contract.md" in text
    )
    assert "facts-v2.1.0" in text


def test_publish_sets_the_page_and_attaches_every_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Страница — с тегом на коммите и не «последним»; все пять файлов приложены."""
    dist = tmp_path / "dist"
    fr.assemble(dist)
    asked: list[tuple[str, Any]] = []
    uploaded: list[str] = []

    def request(method: str, path: str, token: str, body: Any = None) -> Any:
        asked.append((path, body))
        return {"upload_url": "https://uploads.github.com/repos/o/r/releases/1/assets{?name}"}

    def upload(url: str, name: str, data: bytes, token: str) -> dict[str, Any]:
        assert data == (dist / name).read_bytes()
        uploaded.append(name)
        return {"name": name}

    monkeypatch.setattr(fr.ghrest, "request", request)
    monkeypatch.setattr(fr.ghrest, "upload_asset", upload)
    said = fr.publish("o/r", "facts-v2.1.0", "2.1.0", "abc", dist, "текст", "t")
    assert "facts-v2.1.0" in said
    ((path, body),) = asked
    assert path == "repos/o/r/releases"
    assert body["tag_name"] == "facts-v2.1.0"
    assert body["target_commitish"] == "abc"
    assert body["make_latest"] == "false"
    assert body["body"] == "текст"
    assert sorted(uploaded) == sorted(one.name for one in fr.ASSETS)


@pytest.mark.parametrize(("token", "target"), [("", "abc"), ("t", "")])
def test_publish_needs_a_token_and_a_target(tmp_path: Path, token: str, target: str) -> None:
    """Без токена человека или без коммита тега — отказ транспорта до запроса."""
    with pytest.raises(fr.ghrest.TransportError):
        fr.publish("o/r", "facts-v2.1.0", "2.1.0", target, tmp_path, "", token)


def test_a_page_without_upload_address_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Страница без адреса загрузки — отказ: страница без проверки хуже отсутствующей."""
    monkeypatch.setattr(fr.ghrest, "request", lambda *_a, **_k: {"id": 1})
    with pytest.raises(fr.ghrest.TransportError, match="без адреса загрузки"):
        fr.publish("o/r", "facts-v2.1.0", "2.1.0", "abc", tmp_path, "", "t")


def test_tag_for_is_named_by_the_contract_number() -> None:
    """`tag_for`: тег — `facts-v` и номер; иная форма номера — отказ."""
    assert fr.tag_for("2.1.0\n") == "facts-v2.1.0"
    with pytest.raises(ValueError):
        fr.tag_for("2.1")


def test_step_files_reads_the_download_list_of_the_ci_step() -> None:
    """`step_files`: список строки `for f in … ; do`, без строки — пусто."""
    step = "dir=x\nfor f in check_facts.py facts.schema.json facts.version; do\n  :\ndone"
    assert fr.step_files(step) == ["check_facts.py", "facts.schema.json", "facts.version"]
    assert fr.step_files("echo нет") == []


def test_verify_passes_the_assembled_release_and_names_a_broken_one(tmp_path: Path) -> None:
    """`verify`: собранный выпуск чист у издателя, испорченный образец — назван."""
    dist = tmp_path / "dist"
    fr.assemble(dist)
    example = dist / fr.check_facts.EXAMPLE_PATH.name
    repo = str(json.loads(example.read_text(encoding="utf-8"))["repo"])
    assert fr.verify(dist, repo) == []
    example.write_text("{}", encoding="utf-8")
    assert fr.verify(dist, repo)
