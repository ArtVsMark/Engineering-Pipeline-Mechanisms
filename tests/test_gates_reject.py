"""Каждый гейт проверяется тем, что он обязан отвергнуть (правило 140).

Проверка того, что гейт пропускает верное, доказывает только половину: гейт,
который не отвергает ничего, зелёный всегда и не держит ничего. Поэтому здесь
прогоняется каждый объявленный исход (145), включая третий — «не отработал».
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path

import pytest

from tests import outcomes
from tests.conftest import ROOT, RunScript, load_script, walk

BROKEN = 2
REJECTED = 1
CLEAN = 0
#: Объявленное состояние «не настроено»: намеренно не единица.
NOT_CONFIGURED = 3


def git(cwd: Path, *args: str) -> None:
    """Зовёт git в подготовленном репозитории теста."""
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    )


# --- состав меток ------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("# только комментарий\n", "пуст"),
        ('- name: "x"\n  color: "нет"\n  description: "d"\n', "шестнадцатеричных"),
        ('- name: "x"\n  color: "ffffff"\n  description: ""\n', "пустое описание"),
        (
            '- name: "x"\n  color: "ffffff"\n  description: "раз"\n'
            '- name: "x"\n  color: "000000"\n  description: "два"\n',
            "дважды",
        ),
    ],
)
def test_label_config_defects_are_third_outcome(
    run_script: RunScript, tmp_path: Path, content: str, expected: str
) -> None:
    """Дефект состава — «не отработал», а не «чисто»: это ошибка входа (075)."""
    config = tmp_path / "labels.yml"
    config.write_text(content, encoding="utf-8")
    result = run_script("sync_labels.py", "--config", str(config), "--repo", "o/r", "--dry-run")
    assert result.code == BROKEN
    assert expected in result.text


def test_label_sync_without_token_does_not_report_clean(run_script: RunScript) -> None:
    """Без токена состояние площадки не прочитано — третий исход, а не ноль."""
    result = run_script(
        "sync_labels.py", "--repo", "o/r", "--dry-run", env={"GH_TOKEN": "", "GITHUB_TOKEN": ""}
    )
    assert result.code == BROKEN
    assert "не прочитано" in result.text


# --- версия ------------------------------------------------------------------


BASE_BRANCH = "base"


def prepare_repo(tmp_path: Path, version: str = "1.2.3") -> Path:
    """Готовит крошечный репозиторий с источником версии.

    Ветка названа явно: имя по умолчанию зависит от настройки машины — на одной
    `master`, на другой `main`, — и тест, опирающийся на него, зелен ровно там,
    где его писали.
    """
    git(tmp_path, "init", "-q", "-b", BASE_BRANCH)
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "Тест")
    (tmp_path / "CONTRACT_VERSION").write_text(f"{version}\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "исходное")
    return tmp_path


def test_version_written_by_hand_is_a_finding(run_script: RunScript, tmp_path: Path) -> None:
    """Число, вписанное руками вне источника, — находка (005, 035)."""
    repo = prepare_repo(tmp_path)
    (repo / "doc.md").write_text("версия 1.2.3 руками\n", encoding="utf-8")
    git(repo, "add", "-A")
    result = run_script("check_version.py", cwd=repo)
    assert result.code == REJECTED
    assert "вне источника" in result.text


def test_stale_marker_is_a_finding(run_script: RunScript, tmp_path: Path) -> None:
    """Маркер есть, а значение чужое — сборка его не переписала (127)."""
    repo = prepare_repo(tmp_path)
    # Теги собираются из частей: написанные парой, они стали бы настоящим
    # маркером, и check_version.py нашёл бы находку в собственном тесте.
    opening = "<!--" + "m:contract" + "-->"
    closing = "<!--" + "/m:contract" + "-->"
    (repo / "doc.md").write_text(f"версия {opening}9.9.9{closing}\n", encoding="utf-8")
    git(repo, "add", "-A")
    result = run_script("check_version.py", cwd=repo)
    assert result.code == REJECTED
    assert "маркер есть" in result.text


def test_fresh_marker_passes(run_script: RunScript, tmp_path: Path) -> None:
    """Маркер с текущим значением проходит — иначе гейт красен неотвратимо."""
    repo = prepare_repo(tmp_path)
    # Теги собираются из частей: написанные парой, они стали бы настоящим
    # маркером, и check_version.py нашёл бы находку в собственном тесте.
    opening = "<!--" + "m:contract" + "-->"
    closing = "<!--" + "/m:contract" + "-->"
    (repo / "doc.md").write_text(f"версия {opening}1.2.3{closing}\n", encoding="utf-8")
    git(repo, "add", "-A")
    assert run_script("check_version.py", cwd=repo).code == CLEAN


def test_missing_version_source_is_third_outcome(run_script: RunScript, tmp_path: Path) -> None:
    """Нет источника версии — гейт не отработал, а не «чисто» (075)."""
    git(tmp_path, "init", "-q", "-b", BASE_BRANCH)
    (tmp_path / "a.md").write_text("текст\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    result = run_script("check_version.py", cwd=tmp_path)
    assert result.code == BROKEN
    assert "объявленную версию взять неоткуда" in result.text


# --- журнал ------------------------------------------------------------------


def test_labels_are_read_from_the_platform_not_the_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Гейт разметки читает изменение у площадки, а не снимок события.

    Снимок `opened` не содержит меток по построению: их проставляет шаг
    открытия через доли секунды ПОСЛЕ события. Замер 09.09: изменение #38
    отвергнуто за «ни одной зоны», когда все три зоны на нём уже стояли, —
    вердикт был вынесен по прошлому.
    """
    check = load_script("check_pr_meta.py")
    stale = {"number": 38, "labels": [], "title": "тема", "body": "Refs #1"}
    live = {"number": 38, "labels": [{"name": "area/core"}], "title": "тема", "body": "Refs #1"}

    calls: list[str] = []

    def request(method: str, path: str, token: str, body: object = None) -> object:
        calls.append(path)
        return live

    # Подмена именно через monkeypatch: транспорт общий на все механизмы, и
    # присвоение атрибута напрямую утекло бы в соседние тесты.
    monkeypatch.setattr(check.ghrest, "request", request)
    got = check.fresh(stale, "о/р", "токен")
    assert calls == ["repos/о/р/pulls/38"]
    assert got["labels"] == [{"name": "area/core"}]


def test_without_a_token_the_snapshot_is_used_and_said_so() -> None:
    """Без токена вердикт по снимку — и это сказано, а не подменено тихо (045)."""
    check = load_script("check_pr_meta.py")
    stale = {"number": 38, "labels": [], "title": "тема", "body": "Refs #1"}
    assert check.fresh(stale, "о/р", "") is stale


def test_change_without_fragment_is_rejected(run_script: RunScript, tmp_path: Path) -> None:
    """Изменение без фрагмента журнала отвергается (030)."""
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "без фрагмента")
    result = run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == REJECTED
    assert "не несёт фрагмента" in result.text


def test_change_with_fragment_passes(run_script: RunScript, tmp_path: Path) -> None:
    """Фрагмент есть — изменение проходит."""
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "changelog.d").mkdir()
    (repo / "changelog.d" / "gate-reads-the-diff.added.md").write_text(
        "что-то новое\n\n#7\n", encoding="utf-8"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "с фрагментом")
    assert run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo).code == CLEAN


