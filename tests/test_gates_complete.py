"""Вердикт сводного гейта проверяется тем, что он обязан отвергнуть."""

from __future__ import annotations

from typing import Any

from tests.conftest import load_script

module = load_script("ci_complete.py")
REQUIRED = ["lint", "test"]


def run(
    name: str,
    status: str = "completed",
    conclusion: str | None = "success",
    run_id: str = "1",
) -> dict[str, Any]:
    """Собирает одну запись проверки в том виде, в каком её отдаёт площадка."""
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "details_url": f"https://github.com/o/r/actions/runs/{run_id}/job/9",
    }


def test_all_green_is_green() -> None:
    """Все объявленные зелёные — вердикт зелёный."""
    problems, waiting = module.verdict([run("lint"), run("test")], REQUIRED, "ci-complete")
    assert (problems, waiting) == ([], False)


def test_missing_record_is_rejected() -> None:
    """Записи нет на голове: прогон не стартовал, а не «зелено» (075)."""
    problems, _ = module.verdict([run("lint")], REQUIRED, "ci-complete")
    assert len(problems) == 1 and "записи нет" in problems[0]


def test_no_records_on_the_head_is_rejected() -> None:
    """Записей на голове нет ни одной: прогон не стартовал, а не «все прошли».

    Отдельно от недостачи одного имени: пустой вход — это отсутствие предмета
    проверки, и гейт, не нашедший предмета, обязан падать (075). Проверяется
    тем, что названы ОБА объявленных имени, а не «есть хотя бы одна находка».
    """
    problems, waiting = module.verdict([], REQUIRED, "ci-complete")
    assert not waiting
    assert {problem.split(":")[0] for problem in problems} == set(REQUIRED)
    assert all("записи нет" in problem for problem in problems)


def test_both_failures_are_named() -> None:
    """Вердикт выносится после последнего случая, а не на первой находке (159).

    Ранний выход снаружи неотличим от рабочего набора: первый отказ назван,
    остальные превращаются в печать. Проверяется тем, что отказов ровно два и
    названы оба, а не «есть хотя бы один».
    """
    problems, _ = module.verdict(
        [run("lint", conclusion="failure"), run("test", conclusion="failure")],
        REQUIRED,
        "ci-complete",
    )
    assert len(problems) == 2
    assert {problem.split(":")[0] for problem in problems} == {"lint", "test"}


def test_skipped_is_rejected() -> None:
    """Пропущенный джоб — отказ: иначе выключение шага обходит гейт."""
    problems, _ = module.verdict(
        [run("lint"), run("test", conclusion="skipped")], REQUIRED, "ci-complete"
    )
    assert any("пропущен" in problem for problem in problems)


def test_all_cancelled_is_rejected() -> None:
    """Если все записи имени отменены, живого вердикта нет — это отказ."""
    problems, _ = module.verdict(
        [run("lint"), run("test", conclusion="cancelled")], REQUIRED, "ci-complete"
    )
    assert any("все записи отменены" in problem for problem in problems)


def test_cancelled_beside_a_live_record_is_ignored() -> None:
    """Отмена от группы отмены не делает здоровую голову красной.

    Новый толчок или новая метка гасят прогон на той же голове, и его записи
    остаются лежать рядом с живыми. Первый прогон на площадке покраснел именно
    на этом: `filter=latest` записи отменённого прогона не отсекает.
    """
    runs = [
        run("lint", conclusion="cancelled"),
        run("lint"),
        run("test", conclusion="cancelled"),
        run("test"),
    ]
    assert module.verdict(runs, REQUIRED, "ci-complete") == ([], False)


def test_failure_beside_a_cancelled_record_still_rejects() -> None:
    """Отбрасывание отмен не прячет настоящий отказ."""
    runs = [run("lint"), run("test", conclusion="cancelled"), run("test", conclusion="failure")]
    problems, _ = module.verdict(runs, REQUIRED, "ci-complete")
    assert any("failure" in problem for problem in problems)


def test_failure_is_rejected() -> None:
    """Красный сосед делает сводный красным, а не пропущенным."""
    problems, _ = module.verdict(
        [run("lint"), run("test", conclusion="failure")], REQUIRED, "ci-complete"
    )
    assert any("failure" in problem for problem in problems)


def test_pending_makes_it_wait() -> None:
    """Незавершённый сосед означает ожидание, а не вердикт."""
    _, waiting = module.verdict(
        [run("lint"), run("test", status="in_progress", conclusion=None)],
        REQUIRED,
        "ci-complete",
    )
    assert waiting is True


def test_two_live_records_with_one_name_are_flagged() -> None:
    """Одно обязательное имя от двух живых прогонов — вердикт неоднозначен."""
    problems, _ = module.verdict([run("lint"), run("test"), run("test")], REQUIRED, "ci-complete")
    assert any("живых записей с одним именем" in problem for problem in problems)


