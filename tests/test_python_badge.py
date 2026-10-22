"""Значок «CI │ Python 3.14 │ 3.15 …»: цвет каждой части — исход своего прогона.

Переехало из каталога вместе со значком (#1563): случаи и ожидания — набора
каталога на `353bf10`. Иначе построены только деревья: у каталога прогон в
подделке — обрывок текста (`with:` без работы), его читал построчный разбор.
Здесь прогон разбирает общий YAML, и деревья — настоящие прогоны.

Источник подделки (правило 170): прогоны — форма ответа площадки
`actions/workflows/<файл>/runs` (поля `conclusion`, `created_at`, `event`,
`id`), работы — `actions/runs/<id>/jobs` (`name`, `conclusion`, `labels`).
"""

import urllib.error
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("python_badge.py")


@pytest.fixture(autouse=True)
def no_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Выпуск и PyPI в наборе не спрашиваются у сети: выпусков нет.

    Манифест сборок setup-python: вышли все серии, которые встречаются в
    деревьях, — невышедшую задаёт тест явно.
    """
    monkeypatch.setattr(module, "platform_release", lambda: None)
    monkeypatch.setattr(module, "pypi_version", lambda package: None)
    monkeypatch.setattr(module, "platform_builds", lambda: {(3, minor) for minor in range(10, 20)})


def run(conclusion: str, when: str, id_: int = 1) -> dict[str, Any]:
    """Прогон в форме ответа площадки."""
    return {"conclusion": conclusion, "created_at": when, "id": id_}


def job(conclusion: str, label: str, name: str = "") -> dict[str, Any]:
    """Работа прогона в форме ответа площадки."""
    return {"conclusion": conclusion, "labels": [label], "name": name}


def setup_step(version: str, preview: bool = False) -> str:
    """Шаг установки Python с версией буквой."""
    mark = "          allow-prereleases: true\n" if preview else ""
    return (
        "      - uses: actions/setup-python@v6\n"
        f'        with:\n          python-version: "{version}"\n{mark}'
    )


def tree(root: Path, ci: str = "3.14", upcoming: str | None = "3.15") -> Path:
    """Дерево с основным CI и предварительным прогоном."""
    folder = root / ".github" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ci.yml").write_text(
        "on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n" + setup_step(ci),
        encoding="utf-8",
    )
    if upcoming:
        (folder / "python-next.yml").write_text(
            "on: push\njobs:\n  next:\n    runs-on: ubuntu-latest\n    steps:\n"
            + setup_step(upcoming, preview=True),
            encoding="utf-8",
        )
    return root


def draw(root: Path, out: Path, *extra: str, **kwargs: Any) -> int:
    """Собрать значок дерева в `out` с подделанной площадкой."""
    return int(module.main(["--root", str(root), "--out", str(out), *extra], **kwargs))


# ── состояние: последний прогон С ВЕРДИКТОМ ────────────────────────────────


def test_the_last_passed_is_green() -> None:
    """Последний прогон с вердиктом прошёл — зелёный."""
    runs = [run("failure", "2026-10-01T10:00Z"), run("success", "2026-10-01T11:00Z")]
    assert module.state(runs) == "pass"


def test_the_last_failed_is_red() -> None:
    """Последний прогон с вердиктом упал — красный."""
    runs = [run("success", "2026-10-01T10:00Z"), run("failure", "2026-10-01T11:00Z")]
    assert module.state(runs) == "fail"


def test_a_cancel_is_no_verdict_and_the_previous_decides() -> None:
    """Отменённый прогон ничего не проверил (039): цвет даёт прошлый вердикт."""
    runs = [run("failure", "2026-10-01T10:00Z"), run("cancelled", "2026-10-01T11:00Z")]
    assert module.state(runs) == "fail"


def test_no_runs_is_grey() -> None:
    """Прогонов с вердиктом нет — серый «не проводилась»."""
    assert module.state([]) == "none"
    assert module.state([run("skipped", "2026-10-01T11:00Z")]) == "none"


def test_a_fork_change_does_not_paint_the_badge() -> None:
    """`branch=main` у площадки — это head_branch, равный main у форка (каталог, обзор #649)."""
    foreign = {**run("failure", "2026-10-01T11:00Z"), "event": "pull_request"}
    own = {**run("success", "2026-10-01T10:00Z"), "event": "push"}
    assert module.state([own, foreign]) == "pass"
    assert module.state([foreign]) == "none"


# ── версии берутся у прогонов, а не пишутся рукой (005) ────────────────────


def test_the_versions_come_from_the_runs(tmp_path: Path) -> None:
    """Подписи версий — у прогонов: основная и предварительная."""
    assert module.versions(tree(tmp_path)) == [("3.14", "ci.yml"), ("3.15", "python-next.yml")]


def test_a_moved_floor_moves_the_label(tmp_path: Path) -> None:
    """Сдвинется версия в прогоне — сдвинется подпись."""
    assert module.versions(tree(tmp_path, "3.15", "3.16"))[0] == ("3.15", "ci.yml")


def test_an_unreadable_matrix_falls_back_to_the_floor(tmp_path: Path) -> None:
    """Версия не читается из прогона — подпись планкой `requires-python`."""
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    (folder / "tests.yml").write_text(
        "on: push\njobs:\n  t:\n    runs-on: x\n    steps:\n"
        "      - uses: actions/setup-python@v6\n        with:\n"
        "          python-version: ${{ matrix.python }}\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.14"\n', encoding="utf-8"
    )
    assert module.versions(tmp_path, "tests.yml") == [("3.14", "tests.yml")]


def _two_versions(root: Path) -> Path:
    tree(root, "3.14", "3.16")
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n"
        + setup_step("3.14")
        + "  b:\n    name: тесты на 3.15\n    runs-on: x\n    steps:\n"
        + setup_step("3.15"),
        encoding="utf-8",
    )
    return root


