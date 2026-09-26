"""Полный взгляд один раз, дальше проверка починки (#848)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("look_mode.py")
Entry = module.findings.Entry
REVIEWER = module.review_findings.REVIEWER_AUTHOR
MARKER = module.review_findings.FIXCHECK_MARKER


def said(look_id: int, body: str, author: str = REVIEWER) -> dict[str, Any]:
    """Комментарий на изменении, как его отдаёт площадка."""
    return {"id": look_id, "body": body, "user": {"login": author}}


FULL_LOOK = said(1, "НАХОДКА[риск]: a.py:1 — раз\nВЕРДИКТ: находок 1")
FIX_LOOK = said(2, f"{MARKER}\nПОЧИНКА[abc1234]: закрыта — да\nВЕРДИКТ: находок 0")


@pytest.mark.parametrize(
    ("comments", "mode"),
    [
        ([], module.FULL),
        ([said(9, "идёт…")], module.FULL),
        ([FULL_LOOK], module.FIX),
        ([FULL_LOOK, FIX_LOOK], module.FIX),
        ([FIX_LOOK], module.FULL),
    ],
    ids=["ленты нет", "вердикта нет", "полный был", "полный и починка", "только починка"],
)
def test_the_full_look_goes_once(comments: list[dict[str, Any]], mode: str) -> None:
    """Проверка починки — только после вердикта ПОЛНОГО захода."""
    assert module.mode_of(comments) == mode


def test_a_fix_marker_from_someone_else_is_not_a_fix_check() -> None:
    """Чужой вердикт полным заходом не считается, и метка починки чужой не ставится."""
    forged = said(3, "ВЕРДИКТ: находок 0", author="someone")
    assert module.mode_of([forged]) == module.FULL, "чужой вердикт засчитан как полный заход"
    marked = said(4, f"{MARKER}\nВЕРДИКТ: находок 0", author="someone")
    assert not module.review_findings.is_fix_check([marked])


def test_prior_findings_are_this_changes_only() -> None:
    """В задание уходят находки этого изменения, по отпечатку."""
    entries = {"bbb2222": Entry(7, "риск", "два"), "aaa1111": Entry(7, "дефект", "раз")}
    entries["ccc3333"] = Entry(8, "риск", "чужая")
    assert [mark for mark, _ in module.prior_of(entries, 7)] == ["aaa1111", "bbb2222"]


def test_the_task_lists_the_prior_findings_and_the_answer_form() -> None:
    """Задание проверки починки называет форму ответа и каждую прошлую находку."""
    task = module.task_text(module.FIX, [("aaa1111", Entry(7, "дефект", "a.py:1 — раз"))])
    assert MARKER in task and "ПОЧИНКА[<отпечаток>]" in task
    assert "`aaa1111` · дефект · a.py:1 — раз" in task
    assert "прошлых находок в реестре нет" in module.task_text(module.FIX, [])
    assert module.task_text(module.FULL, []) == ""


def platform(monkeypatch: pytest.MonkeyPatch, comments: list[dict[str, Any]], body: str) -> None:
    """Площадка: лента изменения и тело реестра."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, token: iter(comments))
    monkeypatch.setattr(module.review_findings, "live_issue", lambda repo, token: (23, body))


def test_main_writes_the_mode_and_the_task(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Исход «записан»: режим и задание уходят в `$GITHUB_OUTPUT`."""
    out = tmp_path / "output"
    body = "- `aaa1111` · #7 · дефект — a.py:1 — раз"
    platform(monkeypatch, [FULL_LOOK], body)
    assert module.main(["--repo", "o/r", "--pr", "7", "--output", str(out)]) == module.EXIT_OK
    written = out.read_text(encoding="utf-8")
    assert "mode=fix\n" in written and "task<<LOOK_MODE_EOF_" in written
    assert "`aaa1111` · дефект · a.py:1 — раз" in written, "прошлая находка не дошла до задания"


def test_main_without_a_token_is_broken(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Нет токена — отказ, и в `$GITHUB_OUTPUT` ничего: взгляд пойдёт полным."""
    out = tmp_path / "output"
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    assert module.main(["--repo", "o/r", "--pr", "7", "--output", str(out)]) == module.EXIT_BROKEN
    assert not out.exists()


def test_main_on_a_platform_refusal_is_broken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Площадка отказала — отказ, а не «полный был»."""

    def refuse(path: str, token: str) -> Any:
        raise module.ghrest.TransportError("503")

    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.ghrest, "paginate", refuse)
    out = tmp_path / "output"
    assert module.main(["--repo", "o/r", "--pr", "7", "--output", str(out)]) == module.EXIT_BROKEN


def test_write_output_keeps_the_task_whole_between_random_fences(tmp_path: Path) -> None:
    """Задание со строкой, похожей на разделитель, не закрывает блок раньше."""
    out = tmp_path / "output"
    module.write_output(out, module.FIX, "строка\nLOOK_MODE_EOF_\nещё\n")
    written = out.read_text(encoding="utf-8").splitlines()
    fence = written[1].removeprefix("task<<")
    assert written[0] == "mode=fix" and fence.startswith("LOOK_MODE_EOF_") and len(fence) > 20
    assert written[2:] == ["строка", "LOOK_MODE_EOF_", "ещё", fence]


def test_a_new_head_cancels_the_look_of_the_old_one() -> None:
    """Заход взгляда снимается новым толчком: группа по изменению, с отменой (#848)."""
    import yaml

    flow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/review.yml").read_text(encoding="utf-8")
    )
    group = flow["jobs"]["review"]["concurrency"]
    assert group["cancel-in-progress"] is True
    assert "pull_request.number" in group["group"] and "head.sha" not in group["group"]
    task = flow["jobs"]["map"]["outputs"]["task"]
    assert task == "${{ steps.mode.outputs.task }}", "задание проверки починки не выходит из карты"
