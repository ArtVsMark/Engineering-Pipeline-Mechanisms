"""Ряд прогонов: что он обязан отвергнуть и чего не обязан помнить.

Отвергаемое здесь тройное, и каждая ошибка правдоподобна снаружи:

* **дыра в ряду** — пропущенный заход по расписанию оставил бы день
  несосчитанным навсегда, а ряд с дырой отвечает средним по остальным;
* **ряд без предела** — файл, который только растёт, однажды перестают читать, и
  чистка «когда придёт потребитель» обрывает ряд ровно в момент нужды;
* **ноль вместо «не сказано»** — заход без разобранного времени, засчитанный
  нулём, занижает среднее молча
  ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, load_script

module = load_script("runs_series.py")

BOUNDS = ROOT / ".rules" / "series.json"


def run(
    name: str, day: str, end: str = "success", seconds: int | None = 60, number: int = 1
) -> dict[str, Any]:
    """Заход площадки — ровно в тех полях, которые читает механизм."""
    said: dict[str, Any] = {
        "id": number,
        "name": name,
        "created_at": f"{day}T10:00:00Z",
        "conclusion": end,
    }
    if seconds is not None:
        said["run_started_at"] = f"{day}T10:00:00Z"
        said["updated_at"] = f"{day}T10:{seconds // 60:02d}:{seconds % 60:02d}Z"
    return said


def platform(
    monkeypatch: pytest.MonkeyPatch, runs: list[dict[str, Any]], jobs: list[str] | None = None
) -> list[str]:
    """Подделывает границу с площадкой и отдаёт список спрошенных адресов."""
    asked: list[str] = []

    def paginate(path: str, token: str, key: str | None = None) -> Any:
        asked.append(path)
        return iter(runs)

    def request(method: str, path: str, token: str, *rest: Any, **kw: Any) -> dict[str, Any]:
        asked.append(path)
        return {"jobs": [{"name": name, "conclusion": "failure"} for name in jobs or []]}

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    monkeypatch.setattr(module.ghrest, "request", request)
    return asked


# --- границы объявлены данными -------------------------------------------------


def test_the_bounds_are_declared_in_data_not_in_code() -> None:
    """Окно ряда читается из объявления, а не зашито в механизм (042)."""
    bounds = module.Bounds.read(BOUNDS)
    assert bounds.window_days > 0 and bounds.recount_days > 0
    assert bounds.recount_days < bounds.window_days, (
        "пересчёт обязан быть короче хранения — иначе окно пересчитывается целиком"
    )
    said = json.loads(BOUNDS.read_text(encoding="utf-8"))
    assert said["window_days"] <= said["kept_days"], (
        "окно шире срока хранения у площадки было бы обещанием, которого механизм не выполнит"
    )


@pytest.mark.parametrize(
    "said",
    [
        pytest.param({}, id="полей нет вовсе"),
        pytest.param({"window_days": 90}, id="пересчёт не объявлен"),
        pytest.param({"window_days": 2, "recount_days": 5}, id="пересчёт шире хранения"),
        pytest.param({"window_days": 90, "recount_days": 0}, id="пересчёт нулевой"),
    ],
)
def test_broken_bounds_are_the_second_outcome(said: dict[str, Any], tmp_path: Path) -> None:
    """Противоречивое объявление — отказ входа, а не молчаливое умолчание (075)."""
    path = tmp_path / "series.json"
    path.write_text(json.dumps(said), encoding="utf-8")
    with pytest.raises(module.NotRun):
        module.Bounds.read(path)


def test_missing_bounds_name_the_file() -> None:
    """Объявления нет — заход называет, какого файла не хватило (158)."""
    with pytest.raises(module.NotRun, match="нет-такого"):
        module.Bounds.read(Path("нет-такого.json"))


# --- время: ноль и «не сказано» — разные вещи ----------------------------------


def test_an_unsaid_duration_is_not_a_zero() -> None:
    """Заход без времени не считается мгновенным и в среднее не входит (045)."""
    assert module.elapsed(run("ci", "2026-09-14", seconds=90)) == 90
    assert module.elapsed(run("ci", "2026-09-14", seconds=None)) is None
    assert module.elapsed({"run_started_at": "не дата", "updated_at": "тоже"}) is None


def test_the_day_of_a_run_is_its_start_at_the_platform() -> None:
    """День захода берётся у площадки, а не у часов машины, где идёт разбор.

    Иначе заход, начатый до полуночи и прочитанный после, уехал бы в чужие сутки
    — и сутки в ряду разошлись бы с сутками площадки молча (049).
    """
    assert module.day_of(run("ci", "2026-09-14")) == "2026-09-14"
    assert module.day_of({}) == "", "нет времени начала — нет и дня, а не сегодняшний"


def test_only_the_failed_jobs_of_a_run_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """У красного захода называются упавшие джобы, а не все его джобы.

    Красный заход почти всегда красен ОДНИМ джобом из десяти, и записать все
    значило бы обвинить девять зелёных (068). `timed_out` при этом красное, а
    `cancelled` — нет: отменённая запись не пройдена, но и отказом не является.

    ПРЕДМЕТ ПЕРЕЕХАЛ С `red_jobs` НА `red_details`, И СВОЙСТВО С НИМ. Первая
    отдавала одни имена и осиротела, когда вторая стала отдавать имя, шаг,
    признак и чей шаг упал. Снять сироту вместе с её проверкой значило бы
    потерять утверждение, которое к замене относится ровно так же (022).
    """

    def request(method: str, path: str, token: str, *rest: object, **kw: object) -> object:
        # Аннотации спрашиваются вторым вызовом и по другому адресу: общий
        # ответ на оба сделал бы разбор признака бессмысленным.
        if path.endswith("/annotations"):
            return []
        return {
            "jobs": [
                {"id": 1, "name": "lint", "conclusion": "success"},
                {"id": 2, "name": "test", "conclusion": "failure"},
                {"id": 3, "name": "debt", "conclusion": "timed_out"},
                {"id": 4, "name": "pr-meta", "conclusion": "cancelled"},
            ]
        }

    monkeypatch.setattr(module.ghrest, "request", request)
    said = [one["name"] for one in module.red_details("o/r", 7, "токен")]
    assert said == ["debt", "test"], said


def test_the_average_counts_only_what_was_timed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Средний заход считается по тем, у кого время известно, а не по всем."""
    platform(
        monkeypatch,
        [
            run("ci", "2026-09-14", seconds=120),
            run("ci", "2026-09-14", seconds=None, number=2),
        ],
    )
    days = module.swept("o/r", "токен", "2026-09-14")
    row = days["2026-09-14"]["ci"]
    assert row == {
        "runs": 2,
        "red": 0,
        "cancelled": 0,
        "seconds": 120,
        "timed": 1,
        "red_jobs": {},
        # ОТЧЁТ ПО КРАСНЫМ КОПИТСЯ РЯДОМ СО СЧЁТОМ (#606): у зелёного дня он
        # пуст, и это состояние, а не отсутствие поля.
        "red_steps": {},
        "red_marks": {},
        "red_whose": {},
    }
    assert module.minutes_of({"2026-09-14": {"runs": days["2026-09-14"]}}, "ci", "2026-09-14") == (
        2.0
    ), "неразобранный заход не тянет среднее вниз"


