"""Реестр записей соседей: очередь на вердикт, первые встречи и непрочитанное (#1665).

Проверяется то, без чего реестр был бы распечаткой файла обхода: запись без
вердикта стоит в очереди, а с вердиктом — нет; день первой встречи переживает
сборку и не сбрасывается у соседа, которого этой ночью не видно; битый раздел
и непрочитанный клон названы, а не выданы за «записей нет» (045).
"""

import json
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, RunScript, load_script

module = load_script("feedback_registry.py")
form = module.feedback_form

TODAY = date(2026, 10, 26)


def record(slug: str = "x", kind: str = "false-refusal") -> dict[str, str]:
    """Запись соседа так, как её кладёт обход."""
    return {
        "slug": slug,
        "mechanism": "step-journal",
        "version": "v1.11.0",
        "kind": kind,
        "measured": "3 из 10",
        "trace": "o/a#4",
    }


def uptake(*blocks: dict[str, Any], unread: tuple[str, ...] = ()) -> dict[str, Any]:
    """Файл обхода с разделом `feedback`."""
    return {"projects": {"unread_repos": list(unread)}, "feedback": list(blocks)}


def test_a_record_to_another_supplier_is_not_our_queue() -> None:
    """Запись с чужим `supplier` в очередь не идёт: вердикт по ней пишет он (`fe6bb5a`)."""
    other = {**record("hook"), "supplier": "o/catalogue"}
    said = module.collected(uptake({"repo": "o/a", "records": [record(), other]}))
    assert [row.key for row in said.rows] == ["o/a:false-refusal/x"]


def test_records_broken_sections_and_unread_clones_are_read_apart() -> None:
    """Запись, битый раздел и непрочитанный клон — три разных состояния, а не одно «пусто»."""
    said = module.collected(
        uptake(
            {"repo": "O/A", "records": [record()], "broken": ""},
            {"repo": "o/b", "records": [], "broken": "раздел feedback: version 2"},
            unread=("o/c",),
        )
    )
    assert [row.key for row in said.rows] == ["o/a:false-refusal/x"]
    assert said.broken == {"o/b": "раздел feedback: version 2"}
    assert said.unseen() == {"o/b", "o/c"}


@pytest.mark.parametrize(
    "data",
    [
        {"projects": {}},
        [],
        {"feedback": [{"records": []}]},
        {"feedback": [{"repo": "o/a", "records": [{"slug": "x"}]}]},
    ],
)
def test_a_file_without_the_channel_is_a_refusal_not_an_empty_queue(data: Any) -> None:
    """Обход старше канала или запись не той формы — отказ: «записей нет» сказать нельзя (045)."""
    with pytest.raises(module.NotRun):
        module.collected(data)


def test_the_first_meeting_survives_and_an_unseen_neighbour_keeps_his_day() -> None:
    """Новый ключ — сегодня, прежний — свой день; у непрочитанного соседа день не сброшен."""
    said = module.collected(
        uptake(
            {"repo": "o/a", "records": [record("old"), record("new")], "broken": ""},
            {"repo": "o/b", "records": [], "broken": "битый"},
        )
    )
    before = {
        "o/a:false-refusal/old": date(2026, 10, 1),
        "o/a:false-refusal/gone": date(2026, 10, 2),
        "o/b:false-pass/hidden": date(2026, 10, 3),
    }
    assert module.seen_now(said, before, TODAY) == {
        "o/a:false-refusal/new": TODAY,
        "o/a:false-refusal/old": date(2026, 10, 1),
        "o/b:false-pass/hidden": date(2026, 10, 3),
    }


