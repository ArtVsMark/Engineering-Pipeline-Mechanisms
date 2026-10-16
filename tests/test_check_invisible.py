"""Гейт невидимых символов: что краснеет, что законно и как он молчит на исправном (#1429)."""

import subprocess
from pathlib import Path

import pytest

from tests.conftest import RunScript, load_script

module = load_script("check_invisible.py")

REJECTED = 1
CLEAN = 0
BROKEN = 2


def tree(root: Path, files: dict[str, str]) -> Path:
    """Репозиторий теста с отслеживаемыми файлами."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


@pytest.mark.parametrize(
    "char",
    [
        "\u200b",
        "\u200e",
        "\u202e",
        "\u2066",
        "\u2060",
        "\u061c",
        "\u180e",
        "\U000e0041",
        "\u00ad",
        "\u3164",
        "\u034f",
        "\ufe0f\ufe0f",
        "\U000e0100",
    ],
    ids=[
        "zwsp",
        "lrm",
        "rlo",
        "lri",
        "wj",
        "alm",
        "mvs",
        "tag",
        "shy",
        "hangul-filler",
        "cgj",
        "selectors",
        "selector-after-letter",
    ],
)
def test_each_class_is_rejected(run_script: RunScript, tmp_path: Path, char: str) -> None:
    """Каждый класс невидимого краснит гейт и называет место."""
    tree(tmp_path, {"SKILL.md": f"делай так{char} и только так\n"})
    result = run_script("check_invisible.py", cwd=tmp_path)
    assert result.code == REJECTED, result.text
    assert "SKILL.md:1:" in result.text


def test_legal_forms_pass(run_script: RunScript, tmp_path: Path) -> None:
    """BOM в начале, составной эмодзи, один селектор и кириллица — чисто."""
    tree(
        tmp_path,
        {
            "a.md": "\ufeffзаголовок — «кавычки» и ё\n",
            "b.md": "## 🧑\u200d💻 окно\n## ⚠\ufe0f внимание\n🐈\u200d\u2b1b кот\n",
            "c.md": "1\ufe0f\u20e3 шаг · \u845b\U000e0100 иероглиф\n",
        },
    )
    result = run_script("check_invisible.py", cwd=tmp_path)
    assert result.code == CLEAN, result.text


def test_code_is_not_judged(run_script: RunScript, tmp_path: Path) -> None:
    """Литерал в коде законен (снятие BOM у грейдера): предмет — текст-указание (195)."""
    tree(tmp_path, {"strip.py": "text.lstrip('\ufeff\u200b')\n", "a.md": "чисто\n"})
    result = run_script("check_invisible.py", cwd=tmp_path)
    assert result.code == CLEAN, result.text


def test_the_borders_of_the_legal_forms_are_held() -> None:
    """Законная форма не на своём месте — находка: BOM внутри, ZWJ между буквами."""
    assert module.hidden("а\ufeffб")
    assert module.hidden("а\u200dб")
    assert not module.hidden("\ufeffа")


def test_an_ignored_file_and_a_binary_are_not_judged(run_script: RunScript, tmp_path: Path) -> None:
    """Предмет — текст дерева: игнорируемый файл и не-UTF-8 гейт не судит."""
    tree(tmp_path, {"a.md": "чисто\n", ".gitignore": "ignored.md\n"})
    (tmp_path / "ignored.md").write_text("\u202e", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00\x2e\x20")
    subprocess.run(["git", "add", "blob.bin"], cwd=tmp_path, check=True)
    result = run_script("check_invisible.py", cwd=tmp_path)
    assert result.code == CLEAN, result.text


def test_a_new_file_not_yet_added_is_judged(run_script: RunScript, tmp_path: Path) -> None:
    """Файл вне индекса, но не игнорируемый, судится: предполётная видит его до толчка."""
    tree(tmp_path, {"a.md": "чисто\n"})
    (tmp_path / "new.md").write_text("а\u202eб\n", encoding="utf-8")
    result = run_script("check_invisible.py", "--root", str(tmp_path))
    assert result.code == REJECTED, result.text
    assert "new.md:1:2" in result.text


def test_outside_a_repository_it_did_not_run(run_script: RunScript, tmp_path: Path) -> None:
    """Без git дерева судить нечего — «не отработал», а не «чисто» (075)."""
    result = run_script("check_invisible.py", cwd=tmp_path)
    assert result.code == BROKEN, result.text


def test_selector_and_emoji_name_their_blocks() -> None:
    """Селектор — из обоих блоков; эмодзи — знак, между которыми законен соединитель."""
    assert module.selector(chr(0xFE0F)) and module.selector(chr(0xE0100))
    assert not module.selector("а")
    assert module.emoji(chr(0x1F9D1)) and module.emoji(chr(0x26A0))
    assert not module.emoji("б")


def test_varied_names_the_bases_of_a_variation() -> None:
    """Вариант бывает у эмодзи, у знаков `VARIED` и у иероглифа, но не у буквы и не у селектора."""
    assert module.varied(chr(0x26A0)) and module.varied("1") and module.varied(chr(0x845B))
    assert not module.varied("а") and not module.varied(chr(0xFE0F))
