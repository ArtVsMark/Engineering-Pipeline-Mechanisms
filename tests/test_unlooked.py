"""Реестр слитого без внешнего взгляда: что он записывает и чего не записывает.

Гейт проверяется тем, что обязан ОТВЕРГНУТЬ
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)),
и здесь отвергаемое — не «плохой код», а ЛОЖНАЯ ЗАПИСЬ. Реестр, записывающий
всё подряд, читается как шум; реестр, молчащий о слитом без взгляда, вернул бы
ровно ту неразличимость, ради которой заведён.

Площадки в проверках нет: `scan` берёт ответ одним `seen`, поэтому подделать
здесь можно решение, а не транспорт.
"""

from __future__ import annotations

import json
import re
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
    entries = module.mark_late({}, 55, "2026-09-12")
    assert entries[55].state == module.STATE_LATE
    assert entries[55].late == "2026-09-12"


def test_a_late_look_adds_a_state_and_does_not_replace_one() -> None:
    """Поздний взгляд ДОПИСЫВАЕТСЯ к состоянию, а не заменяет его.

    «Прогон взгляда прошёл, а ответа нет» отвечает на вопрос о КАНАЛЕ; «поздний
    взгляд состоялся» — на вопрос об остатке. Пока второе затирало первое,
    после позднего взгляда узнать, почему изменение попало в реестр, было
    нечем — а счёт этих причин и есть мера надёжности канала.
    """
    было = module.Entry(7, module.STATE_SILENT, "2026-09-10")
    стало = module.mark_late({7: было}, 7, "2026-09-12")[7]
    assert стало.state == было.state, "прежнее состояние затёрто"
    assert стало.merged == было.merged
    assert стало.late == "2026-09-12"
    assert стало.said() == f"- #7 · {было.state} · 2026-09-10 · поздний взгляд 2026-09-12"
    assert module.parse_entries(стало.said())[7] == стало, "своя же строка не разбирается обратно"


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
    posted = {"body": late, "user": {"type": "Bot", "login": module.LATE_AUTHOR}}
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter([posted]))
    assert module.look_at("owner/repo", 77, "token") == module.STATE_NONE