# --- джобы спрашиваются только у красных ---------------------------------------


def test_only_a_red_run_is_asked_for_its_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Джобы полутора тысяч заходов стоили бы квоты; красных — тринадцать (058)."""
    asked = platform(
        monkeypatch,
        [run("ci", "2026-09-14"), run("ci", "2026-09-14", end="failure", number=7)],
        jobs=["test", "lint"],
    )
    days = module.swept("o/r", "токен", "2026-09-14")
    assert days["2026-09-14"]["ci"]["red_jobs"] == {"test": 1, "lint": 1}
    jobs = [path for path in asked if path.endswith("/jobs")]
    assert jobs == ["repos/o/r/actions/runs/7/jobs"], "спрошен ровно красный, и ровно один раз"


def test_a_cancelled_run_is_counted_apart_from_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отменённая не красная: она не пройдена, но и не отказ."""
    platform(monkeypatch, [run("ci", "2026-09-14", end="cancelled")])
    row = module.swept("o/r", "токен", "2026-09-14")["2026-09-14"]["ci"]
    assert (row["red"], row["cancelled"]) == (0, 1)


def test_a_platform_without_runs_is_the_second_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заходов не отдано ни одного — отказ входа, а не пустой ряд (075)."""
    platform(monkeypatch, [])
    with pytest.raises(module.NotRun):
        module.swept("o/r", "токен", "2026-09-14")


# --- окно: пересчёт молодых, чистка старых -------------------------------------


def test_a_recounted_day_replaces_the_old_row() -> None:
    """Пересчёт закрывает дыру от пропущенного захода, а не добавляет вторую строку."""
    known = {"2026-09-14": {"runs": {"ci": {"runs": 1, "red": 0, "cancelled": 0, "seconds": 1}}}}
    fresh = {"2026-09-14": {"ci": {"runs": 9, "red": 1, "cancelled": 2, "seconds": 90, "timed": 9}}}
    bounds = module.Bounds(window_days=90, recount_days=3)
    days = module.merge(known, fresh, bounds, "2026-09-15")
    assert days["2026-09-14"]["runs"]["ci"]["runs"] == 9, "свежий замер дня побеждает прежний"


def test_the_window_sweeps_what_fell_out_of_it() -> None:
    """Ряд шире окна чистится — проверено на переполнении, а не на замысле."""
    bounds = module.Bounds(window_days=90, recount_days=3)
    начало = date(2026, 3, 1)
    known = {str(начало + timedelta(days=shift)): {"ci": {"runs": 1}} for shift in range(200)}
    days = module.merge(known, {}, bounds, "2026-09-15")
    assert len(days) == bounds.window_days, (
        f"после чистки осталось {len(days)} дней при окне {bounds.window_days}"
    )
    assert min(days) == "2026-06-18" and max(days) == "2026-09-15", (
        "окно кончается нынешним днём и начинается ровно за 90 дней до него"
    )
    assert "2026-09-16" in known and "2026-09-16" not in days, (
        "день из будущего в окно не входит: он вытеснил бы настоящий (075)"
    )


def test_the_window_edge_counts_the_present_day() -> None:
    """Окно в один день оставляет ровно нынешний — граница названа, а не угадана."""
    bounds = module.Bounds(window_days=1, recount_days=1)
    known = {"2026-09-14": {"ci": {"runs": 1}}, "2026-09-15": {"ci": {"runs": 2}}}
    assert module.merge(known, {}, bounds, "2026-09-15") == {"2026-09-15": {"ci": {"runs": 2}}}


def test_the_recount_window_names_its_first_day() -> None:
    """Пересчёт трёх дней начинается позавчера, а не четыре дня назад."""
    assert module.since_day("2026-09-15", 3) == "2026-09-13"
    assert module.since_day("2026-09-15", 1) == "2026-09-15"


# --- отчёт: число с датой, и названное отсутствующее ---------------------------


def test_the_report_answers_with_a_number_and_a_date() -> None:
    """Ответ ряда — число с датой; без даты оно устаревает молча (005)."""
    days = {
        "2026-09-14": {
            "runs": {"ci": {"runs": 10, "red": 1, "cancelled": 4, "seconds": 600, "timed": 10}},
            "coverage": 86.9,
        },
        "2026-09-15": {
            "runs": {"ci": {"runs": 10, "red": 0, "cancelled": 1, "seconds": 900, "timed": 10}},
            "coverage": 87.3,
        },
    }
    said = module.report(days, module.Bounds(window_days=90, recount_days=3), "2026-09-15")
    assert "Собрано 2026-09-15" in said
    assert "25.0 %" in said, "доля погашенных заходов названа числом"
    assert "1.0 мин 2026-09-14 → 1.5 мин 2026-09-15" in said, "время прогона названо по дням"
    assert "реестр #99" in said, "чего в ряду нет — названо, а не умолчано (022)"
    assert "86.9 % 2026-09-14 → 87.3 % 2026-09-15" in said, "покрытие названо числом с днём"
    assert "решение" in said and "владельца" in said, "порог остаётся решением человека"


def test_the_sums_of_the_series_are_counted_across_days() -> None:
    """Числа ряда складываются по всем дням и всем прогонам, а не по одному дню.

    Ряд заведён ради сложения: ответ «сколько гаснет впустую» получается только
    из суммы, и считать его на глаз по строкам значило бы вернуть память вместо
    механизма (005).
    """
    days = {
        "2026-09-14": {
            "runs": {
                "ci": {"runs": 10, "red": 2, "cancelled": 3, "red_jobs": {"test": 2}},
                "hail": {"runs": 4, "red": 0, "cancelled": 1, "red_jobs": {}},
            }
        },
        "2026-09-15": {
            "runs": {
                "ci": {"runs": 6, "red": 1, "cancelled": 0, "red_jobs": {"test": 1, "lint": 1}}
            }
        },
    }
    assert module.total(days, "runs") == 20
    assert module.total(days, "cancelled") == 4
    assert module.reds(days).most_common() == [("test", 3), ("lint", 1)], (
        "имена красных джобов складываются по всему ряду и идут от частого к редкому"
    )
    assert module.total(days, "нет-такого-поля") == 0, (
        "неизвестное поле считается нулём: это сумма отсутствующего, а не отказ"
    )


# --- покрытие: записывается, а не считается ------------------------------------


def test_the_coverage_is_taken_from_the_storefront(monkeypatch: pytest.MonkeyPatch) -> None:
    """Число берётся у витрины, а не считается заново: счёт один (022)."""
    monkeypatch.setattr(
        module.ghrest, "raw_json", lambda url: {"coverage": {"read": True, "percent": 87.34}}
    )
    assert module.coverage_now("o/r") == 87.3


@pytest.mark.parametrize(
    "facts",
    [
        pytest.param({"coverage": {"read": False, "percent": 0.0}}, id="витрина не прочитала"),
        pytest.param({"coverage": {}}, id="поля read нет"),
        pytest.param({}, id="покрытия в фактах нет вовсе"),
        pytest.param({"coverage": {"read": True, "percent": "почти всё"}}, id="не число"),
    ],
)
def test_an_unread_coverage_is_not_a_zero(
    monkeypatch: pytest.MonkeyPatch, facts: dict[str, Any]
) -> None:
    """«Не прочитано» остаётся состоянием: ноль записал бы обвал, которого нет (045)."""
    monkeypatch.setattr(module.ghrest, "raw_json", lambda url: facts)
    assert module.coverage_now("o/r") is None


def test_an_unreachable_storefront_is_not_a_zero_either(monkeypatch: pytest.MonkeyPatch) -> None:
    """Витрина не ответила — у дня просто нет покрытия, и ряд не испорчен."""

    def refuse(url: str) -> dict[str, Any]:
        raise module.ghrest.TransportError("витрина недоступна")

    monkeypatch.setattr(module.ghrest, "raw_json", refuse)
    assert module.coverage_now("o/r") is None


def test_the_coverage_lands_only_on_the_present_day() -> None:
    """Покрытие пишется в нынешний день: витрина публикует текущее число (005)."""
    bounds = module.Bounds(window_days=90, recount_days=3)
    days = module.merge({}, {"2026-09-14": {"ci": {"runs": 1}}}, bounds, "2026-09-15", 87.3)
    assert days["2026-09-15"]["coverage"] == 87.3
    assert "coverage" not in days["2026-09-14"], "вчерашнему дню чужое число не дописывается"


def test_a_recount_does_not_lose_the_coverage_of_that_day() -> None:
    """Пересчёт дня меняет заходы и оставляет покрытие: заново его не прочесть.

    Иначе ряд терял бы вчерашнее покрытие на каждом заходе, и «ряда всё ещё нет»
    получалось бы само собой — а порог ждёт именно ряда (045).
    """
    bounds = module.Bounds(window_days=90, recount_days=3)
    known = {"2026-09-14": {"runs": {"ci": {"runs": 1}}, "coverage": 86.9}}
    days = module.merge(known, {"2026-09-14": {"ci": {"runs": 9}}}, bounds, "2026-09-15", 87.3)
    assert days["2026-09-14"] == {"runs": {"ci": {"runs": 9}}, "coverage": 86.9}
    assert days["2026-09-15"]["coverage"] == 87.3


def test_the_two_fields_of_a_day_are_read_apart() -> None:
    """Заходы и покрытие — разные вопросы одной строки, и читаются по отдельности.

    Пока строка дня была словарём прогонов, покрытию в ней места не было: оно
    оказалось бы «прогоном по имени coverage» и попало бы в суммы заходов (022).
    """
    days = {
        "2026-09-14": {"runs": {"ci": {"runs": 4}}, "coverage": 86.9},
        "2026-09-15": {"runs": {"ci": {"runs": 6}}},
    }
    assert module.runs_of(days, "2026-09-15") == {"ci": {"runs": 6}}
    assert module.runs_of(days, "нет такого дня") == {}
    assert module.total(days, "runs") == 10, "покрытие в счёт заходов не попадает"
    assert module.covered(days) == [("2026-09-14", 86.9)], (
        "прочитанным считается день с числом, а не всякий день ряда"
    )


def test_the_report_names_an_empty_coverage_series() -> None:
    """Ряда покрытия нет — отчёт это говорит, а не пропускает раздел (046)."""
    days = {"2026-09-15": {"runs": {"ci": {"runs": 1, "red": 0, "cancelled": 0}}}}
    said = module.report(days, module.Bounds(window_days=90, recount_days=3), "2026-09-15")
    assert "Ни одного прочитанного числа" in said
    assert "не прочитано" in said


def test_a_dry_walk_writes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Сухой заход считает и не пишет: запись — отдельное разрешение.

    ДАТА ПОДДЕЛКИ ВЫВОДИТСЯ ОТ СЕГОДНЯ, А НЕ ВПИСЫВАЕТСЯ РУКОЙ. Заход через
    `main()` идёт по ЖИВОМУ окну пересчёта — три последних дня, — и рукописная
    дата выходит из него сама, без всякой правки в дереве. Здесь стояло
    «2026-09-15»: проверка была зелёной три дня и покраснела на четвёртый,
    ничего не сломав. Так рукописное число и устаревает
    ([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).

    ПРОЧИЕ ДАТЫ В ЭТОМ ФАЙЛЕ ОСТАЮТСЯ РУКОПИСНЫМИ ЗАКОННО: они идут в разбор с
    ЯВНЫМ `since`, то есть живого окна не касаются. Заминирован календарём был
    ровно этот заход — единственный, который зовёт `main()` с настоящими
    границами.
    """
    сегодня = date.today().isoformat()
    platform(monkeypatch, [run("ci", сегодня)])
    monkeypatch.setenv("GH_TOKEN", "токен")
    store = tmp_path / "runs.json"
    assert module.main(["--repo", "o/r", "--store", str(store)]) == module.EXIT_OK
    assert not store.exists(), "сухой заход не оставляет файла"
    assert module.main(["--repo", "o/r", "--store", str(store), "--apply"]) == module.EXIT_OK
    said = json.loads(store.read_text(encoding="utf-8"))
    assert said["days"][сегодня]["runs"]["ci"]["runs"] == 1
    assert said["window_days"] == module.Bounds.read(BOUNDS).window_days