def test_several_main_versions_ascending(tmp_path: Path) -> None:
    """Основных версий несколько (решение владельца 14.10) — по возрастанию, затем следующие."""
    assert module.versions(_two_versions(tmp_path)) == [
        ("3.14", "ci.yml"),
        ("3.15", "ci.yml"),
        ("3.16", "python-next.yml"),
    ]


def test_a_version_is_painted_by_its_own_job() -> None:
    """Работа с версией в имени отвечает за неё, без версии — за планку."""
    jobs = [
        {"name": "catalogue", "conclusion": "success"},
        {"name": "тесты на 3.15", "conclusion": "failure"},
    ]
    assert module.by_version(["3.14", "3.15"], jobs) == {"3.14": "pass", "3.15": "fail"}


def test_a_literal_floor_and_a_matrix_are_both_on_the_badge(tmp_path: Path) -> None:
    """Приёмка каталога #926: планка буквой рядом с матрицей — обе версии, каждая своей работой."""
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    (folder / "ci.yml").write_text(
        "on: push\njobs:\n  lint:\n    runs-on: ubuntu-latest\n    steps:\n"
        + setup_step("3.14")
        + "  test-matrix:\n    runs-on: ubuntu-latest\n    strategy:\n      matrix:\n"
        '        python: ["3.14", "3.15"]\n    steps:\n'
        "      - uses: actions/setup-python@v6\n        with:\n"
        "          python-version: ${{ matrix.python }}\n",
        encoding="utf-8",
    )
    labels = [label for label, _ in module.versions(tmp_path)]
    assert labels == ["3.14", "3.15"]
    jobs = [
        {"name": "lint", "conclusion": "success"},
        {"name": "test-matrix (3.14)", "conclusion": "success"},
        {"name": "test-matrix (3.15)", "conclusion": "failure"},
    ]
    assert module.by_version(labels, jobs) == {"3.14": "pass", "3.15": "fail"}


# ── картинка ───────────────────────────────────────────────────────────────


def _colors(svg: str) -> list[str]:
    return [piece.split('fill="')[1].split('"')[0] for piece in svg.split('<rect x="')[1:]]


def test_three_parts_and_python_in_the_main_ci_color() -> None:
    """Порядок цветов частей: CI (подпись), Python, 3.14, 3.15; слово — в подсказке."""
    svg = module.picture(module.checks_zones([("3.14", "pass"), ("3.15", "fail")], "pass"))
    assert ">Python<" in svg and ">3.14<" in svg and ">3.15<" in svg
    green, red = module.STATES["pass"][0], module.STATES["fail"][0]
    assert _colors(svg)[:4] == [module.LABEL, green, green, red]
    assert "CI не пройден" in svg


def test_the_prefix_is_part_of_the_first_zone() -> None:
    """«CI» — часть первой зоны, прямо перед «Python», а не своя зона (каталог, обзор #720)."""
    zones = module.checks_zones([("3.14", "pass"), ("linux", "pass")], "fail")
    assert [text for text, _, _ in zones[0][:2]] == ["CI", "Python"]
    assert all("CI" not in [text for text, _, _ in zone] for zone in zones[1:])
    assert module.picture(zones).count("<clipPath") == len(zones)


def test_a_shift_lowers_the_strip_and_zero_keeps_the_picture() -> None:
    """Сдвиг опускает полосу, а без сдвига картинка та же байт в байт."""
    zones = module.checks_zones([("3.14", "pass")], "pass")
    assert module.picture(zones) == module.picture(zones, shift=0)
    assert ' y="20"' in module.picture(zones, shift=20)


