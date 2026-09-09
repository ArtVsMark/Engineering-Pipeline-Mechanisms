"""Каждый гейт проверяется тем, что он обязан отвергнуть (правило 140).

Проверка того, что гейт пропускает верное, доказывает только половину: гейт,
который не отвергает ничего, зелёный всегда и не держит ничего. Поэтому здесь
прогоняется каждый объявленный исход (145), включая третий — «не отработал».
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import ROOT, RunScript, load_script

BROKEN = 2
REJECTED = 1
CLEAN = 0
#: Объявленное состояние «не настроено»: намеренно не единица.
NOT_CONFIGURED = 3


def git(cwd: Path, *args: str) -> None:
    """Зовёт git в подготовленном репозитории теста."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


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
    (repo / "changelog.d" / "7.added.md").write_text("что-то новое\n\n#7\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "с фрагментом")
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
    """Кладёт событие площадки об изменении и отдаёт окружение для гейта."""
    event = {
        "pull_request": {"labels": [{"name": name} for name in labels], "title": "t", "body": body}
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event), encoding="utf-8")
    return {"GITHUB_EVENT_PATH": str(path)}


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


def test_no_event_is_third_outcome(run_script: RunScript, tmp_path: Path) -> None:
    """Нет события об изменении — предмет не найден, гейт не отработал."""
    result = run_script("check_pr_meta.py", env={"GITHUB_EVENT_PATH": ""})
    assert result.code == BROKEN
    assert "предмет проверки не найден" in result.text


# --- журнал: сборка ----------------------------------------------------------


def test_release_without_fragments_is_third_outcome(run_script: RunScript, tmp_path: Path) -> None:
    """Выпуск без единого фрагмента — ошибка входа, а не пустой выпуск."""
    (tmp_path / "CONTRACT_VERSION").write_text("0.1.0\n", encoding="utf-8")
    (tmp_path / "changelog.d").mkdir()
    result = run_script("build_changelog.py", "--release", "0.2.0", cwd=tmp_path)
    assert result.code == BROKEN
    assert "выпускать нечего" in result.text


def test_unnamed_fragment_is_third_outcome(run_script: RunScript, tmp_path: Path) -> None:
    """Фрагмент с неразбираемым именем не пропускается молча."""
    (tmp_path / "CONTRACT_VERSION").write_text("0.1.0\n", encoding="utf-8")
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
    (tmp_path / "CONTRACT_VERSION").write_text("0.1.0\n", encoding="utf-8")
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "changelog.d" / "1.added.md").write_text("#1\n\nтекст\n", encoding="utf-8")
    result = run_script("build_changelog.py", "--check", cwd=tmp_path)
    assert result.code == BROKEN
    assert "не последней строкой" in result.text


def test_fragment_may_name_two_tasks(run_script: RunScript, tmp_path: Path) -> None:
    """Одна работа бывает по двум задачам, и такая ссылка законна."""
    (tmp_path / "CONTRACT_VERSION").write_text("0.1.0\n", encoding="utf-8")
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


def test_fragments_are_checked_without_the_assembled_file(
    run_script: RunScript, tmp_path: Path
) -> None:
    """На изменении спрашивают фрагменты, а собранного файла может не быть.

    Сборка — дело выпуска (030): общий файл, который трогает каждая ветка,
    даёт конфликт на каждом втором изменении.
    """
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "changelog.d" / "slug.added.md").write_text("текст\n\n#1\n", encoding="utf-8")
    result = run_script("build_changelog.py", "--fragments", cwd=tmp_path)
    assert result.code == CLEAN, result.text
    assert not (tmp_path / "CHANGELOG.md").exists(), "проверка фрагментов собрала файл"


def test_fragments_check_refuses_a_broken_fragment(run_script: RunScript, tmp_path: Path) -> None:
    """Дефект фрагмента ловится на изменении, а не при выпуске."""
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "changelog.d" / "заметка.md").write_text("текст\n", encoding="utf-8")
    result = run_script("build_changelog.py", "--fragments", cwd=tmp_path)
    assert result.code == BROKEN, result.text


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
    (tmp_path / "CONTRACT_VERSION").write_text("0.1.0\n", encoding="utf-8")
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
    """Нет токена владельца — «не настроено», и на токен прогона шаг не переходит."""
    result = run_script(
        "agent_pr.py",
        "--repo",
        "o/r",
        "--branch",
        "agent/x",
        "--dry-run",
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
