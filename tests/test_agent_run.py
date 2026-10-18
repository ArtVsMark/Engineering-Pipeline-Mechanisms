"""Заход агента называет модель и отказ — аннотацией проверки (#673, #663).

Проверяется на файле захода той формы, какую пишет действие
`anthropics/claude-code-action`: список сырых сообщений SDK, первое —
`system/init` с моделью, последнее — `result` с итогом.
"""

import json
from pathlib import Path
from typing import Any

import pytest
import report

from tests.conftest import ROOT, load_script, walk

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
    # Причину шаг не знает: замена новым прогоном бывает не у всех групп, а
    # ручную отмену прежний текст не называл вовсе (взгляд на #742).
    assert "ручная отмена" in said and "где группа прогона это объявляет" in said, said
    assert module.main(["--from", "", "--call", "взгляд", "--outcome", "failure"]) == 0
    assert module.REFUSED in capsys.readouterr().out


def test_every_copy_of_the_cancellation_note_names_every_cause() -> None:
    """Комментарий о снятии у КАЖДОГО вызова называет ручную отмену и подписан дублем.

    Первая починка тронула две копии из пяти, и три оставшиеся нашёл поздний
    взгляд на #770 (195). Копии законны только подписанными (071), а причины
    снятия — ручная отмена у всех, замена новым прогоном — где группа её
    объявляет — обязаны быть названы в каждой.
    """
    flows = walk(ROOT / ".github" / "workflows", "*.yml")
    notes = [
        (flow.name, block)
        for flow in flows
        for block in flow.read_text(encoding="utf-8").split("# Снятое задание")[1:]
    ]
    # Обе формы вызова: из дерева и из выкачки общего шага (#993).
    calls = sum(
        flow.read_text(encoding="utf-8").count(form)
        for flow in flows
        for form in ("python scripts/agent_run.py", "python $MECHANISMS/scripts/agent_run.py")
    )
    assert calls, "вызовов agent_run.py не найдено — предмета нет (075)"
    assert len(notes) == calls, f"комментарий о снятии у {len(notes)} вызовов из {calls}"
    for name, block in notes:
        head = block[: block.index("(071)") + 5] if "(071)" in block else block[:600]
        assert "ручная отмена" in head, f"{name}: копия не называет ручную отмену"
        assert "ПОДПИСАННЫЙ ДУБЛЬ" in head, f"{name}: копия не подписана как дубль (071)"


# --- заход без вердикта (#1480) ------------------------------------------------


def bash(command: str, *, background: bool = False) -> dict[str, Any]:
    """Сообщение агента с одним вызовом оболочки — той формы, какую пишет SDK."""
    given: dict[str, Any] = {"command": command}
    if background:
        given["run_in_background"] = True
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Bash", "input": given}]},
    }