def test_a_stretch_widens_the_zone_by_exactly_its_points() -> None:
    """Растяжка добавляет зоне ровно названное число точек — поровну, остаток последним."""
    zones = module.checks_zones([("3.14", "pass")], "pass")
    plain = module.picture(zones)
    wide = module.picture(zones, stretch={0: 7})

    def width(svg: str) -> int:
        return int(svg.split('width="')[1].split('"')[0])

    assert width(wide) - width(plain) == 7


def test_the_four_states_differ_in_color() -> None:
    """Цвет различает «не проводилась», «не проверяется», «сборки нет» (владелец 16.10)."""
    colors = [module.STATES[said][0] for said in ("none", "absent", "unreleased", "pass", "fail")]
    assert len(set(colors)) == len(colors)
    assert module.STATES["unreleased"][0] != module.LABEL


def test_the_width_of_a_part_is_the_font_table_plus_fields() -> None:
    """Ширина части — по таблице шрифта и два поля; числа каталога сняты с файла шрифта."""
    for text, px in (("coverage / all (os)", 112), ("windows", 57), ("linux", 36), ("3.14", 35)):
        assert module.part_width(text) == px


# ── main: собранный значок и третий исход ─────────────────────────────────


def test_python_is_red_when_ci_failed(tmp_path: Path) -> None:
    """Исход основного CI несёт часть «Python», первая часть — префикс «CI»."""
    out = tmp_path / "python.svg"
    outcomes = {"ci.yml": [run("failure", "2026-10-01T11:00Z")], "python-next.yml": []}
    code = draw(
        tree(tmp_path),
        out,
        runs=outcomes.__getitem__,
        jobs=lambda _: [job("failure", "ubuntu-latest")],
    )
    assert code == module.EXIT_OK
    svg = out.read_text(encoding="utf-8")
    assert module.STATES["fail"][0] == _colors(svg)[1]
    assert "проверка не проводилась" in svg
    assert out.with_name("python.zones.json").is_file(), "зоны рядом с картинкой не легли"


def test_a_silent_platform_is_the_third_outcome_not_grey(tmp_path: Path) -> None:
    """Площадка молчит — значок не собран, а не серый (039)."""
    out = tmp_path / "python.svg"

    def silent(_: str) -> list[dict[str, Any]]:
        raise module.NoAnswer("502")

    assert draw(tree(tmp_path), out, runs=silent) == module.EXIT_BROKEN
    assert not out.exists()


