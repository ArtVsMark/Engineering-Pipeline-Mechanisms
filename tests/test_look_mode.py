"""Полный взгляд один раз, дальше проверка починки (#848)."""

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
    assert "прошлых находок нет" in module.task_text(module.FIX, [])
    assert module.task_text(module.FULL, []) == ""


def platform(monkeypatch: pytest.MonkeyPatch, comments: list[dict[str, Any]], body: str) -> None:
    """Площадка: лента изменения и тело реестра."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, token: iter(comments))
    monkeypatch.setattr(module.review_findings, "live_issue", lambda repo, token: (23, body))


def test_main_writes_the_mode_and_the_task(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Исход «записан»: режим и задание уходят в `$GITHUB_OUTPUT`."""
    out = tmp_path / "output"
    body = (
        "- `aaa1111` · #7 · дефект — a.py:1 — раз\nЗаписано: "
        + module.review_findings.render_recorded({7: 1})
    )
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
    assert written[2:] == ["строка", "LOOK_MODE_EOF_", "ещё", fence, "seen="]


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


def test_an_unrecorded_full_look_keeps_the_look_full() -> None:
    """Полный заход ещё не в реестре — заход снова полный, а не «находок 0» (#842)."""
    assert module.settled(module.FIX, 7, {}) == module.FULL
    assert module.settled(module.FIX, 7, {8: 1}) == module.FULL, "чужая отметка засчитана"
    assert module.settled(module.FIX, 7, {7: 1}) == module.FIX
    assert module.settled(module.FULL, 7, {7: 1}) == module.FULL


def test_prior_findings_come_from_the_registry_only() -> None:
    """Лента в прошлые находки не подмешивается: отпечаток пересказа живёт в реестре (210)."""
    entries = {"aaa1111": Entry(7, "риск", "пересказ")}
    assert module.prior_of(entries, 7) == [("aaa1111", entries["aaa1111"])]


