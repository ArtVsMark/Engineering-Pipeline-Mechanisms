"""Проба передачи зовёт то же, что заход печатает потребителю.

Проверяется не «есть ли файл», а совпадение с тем, что ОТДАЁТСЯ: адрес и
прибивка берутся у `onboard`, и расхождение означает, что проверяется не тот
путь, которым пойдёт потребитель (090, 022).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tests.conftest import ROOT, load_script, needs_history

onboard = load_script("onboard.py")
family_uptake = load_script("family_uptake.py")
module = load_script("drift.py")

PROBE = ROOT / ".github" / "workflows" / "handover-probe.yml"
PREFIX = "probe-"

#: Шаги, которых проба НЕ зовёт, и причина у списка одна: они считают
#: относительно БАЗЫ изменения, а вне изменения её нет. Замер прогоном
#: 21.09.2026 (35569411331): все девять стартовали внешним путём, эти четыре
#: отказали третьим исходом ВНУТРИ себя. Список здесь, а не в памяти: иначе
#: сужение пробы читается как забывчивость
#: ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
NEEDS_A_CHANGE = ("journal", "pr-meta", "window-lifetime", "rulebook-fresh")


def probe() -> dict[Any, Any]:
    """Разобранная проба: предмет берётся из дерева, а не из памяти."""
    said: dict[Any, Any] = yaml.safe_load(PROBE.read_text(encoding="utf-8"))
    return said


def test_the_probe_calls_every_step_it_can() -> None:
    """Зовётся КАЖДЫЙ отдаваемый шаг, кроме названных неподъёмными вне изменения.

    Проба по одному шагу говорила бы только о нём: вызов по тегу площадка
    разрешает для каждого файла отдельно, и молчание о прочих — это молчание.
    Сосед у сужения назван списком выше, а не оставлен читателю (195).
    """
    called = {name.removeprefix(PREFIX) for name in probe()["jobs"]}
    want = set(onboard.steps(ROOT)) - set(NEEDS_A_CHANGE)
    assert called == want, "проба зовёт не тот состав, что отдаётся наружу"


def test_the_gap_of_the_probe_is_named_not_silent() -> None:
    """Пробел назван В САМОЙ пробе, а не только здесь.

    Читатель прогона должен видеть, чего проба НЕ проверяет, не открывая
    набора: умолчание о четырёх шагах снаружи неотличимо от их проверки (046).
    """
    said = PROBE.read_text(encoding="utf-8")
    for one in NEEDS_A_CHANGE:
        assert one in said, f"пробел про «{one}» в пробе не назван"
    # Регистр не судится: шапки механизмов пишут признак прописными, и
    # требовать строчных значило бы проверять стиль, а не наличие.
    assert "не проверяет" in said.lower()


def test_the_probe_goes_the_outward_way() -> None:
    """Путь ВНЕШНИЙ: адрес с владельцем и тегом, а не `./` внутри дерева.

    Внутренний вызов приезжает тем же ref, что и файл прогона, и о внешнем
    пути не говорит ничего — ради этой разницы проба и заведена (139).
    """
    for name, job in probe()["jobs"].items():
        said = str(job["uses"])
        assert not said.startswith("./"), f"{name}: проба пошла внутренним путём"
        assert "@" in said, f"{name}: вызов без версии"


@needs_history
def test_the_probe_says_what_the_kit_prints() -> None:
    """Адрес и прибивка — те же, что печатает заход подключения.

    Иначе проверяется не то, что отдаётся: заготовка потребителя и проба
    разошлись бы молча, и зелёная проба обещала бы работу чужому вызову,
    которого никто не проверял.
    """
    pin = onboard.pin_of(ROOT)
    for step in set(onboard.steps(ROOT)) - set(NEEDS_A_CHANGE):
        want = onboard.caller(step, family_uptake.OURS, pin).splitlines()
        said = str(probe()["jobs"][f"{PREFIX}{step}"]["uses"])
        assert any(said in line for line in want), f"{step}: проба зовёт не тот адрес"


def test_the_probe_job_names_do_not_collide_with_the_pipeline() -> None:
    """Имена джобов пробы СВОИ: иначе две разные проверки дают одно имя.

    Сводный гейт такое уже ловил — «на голове 2 живых записей с одним именем,
    вердикт неоднозначен», — и разбираться там пришлось руками.
    """
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    assert not set(probe()["jobs"]) & set(ci["jobs"]), "имена джобов пробы и конвейера совпали"


def test_the_probe_runs_on_the_release_and_by_hand() -> None:
    """Проба идёт по выпуску — единственному мигу, когда меняется отдаваемое, —
    и по кнопке: события теряются (104)."""
    # `on:` в YAML 1.1 разбирается как `True`: ловушка известная, и читать
    # ключ по одному имени значило бы молча получить `None` (045).
    said = probe().get(True) or probe().get("on") or {}
    assert "release" in said and "workflow_dispatch" in said, said


@needs_history
def test_a_probe_pinned_to_the_release_is_not_a_drift(tmp_path: Path) -> None:
    """Прибивка совпала с выпуском — находки нет.

    Без этой половины источник был бы неотличим от «всегда находит», а такой
    учат пропускать (051).
    """
    assert module.probe_behind_release(ROOT) == []


def test_a_probe_behind_the_release_is_a_drift(monkeypatch: object, tmp_path: Path) -> None:
    """Прибивка отстала от выпуска — находка с обоими числами.

    Так выглядит день после выпуска: свежий тег не проверен внешним путём
    никем, а проба отвечает на вопрос, который потребителю уже не задают.
    """
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / PROBE.relative_to(ROOT)).write_text(
        "jobs:\n  probe-lint:\n    uses: o/r/.github/workflows/step-lint.yml@v1.0.0\n",
        encoding="utf-8",
    )
    keep = module.version.release_tag
    module.version.release_tag = lambda *_a, **_k: "v9.9.9"
    try:
        found = module.probe_behind_release(tmp_path)
    finally:
        module.version.release_tag = keep
    assert len(found) == 1
    assert found[0].source == "probe-behind"
    assert "v1.0.0" in found[0].said and "v9.9.9" in found[0].said


def test_a_probe_without_an_outward_call_is_the_third_outcome(tmp_path: Path) -> None:
    """В пробе нет ни одного вызова по тегу — отказ, а не «сошлось».

    Пустая проба зеленела бы и обещала проверенный внешний путь там, где его
    не проверяли вовсе (075).
    """
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / PROBE.relative_to(ROOT)).write_text(
        "jobs:\n  probe-lint:\n    uses: ./.github/workflows/step-lint.yml\n", encoding="utf-8"
    )
    keep = module.version.release_tag
    module.version.release_tag = lambda *_a, **_k: "v9.9.9"
    try:
        import pytest

        with pytest.raises(module.NotRun, match="внешним путём"):
            module.probe_behind_release(tmp_path)
    finally:
        module.version.release_tag = keep


def test_a_missing_probe_is_the_third_outcome(tmp_path: Path) -> None:
    """Пробы нет вовсе — отказ с причиной, а не «прибивка свежая» (075)."""
    import pytest

    keep = module.version.release_tag
    module.version.release_tag = lambda *_a, **_k: "v9.9.9"
    try:
        with pytest.raises(module.NotRun, match="проба передачи не заведена"):
            module.probe_behind_release(tmp_path)
    finally:
        module.version.release_tag = keep