def test_no_run_with_a_version_is_the_third_outcome(tmp_path: Path) -> None:
    """Подписывать нечего — значок не собран (075)."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    assert draw(tmp_path, tmp_path / "p.svg", runs=lambda _: []) == module.EXIT_BROKEN


def test_a_full_page_without_a_verdict_is_the_third_outcome(tmp_path: Path) -> None:
    """За краем страницы вердикт может быть: серый о неспрошенном был бы ложью (039)."""
    out = tmp_path / "python.svg"
    blank = [run("cancelled", f"2026-10-01T{i:02d}:00Z", i) for i in range(module.LIMIT)]
    outcomes = {"ci.yml": [run("success", "2026-10-01T10:00Z")], "python-next.yml": blank}
    assert (
        draw(tree(tmp_path), out, runs=outcomes.__getitem__, jobs=lambda _: [])
        == module.EXIT_BROKEN
    )
    assert not out.exists()


def test_no_version_of_the_main_ci_is_the_third_outcome(tmp_path: Path) -> None:
    """У основного CI нет версии — его не спрашивают, и серый «Python» был бы ложью (039)."""
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    (folder / "pr-check.yml").write_text(
        "on: push\njobs:\n  a:\n    runs-on: x\n", encoding="utf-8"
    )
    (folder / "python-next.yml").write_text(
        "on: push\njobs:\n  n:\n    runs-on: x\n    steps:\n" + setup_step("3.15", preview=True),
        encoding="utf-8",
    )
    out = tmp_path / "python.svg"
    code = draw(tmp_path, out, "--ci", "pr-check.yml", runs=lambda _: [], jobs=lambda _: [])
    assert code == module.EXIT_BROKEN
    assert not out.exists()


def test_an_unparsable_flow_is_the_third_outcome(tmp_path: Path) -> None:
    """Прогон не разбирается — значок не собран с причиной, а не трассой."""
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    (folder / "ci.yml").write_text("on: [push\n", encoding="utf-8")
    assert draw(tmp_path, tmp_path / "p.svg", runs=lambda _: []) == module.EXIT_BROKEN


def test_the_systems_come_from_the_deciding_run(tmp_path: Path) -> None:
    """ОС спрашиваются у решающего прогона: отменённый ничего не проверил."""
    out = tmp_path / "python.svg"
    asked: list[int] = []

    def jobs(run_id: int) -> list[dict[str, Any]]:
        asked.append(run_id)
        return [job("success", "ubuntu-latest")]

    outcomes = {
        "ci.yml": [
            run("success", "2026-10-01T10:00Z", 7),
            run("cancelled", "2026-10-01T11:00Z", 8),
        ],
        "python-next.yml": [run("success", "2026-10-01T10:00Z", 9)],
    }
    assert draw(tree(tmp_path), out, runs=outcomes.__getitem__, jobs=jobs) == module.EXIT_OK
    assert asked == [7]
    svg = out.read_text(encoding="utf-8")
    assert ">linux<" in svg and ">windows<" in svg and ">mac<" in svg


def test_an_unreleased_preview_is_dark_grey_with_its_word(tmp_path: Path) -> None:
    """Невышедшая предварительная — «сборки для CI ещё нет», а не «не проводилась»."""
    out = tmp_path / "p.svg"
    jobs = [
        {"name": "a", "conclusion": "success", "labels": ["ubuntu-latest"]},
        {"name": "тесты на 3.15", "conclusion": "success", "labels": ["ubuntu-latest"]},
    ]
    code = draw(
        _two_versions(tmp_path),
        out,
        runs=lambda _: [run("success", "2026-10-14T10:00Z")],
        jobs=lambda _: jobs,
        release=lambda: None,
        builds=lambda: {(3, 14), (3, 15)},
    )
    assert code == module.EXIT_OK
    svg = out.read_text(encoding="utf-8")
    assert "3.16: сборки для CI ещё нет" in svg and "3.15: CI пройден" in svg


# ── части по ОС ────────────────────────────────────────────────────────────


def test_unchecked_systems_are_grey_not_gone() -> None:
    """Мультиплатформенность решает проект, а значок показывает её честно."""
    assert module.by_system([job("success", "ubuntu-latest")]) == [
        ("linux", "pass"),
        ("windows", "none"),
        ("mac", "none"),
    ]


def test_a_failed_system_is_named() -> None:
    """Из трёх ОС красная та, на которой упало."""
    jobs = [
        job("success", "ubuntu-latest"),
        job("failure", "windows-latest"),
        job("success", "macos-14"),
        job("success", "windows-latest"),
    ]
    assert module.by_system(jobs) == [("linux", "pass"), ("windows", "fail"), ("mac", "pass")]


def test_a_skipped_job_does_not_make_a_system_grey() -> None:
    """Порядок работ не решает цвет — fail > pass > none (каталог, обзор #649)."""
    assert module.by_system([job("skipped", "ubuntu-latest"), job("success", "ubuntu-latest")])[
        0
    ] == (
        "linux",
        "pass",
    )
    ran = [
        job("success", "ubuntu-latest"),
        job("failure", "ubuntu-latest"),
        job("skipped", "ubuntu-latest"),
    ]
    assert module.by_system(ran)[0] == ("linux", "fail")


# ── лесенка семьи ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("own", "expected"),
    [
        ([("3.14", "pass")], [("3.14", "pass"), ("3.15", "absent"), ("3.16", "absent")]),
        (
            [("3.14", "pass"), ("3.16", "unreleased")],
            [("3.14", "pass"), ("3.15", "absent"), ("3.16", "unreleased")],
        ),
        (
            [("3.14", "pass"), ("3.15", "fail"), ("3.16", "none")],
            [("3.14", "pass"), ("3.15", "fail"), ("3.16", "none")],
        ),
        (
            [("3.13", "pass")],
            [("3.13", "pass"), ("3.14", "absent"), ("3.15", "absent"), ("3.16", "absent")],
        ),
    ],
)
def test_missing_steps_join_in_ascending_order(
    own: list[tuple[str, str]], expected: list[tuple[str, str]]
) -> None:
    """Недостающие ступени лесенки встают по возрастанию, жёлтыми."""
    assert module.on_ladder(own, ["3.14", "3.15", "3.16"]) == expected


def test_an_unreleased_step_is_not_a_lag() -> None:
    """Недостающая ступень без сборки — `unreleased`, а не жёлтое `absent`."""
    assert module.on_ladder([("3.14", "pass")], ["3.14", "3.15", "3.16"], {(3, 14), (3, 15)}) == [
        ("3.14", "pass"),
        ("3.15", "absent"),
        ("3.16", "unreleased"),
    ]


