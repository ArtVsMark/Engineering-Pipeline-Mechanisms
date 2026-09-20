"""Обход клонов семьи: кто ВЗЯЛ наши шаги, а не кто о них сказал.

Подключившийся молча невидим реестру адресов, а молчаливое подключение —
обычный случай. Проверяется здесь то, без чего обход был бы распечаткой
памяти: вызов отличается от упоминания (166), список семьи берётся из
выгрузки каталога, а непрочитанный клон называется незнанием, а не нулём
подключений (045).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import load_script

module = load_script("family_uptake.py")

CALL = (
    "jobs:\n  lint:\n    uses: ArtVsMark/Engineering-Pipeline-Mechanisms"
    "/.github/workflows/step-lint.yml@v1.2.0\n"
)


def test_a_call_is_found_with_its_step_and_version() -> None:
    """Вызов даёт и имя шага, и версию: без версии «взял» ничего не говорит."""
    steps, refs = module.calls_in(CALL)
    assert steps == ("step-lint",)
    assert refs == ("v1.2.0",)


def test_a_mention_is_not_a_call() -> None:
    """Имя проекта в прозе — не подключение (166).

    Наше имя встречается у соседей в комментариях и ссылках, и считать их
    подключением значило бы объявить взявшими всех разом.
    """
    said = (
        "# берём шаги из ArtVsMark/Engineering-Pipeline-Mechanisms, когда дойдут руки\n"
        "# см. https://github.com/ArtVsMark/Engineering-Pipeline-Mechanisms/blob/main/docs/onboarding.md\n"
    )
    assert module.calls_in(said) == ((), ())


def test_two_versions_at_one_consumer_are_named() -> None:
    """Разные версии у одного потребителя — находка, а не мелочь (152).

    Так выглядит недоведённый переезд: часть шагов уехала на новый тег, часть
    осталась, и снаружи это неотличимо от осознанного выбора.
    """
    said = CALL + CALL.replace("step-lint.yml@v1.2.0", "step-debt.yml@v1.1.0")
    steps, refs = module.calls_in(said)
    assert steps == ("step-debt", "step-lint")
    assert refs == ("v1.1.0", "v1.2.0")
    line = module.Took(repo="o/r", steps=steps, refs=refs).said()
    assert "разные версии" in line, line


def test_one_version_is_not_a_finding() -> None:
    """Вторая половина: одна версия у потребителя — не находка.

    Без неё строка кричала бы на каждом исправном подключении, а такое учат
    пропускать (051).
    """
    line = module.Took(repo="o/r", steps=("step-lint",), refs=("v1.2.0",)).said()
    assert "разные версии" not in line
    assert "v1.2.0" in line and "step-lint" in line


def test_taking_nothing_is_said_in_words() -> None:
    """«Не взял ничего» — состояние, названное словом, а не пустая строка."""
    assert "не взял ничего" in module.Took(repo="o/r", steps=(), refs=()).said()


def test_we_are_not_counted_among_the_family(monkeypatch: pytest.MonkeyPatch) -> None:
    """Себя обход не считает: мы свой первый потребитель, но не сосед.

    Иначе сводка всегда показывала бы одного взявшего — нас, — и «никто не
    взял» стало бы невыразимым.
    """
    monkeypatch.setattr(
        module.ghrest,
        "raw_json",
        lambda *_: {"consumers": [{"repo": module.OURS}, {"repo": "o/сосед"}]},
    )
    assert module.family() == ["o/сосед"]


def test_a_family_of_only_us_is_the_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """В сводке только мы — обходить некого, и это отказ, а не «никто не взял» (075)."""
    monkeypatch.setattr(
        module.ghrest, "raw_json", lambda *_: {"consumers": [{"repo": module.OURS}]}
    )
    with pytest.raises(module.NotRun, match="обходить некого"):
        module.family()


def test_an_empty_summary_is_the_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сводка пуста — предмета нет, и заход это говорит."""
    monkeypatch.setattr(module.ghrest, "raw_json", lambda *_: {"consumers": []})
    with pytest.raises(module.NotRun, match="обходить некого"):
        module.family()


def test_an_unreadable_summary_is_not_an_empty_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ транспорта и пустая сводка — разные ответы (045)."""

    def broken(*_a: object) -> None:
        raise module.ghrest.TransportError("снимок не прочитан")

    monkeypatch.setattr(module.ghrest, "raw_json", broken)
    with pytest.raises(module.NotRun, match="не прочитана"):
        module.family()


def test_an_unread_clone_is_not_a_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Клон не взят — сосед попадает в «не прочитано», а не в «не взял».

    Частный репозиторий, упавшая сеть и отсутствие ветки снаружи одинаковы, а
    значат разное: выдать их за ноль подключений значило бы объявить сводку
    полной там, где она неполна.
    """

    def refuse(repo: str, _where: Path) -> None:
        raise module.NotRun(f"{repo}: клон не взят")

    monkeypatch.setattr(module, "took", refuse)
    seen, unread = module.sweep(["o/один", "o/два"], tmp_path)
    assert seen == []
    assert unread == ["o/один", "o/два"]
    lines = module.report_lines(seen, unread)
    assert any("не прочитано клонов: 2" in line for line in lines), lines
    assert any("незнание" in line for line in lines), lines


