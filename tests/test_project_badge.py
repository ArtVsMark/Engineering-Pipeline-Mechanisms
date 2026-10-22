"""Значок проекта в две строки: счёт правил, одна граница, серое с причиной.

Переехало из каталога вместе со значком (#1563): случаи и ожидания — набора
каталога на `353bf10`. Отличие одно и названо: выгрузка читается по адресу
транспортом, и подделка — функция чтения, а не файл в дереве действия.

Источник подделки (правило 170): выгрузка — форма `export/rules.json` каталога
(`rules`: записи с `id` и `status`); зоны — форма `python.zones.json`, которую
пишет `python_badge.main`; разбор семьи — форма `family-check.json` от
`family_check.analyse`.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

pb = load_script("project_badge.py")
badge = load_script("python_badge.py")


def answer(**rules: dict[str, Any]) -> dict[str, Any]:
    """Ответ каталогу с данными записями правил."""
    return {"schema": "1.9", "rules": rules}


def export(*active: str, superseded: tuple[str, ...] = ()) -> dict[str, Any]:
    """Выгрузка каталога: действующие и заменённые правила."""
    rules = [{"id": one, "status": "active"} for one in active]
    rules += [{"id": one, "status": "superseded", "superseded_by": "999"} for one in superseded]
    return {"schema": "1.9", "rules": rules}


def test_rules_are_counted_in_one_zone() -> None:
    """Знаменатель — действующие правила, правила и механизмы — одна зона (каталог, 15.10)."""
    zones, why = pb.rules_zones(
        answer(
            **{
                "001": {"status": "active", "mechanism": "gate", "origin_kind": "own"},
                "002": {"status": "active", "mechanism": "pipeline", "origin_kind": "called"},
                "003": {"status": "active", "mechanism": "document"},
                "004": {"status": "not-applicable", "mechanism": "none"},
            }
        ),
        {"001", "002", "003", "004"},
    )
    assert why == ""
    assert len(zones) == 1
    assert [text for text, _, _ in zones[0]] == ["rules", "machine 2/4 · 50%", "own 1", "taken 1"]


@pytest.mark.parametrize("bad", [None, [], {"rules": []}, {"schema": "1.9"}])
def test_no_answer_is_grey_with_a_reason(bad: object) -> None:
    """Ответа нет или он не той формы — серое с причиной."""
    zones, why = pb.rules_zones(bad, {"001"})
    assert why
    assert any(color == pb.GREY for zone in zones for _, color, _ in zone)


def test_a_superseded_rule_is_not_in_the_share() -> None:
    """Ответ о заменённом в знаменатель и в «machine» не идёт (каталог, 17.10)."""
    zones, why = pb.rules_zones(
        answer(
            **{
                "001": {"status": "active", "mechanism": "gate", "origin_kind": "own"},
                "002": {"status": "active", "mechanism": "gate", "origin_kind": "own"},
                "003": {"status": "active", "mechanism": "none"},
            }
        ),
        {"002", "003"},
    )
    assert why == ""
    assert [text for text, _, _ in zones[0]][1:3] == ["machine 1/2 · 50%", "own 1"]


def test_an_unread_export_is_grey_with_a_reason() -> None:
    """Действующих не отличить — серое с причиной, а не счёт по всем (075)."""
    zones, why = pb.rules_zones(answer(**{"001": {"status": "active"}}), None)
    assert "выгрузка" in why
    assert any(color == pb.GREY for zone in zones for _, color, _ in zone)


def test_machine_is_the_shared_set_of_kinds() -> None:
    """«Машиной» — виды `kinds.MACHINE`, тот же набор, что считает факты (214)."""
    rules = {
        f"00{n}": {"status": "active", "mechanism": kind}
        for n, kind in enumerate(sorted(pb.kinds.MACHINE))
    }
    zones, _ = pb.rules_zones(answer(**rules), set(rules))
    count = len(rules)
    assert zones[0][1][0] == f"machine {count}/{count} · 100%"


def test_no_denominator_no_percent() -> None:
    """Без знаменателя процента нет, а цвет серый."""
    assert pb.share(0, 0) == "0/0 · —"
    assert pb.share_color(0, 0) == pb.GREY
    assert pb.share_color(1, 4) == "#cf222e"
    assert pb.share_color(1, 2) == "#bf8700"
    assert pb.share_color(3, 4) == badge.COVERAGE_COLORS["green"]


def zones_of(*texts: tuple[str, ...]) -> list[list[tuple[str, str, str]]]:
    """Зоны с данными надписями."""
    return [[(text, "#000", "") for text in zone] for zone in texts]


def end(zones: list[list[tuple[str, str, str]]], stretch: dict[int, int], index: int) -> int:
    """Где кончается зона `index` с растяжками."""
    width: list[int] = pb.widths(zones)
    return (
        sum(width[: index + 1])
        + sum(stretch.get(one, 0) for one in range(index + 1))
        + index * int(badge.GAP)
    )


TOP = zones_of(
    ("CI", "Python", "3.14"),
    ("linux", "windows", "mac"),
    ("coverage", "76%"),
    ("version", "1.13.19"),
)


@pytest.mark.parametrize(
    "rules", [("rules", "m"), ("rules", "machine 170/217 · 78%", "own 150", "taken 20 и ещё")]
)
def test_rules_ends_under_the_os_zone(rules: tuple[str, ...]) -> None:
    """Одна граница (каталог, 16.10): конец rules — под концом ОС."""
    bottom = zones_of(rules, ("family", "gives ✓"), ("EIP ✓",))
    stretch_top, stretch_bottom = pb.align(TOP, bottom)
    assert end(TOP, stretch_top, pb.OS_ZONE) == end(bottom, stretch_bottom, 0)
    # Растягивается только одна из двух зон границы.
    assert set(stretch_top) <= {pb.OS_ZONE}
    assert set(stretch_bottom) <= {0}
    assert not (stretch_top and stretch_bottom)


def test_a_stretch_is_shared_by_the_parts() -> None:
    """Разница делится на все части зоны, а не уходит в последнюю (каталог, 16.10)."""
    zones = [[("a", "#000", ""), ("b", "#000", ""), ("c", "#000", "")]]
    svg = badge.picture(zones, 0, {0: 10})
    drawn = [
        int(width)
        for width in re.findall(
            r'<rect x="[\d.]+" width="(\d+)" height="20" fill="[^"]+" clip-path', svg
        )
    ]
    own = [badge.part_width(text) for text in "abc"]
    assert sum(drawn) - sum(own) == 10
    gaps = [a - b for a, b in zip(drawn, own, strict=True)]
    assert max(gaps) - min(gaps) <= 1


def test_without_zones_nothing_to_align() -> None:
    """Нет зоны ОС — выравнивать нечего."""
    assert pb.align(zones_of(("CI",)), zones_of(("rules",), ("x",))) == ({}, {})


def tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Дерево проекта с ответом, зонами состояния и разбором семьи."""
    (tmp_path / ".rules").mkdir()
    (tmp_path / ".rules" / "bindings.json").write_text(
        json.dumps(answer(**{"001": {"status": "active", "mechanism": "gate"}})), encoding="utf-8"
    )
    zones = tmp_path / "python.zones.json"
    zones.write_text(
        json.dumps([[["CI", "#444d56", ""], ["ok", "#2da44e", "CI пройден"]]]), encoding="utf-8"
    )
    family = tmp_path / "family-check.json"
    family.write_text(
        json.dumps(
            {
                "segments": {"gives": {"state": "ok", "why": "", "links": []}},
                "publishers": [{"code": "EIP", "state": "ok", "why": ""}],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path, zones, family


def test_two_rows_without_transforms(tmp_path: Path) -> None:
    """Две строки одним `<svg>`: вторая — сдвигом, а не трансформацией."""
    svg, greys = pb.build(*tree(tmp_path), fetch=lambda _url: export("001"))
    assert greys == []
    assert 'height="44"' in svg.split(">", 1)[0]
    assert "transform" not in svg
    assert svg.count("<svg") == 1
    assert re.search(r'<clipPath id="z\w+"><rect y="24"', svg)
    assert "machine 1/1 · 100%" in svg
    assert "EIP" in svg


def test_the_zones_lie_next_to_the_picture() -> None:
    """python_badge кладёт зоны рядом с картинкой: python.svg → python.zones.json."""
    assert Path("python.svg").with_name("python" + badge.ZONES).name == "python.zones.json"


def test_missing_parts_are_grey_not_a_broken_picture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Нет ни зон, ни разбора, ни выгрузки — три серые части, исход 1."""

    def silent(url: str, timeout: int = 30) -> dict[str, Any]:
        raise pb.ghrest.TransportError(f"нет ответа ({url})")

    monkeypatch.setattr(pb.ghrest, "raw_json", silent)
    out = tmp_path / "out" / "project.svg"
    argv = [
        "--root",
        str(tmp_path),
        "--python-zones",
        str(tmp_path / "нет.json"),
        "--family-json",
        str(tmp_path / "нет2.json"),
        "--out",
        str(out),
    ]
    assert pb.main(argv) == pb.EXIT_GREY
    svg = out.read_text(encoding="utf-8")
    # Видимая надпись части — текст без тени: три серые части, по одной на источник.
    assert len(re.findall(r'y="(?:14|38)">n/a<', svg)) == 3
    assert "нет.json" in capsys.readouterr().err


@pytest.mark.parametrize("said", ["{}", "[]", '[["a"]]', '[[["a", "b"]]]'])
def test_zones_of_another_form_are_grey(tmp_path: Path, said: str) -> None:
    """Зоны не той формы — серое с причиной."""
    path = tmp_path / "python.zones.json"
    path.write_text(said, encoding="utf-8")
    _, why = pb.state_zones(path)
    assert why


def test_an_unwritten_file_is_the_third_outcome(tmp_path: Path) -> None:
    """Файл значка не записан — исход 2."""
    root, zones, family = tree(tmp_path)
    taken = tmp_path / "файл"
    taken.write_text("", encoding="utf-8")
    argv = [
        "--root",
        str(root),
        "--python-zones",
        str(zones),
        "--family-json",
        str(family),
        "--out",
        str(taken / "project.svg"),
    ]
    assert pb.main(argv) == pb.EXIT_BROKEN


def test_the_picture_without_shift_and_stretch_is_unchanged() -> None:
    """Входы по умолчанию не меняют python.svg и family.svg ни на байт."""
    zones = [[("a", "#000", "w")]]
    assert badge.picture(zones) == badge.picture(zones, 0, None) == badge.picture(zones, 0, {})


@pytest.mark.parametrize("said", [{"schema": "1.8"}, {"rules": None}, {"rules": "список"}])
def test_an_export_without_rules_is_grey_not_zero(tmp_path: Path, said: dict[str, Any]) -> None:
    """Прочитанная выгрузка без списка «rules» — серое с причиной, а не «0/0» (каталог, #917)."""
    root, _, _ = tree(tmp_path)
    svg, why = pb.build(root, tmp_path / "нет.json", tmp_path / "нет.json", fetch=lambda _u: said)
    assert any("выгрузка" in one for one in why)
    assert "0/0" not in svg


def test_active_of_reads_the_shared_reader() -> None:
    """Действующие — `catalogue.active_rules`: заменённые не в счёт; отказ канала — None."""
    assert pb.active_of(lambda _u: export("001", "002", superseded=("003",))) == {"001", "002"}

    def broken(_url: str) -> dict[str, Any]:
        raise pb.ghrest.TransportError("нет ответа")

    assert pb.active_of(broken) is None
    assert pb.active_of(lambda _u: {"schema": "1.9"}) is None


def test_family_zones_join_label_and_segments(tmp_path: Path) -> None:
    """Подпись и сегменты семьи — одна зона; разбор не прочитан — серое с причиной."""
    _, _, family = tree(tmp_path)
    zones, why = pb.family_zones(family)
    assert why == ""
    assert zones[0][0][0] == "family"
    assert pb.family_zones(tmp_path / "нет.json")[1]
    assert pb.grey("x", "почему")[0][1] == ("n/a", pb.GREY, "почему")


def test_parts_are_drawn_by_one_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--parts`: значок Python и семейный рисуются тем же вызовом, их входы доходят до них."""
    asked: dict[str, list[str]] = {}

    def python_main(argv: list[str]) -> int:
        asked["python"] = argv
        out = Path(argv[argv.index("--out") + 1])
        out.with_name(out.stem + badge.ZONES).write_text(
            json.dumps([[["CI", "#444d56", ""], ["ok", "#2da44e", ""]]]), encoding="utf-8"
        )
        return 0

    def family_main(argv: list[str]) -> int:
        asked["family"] = argv
        out = Path(argv[argv.index("--out") + 1])
        out.with_name(pb.family_check.VERDICT.name).write_text(
            json.dumps(
                {
                    "segments": {"gives": {"state": "ok", "why": "", "links": []}},
                    "publishers": [{"code": "EIP", "state": "ok", "why": ""}],
                }
            ),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(pb.python_badge, "main", python_main)
    monkeypatch.setattr(pb.family_check, "main", family_main)
    monkeypatch.setattr(pb.ghrest, "raw_json", lambda *_a, **_k: export("001"))
    root, _, _ = tree(tmp_path)
    out = tmp_path / "badges" / "project.svg"
    argv = ["--root", str(root), "--parts", "--out", str(out), "--repo", "o/p", "--ci", "ci.yml"]
    assert pb.main([*argv, "--pypi", "pkg"]) == pb.EXIT_OK
    assert asked["python"][-4:] == ["--ci", "ci.yml", "--pypi", "pkg"]
    assert asked["family"][-2:] == ["--repo", "o/p"]
    assert out.is_file()


def test_a_broken_part_is_the_third_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Часть не собрана — склейка всё равно рисуется, но исход 2: прежний значок не трогать."""
    monkeypatch.setattr(pb.python_badge, "main", lambda _argv: pb.EXIT_BROKEN)
    monkeypatch.setattr(pb.family_check, "main", lambda _argv: pb.EXIT_OK)
    monkeypatch.setattr(pb.ghrest, "raw_json", lambda *_a, **_k: export("001"))
    root, _, _ = tree(tmp_path)
    out = tmp_path / "b" / "project.svg"
    assert pb.draw_parts(root, out.parent, [], []) == (pb.EXIT_BROKEN, pb.EXIT_OK)
    assert pb.main(["--root", str(root), "--parts", "--out", str(out)]) == pb.EXIT_BROKEN


def test_without_parts_both_inputs_are_required(tmp_path: Path) -> None:
    """Без `--parts` склейке нужны оба готовых входа, а лишний довод — ошибка, а не молчание."""
    with pytest.raises(SystemExit):
        pb.main(["--out", str(tmp_path / "p.svg")])
    with pytest.raises(SystemExit):
        pb.main(
            [
                "--out",
                str(tmp_path / "p.svg"),
                "--python-zones",
                "a",
                "--family-json",
                "b",
                "--ci",
                "x",
            ]
        )