def test_the_family_ladder_is_the_mechanisms_own_tree() -> None:
    """Лесенка — версии самого дерева механизмов, второй её записи нет (владелец 16.10)."""
    floor = load_script("check_env.py").python_floor(module.ROOT)
    assert module.ladder() == [label for label, _ in module.versions(module.ROOT)]
    assert module.ladder()[0] == f"{floor[0]}.{floor[1]}"


# ── зоны выпуска: покрытие, release / PyPI, версия ─────────────────────────


def test_a_release_matching_pypi_is_green_and_short() -> None:
    part = module.release_zone("v1.5.0", "1.5.0", True)[1]
    assert part[0] == "1.5" and part[1] == module.STATES["pass"][0]


def test_a_release_off_pypi_is_red_with_both_numbers() -> None:
    part = module.release_zone("v2.8.0", "2.7.0", True)[1]
    assert part[0] == "2.8 / 2.7" and part[1] == module.STATES["fail"][0]


def test_undeclared_pypi_is_grey_with_the_release_number() -> None:
    part = module.release_zone("v1.5.0", None, False)[1]
    assert part[0] == "1.5" and part[1] == module.STATES["none"][0]


def test_declared_but_missing_pypi_package_is_red() -> None:
    part = module.release_zone("v1.5.0", None, True)[1]
    assert part[0] == "1.5 / —" and part[1] == module.STATES["fail"][0]


def test_the_comparison_is_by_the_two_shown_numbers() -> None:
    """Третье число — счётчик версии: красного над `2.8 / 2.8` не бывает (каталог, обзор #653)."""
    part = module.release_zone("v2.8.0", "2.8.0", True)[1]
    assert part[0] == "2.8" and part[1] == module.STATES["pass"][0]
    assert module.release_zone("v2.8.0", "2.8.3", True)[1][1] == module.STATES["pass"][0]


def test_coverage_by_its_thresholds() -> None:
    assert module.coverage_zone("72%")[1][:2] == ("72%", module.COVERAGE_COLORS["yellow"])
    assert module.coverage_zone("95%")[1][1] == module.COVERAGE_COLORS["brightgreen"]
    assert module.coverage_zone(None)[1][1] == module.STATES["none"][0]


def test_every_coverage_threshold_has_a_color() -> None:
    """Имя порога без цвета уронило бы сборку KeyError (каталог, обзор #653)."""
    assert {name for _, name in module.COVERAGE_THRESHOLDS} <= set(module.COVERAGE_COLORS)


def test_a_second_coverage_over_all_systems_sits_behind_a_slash() -> None:
    """Второе число покрытия видно, только когда оно есть и другое."""
    label, part = module.coverage_zone("72%", "85%")
    assert label[0] == "coverage / all (os)"
    assert part[0] == "72% / 85%" and part[1] == module.COVERAGE_COLORS["yellow"]
    label, part = module.coverage_zone("72%", None)
    assert (label[0], part[0]) == ("coverage", "72%")
    assert module.coverage_zone("72%", "72%")[1][0] == "72%"


def test_the_zone_order_puts_the_version_last(tmp_path: Path) -> None:
    """Решение владельца: проверки, ОС, покрытие, выпуск, версия — последней."""
    out = tmp_path / "python.svg"
    (tmp_path / "v.json").write_text('{"message": "1.5.3"}', encoding="utf-8")
    (tmp_path / "c.json").write_text('{"message": "72%"}', encoding="utf-8")
    outcomes = {
        "ci.yml": [run("success", "2026-10-01T10:00Z")],
        "python-next.yml": [run("success", "2026-10-01T10:00Z")],
    }
    code = draw(
        tree(tmp_path),
        out,
        "--coverage-json",
        str(tmp_path / "c.json"),
        "--version-json",
        str(tmp_path / "v.json"),
        runs=outcomes.__getitem__,
        jobs=lambda _: [job("success", "ubuntu-latest")],
        release=lambda: "v1.5.0",
    )
    assert code == module.EXIT_OK
    svg = out.read_text(encoding="utf-8")
    order = [
        svg.index(f">{text}<")
        for text in ("Python", "linux", "coverage", "release / PyPI", "version")
    ]
    assert order == sorted(order)


def test_a_silent_pypi_is_the_third_outcome(tmp_path: Path) -> None:
    def silent(_: str) -> str | None:
        raise module.NoAnswer("PyPI: timeout")

    outcomes = {"ci.yml": [run("success", "2026-10-01T10:00Z")], "python-next.yml": []}
    code = draw(
        tree(tmp_path),
        tmp_path / "p.svg",
        "--pypi",
        "stepik-python-grader",
        runs=outcomes.__getitem__,
        jobs=lambda _: [],
        release=lambda: "v2.8.0",
        pypi=silent,
    )
    assert code == module.EXIT_BROKEN