def test_two_records_outward_are_warned_about_not_rejected(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Две записи наружу — два «зачем»: предупреждение, а не отказ (132).

    ОТКАЗА ЗДЕСЬ БЫТЬ НЕ ДОЛЖНО, и это требование самого правила: широкая тема
    — переименование вместе со всеми его следствиями — неделима, и машине не
    отличить её от сборности. Ложный отказ на ней дороже пропуска (051), а
    совещательный канал основного пути не держит (084).
    """
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "changelog.d").mkdir()
    (repo / "changelog.d" / "first-theme.added.md").write_text("одно\n\n#7\n", encoding="utf-8")
    (repo / "changelog.d" / "second-theme.fixed.md").write_text("другое\n\n#8\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "две темы разом")
    result = run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == CLEAN, "предупреждение не отказ: слияние оно не держит"
    assert "::warning::" in result.text, "сборность названа вслух, а не молча пропущена"
    assert "наружу: 2" in result.text and "132" in result.text


def test_an_internal_record_is_not_a_second_theme(run_script: RunScript, tmp_path: Path) -> None:
    """Внутренняя запись темой не считается: ею сопровождают чужую работу.

    Иначе предупреждение срабатывало бы ровно на том, что автор объявил
    безразличным потребителю, — и его научились бы пролистывать (051).
    """
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "changelog.d").mkdir()
    (repo / "changelog.d" / "the-theme.added.md").write_text("одно\n\n#7\n", encoding="utf-8")
    (repo / "changelog.d" / "a-side-note.internal.md").write_text(
        "> **Потребителю безразлично:** внутренняя правка\n\nтекст\n\n#7\n", encoding="utf-8"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "тема и внутренняя запись")
    result = run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == CLEAN
    assert "::warning::" not in result.text, "внутренняя запись второй темой не является"


def test_a_fragment_named_by_the_task_number_is_rejected(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Имя фрагмента говорит, ЧТО изменилось, а не какая задача.

    Одна задача живёт дольше одного изменения, и два захода целятся в одно имя.
    Конфликта это не даёт — побеждает последний, — поэтому ловить обязан гейт, а
    не внимательность (075). Замер: `12.fix.md` завели дважды, и запись об
    исправлении атрибуции исчезла без следа и без выпуска.
    """
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "changelog.d").mkdir()
    (repo / "changelog.d" / "12.fixed.md").write_text("правка\n\n#12\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "фрагмент назван номером")
    result = run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == REJECTED
    assert "назван номером задачи" in result.text


def test_deleting_a_fragment_named_by_a_number_is_allowed(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Уборку старого фрагмента гейт имени не отвергает.

    Гейт судит ИМЯ существующего файла. Удалённого в голове нет, и требовать от
    него правильного имени не на чем — иначе уборка фрагментов, названных по
    номеру, отвергалась бы гейтом, который эту уборку и требует.
    """
    repo = prepare_repo(tmp_path)
    (repo / "changelog.d").mkdir(exist_ok=True)
    (repo / "changelog.d" / "12.fixed.md").write_text("старое\n\n#12\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "фрагмент по номеру уже лежит в базе")

    git(repo, "checkout", "-qb", "work")
    (repo / "changelog.d" / "12.fixed.md").unlink()
    (repo / "changelog.d" / "name-says-what-changed.fixed.md").write_text(
        "новое\n\n#12\n", encoding="utf-8"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "переименовал по смыслу")
    result = run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == CLEAN, result.text


def test_deleting_a_fragment_is_not_bringing_one(run_script: RunScript, tmp_path: Path) -> None:
    """Удалённый фрагмент за принесённую запись не считается.

    Иначе изменение, которое запись УНЕСЛО, а своей не оставило, проходит
    гейт зелёным — и уборка старого фрагмента проносит мимо него любую правку
    кода. «Файл упомянут в дифе» и «запись есть в голове» — разные вещи.
    """
    repo = prepare_repo(tmp_path)
    (repo / "changelog.d").mkdir(exist_ok=True)
    (repo / "changelog.d" / "старое.added.md").write_text("старое\n\n#1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "фрагмент лежит в базе")

    git(repo, "checkout", "-qb", "work")
    (repo / "changelog.d" / "старое.added.md").unlink()
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "унёс запись, своей не принёс")
    result = run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == REJECTED, result.text
    assert "не несёт фрагмента" in result.text


def test_a_pure_cleanup_gets_a_declared_outcome_not_a_traceback(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Изменение, которое только удаляет, получает объявленный исход.

    Пустой ответ git значит разное: пустой ПОЛНЫЙ список — изменений нет вовсе
    и это ошибка входа (075); пустой список ВЫЖИВШИХ — изменение всё удалило, и
    это законное состояние. Пока их не развели, чистая уборка роняла гейт
    необработанным исключением — то есть отказом, которого механизм не
    объявлял (039).
    """
    repo = prepare_repo(tmp_path)
    (repo / "changelog.d").mkdir(exist_ok=True)
    (repo / "changelog.d" / "старое.added.md").write_text("старое\n\n#1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "фрагмент лежит в базе")

    git(repo, "checkout", "-qb", "work")
    (repo / "changelog.d" / "старое.added.md").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "только уборка")
    result = run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo)
    assert result.code in {CLEAN, REJECTED}, result.text
    assert "Traceback" not in result.text, result.text


def test_a_fix_without_a_test_is_rejected(run_script: RunScript, tmp_path: Path) -> None:
    """Починка механизма без единой проверки не проходит (014).

    Без входа, на котором гейт краснел до правки, убирается ПОВЕДЕНИЕ, а не
    разбор: дефект может вернуться, и вернётся он молча — набор останется
    зелёным.
    """
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / "gate.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "changelog.d").mkdir(exist_ok=True)
    (repo / "changelog.d" / "gate-stops-eating-input.fixed.md").write_text(
        "починка\n\n#1\n", encoding="utf-8"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "починка без проверки")
    result = run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == REJECTED, result.text
    assert "не принесла ни одной проверки" in result.text


def test_a_fix_in_the_shared_bottom_needs_a_test_too(run_script: RunScript, tmp_path: Path) -> None:
    """Починка ОБЩЕГО НИЗА без проверки отвергается наравне с починкой скрипта.

    ПРЕЖДЕ ЗДЕСЬ БЫЛА ДЫРА. Перечень «где живут механизмы» у гейта состоял из
    `scripts/` и прогонов, а транспорт с обрезкой вывода уехали в
    `packages/transport/` — и починка общего низа проходила БЕЗ единой проверки.
    Того самого низа, чьи имена зовут все прочие механизмы (090).

    Нашёл внешний взгляд находкой `adaa7ce` на #411, и назвал точно: перечень
    стал читаться из объявления, а прогона на НОВОЙ половине предмета не было —
    держался только образец на форму объявления. Форму можно написать верно и
    поведения не получить, и снаружи это выглядит ровно как работающий гейт
    ([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).
    """
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    bottom = repo / "packages" / "transport"
    bottom.mkdir(parents=True, exist_ok=True)
    (bottom / "ghrest.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "changelog.d").mkdir(exist_ok=True)
    (repo / "changelog.d" / "the-transport-stops-swallowing.fixed.md").write_text(
        "починка\n\n#1\n", encoding="utf-8"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "починка общего низа без проверки")
    result = run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == REJECTED, result.text
    assert "не принесла ни одной проверки" in result.text
    assert "packages/transport" in result.text, "гейт не назвал, ЧТО он счёл механизмом"


def test_a_fix_with_a_test_passes(run_script: RunScript, tmp_path: Path) -> None:
    """Здоровый вход обязан пройти: починка с проверкой не отвергается (097)."""
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / "gate.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_gate.py").write_text(
        "def test_x() -> None:\n    pass\n", encoding="utf-8"
    )
    (repo / "changelog.d").mkdir(exist_ok=True)
    (repo / "changelog.d" / "gate-stops-eating-input.fixed.md").write_text(
        "починка\n\n#1\n", encoding="utf-8"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "починка с проверкой")
    assert run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo).code == CLEAN


def test_a_fix_of_prose_needs_no_test(run_script: RunScript, tmp_path: Path) -> None:
    """Починка текста проверки не требует: механизма она не трогает.

    Требовать её значило бы заводить пустые проверки ради гейта — ровно то
    поведение, ради борьбы с которым он и написан.
    """
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "docs" / "use").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "use" / "pipeline.md").write_text("текст\n", encoding="utf-8")
    (repo / "changelog.d").mkdir(exist_ok=True)
    (repo / "changelog.d" / "wording-says-what-happens.fixed.md").write_text(
        "починка текста\n\n#1\n", encoding="utf-8"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "починка прозы")
    assert run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo).code == CLEAN


def test_no_diff_is_third_outcome(run_script: RunScript, tmp_path: Path) -> None:
    """Нечего проверять — ошибка входа, а не «прошло» (075)."""
    repo = prepare_repo(tmp_path)
    result = run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == BROKEN
    assert "изменений нет" in result.text