def test_a_hand_written_date_would_leave_the_recount_window() -> None:
    """Довод починки замерен, а не объявлен: окно пересчёта КОРОЧЕ истории дерева.

    Проверка выше была зелёной три дня и покраснела на четвёртый. Здесь названо,
    почему это неизбежно: окно пересчёта — три дня, и любая дата, вписанная
    рукой, выходит из него через столько же. Если окно однажды расширят, довод
    ослабнет — и это станет видно здесь, а не в упавшем наборе.
    """
    границы = module.Bounds.read(BOUNDS)
    assert границы.recount_days <= 7, (
        f"окно пересчёта {границы.recount_days} дней — довод про рукописную дату надо перемерить"
    )


def test_a_walk_without_a_repo_is_the_second_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Чей ряд считать — не сказано: отказ входа с названным предметом (075, 158)."""
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert module.main(["--store", str(tmp_path / "runs.json")]) == module.EXIT_BROKEN
    assert "предмет не найден" in capsys.readouterr().err


REPORT_MARKS = module.REPORT_MARKS


# --- отчёт по красным копится, чтобы теорию можно было проверить (#606) -------


def job(name: str, *, step: str = "", conclusion: str = "failure") -> dict[str, Any]:
    """Ответ площадки об одном джобе — с шагами, как она их отдаёт."""
    steps = [{"name": "Set up job", "conclusion": "success"}]
    if step:
        steps.append({"name": step, "conclusion": conclusion})
    return {"id": 42, "name": name, "conclusion": conclusion, "steps": steps}


def test_the_failed_step_is_named_not_guessed() -> None:
    """Шаг падения читается у площадки: по имени ДЖОБА его не узнать.

    ЗАМЕР, РАДИ КОТОРОГО СБОР ЗАВЕДЁН (21.09.2026, #606). Владелец назвал
    предмет: «нужен отчёт по красным, и на основе него принимать решение —
    перезапускать ли этот джоб, его вместе с суммирующим или все сразу».

    Имя джоба на этот вопрос не отвечает: оно одно и то же и у дефекта, и у
    осечки. Отвечает ШАГ — служебный против своего.
    """
    assert module.failed_step(job("test", step="тесты")) == "тесты"
    assert module.failed_step(job("test")) == "", "шагов нет — это пусто, а не выдумка"


def test_a_report_mark_is_read_from_annotations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Признак осечки берётся из аннотаций, а не из логов.

    Логи окну недоступны — площадка отвечает 403 через прокси, — а аннотации
    приходят обычным чтением. Признак «ждём соседей» ИЗМЕРЕН: 16 красных
    `ci-complete` из 16 несут его, то есть он стопроцентный на нашей истории.
    """
    monkeypatch.setattr(
        module.ghrest,
        "request",
        lambda *a, **k: [{"message": "сводный гейт: красно\nждём соседей на голове abc…"}],
    )
    assert module.report_mark("o/r", 42, "токен") == REPORT_MARKS["ждём соседей"]


def test_an_unknown_failure_has_no_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    """Признака нет — пусто, а не догадка.

    Половина, без которой сбор превращается в приписывание: «Process completed
    with exit code 1» не говорит НИЧЕГО, и выдать его за осечку значило бы
    построить статистику на выдумке (005).
    """
    monkeypatch.setattr(
        module.ghrest,
        "request",
        lambda *a, **k: [{"message": "Process completed with exit code 1."}],
    )
    assert module.report_mark("o/r", 42, "токен") == ""


def test_a_refused_read_is_not_absence_of_a_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ чтения не превращается в «признака нет» молча (045).

    ПРОВЕРКА САМА БЫЛА ТРЕТЬИМ ЛИЦОМ ДЕФЕКТА. Имя её говорило «отказ — не
    отсутствие», докстрока ссылалась на 045, а сравнение стояло ровно то же,
    что у соседки про отсутствие: `== ""`. Зелёной она была потому, что код
    склеивал оба исхода, — и подтверждала не договор, а склейку. Нашёл внешний
    взгляд находкой `24fd8f7`.

    Цена склейки счётная: непрочитанные отчёты попадали бы в долю «осечек не
    найдено» и разбавляли бы её тем, чего никто не смотрел, — то есть портили
    бы ровно ту статистику, ради которой сбор и заведён (005, 049).
    """

    def falls(*a: Any, **k: Any) -> Any:
        raise module.ghrest.TransportError("площадка молчит")

    monkeypatch.setattr(module.ghrest, "request", falls)
    said = module.report_mark("o/r", 42, "токен")
    assert said == module.MARK_UNREAD, said
    assert said != "", "отказ снова неотличим от «признака нет»"


def test_our_install_steps_are_service_too(tmp_path: Path) -> None:
    """Наш шаг установки — служебный, и состав таких имён читается ИЗ ДЕРЕВА.

    ЗАМЕР 22.09.2026, РАДИ КОТОРОГО ЭТО ЗАВЕДЕНО. Шагов, ставящих зависимости,
    в дереве ПЯТНАДЦАТЬ, и список площадочных умолчаний не видел служебным ни
    одного: он знает только английские имена от GitHub, а наши названы
    по-русски. Отчёт при этом утверждал «130 из 130 упали на своём шаге» — и
    число было АРТЕФАКТОМ СПИСКА, а не фактом о дереве
    ([206](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/206-a-form-the-gate-cannot-see-is-a-bypass.md)).

    Живой случай: `test-next (3.15)` упал на «поставить проверки» — на
    `pip install`, до единого теста, на предрелизном интерпретаторе.
    """
    runs = tmp_path / "прогоны"
    runs.mkdir()
    (runs / "ci.yml").write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - name: поставить проверки\n"
        '        run: python -m pip install --quiet "pytest>=8,<10"\n'
        "      - name: тесты\n"
        "        run: pytest\n",
        encoding="utf-8",
    )
    наши = module.installing_steps(runs)
    assert наши == {"поставить проверки"}, наши
    assert module.whose_step("поставить проверки", наши) == module.WHOSE_SERVICE
    assert module.whose_step("тесты", наши) == module.WHOSE_OWN


def test_a_step_that_installs_and_does_is_not_service(tmp_path: Path) -> None:
    """Вторая половина: шаг, который ставит И делает, служебным не считается.

    Его падение может быть о чём угодно, и относить его к площадке значило бы
    ПРЯТАТЬ настоящий отказ — ошибка в ту сторону, которой здесь нельзя
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    В дереве такой ровно один — «сосчитать покрытие»: он ставит набор и тут же
    считает покрытие (195).

    БЕЗЫМЯННЫЙ ШАГ СЮДА НЕ ПОПАДАЕТ ТОЖЕ: площадка зовёт его текстом команды, и
    сопоставить по имени нечем.
    """
    runs = tmp_path / "прогоны"
    runs.mkdir()
    (runs / "ci.yml").write_text(
        "jobs:\n"
        "  cover:\n"
        "    steps:\n"
        "      - name: сосчитать покрытие\n"
        "        run: |\n"
        "          python -m pip install --quiet coverage\n"
        "          coverage run -m pytest\n"
        "      - run: python -m pip install --quiet нечто\n",
        encoding="utf-8",
    )
    наши = module.installing_steps(runs)
    assert наши == frozenset(), наши
    assert module.whose_step("сосчитать покрытие", наши) == module.WHOSE_OWN


def test_a_block_is_read_as_the_shell_would_run_it() -> None:
    """Блок `run:` разбирается на команды так, как их исполнит оболочка.

    Обе половины названы здесь: что командой СЧИТАЕТСЯ (строка, часть строки за
    связкой) и что не считается (пустая строка, комментарий). Без второй
    половины признак неотличим от «в блоке встретилось слово install».
    """
    assert module.commands("pip install ruff") == ["pip install ruff"]
    assert module.commands("pip install pytest && pytest") == ["pip install pytest", "pytest"]
    assert module.commands("pip install a || pip install b") == ["pip install a", "pip install b"]
    assert module.commands("  # только пояснение\n") == []
    assert module.commands("") == []

    assert module.only_installs("pip install ruff")
    assert module.only_installs("# почему такая граница\npip install ruff")
    assert not module.only_installs("pip install pytest && pytest")
    assert not module.only_installs("# только пояснение")
    assert not module.only_installs("")


def test_a_trailing_comment_is_not_a_command() -> None:
    """Хвостовой комментарий командой не считается, а кавычки уважаются.

    НАХОДКА ВНЕШНЕГО ВЗГЛЯДА НА #641 (`34cec89`). Прежняя редакция отбрасывала
    строку, НАЧИНАЮЩУЮСЯ с решётки, а комментарий в хвосте оставляла — и
    `pytest  # не забыть pip install` читался установкой: маркер находился в
    пояснении, а не в команде.

    ВТОРАЯ ПОЛОВИНА ВАЖНЕЕ ПЕРВОЙ. Резать по первой решётке нельзя: в дереве
    ЧЕТЫРЕ строки `run:` несут её внутри кавычек (`echo "…записан в #196"` и
    соседние), и наивная обрезка искалечила бы все четыре. Предикат « #» назвал
    их поимённо — поэтому имена и читаются, а не только счёт
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    assert module.bare_of("pytest  # не забыть pip install") == "pytest"
    assert module.bare_of("# только пояснение") == ""
    assert "#196" in module.bare_of('echo "ответ записан в #196"')
    assert "#$ASKED" in module.bare_of('echo "смотрим названное: #$ASKED"')
    # Незакрытая кавычка разбору не по зубам: строка отдаётся как есть, и шаг
    # посчитается работающим — ошибка уходит в дешёвую сторону (051).
    assert module.bare_of('echo "не закрыл') == 'echo "не закрыл'

    assert not module.only_installs("pytest  # не забыть pip install")
    assert module.only_installs("pip install ruff  # верхняя граница ниже")


def test_the_order_of_the_joiners_does_not_change_the_split() -> None:
    """Порядок альтернатив в разборе связок на результат НЕ влияет.

    НАХОДКА ВНЕШНЕГО ВЗГЛЯДА НА #641 (`73ea8c9`). Рядом с `JOINERS` стоял
    довод «порядок значим: `||` обязан проверяться раньше `|`». Довод звучал
    правдоподобно и был выдуман: пустые куски отсеиваются ниже, и оба порядка
    дают одно и то же. Проверяется прогоном, а не чтением
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    """
    обратный = re.compile(r"&&|\||;|\|\|")
    for said in ("pip install a || pip install b", "a && b", "a | b", "a; b"):
        прямой = [one.strip() for one in module.JOINERS.split(said) if one.strip()]
        иначе = [one.strip() for one in обратный.split(said) if one.strip()]
        assert прямой == иначе, said


def test_a_comment_inside_the_block_does_not_unmake_a_service_step(tmp_path: Path) -> None:
    """Комментарий внутри `run: |` командой не считается.

    НАХОДКА ВНЕШНЕГО ВЗГЛЯДА НА #635 (`64308c8`). Прежняя редакция требовала
    признака установки от КАЖДОЙ непустой строки — а проект объясняет границы
    версий пакетов именно строчным комментарием внутри блока (`step-lint.yml`,
    `labels-sync.yml`). Такая строка признака не несла и молча вышибала шаг из
    состава служебных, воспроизводя беду #634 на новом месте.

    Предмета в дереве на день починки НЕТ — ни один install-вызов не оформлен
    многострочным блоком с комментарием. Поэтому дерево здесь строится руками:
    находка о ФОРМЕ, а не о сегодняшнем совпадении стиля
    ([206](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/206-a-form-the-gate-cannot-see-is-a-bypass.md)).
    """
    runs = tmp_path / "прогоны"
    runs.mkdir()
    (runs / "ci.yml").write_text(
        "jobs:\n"
        "  lint:\n"
        "    steps:\n"
        "      - name: поставить проверки\n"
        "        run: |\n"
        "          # Верхняя граница нужна, чтобы мажор не приехал сам.\n"
        '          python -m pip install --quiet "ruff>=0.6,<1"\n',
        encoding="utf-8",
    )
    assert module.installing_steps(runs) == {"поставить проверки"}


def test_a_line_that_installs_and_then_works_is_not_service(tmp_path: Path) -> None:
    """Строка, которая ставит И работает, служебной не делает.

    НАХОДКА ВНЕШНЕГО ВЗГЛЯДА НА #635 (`794993a`). Поиск подстроки видел в
    `pip install X && pytest` установку и объявлял шаг служебным целиком —
    падение настоящей работы пряталось бы за площадкой. Граница «ставит И
    делает» была названа, но держалась только на блоке `run: |`: соединение
    команд в одну строку её обходило.
    """
    runs = tmp_path / "прогоны"
    runs.mkdir()
    (runs / "ci.yml").write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - name: поставить и прогнать\n"
        "        run: pip install pytest && pytest\n",
        encoding="utf-8",
    )
    assert module.installing_steps(runs) == frozenset()


