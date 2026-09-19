"""Сверка потребителей: факты читаются у них, адреса ведутся у нас.

Версия, на которой стоит потребитель, и то, какие шаги он обошёл, лежат в ЕГО
`.pipeline.yml`: факты о проекте публикует сам проект (174). Реестр, ведомый за
потребителя, разошёлся бы с ним молча — и разошёлся бы в ту сторону, где мы
считаем, что всё хорошо. Проверяется здесь то, без чего сверка была бы вторым
реестром:

* адреса берутся из объявленного реестра, а запись обязана назвать себя целиком;
* обход виден как обход, и обход БЕЗ ПРИЧИНЫ назван отдельно (154);
* пустой список — состояние, а не отказ и не тишина;
* непрочитанный ответ — третий исход, а не «все на свежей версии» (045).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script

module = load_script("consumers.py")
policy = load_script("pipeline_checks.py")


def registry_with(tmp_path: Path, *rows: dict[str, Any]) -> Path:
    """Дерево с реестром адресов — настоящим файлом, а не подменённым чтением."""
    (tmp_path / ".rules").mkdir(parents=True)
    (tmp_path / ".rules" / "consumers.json").write_text(
        json.dumps({"connected": list(rows)}, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


def answering(monkeypatch: pytest.MonkeyPatch, said: str) -> None:
    """Потребитель отдаёт свой ответ — так, как его отдаёт площадка: в base64."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    monkeypatch.setattr(
        module.ghrest,
        "request",
        lambda *_, **__: {"content": base64.b64encode(said.encode()).decode()},
    )


def test_an_empty_registry_is_a_state_not_a_refusal(tmp_path: Path) -> None:
    """Подключённых нет — состояние, а не отказ и не тишина (154).

    Отказ здесь означал бы «проект обязан иметь потребителей», а тишина —
    «все на свежей версии», чего никто не проверял.
    """
    assert module.main(["--root", str(registry_with(tmp_path))]) == module.EXIT_OK


def test_a_row_must_name_itself(tmp_path: Path) -> None:
    """Запись без адреса, даты или причины — отказ входа, а не полузапись."""
    root = registry_with(tmp_path, {"repo": "o/r"})
    with pytest.raises(module.NotRun, match="since"):
        module.registry(root)


def test_a_missing_registry_does_not_run(tmp_path: Path) -> None:
    """Реестра нет — у кого спрашивать, взять неоткуда (075)."""
    assert module.main(["--root", str(tmp_path)]) == module.EXIT_BROKEN


def test_a_bypass_is_seen_as_a_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Шаг, объявленный выключенным, виден обходом — с причиной и без."""
    answering(monkeypatch, 'checks:\n  "lint / lint":\n    class: off\n    why: свой линтер\n')
    assert module.bypassed(module.answer_of("o/r", "токен")) == ["lint / lint"]


def test_a_bypass_without_a_reason_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обход БЕЗ причины называется отдельно: это молчание, а не состояние.

    Вторая половина. Без неё сверка показывала бы объявленный и необъявленный
    обход одинаково — то есть ровно то, ради чего объявление и заведено (154).
    """
    answering(monkeypatch, 'checks:\n  "lint / lint": off\n')
    assert module.bypassed(module.answer_of("o/r", "токен")) == ["lint / lint — БЕЗ ПРИЧИНЫ"]


def test_a_live_step_is_not_a_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подключённый шаг обходом не считается — иначе предикат шире предмета."""
    answering(monkeypatch, 'checks:\n  "lint / lint": required\n  "debt / debt": advisory\n')
    assert module.bypassed(module.answer_of("o/r", "токен")) == []


def test_an_unread_answer_is_its_own_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ответ не прочитан — третий исход, а не «все на свежей версии» (045)."""
    root = registry_with(tmp_path, {"repo": "o/r", "since": "2026-09-19", "why": "берёт линтер"})
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")

    def broken(*_: object, **__: object) -> Any:
        raise module.ghrest.TransportError("404")

    monkeypatch.setattr(module.ghrest, "request", broken)
    assert module.main(["--root", str(root)]) == module.EXIT_UNREAD


def test_without_a_token_the_answers_are_not_guessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Токена нет — ответы НЕ прочитаны, и это сказано, а не выдано за чистоту."""
    root = registry_with(tmp_path, {"repo": "o/r", "since": "2026-09-19", "why": "берёт линтер"})
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    assert module.main(["--root", str(root)]) == module.EXIT_UNREAD


def test_the_live_registry_is_readable() -> None:
    """Живой реестр дерева разбирается и называет свою пустоту словами (139)."""
    said = json.loads((ROOT / module.paths.CONSUMERS).read_text(encoding="utf-8"))
    assert module.CONNECTED in said, "в реестре нет раздела подключённых"
    assert not said[module.CONNECTED], "подключённые появились — перемерьте этот прогон"
    assert any("пуст" in key for key in said), "пустота реестра не названа причиной (154)"