def test_a_named_but_missing_badge_file_is_the_third_outcome(tmp_path: Path) -> None:
    """Упавший шаг покрытия не рисуется серым «не измерено» (каталог, обзор #653)."""
    outcomes = {"ci.yml": [run("success", "2026-10-01T10:00Z")], "python-next.yml": []}
    out = tmp_path / "p.svg"
    root = tree(tmp_path)
    assert (
        draw(
            root,
            out,
            "--coverage-json",
            str(tmp_path / "нет.json"),
            runs=outcomes.__getitem__,
            jobs=lambda _: [],
        )
        == module.EXIT_BROKEN
    )
    (tmp_path / "битый.json").write_text("{", encoding="utf-8")
    assert (
        draw(
            root,
            out,
            "--version-json",
            str(tmp_path / "битый.json"),
            runs=outcomes.__getitem__,
            jobs=lambda _: [],
        )
        == module.EXIT_BROKEN
    )
    assert not out.exists()


def test_a_badge_file_without_a_number_is_the_third_outcome(tmp_path: Path) -> None:
    """Файл есть, а message пуст или не число — непрочитанный ответ (039)."""
    outcomes = {"ci.yml": [run("success", "2026-10-01T10:00Z")], "python-next.yml": []}
    out = tmp_path / "p.svg"
    root = tree(tmp_path)
    for name, body, key in (
        ("c.json", '{"message": "n/a"}', "--coverage-json"),
        ("v.json", '{"message": ""}', "--version-json"),
    ):
        (tmp_path / name).write_text(body, encoding="utf-8")
        assert (
            draw(root, out, key, str(tmp_path / name), runs=outcomes.__getitem__, jobs=lambda _: [])
            == 2
        )
    assert not out.exists()


def test_the_prefix_is_not_configurable(tmp_path: Path) -> None:
    """Решение владельца 08.10: «CI» стоит всегда, входа нет."""
    with pytest.raises(SystemExit):
        draw(tree(tmp_path), tmp_path / "p.svg", "--prefix", "", runs=lambda _: [])


# ── зона наборов: работы основного CI, сверенные с файлом ─────────────────

CI_WITH_JOBS = """name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v6
        with:
          python-version: "3.14"
  e2e:  # сквозные
    runs-on: ubuntu-latest
  'sandbox-linux':
    name: Sandbox (linux)  # песочница
    runs-on: ubuntu-latest
"""


def _with_suites(root: Path, given: str, jobs: list[dict[str, Any]]) -> tuple[int, str]:
    tree(root)
    (root / ".github" / "workflows" / "ci.yml").write_text(CI_WITH_JOBS, encoding="utf-8")
    out = root / "python.svg"
    outcomes = {
        "ci.yml": [run("success", "2026-10-01T11:00Z")],
        "python-next.yml": [run("success", "2026-10-01T11:00Z")],
    }
    code = draw(root, out, "--suites", given, runs=outcomes.__getitem__, jobs=lambda _: jobs)
    return code, out.read_text(encoding="utf-8") if out.exists() else ""


def named(name: str, conclusion: str) -> dict[str, Any]:
    return {"name": name, "conclusion": conclusion, "labels": ["ubuntu-latest"]}


def test_ci_jobs_key_and_name_without_comments_or_quotes() -> None:
    """Ключ и имя работы — разбором YAML: комментарий и кавычки не входят (каталог, обзор #725)."""
    assert module.ci_jobs(CI_WITH_JOBS) == {
        "test": "test",
        "e2e": "e2e",
        "sandbox-linux": "Sandbox (linux)",
    }


def test_a_suite_is_red_when_its_job_failed(tmp_path: Path) -> None:
    code, svg = _with_suites(
        tmp_path,
        "e2e, sandbox-linux:sandbox",
        [
            named("test (ubuntu-latest, 3.14)", "success"),
            named("e2e", "failure"),
            named("Sandbox (linux)", "success"),
        ],
    )
    assert code == module.EXIT_OK
    assert "e2e: CI не пройден" in svg and "sandbox: CI пройден" in svg


def test_suites_sit_after_the_systems_before_coverage(tmp_path: Path) -> None:
    code, svg = _with_suites(tmp_path, "e2e", [named("e2e", "success")])
    assert code == module.EXIT_OK
    assert svg.index(">linux<") < svg.index(">e2e<") < svg.index(">coverage<")


def test_a_matrix_job_matches_its_name_with_values(tmp_path: Path) -> None:
    code, svg = _with_suites(
        tmp_path,
        "test:unit",
        [
            named("test (ubuntu-latest, 3.14)", "success"),
            named("test (windows-latest, 3.14)", "failure"),
        ],
    )
    assert code == module.EXIT_OK and "unit: CI не пройден" in svg