def test_a_name_that_works_anywhere_is_service_nowhere(tmp_path: Path) -> None:
    """Имя, которое где-то делает работу, служебным не считается нигде.

    НАХОДКА ВНЕШНЕГО ВЗГЛЯДА НА #635 (`fb3f7c4`). Площадка отдаёт упавший шаг
    ОДНИМ именем, без файла и джоба. Пока состав собирался по первому же
    совпадению, одноимённый сосед, который ставит И делает, наследовал чужую
    отметку «площадка» — и его настоящее падение пряталось.

    Вычитание уводит ошибку в дешёвую сторону: служебное падение назовут своим,
    и его увидят
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    """
    runs = tmp_path / "прогоны"
    runs.mkdir()
    (runs / "ci.yml").write_text(
        "jobs:\n"
        "  lint:\n"
        "    steps:\n"
        "      - name: поставить проверки\n"
        "        run: pip install ruff\n"
        "  test:\n"
        "    steps:\n"
        "      - name: поставить проверки\n"
        "        run: |\n"
        "          pip install pytest\n"
        "          pytest\n"
        "      - name: поставить разбор\n"
        "        run: pip install pyyaml\n",
        encoding="utf-8",
    )
    наши = module.installing_steps(runs)
    assert наши == {"поставить разбор"}, наши
    assert module.whose_step("поставить проверки", наши) == module.WHOSE_OWN


