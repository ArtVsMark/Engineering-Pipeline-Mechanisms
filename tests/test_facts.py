"""Факты о проекте и их публикация проверяются отказом, а не осмотром.

Предмет двойной: числа обязаны приходить из источников (иначе значок врёт
уверенно), а производное обязано оставаться вне общей ветки (иначе оно там
протухает молча). Проверяется и то, и другое.
"""

import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from tests.conftest import FAKE_VERSION, ROOT, RunScript, badges_shown, load_script

facts = load_script("build_facts.py")

WORKFLOW = ROOT / ".github" / "workflows" / "badges.yml"
CHECKS = 'schema: 4\ncontract: ">=9.9,<9.10"\nchecks:\n  lint: required\n'


def bindings(**rules: dict[str, Any]) -> str:
    """Ответ каталогу в том виде, в каком его читает механизм."""
    return json.dumps({"schema": "1.0", "rules": rules}, ensure_ascii=False)


def tree(root: Path, answer: str) -> Path:
    """Собирает дерево-источник: версия, ответ каталогу, ответ по проверкам, прогон CI.

    Прогон CI — без матрицы версий: договор требует `ci.workflow` всегда, а
    версии Python у синтетического дерева законно уходят причиной в `none`.
    """
    (root / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    (root / facts.CI_FLOW).parent.mkdir(parents=True, exist_ok=True)
    (root / facts.CI_FLOW).write_text("jobs: {}\n", encoding="utf-8")
    (root / ".rules").mkdir(exist_ok=True)
    (root / ".rules" / "bindings.json").write_text(answer, encoding="utf-8")
    (root / ".pipeline.yml").write_text(CHECKS, encoding="utf-8")
    return root


def test_numbers_come_from_the_sources(tmp_path: Path) -> None:
    """Каждое число собрано из источника, а не вписано в механизм."""
    tree(
        tmp_path,
        bindings(
            **{
                "001": {"status": "active", "mechanism": "gate", "where": "тут"},
                "002": {"status": "active", "mechanism": "document", "where": "там"},
                "003": {"status": "unreviewed"},
                "004": {"status": "rejected", "why": "не наш предмет"},
            }
        ),
    )
    collected = facts.collect(tmp_path, "голова")
    assert collected["contract"] == FAKE_VERSION
    assert collected["rules"]["total"] == 4
    assert collected["rules"]["answered"] == 3
    assert collected["rules"]["by_mechanism"] == {"document": 1, "gate": 1}
    assert collected["checks_per_pr"]["by_class"]["required"] == 1
    assert collected["commit"] == "голова"
    # Договор фактов 1.3 (#1046): номер — договора, а не наш.
    assert collected["schema"] == "1.3"
    # В синтетическом дереве нет матрицы CI — значит причина, а не пропуск.
    assert collected["none"]["python"] == facts.NO_PYTHON
    assert collected["generated_at"].endswith("+00:00")


def test_unknown_status_is_refused(tmp_path: Path) -> None:
    """Статус вне схемы — дефект ответа, а не новая тонкость (068)."""
    tree(tmp_path, bindings(**{"001": {"status": "почти"}}))
    with pytest.raises(facts.NotRun, match="статус"):
        facts.collect(tmp_path, "")


def test_active_without_a_mechanism_is_refused(tmp_path: Path) -> None:
    """«Действует» без названного механизма — обещание, а не ответ (002)."""
    tree(tmp_path, bindings(**{"001": {"status": "active"}}))
    with pytest.raises(facts.NotRun, match="чем — не сказано"):
        facts.collect(tmp_path, "")


def test_empty_answer_is_an_input_error(tmp_path: Path) -> None:
    """Пустой ответ каталогу — ошибка входа, а не «правил нет» (075)."""
    tree(tmp_path, bindings())
    with pytest.raises(facts.NotRun):
        facts.collect(tmp_path, "")


def test_missing_version_is_an_input_error(tmp_path: Path) -> None:
    """Без версии контракта факты не собираются: публиковать нечего.

    Отказ приходит из счёта версии, а не из сборки: та спрашивает версию у
    НАЗВАННОГО дерева. Пока корень не передавался, версия читалась из текущего
    рабочего каталога — то есть из настоящего дерева проекта, — и подделанное
    дерево без файла версии всё равно получало число. Нашёл внешний взгляд
    на #106.
    """
    tree(tmp_path, bindings(**{"001": {"status": "unreviewed"}}))
    (tmp_path / "CONTRACT_VERSION").unlink()
    with pytest.raises((facts.NotRun, facts.version.NotRun)):
        facts.collect(tmp_path, "")


def test_badge_shows_the_number_it_measured() -> None:
    """Значок несёт то же число, что и факты: второго источника у него нет.

    Считаются держащиеся МАШИНОЙ, а не отвеченные: `answered` равен `total` по
    построению — проект отвечает по каждому правилу каталога (129), — и такой
    значок не сдвинулся бы никогда.
    """
    zones = facts.project_zones(
        {"rules": {"by_mechanism": {"gate": 60, "pipeline": 6, "document": 129}}}
    )
    assert zones[0][1][0] == "машиной 66/195 · 34%"
    assert "машиной 66/195 · 34%" in facts.drawing(zones)


@pytest.mark.parametrize(
    ("numerator", "denominator", "color"),
    [
        (0, 5, "RED"),
        (1, 3, "RED"),
        (1, 2, "YELLOW"),
        (2, 3, "YELLOW"),
        (7, 10, "GREEN"),
        (5, 5, "GREEN"),
        (0, 0, "GREY"),
    ],
)
def test_the_share_colour_has_three_bands(numerator: int, denominator: int, color: str) -> None:
    """Три полосы доли — красная, жёлтая, зелёная; пустой знаменатель — ноль, а не падение."""
    assert facts.share_color(numerator, denominator) == getattr(facts, color)


def test_a_wider_text_gets_a_wider_part() -> None:
    """Ширина части растёт с надписью: зоны не наезжают друг на друга в картинке."""
    narrow, wide = facts.part_width("1/5"), facts.part_width("машиной 66/195 · 34%")
    assert 0 < narrow < wide
    svg = facts.drawing(
        [[("правила", facts.LABEL_COLOR, ""), ("машиной 66/195 · 34%", "#000", "")]]
    )
    assert f'width="{facts.part_width("правила") + wide}"' in svg


#: Посаженные факты манифеста семьи: проект, выпуск и отдаваемый контракт.
MANIFEST_PLANTED: Final[dict[str, Any]] = {
    "repo": "Я/Проект",
    "manifest": {"release": {"tag": "v1.5.0", "sha": "a" * 40}, "gives": {"steps": "0.7"}},
}


def test_the_family_manifest_has_the_catalogue_form(tmp_path: Path) -> None:
    """Манифест — форма контракта `family` каталога, и уборка ветки его не снимает (#1285)."""
    facts.draw_badges({"rules": {"by_mechanism": {"gate": 1}}, **MANIFEST_PLANTED}, tmp_path)
    doc = json.loads((tmp_path / "contracts.json").read_text(encoding="utf-8"))
    assert doc == {
        "schema": facts.FAMILY_SCHEMA,
        "project": "Я/Проект",
        "release": {"tag": "v1.5.0", "sha": "a" * 40},
        "gives": {"steps": "0.7"},
        "takes": [],
    }
    assert "contracts.json" in facts.branch_files()
    planted = {"rules": {}, **MANIFEST_PLANTED}
    assert facts.family_manifest(planted) == (tmp_path / "contracts.json").read_text("utf-8")


def test_the_manifest_without_a_section_is_not_drawn_empty(tmp_path: Path) -> None:
    """Нет раздела `manifest` — отказ, а не манифест «ничего не отдаю» (045)."""
    with pytest.raises(KeyError):
        facts.draw_badges({"rules": {"by_mechanism": {"gate": 1}}, "repo": "Я/Проект"}, tmp_path)


def test_manifest_facts_read_the_release_and_the_contract(tmp_path: Path) -> None:
    """Выпуск — последний тег с его коммитом; без тега — null; контракт — MAJOR.MINOR."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / facts.VERSION_FILE).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / facts.VERSION_FILE).write_text("0.7.3\n", encoding="utf-8")
    assert facts.manifest_facts(tmp_path) == {"release": None, "gives": {"steps": "0.7"}}
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "c"], check=True)
    subprocess.run([*git, "tag", "v1.5.0"], check=True)
    sha = subprocess.run(
        [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()
    assert facts.manifest_facts(tmp_path)["release"] == {"tag": "v1.5.0", "sha": sha}
    # Голова ушла вперёд выпуска — номер остаётся номером тега (#299, взгляд на #1294).
    (tmp_path / facts.VERSION_FILE).write_text("0.8.0\n", encoding="utf-8")
    subprocess.run([*git, "commit", "-qam", "d"], check=True)
    assert facts.manifest_facts(tmp_path)["gives"] == {"steps": "0.7"}


def test_the_project_picture_is_drawn_and_kept_on_the_branch(tmp_path: Path) -> None:
    """Значок проекта рисуется сборкой и уборкой ветки не снимается (196, #1213).

    Витрина ссылается на него, и ссылка не смеет вести на снятый файл.
    """
    facts.draw_badges(
        {
            "rules": {"by_mechanism": {"gate": 1, "document": 1}},
            "version": "1.0.0",
            "version_whole": True,
            **MANIFEST_PLANTED,
        },
        tmp_path,
    )
    for name in facts.PICTURES:
        assert (tmp_path / name).read_text(encoding="utf-8").startswith("<svg")
        assert name in facts.branch_files()


def test_badge_colour_follows_the_share() -> None:
    """Цвет говорит о доле правил, а не о настроении: три доли — три цвета."""
    low, mid, high = (
        facts.project_zones({"rules": {"by_mechanism": {"gate": share, "document": 100 - share}}})[
            0
        ][1][1]
        for share in (10, 50, 90)
    )
    assert len({low, mid, high}) == 3


#: Разрезы витрины, публикующие ДОЛЮ, и два числа, из которых она сделана.
#: Список разрешительный (068): доля, которой здесь нет, гейтом отвергается —
#: она обязана приехать со своими слагаемыми либо быть объявлена тут с ними.
A_SHARE_AND_ITS_NUMBERS: dict[str, tuple[str, str]] = {
    "coverage_percent": ("coverage.covered", "coverage.lines"),
}


def flat(said: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Витрина в один уровень: «разрез.ключ» → значение."""
    found: dict[str, Any] = {}
    for key, value in said.items():
        where = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            found |= flat(value, where)
        else:
            found[where] = value
    return found


def test_every_published_share_stands_beside_its_two_numbers(tmp_path: Path) -> None:
    """Доля публикуется вместе с числами, из которых сделана (041).

    «77 %» отвечает на «много ли» и не отвечает на «много ЧЕГО»: та же доля у
    дерева в сто строк и в десять тысяч значит разное, а падение с 77 до 70
    бывает и новым кодом без проверок, и удалением покрытого. Читатель одной
    доли этого не различит и различить не может.

    ЗАМЕР 18.09.2026: долей в витрине две, слагаемые были у ОДНОЙ. У семьи доля
    ехала рядом с `closed_by_shared` из `held_by_machine`, у покрытия — одна.
    То есть ответ проекта «витрина публикует несколько честных чисел и ни одного
    усреднённого» о покрытии был неверен, и опровергался одной командой
    ([175](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/175-an-absence-claim-that-a-command-can-refute-must-be-a-gate.md)).

    ЧИСЛА БЕРУТСЯ ИЗ СОБРАННОЙ ВИТРИНЫ, А НЕ ИЗ СПИСКА: новая доля, добавленная
    мимо объявления, краснеет здесь, а не расходится с ним молча.
    """
    collected = facts.collect(
        tree(
            tmp_path,
            bindings(**{"001": {"status": "active", "mechanism": "gate", "where": "x.py"}}),
        ),
        "голова",
    )
    numbers = flat(collected)
    bare = [
        f"{where} = {value}"
        for where, value in numbers.items()
        if isinstance(value, float) and where not in A_SHARE_AND_ITS_NUMBERS
    ]
    assert not bare, (
        "доля опубликована без чисел, из которых сделана (041):\n  "
        + "\n  ".join(bare)
        + "\n  Публикуйте рядом числитель и знаменатель и объявите пару в"
        " A_SHARE_AND_ITS_NUMBERS: читатель одной доли не отличит рост от усадки."
    )


def test_the_declared_pairs_are_not_a_promise(tmp_path: Path) -> None:
    """Объявленная пара действительно публикуется, а не обещана списком.

    Список, о котором сказано «доля едет со слагаемыми», обязан быть тем, что
    витрина собирает. Иначе это обещание в прозе, и снаружи полная пара и
    отсутствующая выглядят одинаково
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

    Разрез, который в этом прогоне НЕ прочитан, из предмета выпадает и назван:
    сводка семьи приходит из чужого дерева, и требовать её здесь значило бы
    требовать сети от набора (084).
    """
    root = tree(
        tmp_path, bindings(**{"001": {"status": "active", "mechanism": "gate", "where": "x.py"}})
    )
    report = tmp_path / "coverage.json"
    # Отчёт счётчика в той форме, в какой его отдаёт `coverage json`. Поля взяты
    # у настоящего отчёта, а не по памяти: имена проверены прогоном 18.09.2026.
    report.write_text(
        json.dumps(
            {"totals": {"percent_covered": 77.0, "covered_lines": 226, "num_statements": 293}}
        ),
        encoding="utf-8",
    )
    collected = facts.collect(root, "голова", coverage=report)
    numbers = flat(collected)
    checked = 0
    for share, pair in A_SHARE_AND_ITS_NUMBERS.items():
        if share not in numbers:
            continue
        # Доля покрытия — ключ контракта наверху (#759), а признак прочитанности
        # — в разделе её слагаемых.
        section = pair[0].split(".")[0]
        if not (collected.get(section) or {}).get("read"):
            continue
        checked += 1
        for one in pair:
            assert one in numbers, f"{share} объявлена с {one}, а витрина его не публикует"
    assert checked, (
        "ни один разрез с долей не прочитан — проверка зеленеет вокруг пустоты (075)."
        " Подайте разрез, который читается: отчёт покрытия собирается прямо здесь"
    )


def derived_names() -> list[str]:
    """Имена производного — ВСЕ, какие объявляет сборка, а не список руками.

    Список руками отстаёт молча: значков стало четыре, а гейт проверял два —
    `family.svg` и `version.svg` появились вместе с витриной и в проверку не
    попали (049). Имена читаются из модуля: добавится пятое — попадёт само.
    Нашёл внешний взгляд на #134.

    ЧИТАЕТСЯ ИНВЕНТАРЬ, А НЕ ПРОСТРАНСТВО ИМЁН МОДУЛЯ. Прежняя редакция
    соскребала строковые константы через `vars()` по хвосту имени файла —
    приём работал ровно до тех пор, пока у значков не появился один список: он
    видит имена, объявленные КОНСТАНТОЙ, и слеп к тем же именам, объявленным
    данными. Признак взят тот, которым пользуется сама сборка.
    """
    found = sorted({*facts.BADGES, *facts.PICTURES, *facts.PAGES, facts.FACTS, facts.UNIFIED})
    assert len(found) >= 5, f"имён производного разобрано {found} — предмет не найден (075)"
    return found


def carried_names(root: Path) -> set[str]:
    """Имена файлов, которые унёс бы в общую ветку `git add -A`.

    ВНЕСЁННОЕ И ЕЩЁ НЕ ВНЕСЁННОЕ — ОБА (взгляд на #1290): гейт, видящий только
    индекс, зелен на файле, который окно создало и ещё не добавило, — урок
    10.09 у гейта версии (`tests/test_gates_reject.py::
    test_the_version_gate_sees_a_file_not_yet_committed`). Игнорируемое не в
    счёт: его `git add -A` не возьмёт, и архив находок в корне клона, куда его
    кладёт навык `close-a-finding`, объявлен в `.gitignore`.

    СОСЕД В ЭТОМ ФАЙЛЕ ВЫБРАЛ ОБРАТНОЕ, И ЭТО НЕ РАСХОЖДЕНИЕ (взгляд на #1305).
    `test_no_contract_word_in_the_tree_is_followed_by_a_bare_version` судит
    только индекс: его предмет — ТЕКСТ отслеживаемых файлов, и черновик правки
    там — незаконченная работа, красить за которую окно нельзя (#1125). Здесь
    предмет — само ПОЯВЛЕНИЕ файла производного: незаконченным оно не бывает,
    и уедет оно первым же `git add -A`.

    ИСКЛЮЧЕНИЙ ПО КАТАЛОГУ НЕТ. Фикстур с именами производного в дереве нет —
    пробы пишут их в `tmp_path`, — а снятый целиком каталог пропускал бы и
    настоящее производное, попавшее туда (взгляд на #1305). Появится фикстура —
    гейт её назовёт, и исключать её придётся поимённо, с причиной.
    Нечитаемый git — отказ (075).

    УДАЛЁННОЕ С ДИСКА НЕ В СЧЁТ (взгляд на #1305). `--cached` отдаёт и файл,
    снятый с диска, но ещё числящийся в индексе, а `git add -A` такой файл
    снимет: в `main` он не уедет. Его вычитает `--deleted`.
    """
    carried = git_listed(root, "--cached", "--others", "--exclude-standard")
    gone = git_listed(root, "--deleted")
    return {Path(one).name for one in carried - gone}


def git_listed(root: Path, *flags: str) -> set[str]:
    """Пути `git ls-files` с флагами; нечитаемый git — отказ (075)."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", *flags],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert out.returncode == 0, f"git ls-files не ответил — сверять не с чем: {out.stderr}"
    return {one for one in out.stdout.split("\0") if one}


def test_derived_output_is_not_in_the_shared_branch() -> None:
    """Производного нет в общей ветке: оно живёт в ветке `badges` (125, 160).

    Гейт написан на ИМЕНА вывода, а не на его содержимое: файл, случайно
    закоммиченный рядом с источником, выглядит безобидно ровно до того дня,
    когда число в нём разойдётся с источником.

    СУДИТСЯ ТО, ЧТО УЕДЕТ В `main`, А НЕ РАБОЧИЙ КАТАЛОГ (взгляд на #1290):
    внесённое и ещё не внесённое, без игнорируемого и без снятого с диска
    (`carried_names`).
    """
    carried = carried_names(ROOT)
    assert carried, "git не отдал ни одного файла — предмет проверки не найден (075)"
    # ВСЁ, ЧТО ВПРАВЕ ДЕРЖАТЬ ВЕТКА `badges`, а не только изданное сборкой: архив
    # находок там же, и его копия в дереве разошлась бы с веткой так же (160, #1271).
    lying = sorted({*derived_names(), *facts.branch_files()} & carried)
    assert not lying, f"производное ветки badges уедет в общую ветку: {lying}"


def test_the_gate_judges_what_git_add_would_carry(tmp_path: Path) -> None:
    """Не внесённый файл производного — нарушение, и в любом каталоге; игнорируемый — нет."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "facts.json").write_text("{}", encoding="utf-8")
    assert "facts.json" in carried_names(tmp_path), "не внесённое в индекс выпало"
    (tmp_path / ".gitignore").write_text("/facts.json\n", encoding="utf-8")
    assert "facts.json" not in carried_names(tmp_path), "игнорируемое засчитано"
    nested = tmp_path / "tests" / "data" / "findings.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("{}", encoding="utf-8")
    assert "findings.json" in carried_names(tmp_path), "производное в tests/ пропущено"


def test_a_file_deleted_from_disk_is_not_carried(tmp_path: Path) -> None:
    """Внесённый и снятый с диска файл `git add -A` снимет — в счёт не идёт (взгляд на #1305)."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "facts.json").write_text("{}", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "facts.json"], check=True)
    assert "facts.json" in carried_names(tmp_path), "внесённое выпало"
    (tmp_path / "facts.json").unlink()
    assert "facts.json" not in carried_names(tmp_path), "снятое с диска засчитано"
    assert git_listed(tmp_path, "--deleted") == {"facts.json"}


@pytest.mark.parametrize("where", ["coverage.json", "packages/transport/coverage.json"])
def test_a_coverage_report_anywhere_is_ignored(where: str) -> None:
    """`coverage json` пишет отчёт в каталог запуска — он игнорируется везде (#1305, #1316)."""
    out = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", where], check=False)
    assert out.returncode == 0, f"отчёт покрытия {where} не игнорируется — гейт покраснеет"


def test_the_root_archive_of_the_skill_is_ignored() -> None:
    """Архив находок, который навык велит класть в корень клона, игнорируется git (#1290)."""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "-q", facts.ARCHIVE],
        check=False,
    )
    assert out.returncode == 0, (
        f"{facts.ARCHIVE} в корне не игнорируется — гейт 160 краснил бы разбор"
    )


def shown_badges() -> list[str]:
    """Значки, на которые ссылается витрина: второй источник тех же имён.

    Витрина — ИСТОЧНИК, НЕЗАВИСИМЫЙ от сборки: её пишет человек, а имена берёт
    у площадки. Сверять список гейта с тем же модулем, из которого он собран,
    значит проверять равенство самому себе — ровно это и делала редакция,
    найденная внешним взглядом на #183.

    Сам образец адреса живёт в `tests/conftest.py`: спрашивающих трое, и
    экземпляр здесь был третьим (022).
    """
    found = sorted(badges_shown((ROOT / "README.md").read_text("utf-8")))
    # Пол — два: значок проекта заменил «держится машиной» и «семью» (#1213).
    assert len(found) >= 2, f"витрина показывает {found} — предмет проверки не найден (075)"
    return found


def test_every_badge_the_showcase_shows_is_covered_by_the_gate() -> None:
    """Гейт видит все значки витрины, а не те, что помнил автор (находка #183).

    ДВА ИСТОЧНИКА, А НЕ ОДИН. Прежняя редакция брала имена из того же модуля,
    из которого их берёт и сам гейт, — и проверяла равенство самому себе.
    `release.svg` в ней не был назван вовсе, а он выпал бы из проверки вместе
    со всеми, потому что и список, и сверка читали один список.
    """
    said = derived_names()
    missing = [name for name in shown_badges() if name not in said]
    assert not missing, f"витрина показывает {missing}, а гейт производного их не видит"


def test_every_badge_the_build_draws_is_shown() -> None:
    """Обратная сторона: нарисованное сборкой доезжает до витрины.

    Значок, который рисуется и никому не показан, — это работа прогона в
    никуда; значок, который показан и не рисуется, — сломанная картинка (196).
    Оба конца сверяются здесь, потому что источники у них разные.

    СПИСОК НАРИСОВАННОГО СПРАШИВАЕТСЯ У СБОРКИ, А НЕ ПОМНИТСЯ. Прежняя
    редакция держала здесь множество из ЧЕТЫРЁХ имён, выписанных рукой, при
    шести рисуемых: `scripts.svg` и `coverage.svg` в него не попали, и
    проверка два месяца сверяла память автора с README — зелёная при том, что
    два значка рисовались каждым прогоном и не были показаны нигде. Обещание
    докстринга «нарисованное сборкой» при этом стояло на месте, то есть гейт
    утверждал о себе неправду
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    # Нарисованное впрок (`AHEAD`) показывается вторым шагом (196).
    drawn = (set(facts.BADGES) | set(facts.PICTURES)) - facts.AHEAD
    # Пол — три: значок проекта заменил «держится машиной» и «семью» (#1213).
    assert len(drawn) >= 3, f"сборка рисует {sorted(drawn)} — предмет проверки не найден (075)"
    # Входы единого значка показываются его зонами, а не сами (#1019): рядом с
    # ним они были бы дублями. Сам единый значок рисует шаг `badges.yml`.
    expected = (drawn - set(facts.ZONE_INPUTS)) | {facts.UNIFIED}
    assert expected == set(shown_badges()), (
        f"витрине положено показать {sorted(expected)}, а показано {shown_badges()}"
    )


def test_every_page_the_build_lays_is_linked() -> None:
    """Страница, положенная сборкой, связана из витрины — или объявлена впрок (195, #1268).

    Сверка значков выше читает `BADGES | PICTURES`; страница — соседний случай
    того же предмета, и без этой проверки ссылка на неё держалась бы ничем.
    """
    assert facts.PAGES, "сборка не кладёт ни одной страницы — предмет проверки не найден (075)"
    drawn = {*facts.PICTURES, *facts.PAGES}
    assert drawn >= facts.AHEAD, f"впрок объявлено не то, что рисуется: {sorted(facts.AHEAD)}"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    unlinked = sorted(
        name
        for name in set(facts.PAGES) - facts.AHEAD
        if f"/badges/.github/badges/{name}" not in readme
    )
    assert not unlinked, f"страница кладётся, а витрина на неё не ведёт: {unlinked}"
    # ОБРАТНОЕ НАПРАВЛЕНИЕ (взгляд на #1268): ссылка README в ветку `badges`
    # называет только то, что сборка вправе туда класть, — иначе имя, убранное
    # из `PAGES`, оставило бы ссылку на снятый файл молча. Образец адреса берёт
    # любое имя, а не только `.json|.svg`, как разбор значков.
    linked = set(re.findall(r"/badges/\.github/badges/([\w.-]+)", readme))
    stray = sorted(linked - set(facts.branch_files()))
    assert not stray, f"витрина ведёт в ветку badges на то, чего сборка не кладёт: {stray}"


def push_command(step: str) -> str:
    """Склеивает команду толчка вместе с её переносами строк."""
    joined = step.replace("\\\n", " ")
    commands = [line for line in joined.splitlines() if "git push" in line]
    assert commands, "шаг публикации ничего не толкает — предмет проверки не найден (075)"
    return commands[0]


def test_publication_writes_only_to_the_derived_branch() -> None:
    """Прогон толкает в `badges`, и никуда больше.

    Право на запись у этого прогона единственное во всём конвейере, поэтому
    проверяется не намерение, а сама команда: имя общей ветки в ней означало бы
    механизм, способный переписать источник своим же выводом.
    """
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # Шаг берётся по имени, а не по месту: после публикации идёт проверка
    # переноса архива (#788), и «последний шаг» публикацией больше не является.
    steps = document["jobs"]["badges"]["steps"]
    publish = next(step for step in steps if step.get("name") == "опубликовать в ветку badges")
    command = push_command(publish["run"])
    assert command.rstrip().endswith("badges"), f"толчок идёт не в производную ветку: {command}"
    assert "main" not in command, "шаг публикации называет общую ветку"
    # Факты кладёт общий шаг (#1001, шаг 2) — и его толчок под тем же судом.
    shared = yaml.safe_load((WORKFLOW.parent / "step-facts.yml").read_text(encoding="utf-8"))
    facts_publish = next(
        step
        for step in shared["jobs"]["facts"]["steps"]
        if step.get("name") == "опубликовать факты коммитом поверх ветки badges"
    )
    # Толчок шага фактов — в скрипте `publish_facts.py`, и его ветку и отказ
    # от `--force` проверяет прогон скрипта (`tests/test_publish_facts.py`).
    # Здесь — что шаг зовёт РОВНО скрипт: сценарий сверяется целиком, а не
    # разбором по слову `git` — `/usr/bin/git`, `"$GIT"` и `cd x;git` разбор
    # пропускал, и ради этого подход и сменили (210, взгляд на #1233).
    assert " ".join(facts_publish["run"].split()) == FACTS_PUBLISH_RUN, facts_publish["run"]


#: Сценарий шага публикации фактов — целиком. Иная запись шага, даже
#: равносильная, краснеет: о ней решают правкой этой строки, а не разбором.
#: ПРЕДЕЛ (взгляд на #1233): запись на `badges` из ДРУГОГО шага `step-facts.yml`
#: этим не ловится — найти её можно только разбором оболочки, от которого и
#: ушли; держит это чтение изменения, а не гейт.
FACTS_PUBLISH_RUN: Final = (
    'python $MECHANISMS/scripts/publish_facts.py "$RUNNER_TEMP/facts/facts.json" '
    '--workdir "$RUNNER_TEMP/publish" --sha "$GITHUB_SHA" --repo "$GITHUB_REPOSITORY"'
)


def test_publication_is_not_a_check_on_a_change() -> None:
    """Публикация не идёт на изменении: она не проверка и вердикта не выносит."""
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "pull_request" not in document[True]


def test_build_refuses_to_write_next_to_the_sources(run_script: RunScript) -> None:
    """Каталог вывода обязателен: умолчания «рядом с источником» нет."""
    run = run_script("build_facts.py")
    assert run.code != 0, run.text
    assert "--out-dir" in run.text


def test_the_facts_carry_the_computed_version() -> None:
    """Факты несут ПОСЧИТАННУЮ версию рядом с объявленным контрактом.

    Числа разные и оба нужны: контракт объявляет поверхность механизмов и
    поднимается решением человека, версия проекта считается по истории —
    «столько изменений принято после выпуска». Свести их в одно значило бы либо
    скрыть работу, либо объявить выпуском каждое изменение (035).
    """
    collected = facts.collect(ROOT, "abc1234")
    assert collected["contract"], "объявленный контракт исчез из фактов"
    assert collected["version"], "посчитанной версии в фактах нет"
    assert collected["version"] != collected["contract"] or collected["version"].endswith(".0")


def test_the_facts_say_whether_the_version_is_whole() -> None:
    """Неполнота названа рядом с числом, а не выброшена.

    Клон без тегов даёт правдоподобное число: MAJOR.MINOR берутся из
    объявленного контракта вместо выпущенного. Потребитель фактов должен видеть
    это в данных, а не догадываться (046).
    """
    assert "version_whole" in facts.collect(ROOT, "abc1234")


def test_the_badge_run_fetches_the_tags() -> None:
    """Прогон значков берёт всю историю и теги — иначе версия считается ложно."""
    text = (ROOT / ".github" / "workflows" / "badges.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 0" in text
    assert "fetch-tags: true" in text


def test_checks_per_pr_count_only_the_change(tmp_path: Path) -> None:
    """Проверки на изменении — только первый раздел, с именами (#759).

    Контракт фактов семьи спрашивает, сколько проверок стоит на ИЗМЕНЕНИИ.
    Прежний ключ `checks` считал оба раздела, и прогон вне изменения попадал в
    ответ на этот вопрос. Имена едут рядом, чтобы число проверяли.
    """
    answer = tmp_path / ".pipeline.yml"
    answer.write_text(
        'schema: 4\ncontract: ">=9.9,<9.10"\n'
        "checks:\n  lint: required\n  review:\n    class: advisory\n"
        "    why: совещательный взгляд\n    addressee: none\n"
        "beyond_the_change:\n  nightly:\n    class: advisory\n"
        "    why: идёт по толчку в общую ветку\n    addressee: none\n",
        encoding="utf-8",
    )
    (tmp_path / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    counted = facts.checks_facts(answer)
    assert counted["count"] == 2
    assert counted["names"] == ["lint", "review"]
    assert counted["by_class"]["advisory"] == 1, "прогон вне изменения попал в счёт"


# --- отставание от семьи: непосчитанное называется ---------------------------


def where_snapshot(tmp_path: Path) -> Path:
    """Сводка каталога с одним чужим ответом, который держится гейтом."""
    path = tmp_path / "where.json"
    path.write_text(
        json.dumps(
            {
                "schema": "1.2",
                "consumers": [
                    {
                        "repo": "ArtVsMark/Glossary-Python",
                        "holds": {"077": {"mechanism": "gate", "where": "scripts/x.py"}},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def answers(tmp_path: Path, body: str) -> Path:
    """Наши ответы каталогу — файлом, как их читает сборщик."""
    path = tmp_path / "bindings.json"
    path.write_text(body, encoding="utf-8")
    return path


def test_the_gap_is_counted_when_both_sides_are_named(tmp_path: Path) -> None:
    """Названы и наше имя, и файл ответов — отставание посчитано.

    Здоровый вход обязан пройти: иначе «не посчитано» неотличимо от «нечего
    считать» (097).
    """
    ours = answers(tmp_path, '{"rules": {"077": {"mechanism": "document", "status": "active"}}}')
    got = facts.family_facts(
        where_snapshot(tmp_path), mine="ArtVsMark/Engineering-Pipeline-Mechanisms", answers=ours
    )
    assert got["behind_read"] is True
    assert got["behind"] == 1 and got["behind_rules"] == ["077"]


def test_an_uncounted_gap_says_so_instead_of_showing_zero(tmp_path: Path) -> None:
    """Имя не названо — отставание НЕ посчитано, и это сказано словами.

    Молчание читалось бы как «отставания нет», а отсутствие числа и нулевое
    число — разные состояния
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Нашёл внешний взгляд на #240.
    """
    got = facts.family_facts(where_snapshot(tmp_path), mine="", answers=None)
    assert got["behind_read"] is False
    assert "behind" not in got, "непосчитанное отставание вышло числом"
    assert "не посчитано" in got["behind_why"]


def test_a_broken_answers_file_refuses_instead_of_counting_everything(tmp_path: Path) -> None:
    """Дефектный ответ — отказ, а не пустой словарь.

    Пустой дал бы отставание, равное числу ВСЕХ машинных ответов семьи:
    правдоподобное число, которое ложь. Нашёл внешний взгляд на #240.
    """
    for body in ('{"правила": {}}', "{ это не json", '{"rules": []}', '{"rules": {}}'):
        got = facts.family_facts(
            where_snapshot(tmp_path),
            mine="ArtVsMark/Engineering-Pipeline-Mechanisms",
            answers=answers(tmp_path, body),
        )
        assert got["behind_read"] is False, body
        assert "behind" not in got, body


#: Что рисовалке значка МОЖНО звать. Список РАЗРЕШИТЕЛЬНЫЙ: имя вне его делает
#: проверку слепой, а слепая отвергает (068).
#:
#: ПЕРВАЯ РЕДАКЦИЯ БЫЛА ЗАПРЕТИТЕЛЬНОЙ — перечисляла «нельзя», — и потому
#: держала не запрет, а список УГАДАННЫХ имён: `read_bytes`, `listdir`,
#: `check_output`, `urlopen` прошли бы незамеченными. Нашёл внешний взгляд.
#: Разрешительный список ошибается в безопасную сторону: новый законный вызов
#: получит отказ с названной причиной и будет дописан сюда осознанно.
#:
#: СПИСОК РАВЕН ЗАМЕРУ, А НЕ ШИРЕ ЕГО. Первая редакция дописала сюда `len`,
#: `max`, `min`, `sorted`, `abs`, `.keys`, `.join`, `.format` — ничего из этого
#: рисовалки не зовут, и разрешение выдавалось впрок. Разрешительный список,
#: выданный впрок, держит ровно столько же, сколько запретительный: он перестаёт
#: быть замером и становится догадкой о будущем (005). Нашёл внешний взгляд.
#:
#: Замер 18.09.2026: шесть рисовалок зовут ровно `badge`, `sum`, `int`, `float`,
#: `str`, `bool`, `round`, `isinstance` и методы отображения `.get`, `.items`,
#: `.values` — ничего сверх счёта по переданным фактам. Понадобится новое имя —
#: оно дописывается вместе с вызовом, а не заранее.
INSIDE_THE_FACTS: Final = frozenset(
    {
        "badge",
        "sum",
        "int",
        "float",
        "str",
        "bool",
        ".get",
        # Цвет доли по двум уже прочитанным числам: ничего не читает (#1213).
        "share_color",
        # Процент по тем же двум числам, что факты публикуют рядом: форма, не новое число.
        "counted",
        ".items",
        ".values",
    }
)


def badge_makers() -> list[ast.FunctionDef]:
    """Рисовалки значков — те, что объявлены в инвентаре BADGES, а не по имени.

    ИМЯ БРАТЬ НЕЛЬЗЯ: признак «функция кончается на `_badge`» — подстрока, и
    рисовалка, названная иначе, ушла бы из-под проверки молча
    ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
    Инвентарь `BADGES` — тот же источник, по которому значки и собираются, так что
    предмет проверки и предмет сборки совпадают по построению (022).
    """
    named = {maker.__name__ for maker in [*facts.BADGES.values(), *facts.PICTURES.values()]}
    tree = ast.parse((ROOT / "scripts" / "build_facts.py").read_text(encoding="utf-8"))
    found = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in named
    ]
    assert len(found) == len(named), (
        "в дереве найдены не все рисовалки инвентаря: "
        f"{sorted(named)} против {sorted(node.name for node in found)}"
    )
    return found


def test_a_badge_shows_only_what_the_facts_already_say() -> None:
    """Значок рисуется ТОЛЬКО из переданных фактов — тогда сырое лежит рядом всегда.

    Форматирование — операция с потерей, и разбор строки обратно есть
    восстановление того, что сам же и уничтожил. Поэтому рядом с показанной
    величиной отдаётся исходное число
    ([122](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/122-ship-the-raw-value-next-to-the-formatted-one.md)).

    У нас это держится УСТРОЙСТВОМ: рисовалка получает факты и больше ничего, а
    факты публикуются рядом со значками тем же прогоном. Рисовалка, посчитавшая
    число сама — обходом дерева, чтением файла, запуском команды, — оставила бы
    потребителю только картинку, и сырого рядом не было бы вовсе.

    ЗАМЕР 18.09.2026: рисовалок шесть, сторонних источников у них ноль, единственный
    аргумент у каждой — факты. То есть требование исполнялось и не держалось ничем
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    """
    guilty: list[str] = []
    for maker in badge_makers():
        names = [arg.arg for arg in maker.args.args]
        if names != ["facts"]:
            guilty.append(f"{maker.name} берёт {names}, а не одни факты")
        called: set[str] = set()
        for node in ast.walk(maker):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(f".{node.func.attr}")
            else:
                called.add("<вызов неразобранной формы>")
        reached = sorted(called - INSIDE_THE_FACTS)
        if reached:
            guilty.append(f"{maker.name} зовёт не из разрешённого: {', '.join(reached)}")
    assert not guilty, (
        "значок получает число не из фактов — сырого рядом с показанным не будет (122):\n  "
        + "\n  ".join(guilty)
        + "\n  Считайте число в сборке фактов и передайте его сюда: публикуется оно"
        " рядом со значком.\n  Если вызов законен и ничего не читает — допишите его"
        " в INSIDE_THE_FACTS осознанно."
    )


def test_every_badge_maker_is_in_the_inventory() -> None:
    """Каждая рисовалка в коде стоит в инвентаре — иначе проверка выше говорит о части.

    ЗДЕСЬ НУЖЕН НЕЗАВИСИМЫЙ СВИДЕТЕЛЬ, И ЭТО НЕ ПРИДИРКА. Первая редакция
    сравнивала инвентарь с функциями, найденными ПО ЭТОМУ ЖЕ инвентарю, — то есть
    сама с собой, и снятие значка из `BADGES` она не замечала: рисовалка уходила из
    предмета вместе с записью о ней. Поймано откатом
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).

    Свидетель — имя функции, кончающееся на `_badge`. Признак это слабый, и
    основным он быть не может (166), но роль у него обратная: он ищет рисовалку,
    которую инвентарь ЗАБЫЛ. Ошибётся он в безопасную сторону — потребует записать
    в инвентарь то, что и так там должно быть.
    """
    assert facts.BADGES, "инвентарь значков пуст — предмет проверки не найден (075)"
    tree = ast.parse((ROOT / "scripts" / "build_facts.py").read_text(encoding="utf-8"))
    in_code = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.endswith(("_badge", "_zones"))
    }
    assert in_code, "рисовалок значков в дереве не нашлось — предмет проверки не найден (075)"
    makers = [*facts.BADGES.values(), *facts.PICTURES.values()]
    forgotten = sorted(in_code - {maker.__name__ for maker in makers})
    assert not forgotten, (
        "рисовалка есть в коде, но не в инвентаре — значок собирается в обход, и"
        f" проверка выше его не судит: {', '.join(forgotten)}"
    )


def test_the_allowed_list_equals_the_measurement() -> None:
    """Разрешено ровно то, что рисовалки зовут, — ни именем больше.

    Разрешительный список, выданный впрок, держит столько же, сколько
    запретительный: он перестаёт быть замером и становится догадкой о будущем.
    Нашёл внешний взгляд.
    """
    called: set[str] = set()
    for maker in badge_makers():
        for node in ast.walk(maker):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(f".{node.func.attr}")
    assert called, "рисовалки не зовут ничего — предмет замера не найден (075)"
    spare = sorted(INSIDE_THE_FACTS - called)
    assert not spare, (
        "разрешено впрок то, чего рисовалки не зовут: " + ", ".join(spare) + "\n  Разрешение"
        " дописывают вместе с вызовом, а не заранее."
    )


def test_an_empty_answer_is_refused_before_the_count(tmp_path: Path) -> None:
    """Пустой ответ каталогу отвергается РАЗБОРОМ, а не счётчиком нулей.

    В списке `counted` у сборки стояло и `rules.total` — запись недостижимая:
    до неё `rules_facts` уже отказал входу. Два места, отвергающие одно,
    расходятся молча, и починив одно, про второе забывают
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    Запись убрана, а отказ обязан остаться ровно один — этот
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    empty = tmp_path / "bindings.json"
    empty.write_text('{"rules": {}}', encoding="utf-8")
    with pytest.raises(facts.NotRun):
        facts.rules_facts(empty)


@pytest.mark.parametrize(
    ("tag", "series"),
    [("v1.3.0", "1.3"), ("v1.10.0", "1.10"), ("v2.0.4", "2.0"), (None, ""), ("", "")],
)
def test_release_is_a_series_not_a_tag(tag: str | None, series: str) -> None:
    """`release` — серия `X.Y` по договору фактов 1.3 (#1046): без `v` и без третьей цифры."""
    assert facts.release_series(tag) == series


def test_collect_writes_the_release_as_a_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`collect` пишет в `release` серию, а не тег: сверяется сборка, а не помощник (#1105)."""
    tree(tmp_path, bindings(**{"001": {"status": "active", "mechanism": "gate", "where": "тут"}}))
    monkeypatch.setattr(facts.version, "release_tag", lambda *_: "v1.3.0")
    assert facts.collect(tmp_path, "голова")["release"] == "1.3"


#: Слово «договор» — СУЩЕСТВИТЕЛЬНОЕ во всех падежах, а не основа:
#: «договорённость» и «договорились» — другие слова (взгляд на #1125).
CONTRACT_WORD: Final = re.compile(r"\bдоговор(?:а|у|ом|е|ы|ов|ам|ами|ах)?\b", re.IGNORECASE)
#: Номер версии в любой записи: `1.3`, `v1.3`, `1.3.0`.
VERSION: Final = re.compile(r"[vV]?\d+\.\d+(?:\.\d+)?")
#: Дата — не версия: `02.10.2026` и `09.2026` номером договора не бывают.
DATE: Final = re.compile(r"\d{1,2}\.\d{2}\.\d{4}|\d{2}\.\d{4}")
#: Что стоит СРАЗУ за словом: за пропущенными знаками — номер (цифры через
#: точки; точка конца фразы к нему не пристаёт) либо слово. Какие знаки
#: пропускаются, а какие рвут разбор, — ниже; прежнее «пропускается всё, что
#: не буква и не цифра» (#1128) отменено, потому что каждый незнакомый знак
#: становился обходом (взгляд на #1153, `3137b51`).
#:
#: КАЖДЫЙ ЗНАК ЗА СЛОВОМ ОТНЕСЁН ЯВНО, А НЕИЗВЕСТНЫЙ — КРАСНОЕ С ИМЕНЕМ (210,
#: 206, 213). Пять заходов взгляда подряд (#1128, #1130, #1133 дважды, #1146)
#: находили знак, которого правило не знало. Вывод по именам Юникода оказался
#: тем же перечнем уровнем выше: `‽` и `।` — концы фразы, а в набор не
#: попали, `¿` и `¡` попали, хотя начинают фразу. У Python нет свойства
#: «конец предложения» (Sentence_Terminal), и любой вывод его угадывает.
#: Поэтому круг рвётся не новой формой, а тем, что неизвестное больше не
#: молчит:
#:
#: * ПРОПУСКАЮТСЯ пробельные знаки (`str.isspace`) и закрытый перечень
#:   `SKIP_MARKS` — ровно знаки, которые стоят за словом в тексте дерева
#:   (замер 05.10.2026: 18 разных знаков, из них границ — 3);
#: * ГРАНИЦЫ — `BOUNDARY` (конец фразы `.` `!` `?` `…`, конец части `;`,
#:   ячейка `|`) и пустая строка; переводы строки — по `str.splitlines`,
#:   `\r\n` — один перевод (атомарная группа);
#: * ЛЮБОЙ ДРУГОЙ знак за словом обрывает разбор, а проверка по дереву
#:   называет его (`unclassified_marks`) и краснеет, пока его не отнесут к
#:   одному из двух перечней. Так `‽` или `¿` в тексте — не ложное красное и
#:   не обход, а вопрос, заданный вслух.
SKIP_MARKS: Final = ',—():`#»*«"[]{}'
BOUNDARY: Final = ".!?…;|"
LINE_BREAKS: Final = "".join(
    char for char in map(chr, range(0x10000)) if len(f"a{char}b".splitlines()) == 2
)
_BREAK: Final = rf"(?>\r\n|[{re.escape(LINE_BREAKS)}])"
BLANK_LINE: Final = rf"{_BREAK}[^\S{re.escape(LINE_BREAKS)}]*{_BREAK}"
NEXT_TOKEN: Final = re.compile(
    rf"(?:(?!{BLANK_LINE})[\s{re.escape(SKIP_MARKS)}]|_)*"
    r"(?P<token>[vV]?\d+(?:\.\d+)+|\w+)"
)
#: Слово, собранное из частей: отвергаемые примеры ниже не стоят в исходнике
#: буквами, и обход дерева не находит их в этом же файле.
WORD: Final = "догово" + "р"
#: Выпущенный журнал — история: его формулировки уже прочитаны и не правятся.
HISTORY: Final = ("CHANGELOG.md", "changelog.d/released/")


def contract_names_off_form(text: str) -> list[str]:
    """Договор по версии без имени: номер стоит СРАЗУ за словом «договор».

    СТРОГОЕ ПРАВИЛО И НАЗВАННЫЙ ОСТАТОК (210, 057; заходы на #1109, #1125
    дважды, #1128 трижды). Разбор фразы рос формой за заход — кавычки, `v`,
    запятая, перенос, двоеточие, сокращения — и каждое расширение рождало
    либо обход, либо ложное красное («договор фактов, пункт 2.1»). Предикат
    судил СМЫСЛ, а не запись. Поэтому машина держит одно: первое, что стоит
    за словом после знаков той же части текста, не номер версии.
    Пропускаются пробелы и знаки `SKIP_MARKS`; граница `BOUNDARY`, пустая
    строка и неизвестный знак разбор обрывают, — поэтому разметка, скобки и
    регистр `v` обхода не дают, а номер следующей фразы, абзаца или ячейки
    ложно не краснеет (примеры — в таблице ниже). Неизвестный знак называет
    `unclassified_marks`.

    ОСТАТОК ДЕРЖИТСЯ ЧТЕНИЕМ, и это названо (195, 057): за словом стоит
    другое слово — «договор поднялся до 1.3», «договору витрины семьи 1.3».
    Отличить их от «договор фактов описан для Python 3.12» может только
    понимание фразы, а не разбор. Форма записи — «договор фактов X.Y» —
    названа у проверки по дереву ниже, и гейт держит её голую половину.
    """
    found = []
    for word in CONTRACT_WORD.finditer(text):
        nxt = NEXT_TOKEN.match(text, word.end())
        if nxt is None:
            continue
        token = nxt.group("token")
        if VERSION.fullmatch(token) and not DATE.fullmatch(token):
            found.append(" ".join(text[word.start() : nxt.end()].split()))
    return found


def test_an_unknown_mark_is_named_not_guessed() -> None:
    """Знак вне обоих перечней обрывает разбор и назван — ни обхода, ни ложного красного (#1146)."""
    for mark in ("‽", "¿", "¡", "।", "‼"):
        text = f"{WORD}{mark} 1.3"
        assert contract_names_off_form(text) == [], text
        assert unclassified_marks(text) == [mark], text
    assert unclassified_marks(f"{WORD} «фактов» (1.3), — `1.3` **1.3**") == []
    # Промежуток — тот же, что у разбора: за границей и пустой строкой знаки
    # другой части не судятся, а за неизвестным — назван только он (`438b122`).
    assert unclassified_marks(f"{WORD}.\n\n- пункт") == []
    assert unclassified_marks(f"{WORD}\n\n- пункт") == []
    assert unclassified_marks(f"{WORD}; ‽ 1.3") == []
    assert unclassified_marks(f"{WORD} ‽ ¿ 1.3") == ["‽"]
    assert unclassified_marks(f"{WORD} _1.3") == []
    assert set(LINE_BREAKS) == {
        "\n",
        "\r",
        "\v",
        "\f",
        "\x1c",
        "\x1d",
        "\x1e",
        "\x85",
        "\u2028",
        "\u2029",
    }
    assert re.match(BLANK_LINE, "\r\n") is None and re.match(BLANK_LINE, "\r\n\r\n")


def unclassified_marks(text: str) -> list[str]:
    """Знаки за словом «договор», которых нет ни в `SKIP_MARKS`, ни в `BOUNDARY`.

    Смотрится ТОТ ЖЕ промежуток, что проходит `NEXT_TOKEN`, и ни знаком
    дальше (взгляд на #1146, `438b122`): от слова до первой буквы или цифры,
    границы `BOUNDARY` или пустой строки. За границей начинается другая
    часть текста — «договор.\n\n- пункт» не судится по `-`, на котором разбор
    и не стоял. Неизвестный знак обрывает разбор, поэтому назван первый,
    а не все до буквы.
    """
    unknown: list[str] = []
    blank_line = re.compile(BLANK_LINE)
    for word in CONTRACT_WORD.finditer(text):
        index = word.end()
        while index < len(text) and not text[index].isalnum():
            char = text[index]
            if char in BOUNDARY or blank_line.match(text, index):
                break
            if not (char.isspace() or char in SKIP_MARKS or char == "_"):
                if char not in unknown:
                    unknown.append(char)
                break
            index += 1
    return unknown


@pytest.mark.parametrize(
    ("text", "off"),
    [
        ("договор фактов 1.3", []),
        ("по договору фактов с 1.2", []),
        ("договор ответа до 2.1", []),
        ("Договор фактов с 1.2", []),
        ("договор фактов `1.3`", []),
        (f"{WORD} 1.3", [f"{WORD} 1.3"]),
        (f"{WORD.capitalize()} 1.3", [f"{WORD.capitalize()} 1.3"]),
        (f"номер {WORD}а `1.3`", [f"{WORD}а `1.3"]),
        (f"номер {WORD}а: `1.3`", [f"{WORD}а: `1.3"]),
        (f"{WORD} v1.3", [f"{WORD} v1.3"]),
        (f"{WORD} 1.3.", [f"{WORD} 1.3"]),
        (f"{WORD} **1.3**", [f"{WORD} **1.3"]),
        (f"{WORD} [1.3]", [f"{WORD} [1.3"]),
        (f"{WORD} 1.3!", [f"{WORD} 1.3"]),
        (f"{WORD} _1.3_", [f"{WORD} _1.3"]),
        (f"{WORD} V1.3", [f"{WORD} V1.3"]),
        # Граница фразы: номер СЛЕДУЮЩЕЙ фразы — не номер этого слова.
        (f"вписано в {WORD}. 2.1 Следующий пункт", []),
        (f"{WORD}.\n\n1.3. Раздел", []),
        (f"{WORD}! 1.3", []),
        # Граница, закрытая разметкой, кавычкой или скобкой, — та же граница.
        (f"**{WORD}.** 1.3", []),
        (f"({WORD}.) 2.1", []),
        (f"{WORD}.» 1.3", []),
        (f"## {WORD.capitalize()}\n\n1.3 Раздел", []),
        (f"| {WORD.capitalize()} | 1.3 |", []),
        (f"{WORD}; 1.3", []),
        (f"{WORD}\n1.3.0", [f"{WORD} 1.3.0"]),
        # Пробельные знаки — все, а не перечень (взгляд на #1133): неразрывный,
        # узкий неразрывный и тонкий пробел, `\r` из CRLF, `\f`, `\v`.
        (f"{WORD}\u00a01.3", [f"{WORD} 1.3"]),
        (f"{WORD}\u202f1.3", [f"{WORD} 1.3"]),
        (f"{WORD}\u20091.3", [f"{WORD} 1.3"]),
        (f"{WORD}\r\n1.3", [f"{WORD} 1.3"]),
        (f"{WORD}\f1.3", [f"{WORD} 1.3"]),
        (f"{WORD}\v1.3", [f"{WORD} 1.3"]),
        # Пустая строка — граница в любой записи: LF, CRLF, с пробелами внутри.
        (f"{WORD}\r\n\r\n1.3 Раздел", []),
        (f"{WORD}\n \t\n1.3 Раздел", []),
        (f"{WORD}\u00a0\n\n1.3 Раздел", []),
        # Границы — перечень `BOUNDARY`, переводы строки — по `str.splitlines`
        # (взгляд на #1133, `ec3f6cf`, `19aacc3`; на #1146, `436af87`):
        # многоточие одним знаком, перевод строки `\r`, U+2028/U+2029, `\x85`.
        (f"{WORD}… 1.3", []),
        # `‼` — не граница, а неизвестный знак: разбор обрывается, и проверка
        # по дереву его называет (`test_an_unknown_mark_is_named_not_guessed`).
        (f"{WORD}‼ 1.3", []),
        (f"{WORD}\r\r1.3 Раздел", []),
        (f"{WORD}\u2028\u20281.3 Раздел", []),
        (f"{WORD}\u2029\u20291.3 Раздел", []),
        (f"{WORD}\x85\x851.3 Раздел", []),
        # Один перевод любой записи — не пустая строка: номер за ним ловится.
        (f"{WORD}\u20281.3", [f"{WORD} 1.3"]),
        (f"{WORD}\x851.3", [f"{WORD} 1.3"]),
        # Ложного красного нет: число после имени — не номер договора.
        ("договор фактов, пункт 2.1", []),
        ("договор фактов описан для Python 3.12", []),
        ("договор конвейера и пояснения говорят о планке 3.14", []),
        (f"{WORD}ились 02.10.2026", []),
        (f"{WORD}ённость о 1.3", []),
        (f"{WORD}ённость 2.1", []),
        (f"{WORD} от 02.10.2026", []),
        (f"{WORD} 02.10.2026", []),
        # ОСТАТОК — ЧТЕНИЕМ (057): за словом стоит слово, и смысл не разобрать.
        (f"{WORD} поднялся до 1.3", []),
        (f"{WORD}у витрины семьи 1.3", []),
        (f"{WORD}, т. е. 1.3", []),
    ],
)
def test_a_contract_is_named_before_its_version(text: str, off: list[str]) -> None:
    """Голый номер за словом — назван; имя или другое слово за словом — чисто.

    Вторая половина — и законные формы, и остаток, который держит чтение
    («договору витрины семьи 1.3»): машина судит только голый номер.
    """
    assert contract_names_off_form(text) == off


def test_no_contract_word_in_the_tree_is_followed_by_a_bare_version() -> None:
    """В дереве за словом «договор» нигде не стоит голый номер (#1109, #1128).

    Держится ГОЛАЯ ПОЛОВИНА формы «договор фактов X.Y»; второе имя между
    словом и номером держит чтение — граница у `contract_names_off_form`.
    """
    listed = subprocess.run(
        # Отслеживаемое, и только оно: черновик в рабочей копии не должен
        # красить гейт у окна, когда у площадки тот же набор зелёный (#1125).
        ["git", "ls-files", "-z", "--cached"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.split("\0")
    off, unsorted = {}, {}
    for name in listed:
        if not name or name.startswith(HISTORY) or not (ROOT / name).is_file():
            continue
        try:
            text = (ROOT / name).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if found := contract_names_off_form(text):
            off[name] = found
        if unknown := unclassified_marks(text):
            unsorted[name] = unknown
    assert not off, f"договор по версии без имени: {off}"
    assert not unsorted, (
        f"за словом стоит знак, которого перечни не знают: {unsorted} — отнесите его "
        "к SKIP_MARKS (пропускать) или к BOUNDARY (граница фразы)"
    )


# --- режимы общего издателя (#1001, шаг 2) -----------------------------------


def test_extra_written_carries_only_our_sections(tmp_path: Path) -> None:
    """`--extra-out` пишет свои разделы — и ни одного общего: их считает общий шаг."""
    import argparse

    out = tmp_path / "extra.json"
    args = argparse.Namespace(
        root=str(ROOT), family="", uptake="", repo="Я/Проект", extra_out=str(out)
    )
    assert facts.extra_written(args) == facts.EXIT_OK
    said = json.loads(out.read_text(encoding="utf-8"))
    assert set(said) == {
        "contract",
        "tests",
        "scripts",
        "rules",
        "checks_per_pr",
        "family",
        "manifest",
    }
    assert not set(said) & facts.common.COMMON_KEYS


def test_drawn_from_draws_the_same_badges_as_the_build(tmp_path: Path) -> None:
    """Значки по опубликованному файлу совпадают со значками сборки: источник один (022)."""
    whole = facts.collect(ROOT, "голова", mine="Я/Проект")
    built = tmp_path / "built"
    built.mkdir()
    facts.draw_badges(whole, built)
    source = tmp_path / "facts.json"
    source.write_text(json.dumps(whole, ensure_ascii=False), encoding="utf-8")
    assert facts.drawn_from(source, str(tmp_path / "out")) == facts.EXIT_OK
    for name in facts.BADGES:
        drawn = tmp_path / "out" / facts.PUBLISHED_DIR / name
        assert drawn.read_text(encoding="utf-8") == (built / name).read_text(encoding="utf-8")


def test_drawn_from_refuses_what_it_cannot_read(tmp_path: Path) -> None:
    """Файла нет, раздела нет, каталога вывода нет — отказ, а не пустые значки (075)."""
    assert facts.drawn_from(tmp_path / "нет.json", str(tmp_path)) == facts.EXIT_BROKEN
    thin = tmp_path / "thin.json"
    thin.write_text("{}", encoding="utf-8")
    assert facts.drawn_from(thin, str(tmp_path / "out")) == facts.EXIT_BROKEN
    assert facts.drawn_from(thin, "") == facts.EXIT_BROKEN


def test_zeroed_names_a_count_cut_short_and_clashed_sees_no_clash(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ноль в счётчике — обрыв, и он назван; живые имена вывода не совпадают."""
    said = {"tests": {"functions": 0, "modules": 1}, "scripts": {"runnable": 1}}
    assert facts.zeroed(said, "корень") is True
    assert "tests.functions" in capsys.readouterr().err
    whole = {"tests": {"functions": 1, "modules": 1}, "scripts": {"runnable": 1}}
    assert facts.zeroed(whole, "корень") is False
    assert facts.clashed() is False


def test_the_badges_branch_keeps_only_what_is_published() -> None:
    """Ветка `badges` держит изданное сборкой, единый значок и архив — и только (#1198).

    Значок, снятый из инвентаря, уходит с ветки: публикация удаляет всё, чего
    в перечне нет, а не копирует поверх.
    """
    module = load_script("build_facts.py")
    kept = set(module.branch_files())
    assert kept == {*module.published_names(), module.UNIFIED, module.ARCHIVE}
    assert "scripts.json" not in kept, "снятый значок остался допустимым на ветке"
    flow = (ROOT / ".github" / "workflows" / "badges.yml").read_text(encoding="utf-8")
    assert 'build_facts.py --prune "$pub/.github/badges"' in flow, "публикация не чистит каталог"
    assert "git add -A .github/badges" in flow, "удаление не записывается в коммит публикации"


def test_pruning_removes_files_and_folders_but_keeps_the_list(tmp_path: Path) -> None:
    """Чистка снимает лишний файл и каталог целиком и не трогает допустимого (взгляд на #1202).

    Прежний цикл звал `git rm` без `-r` и падал на подкаталоге или
    неотслеживаемом файле, роняя всю публикацию; гейт по подстроке в тексте
    прогона этого не видел.
    """
    module = load_script("build_facts.py")
    for name in module.branch_files():
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "retired.json").write_text("{}", encoding="utf-8")
    (tmp_path / "stray").mkdir()
    (tmp_path / "stray" / "inner.json").write_text("{}", encoding="utf-8")
    gone = module.prune(tmp_path)
    assert sorted(gone) == ["retired.json", "stray"]
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(module.branch_files())


def test_the_shared_steps_files_are_kept_on_the_branch() -> None:
    """Файлы общего шага фактов на ветке допустимы, и чистка их не снимает (взгляд на #1202).

    Перечень допустимого строит потребитель из своего инвентаря, а ветку он
    делит с общим шагом: второй файл шага удалялся бы каждым заходом. Что шаг
    кладёт, названо константой `publish_facts.PUBLISHES` и читается импортом:
    разбор оболочки шага три захода подряд пропускал новую форму записи
    (решение владельца 08.10.2026, #639).
    """
    module = load_script("build_facts.py")
    written = {Path(path).name for path in load_script("publish_facts.py").PUBLISHES}
    assert written == set(module.SHARED_STEP), (
        f"общий шаг кладёт {sorted(written)}, а `SHARED_STEP` называет {sorted(module.SHARED_STEP)}"
    )
    missing = written - set(module.branch_files())
    assert not missing, f"чистка сняла бы файлы общего шага: {sorted(missing)}"
