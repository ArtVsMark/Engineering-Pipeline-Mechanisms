"""Реестр слитого без внешнего взгляда: что он записывает и чего не записывает.

Гейт проверяется тем, что обязан ОТВЕРГНУТЬ
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-proved-by-what-it-rejects.md)),
и здесь отвергаемое — не «плохой код», а ЛОЖНАЯ ЗАПИСЬ. Реестр, записывающий
всё подряд, читается как шум; реестр, молчащий о слитом без взгляда, вернул бы
ровно ту неразличимость, ради которой заведён.

Площадки в проверках нет: `scan` берёт ответ одним `seen`, поэтому подделать
здесь можно решение, а не транспорт.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import ROOT, load_script

module = load_script("unlooked.py")

DAY = "2026-09-10T12:00:00Z"


def merged(number: int, at: str = DAY) -> dict[str, Any]:
    """Слитое изменение в том виде, в каком его отдаёт площадка."""
    return {"number": number, "merged_at": at}


def looked_at(*numbers: int) -> Any:
    """Ответ «вердикт был» ровно по названным изменениям, иначе «вердикта нет»."""
    return lambda number: None if number in numbers else module.STATE_NONE


def test_a_merge_without_a_verdict_is_recorded() -> None:
    """Слитое без вердикта попадает в реестр — это предмет всего механизма."""
    entries, _ = module.scan([merged(77)], {}, 0, looked_at())
    assert entries[77].state == module.STATE_NONE
    assert entries[77].merged == "2026-09-10"


def test_a_merge_with_a_verdict_is_not_recorded() -> None:
    """Слитое с вердиктом в реестр НЕ попадает.

    Без этой половины реестр перечислял бы всё слитое подряд и не значил бы
    ничего: список, совпадающий с историей, читателю не сообщает.
    """
    entries, _ = module.scan([merged(77)], {}, 0, looked_at(77))
    assert entries == {}


def test_a_late_verdict_removes_the_record() -> None:
    """Вердикт, опоздавший к слиянию, снимает запись сам.

    Замер соседа: вердикт опаздывал на 2,3 минуты. Запись, которую в таком
    случае снимают рукой, не снимают вовсе.
    """
    known = {77: module.Entry(77, module.STATE_NONE, "2026-09-10")}
    entries, _ = module.scan([], known, 77, looked_at(77))
    assert entries == {}


def test_a_late_look_is_not_re_read_as_a_verdict() -> None:
    """«Поздний взгляд» переживает заход и не превращается в «взгляд был».

    Состояние ставит человек по прогону, смотревшему код УЖЕ в общей ветке.
    Пересчитать его нечем: вердикта на самом изменении от этого не появилось,
    и следующий заход снял бы отметку, будь она обычной записью.
    """
    known = {77: module.Entry(77, module.STATE_LATE, "2026-09-10")}
    entries, _ = module.scan([merged(77)], known, 0, looked_at())
    assert entries[77].state == module.STATE_LATE


def test_the_watermark_stops_a_second_look_at_the_same_change() -> None:
    """Уже просмотренное второй раз у площадки не спрашивают.

    Без отметки обхода каждое событие очереди стоило бы запроса на каждое
    изменение окна — тридцать запросов на пустом месте, и это при разделяемой
    квоте (`ghrest`).
    """
    asked: list[int] = []

    def seen(number: int) -> bool:
        asked.append(number)
        return False

    entries, mark = module.scan([merged(80), merged(79)], {}, 79, seen)
    assert asked == [80], "спрошено не только новое"
    assert set(entries) == {80}
    assert mark == 80


def test_the_watermark_advances_only_to_what_was_seen() -> None:
    """Отметка обхода — максимум увиденного, а не выдуманное число."""
    _, mark = module.scan([merged(41), merged(40)], {}, 30, looked_at(41, 40))
    assert mark == 41


def test_the_registry_reads_back_what_it_wrote() -> None:
    """Тело реестра — не украшение: механизм читает из него собственную запись.

    Разойдись сборка и разбор, реестр каждый заход считал бы записи новыми и
    заводил их заново поверх снятых.
    """
    entries = {
        77: module.Entry(77, module.STATE_NONE, "2026-09-10"),
        70: module.Entry(70, module.STATE_LATE, "2026-09-01"),
    }
    body = module.render_body(entries, 81)
    assert module.parse_entries(body) == entries
    assert module.parse_watermark(body) == 81


def test_an_empty_registry_still_carries_its_watermark() -> None:
    """Пустой реестр не теряет отметку обхода.

    Потерянная отметка — это полный обход окна на каждом событии, и заметить
    это нечем: реестр при этом верен.
    """
    assert module.parse_watermark(module.render_body({}, 81)) == 81


def test_a_registry_that_was_never_scanned_says_zero() -> None:
    """Отметки нет — ноль, а не догадка: обход начинается с начала окна."""
    assert module.parse_watermark("") == 0
    assert module.parse_watermark(None) == 0


def test_a_late_look_at_a_change_the_registry_did_not_know() -> None:
    """Поздний взгляд по изменению без записи заводит её, а не теряется.

    Записи может не быть по законной причине: вердикт был, и в реестр
    изменение не попало. Поздний взгляд по нему всё равно состоялся, и молчать
    о нём значило бы отчитаться о меньшем, чем было.
    """
    entries = module.mark_late({}, 55)
    assert entries[55].state == module.STATE_LATE


@pytest.mark.parametrize("state", module.STATES, ids=lambda state: state)
def test_every_state_is_named_in_the_body(state: str) -> None:
    """Оба состояния объяснены в теле задачи, а не только в коде.

    Читатель реестра — окно и владелец, и разницу между «взгляда не было» и
    «поздний взгляд» им должен объяснять сам реестр (021).
    """
    assert state in module.render_body({}, 0)


def test_a_late_comment_is_not_a_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вердикт позднего взгляда не считается взглядом ДО слияния.

    Это то самое отвергаемое, ради которого состояния разведены: строка
    «ВЕРДИКТ: находок 0» в позднем комментарии выглядит точно так же, как в
    своевременном, и без отметки сняла бы запись «взгляда не было» — реестр
    сказал бы, что взгляд был вовремя (154).
    """
    late = f"{module.LATE_MARKER}\nразбор по общей ветке\nВЕРДИКТ: находок 0"
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter([{"body": late}]))
    assert module.look_at("owner/repo", 77, "token") == module.STATE_NONE