def test_explicit_base_is_not_rewritten_by_the_environment(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Переданная ключом база не переписывается переменной площадки.

    Гейт дописывал `origin/` ко ВСЯКОЙ базе, если в окружении была
    GITHUB_BASE_REF, — то есть молча подменял то, что имел в виду зовущий.
    Локально переменной нет, и расхождение вылезло только на площадке.
    """
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "без фрагмента")
    result = run_script(
        "check_journal.py", "--base", BASE_BRANCH, cwd=repo, env={"GITHUB_BASE_REF": "main"}
    )
    assert result.code == REJECTED, result.text
    assert "origin/" not in result.text


# --- разметка изменения ------------------------------------------------------


def write_event(
    tmp_path: Path, labels: list[str], body: str, title: str = "t", head: str = ""
) -> dict[str, str]:
    """Кладёт событие площадки об изменении и отдаёт окружение для гейта.

    Учётные данные площадки СНИМАЮТСЯ. В прогоне они в окружении есть, и гейт
    пошёл бы за настоящей задачей: набор стал бы зависеть от чужого состояния и
    от сети. Проверять надо решение гейта, а не доступность площадки — её
    проверяет транспорт у себя.
    """
    event = {
        "pull_request": {
            "labels": [{"name": name} for name in labels],
            "title": title,
            "body": body,
            "head": {"ref": head},
        }
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event), encoding="utf-8")
    return {
        "GITHUB_EVENT_PATH": str(path),
        "GH_TOKEN": "",
        "GITHUB_TOKEN": "",
        "GITHUB_REPOSITORY": "",
    }


def test_undeclared_label_is_rejected(run_script: RunScript, tmp_path: Path) -> None:
    """Метка вне состава отвергается: список разрешительный (068)."""
    env = write_event(tmp_path, ["area/docs", "выдуманная"], "Closes #1")
    result = run_script("check_pr_meta.py", "--files", "README.md", env=env)
    assert result.code == REJECTED
    assert "не объявляет" in result.text


def test_missing_zone_is_rejected(run_script: RunScript, tmp_path: Path) -> None:
    """Изменение без зоны не разобрано."""
    env = write_event(tmp_path, ["bug"], "Closes #1")
    result = run_script("check_pr_meta.py", "--files", "README.md", env=env)
    assert result.code == REJECTED
    assert "ни одна зона" in result.text


def test_zone_of_touched_files_is_required(run_script: RunScript, tmp_path: Path) -> None:
    """Зона выводится из путей состава, а не ставится на глазок."""
    env = write_event(tmp_path, ["area/docs"], "Closes #1")
    result = run_script("check_pr_meta.py", "--files", "scripts/x.py", env=env)
    assert result.code == REJECTED
    assert "area/gates" in result.text


def test_missing_task_link_is_rejected(run_script: RunScript, tmp_path: Path) -> None:
    """Без связи с задачей она не закроется при слиянии."""
    env = write_event(tmp_path, ["area/docs"], "просто текст")
    result = run_script("check_pr_meta.py", "--files", "README.md", env=env)
    assert result.code == REJECTED
    assert "связи с задачей" in result.text


def test_correct_meta_passes(run_script: RunScript, tmp_path: Path) -> None:
    """Верная разметка проходит."""
    env = write_event(tmp_path, ["area/docs", "documentation"], "Closes #8")
    assert run_script("check_pr_meta.py", "--files", "README.md", env=env).code == CLEAN


def test_a_skipped_checklist_check_says_so(run_script: RunScript, tmp_path: Path) -> None:
    """Без учётных данных полнота чек-листа не проверяется — и это сказано.

    Молчащий пропуск неотличим от «проверено и чисто» (045): читатель зелёного
    гейта решил бы, что задача закрывается правомерно, а её никто не смотрел.
    """
    env = write_event(tmp_path, ["area/docs", "documentation"], "Closes #8")
    result = run_script("check_pr_meta.py", "--files", "README.md", env=env)
    assert result.code == CLEAN
    assert "полнота чек-листа не проверена" in result.text


def test_no_event_is_third_outcome(run_script: RunScript, tmp_path: Path) -> None:
    """Нет события об изменении — предмет не найден, гейт не отработал."""
    result = run_script("check_pr_meta.py", env={"GITHUB_EVENT_PATH": ""})
    assert result.code == BROKEN
    assert "предмет проверки не найден" in result.text


# --- журнал: сборка ----------------------------------------------------------


def test_release_without_fragments_is_third_outcome(run_script: RunScript, tmp_path: Path) -> None:
    """Выпуск без единого фрагмента — ошибка входа, а не пустой выпуск."""
    (tmp_path / "CONTRACT_VERSION").write_text("9.9.0\n", encoding="utf-8")
    (tmp_path / "changelog.d").mkdir()
    result = run_script("build_changelog.py", "--release", "9.10.0", cwd=tmp_path)
    assert result.code == BROKEN
    assert "выпускать нечего" in result.text


def test_unnamed_fragment_is_third_outcome(run_script: RunScript, tmp_path: Path) -> None:
    """Фрагмент с неразбираемым именем не пропускается молча."""
    (tmp_path / "CONTRACT_VERSION").write_text("9.9.0\n", encoding="utf-8")
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "changelog.d" / "заметка.md").write_text("текст\n", encoding="utf-8")
    result = run_script("build_changelog.py", "--check", cwd=tmp_path)
    assert result.code == BROKEN
    assert "неразбираемым именем" in result.text


def test_fragment_with_the_link_on_top_is_third_outcome(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Ссылка на задачу не последней строкой — отказ, а не мелочь оформления.

    Конвенция была записана в README каталога фрагментов и держалась
    внимательностью: два фрагмента подряд поставили тег первой строкой, и
    сборка склеила их как есть. Правило без механизма — обещание (002).
    """
    (tmp_path / "CONTRACT_VERSION").write_text("9.9.0\n", encoding="utf-8")
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "changelog.d" / "1.added.md").write_text("#1\n\nтекст\n", encoding="utf-8")
    result = run_script("build_changelog.py", "--check", cwd=tmp_path)
    assert result.code == BROKEN
    assert "не последней строкой" in result.text


def test_fragment_may_name_two_tasks(run_script: RunScript, tmp_path: Path) -> None:
    """Одна работа бывает по двум задачам, и такая ссылка законна."""
    (tmp_path / "CONTRACT_VERSION").write_text("9.9.0\n", encoding="utf-8")
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "changelog.d" / "1.added.md").write_text("текст\n\n#1 #2\n", encoding="utf-8")
    assert run_script("build_changelog.py", cwd=tmp_path).code == CLEAN


def test_kinds_are_declared_once_for_all_mechanisms() -> None:
    """Гейт на дрейф: роды записи объявляет один модуль.

    Списки были копиями у сборки и у гейта изменения: достаточно добавить род
    в одном месте, чтобы второй перестал видеть законный фрагмент. Расходились
    бы они молча — как уже расходились состав меток и связь с задачей.
    """
    for name in ("build_changelog.py", "check_journal.py"):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "contract|" not in source and "|internal" not in source, (
            f"{name} объявляет роды своей копией"
        )


def with_fragment(repo: Path, name: str, body: str) -> None:
    """Кладёт в ветку изменения один фрагмент журнала."""
    git(repo, "checkout", "-qb", "work")
    (repo / "changelog.d").mkdir(exist_ok=True)
    (repo / "changelog.d" / name).write_text(body, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "фрагмент")


