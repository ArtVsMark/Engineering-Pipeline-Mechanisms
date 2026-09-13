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
from tests.conftest import ROOT, RunScript, load_script

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
    assert "нет источника версии" in result.text


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
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "pipeline.md").write_text("текст\n", encoding="utf-8")
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


def write_event(tmp_path: Path, labels: list[str], body: str) -> dict[str, str]:
    """Кладёт событие площадки об изменении и отдаёт окружение для гейта.

    Учётные данные площадки СНИМАЮТСЯ. В прогоне они в окружении есть, и гейт
    пошёл бы за настоящей задачей: набор стал бы зависеть от чужого состояния и
    от сети. Проверять надо решение гейта, а не доступность площадки — её
    проверяет транспорт у себя.
    """
    event = {
        "pull_request": {"labels": [{"name": name} for name in labels], "title": "t", "body": body}
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
    gates = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
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
    assert expected <= {path.name for path in (ROOT / "scripts").glob("*.py")}


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
        title, _ = agent_pr.describe("agent/x", "main")
    assert "работа со связью" in title


# --- реестр: у КАЖДОГО гейта есть прогон отказа -------------------------------


#: Гейты дерева узнаются по приставке имени — это соглашение самого проекта, и
#: второй список того же разошёлся бы с ним молча (022). Граница названа: шаги,
#: не начинающиеся с `check_`, сюда не попадают, и если такой появится, его
#: придётся внести — молча он не пройдёт (068).
GATES = sorted(path.name for path in (ROOT / "scripts").glob("check_*.py"))

#: Как в этом дереве выражается ОТКАЗ гейта. Список разрешительный: новое имя
#: исхода дописывается сюда, а не проходит само.
REFUSAL_NAMES = ("EXIT_REJECTED", "EXIT_FOUND", "EXIT_FINDINGS", "REJECTED")


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
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = outcomes.tree_of(path)
        numbers, names = outcomes.asserted(tree)
        for gate in outcomes.started_by(tree):
            if gate not in GATES:
                continue
            said = outcomes.declared(gate)
            wanted = refusal_of(gate)
            hit = numbers | {said[name] for name in names if name in said}
            if not wanted or hit & wanted:
                found.add(gate)
    return found


def test_every_gate_has_a_run_of_its_refusal() -> None:
    """У каждого гейта дерева есть прогон того, что он обязан отвергнуть (140).

    Отдельные случаи отказа в наборе были и раньше — их полсотни. Чего не было:
    РЕЕСТРА. Новый гейт, приехавший без прогона отказа, не замечал никто:
    порядок работы окна держал это вниманием автора, а внимание — не механизм
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

    Замер 13.09.2026, первый же заход: из тринадцати гейтов **два** проверялись
    только чистыми функциями, а по пути отказа не прогонялись ни разу —
    `check_derived_refs.py` и `check_reread.py`, причём второй написан в ту же
    смену и ровно с этим упрёком в шапке.
    """
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