def test_a_timely_comment_is_a_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Своевременный вердикт читается как взгляд — иначе реестр врал бы в обе стороны."""
    monkeypatch.setattr(
        module.ghrest, "paginate", lambda *_, **__: iter([{"body": "ВЕРДИКТ: находок 0"}])
    )
    assert module.look_at("owner/repo", 77, "token") is None


# --- третье состояние: ответ оборван ------------------------------------------
#
# Задача просила назвать причину четырьмя словами — «вердикта не было · прогон
# упал · секрета нет · находки не закрыты». Артефакты дают из них полторы, и
# здесь проверяется ровно то, что механизм действительно различает.


def test_a_cut_answer_is_not_the_same_as_silence() -> None:
    """Ревьюер начал отвечать и не закончил — это своё состояние.

    Это и есть видимая часть «прогон упал»: сам джоб зелен всегда, шаг ревью
    объявлен `continue-on-error`, и краснеть ему нечем. Записать оборванный
    ответ как молчание значило бы стереть единственный видимый след того, что
    взгляд был и сорвался.
    """
    cut = [{"body": "НАХОДКА[дефект]: гейт не проверяет свой предмет"}]
    assert module.look_of(cut) == module.STATE_CUT


def test_silence_is_silence() -> None:
    """Ни находок, ни вердикта — «вердикта нет», и причина не выдумывается."""
    assert module.look_of([{"body": "спасибо, посмотрю"}]) == module.STATE_NONE


def test_a_verdict_outweighs_the_findings_lines() -> None:
    """Вердикт есть — взгляд состоялся, сколько бы находок ни было названо."""
    whole = [{"body": "НАХОДКА[риск]: раз\nВЕРДИКТ: находок 1"}]
    assert module.look_of(whole) is None


def test_a_cut_answer_finished_later_changes_the_record() -> None:
    """Дописанный вердикт снимает запись, а уточнённое состояние её меняет.

    Запись, застывшая в первом прочтении, врала бы ровно там, где реестр обязан
    быть точным: «оборвался» и «промолчал» — разные поводы к разговору.
    """
    known = {77: module.Entry(77, module.STATE_NONE, "2026-09-10")}
    entries, _ = module.scan([], known, 77, lambda _: module.STATE_CUT)
    assert entries[77].state == module.STATE_CUT
    assert entries[77].merged == "2026-09-10", "дата слияния переписана заходом"


def test_unresolved_findings_are_not_a_second_list() -> None:
    """Незакрытых находок реестр не ведёт — у них уже есть адресат.

    Второй счёт того же разошёлся бы с первым молча (022), и оба выглядели бы
    правдоподобно. Проверяется по коду: реестр не ходит в живую задачу находок
    за записями.
    """
    source = (ROOT / "scripts" / "unlooked.py").read_text(encoding="utf-8")
    assert "parse_entries(body)" in source, "предмет проверки не найден — разбор реестра исчез"
    assert "findings.parse_entries" not in source, "реестр завёл второй список незакрытых находок"


# --- причина тишины ----------------------------------------------------------


def test_no_record_of_the_look_means_it_never_ran() -> None:
    """Записи проверки взгляда на голове нет — прогон не запускался.

    Смотреть тогда надо условия шага, а не работу: это разные починки, и
    прежде обе назывались одним словом «вердикта нет» (046).
    """
    assert module.why_quiet([]) == module.STATE_NONE
    assert module.why_quiet([{"name": "lint", "conclusion": "success"}]) == module.STATE_NONE


def test_a_red_look_run_is_told_apart_from_silence() -> None:
    """Красная запись взгляда — поломка канала, а не молчание ревьюера."""
    assert module.why_quiet([{"name": "review", "conclusion": "failure"}]) == module.STATE_BROKEN


def test_a_green_run_without_an_answer_is_its_own_state() -> None:
    """Запись зелёная, ответа нет — отдельное состояние, а не «вердикта нет»."""
    assert module.why_quiet([{"name": "review", "conclusion": "success"}]) == module.STATE_SILENT


def test_a_failed_run_outweighs_a_green_one() -> None:
    """У имени несколько записей — «упал» важнее «прошёл».

    Иначе повторный зелёный заход спрятал бы упавший, и причина указала бы на
    ключ там, где чинить надо канал.
    """
    runs = [
        {"name": "review", "conclusion": "success"},
        {"name": "review", "conclusion": "failure"},
    ]
    assert module.why_quiet(runs) == module.STATE_BROKEN


def test_the_reason_never_costs_the_record_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ на запросе причины не роняет заход: запись важнее подробности (084)."""

    def broken(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("площадка отказала")

    monkeypatch.setattr(module.ghrest, "request", broken)
    assert module.head_runs("o/r", 7, "token") == []


def test_a_cut_answer_needs_no_check_runs() -> None:
    """Оборванный ответ объясняет себя сам — записи проверок для него не нужны.

    Это не мелочь: второй запрос на каждое изменение окна стоил бы тридцати
    обращений за заход ради причины, которая уже видна.
    """
    comments = [{"body": "НАХОДКА[дефект]: что-то не так"}]
    assert module.look_of(comments) == module.STATE_CUT