def test_a_block_of_only_comments_is_not_service(tmp_path: Path) -> None:
    """Блок без команд вовсе служебным не считается.

    «Команд нет» и «все команды ставят» — разные состояния, и сливать их
    значило бы объявить служебным шаг, о котором не известно ничего
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    runs = tmp_path / "прогоны"
    runs.mkdir()
    (runs / "ci.yml").write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - name: пусто\n"
        "        run: |\n"
        "          # здесь только пояснение\n",
        encoding="utf-8",
    )
    assert module.installing_steps(runs) == frozenset()


def test_a_tree_without_runs_is_an_empty_set(tmp_path: Path) -> None:
    """Прогонов нет — пустой состав, а не отказ: у потребителя их может не быть."""
    assert module.installing_steps(tmp_path / "нет") == frozenset()


def test_whose_step_fell_is_counted_not_assumed() -> None:
    """Служебный шаг отличается от своего — и это СЧИТАЕТСЯ, а не подразумевается.

    `SERVICE_STEPS` был объявлен и не вызывался ниоткуда: различение, ради
    которого собирается весь отчёт, не происходило вовсе, а докстроки соседей
    его обещали. Список, который ничего не находит, доказывает только себя
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    Нашёл внешний взгляд находкой `f7b99be`.

    Три исхода, а не два: у «шагов площадка не отдала» своё значение, иначе оно
    слиплось бы со «своим» и завысило бы долю дефектов
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    assert module.whose_step("Set up job") == module.WHOSE_SERVICE
    assert module.whose_step("Post Run actions/checkout@v7") == module.WHOSE_SERVICE
    assert module.whose_step("тесты") == module.WHOSE_OWN
    assert module.whose_step("") == module.WHOSE_UNKNOWN


