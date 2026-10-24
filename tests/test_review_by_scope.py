"""Взгляд по сценарию: метка `scope/*` урезает роли и тесты взгляда (#1608)."""

import json
from pathlib import Path

import pytest

from tests.conftest import ROOT, load_script
from tests.test_scope import git

module = load_script("review_map.py")

TABLE = {
    "required": ["тестировщик", "аудитор", "ревизор", "критик метода", "правила каталога"],
    "by_scope": {"text": ["ревизор", "правила каталога"]},
}


@pytest.mark.parametrize(
    ("labels", "kind"),
    [
        (None, "full"),
        (set(), "full"),
        ({"bug", "area/docs"}, "full"),
        ({"scope/text"}, "text"),
        ({"scope/text", "scope/full"}, "full"),
        ({"scope/code"}, "code"),
    ],
    ids=["не-прочитаны", "пусто", "без-сценария", "текст", "шире-владелец", "код"],
)
def test_the_scenario_comes_from_the_label(labels: set[str] | None, kind: str) -> None:
    """Сценарий — метка изменения; нет её или не прочитана — полный состав (ошибка вширь)."""
    assert module.scenario_of(labels) == kind


def test_a_text_change_drops_the_testing_roles() -> None:
    """На тексте остаются ревизор и правила каталога; на коде — все обязательные."""
    required = TABLE["required"]
    assert module.for_scenario(required, TABLE, "text") == ["ревизор", "правила каталога"]
    assert module.for_scenario(required, TABLE, "code") == required
    assert module.for_scenario(required, {"required": required}, "text") == required


@pytest.mark.parametrize(
    "by_scope",
    [["text"], {"мелочь": ["ревизор"]}, {"text": ["посторонний"]}, {"text": "ревизор"}],
    ids=["не-словарь", "чужой-сценарий", "не-обязательная", "не-список"],
)
def test_a_broken_scope_table_is_refused(by_scope: object) -> None:
    """Таблица сценариев иной формы — отказ: сценарий только сужает обязательные."""
    with pytest.raises(module.NotRun, match="by_scope"):
        module.table_shape({"required": TABLE["required"], "by_scope": by_scope})


def test_the_live_table_passes_its_own_shape() -> None:
    """Таблица дерева проходит свою форму и сужает текст до названных ролей."""
    table = json.loads((ROOT / ".rules" / "review-roles.json").read_text(encoding="utf-8"))
    module.table_shape(table)
    assert set(table["by_scope"]["text"]) < set(table["required"])


def test_the_tests_line_follows_the_scenario() -> None:
    """Текст — не гонять; код — выбор классификатора; пустой выбор — нечего; прочее — прежнее."""
    assert "Тесты не гоняй" in "\n".join(module.tests_said("text", None))
    said = "\n".join(module.tests_said("code", ("tests/test_a.py", "tests/test_b.py")))
    assert "python -m pytest -q tests/test_a.py tests/test_b.py" in said
    assert "пуст" in "\n".join(module.tests_said("code", ()))
    assert module.tests_said("code", None) == []
    assert module.tests_said("full", ("tests/test_a.py",)) == []


def base_tree(tmp_path: Path) -> Path:
    """Дерево базы: модуль `a` и его тест."""
    for name, text in {
        "scripts/a.py": "A = 1\n",
        "tests/test_a.py": 'load_script("a.py")\n',
        "tests/test_other.py": "",
    }.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "база")
    return tmp_path


def test_the_choice_is_the_base_graph_plus_touched_tests(tmp_path: Path) -> None:
    """Выбор — по графу базы, а тронутый тест-файл, новый в голове, входит сам."""
    root = base_tree(tmp_path)
    said = module.chosen_tests(["scripts/a.py", "tests/test_new.py"], root)
    assert said == ("tests/test_a.py", "tests/test_new.py")


def test_an_uncountable_choice_falls_back(tmp_path: Path) -> None:
    """Битый раздел областей — выбор не посчитан, и строка о тестах прежняя."""
    root = base_tree(tmp_path)
    (root / ".pipeline.yml").write_text("scopes: [web]\n", encoding="utf-8")
    assert module.chosen_tests(["scripts/a.py"], root) is None


