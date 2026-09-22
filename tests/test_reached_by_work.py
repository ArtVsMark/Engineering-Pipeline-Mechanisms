"""Добавленное зовёт рабочий путь, а не только прогон набора.

21–22.09.2026 шесть механизмов оказались построенными и недостижимыми. Гейт —
пара к `check_new_is_tested`: тот спрашивает, зовёт ли имя НАБОР, этот — зовёт
ли его РАБОЧИЙ путь. Проверяется здесь то, без чего он был бы копией соседа
либо ложной тревогой:

* сирота названа: добавленное, к которому рабочий код не обращается;
* вызов ИЗ СВОЕГО модуля достижимостью является — первая редакция читала текст
  и исключала свой модуль целиком, отчего на настоящей истории дала три ложные
  находки подряд;
* значения не судятся вовсе: пять из пяти таких в дереве законны (росписи для
  набора и пределы, адресованные человеку);
* предмет — только ДОБАВЛЕННОЕ: стоящие в дереве сироты этот гейт не судит;
* имя, названное шагом площадки, достигнуто.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import load_script

module = load_script("check_reached_by_work.py")


def _git(where: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=where, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Дерево с рабочим модулем на общей ветке и веткой изменения."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "them@example.com")
    _git(tmp_path, "config", "user.name", "Кто-то")
    for root in module.WORK:
        (tmp_path / root).mkdir(parents=True)
    (tmp_path / "scripts" / "thing.py").write_text(
        "def main() -> int:\n    return 0\n", encoding="utf-8"
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "механизм")
    _git(tmp_path, "checkout", "-q", "-b", "change")
    return tmp_path


def появилось(repo: Path, текст: str) -> None:
    """Кладёт новую редакцию модуля и фиксирует её."""
    (repo / "scripts" / "thing.py").write_text(текст, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "правка")


def test_an_orphan_is_named(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Добавленное, к которому рабочий код не обращается, названо с адресом.

    ЭТО ТОТ САМЫЙ СЛУЧАЙ #611: `whose` сводил счёт по всему ряду и не
    вызывался ни из отчёта, ни из захода — число считалось и до читателя не
    доходило. Набор при этом был зелёным: он звал функцию напрямую.
    """
    monkeypatch.chdir(repo)
    появилось(repo, "def main() -> int:\n    return 0\n\n\ndef осиротела() -> int:\n    return 1\n")
    assert module.findings("main") == ["scripts/thing.py:осиротела"]
    assert module.main(["--base", "main"]) == module.EXIT_FOUND