def test_the_series_counts_whose_steps_fell() -> None:
    """Счёт «свои против площадкиных» доходит до РЯДА, а не оседает в записи.

    Различение, посчитанное и не сведённое, отвечает ровно так же, как
    несчитанное: владелец спрашивает про ряд — «у всех джобов одна ошибка
    платформы?», — а не про один джоб.

    ЗАМЕР НА НАШЕЙ ИСТОРИИ (21.09.2026): 130 упавших джобов из 130 упали на
    СВОЁМ шаге, то есть счёт площадкиных сегодня НОЛЬ. Это запись наблюдения, а
    не пробел (046).
    """
    days = {
        "2026-09-21": {
            "runs": {
                "ci": {"red_whose": {module.WHOSE_OWN: 3}},
                "review": {"red_whose": {module.WHOSE_OWN: 1, module.WHOSE_SERVICE: 2}},
            }
        }
    }
    assert module.whose(days) == {module.WHOSE_OWN: 4, module.WHOSE_SERVICE: 2}
    empty: dict[str, Any] = {"2026-09-21": {"runs": {"ci": {}}}}
    assert module.whose(empty) == {}, "пустой день — пустой счёт, а не выдумка"


def test_the_report_names_whose_step_fell() -> None:
    """Счёт доходит до ОТЧЁТА, который читает человек, а не оседает в функции.

    ТРЕТЬЕ ЛИЦО ОДНОГО ДЕФЕКТА, и нашёл его внешний взгляд на #611. Сначала
    `SERVICE_STEPS` был объявлен и не вызывался; потом различение считалось и не
    сводилось по ряду; потом свелось — и не печаталось. Каждый раз починка
    двигала границу на шаг и останавливалась перед последним
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

    Отчёт и есть предмет: логи прогонов читаются не из всякого окна, а файл ряда
    читается по прямой ссылке. Число, не дошедшее до него, отвечает ровно так
    же, как несчитанное.
    """
    days = {
        "2026-09-21": {"runs": {"ci": {"runs": 4, "red": 2, "red_whose": {module.WHOSE_OWN: 2}}}}
    }
    said = module.report(days, module.Bounds.read(BOUNDS), "2026-09-21")
    assert "на СВОЁМ шаге — 2" in said, said
    assert "подтверждения НЕ имеет" in said, "нулевой счёт площадкиных не назван вслух (046)"