def test_a_record_with_a_conclusion_is_not_awaited() -> None:
    """Запись с исходом завершена, каким бы ни было её состояние.

    Погашенный группой отмены прогон оставляет на голове запись со `status:
    in_progress` и уже проставленным `conclusion`. Ждать её нечего, а ждали бы
    её вечно: новых событий у изменения больше нет, и сдвинуть её нечем.
    Замер 09.09.2026: очередь встала на изменении #73 при девяти зелёных
    записях из-за одной такой записи-зомби.
    """
    problems, waiting = module.verdict(
        [run("lint"), run("test", status="in_progress")], REQUIRED, "ci-complete"
    )
    assert (problems, waiting) == ([], False)


def test_a_record_without_a_conclusion_is_still_awaited() -> None:
    """Настоящая идущая запись по-прежнему останавливает вердикт (097).

    Иначе лечение хуже болезни: гейт перестал бы ждать вообще и выносил бы
    вердикт по недосчитанной голове.
    """
    problems, waiting = module.verdict(
        [run("lint"), run("test", status="in_progress", conclusion=None)],
        REQUIRED,
        "ci-complete",
    )
    assert waiting and not problems


def test_itself_is_not_awaited() -> None:
    """Сводный не ждёт собственной записи — иначе он не дождётся никогда."""
    problems, waiting = module.verdict(
        [run("lint"), run("test")], [*REQUIRED, "ci-complete"], "ci-complete"
    )
    assert (problems, waiting) == ([], False)


def test_records_of_a_foreign_run_do_not_confuse_the_verdict() -> None:
    """Второй прогон того же файла на голове — штатное событие, а не беда.

    Снятие черновика или новое событие запускают ci заново на том же коммите, и
    каждое имя оказывается представлено дважды при обоих здоровых прогонах.
    Замер 09.09: это уронило сводный гейт при восьми зелёных соседях.
    """
    runs = [
        run("lint", run_id="old"),
        run("test", run_id="old"),
        run("lint", run_id="mine"),
        run("test", run_id="mine"),
    ]
    assert module.verdict(runs, REQUIRED, "ci-complete", "mine") == ([], False)


def test_a_foreign_record_still_counts_when_own_run_has_none() -> None:
    """Имя, которого свой прогон не выдаёт, берётся у чужого — иначе пропуск."""
    runs = [run("lint", run_id="mine"), run("test", conclusion="failure", run_id="old")]
    problems, _ = module.verdict(runs, REQUIRED, "ci-complete", "mine")
    assert any("failure" in problem for problem in problems)


def test_two_records_of_the_same_run_are_still_ambiguous() -> None:
    """Внутри одного прогона два одинаковых имени — по-прежнему неоднозначность."""
    runs = [run("lint", run_id="mine"), run("test", run_id="mine"), run("test", run_id="mine")]
    problems, _ = module.verdict(runs, REQUIRED, "ci-complete", "mine")
    assert any("живых записей с одним именем" in problem for problem in problems)


# --- наполнение опроса приходит из данных ------------------------------------


def test_two_sources_of_subject_are_refused() -> None:
    """Наполнение объявлено дважды — отказ, а не «возьмём тот, что подробнее».

    Два списка одного и того же расходятся молча (022), и молчание здесь стоит
    дороже всего: разойдясь, они дадут зелёный гейт на неполном опросе.
    """
    try:
        module.sources(".pipeline.yml", "lint,test")
    except module.NotRun as exc:
        assert "дважды" in str(exc)
    else:
        raise AssertionError("два источника наполнения приняты молча")


def test_policy_gives_both_classes(tmp_path: Any) -> None:
    """Из данных приходят обязательные и совещательные — разными списками."""
    answer = tmp_path / ".pipeline.yml"
    answer.write_text(
        "schema: 1\nchecks:\n  lint: required\n  review:\n    class: advisory\n"
        "    why: слияния не держит\n  e2e:\n    class: off\n    why: нет окружения\n",
        encoding="utf-8",
    )
    required, advisory = module.sources(str(answer), "")
    assert required == ["lint"]
    assert advisory == ["review"]


def test_advisory_missing_record_is_not_a_problem() -> None:
    """У совещательной отсутствие записи законно: она могла не идти вовсе."""
    problems, _ = module.verdict([], ["review"], "ci-complete", strict_missing=False)
    assert problems == []


def test_advisory_red_is_still_reported() -> None:
    """Но красное у совещательной не молчит: иначе это «выключена» повежливее."""
    failed = run("review", conclusion="failure")
    problems, _ = module.verdict([failed], ["review"], "ci-complete", strict_missing=False)
    assert len(problems) == 1 and "review" in problems[0]


def test_required_missing_record_is_still_a_refusal() -> None:
    """У обязательной послабления нет: нет записи — нет вердикта (075)."""
    problems, _ = module.verdict([], ["lint"], "ci-complete")
    assert len(problems) == 1 and "записи нет" in problems[0]