def test_a_call_from_its_own_module_counts(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Вызов ИЗ СВОЕГО модуля — достижимость: модуль начинается точкой входа.

    ПЕРВАЯ РЕДАКЦИЯ ЭТО ТЕРЯЛА. Она читала текст и исключала свой модуль
    целиком — иначе `def имя(` засчитывалось за вызов, — и на настоящей истории
    дала ТРИ ложные находки подряд: `say_the_look_is_silenced`, `carriers`,
    `bare_lines`. Все три зовутся из своего же модуля, а тот начинается
    `main()`. Гейт, краснеющий на исправном, учит себя обходить
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    """
    monkeypatch.chdir(repo)
    появилось(
        repo,
        "def помощник() -> int:\n    return 1\n\n\ndef main() -> int:\n    return помощник()\n",
    )
    assert module.findings("main") == []


def test_a_value_is_not_judged(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Значения не судятся, и это ЗАМЕР, а не осторожность.

    Предикат «объявлено и рабочим кодом не достижимо» по 66 модулям дал семь
    имён: два вызываемых — настоящие сироты, и ПЯТЬ значений — законные.
    Закрытые росписи заводятся ДЛЯ набора: их полноту приёмка и проверяет
    (`findings.CHECKED`, `unlooked.STATES`, `paths.ALL`, `kinds.DOCUMENT`), а
    `findings.SAID_LIMIT` адресован человеку прямой оговоркой в докстроке.
    Судить их значило бы краснеть на пяти законных ради двух находок
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    monkeypatch.chdir(repo)
    появилось(repo, 'РОСПИСЬ = ("а", "б")\n\n\ndef main() -> int:\n    return 0\n')
    assert module.findings("main") == [], "значение объявлено находкой"


def test_a_standing_orphan_is_not_this_gates_subject(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Предмет — только ДОБАВЛЕННОЕ этим изменением.

    В дереве есть стоящие сироты — `runs_series.red_jobs` и
    `changerefs.resolutions_in`, обе осиротели от постройки соседа. Краснеть на
    них при каждом изменении значило бы учить себя обходить гейт; долг такого
    рода называется замером, а не красным на чужой работе (051).
    """
    monkeypatch.chdir(repo)
    (repo / "scripts" / "thing.py").write_text(
        "def давняя_сирота() -> int:\n    return 1\n\n\ndef main() -> int:\n    return 0\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "сирота уже на базе")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "change")
    _git(repo, "checkout", "-q", "-b", "потом")
    появилось(
        repo,
        "def давняя_сирота() -> int:\n    return 1\n\n\ndef новая() -> int:\n    return 2\n"
        "\n\ndef main() -> int:\n    return новая()\n",
    )
    assert module.findings("main") == [], "гейт покраснел на сироте, которой не добавлял"


def test_a_name_used_by_a_platform_step_is_reached(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Имя, названное шагом прогона, достигнуто: площадка зовёт его строкой."""
    monkeypatch.chdir(repo)
    runs = repo / ".github" / "workflows"
    runs.mkdir(parents=True)
    (runs / "ci.yml").write_text(
        "шаг:\n  run: python -c 'from thing import зовут_шагом'\n", "utf-8"
    )
    появилось(
        repo, "def main() -> int:\n    return 0\n\n\ndef зовут_шагом() -> int:\n    return 1\n"
    )
    assert module.findings("main") == []


def test_the_platform_runs_are_read_from_the_anchor(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Прогоны читаются по ОБЪЯВЛЕННОМУ адресу, и их отсутствие — не отказ.

    Адрес берётся у якоря `paths`, а не пишется здесь вторым написанием:
    переименование каталога прогонов чинилось бы поиском по строке (022, 090).
    Гейт второго якоря поймал в первой редакции ровно это.

    ПУСТО — ЗАКОННОЕ СОСТОЯНИЕ: у проекта может не быть ни одного прогона, и
    требовать их значило бы требовать наличия того, чем он не обязан
    пользоваться (046).
    """
    monkeypatch.chdir(repo)
    assert module.RUNS == module.paths.WORKFLOWS, "адрес прогонов написан вторым разом"
    assert module.runs_text() == "", "отсутствие прогонов прочитано как отказ"
    runs = repo / module.RUNS
    runs.mkdir(parents=True)
    (runs / "ci.yml").write_text("шаг: тут\n", encoding="utf-8")
    assert "шаг: тут" in module.runs_text()


def test_every_declared_source_is_walked(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Достижимость считается по ВСЕМ источникам, а не по одним скриптам.

    ЗДЕСЬ БЫЛ ДЕФЕКТ, И НАШЁЛ ЕГО ВНЕШНИЙ ВЗГЛЯД (#623). Судится всё, что
    отбирает `touched`, а он идёт по `paths.SOURCES` — скрипты И пакет
    транспорта. Достижимость же считалась по одним скриптам, и имя,
    добавленное в `packages/transport` и вызванное ТАМ ЖЕ, объявлялось сиротой
    ложно. Замер пробой: две добавленные в транспорт функции, одна зовёт
    другую, — гейт назвал сиротами обеих
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

    ТОТ ЖЕ ПЕРЕНОС ОДНАЖДЫ УЖЕ ОСЛЕПИЛ СОСЕДА: `paths.SOURCES` заведён ровно
    потому, что после выноса транспорта наружу свой глоб у каждого читателя
    молча переставал его видеть (090).
    """
    monkeypatch.chdir(repo)
    assert module.WORK == module.paths.SOURCES, "источники написаны вторым разом"
    (repo / "packages" / "transport" / "низ.py").write_text(
        "def зовущая() -> int:\n    return сиротой_не_является()\n\n\n"
        "def сиротой_не_является() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "добавлено в транспорт")
    assert module.findings("main") == ["packages/transport/низ.py:зовущая"], (
        "вызванное внутри транспорта объявлено сиротой — обход идёт не по всем источникам"
    )


def test_a_tree_that_does_not_parse_is_the_third_outcome(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Неразбираемый модуль — отказ, а не «достижимых имён нет» (039, 045)."""
    monkeypatch.chdir(repo)
    (repo / "scripts" / "сломан.py").write_text("def (\n", encoding="utf-8")
    with pytest.raises(module.NotRun, match="не разбирается"):
        module.mentioned()
    появилось(repo, "def main() -> int:\n    return 0\n")
    assert module.main(["--base", "main"]) == module.EXIT_BROKEN


def test_an_untouched_change_says_so(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Изменение без механизмов — не находка и не отказ, а названное состояние."""
    monkeypatch.chdir(repo)
    (repo / "проза.md").write_text("текст\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "проза")
    assert module.main(["--base", "main"]) == module.EXIT_OK