def test_a_job_that_did_not_run_leaves_the_suite_grey(tmp_path: Path) -> None:
    code, svg = _with_suites(tmp_path, "e2e", [named("e2e", "skipped")])
    assert code == module.EXIT_OK and "e2e: проверка не проводилась" in svg


def test_a_job_missing_from_ci_stops_the_badge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Переименованная работа не сереет молча (005, 039)."""
    code, svg = _with_suites(tmp_path, "e2e-old", [named("e2e", "success")])
    assert code == module.EXIT_BROKEN and svg == ""
    assert "e2e-old" in capsys.readouterr().err


def test_more_than_four_suites_stop_the_badge(tmp_path: Path) -> None:
    code, _ = _with_suites(tmp_path, "test,e2e,sandbox-linux,test:a,e2e:b", [])
    assert code == module.EXIT_BROKEN


def test_a_name_by_expression_has_nothing_to_match() -> None:
    jobs = module.ci_jobs("on: push\njobs:\n  t:\n    name: ${{ matrix.os }}\n    runs-on: x\n")
    assert "выражением" in (module.check_suites([("t", "t")], jobs) or "")


def test_no_suites_no_zone(tmp_path: Path) -> None:
    assert module.suites_zone([]) == []
    code, svg = _with_suites(tmp_path, "", [named("e2e", "failure")])
    assert code == module.EXIT_OK and ">e2e<" not in svg


def test_a_separate_job_with_brackets_is_not_a_neighbour_matrix() -> None:
    jobs = {"e2e": "e2e", "smoke": "e2e (smoke)"}
    ran = [named("e2e", "success"), named("e2e (smoke)", "failure")]
    assert module.by_suite([("e2e", "e2e")], jobs, ran) == [("e2e", "pass")]
    assert module.by_suite([("smoke", "smoke")], jobs, ran) == [("smoke", "fail")]


# ── обращения к площадке: выпуск, PyPI, сборки ────────────────────────────


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (["facts-v2.0.0", "v1.13.0", "v1.12.0"], "v1.13.0"),
        (["v1.9.0", "v1.10.0"], "v1.10.0"),
        (["facts-v2.0.0"], None),
        ([], None),
    ],
)
def test_the_release_is_only_a_vxyz_tag(tags: list[str], expected: str | None) -> None:
    """Зона выпуска берёт старший тег `vX.Y.Z`, а не «последний» площадки (каталог 15.10)."""
    assert module.newest_release(tags) == expected


def test_a_404_from_pypi_means_no_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Пакета нет» — по коду ответа, а не подстроке «404» в адресе (каталог, обзор #653)."""
    reload = load_script("python_badge.py")
    monkeypatch.undo()  # автофикстура подменила саму функцию — здесь проверяется настоящая

    def missing(url: str, timeout: int = 30) -> str:
        cause = urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]
        raise reload.ghrest.TransportError(f"снимок не прочитан ({url}): {cause!r}") from cause

    def refused(url: str, timeout: int = 30) -> str:
        cause = urllib.error.URLError("[Errno 111] host:4040")
        raise reload.ghrest.TransportError(f"снимок не прочитан ({url}): {cause!r}") from cause

    monkeypatch.setattr(reload.ghrest, "raw_text", missing)
    assert reload.pypi_version("nobody-here") is None
    monkeypatch.setattr(reload.ghrest, "raw_text", refused)
    with pytest.raises(reload.NoAnswer):
        reload.pypi_version("x")
    monkeypatch.setattr(
        reload.ghrest, "raw_text", lambda *_a, **_k: '{"info": {"version": "2.8.0"}}'
    )
    assert reload.pypi_version("x") == "2.8.0"


def test_the_builds_manifest_is_a_list_of_series(monkeypatch: pytest.MonkeyPatch) -> None:
    """Манифест сборок — список; серии `X.Y` из версий, иное — третий исход."""
    reload = load_script("python_badge.py")
    monkeypatch.undo()  # автофикстура подменила саму функцию — здесь проверяется настоящая
    manifest = '[{"version": "3.14.0"}, {"version": "3.15.0a1"}, {"version": "x"}]'
    monkeypatch.setattr(reload.ghrest, "raw_text", lambda *_a, **_k: manifest)
    assert reload.platform_builds() == {(3, 14), (3, 15)}
    monkeypatch.setattr(reload.ghrest, "raw_text", lambda *_a, **_k: '{"version": "3.14"}')
    with pytest.raises(reload.NoAnswer, match="не список"):
        reload.platform_builds()