def test_a_verdict_quoting_the_late_marker_is_still_a_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Взгляд до слияния, процитировавший метку, не теряет вердикт (взгляд на #815).

    Прежде из ленты выпадал любой комментарий со строкой метки, и ревьюер,
    разбиравший сам механизм позднего взгляда, оставлял изменение «без взгляда».
    """
    quoting = {
        "body": f"разбор: метка `{module.LATE_MARKER}` читается реестром\nВЕРДИКТ: находок 0",
        "user": {"type": "Bot", "login": "claude[bot]"},
    }
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_, **__: iter([quoting]))
    assert module.look_at("owner/repo", 77, "token") is None


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


# --- очередь позднего взгляда ------------------------------------------------


def test_the_queue_takes_the_oldest_first() -> None:
    """Очередь берёт самые СТАРЫЕ непросмотренные.

    Свежее слитое ещё может получить вердикт само — ревьюер бывает медленнее
    очереди, и запись снимется на следующем заходе. Старое такой надежды не
    имеет: чем дольше изменение лежит без взгляда, тем вернее, что его не
    посмотрит никто.
    """
    entries = {
        120: module.Entry(120, module.STATE_NONE, "2026-09-10"),
        73: module.Entry(73, module.STATE_SILENT, "2026-09-09"),
        95: module.Entry(95, module.STATE_CUT, "2026-09-10"),
    }
    assert module.queue_of(entries) == [73, 95, 120]


def test_the_oldest_is_counted_by_the_merge_date_not_the_number() -> None:
    """Выборка, где номер и дата СПОРЯТ, — и порядок решает дата слияния.

    Номер говорит, когда изменение открыли; очередь про то, сколько оно лежит
    СЛИТЫМ. Здесь #7 открыт раньше всех, но провисел на ревью и слился позже
    всех — значит он самый свежий, а не самый старый. Прежняя сортировка по
    номеру ставила его первым, и прежний тест этого не ловил: в его выборке
    номер и дата были упорядочены одинаково (107). Нашёл внешний взгляд на #131.
    """
    entries = {
        7: module.Entry(7, module.STATE_NONE, "2026-09-12"),
        200: module.Entry(200, module.STATE_SILENT, "2026-09-08"),
        150: module.Entry(150, module.STATE_CUT, "2026-09-10"),
    }
    assert module.queue_of(entries) == [200, 150, 7]


def test_an_entry_without_a_date_is_taken_first() -> None:
    """Даты нет — лежит с неизвестных пор, и это ПЕРВЫЙ в очереди.

    Запись из старой формы реестра даты не несёт. В конец её ставить значило бы
    прятать самое старое за самым понятным (045).
    """
    entries = {
        9: module.Entry(9, module.STATE_NONE, ""),
        3: module.Entry(3, module.STATE_NONE, "2026-09-01"),
    }
    assert module.queue_of(entries) == [9, 3]


def test_the_order_is_defined_when_dates_agree() -> None:
    """При равной дате порядок решает номер: ответ обязан быть одним и тем же.

    Иначе заход отдаёт разную очередь на одном и том же реестре, и «первый в
    очереди» перестаёт быть правилом (053).
    """
    entries = {
        80: module.Entry(80, module.STATE_NONE, "2026-09-09"),
        12: module.Entry(12, module.STATE_NONE, "2026-09-09"),
    }
    assert module.queue_of(entries) == [12, 80]


def test_the_queue_skips_what_was_already_looked_at() -> None:
    """Уже просмотренное в очередь не попадает — в обеих своих формах.

    ФОРМ ДВЕ, А ПРОВЕРЯЛАСЬ ОДНА. Запись, чьё СОСТОЯНИЕ — сам поздний взгляд,
    бывает только у изменения, которого реестр не знал. Обычная выглядит иначе:
    состояние осталось открытым (оно про канал и после взгляда не меняется), а
    поздний взгляд дописан хвостом. Её в выборке не было, и обещание держалось
    на форме, которая в реестре почти не встречается
    ([107](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/107-it-works-for-the-author-means-tested-on-the-authors-sample.md)).

    ЗАМЕР 16.09.2026 на живом #89: все пять записей посмотрены в тот же день, а
    очередь предлагала три из них — по прогону агента за заход, без конца.
    """
    entries = {
        73: module.Entry(73, module.STATE_LATE, "2026-09-09"),
        88: module.Entry(88, module.STATE_SILENT, "2026-09-09", "2026-09-16"),
        95: module.Entry(95, module.STATE_NONE, "2026-09-10"),
    }
    assert module.queue_of(entries) == [95]


# --- снятие просмотренного и счёт осечек --------------------------------------


def test_an_updated_state_keeps_the_look_tail() -> None:
    """Уточнение состояния не стирает хвост позднего взгляда.

    Состояние уточняется само собой: оборванный ответ дописывают, прогон
    доезжает. Пока запись при этом пересобиралась заново, `late` терялся — и
    уже посмотренная запись молча возвращалась в список, снятие отменялось,
    очередь снова предлагала её на прогон агента. Нашёл внешний взгляд
    находкой `093d002` на #391 в тот же день, когда снятие и завели.
    """
    known = {88: module.Entry(88, module.STATE_CUT, "2026-09-09", "2026-09-16")}
    entries, _ = module.scan([], known, 100, lambda number: module.STATE_SILENT)
    assert entries[88].state == module.STATE_SILENT
    assert entries[88].late == "2026-09-16", "хвост взгляда потерян при уточнении состояния"
    assert entries[88].merged == "2026-09-09", "дата слияния потеряна"
    # И следствие: такая запись снимается, а не возвращается в список.
    left, tally = module.retire(entries, {})
    assert left == {}, left
    assert tally == {module.STATE_SILENT: 1}, tally


def test_a_looked_remnant_is_told_by_the_tail_not_the_state() -> None:
    """«Остаток посмотрен» читается по хвосту взгляда, а не по состоянию.

    Состояние отвечает на вопрос о канале и после позднего взгляда не меняется:
    осечка уже случилась. Спрашивать по нему «смотрели ли» значит спрашивать
    не о том — и именно так очередь и промахивалась.
    """
    assert module.looked(module.Entry(88, module.STATE_SILENT, "2026-09-09", "2026-09-16"))
    assert not module.looked(module.Entry(95, module.STATE_NONE, "2026-09-10"))
    # Состояние «поздний взгляд» без хвоста — запись, которую ЗАВЕЛ поздний
    # взгляд, но дату ей ещё не проставили: смотреть на неё как на посмотренную
    # значило бы поверить состоянию, а не факту.
    assert not module.looked(module.Entry(73, module.STATE_LATE, "2026-09-09"))


def test_an_empty_tally_is_said_in_words_not_by_a_blank() -> None:
    """Пустой счёт объявляется словом: пропуск строки читается как поломка (154)."""
    said = module.said_tally({})
    assert said.startswith(module.TALLY_HEAD)
    assert "пусто" in said, said


def test_the_tally_is_written_in_a_defined_order() -> None:
    """Порядок слагаемых определён, иначе тело переписывается на ровном месте.

    Задача правится по месту каждым заходом: если порядок зависит от прихода,
    два одинаковых счёта дают разные тела, и читатель видит правку там, где
    ничего не изменилось (053).
    """
    one = module.said_tally({module.STATE_SILENT: 3, module.STATE_CUT: 1})
    two = module.said_tally({module.STATE_CUT: 1, module.STATE_SILENT: 3})
    assert one == two, (one, two)


def test_a_looked_remnant_leaves_the_registry() -> None:
    """Остаток посмотрен — запись уходит из списка, а не висит навсегда.

    Список здесь — то, на что ещё никто не смотрел. Пока снятия не было вовсе,
    он только рос; список, который не пустеет, перестают читать вместе со
    свежими записями (051).
    """
    entries = {
        88: module.Entry(88, module.STATE_SILENT, "2026-09-09", "2026-09-16"),
        95: module.Entry(95, module.STATE_NONE, "2026-09-10"),
    }
    left, tally = module.retire(entries, {})
    assert list(left) == [95], left
    assert tally == {module.STATE_SILENT: 1}, tally


def test_the_state_of_a_retired_record_is_not_lost() -> None:
    """Состояние снятой записи переезжает в счёт, а не пропадает.

    Состояние — мера надёжности канала, и счёт этих причин уже был нужен
    однажды: предмет автоперезапуска искали среди исходов проверок, не найдя
    его там по построению.
    """
    tally = {module.STATE_SILENT: 2}
    entries = {
        88: module.Entry(88, module.STATE_SILENT, "2026-09-09", "2026-09-16"),
        90: module.Entry(90, module.STATE_NONE, "2026-09-09", "2026-09-16"),
    }
    _, counted = module.retire(entries, tally)
    assert counted == {module.STATE_SILENT: 3, module.STATE_NONE: 1}, counted


def test_a_late_look_is_not_counted_as_a_channel_miss() -> None:
    """Запись, чьё состояние — сам поздний взгляд, в счёт осечек не идёт (044).

    Это аудит общей ветки, а не пропущенный взгляд на изменение. Считать её
    значило бы завысить меру тем самым механизмом, который её и чинит.
    """
    entries = {73: module.Entry(73, module.STATE_LATE, "2026-09-09", "2026-09-16")}
    left, tally = module.retire(entries, {})
    assert left == {}, left
    assert tally == {}, tally


def test_the_tally_survives_a_round_trip() -> None:
    """Счёт читается обратно из тела: другого хранилища у него нет."""
    tally = {module.STATE_SILENT: 3, module.STATE_CUT: 1}
    body = module.render_body({}, 387, tally)
    assert module.parse_tally(body) == tally, module.parse_tally(body)


def test_an_empty_tally_says_so_in_words() -> None:
    """Пустой счёт объявляется словом: «счёта нет» и «осечек нет» иначе слипаются."""
    body = module.render_body({}, 387, {})
    assert module.TALLY_HEAD in body
    assert module.parse_tally(body) == {}
    assert "пусто" in body[body.index(module.TALLY_HEAD) :].splitlines()[0]


def test_only_the_tally_line_is_read_as_the_tally() -> None:
    """Счёт берётся со СВОЕЙ строки, а не образцом по всему телу.

    Тело этой задачи читают и правят люди: в нём бывает и приписка, и цитата
    из разбора, и в них те же кавычки с тем же числом. Разбор по всему
    документу принял бы такую строку за слагаемое и завысил бы меру — молча,
    потому что снаружи оба числа выглядят одинаково правдоподобно (045).

    ПОЙМАНО ОТКАТОМ. Первая редакция этой проверки брала тело, собранное самим
    механизмом, и ничего не проверяла: перечень состояний в нём кончается
    словами, а не числом, и разбор по всему телу давал тот же ответ. Откат на
    разбор по всему телу не покраснел — проверка была зелёной впустую (075).
    """
    body = module.render_body({}, 387, {module.STATE_SILENT: 2})
    body += f"\nВ разборе на #333 говорилось: «{module.STATE_CUT}» — 9 раз за неделю.\n"
    assert module.parse_tally(body) == {module.STATE_SILENT: 2}, module.parse_tally(body)


def test_the_queue_is_bounded() -> None:
    """Очередь ограничена: каждый поздний взгляд — прогон агента.

    Ограничение не про нагрузку площадки, а про цену: заход, берущий всё
    накопленное разом, съел бы смену целиком (051).
    """
    entries = {n: module.Entry(n, module.STATE_NONE, "2026-09-10") for n in range(1, 20)}
    assert len(module.queue_of(entries)) == module.LOOK_AT_ONCE


def test_an_empty_queue_is_a_state_not_a_failure() -> None:
    """Смотреть нечего — это пустой список, а не отказ."""
    assert module.queue_of({}) == []


# --- что нашёл внешний взгляд: запись есть, а вердикта нет --------------------


def test_a_skipped_review_is_not_a_missing_one() -> None:
    """Шаг пропущен условием — это не «прогон не запускался» (находка #127).

    Площадка отдаёт `skipped`, когда условие вычислено и оказалось ложным:
    запись есть и она говорит «пропущено». Форк-изменение получало «вердикта
    нет» — то есть читателя отправляли смотреть, почему шаг не запускался,
    когда он и не должен был.
    """
    runs = [{"name": module.REVIEW_CHECK, "status": "completed", "conclusion": "skipped"}]
    assert module.why_quiet(runs) == module.STATE_SKIPPED


def test_a_cancelled_review_is_not_a_missing_one() -> None:
    """Отменённый прогон зовёт смотреть, кто его гасит, а не условия шага (154)."""
    runs = [{"name": module.REVIEW_CHECK, "status": "completed", "conclusion": "cancelled"}]
    assert module.why_quiet(runs) == module.STATE_CANCELLED


def test_a_running_review_is_not_a_missing_one() -> None:
    """Прогон ещё идёт — вердикта нет и не должно быть: спрашивать рано."""
    runs = [{"name": module.REVIEW_CHECK, "status": "in_progress", "conclusion": None}]
    assert module.why_quiet(runs) == module.STATE_RUNNING


def test_a_failure_still_outranks_the_rest() -> None:
    """«Упал» важнее всего прочего: иначе отменённый сосед спрятал бы красное."""
    runs = [
        {"name": module.REVIEW_CHECK, "status": "completed", "conclusion": "cancelled"},
        {"name": module.REVIEW_CHECK, "status": "completed", "conclusion": "failure"},
    ]
    assert module.why_quiet(runs) == module.STATE_BROKEN


def test_no_record_at_all_is_still_its_own_state() -> None:
    """Записи нет вовсе — это по-прежнему отдельное состояние, а не «пропущено»."""
    assert module.why_quiet([]) == module.STATE_NONE
    assert module.why_quiet([{"name": "ci", "conclusion": "success"}]) == module.STATE_NONE


def test_every_state_is_described_in_the_registry() -> None:
    """Каждое состояние объяснено в теле реестра, а не только названо (046).

    Состояние, которого нет в объяснении, читатель встретит в списке и не
    поймёт, что с ним делать, — а именно ради этого реестр и заведён.
    """
    body = module.render_body({}, "#0")
    missing = [state for state in module.STATES if state not in body]
    assert not missing, f"состояния названы, но не объяснены: {missing}"


def test_a_running_run_outranks_yesterdays_green() -> None:
    """Идущий прогон сильнее прошлого исхода (находка #180).

    Повторный заход руками кладёт новую запись рядом со старой. Пока «прошёл»
    проверялся первым, свежий идущий прогон прятался за вчерашним зелёным —
    реестр говорил «прошёл, а ответа нет» там, где ответа ещё просто не было.
    """
    runs = [
        {"name": module.REVIEW_CHECK, "status": "completed", "conclusion": "success"},
        {"name": module.REVIEW_CHECK, "status": "in_progress", "conclusion": None},
    ]
    assert module.why_quiet(runs) == module.STATE_RUNNING


def test_a_zombie_record_is_not_running() -> None:
    """Запись с готовым исходом при переходном состоянии идущей не считается.

    Площадка оставляет такие записи-зомби; принять их за идущие значило бы
    ждать вечно. Тот же приём и по той же причине — в `ci_complete.roster_of`.
    """
    runs = [{"name": module.REVIEW_CHECK, "status": "in_progress", "conclusion": "success"}]
    assert module.why_quiet(runs) == module.STATE_SILENT


def test_an_unknown_conclusion_is_named_with_its_word() -> None:
    """Исход, которого разбор не знает, называется, а не сворачивается в «нет записи».

    Запись ЕСТЬ, и говорить «шаг не запускался» значит послать читателя искать
    не там (046). Слово исхода — от площадки: догадываться о нём нечем (154).
    """
    runs = [{"name": module.REVIEW_CHECK, "status": "completed", "conclusion": "timed_out"}]
    said = module.why_quiet(runs)
    assert said.startswith(module.STATE_ODD)
    assert "timed_out" in said


def test_every_unknown_conclusion_is_listed_once() -> None:
    """Несколько незнакомых исходов названы все и без повторов (159)."""
    runs = [
        {"name": module.REVIEW_CHECK, "status": "completed", "conclusion": "neutral"},
        {"name": module.REVIEW_CHECK, "status": "completed", "conclusion": "stale"},
        {"name": module.REVIEW_CHECK, "status": "completed", "conclusion": "neutral"},
    ]
    said = module.why_quiet(runs)
    assert "neutral" in said and "stale" in said
    assert said.count("neutral") == 1


def test_skipped_means_a_fork_and_says_so() -> None:
    """«Пропущено» означает форк, и только его (находка #180).

    Правка самого файла прогона сюда не относится: джоб при ней стартует,
    отказывается работать действие, а шаг объявлен `continue-on-error` —
    запись выходит ЗЕЛЁНОЙ. Живой случай #120 лежит в реестре как «прогон
    прошёл, а ответа нет», и прежняя редакция противоречила собственному замеру.
    """
    assert "форк" in module.STATE_SKIPPED
    assert "прогона" not in module.STATE_SKIPPED
    body = module.render_body({}, "#0")
    place = body.index(module.STATE_SILENT)
    assert "continue-on-error" in body[place : place + 700], "причина не названа там, где живёт"


def test_a_state_with_a_suffix_is_still_open() -> None:
    """Состояние с суффиксом исхода перечитывается наравне с голым (находка #187).

    «Исход, которого разбор не знает» несёт САМ исход суффиксом — иначе он
    ничего не говорит читателю. При точном сравнении такая запись выпадала из
    всех трёх проверок сразу.
    """
    odd = f"{module.STATE_ODD}: timed_out"
    assert module.is_open(odd), "запись с суффиксом не перечитывается — снять её нечем"
    assert module.is_open(module.STATE_NONE)
    assert not module.is_open(module.STATE_LATE), "поздний взгляд открытым не считается"


def test_a_suffixed_state_is_counted_as_unlooked_not_as_looked() -> None:
    """Такая запись считается НЕПРОСМОТРЕННОЙ, а не «позже просмотренной».

    Худшее из трёх следствий точного сравнения: механизм объявлял взглядом то,
    на что никто не смотрел (045).
    """
    entries = {
        7: module.Entry(7, f"{module.STATE_ODD}: stale", "2026-09-11"),
        8: module.Entry(8, module.STATE_LATE, "2026-09-11"),
    }
    assert module.queue_of(entries) == [7]


def test_a_suffixed_state_is_re_read_on_the_next_pass() -> None:
    """Заход перечитывает такую запись, и она уходит сама, когда вердикт пришёл.

    Обещание реестра — «запись снимается сама, если вердикт всё же появился».
    Для состояний с суффиксом оно не выполнялось ни разу.
    """
    entries = {7: module.Entry(7, f"{module.STATE_ODD}: neutral", "2026-09-11")}
    left, _ = module.scan([], entries, 0, lambda number: None)
    assert 7 not in left, "запись не перечитана — снять её было бы нечем"


def test_the_queue_answer_is_one_line_on_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ответ `--queue` — РОВНО одна строка: его читает оболочка, а не человек.

    Шаг взгляда берёт очередь как ``numbers=$(python scripts/unlooked.py
    --queue)`` и кладёт результат в `$GITHUB_OUTPUT`. Любая вторая строка
    уезжает туда же без ``ключ=``, и площадка роняет джоб на
    ``Invalid format``. Так заход позднего взгляда падал 18 и 19.09.2026:
    второй строкой была приставка пробного режима.
    """
    monkeypatch.setenv("GH_TOKEN", "т")
    monkeypatch.setattr(module.findings, "live_issue", lambda *_, **__: (7, ""))
    assert module.main(["--repo", "o/r", "--queue"]) == module.EXIT_NOTHING
    said = capsys.readouterr()
    assert said.out.splitlines() == ["[]"], f"на stdout не один машинный ответ: {said.out!r}"


def test_the_queue_still_names_its_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Вторая половина: режим назван — просто в другом потоке (045).

    Без неё «одна строка на stdout» достигалось бы и молчанием о режиме, а
    молчание — ровно то ослабление, ради запрета которого приставка и заведена.
    """
    monkeypatch.setenv("GH_TOKEN", "т")
    monkeypatch.setattr(module.findings, "live_issue", lambda *_, **__: (7, ""))
    module.main(["--repo", "o/r", "--queue"])
    assert module.report.DRY in capsys.readouterr().err


def test_a_refusal_named_on_the_check_outranks_plain_silence() -> None:
    """Зелёная проверка с аннотацией отказа — «действие отказало», а не «тишина».

    ЗАМЕР 23.09.2026 (#673): объявленную модель CLI не знал, каждый заход
    кончался за 0–1 с, а реестр мог сказать только «прошёл, а ответа нет».
    Теперь причина названа на проверке шагом `agent_run.py`, и реестр её
    различает. Вторая половина: без пометки зелёная тишина остаётся тишиной.
    """
    marked = {"name": "review", "conclusion": "success", module.REFUSED_KEY: True}
    assert module.why_quiet([marked]) == module.STATE_REFUSED
    assert module.why_quiet([{"name": "review", "conclusion": "success"}]) == module.STATE_SILENT


def test_only_the_refusal_words_make_a_refusal() -> None:
    """Отказом считается аннотация со словами `agent_run.REFUSED`, а не любая ошибка.

    Уровень ошибки ставит и площадка («Process completed with exit code 1»),
    а модель захода — отдельная аннотация; ни то, ни другое отказом не является.
    """
    words = module.agent_run.REFUSED
    assert module.refused([{"annotation_level": "failure", "message": f"взгляд: {words} — 404"}])
    assert not module.refused(
        [{"annotation_level": "notice", "message": "взгляд: модель захода — x"}]
    )
    assert not module.refused(
        [{"annotation_level": "failure", "message": "Process completed with exit code 1."}]
    )


def test_head_runs_asks_annotations_only_of_the_review_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Аннотации спрашиваются у проверки взгляда с аннотациями — и больше ни у кого."""
    asked: list[str] = []
    runs = [
        {"id": 1, "name": "review", "conclusion": "success", "output": {"annotations_count": 2}},
        {"id": 2, "name": "lint", "conclusion": "success", "output": {"annotations_count": 5}},
        {"id": 3, "name": "review", "conclusion": "success", "output": {"annotations_count": 0}},
    ]

    def request(_method: str, path: str, *_rest: Any, **_kw: Any) -> Any:
        return {"head": {"sha": "c" * 40}}

    def paginate(path: str, *_rest: Any, **_kw: Any) -> Any:
        asked.append(path)
        if path.endswith("/annotations"):
            return iter(
                [{"annotation_level": "failure", "message": f"x: {module.agent_run.REFUSED} — y"}]
            )
        return iter([dict(one) for one in runs])

    monkeypatch.setattr(module.ghrest, "request", request)
    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    found = module.head_runs("o/r", 5, "t")
    assert [path for path in asked if path.endswith("/annotations")] == [
        "repos/o/r/check-runs/1/annotations"
    ]
    assert found[0][module.REFUSED_KEY] is True and module.REFUSED_KEY not in found[1]


def test_a_step_without_a_token_is_the_broken_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Токена нет — исход «шаг не отработал», а не «реестр пуст».

    Прежде этот исход засчитывался прогнанным по чужому `assert … == 2` в
    соседнем наборе: распознаватель исходов узнаёт код по числу. Здесь он
    прогнан по имени.
    """
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    assert module.main(["--repo", "o/r"]) == module.EXIT_BROKEN


def test_a_silent_platform_is_the_broken_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка молчит — исход «шаг не отработал», а не «нечего записывать» (045)."""

    def refuse(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("502")

    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.ghrest, "request", refuse)
    monkeypatch.setattr(module.ghrest, "paginate", refuse)
    assert module.main(["--repo", "o/r"]) == module.EXIT_BROKEN


def test_the_body_quotes_the_line_the_run_prints(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Цитата тела реестра — дословно та строка, что печатает заход (`14c2553`).

    Тело велит искать в логе строку «аннотации взгляда не прочитаны», а заход
    печатал «аннотации взгляда по #N не прочитаны» — поиск по цитате не
    находил ничего.
    """
    runs = [
        {"id": 1, "name": "review", "conclusion": "success", "output": {"annotations_count": 1}}
    ]

    def paginate(path: str, *_rest: Any, **_kw: Any) -> Any:
        if path.endswith("/annotations"):
            raise module.ghrest.TransportError("502")
        return iter([dict(one) for one in runs])

    monkeypatch.setattr(module.ghrest, "request", lambda *_a, **_k: {"head": {"sha": "c" * 40}})
    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    module.head_runs("o/r", 5, "t")
    printed = capsys.readouterr().out
    quoted = re.search(r"строкой «([^»]+)»", module.render_body({}, 0))
    assert quoted is not None, "тело реестра больше не цитирует строку захода"
    assert quoted[1] in printed, f"цитата «{quoted[1]}» не находится в печати: {printed!r}"


def test_an_unread_annotation_keeps_the_runs_already_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ на аннотациях не уносит записи проверок: «прошёл» остаётся «прошёл» (`3d25893`).

    Причина — уточнение к записи; потерять из-за неё саму запись значило бы
    разменять факт на подробность (084).
    """
    runs = [
        {"id": 1, "name": "review", "conclusion": "success", "output": {"annotations_count": 1}}
    ]

    def request(_method: str, path: str, *_rest: Any, **_kw: Any) -> Any:
        return {"head": {"sha": "c" * 40}}

    def paginate(path: str, *_rest: Any, **_kw: Any) -> Any:
        if path.endswith("/annotations"):
            raise module.ghrest.TransportError("502")
        return iter([dict(one) for one in runs])

    monkeypatch.setattr(module.ghrest, "request", request)
    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    found = module.head_runs("o/r", 5, "t")
    assert [one["id"] for one in found] == [1]
    assert module.why_quiet(found) == module.STATE_SILENT


def test_the_body_quotes_the_refusal_in_the_words_agent_run_writes() -> None:
    """Слова отказа в теле реестра — те, что пишет `agent_run` (`359f9c5`).

    Цитата стояла вписанной рукой: правка фразы в `agent_run.py` развела бы
    тело с аннотацией, и искать по телу стало бы нечего.
    """
    body = module.render_body({}, 0)
    assert f"«{module.agent_run.REFUSED} — <текст>»" in body


def test_the_late_tail_is_read_and_quoted_by_its_constant() -> None:
    """Хвост позднего взгляда пишется, читается и цитируется одной константой.

    Прежде `ENTRY_RE` и тело реестра несли слова хвоста вписанными рукой:
    правка `LATE_TAIL` развела бы записи с разбором молча (`5bd5689`,
    `17273d5`). Запись с хвостом переживает круг «записать — прочитать».
    """
    assert re.escape(module.LATE_TAIL) in module.ENTRY_RE.pattern
    assert f"«{module.LATE_TAIL} ДАТА»" in module.render_body({}, 0)
    line = module.Entry(5, module.STATE_SILENT, "2026-09-24", "2026-09-25").said()
    found = module.ENTRY_RE.match(line)
    assert found is not None and found[4] == "2026-09-25", line


def test_a_look_skipped_on_a_red_head_is_named_not_silent() -> None:
    """Пропуск воротами на красной голове — своё состояние, а не «тишина» (195, #771)."""
    run = {"name": "review", "conclusion": "success", module.SKIPPED_RED_KEY: True}
    assert module.why_quiet([run]) == module.STATE_SKIPPED_RED
    refused = {**run, module.REFUSED_KEY: True}
    assert module.why_quiet([refused]) == module.STATE_REFUSED, "названный отказ сильнее пропуска"


def late_answer(day: str) -> dict[str, Any]:
    """Ответ позднего взгляда в ленте: отметка и вердикт, от имени прогона."""
    return {
        "user": {"type": "Bot", "login": module.LATE_AUTHOR},
        "body": f"{module.LATE_MARKER}\nВЕРДИКТ: находок 2",
        "created_at": f"{day}T12:00:00Z",
    }


def test_a_late_look_is_seen_in_the_feed_by_its_marker() -> None:
    """Поздний взгляд узнаётся по отметке переноса — тот же признак, что у `--late` (#790).

    Ответ без строки `ВЕРДИКТ` — тоже перенесённый ответ: шаг отметил бы его в
    реестре, и лента обязана вернуть ту же отметку, если её стёрла гонка.
    """
    assert module.late_seen([late_answer("2026-09-24")]) == "2026-09-24"
    unanswered = {
        "user": {"type": "Bot", "login": module.LATE_AUTHOR},
        "body": module.LATE_MARKER,
        "created_at": "2026-09-24T12:00:00Z",
    }
    assert module.late_seen([unanswered]) == "2026-09-24"
    # Цитата метки человеком — не поздний взгляд (взгляд на #810).
    quoted = {**unanswered, "user": {"type": "User", "login": "someone"}}
    assert module.late_seen([quoted]) == ""
    # Ответчик по обращению пишет тем же `claude[bot]`, что и ревьюер: «бот»
    # его не отсекает, отсекает автор прогона (взгляд на #815, `1d79af0`).
    responder = {**unanswered, "user": {"type": "Bot", "login": "claude[bot]"}}
    assert module.late_seen([responder]) == ""
    # Метка не первой строкой — цитата, даже от имени прогона.
    inside = {**unanswered, "body": f"сказано:\n{module.LATE_MARKER}"}
    assert module.late_seen([inside]) == ""
    assert (
        module.late_seen([{"body": "ВЕРДИКТ: находок 0", "created_at": "2026-09-24T12:00:00Z"}])
        == ""
    )


def test_a_late_look_lost_by_a_racing_write_is_restored_from_the_feed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отметка позднего взгляда, стёртая чужой записью, восстанавливается по ленте (#89).

    Реестр пишут два прогона, и заход очереди, начатый до отметки позднего
    взгляда, стирал её своим снимком: #761, #768, #769 висели «без взгляда»,
    хотя ответ позднего взгляда лежал в их лентах.
    """
    body = (
        f"{module.MARKER}\n"
        "- #761 · прогон взгляда прошёл, а ответа нет · 2026-09-24\n"
        "- #773 · вердикта нет · 2026-09-24\n"
    )
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.findings, "live_issue", lambda repo, token, marker: (89, body))
    monkeypatch.setattr(module, "merged_changes", lambda repo, token, limit: [])
    monkeypatch.setattr(module, "look_at", lambda repo, number, token, *_: module.STATE_SILENT)
    feeds = {761: [late_answer("2026-09-24")], 773: []}
    monkeypatch.setattr(
        module, "late_on", lambda repo, number, token, *_: module.late_seen(feeds[number])
    )
    module.main(["--repo", "o/r"])
    said = capsys.readouterr().out
    assert "сняты: #761" in said, said
    # #773 ОСТАЁТСЯ ОТКРЫТЫМ — проверяется его строкой в списке и счётом, а не
    # упоминанием: номер печатается при любом исходе (взгляд на #790).
    assert "сняты: #761\n" in said, said
    assert "слито без взгляда: 1," in said
    assert any(line.strip().startswith("#773 ·") for line in said.splitlines()), said


def test_late_on_reads_the_feed_of_the_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """`late_on` спрашивает ленту изменения у площадки."""

    def paginate(path: str, token: str, **_: Any) -> Any:
        assert path == "repos/o/r/issues/761/comments"
        return iter([late_answer("2026-09-23")])

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    assert module.late_on("o/r", 761, "t") == "2026-09-23"


def test_the_late_queue_runs_after_every_ci_on_the_trunk() -> None:
    """Очередь позднего взгляда идёт и после `ci` на общей ветке, а не только ночью (#89).

    Слитое без взгляда ждало ночи, а ночная очередь берёт три за заход: за
    день таких набралось пять.
    """
    import yaml

    flow = yaml.safe_load((ROOT / ".github/workflows/review.yml").read_text(encoding="utf-8"))
    condition = str(flow["jobs"]["late-queue"]["if"])
    for event in ("schedule", "workflow_dispatch", "workflow_run"):
        assert f"github.event_name == '{event}'" in condition, f"очередь не идёт по {event}"
    assert "workflow_run" in (flow.get(True) or flow.get("on") or {}), "прогон не слушает ci"


def test_the_feed_is_read_once_per_change_in_a_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Лента изменения читается один раз за заход, хоть её спрашивают двое (#790)."""
    asked: list[str] = []

    def paginate(path: str, token: str, **_: Any) -> Any:
        asked.append(path)
        return iter([])

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    feed = module.feed_reader("o/r", "t")
    module.late_on("o/r", 761, "t", feed)
    module.late_on("o/r", 761, "t", feed)
    assert asked == ["repos/o/r/issues/761/comments"]


def test_an_unread_feed_does_not_break_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ленту одной записи не прочитать — отметка пуста, заход идёт, отказ назван (084)."""

    def refused(path: str, token: str, **_: Any) -> Any:
        raise module.ghrest.TransportError("502")

    monkeypatch.setattr(module.ghrest, "paginate", refused)
    assert module.late_on("o/r", 761, "t") == ""
    assert "не сверен с лентой" in capsys.readouterr().err


def test_the_queue_skips_what_the_feed_says_was_looked_at(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Очередь сверяется с лентой: посмотренное не ставится второй раз, место берёт следующий."""
    entries = {
        number: module.Entry(number, module.STATE_SILENT, f"2026-09-2{i}")
        for i, number in enumerate((761, 768, 769, 773))
    }
    seen = {761: "2026-09-24"}
    queue = module.queue_checked(entries, lambda number: seen.get(number, ""), limit=3)
    assert queue == [768, 769, 773], "посмотренный стоял бы в очереди на платный прогон"
    assert "#761: поздний взгляд был 2026-09-24" in capsys.readouterr().err


def test_the_queue_run_checks_the_feed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Заход `--queue` сверяет очередь с лентой, а не верит телу реестра (#790)."""
    body = (
        f"{module.MARKER}\n- #761 · вердикта нет · 2026-09-20\n- #768 · вердикта нет · 2026-09-21\n"
    )
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.findings, "live_issue", lambda repo, token, marker: (89, body))
    feeds = {761: [late_answer("2026-09-24")], 768: []}
    monkeypatch.setattr(
        module, "late_on", lambda repo, number, token, *_: module.late_seen(feeds[number])
    )
    module.main(["--repo", "o/r", "--queue"])
    out = capsys.readouterr().out
    # stdout идёт в `$GITHUB_OUTPUT`: ровно одна строка JSON, без соседей (#810).
    assert out.strip().splitlines() == [json.dumps([768])], out


def test_the_queue_output_stays_one_line_when_a_feed_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отказ ленты кандидата не добавляет строк в stdout `--queue` (взгляд на #810)."""
    body = f"{module.MARKER}\n- #761 · вердикта нет · 2026-09-20\n"
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "t")
    monkeypatch.setattr(module.findings, "live_issue", lambda repo, token, marker: (89, body))

    def refused(path: str, token: str, **_: Any) -> Any:
        raise module.ghrest.TransportError("502")

    monkeypatch.setattr(module.ghrest, "paginate", refused)
    module.main(["--repo", "o/r", "--queue"])
    said = capsys.readouterr()
    assert said.out.strip().splitlines() == [json.dumps([761])], said.out
    assert "не сверен с лентой" in said.err


@pytest.mark.parametrize(
    ("login", "body", "late"),
    [
        (module.LATE_AUTHOR, f"{module.LATE_MARKER}\nответ", True),
        (module.LATE_AUTHOR, f"\n  {module.LATE_MARKER}\nответ", True),
        ("claude[bot]", f"{module.LATE_MARKER}\nответ", False),
        (module.LATE_AUTHOR, f"цитата {module.LATE_MARKER}", False),
        ("", module.LATE_MARKER, False),
    ],
    ids=["прогон", "пробел впереди", "ответчик", "не первой строкой", "без автора"],
)
def test_is_late_look_needs_the_run_and_the_first_line(login: str, body: str, late: bool) -> None:
    """Поздний взгляд — автор-прогон и метка первой строкой, а не любое вхождение."""
    assert module.is_late_look({"user": {"login": login}, "body": body}) is late


def test_a_verifier_answer_is_not_a_late_look() -> None:
    """Ответ верификатора пишет тот же шаг тем же токеном, но это не поздний взгляд (#815)."""
    late_look = load_script("late_look.py")
    posted = {
        "user": {"type": "Bot", "login": module.LATE_AUTHOR},
        "body": late_look.compose_verification("ПРЕМИСА: подтверждена — так"),
        "created_at": "2026-09-25T12:00:00Z",
    }
    assert not module.is_late_look(posted)
    assert module.late_seen([posted]) == ""


def test_a_verifier_answer_is_not_a_look_before_the_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ответ верификатора с `ВЕРДИКТ:` не делает изменение просмотренным (взгляд на #825)."""
    late_look = load_script("late_look.py")
    posted = {
        "user": {"type": "Bot", "login": module.LATE_AUTHOR},
        "body": late_look.compose_verification("ПРЕМИСА: подтверждена — так\nВЕРДИКТ: находок 0"),
    }
    monkeypatch.setattr(module, "head_runs", lambda *_a, **_k: [])
    assert module.look_at("o/r", 7, "t", lambda _n: [posted]) == module.STATE_NONE


@pytest.mark.parametrize(
    ("login", "body", "answer"),
    [
        (module.LATE_AUTHOR, f"{module.VERIFY_MARKER}\nПРЕМИСА: да", True),
        (module.LATE_AUTHOR, f"{module.LATE_MARKER}\nответ", True),
        ("claude[bot]", f"{module.VERIFY_MARKER}\nВЕРДИКТ: находок 0", False),
        (module.LATE_AUTHOR, "ВЕРДИКТ: находок 0", False),
    ],
    ids=["верификатор", "поздний взгляд", "цитата ревьюера", "без метки"],
)
def test_is_run_answer_needs_the_run_and_a_marker(login: str, body: str, answer: bool) -> None:
    """Ответ прогона — автор-прогон и одна из двух меток первой строкой."""
    assert module.is_run_answer({"user": {"login": login}, "body": body}) is answer