def test_fragments_are_checked_without_the_assembled_file(
    run_script: RunScript, tmp_path: Path
) -> None:
    """На изменении спрашивают фрагменты, а собранного файла может не быть.

    Сборка — дело выпуска (030): общий файл, который трогает каждая ветка,
    даёт конфликт на каждом втором изменении.
    """
    repo = prepare_repo(tmp_path)
    with_fragment(repo, "slug.added.md", "текст\n\n#1\n")
    result = run_script("build_changelog.py", "--fragments", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == CLEAN, result.text
    assert not (repo / "CHANGELOG.md").exists(), "проверка фрагментов собрала файл"


def test_fragments_check_refuses_a_broken_fragment(run_script: RunScript, tmp_path: Path) -> None:
    """Дефект фрагмента ловится на изменении, а не при выпуске."""
    repo = prepare_repo(tmp_path)
    with_fragment(repo, "заметка.md", "текст\n")
    result = run_script("build_changelog.py", "--fragments", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == BROKEN, result.text


def test_an_empty_catalogue_after_a_release_does_not_break_the_gate(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Пустой `changelog.d` после выпуска не роняет гейт на следующем изменении.

    Раньше шаг разбирал ВЕСЬ каталог и падал третьим исходом, стоило выпуску
    унести фрагменты в `released/`: изменение приносило свой фрагмент, а гейт
    смотрел не туда. Предмет проверки — то, что приезжает С ИЗМЕНЕНИЕМ.
    """
    repo = prepare_repo(tmp_path)
    with_fragment(repo, "after-a-release.added.md", "текст\n\n#1\n")
    result = run_script("build_changelog.py", "--fragments", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == CLEAN, result.text
    assert "фрагменты изменения разбираются: 1" in result.text


def test_a_neighbours_broken_fragment_is_not_this_change_s_problem(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Негодный фрагмент, лежавший в базе, не роняет чужое изменение.

    Гейт на изменении отвечает за то, что изменение принесло. Чужой дефект —
    предмет выпуска и того изменения, которое его завело.
    """
    repo = prepare_repo(tmp_path)
    (repo / "changelog.d").mkdir(exist_ok=True)
    (repo / "changelog.d" / "негодный.md").write_text("текст\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "негодный фрагмент в базе")
    with_fragment(repo, "moя-запись.added.md", "текст\n\n#1\n")
    result = run_script("build_changelog.py", "--fragments", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == CLEAN, result.text


def test_a_change_without_fragments_is_not_the_fragment_gate_s_problem(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Изменение без фрагментов гейт разбора не роняет — и говорит почему.

    Нужен ли фрагмент вообще, решает `check_journal.py`, и он же отвергает
    изменение без него. Краснеть здесь вторым разом значило бы завести второй
    источник того же решения (022). Ветка объявлена, поэтому она и прогоняется:
    объявив исход, механизм проходит по каждому (145).
    """
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "без фрагмента вовсе")
    result = run_script("build_changelog.py", "--fragments", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == CLEAN, result.text
    assert "не несёт фрагментов" in result.text


def test_the_run_does_not_assemble_the_journal_on_a_change() -> None:
    """Гейт на договор: прогон изменения не сверяет собранный журнал.

    Иначе правило 030 держалось бы внимательностью автора, а стоило бы это
    конфликта на каждом втором изменении.
    """
    # ПО ВСЕМУ КАТАЛОГУ: файл — адрес шага, а не его личность (168). Прибитая к
    # `ci.yml` проверка сломалась на выносе шага журнала в переиспользуемый
    # прогон — при том что сам шаг остался ровно тем же.
    gates = "\n".join(
        path.read_text(encoding="utf-8") for path in walk(ROOT / ".github" / "workflows", "*.yml")
    )
    assert "build_changelog.py --fragments" in gates
    assert "build_changelog.py --check" not in gates


def test_assembled_journal_matches_itself(run_script: RunScript, tmp_path: Path) -> None:
    """Собранный журнал совпадает со сборкой, а изменённый рукой — нет (125)."""
    (tmp_path / "CONTRACT_VERSION").write_text("9.9.0\n", encoding="utf-8")
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "changelog.d" / "1.added.md").write_text("новое\n\n#1\n", encoding="utf-8")
    assert run_script("build_changelog.py", cwd=tmp_path).code == CLEAN
    assert run_script("build_changelog.py", "--check", cwd=tmp_path).code == CLEAN

    journal = tmp_path / "CHANGELOG.md"
    journal.write_text(journal.read_text(encoding="utf-8") + "правка рукой\n", encoding="utf-8")
    result = run_script("build_changelog.py", "--check", cwd=tmp_path)
    assert result.code == REJECTED
    assert "расходится" in result.text


# --- открытие изменения ------------------------------------------------------


def test_branch_without_prefix_opens_nothing(run_script: RunScript) -> None:
    """Имя ветки — переключатель: без приставки изменение не открывается (003)."""
    result = run_script("agent_pr.py", "--repo", "o/r", "--branch", "fix/x", "--dry-run")
    assert result.code == CLEAN
    assert "без объявленной приставки" in result.text


def test_no_owner_token_is_not_configured(run_script: RunScript) -> None:
    """Нет токена владельца — «не настроено», и на токен прогона шаг не переходит.

    Спрашивается НЕ сухой прогон: у него предмет — дерево, на площадку он не
    ходит, и токен ему не нужен.
    """
    result = run_script(
        "agent_pr.py",
        "--repo",
        "o/r",
        "--branch",
        "agent/x",
        env={"MERGE_QUEUE_TOKEN": ""},
    )
    # Не единица: её отдаёт Python при необработанном сбое, и объявленным
    # состоянием она быть не может — иначе сломанный шаг читается как
    # работающий. Ровно это и случилось на прогоне: ImportError отдал единицу,
    # а прогон напечатал «секрет не задан» и остался зелёным.
    assert result.code == NOT_CONFIGURED
    assert result.code != REJECTED
    assert "не переходит намеренно" in result.text


def test_python_version_is_new_enough() -> None:
    """Скрипты пользуются синтаксисом, которого нет в старых версиях."""
    assert sys.version_info >= (3, 11)


def test_scripts_are_where_the_contract_says() -> None:
    """Каждый механизм лежит в scripts/ — договор называет его адресом."""
    expected = {
        "sync_labels.py",
        "build_changelog.py",
        "check_journal.py",
        "check_version.py",
        "check_pr_meta.py",
        "check_required_context.py",
        "ci_complete.py",
        "agent_pr.py",
    }
    assert expected <= {path.name for path in walk(ROOT / "scripts", "*.py")}


def test_zones_are_applied_even_when_the_change_is_already_open(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Зоны доставляются и на уже открытом изменении, а не только при создании.

    Иначе отказ на шаге разметки необратим: изменение открыто, следующий прогон
    уходит веткой «уже открыто» и выходит с нулём, ни разу не попытавшись
    доставить метки, — а гейт разметки продолжает его отвергать. Шаг обязан
    быть идемпотентным целиком, а не наполовину.
    """
    module = load_script("agent_pr.py")
    source = (ROOT / "scripts" / "agent_pr.py").read_text(encoding="utf-8")

    # Ветка «уже открыто» обязана звать доставку зон до своего возврата.
    already = source.index("изменение для ветки уже открыто")
    returns = source.index("return EXIT_OK", already)
    assert "apply_zones(" in source[already:returns], "ветка «уже открыто» не доставляет зоны"
    assert callable(module.apply_zones)


def test_the_journal_unfolds_a_bounded_number_of_releases(tmp_path: Path) -> None:
    """Собранный журнал разворачивает предел выпусков, а не все подряд.

    Источник не сокращается: запись лежит в каталоге выпуска целиком. Предел
    стоит у ПРЕДСТАВЛЕНИЯ — иначе файл растёт линейно по числу выпусков, и к
    сотому свежее ищут прокруткой (108).
    """
    module = load_script("build_changelog.py")
    released = tmp_path / "changelog.d" / "released"
    for minor in range(module.UNFOLDED_RELEASES + 3):
        directory = released / f"1.{minor}.0"
        directory.mkdir(parents=True)
        (directory / f"запись-{minor}.added.md").write_text("текст\n\n#1\n", encoding="utf-8")
    (tmp_path / "changelog.d" / "свежее.added.md").write_text("текст\n\n#2\n", encoding="utf-8")

    monkey = pytest.MonkeyPatch()
    try:
        monkey.chdir(tmp_path)
        monkey.setattr(module, "FRAGMENTS", Path("changelog.d"))
        monkey.setattr(module, "RELEASED", Path("changelog.d/released"))
        assembled = module.render("1.7.0")
    finally:
        monkey.undo()

    unfolded = [line for line in assembled.splitlines() if line.startswith("## 1.")]
    assert len(unfolded) == module.UNFOLDED_RELEASES, assembled
    assert "Выпуски раньше" in assembled, "свёрнутые выпуски оборваны молча"
    for minor in range(3):
        assert f"1.{minor}.0" in assembled, "свёрнутый выпуск не назван ссылкой"


def test_a_short_history_folds_nothing(tmp_path: Path) -> None:
    """Пока выпусков меньше предела, свёрнутого раздела нет вовсе.

    Раздел «раньше такой-то версии» на пустом месте объявлял бы предел там, где
    его ещё не достигли, — и читался бы как пропажа (075).
    """
    module = load_script("build_changelog.py")
    released = tmp_path / "changelog.d" / "released" / "1.0.0"
    released.mkdir(parents=True)
    (released / "запись.added.md").write_text("текст\n\n#1\n", encoding="utf-8")
    (tmp_path / "changelog.d" / "свежее.added.md").write_text("текст\n\n#2\n", encoding="utf-8")

    monkey = pytest.MonkeyPatch()
    try:
        monkey.chdir(tmp_path)
        monkey.setattr(module, "FRAGMENTS", Path("changelog.d"))
        monkey.setattr(module, "RELEASED", Path("changelog.d/released"))
        assembled = module.render("1.0.0")
    finally:
        monkey.undo()

    assert "Выпуски раньше" not in assembled, assembled


# --- частичное закрытие задачи -----------------------------------------------


def issue_with(body: str) -> dict[str, object]:
    """Задача площадки с заданным телом."""
    return {"body": body}


def test_closing_a_task_with_open_items_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Closes` при незакрытых пунктах чек-листа — красное (026, 128).

    Площадка умеет только полное закрытие: несделанные этапы уходят из списка
    открытых вместе с задачей, и туда больше никто не смотрит.
    """
    check = load_script("check_pr_meta.py")
    monkeypatch.setattr(
        check.ghrest,
        "request",
        lambda method, path, token, body=None: issue_with("- [x] первый\n- [ ] второй\n"),
    )
    links = check.changerefs.links_in("Closes #7")
    problems = check.premature("о/р", "токен", links, [])
    assert problems and "осталось незакрытых пунктов" in problems[0]


def test_an_item_closed_by_this_change_does_not_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пункт, названный закрытым в самом изменении, из счёта уходит.

    Иначе последний этап закрыть было бы нечем: отметить его до слияния негде,
    а после слияния задача уже закрыта.
    """
    check = load_script("check_pr_meta.py")
    monkeypatch.setattr(
        check.ghrest,
        "request",
        lambda method, path, token, body=None: issue_with("- [x] первый\n- [ ] второй\n"),
    )
    text = "Closes #7\nЗакрывает пункт: второй"
    problems = check.premature(
        "о/р",
        "токен",
        check.changerefs.links_in(text),
        [check.changerefs.normalise(item) for item in check.changerefs.closed_items_in(text)],
    )
    assert problems == []


def test_one_declared_item_is_marked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Один объявленный пункт отмечается в ОДНОЙ задаче — как в `items.mark`.

    `Closes #8` и `Closes #9`, в обеих открыт «второй», объявлен он один раз:
    `items.py` отметит его только в первой, и #9 закроется с неотмеченным
    пунктом. Гейт прогоняет ту же отметку и это видит (взгляд на #937).
    """
    check = load_script("check_pr_meta.py")
    monkeypatch.setattr(
        check.ghrest,
        "request",
        lambda method, path, token, body=None: issue_with("- [x] первый\n- [ ] второй\n"),
    )
    text = "Closes #8\nCloses #9\nЗакрывает пункт: второй"
    problems = check.premature("о/р", "токен", check.changerefs.links_in(text), ["второй"], [8, 9])
    assert len(problems) == 1 and problems[0].startswith("#9"), problems


def test_an_item_is_known_by_its_heading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пункт-абзац узнаётся по жирному заголовку — как в `items.marked`.

    Иначе гейт отверг бы то, что `items.py` отметит (взгляд на #937).
    """
    check = load_script("check_pr_meta.py")
    monkeypatch.setattr(
        check.ghrest,
        "request",
        lambda method, path, token, body=None: issue_with("- [ ] **1. Решения** — проза\n"),
    )
    links = check.changerefs.links_in("Closes #8")
    assert check.premature("о/р", "токен", links, ["1. Решения"], [8]) == []


def test_a_task_without_a_checklist_closes_freely(monkeypatch: pytest.MonkeyPatch) -> None:
    """Задача без чек-листа закрывается: отмечать в ней нечего.

    Требовать список там, где этап один, значило бы заводить ритуал (154).
    """
    check = load_script("check_pr_meta.py")
    monkeypatch.setattr(
        check.ghrest,
        "request",
        lambda method, path, token, body=None: issue_with("Просто описание без списка."),
    )
    assert check.premature("о/р", "токен", check.changerefs.links_in("Closes #7"), []) == []


def test_a_partial_link_is_not_checked_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Refs` ничего не закрывает, и спрашивать с него полноту нечего."""
    check = load_script("check_pr_meta.py")

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("частичная связь не должна читать задачу")

    monkeypatch.setattr(check.ghrest, "request", refuse)
    assert check.premature("о/р", "токен", check.changerefs.links_in("Refs #7"), []) == []


def test_an_unreadable_task_is_a_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Задача не прочитана — объявленный третий исход, а не трассировка.

    Необработанное исключение отдаёт единицу, а единица здесь значит
    «изменение отвергнуто»: сломанный гейт читался бы как сработавший (039).
    """
    check = load_script("check_pr_meta.py")

    def refuse(*args: object, **kwargs: object) -> None:
        raise check.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(check.ghrest, "request", refuse)
    with pytest.raises(check.NotRun):
        check.premature("о/р", "токен", check.changerefs.links_in("Closes #7"), [])


def test_findings_survive_an_unreadable_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Найденное до отказа не пропадает вместе с отказом.

    Метки и связь разобраны, и находки по ним верны независимо от того,
    прочиталась ли задача. Выбросить их молча значит отдать автору «проверка не
    отработала» там, где у него настоящий дефект разметки: он починит
    недоступность площадки, а не свою метку.
    """
    check = load_script("check_pr_meta.py")
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "pull_request": {
                    "number": 7,
                    "labels": [{"name": "area/docs"}, {"name": "выдуманная"}],
                    "title": "t",
                    "body": "Closes #8",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "о/р")
    monkeypatch.setenv("GH_TOKEN", "токен")

    def refuse(*args: object, **kwargs: object) -> None:
        raise check.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(check.ghrest, "request", refuse)
    monkeypatch.setattr(check, "fresh", lambda pull, repo, token: pull)

    assert check.main(["--files", "README.md"]) == BROKEN
    printed = capsys.readouterr().err
    assert "не отработала" in printed
    assert "выдуманная" in printed, "находка разметки исчезла вместе с отказом"


@pytest.mark.parametrize(
    ("body", "message", "rewritten", "verdict"),
    [
        # Случай #927: тело ещё старое, строка пункта уже в коммите. Связь в
        # коммите есть всегда: без неё `agent_pr` изменение не откроет.
        ("Closes #8", "тема\n\nCloses #8\nЗакрывает пункт: второй\n", True, CLEAN),
        # Та же гонка со связью: тело без неё, коммит её несёт.
        ("", "тема\n\nCloses #8\nЗакрывает пункт: второй\n", True, CLEAN),
        # Путь человека: пункт закрыт правкой тела, коммиты молчат.
        ("Closes #8\nЗакрывает пункт: второй", "тема\n", False, CLEAN),
        # Вторая половина: пункт не закрыт нигде — отказ, а не «сошлось».
        ("Closes #8", "тема\n", True, REJECTED),
        # Тело пишет человек: пункт из коммита в него не доедет, и `items.py`
        # его не отметит — засчитывать нельзя (взгляд на #935).
        ("Closes #8", "тема\n\nЗакрывает пункт: второй\n", False, REJECTED),
        # Тело пишет `agent_pr`: нынешнее он ЗАМЕНИТ, и пункт, которого нет в
        # коммитах, из устаревшего тела не засчитывается (взгляд на #936).
        ("Closes #8\nЗакрывает пункт: второй", "тема\n\nCloses #8\n", True, REJECTED),
        # Тело человека называет пункт, а задачу — только коммит: `items.py`
        # отмечает пункты лишь в задачах из тела (взгляд на #937).
        ("Закрывает пункт: второй", "тема\n\nCloses #8\n", False, REJECTED),
    ],
)
def test_links_and_closed_items_are_read_from_commits_too(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    message: str,
    rewritten: bool,
    verdict: int,
    title: str = "t",
) -> None:
    """Вердикт не зависит от того, успел ли `agent-pr` дописать тело (#929).

    Тело дописывается токеном прогона после толчка, и нового захода проверок
    это не запускает: гейт, читавший одно тело, отверг #927 за пункт, который
    строка коммита уже закрыла. Пункт из коммита засчитывается там, где тело
    допишет `agent_pr`: отмечает пункты `items.py` только по телу.
    """
    check = load_script("check_pr_meta.py")
    agent_pr = load_script("agent_pr.py")
    head = "agent/x" if rewritten else "feature/x"
    body = f"{body}\n\n{agent_pr.MARK}" if rewritten else body
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "pull_request": {
                    "number": 7,
                    "labels": [{"name": "area/docs"}],
                    "title": title,
                    "body": body,
                    "head": {"ref": head},
                }
            }
        ),
        encoding="utf-8",
    )
    messages = tmp_path / "messages.txt"
    messages.write_bytes(f"{message}\0".encode())
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "о/р")
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(
        check.ghrest,
        "request",
        lambda method, path, token, body=None: issue_with("- [x] первый\n- [ ] второй\n"),
    )
    monkeypatch.setattr(check, "fresh", lambda pull, repo, token: pull)
    said = ["--files", "README.md", "--messages-from", str(messages)]
    assert check.main(said) == verdict


def test_a_closed_item_in_the_title_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пункт в заголовке не засчитывается: `items.py` читает только описание.

    Строка «Закрывает пункт» в заголовке засчиталась бы, но не отметилась бы
    никем — задача закрылась бы с неотмеченным пунктом (взгляд на #936).
    """
    test_links_and_closed_items_are_read_from_commits_too(
        tmp_path,
        monkeypatch,
        "Closes #8",
        "тема\n",
        False,
        REJECTED,
        title="Закрывает пункт: второй",
    )


def test_the_version_gate_sees_a_file_not_yet_committed(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Гейт версии видит файл, ещё не внесённый в учёт.

    ЗАМЕР 10.09.2026. Гейт смотрел только `git ls-files` — то есть внесённое, —
    и пропускал ровно тот файл, который окно пишет прямо сейчас. Новый тест с
    примером версии прошёл свой прогон перед толчком зелёным и покраснел на
    площадке сразу после коммита: гейт, не видящий предмета в момент проверки,
    зелен на том, чего не смотрел (075).
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "CONTRACT_VERSION").write_text("9.9.0\n", encoding="utf-8")
    (tmp_path / "свежий.md").write_text("версия 9.9.0 вписана руками\n", encoding="utf-8")
    run = run_script("check_version.py", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "свежий.md" in run.text


@contextmanager
def inside(root: Path) -> Iterator[None]:
    """Работает в чужом дереве и возвращается назад: разбор зовёт git в cwd."""
    was = Path.cwd()
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(was)


def branch_with(root: Path, message: str) -> Path:
    """Дерево с общей веткой и веткой работы, несущей один коммит."""
    run = partial(subprocess.run, cwd=root, check=True, capture_output=True)
    run(["git", "init", "--quiet", "-b", "main"])
    (root / "readme.md").write_text("начало\n", encoding="utf-8")
    run(["git", "add", "-A"])
    run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "начало"])
    run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"])
    run(["git", "checkout", "--quiet", "-b", "agent/x"])
    (root / "readme.md").write_text("работа\n", encoding="utf-8")
    run(["git", "add", "-A"])
    run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", message])
    return root


def test_a_dry_run_refuses_a_branch_without_a_task(tmp_path: Path) -> None:
    """Сухой прогон краснеет на ветке без связи с задачей — до толчка.

    Ровно этого не хватало 10.09.2026: три ветки подряд ушли на площадку без
    строки `Refs #N`, `agent-pr` отказался открывать изменение, и узналось это
    по ОТСУТСТВИЮ изменения, а не по красному. Гейт проверяется тем, что он
    обязан отвергнуть (140).
    """
    agent_pr = load_script("agent_pr.py")
    root = branch_with(tmp_path, "feat: работа без связи")
    with inside(root), pytest.raises(agent_pr.NotRun) as caught:
        agent_pr.describe("agent/x", "main")
    assert "задачу" in str(caught.value)


def test_a_dry_run_accepts_a_branch_that_names_its_task(tmp_path: Path) -> None:
    """Связь названа — сухой прогон её принимает, и красное не ложное."""
    agent_pr = load_script("agent_pr.py")
    root = branch_with(tmp_path, "feat: работа со связью\n\nRefs #1")
    with inside(root):
        title = agent_pr.describe("agent/x", "main").title
    assert "работа со связью" in title


# --- реестр: у КАЖДОГО гейта есть прогон отказа -------------------------------


#: Гейты дерева узнаются по приставке имени — это соглашение самого проекта, и
#: второй список того же разошёлся бы с ним молча (022). Граница названа: шаги,
#: не начинающиеся с `check_`, сюда не попадают, и если такой появится, его
#: придётся внести — молча он не пройдёт (068).
GATES = sorted(path.name for path in walk(ROOT / "scripts", "check_*.py"))

#: Как в этом дереве выражается ОТКАЗ гейта. Список разрешительный: новое имя
#: исхода дописывается сюда, а не проходит само.
REFUSAL_NAMES = (
    "EXIT_REJECTED",
    "EXIT_FOUND",
    "EXIT_FINDINGS",
    "EXIT_MISMATCH",
    "REJECTED",
    # Отказ гейта воскрешения назван по тому, ЧТО случится от толчка, а не по
    # слову «отказ»: сообщение об этом и говорит («толчок воскресит ветку»).
    "EXIT_REVIVED",
    # Тем же приёмом назван исход предупреждения о тишине взгляда: правка файла
    # прогона ГЛУШИТ агента на этой голове. Толчок он не держит — правка такого
    # файла законна, — но исход у него не нулевой, и прогон его отказа нужен
    # ровно так же (051).
    "EXIT_SILENCED",
)


def refusal_of(gate: str) -> set[int]:
    """Какими числами ЭТОТ гейт объявляет отказ — по его собственным константам.

    СПРАШИВАЕТСЯ У ГЕЙТА, А НЕ НАЗНАЧАЕТСЯ СПИСКОМ. Отказ не всегда единица:
    у `check_pipeline` и `check_required_context` находка объявлена исходом 3,
    и требовать от них единицы значило бы требовать невозможного, а потом
    «чинить» исправное. Замер 13.09.2026: из пяти гейтов, которые реестр назвал
    непокрытыми, два были покрыты своим объявленным исходом
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    """
    return {code for name, code in outcomes.declared(gate).items() if name in REFUSAL_NAMES}


def gates_with_a_refusal_run() -> set[str]:
    """Гейты, у которых в наборе есть прогон ИХ отказа.

    ЧИТАЕТСЯ МОДУЛЬ ЦЕЛИКОМ, И ПРЕДЕЛ ЭТОГО НАЗВАН. Гейт нередко запускают
    вспомогательной функцией модуля, а не прямо в случае, и разбор по
    отдельным случаям такие прогоны терял: замер дал восемь «непокрытых», из
    которых шесть были покрыты через помощника. Поэтому предметом считается
    модуль — запускает гейт и утверждает его отказ.

    Цена известна: модуль, запускающий ДВА гейта и отвергающий одним из них,
    засчитает оба. Реестр ловит не это, а другое — гейт, у которого прогона
    отказа нет НИГДЕ, — и притворяться, что он ловит больше, было бы хуже
    неполноты
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
    """
    found: set[str] = set()
    for path in walk(ROOT / "tests", "test_*.py"):
        tree = outcomes.tree_of(path)
        numbers, names = outcomes.asserted(tree)
        for gate in outcomes.started_by(tree):
            if gate not in GATES:
                continue
            said = outcomes.declared(gate)
            wanted = refusal_of(gate)
            hit = numbers | {said[name] for name in names if name in said}
            if hit & wanted:
                found.add(gate)
    return found


def gates_without_a_known_refusal() -> list[str]:
    """Гейты, чьё имя отказа росписи незнакомо.

    ПОЧЕМУ ЭТО ОТДЕЛЬНАЯ НАХОДКА, А НЕ ТИХИЙ ПРОПУСК. Раньше такой гейт
    считался покрытым: `not wanted` читалось как «отказа у него нет, значит и
    спрашивать нечего». На деле отказ был, только назывался иначе —
    `check_env.py` объявляет `EXIT_MISMATCH`, и реестр зеленел на нём вслепую,
    ни одного прогона не найдя. Разрешительный список пополняется ОСОЗНАННО, а
    не обходится молчанием
    ([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)).
    Нашёл внешний взгляд на #282.
    """
    return [gate for gate in GATES if not refusal_of(gate)]


def test_every_gate_has_a_run_of_its_refusal() -> None:
    """У каждого гейта дерева есть прогон того, что он обязан отвергнуть (140).

    Отдельные случаи отказа в наборе были и раньше — их полсотни. Чего не было:
    РЕЕСТРА. Новый гейт, приехавший без прогона отказа, не замечал никто:
    порядок работы окна держал это вниманием автора, а внимание — не механизм
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

    Замер 13.09.2026, и чисел в нём ДВА — они о разных моментах, а не спорят.
    Первый заход назвал непокрытыми **четыре** гейта из тринадцати; проверка
    премисы сняла два из них — у `check_pipeline` и `check_required_context`
    отказ объявлен исходом 3, и требовать от них единицы значило бы «чинить»
    исправное (044). Осталось **два**: `check_derived_refs.py` и
    `check_reread.py`, причём второй написан в ту же смену и ровно с этим
    упрёком в шапке. Запись журнала называет первое число, эта строка —
    второе; расхождение нашёл внешний взгляд на #282.
    """
    unknown = gates_without_a_known_refusal()
    assert not unknown, (
        "росписи незнакомо имя отказа у: " + ", ".join(unknown) + " — такой гейт "
        "считался бы покрытым, не имея ни одного прогона отказа. Внесите имя в "
        "REFUSAL_NAMES осознанно (068)"
    )
    missing = sorted(set(GATES) - gates_with_a_refusal_run())
    assert not missing, (
        "гейты без прогона отказа: " + ", ".join(missing) + " — гейт, проверенный "
        "только пропуском верного, зелен всегда и не держит ничего"
    )


def test_the_roster_finds_its_subject() -> None:
    """Предмет реестра найден: гейты в дереве ЕСТЬ, и прогоны отказа у них тоже.

    Без этого соседняя проверка зеленела бы на пустом списке — «все гейты
    покрыты» верно и тогда, когда гейтов не нашлось
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    assert GATES, "гейтов в дереве не найдено — разбор не находит предмета"
    assert gates_with_a_refusal_run(), "прогонов отказа не найдено ни одного — разбор слеп"


def journal_change(tmp_path: Path, *, fragment: str, message: str) -> Path:
    """Дерево с правкой кода, фрагментом журнала и заданным телом коммита.

    Форма у трёх проверок ниже одна, и разводит их ровно две строки — текст
    фрагмента и текст коммита. Поднято вверх, а не повторено трижды (090).
    """
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "changelog.d").mkdir()
    (repo / "changelog.d" / "fix-a-thing.fixed.md").write_text(fragment, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return repo


#: Фрагмент, объявляющий находку разобранной.
SAYS_RESOLVED = "что-то починено\n\nРазобрано: abc1234\n\n#7\n"


def test_a_resolution_left_in_the_journal_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Отметка снятия во фрагменте и не в коммите — отказ.

    СНЯТИЕ ЕДЕТ ТЕЛОМ КОММИТА. Уборка реестра читает тело слитого ИЗМЕНЕНИЯ, а
    его собирает `agent_pr` из тел коммитов; фрагмент журнала в эту цепочку не
    входит вовсе. Отметка, написанная только во фрагменте, адресату не
    доезжает: работа сделана, находка в реестре осталась, и снять её больше
    нечем.

    ЗАМЕР 17.09.2026: так потерялись ДВАДЦАТЬ ТРИ снятия за одну смену — семь
    изменений подряд. Причина не в забывчивости: навык разбора находки говорил
    «снять строкой в ТЕЛЕ ИЗМЕНЕНИЯ», а тело изменения окно писать не вправе
    ([131](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/131-no-writes-from-a-cloud-session.md))
    — назван был адрес, которого у окна нет, и окно выбрало похожий.
    """
    repo = journal_change(tmp_path, fragment=SAYS_RESOLVED, message="починка без отметки в коммите")
    result = run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == REJECTED
    assert "abc1234" in result.text and "ТЕЛЕ КОММИТА" in result.text


def test_a_resolution_carried_by_the_commit_passes(run_script: RunScript, tmp_path: Path) -> None:
    """Та же отметка в теле коммита — проходит: снятие уехало с работой."""
    repo = journal_change(tmp_path, fragment=SAYS_RESOLVED, message="починка\n\nРазобрано: abc1234")
    assert run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo).code == CLEAN


def test_a_fragment_without_resolutions_is_asked_nothing(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Фрагмент без отметок ничего не требует: судится ЗАЯВЛЕННОЕ.

    Требовать отметку у каждого изменения значило бы красить работу, которая
    находок не разбирала вовсе (051).
    """
    repo = journal_change(
        tmp_path, fragment="что-то починено\n\n#7\n", message="починка без снятий"
    )
    assert run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo).code == CLEAN


def test_the_common_ancestor_is_asked_of_git_and_refuses_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Общий предок спрашивается у git, а его отсутствие — третий исход.

    Точка сравнения объявлена отдельным именем ради того, чтобы читатели брали
    ОДНУ: вершина базы движется, пока изменение открыто. Пустой ответ здесь
    значит «сравнивать не с чем», и молчаливое «ну ладно» подставило бы пустую
    ссылку во все последующие вызовы (045).
    """
    journal = load_script("journal.py")
    asked: list[list[str]] = []

    def remembering(args: list[str]) -> str:
        asked.append(args)
        return "деадбиф\n"

    monkeypatch.setattr(journal, "git", remembering)
    assert journal.common_ancestor("origin/main") == "деадбиф"
    assert asked == [["git", "merge-base", "origin/main", "HEAD"]]

    monkeypatch.setattr(journal, "git", lambda args: "   \n")
    with pytest.raises(journal.NotRun):
        journal.common_ancestor("origin/main")


def test_a_given_ancestor_is_not_asked_of_git_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Готовая точка сравнения принимается, а не переспрашивается.

    Зовущему, которому предок нужен и самому, незачем платить вторым вызовом
    `git merge-base`. И дело не только в вызове: между двумя вопросами общая
    ветка может сдвинуться, и два читателя ОДНОГО захода получат разные точки
    (нашёл внешний взгляд на #445).
    """
    journal = load_script("journal.py")
    asked: list[list[str]] = []

    def remembering(args: list[str]) -> str:
        asked.append(args)
        return "путь\0"

    monkeypatch.setattr(journal, "git", remembering)
    journal.changed_files("origin/main", ancestor="деадбиф")
    assert not any("merge-base" in args for args in asked), (
        f"предок спрошен заново при готовом: {asked}"
    )
    assert any("деадбиф...HEAD" in args for args in asked), (
        f"переданный предок не использован: {asked}"
    )


def test_without_a_given_ancestor_git_is_still_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вторая половина: без готового предка он по-прежнему спрашивается.

    Без неё послабление сняло бы точку сравнения вовсе — и отбор пошёл бы от
    пустой ссылки (051).
    """
    journal = load_script("journal.py")
    asked: list[list[str]] = []

    def remembering(args: list[str]) -> str:
        asked.append(args)
        return "деадбиф\n" if "merge-base" in args else "путь\0"

    monkeypatch.setattr(journal, "git", remembering)
    journal.changed_files("origin/main")
    assert any("merge-base" in args for args in asked), "предок не спрошен вовсе"


def test_a_change_that_touches_the_built_journal_is_rejected(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Изменение, тронувшее собранный `CHANGELOG.md`, отвергается (030).

    Собранный журнал производный: его пересобирает ВЫПУСК. Общий файл, который
    правит каждая ветка, даёт конфликт на каждом втором изменении — ровно тот
    инцидент, из-за которого фрагменты и заведены.

    Замер 21.09.2026 по 90 коммитам общей ветки: `CHANGELOG.md` тронут в
    шестнадцати — один раз коммитом выпуска (он идёт мимо изменений) и
    пятнадцать раз изменениями одного окна за две смены. Прежде гейт держал
    этот файл в СПИСКЕ ОСВОБОЖДЁННЫХ, то есть разрешал ровно запрещённое.
    """
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "CHANGELOG.md").write_text("# Журнал\n\nсобрано рукой\n", encoding="utf-8")
    (repo / "changelog.d").mkdir(exist_ok=True)
    (repo / "changelog.d" / "the-journal-is-built-by-the-release.added.md").write_text(
        "запись\n\n#7\n", encoding="utf-8"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "собрал журнал руками")
    result = run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo)
    assert result.code == REJECTED
    assert "CHANGELOG.md" in result.text
    assert "выпуск" in result.text.lower(), result.text


def test_a_fragment_alone_still_passes(run_script: RunScript, tmp_path: Path) -> None:
    """Вторая половина: фрагмент без собранного журнала проходит.

    Без неё отказ был бы неотличим от «журнал трогать нельзя никак», и окно
    перестало бы класть фрагменты — то есть гейт сломал бы то, что защищает
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    """
    repo = prepare_repo(tmp_path)
    git(repo, "checkout", "-qb", "work")
    (repo / "code.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "changelog.d").mkdir(exist_ok=True)
    (repo / "changelog.d" / "only-a-fragment-travels.added.md").write_text(
        "запись\n\n#7\n", encoding="utf-8"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "только фрагмент")
    assert run_script("check_journal.py", "--base", BASE_BRANCH, cwd=repo).code == CLEAN


def test_a_stray_closing_word_is_rejected(run_script: RunScript, tmp_path: Path) -> None:
    """Слово закрытия с номером вне строки связи отвергается — в сообщениях (#928).

    Площадка закрыла бы задачу при слиянии: так #925 закрыло #922 пояснением
    строки «Разобрано». Соседняя половина — строка связи в сообщении проходит.
    """
    check = load_script("check_pr_meta.py")
    env = write_event(tmp_path, ["area/docs"], "Refs #1")
    bad = tmp_path / "bad.txt"
    bad.write_bytes("тема\n\nРазобрано: 13cf07f — `Closes #922` не пройдёт\n\0".encode())
    result = run_script(
        "check_pr_meta.py", "--files", "README.md", "--messages-from", str(bad), env=env
    )
    assert result.code == REJECTED
    assert check.STRAY_CLOSING in result.text
    good = tmp_path / "good.txt"
    good.write_bytes("тема\n\nCloses #1\nРазобрано: 13cf07f — ответ переписан\n\0".encode())
    result = run_script(
        "check_pr_meta.py", "--files", "README.md", "--messages-from", str(good), env=env
    )
    assert check.STRAY_CLOSING not in result.text


def agent_event(tmp_path: Path) -> dict[str, str]:
    """Изменение, описание которого пишет `agent_pr`: его ветка и его отметка."""
    agent_pr = load_script("agent_pr.py")
    return write_event(tmp_path, ["area/docs"], f"Refs #1\n\n{agent_pr.MARK}", head="agent/x")


@pytest.mark.parametrize(
    ("message", "caught"),
    [
        # Заголовок коммита едет в тело слияния строкой списка.
        ("Fixes #5 в гейте\n", True),
        # Первый абзац git склеивает в один заголовок — слово во второй его
        # строке едет в тело слияния (взгляд на #933).
        ("Починка гейта\nfixes #5\n\nтело\n", True),
        # Строки, которые `agent_pr` переносит в ОПИСАНИЕ после прогона гейта:
        # площадка прочтёт их при слиянии (взгляд на #933).
        ("тема\n\nRefs #1\nЗакрывает пункт: отказ, который fixes #5\n", True),
        ("тема\n\nRefs #1\nЖдёт: пока resolves #7 не выйдет\n", True),
        # Проза тела коммита в общую ветку не едет — судить её нечего.
        ("тема\n\nКогда-то это fixes #5, но строка остаётся в ветке.\n", False),
    ],
)
def test_only_what_lands_is_judged(
    run_script: RunScript, tmp_path: Path, message: str, caught: bool
) -> None:
    """Из коммитов судится только отобранное `squash_body.compose_from`.

    Иначе слово в прозе, которая никуда не доедет, требовало бы переписать
    историю ветки — отказ без вреда, который он предотвращает.
    """
    check = load_script("check_pr_meta.py")
    env = agent_event(tmp_path)
    said = tmp_path / "messages.txt"
    said.write_bytes(f"{message}\0".encode())
    result = run_script(
        "check_pr_meta.py", "--files", "README.md", "--messages-from", str(said), env=env
    )
    assert (check.STRAY_CLOSING in result.text) is caught, result.text


def test_the_first_commits_hold_is_judged(run_script: RunScript, tmp_path: Path) -> None:
    """Задержка, которую перенесёт `agent_pr`, — первого коммита, и её судят.

    Сообщения идут от старых к новым; слово закрытия в «Ждёт:» старого коммита
    уедет в описание, и гейт обязан увидеть именно его (взгляд на #934).
    """
    check = load_script("check_pr_meta.py")
    env = agent_event(tmp_path)
    said = tmp_path / "messages.txt"
    older = "старый\n\nRefs #1\nЖдёт: пока fixes #5 не выйдет\n"
    newer = "новый\n\nЖдёт: #9\n"
    said.write_bytes(f"{older}\0{newer}\0".encode())
    result = run_script(
        "check_pr_meta.py", "--files", "README.md", "--messages-from", str(said), env=env
    )
    assert result.code == REJECTED
    assert check.STRAY_CLOSING in result.text


@pytest.mark.parametrize(
    ("body", "head"),
    [
        # Описание писал человек: `agent_pr` его не перепишет.
        ("Refs #1", "agent/x"),
        # Ветка не `agent/`: `agent_pr` её не открывает вовсе.
        ("Refs #1\n\n{mark}", "feature/x"),
    ],
)
def test_a_description_nobody_rewrites_is_not_judged_ahead(
    run_script: RunScript, tmp_path: Path, body: str, head: str
) -> None:
    """Будущее описание судится только там, где `agent_pr` его допишет.

    Иначе строка из коммита, которая никуда не доедет, отвергала бы изменение
    человека (взгляд на #934). Соседняя половина — `test_only_what_lands_is_judged`.
    """
    check = load_script("check_pr_meta.py")
    agent_pr = load_script("agent_pr.py")
    env = write_event(tmp_path, ["area/docs"], body.format(mark=agent_pr.MARK), head=head)
    said = tmp_path / "messages.txt"
    said.write_bytes("тема\n\nRefs #1\nЖдёт: пока fixes #5 не выйдет\n\0".encode())
    result = run_script(
        "check_pr_meta.py", "--files", "README.md", "--messages-from", str(said), env=env
    )
    assert check.STRAY_CLOSING not in result.text, result.text


def test_the_step_hands_the_messages_to_the_gate() -> None:
    """Прогон передаёт гейту сообщения коммитов — иначе проверка выключена молча.

    Без `--messages-from` гейт пишет MESSAGES_UNREAD в журнал прогона и
    пропускает изменение: зелёный прогон неотличим от проверенного (045).
    """
    step = (ROOT / ".github" / "workflows" / "step-pr-meta.yml").read_text(encoding="utf-8")
    gate = next(line for line in step.splitlines() if "check_pr_meta.py" in line)
    source = gate.split("--messages-from", 1)[1].split()[0] if "--messages-from" in gate else ""
    assert source, "прогон зовёт гейт без --messages-from"
    writer = next((line for line in step.splitlines() if f"> {source}" in line), "")
    assert writer, f"{source}: прогон не пишет файл, который передаёт"
    # От старых к новым, как читают `agent_pr` и `squash_body` (взгляд на #934).
    assert "--reverse" in writer, "сообщения переданы от новых к старым"


@pytest.mark.parametrize(
    ("title", "body"),
    [
        # Заголовок становится заголовком коммита слияния (`automerge.py`).
        ("Fixes #5 в гейте", "Refs #1"),
        # Заголовок судится БЕЗ исключения строки связи: `Fixes #5 (#N)` в
        # заголовке коммита слияния закроет #5, даже если описание молчит.
        ("Fixes #5", "Refs #1"),
        # Описание площадка читает целиком, не только строку связи.
        ("t", "Refs #1\n\nЗаодно это resolves #5."),
    ],
)
def test_a_stray_closing_word_in_the_change_is_rejected(
    run_script: RunScript, tmp_path: Path, title: str, body: str
) -> None:
    """Заголовок и описание изменения судятся тем же правилом, что сообщения (#928)."""
    check = load_script("check_pr_meta.py")
    env = write_event(tmp_path, ["area/docs"], body, title=title)
    result = run_script("check_pr_meta.py", "--files", "README.md", env=env)
    assert result.code == REJECTED
    assert check.STRAY_CLOSING in result.text


def test_messages_are_read_whole_and_their_absence_is_said(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Сообщения коммитов читаются все, а без файла пропуск назван (045)."""
    check = load_script("check_pr_meta.py")
    said = tmp_path / "messages.txt"
    said.write_bytes("первый\n\0второй\n\0".encode())
    assert check.read_messages(str(said)) == ["первый\n", "второй\n"]
    assert check.read_messages("") == []
    assert check.MESSAGES_UNREAD in capsys.readouterr().err