def test_one_refusal_does_not_fell_the_sweep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Вторая половина: отказ по одному соседу не прячет состояние остальных."""

    def half(repo: str, _where: Path):  # type: ignore[no-untyped-def]
        if repo == "o/один":
            raise module.NotRun("клон не взят")
        return module.Took(repo=repo, steps=("step-lint",), refs=("v1.2.0",))

    monkeypatch.setattr(module, "took", half)
    seen, unread = module.sweep(["o/один", "o/два"], tmp_path)
    assert [one.repo for one in seen] == ["o/два"]
    assert unread == ["o/один"]


def test_a_neighbour_without_workflows_took_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Каталога прогонов нет — «не взял», а не отказ: конвейера у соседа может не быть.

    Настоящий клон здесь не делается: предмет проверки — разбор ОТСУТСТВИЯ
    каталога, а не работа git.
    """
    monkeypatch.setattr(module, "shallow_clone", lambda _repo, _where: tmp_path)
    got = module.took("o/пустой", tmp_path)
    assert got.steps == () and got.refs == ()


def test_the_clone_is_shallow_and_sparse() -> None:
    """Клон берётся поверхностным и частичным, а не целиком.

    Прогонов у соседа до тринадцати, а дерево целиком нам не нужно: за трафик
    платит и он тоже. Признак назван ключами команды, а не замером скорости —
    скорость зависит от сети, а ключи от нас.
    """
    source = (Path("scripts") / "family_uptake.py").read_text(encoding="utf-8")
    for key in ("--depth", "--filter=blob:none", "--sparse", "sparse-checkout"):
        assert key in source, f"клон берётся без «{key}» — это уже не поверхностный обход"


def test_the_sweep_reaches_its_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Оба исхода захода ПРОГОНЯЮТСЯ, а не только объявлены (039, 145)."""
    monkeypatch.setattr(module, "family", lambda: ["o/сосед"])
    monkeypatch.setattr(
        module, "took", lambda repo, _where: module.Took(repo=repo, steps=(), refs=())
    )
    assert module.main([]) == module.EXIT_OK

    def refuse(repo: str, _where: Path) -> None:
        raise module.NotRun(f"{repo}: клон не взят")

    monkeypatch.setattr(module, "took", refuse)
    assert module.main([]) == module.EXIT_UNREAD


def test_a_broken_family_list_is_its_own_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Список семьи не прочитан — второй исход, а не пустая сводка."""

    def broken() -> None:
        raise module.NotRun("сводка семьи не прочитана")

    monkeypatch.setattr(module, "family", broken)
    assert module.main([]) == module.EXIT_BROKEN


def test_a_timeout_is_caught_like_any_other_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Зависший сосед не вешает обход: предел ожидания объявлен и ловится.

    Без предела заход стоит на недоступном соседе и не доходит до остальных —
    то есть один медленный прячет состояние всех.
    """

    def slow(repo: str, _where: Path) -> None:
        raise subprocess.TimeoutExpired(cmd=["git", "clone", repo], timeout=module.TIMEOUT)

    monkeypatch.setattr(module, "took", slow)
    seen, unread = module.sweep(["o/медленный"], tmp_path)
    assert seen == [] and unread == ["o/медленный"]


def test_a_shallow_clone_brings_only_the_workflows(tmp_path: Path) -> None:
    """Клон берётся по-настоящему — на локальном репозитории, без сети.

    Подменять `shallow_clone` во всех проверках значило бы не проверить его ни
    разу: подменённое имя снаружи неотличимо от непроверенного (146). Источник
    здесь локальный, поэтому проверка не зависит ни от сети, ни от соседей.
    """
    source = tmp_path / "сосед"
    (source / ".github" / "workflows").mkdir(parents=True)
    (source / ".github" / "workflows" / "ci.yml").write_text(CALL, encoding="utf-8")
    (source / "лишнее.txt").write_text("не нужно", encoding="utf-8")
    run = ["git", "-C", str(source)]
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(source)], check=True)
    subprocess.run([*run, "config", "user.email", "т@т"], check=True)
    subprocess.run([*run, "config", "user.name", "т"], check=True)
    subprocess.run([*run, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*run, "commit", "--quiet", "-m", "прогоны"], check=True)

    into = tmp_path / "клоны"
    into.mkdir()
    got = module.shallow_clone("сосед", into, host=str(tmp_path))
    assert (got / ".github" / "workflows" / "ci.yml").is_file(), "прогоны не приехали"


def test_a_clone_that_refuses_is_named(tmp_path: Path) -> None:
    """Источника нет — отказ с причиной, а не пустой клон (075)."""
    with pytest.raises(module.NotRun, match="клон не взят"):
        module.shallow_clone("нет-такого", tmp_path, host=str(tmp_path))