def test_the_platform_is_asked_about_its_own_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    """Прогоны и работы спрашиваются у `GITHUB_REPOSITORY` общим транспортом; без него — отказ."""
    reload = load_script("python_badge.py")
    asked: list[str] = []
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(reload.ghrest, "token_from_env", lambda: "т")

    def request(method: str, path: str, token: str) -> dict[str, Any]:
        asked.append(path)
        return {"workflow_runs": [run("success", "2026-10-01T10:00Z")]}

    monkeypatch.setattr(reload.ghrest, "request", request)
    monkeypatch.setattr(
        reload.ghrest, "paginate", lambda path, token, key=None: iter([{"path": path}])
    )
    assert reload.platform_runs("ci.yml")[0]["conclusion"] == "success"
    assert asked[0].startswith("repos/o/r/actions/workflows/ci.yml/runs?branch=main")
    assert reload.platform_jobs(7) == [{"path": "repos/o/r/actions/runs/7/jobs"}]
    monkeypatch.delenv("GITHUB_REPOSITORY")
    with pytest.raises(reload.NoAnswer, match="GITHUB_REPOSITORY"):
        reload.platform_runs("ci.yml")


def test_the_deciding_run_is_the_latest_own_verdict() -> None:
    """Решает последний прогон своей ветки С ВЕРДИКТОМ: отменённый и чужое событие — мимо."""
    runs = [
        run("success", "2026-10-01", 1),
        {**run("failure", "2026-10-03", 2), "event": "pull_request"},
        run("cancelled", "2026-10-04", 3),
        run("failure", "2026-10-02", 4),
    ]
    assert module.deciding(runs) == run("failure", "2026-10-02", 4)
    assert module.deciding([run("cancelled", "2026-10-04")]) is None
    assert module.deciding([]) is None


@pytest.mark.parametrize(
    ("percent", "expected"),
    [(100, "brightgreen"), (90, "brightgreen"), (89.9, "green"), (50, "yellow"), (0, "red")],
)
def test_the_coverage_color_is_the_threshold_it_reaches(percent: float, expected: str) -> None:
    """Цвет покрытия — первый порог, до которого процент дотянул, границы включительно."""
    assert module.coverage_color(percent) == expected


def test_suites_are_parsed_from_the_input() -> None:
    """`работа[:подпись],…`: подпись по умолчанию — имя работы, пустые куски — мимо."""
    assert module.suites("test, lint:ruff,,") == [("test", "test"), ("lint", "ruff")]
    assert module.suites("") == []


@pytest.mark.parametrize(
    ("said", "expected"), [("v1.5.0", "1.5"), ("2.10.3", "2.10"), ("vnext", "next")]
)
def test_short_keeps_the_two_leading_numbers(said: str, expected: str) -> None:
    """На значке — старшие два числа версии; не версию отдаёт как есть, без `v`."""
    assert module.short(said) == expected


def test_the_version_zone_is_blue_or_grey() -> None:
    """Версия — синим счётчиком; не собрана — серым, а не пустой частью."""
    assert module.version_zone("1.5")[1] == ("1.5", module.BLUE, "версия 1.5")
    assert module.version_zone(None)[1][1] == module.STATES["none"][0]


def test_from_badge_tells_unset_from_unread(tmp_path: Path) -> None:
    """Вход не задан — None; задан, но нет файла, он битый или без message — третий исход."""
    assert module.from_badge(None) is None
    good = tmp_path / "coverage.json"
    good.write_text('{"message": "87%"}', encoding="utf-8")
    assert module.from_badge(good) == "87%"
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text('{"message": " "}', encoding="utf-8")
    for path in (tmp_path / "absent.json", broken, empty):
        with pytest.raises(module.NoAnswer):
            module.from_badge(path)


def test_the_platform_release_skips_drafts_and_previews(monkeypatch: pytest.MonkeyPatch) -> None:
    """Старший выпуск — из всех страниц, без черновиков и предварительных; сбой — третий исход."""
    reload = load_script("python_badge.py")
    monkeypatch.undo()  # автофикстура подменила саму функцию — здесь проверяется настоящая
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    pages = [
        {"tag_name": "v1.9.0"},
        {"tag_name": "v1.10.0"},
        {"tag_name": "v2.0.0", "draft": True},
        {"tag_name": "v1.11.0", "prerelease": True},
        {"tag_name": "facts-v2.0.0"},
    ]
    monkeypatch.setattr(reload.ghrest, "paginate", lambda *_a, **_k: iter(pages))
    assert reload.platform_release() == "v1.10.0"

    def broken(*_a: Any, **_k: Any) -> Any:
        raise reload.ghrest.TransportError("нет ответа")

    monkeypatch.setattr(reload.ghrest, "paginate", broken)
    with pytest.raises(reload.NoAnswer):
        reload.platform_release()