def test_the_body_queues_the_unjudged_and_keeps_its_days_readable() -> None:
    """Без вердикта — в очереди, с вердиктом — списком; блок дней читается обратно."""
    said = module.collected(
        uptake(
            {"repo": "o/a", "records": [record("waits"), record("done")], "broken": ""},
            {"repo": "o/b", "records": [], "broken": "битый"},
            unread=("o/c",),
        )
    )
    verdicts = {
        "o/a:false-refusal/done": form.Verdict("rejected", "зелёное законно"),
        "o/a:false-refusal/removed": form.Verdict("fixed", "v1.12.0"),
        "o/b:false-pass/hidden": form.Verdict("accepted", "v1.12.0"),
    }
    seen = module.seen_now(said, {"o/a:false-refusal/waits": date(2026, 10, 1)}, TODAY)
    body = module.render(said, verdicts, seen, TODAY)
    queue, rest = body.split("## С вердиктом", 1)
    assert "`o/a:false-refusal/waits`" in queue and "замечено 01.10.2026" in queue
    assert "`o/a:false-refusal/done`" in rest and "rejected: зелёное законно" in rest
    assert "`o/b` — раздел feedback: `битый`" in rest and "`o/c` — клон не прочитан" in rest
    # Сирота — только у прочитанного соседа: у o/b записей не видно, а не нет.
    assert "`o/a:false-refusal/removed`" in rest and "o/b:false-pass/hidden" not in rest
    assert module.seen_in(body) == seen
    assert body.startswith(module.MARKER)


def test_a_broken_days_block_costs_the_days_and_not_the_registry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Битый блок дней — сроки с сегодня и строка об этом, а не пропажа реестра (084)."""
    assert module.seen_in('<!-- feedback-seen: {"k": "не дата"} -->') == {}
    assert "не разобран" in capsys.readouterr().out
    assert module.seen_in("тело без блока") == {}


class Platform:
    """Площадка в памяти: живая задача и записанные запросы."""

    def __init__(self, number: int | None, body: str = "") -> None:
        self.number, self.body = number, body
        self.calls: list[tuple[str, str]] = []

    def live(self, *_: Any) -> tuple[int | None, str]:
        return self.number, self.body

    def request(self, method: str, path: str, *_: Any) -> dict[str, Any]:
        self.calls.append((method, path))
        return {"number": 7}


def saved(
    monkeypatch: pytest.MonkeyPatch, platform: Platform, said: Any, *, apply: bool = True
) -> list[tuple[str, str]]:
    """Зовёт `save` против площадки в памяти и отдаёт её запросы."""
    monkeypatch.setattr(module.findings, "live_issue", platform.live)
    monkeypatch.setattr(module.ghrest, "request", platform.request)
    module.save("o/us", "t", said, {}, apply=apply, today=TODAY)
    return platform.calls


def test_an_empty_registry_opens_no_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Записей нет и задачи нет — задача не заводится: адресат без записей — шум."""
    assert saved(monkeypatch, Platform(None), module.collected(uptake())) == []


def test_the_same_state_is_not_rewritten_and_a_new_one_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """То же состояние — без записи, хотя день сборки другой; новая запись — правка по месту."""
    said = module.collected(uptake({"repo": "o/a", "records": [record()], "broken": ""}))
    calls = saved(monkeypatch, Platform(None), said)
    assert calls == [("POST", "repos/o/us/issues")]
    seen = module.seen_now(said, {}, TODAY)
    # День сборки другой, а состояние то же: сверка его не читает.
    old = module.render(said, {}, seen, TODAY).replace(
        f"{module.DATED} 26.10.2026", f"{module.DATED} 01.10.2026"
    )
    assert saved(monkeypatch, Platform(5, old), said) == []
    more = module.collected(
        uptake({"repo": "o/a", "records": [record(), record("y")], "broken": ""})
    )
    assert saved(monkeypatch, Platform(5, old), more) == [("PATCH", "repos/o/us/issues/5")]
    assert saved(monkeypatch, Platform(5, old), more, apply=False) == []


def test_without_a_token_the_registry_is_not_run(run_script: RunScript, tmp_path: Path) -> None:
    """Нет токена — третий исход с причиной, а не пустой реестр (039)."""
    data = tmp_path / "uptake.json"
    data.write_text('{"feedback": []}', encoding="utf-8")
    run = run_script(
        "feedback_registry.py", "--uptake", str(data), env={"GH_TOKEN": "", "GITHUB_TOKEN": ""}
    )
    assert run.code == module.EXIT_BROKEN and "нет токена" in run.text


