"""Заход агента называет модель и отказ — аннотацией проверки (#673, #663).

Проверяется на файле захода той формы, какую пишет действие
`anthropics/claude-code-action`: список сырых сообщений SDK, первое —
`system/init` с моделью, последнее — `result` с итогом.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("agent_run.py")


def run_file(tmp_path: Path, messages: list[dict[str, Any]]) -> Path:
    """Файл захода на диске — как его кладёт действие в `RUNNER_TEMP`."""
    path = tmp_path / "claude-execution-output.json"
    path.write_text(json.dumps(messages), encoding="utf-8")
    return path


INIT = {"type": "system", "subtype": "init", "model": "claude-opus-5", "tools": []}


def test_the_model_is_read_from_the_init_message() -> None:
    """Модель — из `system/init`; нет такого сообщения — модель не названа."""
    assert module.model_of([INIT, {"type": "assistant"}]) == "claude-opus-5"
    assert module.model_of([{"type": "assistant"}]) == ""


def test_a_failure_is_an_error_result_not_any_result() -> None:
    """Отказ — итог с `is_error`; удачный итог отказом не считается.

    Живой случай 23.09.2026: CLI 2.1.261 не знал имени `claude-opus-5-5`, и
    заход кончался итогом `subtype: success, is_error: true` за 0 с.
    """
    ok = {"type": "result", "subtype": "success", "is_error": False, "result": "ВЕРДИКТ: находок 0"}
    bad = {"type": "result", "subtype": "success", "is_error": True, "result": "model  not\nfound"}
    assert module.failure_of([INIT, ok]) is None
    assert module.failure_of([INIT, bad]) == "model not found"
    silent = {"type": "result", "subtype": "error_during_execution", "is_error": True}
    assert "error_during_execution" in str(module.failure_of([INIT, silent]))


def test_a_run_without_a_result_is_named_cut_not_fine() -> None:
    """Итога нет вовсе — это оборванный заход, а не удачный (045)."""
    assert "итога нет" in str(module.failure_of([INIT]))


def test_a_read_file_names_model_and_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Файл прочитан — исход 0, модель и отказ напечатаны аннотациями."""
    bad = {"type": "result", "subtype": "success", "is_error": True, "result": "404 model"}
    path = run_file(tmp_path, [INIT, bad])
    assert module.main(["--from", str(path), "--call", "взгляд"]) == module.EXIT_OK
    said = capsys.readouterr().out
    assert "::notice::взгляд: модель захода — claude-opus-5" in said
    assert "::error::взгляд: заход отказал — 404 model" in said


def test_a_good_run_says_its_model_and_no_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Удачный заход называет модель и не печатает отказа."""
    ok = {"type": "result", "subtype": "success", "is_error": False, "result": "готово"}
    assert module.main(["--from", str(run_file(tmp_path, [INIT, ok]))]) == module.EXIT_OK
    said = capsys.readouterr().out
    assert "модель захода — claude-opus-5" in said and "::error::" not in said


@pytest.mark.parametrize(
    "raw",
    [None, "{не json", json.dumps({"type": "result"})],
    ids=["нет файла", "не json", "не список"],
)
def test_an_unreadable_file_is_the_second_outcome(tmp_path: Path, raw: str | None) -> None:
    """Файла нет, он не разобрался или он не список — исход 2, а не «всё хорошо»."""
    path = tmp_path / "run.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
    assert module.main(["--from", str(path)]) == module.EXIT_BROKEN


def test_an_action_without_a_file_is_named_a_refusal(capsys: pytest.CaptureFixture[str]) -> None:
    """Пустой `--from` — действие упало раньше агента: отказ назван, исход 0 (`2e92154`).

    Шаг зовётся так только после провала вызова (условие «файл или провал»):
    успех без файла — законный пропуск, и тогда шаг не зовут. Названный
    несуществующий файл — другое дело: это поломка шага, исход 2.
    """
    assert module.main(["--from", "", "--call", "взгляд"]) == module.EXIT_OK
    said = capsys.readouterr().out
    assert said.startswith(f"::error::взгляд: {module.REFUSED} — действие не отдало файла"), said


def test_the_file_form_is_read_once_for_every_reader() -> None:
    """Список сообщений разбирает `messages_of`, и не-словари в нём отбрасываются.

    Этой формой пользуется и `late_look.answer_of`: одно понимание «что такое
    файл захода» на всех читателей (090).
    """
    raw = json.dumps([INIT, "строка вместо сообщения", {"type": "result"}])
    assert module.messages_of(raw) == [INIT, {"type": "result"}]
    with pytest.raises(module.NotRun, match="не список"):
        module.messages_of(json.dumps({"type": "result"}))


def test_a_cancelled_call_is_named_a_cancellation_not_a_refusal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Снятый заход — не отказ агента: слов отказа нет, снятие названо (`6af0b2a`).

    `cancelled` дают тайм-аут задания и отмена группой `cancel-in-progress`,
    когда по той же голове пошёл новый прогон. Слова отказа узнаёт реестр
    слитого без взгляда — и записал бы отказ, которого не было.
    """
    assert module.main(["--from", "", "--call", "взгляд", "--outcome", "cancelled"]) == 0
    said = capsys.readouterr().out
    assert module.REFUSED not in said and "заход снят" in said, said
    assert module.main(["--from", "", "--call", "взгляд", "--outcome", "failure"]) == 0
    assert module.REFUSED in capsys.readouterr().out
