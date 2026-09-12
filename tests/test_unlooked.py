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
    """Уже просмотренное в очередь не попадает: у него состояние не открытое."""
    entries = {
        73: module.Entry(73, module.STATE_LATE, "2026-09-09"),
        95: module.Entry(95, module.STATE_NONE, "2026-09-10"),
    }
    assert module.queue_of(entries) == [95]


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
