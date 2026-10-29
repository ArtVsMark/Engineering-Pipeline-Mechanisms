"""Чужой текст кодом строки — отданное семье обезвреживание (#1782, правило 230)."""

import pytest
import untrusted

from tests.conftest import load_script

registry = load_script("feedback_registry.py")


@pytest.mark.parametrize(
    ("said", "shown"),
    [
        ("@someone посмотри #12", "`@someone посмотри #12`"),
        ("строка\n## заголовок\n- пункт", "`строка ## заголовок - пункт`"),
        ("<!-- метка -->", "`<! -- метка -->`"),
        ("a`b", "``a`b``"),
        ("`край", "`` `край ``"),
        ("   ", ""),
    ],
    ids=[
        "упоминание-и-ссылка",
        "многострочный",
        "метка",
        "кавычка-внутри",
        "кавычка-у-края",
        "пусто",
    ],
)
def test_foreign_text_becomes_an_inert_code_span(said: str, shown: str) -> None:
    """Упоминание, ссылка, заголовок и метка не действуют: всё — код одной строки (230)."""
    assert untrusted.quoted(said) == shown


def test_the_registry_quotes_through_the_package() -> None:
    """Реестр соседей зовёт пакетное ограждение, а невидимое делает видимым сам (#1782, 214)."""
    assert registry.quoted("@сосед") == untrusted.quoted("@сосед")
    assert registry.MARK_OPEN == untrusted.MARK_OPEN
    assert "\\u{200b}" in registry.quoted(f"a{chr(0x200B)}b")