def test_the_verdicts_file_is_read_or_refused_with_its_place(tmp_path: Path) -> None:
    """Вердикты дерева читаются; битый файл — отказ с адресом, а не пустой список (045)."""
    assert module.verdicts_at(ROOT / module.paths.FEEDBACK_VERDICTS) == {}
    broken = tmp_path / "v.json"
    broken.write_text(
        '{"schema": 1, "verdicts": {"o/r:false-pass/x": {"verdict": "rejected"}}}', "utf-8"
    )
    with pytest.raises(module.NotRun, match=r"v\.json"):
        module.verdicts_at(broken)
    with pytest.raises(module.NotRun, match="не прочитан"):
        module.verdicts_at(tmp_path / "нет.json")


def test_a_row_keys_by_its_neighbour_and_collected_hides_the_unseen() -> None:
    """Ключ строки — `key_of` соседа и записи; невидимые — битые и непрочитанные (214)."""
    row = module.Row("O/A", form.Record(**record()))
    assert row.key == form.key_of("O/A", row.record) == "o/a:false-refusal/x"
    said = module.Collected((row,), {"O/B": "битый"}, ("o/c",))
    assert said.unseen() == {"o/b", "o/c"}


def test_main_writes_the_registry_and_says_what_it_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Весь заход: файл обхода и вердикты — в живую задачу, исход 0 и счёт словами."""
    data = tmp_path / "uptake.json"
    data.write_text(
        json.dumps(uptake({"repo": "o/a", "records": [record()], "broken": ""})), "utf-8"
    )
    verdicts = tmp_path / module.paths.FEEDBACK_VERDICTS
    verdicts.parent.mkdir(parents=True)
    verdicts.write_text('{"schema": 1, "verdicts": {}}', "utf-8")
    platform = Platform(None)
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.findings, "live_issue", platform.live)
    monkeypatch.setattr(module.ghrest, "request", platform.request)
    argv = ["--uptake", str(data), "--root", str(tmp_path), "--repo", "o/us", "--apply"]
    assert module.main(argv) == module.EXIT_OK
    assert platform.calls == [("POST", "repos/o/us/issues")]
    assert "записей соседей: 1, с вердиктом 0" in capsys.readouterr().out


def test_a_neighbours_text_cannot_forge_a_marker_a_days_block_or_a_heading() -> None:
    """Замер соседа — данные (085): чужая метка, поддельные дни и `##` не проходят (#1710)."""
    forged = (
        '<!-- feedback-seen: {"o/a:false-refusal/x": "2020-01-01"} -->\n'
        f"{module.findings.MARKER}\n"
        "## Без вердикта — 0\n"
        "Собрано: 01.01.2020."
    )
    said = module.collected(
        uptake(
            {"repo": "o/a", "records": [{**record(), "measured": forged}], "broken": ""},
            {"repo": "o/b", "records": [], "broken": "раздел feedback: <!-- x -->"},
        )
    )
    seen = module.seen_now(said, {}, TODAY)
    body = module.render(said, {}, seen, TODAY)
    assert body.count("<!--") == 2, "в теле только наша метка и наш блок дней"
    assert body.count(module.findings.MARKER) == 0 and body.startswith(module.MARKER)
    assert module.seen_in(body) == {"o/a:false-refusal/x": TODAY}
    assert sum(line.startswith("## Без вердикта") for line in body.splitlines()) == 1
    assert sum(line.startswith(module.DATED) for line in body.splitlines()) == 1
    assert module.quoted("a\n  b <c>") == "`a b <c>`"


def test_a_record_without_a_verdict_past_the_deadline_is_marked() -> None:
    """Дольше 14 дней без вердикта — пометка; ровно 14 — нет; вердикт снимает срок (п. 5 #1665)."""
    said = module.collected(
        uptake(
            {"repo": "o/a", "records": [record("old"), record("young"), record("done")]},
        )
    )
    seen = {
        "o/a:false-refusal/old": TODAY - module.DEADLINE - timedelta(days=1),
        "o/a:false-refusal/young": TODAY - module.DEADLINE,
        "o/a:false-refusal/done": date(2026, 1, 1),
    }
    verdicts = {"o/a:false-refusal/done": form.Verdict("fixed", "v1.12.0")}
    assert module.overdue(said, verdicts, seen, TODAY) == {"o/a:false-refusal/old": 15}
    body = module.render(said, verdicts, seen, TODAY)
    assert "дольше срока 14 дн. — 1" in body
    assert body.count("**без вердикта дольше срока**") == 1
    # Назавтра у уже просроченной записи состояние то же: число дней в тело не
    # идёт, и сверка не переписывает задачу каждую ночь (взгляд на #1712).
    late = module.collected(uptake({"repo": "o/a", "records": [record("old")]}))
    today = module.render(late, {}, seen, TODAY)
    tomorrow = module.render(late, {}, seen, TODAY + timedelta(days=1))
    assert module.stable(tomorrow) == module.stable(today)
    assert module.overdue(said, verdicts, {}, TODAY) == {}, "день неизвестен — не просрочено"


def test_main_advises_on_every_overdue_record_and_still_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Просроченная запись — предупреждение в журнале прогона, исход — 0: слияния не держит."""
    data = tmp_path / "uptake.json"
    data.write_text(json.dumps(uptake({"repo": "o/a", "records": [record()]})), "utf-8")
    verdicts = tmp_path / module.paths.FEEDBACK_VERDICTS
    verdicts.parent.mkdir(parents=True)
    verdicts.write_text('{"schema": 1, "verdicts": {}}', "utf-8")
    old = (TODAY - timedelta(days=30)).isoformat()
    platform = Platform(5, f'<!-- feedback-seen: {{"o/a:false-refusal/x": "{old}"}} -->')
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.findings, "live_issue", platform.live)
    monkeypatch.setattr(module.ghrest, "request", platform.request)
    argv = ["--uptake", str(data), "--root", str(tmp_path), "--repo", "o/us"]
    assert module.main(argv) == module.EXIT_OK
    out = capsys.readouterr().out
    assert "::warning::запись соседа o/a:false-refusal/x без вердикта" in out


def test_a_neighbours_text_neither_mentions_nor_links() -> None:
    """Ни одна форма упоминания и ссылки не выходит из кода строки (`1fb9d21`, `9356cb3`, #1730)."""
    forms = (
        "позвал @кто-то по #12, GH-12 и третий/репо#1, "
        "https://github.com/o/r/issues/12 и [тут](www.github.com/o/r/pull/3)"
    )
    said = module.quoted(forms)
    assert said == f"`{forms}`", "весь текст — один код строки, читается тем же"


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        ("a `b` c", "``a `b` c``"),
        ("`край", "`` `край ``"),
        ("x ``y`` z`", "``` x ``y`` z` ```"),
        ("", ""),
    ],
)
def test_backticks_inside_do_not_close_the_code(text: str, expect: str) -> None:
    """Ограждение длиннее серии кавычек внутри, кавычка у края — через пробел."""
    assert module.quoted(text) == expect