def result(text: str = "готово", denials: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Итог захода: успех, текст и отказы разрешений."""
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": text,
        "permission_denials": denials or [],
    }


#: Комментарий взгляда пишет инструмент, а не итог: строка вердикта живёт там.
COMMENT = {
    "type": "assistant",
    "message": {
        "content": [
            {
                "type": "tool_use",
                "name": "mcp__github_comment__update_claude_comment",
                "input": {"body": "находок нет\n\nВЕРДИКТ: находок 0"},
            }
        ]
    },
}


def test_every_review_call_waits_for_its_answer_line() -> None:
    """Каждый заход `step-review.yml` ждёт свою строку ответа — и верификатор тоже (195).

    У взгляда и позднего взгляда ответ — `ВЕРДИКТ:`, у верификатора — `ПРЕМИСА:`.
    Запрет фона получили все три, а ожидание строки — сперва только двое, и заход
    верификатора без ответа не назывался (поздний взгляд на #1495).
    """
    flow = (ROOT / ".github" / "workflows" / "step-review.yml").read_text(encoding="utf-8")
    calls = [line for line in flow.splitlines() if "scripts/agent_run.py --from" in line]
    assert len(calls) == 3, calls
    expected = {"взгляд": "ВЕРДИКТ:", "верификатор": "ПРЕМИСА:", "поздний взгляд": "ВЕРДИКТ:"}
    for call, line in expected.items():
        found = [one for one in calls if f'--call "{call}"' in one]
        assert len(found) == 1, f"{call}: вызов найден {len(found)} раз (075)"
        assert f'--expect "{line}"' in found[0], f"{call}: не ждёт строки «{line}»"


def test_the_background_calls_are_named() -> None:
    """Вызов оболочки, уведённый в фон, назван командой; передний план — нет."""
    messages = [INIT, bash("python -m pytest -q"), bash("python -m pytest", background=True)]
    assert module.background_of(messages) == ["python -m pytest"]


def test_the_permission_denials_are_named_with_their_command() -> None:
    """Отказы разрешений — из итога, с инструментом и его командой или путём."""
    denials: list[Any] = [
        {"tool_name": "Bash", "tool_input": {"command": "cd x &&\n python -m pytest"}},
        {"tool_name": "Write", "tool_input": {"file_path": "a.py"}},
        {"tool_name": "WebFetch", "tool_input": {}},
        "не словарь",
    ]
    said = module.denials_of([INIT, result(denials=denials)])
    assert said == ["Bash: cd x && python -m pytest", "Write: a.py", "WebFetch"]


@pytest.mark.parametrize(
    ("messages", "said"),
    [
        ([INIT, result("ВЕРДИКТ: находок 1")], True),
        ([INIT, COMMENT, result("комментарий обновлён")], True),
        ([INIT, bash("python -m pytest", background=True), result("жду прогона")], False),
        ([INIT, bash('grep -n "ВЕРДИКТ:" scripts/agent_run.py'), result("смотрю")], False),
    ],
    ids=["в-итоге", "в-комментарии", "нет-нигде", "упомянута-не-сказана"],
)
def test_the_expected_line_is_looked_for_in_the_result_and_the_comment(
    messages: list[dict[str, Any]], said: bool
) -> None:
    """Строку ищут в итоге и в комментарии; во входе прочих инструментов — нет.

    Взгляд на сам механизм вердикта зовёт `grep "ВЕРДИКТ:"`, и без отбора по
    инструменту такой заход без ответа читался бы заходом с ответом
    (поздний взгляд на #1495).
    """
    assert module.says(messages, "ВЕРДИКТ:") is said


def test_a_run_without_its_verdict_is_its_own_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Заход «успехом» без строки вердикта назван словами `NO_VERDICT` с причинами рядом."""
    denied = [{"tool_name": "Bash", "tool_input": {"command": "pytest -x"}}]
    messages = [INIT, bash("python -m pytest", background=True), result("жду", denied)]
    path = run_file(tmp_path, messages)
    assert module.main(["--from", str(path), "--call", "взгляд", "--expect", "ВЕРДИКТ:"]) == 0
    out = capsys.readouterr().out
    assert f"::warning::взгляд: {module.NO_VERDICT}" in out
    assert "в фоне: 1" in out and "отказов разрешений: 1" in out
    assert "::notice::взгляд: увёл в фон — python -m pytest" in out
    assert "::notice::взгляд: отказы разрешений — Bash: pytest -x" in out


@pytest.mark.parametrize(
    ("argv", "messages"),
    [
        (["--expect", "ВЕРДИКТ:"], [INIT, COMMENT, result()]),
        ([], [INIT, result("без строки")]),
    ],
    ids=["вердикт-есть", "строку-не-ждут"],
)
def test_a_run_with_its_verdict_or_without_expectation_is_not_named(
    argv: list[str],
    messages: list[dict[str, Any]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Вердикт на месте или строку не ждут — состояния «без вердикта» нет."""
    path = run_file(tmp_path, messages)
    assert module.main(["--from", str(path), *argv]) == module.EXIT_OK
    assert module.NO_VERDICT not in capsys.readouterr().out


def test_a_refusal_is_not_also_a_run_without_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ захода — уже названная причина: «без вердикта» поверх него не ставится."""
    failed = {"type": "result", "subtype": "success", "is_error": True, "result": "нет модели"}
    path = run_file(tmp_path, [INIT, failed])
    assert module.main(["--from", str(path), "--expect", "ВЕРДИКТ:"]) == module.EXIT_OK
    out = capsys.readouterr().out
    assert module.REFUSED in out and module.NO_VERDICT not in out


@pytest.mark.parametrize(
    "text",
    ["коротко", "я" * module.LIMIT, "я" * (module.LIMIT + 1), "  поля  "],
    ids=["коротко", "на-границе", "за-границей", "поля"],
)
def test_the_cut_is_the_transport_one(text: str) -> None:
    """Обрезка шага — копия `report.cut`, и разойтись с ним молча ей нельзя (016)."""
    assert module.LIMIT == report.LIMIT
    assert module.cut(text) == report.cut(text)


def test_tool_calls_are_the_tool_blocks_of_the_agent_in_order() -> None:
    """Вызовы — блоки `tool_use` сообщений агента, по порядку; прочее не вызов.

    Текст ответа, сообщение не агента и тело не той формы вызовами не считаются:
    по ним `says` и `background_of` судили бы чужое.
    """
    text = {"type": "assistant", "message": {"content": [{"type": "text", "text": "думаю"}]}}
    odd = {"type": "assistant", "message": "не словарь"}
    user = {"type": "user", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}
    first, second = bash("ls"), bash("python -m pytest", background=True)
    messages = [INIT, first, text, odd, user, second, COMMENT]
    names = [call["name"] for call in module.tool_calls(messages)]
    assert names == ["Bash", "Bash", "mcp__github_comment__update_claude_comment"]
    assert module.tool_calls([INIT, result()]) == []


@pytest.mark.parametrize(
    ("text", "said"),
    [("cd x &&\n  python -m pytest", "cd x && python -m pytest"), ("  ls  ", "ls")],
    ids=["перенос", "поля"],
)
def test_one_line_joins_the_command_and_cuts_it(text: str, said: str) -> None:
    """Команда — одной строкой без лишних пробелов и с тем же пределом, что у обрезки."""
    assert module.one_line(text) == said
    long = "я " * module.LIMIT
    assert module.one_line(long) == module.cut(" ".join(long.split()))