def test_the_roles_section_drops_roles_on_a_text_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """Раздел ролей на `scope/text`: тестировщика нет, тесты не гонять."""
    monkeypatch.setattr(module, "labels_of", lambda *_: {"scope/text"})
    shown = {
        module.paths.REVIEW_PROCEDURE: "процедура",
        module.paths.REVIEW_ROLES: json.dumps(TABLE, ensure_ascii=False),
        module.paths.PIPELINE: "",
    }
    monkeypatch.setattr(module, "shown_from_base", lambda base, path: shown[path])
    said = module.roles_section("origin/main", "о/р", 7, files=["README.md"])
    assert "**Обязательные роли:** ревизор, правила каталога." in said
    assert "Тесты не гоняй" in said
    assert "**Сценарий `text`**" in said and "сняты тестировщик, аудитор, критик метода" in said


@pytest.mark.parametrize(
    ("labels", "own", "kind"),
    [
        ({"scope/text"}, "code", "code"),
        ({"scope/full"}, "text", "full"),
        ({"scope/code"}, "code", "code"),
        (None, "text", "full"),
    ],
    ids=["метка-уже-ответа", "метка-шире", "совпали", "метка-не-прочитана"],
)
def test_a_label_does_not_narrow_past_the_own_answer(
    labels: set[str] | None, own: str, kind: str
) -> None:
    """Сценарий — шире из метки и своего ответа: суженная после гейта метка не урезает (#1609)."""
    assert module.scenario_of(labels, module.scope.Choice(own, (), "")) == kind


def test_an_uncounted_own_answer_keeps_every_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """Свой ответ не посчитан при тронутом — состав полный, метка `scope/text` не сужает (045)."""
    monkeypatch.setattr(module, "labels_of", lambda *_: {"scope/text"})
    monkeypatch.setattr(module, "own_choice", lambda *_: None)
    shown = {
        module.paths.REVIEW_PROCEDURE: "процедура",
        module.paths.REVIEW_ROLES: json.dumps(TABLE, ensure_ascii=False),
        module.paths.PIPELINE: "",
    }
    monkeypatch.setattr(module, "shown_from_base", lambda base, path: shown[path])
    said = module.roles_section("origin/main", "о/р", 7, files=["README.md"])
    assert f"**Обязательные роли:** {', '.join(TABLE['required'])}." in said
    assert "сняты" not in said


def test_a_test_removed_by_the_change_is_not_run(tmp_path: Path) -> None:
    """Тест, удалённый в голове, в команду не идёт: pytest не получит мёртвый путь (#1609)."""
    root = base_tree(tmp_path)
    git(root, "rm", "-q", "tests/test_a.py")
    git(root, "commit", "-qm", "голова")
    head = git(root, "rev-parse", "HEAD").strip()
    git(root, "checkout", "-q", "HEAD~1")
    said = module.chosen_tests(["scripts/a.py", "tests/test_a.py"], root, head=head)
    assert said == ()


def test_labels_are_asked_of_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """Метки — у площадки; без номера или токена и при отказе — `None`, состав полный."""
    monkeypatch.setattr(module.ghrest, "paginate", lambda *_: iter([{"name": "scope/code"}]))
    assert module.labels_of("о/р", 7, "т") == {"scope/code"}
    assert module.labels_of("о/р", 0, "т") is None

    def refuse(*_: object) -> object:
        raise module.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(module.ghrest, "paginate", refuse)
    assert module.labels_of("о/р", 7, "т") is None


def test_the_head_tree_is_asked_and_its_silence_is_named(tmp_path: Path) -> None:
    """`present_in`: пути головы — по дереву git; неизвестная голова — `None`, а не «нет»."""
    root = base_tree(tmp_path)
    assert module.present_in("HEAD", ["tests/test_a.py", "tests/нет.py"], root) == {
        "tests/test_a.py"
    }
    assert module.present_in("HEAD", [], root) == frozenset()
    assert module.present_in("нет-такой-головы", ["tests/test_a.py"], root) is None


def test_the_own_choice_is_the_classifier_or_none(tmp_path: Path) -> None:
    """`own_choice`: ответ классификатора по графу базы; битые области — `None`."""
    root = base_tree(tmp_path)
    said = module.own_choice(["scripts/a.py"], root)
    assert said is not None and said.scenario == module.scope.CODE
    assert said.tests == ("tests/test_a.py",)
    (root / ".pipeline.yml").write_text("scopes: [web]\n", encoding="utf-8")
    assert module.own_choice(["scripts/a.py"], root) is None