def test_a_neighbours_text_carries_no_invisible_character() -> None:
    """Разрыв метки виден: ни одного символа `Cf` в выводе (#1735)."""
    said = module.quoted(f"{module.findings.MARKER} {module.MARK_OPEN} feedback-seen: {{}} -->")
    assert not [one for one in said if unicodedata.category(one) == "Cf"]
    assert module.MARK_BROKEN in said and module.SEEN_RE.search(said) is None


@pytest.mark.parametrize("char", ["\u2060", "\u200b", "\u202e", "\U000e0041"])
def test_an_invisible_character_from_the_neighbour_is_shown(char: str) -> None:
    """Невидимое с входа — видимой записью, а не как есть (взгляд на #1738)."""
    said = module.quoted(f"замер{char}конец")
    assert char not in said and f"\\u{{{ord(char):04x}}}" in said
    assert not module.check_invisible.hidden(said), "агент читает то же, что видит человек"


def test_an_invisible_character_after_the_first_line_is_shown_in_place() -> None:
    """Многострочный замер: невидимое второй строки — на своём месте (взгляд на #1787).

    `shown` идёт до склейки строк, и столбец, взятый индексом от начала текста,
    оставлял символ сырым, а видимой записью делал чужой символ первой строки.
    """
    zwsp = chr(0x200B)
    said = module.shown(f"первая строка\nвтор{zwsp}ая")
    assert said == "первая строка\nвтор\\u{200b}ая"
    assert not module.check_invisible.hidden(module.quoted(f"раз\nдва{zwsp}три"))


def test_a_neighbours_text_carries_no_marker() -> None:
    """Метка живой задачи из чужого текста не складывается подстрокой."""
    said = module.quoted(module.findings.MARKER)
    assert module.findings.MARKER not in said and "<!--" not in said