def test_the_report_says_unread_not_innocent() -> None:
    """Пустой счёт печатается как «не прочитано», а не как «площадка не виновата».

    Половина, без которой раздел врёт в самую дорогую сторону: «служебных падений
    ноль» при НЕразобранных падениях — вывод из незнания
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    days = {"2026-09-21": {"runs": {"ci": {"runs": 4, "red": 2, "red_whose": {}}}}}
    said = module.report(days, module.Bounds.read(BOUNDS), "2026-09-21")
    assert "не из чего" in said, said
    assert "подтверждения НЕ имеет" not in said, "незнание выдано за оправдание площадки"


def test_the_day_row_carries_whose_step_fell(monkeypatch: pytest.MonkeyPatch) -> None:
    """Различение доходит от ОТВЕТА ПЛОЩАДКИ до строки дня, а не только до записи.

    ПОЧЕМУ ЭТА ПРОВЕРКА ЗАВЕДЕНА ОТДЕЛЬНО ОТ СОСЕДКИ. Соседка строит ряд рукой
    и спрашивает только читателя — `whose`. Откат накопления её НЕ покрасил: у
    поддельной площадки красные джобы приходили без шагов, и счёт оставался
    пустым при любом коде. Откат, который не краснеет, — находка, а не
    облегчение
    ([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

    Поэтому здесь площадка отдаёт джоб С ШАГАМИ — тем входом, которого
    подделка соседки не строит.
    """

    def paginate(path: str, token: str, key: str | None = None) -> Any:
        return iter([run("ci", "2026-09-21", end="failure", number=7)])

    def request(method: str, path: str, token: str, *rest: Any, **kw: Any) -> Any:
        if path.endswith("/annotations"):
            return []
        return {
            "jobs": [
                {
                    "id": 1,
                    "name": "test",
                    "conclusion": "failure",
                    "steps": [{"name": "тесты", "conclusion": "failure"}],
                },
                {
                    "id": 2,
                    "name": "lint",
                    "conclusion": "failure",
                    "steps": [{"name": "Set up job", "conclusion": "failure"}],
                },
            ]
        }

    monkeypatch.setattr(module.ghrest, "paginate", paginate)
    monkeypatch.setattr(module.ghrest, "request", request)
    row = module.swept("o/r", "токен", "2026-09-21")["2026-09-21"]["ci"]
    assert row["red_whose"] == {module.WHOSE_OWN: 1, module.WHOSE_SERVICE: 1}, row["red_whose"]


def test_the_marks_are_named_with_their_reason() -> None:
    """У каждого признака названа причина, и список не пуст (075, 154).

    Пустой список означал бы сбор, который ничего не различает, — и снаружи он
    неотличим от работающего.
    """
    assert REPORT_MARKS, "признаков осечки не объявлено — собирать нечего"
    for mark, why in REPORT_MARKS.items():
        assert mark.strip() and why.strip(), f"«{mark}»: признак без причины"


def test_the_details_of_a_red_run_come_in_one_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """`red_details` отдаёт имя, шаг и признак ОДНИМ обходом ответа площадки.

    Три обхода того же стоили бы вызовов из общей квоты и разошлись бы между
    собой молча (058, 022). Проверяется и отбор: зелёные джобы в отчёт не
    попадают — иначе статистика красных считала бы зелёное.
    """
    asked: list[str] = []

    def answer(method: str, path: str, *rest: Any, **kw: Any) -> Any:
        asked.append(path)
        if "/jobs" in path:
            return {
                "jobs": [
                    job("test", step="тесты"),
                    job("lint", step="стиль", conclusion="success"),
                ]
            }
        return [{"message": "ждём соседей на голове abc…"}]

    monkeypatch.setattr(module.ghrest, "request", answer)
    said = module.red_details("o/r", 7, "токен")

    assert [one["name"] for one in said] == ["test"], "зелёный джоб попал в отчёт красных"
    assert said[0]["step"] == "тесты"
    assert said[0]["mark"] == REPORT_MARKS["ждём соседей"]
    assert sum(1 for one in asked if "/jobs" in one) == 1, "список джобов спрошен не один раз"