def test_main_without_a_recorded_full_look_runs_full(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Реестр без отметки изменения — режим полный, задания нет."""
    out = tmp_path / "output"
    platform(monkeypatch, [FULL_LOOK], "- `aaa1111` · #7 · дефект — a.py:1 — раз")
    assert module.main(["--repo", "o/r", "--pr", "7", "--output", str(out)]) == module.EXIT_OK
    assert "mode=full\n" in out.read_text(encoding="utf-8")


def test_the_task_line_form_is_the_one_the_parser_reads() -> None:
    """Строка из задания разбирается `FIX_RE`: форма одна, букв в двух местах нет (209)."""
    rf = module.review_findings
    for closed in (True, False):
        line = rf.fix_form("abc1234", closed, "почему")
        assert rf.fix_answers([said(1, line)]) == {"abc1234": closed}
    task = module.task_text(module.FIX, [])
    assert rf.fix_form("<отпечаток>", True, "<чем закрыта, одной фразой>") in task


# --- #1144: дифф уже просмотрен — взгляд не нужен --------------------------------

OWN = "@@ -1,3 +1,3 @@\n контекст\n-было\n+стало\n контекст"
#: Та же правка после подтянутой main: сдвинуты только номера в `@@`.
OWN_MOVED = "@@ -10,3 +12,3 @@\n контекст\n-было\n+стало\n контекст"
#: Те же строки `+`/`-`, перенесённые в другое место файла.
OWN_ELSEWHERE = "@@ -40,3 +40,3 @@\n другое место\n-было\n+стало\n другое место"
#: Слияние с разрешённым конфликтом: собственная правка стала другой.
RESOLVED = "@@ -1,3 +1,3 @@\n контекст\n-было\n+стало иначе\n контекст"


def changed(patch: str, name: str = "a.py") -> list[dict[str, Any]]:
    """Ответ сравнения площадки с одним файлом."""
    return [{"filename": name, "status": "modified", "changes": 2, "patch": patch}]


def look_on_run(look_id: int, run: int, body: str = "ВЕРДИКТ: находок 0") -> dict[str, Any]:
    """Вердикт ревьюера со ссылкой на свой прогон, как его пишет действие."""
    link = f"[View job](https://github.com/o/r/actions/runs/{run})"
    return said(look_id, f"**Claude finished** —— {link}\n\n{body}") | {
        "html_url": f"https://github.com/o/r/pull/7#issuecomment-{look_id}"
    }


def test_the_diff_key_ignores_hunk_numbers_but_sees_the_place() -> None:
    """Сдвиг `@@` ключа не меняет, перенос правки в другое место — меняет (#1161)."""
    assert module.diff_key(changed(OWN)) == module.diff_key(changed(OWN_MOVED))
    assert module.diff_key(changed(OWN)) != module.diff_key(changed(OWN_ELSEWHERE))
    assert module.diff_key(changed(OWN)) != module.diff_key(changed(RESOLVED))
    assert module.diff_key(changed(OWN)) != module.diff_key(changed(OWN, name="b.py"))


def test_a_cut_comparison_has_no_key() -> None:
    """Обрезанный ответ или файл без заплатки — ключа нет, а не ключ части диффа."""
    assert module.diff_key(None) is None
    assert module.diff_key(changed(OWN) * module.COMPARE_FILES_CAP) is None
    unread = [{"filename": "a.png", "status": "modified", "changes": 3}]
    assert module.diff_key(unread) is None, "ни заплатки, ни блоба — а ключ есть"
    renamed = [{"filename": "b.py", "status": "renamed", "changes": 0}]
    assert module.diff_key(renamed) is not None, "переименование без правки — законный ключ"


def head_of(runs: dict[int, str]) -> Any:
    """Голова прогона по номеру."""
    return lambda run: runs.get(run, "")


def test_a_merged_main_with_the_same_own_diff_skips_the_look() -> None:
    """Голова после подтянутой main: дифф прежний, вердикт есть — взгляд не нужен."""
    patches = {"old": OWN, "new": OWN_MOVED}
    seen = module.same_diff(
        "new", [look_on_run(5, 100)], lambda sha: changed(patches[sha]), head_of({100: "old"})
    )
    assert seen == "https://github.com/o/r/pull/7#issuecomment-5"


def test_a_resolved_conflict_gets_the_look() -> None:
    """Слияние с разрешённым конфликтом меняет дифф — взгляд идёт."""
    patches = {"old": OWN, "new": RESOLVED}
    seen = module.same_diff(
        "new", [look_on_run(5, 100)], lambda sha: changed(patches[sha]), head_of({100: "old"})
    )
    assert seen is None


def test_no_verdict_or_the_same_head_gets_the_look() -> None:
    """Вердикта нет, он чужой, оборван или на той же голове — взгляд идёт."""
    same = lambda sha: changed(OWN)  # noqa: E731
    heads = head_of({100: "old", 101: "new"})
    assert module.same_diff("new", [], same, heads) is None
    foreign = look_on_run(5, 100) | {"user": {"login": "someone"}}
    assert module.same_diff("new", [foreign], same, heads) is None, "чужой вердикт засчитан"
    assert module.same_diff("new", [look_on_run(6, 101)], same, heads) is None, "перезапуск снят"
    unlinked = said(7, "ВЕРДИКТ: находок 0")
    assert module.same_diff("new", [unlinked], same, heads) is None


def test_an_unread_comparison_gets_the_look() -> None:
    """Сравнение не прочитано — взгляд идёт, как без пропуска (045)."""
    assert (
        module.same_diff("new", [look_on_run(5, 100)], lambda sha: None, head_of({100: "old"}))
        is None
    )
    assert (
        module.same_diff("new", [look_on_run(5, 100)], lambda sha: changed(OWN), head_of({}))
        is None
    )


def test_main_writes_the_skip_with_the_prior_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Исход «записан»: режим пропуска и адрес прежнего вердикта — в `$GITHUB_OUTPUT`."""
    out = tmp_path / "output"
    platform(monkeypatch, [look_on_run(5, 100)], "")
    patches = {"old": OWN, "new": OWN_MOVED}
    monkeypatch.setattr(
        module, "platform_compare", lambda repo, base, token: lambda sha: changed(patches[sha])
    )
    monkeypatch.setattr(module, "platform_run_head", lambda repo, token: head_of({100: "old"}))
    argv = ["--repo", "o/r", "--pr", "7", "--output", str(out), "--head", "new", "--base", "main"]
    assert module.main(argv) == module.EXIT_OK
    written = out.read_text(encoding="utf-8")
    assert "mode=skip\n" in written
    assert "seen=https://github.com/o/r/pull/7#issuecomment-5\n" in written


def test_the_skip_turns_off_the_look_and_says_so() -> None:
    """Пропуск выключает шаг ключа — а с ним агента — и пишет строку с вердиктом."""
    import yaml

    flow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/review.yml").read_text(encoding="utf-8")
    )
    outputs = flow["jobs"]["map"]["outputs"]
    assert outputs["mode"] == "${{ steps.mode.outputs.mode }}"
    assert outputs["seen"] == "${{ steps.mode.outputs.seen }}"
    steps = flow["jobs"]["review"]["steps"]
    token = next(step for step in steps if step.get("id") == "token")
    assert token["if"] == "needs.map.outputs.mode != 'skip'"
    told = next(step for step in steps if step.get("if") == "needs.map.outputs.mode == 'skip'")
    assert "SEEN" in told["run"] and told["env"]["SEEN"] == "${{ needs.map.outputs.seen }}"
    mode = next(step for step in flow["jobs"]["map"]["steps"] if step.get("id") == "mode")
    assert "--head" in mode["run"] and "--base" in mode["run"]


def test_verdict_runs_name_the_run_of_each_verdict() -> None:
    """Каждый вердикт ревьюера — со своим прогоном; без ссылки заход не берётся."""
    comments = [look_on_run(5, 100), said(6, "ВЕРДИКТ: находок 0"), look_on_run(7, 101)]
    assert module.verdict_runs(comments) == [
        ("https://github.com/o/r/pull/7#issuecomment-5", 100),
        ("https://github.com/o/r/pull/7#issuecomment-7", 101),
    ]


def test_platform_readers_say_nothing_on_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сравнение и голова прогона — у площадки; её отказ — «не прочитано», а не падение."""
    asked: list[str] = []

    def answer(method: str, path: str, token: str) -> dict[str, Any]:
        asked.append(path)
        if path.endswith("/compare/main...abc"):
            return {"files": changed(OWN)}
        if path.endswith("/actions/runs/100"):
            return {"head_sha": "abc"}
        raise module.ghrest.TransportError("503")

    monkeypatch.setattr(module.ghrest, "request", answer)
    compare = module.platform_compare("o/r", "main", "t")
    run_head = module.platform_run_head("o/r", "t")
    assert compare("abc") == changed(OWN) and compare("def") is None
    assert run_head(100) == "abc" and run_head(101) == ""
    assert "repos/o/r/compare/main...abc" in asked and "repos/o/r/actions/runs/100" in asked


def test_a_binary_file_enters_the_key_by_its_blob() -> None:
    """Двоичный файл — `changes` 0 и без заплатки, как отдаёт площадка: смену видит блоб (#1161)."""

    def binary(sha: str) -> list[dict[str, Any]]:
        return [{"filename": "a.png", "status": "modified", "changes": 0, "sha": sha}]

    assert module.diff_key(binary("aaa")) is not None
    assert module.diff_key(binary("aaa")) == module.diff_key(binary("aaa"))
    assert module.diff_key(binary("aaa")) != module.diff_key(binary("bbb"))


def test_the_review_reads_runs_and_passes_the_base_by_environment() -> None:
    """Карта читает прогоны (`actions: read`), голова и база — окружением (#1161, 085)."""
    import yaml

    flow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/review.yml").read_text(encoding="utf-8")
    )
    assert flow["permissions"].get("actions") == "read"
    mode = next(step for step in flow["jobs"]["map"]["steps"] if step.get("id") == "mode")
    assert "${{" not in mode["run"].split("look_mode.py", 1)[1].split("||")[0].replace(
        '"${{ github.event.pull_request.number }}"', ""
    ), "голова или база подставлены в текст команды"
    assert mode["env"]["BASE_REF"] == "${{ github.event.pull_request.base.ref }}"
