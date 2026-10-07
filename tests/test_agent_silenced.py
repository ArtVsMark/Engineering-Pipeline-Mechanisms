"""Правка файла прогона глушит агента — и об этом говорят ДО толчка.

21.09.2026 изменение #614 правило `.github/workflows/review.yml` и уехало в
общую ветку без внешнего взгляда. Площадка отказала действию агента — файл
прогона обязан совпадать с версией на общей ветке, — но шаг объявлен
`continue-on-error`, поэтому он остался ЗЕЛЁНЫМ. Тишина не покраснела нигде, и
узналось это из реестра #89 уже после слияния.

Проверяется здесь то, без чего предупреждение было бы догадкой:

* носители действия берутся ИЗ ДЕРЕВА по вызову, а не перечисляются именами:
  их три, и четвёртый появился бы молча;
* состав носителей спрашивается у ОБЩЕЙ ветки — с нею площадка и сравнивает;
* нетронутый прогон предупреждения не даёт: гейт, кричащий на здоровом, учат
  обходить (051);
* отсутствие носителей вовсе — третий исход, а не «чисто» (075).
"""

import subprocess
from pathlib import Path

import pytest

from tests.conftest import load_script

module = load_script("check_agent_silenced.py")

#: Прогон, который в дереве действие агента НЕ объявляет: правка такого файла
#: взгляда не глушит, и предупреждать о ней значило бы кричать на здоровом.
INNOCENT = ".github/workflows/ci.yml"


def tree(tmp_path: Path, carriers: dict[str, str], touched: dict[str, str]) -> Path:
    """Дерево с общей веткой и правкой поверх неё — настоящим git, а не подделкой.

    ПОДДЕЛКИ ЗДЕСЬ БЫТЬ НЕ МОЖЕТ: предмет проверки — два вопроса К GIT
    (`grep` по базе и `diff` против неё), и заменив их, проверялся бы не
    механизм, а заглушка
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    """
    root = tmp_path / "дерево"
    (root / ".github" / "workflows").mkdir(parents=True)

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "проба@example.invalid")
    run("config", "user.name", "проба")
    for name, text in carriers.items():
        (root / name).write_text(text, encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "общая ветка")
    run("branch", "база")
    for name, text in touched.items():
        (root / name).write_text(text, encoding="utf-8")
    if touched:
        run("add", "-A")
        run("commit", "-qm", "правка")
    return root


CARRIER = f"шаг:\n  uses: {module.ACTION}@v1\n"


def test_a_touched_carrier_warns_that_the_look_will_be_silent(tmp_path: Path) -> None:
    """Правка носителя названа — с именем файла и с ценой (154)."""
    root = tree(
        tmp_path,
        {".github/workflows/review.yml": CARRIER, INNOCENT: "шаг: тесты\n"},
        {".github/workflows/review.yml": CARRIER + "# правка\n"},
    )
    code, said = module.look(root, "база")
    assert code == module.EXIT_SILENCED, said
    assert "review.yml" in said, "имя файла не названо — искать придётся вслепую"
    assert "НЕ БУДЕТ" in said, "цена правки не названа"


def test_an_untouched_carrier_stays_quiet(tmp_path: Path) -> None:
    """Вторая половина: тронут прогон БЕЗ действия — предупреждения нет.

    Без неё проверка неотличима от «изменение трогает `.github/workflows/`» —
    такая кричала бы на всякой правке конвейера, и её научились бы пролистывать
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    """
    root = tree(
        tmp_path,
        {".github/workflows/review.yml": CARRIER, INNOCENT: "шаг: тесты\n"},
        {INNOCENT: "шаг: тесты\n# правка\n"},
    )
    code, said = module.look(root, "база")
    assert code == module.EXIT_OK, said
    assert "не тронуты" in said


def test_the_carriers_come_from_the_tree_not_from_a_list(tmp_path: Path) -> None:
    """Носители находятся ПО ВЫЗОВУ, а любое имя файла — законное.

    Список именами устарел бы молча: действие объявляют три прогона, и четвёртый
    получил бы тишину без предупреждения
    ([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).
    """
    свой = ".github/workflows/совсем-другое-имя.yml"
    root = tree(tmp_path, {свой: CARRIER}, {свой: CARRIER + "# правка\n"})
    code, said = module.look(root, "база")
    assert code == module.EXIT_SILENCED, said
    assert "совсем-другое-имя.yml" in said


def test_a_tree_without_the_action_is_the_third_outcome(tmp_path: Path) -> None:
    """Носителей нет вовсе — отказ, а не «чисто».

    Предикат, не находящий предмета, доказывает только себя
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    root = tree(tmp_path, {INNOCENT: "шаг: тесты\n"}, {INNOCENT: "шаг: тесты\n# правка\n"})
    with pytest.raises(module.NotRun, match="предмета у проверки нет"):
        module.look(root, "база")


def test_the_carriers_are_read_from_the_shared_branch(tmp_path: Path) -> None:
    """Состав носителей спрашивается у ОБЩЕЙ ветки, а не у рабочего дерева.

    Прогон, заведённый САМИМ изменением, на общей ветке ещё не объявлен, и
    площадке сравнивать его не с чем — предупреждать о нём значило бы обещать
    отказ, которого не будет. Держит это `carriers(root, base)`: он спрашивает
    базу, и подмена её рабочим деревом здесь краснеет.
    """
    новый = ".github/workflows/заведён-этим-изменением.yml"
    root = tree(
        tmp_path,
        {".github/workflows/review.yml": CARRIER, INNOCENT: "шаг: тесты\n"},
        {новый: CARRIER},
    )
    assert module.carriers(root, "база") == {".github/workflows/review.yml"}
    code, said = module.look(root, "база")
    assert code == module.EXIT_OK, said


def test_the_refusal_of_git_is_not_an_empty_answer(tmp_path: Path) -> None:
    """Отказ git — третий исход, а не пустой список файлов (045)."""
    root = tmp_path / "не-дерево"
    root.mkdir()
    with pytest.raises(module.NotRun, match="git"):
        module.look(root, "база")


def test_the_run_returns_the_declared_outcome(tmp_path: Path) -> None:
    """Заход отдаёт объявленный исход отказа, а не просто печатает (039, 140)."""
    root = tree(
        tmp_path,
        {".github/workflows/review.yml": CARRIER},
        {".github/workflows/review.yml": CARRIER + "# правка\n"},
    )
    assert module.main(["--root", str(root), "--base", "база"]) == module.EXIT_SILENCED
    assert module.main(["--root", str(tmp_path / "нет"), "--base", "база"]) == module.EXIT_BROKEN


#: Тело взгляда — общий шаг с действием агента (#993).
STEP = ".github/workflows/step-review.yml"
#: Вызывающий того же шага: по адресу с общей веткой и внутренним путём.
BY_TRUNK = "jobs:\n  review:\n    uses: О/Р/.github/workflows/step-review.yml@main\n"
BY_PATH = "jobs:\n  review:\n    uses: ./.github/workflows/step-review.yml\n"


def test_the_caller_of_a_carrier_carries_too(tmp_path: Path) -> None:
    """Правка ВЫЗЫВАЮЩЕГО носителя названа: файлом прогона площадке служит он (#993)."""
    caller = ".github/workflows/review.yml"
    root = tree(tmp_path, {STEP: CARRIER, caller: BY_TRUNK}, {caller: BY_TRUNK + "# правка\n"})
    assert module.callers(root, "база", {STEP}) == {caller}
    code, said = module.look(root, "база")
    assert code == module.EXIT_SILENCED, said
    assert "review.yml" in said


def test_a_step_called_from_the_trunk_is_not_silenced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Обе половины: шаг, позванный с общей веткой, правкой не глушится, а внутренним путём — да.

    Адрес с общей веткой берёт файл не из изменения (#993), и расходиться с
    общей веткой на голове ему нечему; внутренний путь берёт его из изменения.
    """
    monkeypatch.setenv("GITHUB_REPOSITORY", "О/Р")
    caller = ".github/workflows/review.yml"
    trunk = tree(tmp_path / "т", {STEP: CARRIER, caller: BY_TRUNK}, {STEP: CARRIER + "# правка\n"})
    assert module.from_trunk(trunk, "база", {STEP}) == {STEP}
    assert module.look(trunk, "база")[0] == module.EXIT_OK
    local = tree(tmp_path / "л", {STEP: CARRIER, caller: BY_PATH}, {STEP: CARRIER + "# правка\n"})
    assert module.from_trunk(local, "база", {STEP}) == set()
    assert module.look(local, "база")[0] == module.EXIT_SILENCED


@pytest.mark.parametrize(
    ("calls", "silenced"),
    [
        ([BY_TRUNK.replace("О/Р/", "Чужой/Р/")], True),
        ([BY_TRUNK.replace("@main", "@main-next")], True),
        ([BY_TRUNK, BY_PATH.replace("  review:", "  ещё:")], True),
        ([BY_TRUNK.replace("о/р".upper(), "о/р")], False),
    ],
    ids=["чужой репозиторий", "ветка с хвостом", "есть и вызов ./", "свой адрес иным регистром"],
)
def test_only_an_own_trunk_call_excludes_the_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[str], silenced: bool
) -> None:
    """Шаг выпадает из носителей, только если ВСЕ его вызовы — свой адрес с общей веткой (#1170).

    Чужой репозиторий с тем же именем файла, `@main-next` и соседний вызов `./`
    шаг не освобождают: тогда правка шага может исполниться из изменения.
    """
    monkeypatch.setenv("GITHUB_REPOSITORY", "О/Р")
    flows = {STEP: CARRIER}
    for number, said in enumerate(calls):
        flows[f".github/workflows/зовущий-{number}.yml"] = said
    root = tree(tmp_path, flows, {STEP: CARRIER + "# правка\n"})
    code = module.look(root, "база")[0]
    assert code == (module.EXIT_SILENCED if silenced else module.EXIT_OK)


def test_an_unknown_own_name_excludes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Своего имени не узнать — шаг остаётся носителем: ошибка в сторону громкости (051)."""
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    root = tree(tmp_path, {STEP: CARRIER, ".github/workflows/review.yml": BY_TRUNK}, {})
    assert module.own_repo(root) == ""
    assert module.from_trunk(root, "база", {STEP}) == set()
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/О/Р.git"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    assert module.own_repo(root) == "О/Р"
    assert module.from_trunk(root, "база", {STEP}) == {STEP}


def test_a_foreign_call_of_the_same_path_is_not_ours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Чужой адрес того же пути не делает вызывающего носителем и не возвращает шаг (#1175).

    Обе половины: рядом со своим `@main` чужой вызов шаг в носители не
    возвращает, а вызывающий чужого файла носителем не считается; свой
    внутренний путь — по-прежнему вызов.
    """
    monkeypatch.setenv("GITHUB_REPOSITORY", "О/Р")
    foreign = BY_TRUNK.replace("О/Р/", "Другой/Р/").replace("  review:", "  чужой:")
    flows = {STEP: CARRIER, ".github/workflows/свой.yml": BY_TRUNK}
    flows[".github/workflows/чужой.yml"] = foreign
    root = tree(tmp_path, flows, {STEP: CARRIER + "# правка\n"})
    assert module.callers(root, "база", {STEP}) == {".github/workflows/свой.yml"}
    assert module.from_trunk(root, "база", {STEP}) == {STEP}
    assert module.look(root, "база")[0] == module.EXIT_OK


@pytest.mark.parametrize(
    ("said", "own", "is_ours"),
    [
        ("./.github/workflows/x.yml", "о/р", True),
        ("О/Р/.github/workflows/x.yml@main", "о/р", True),
        ("Другой/Р/.github/workflows/x.yml@main", "о/р", False),
        ("Другой/Р/.github/workflows/x.yml@main", "", True),
    ],
    ids=["внутренний путь", "свой адрес", "чужой адрес", "своё имя неизвестно"],
)
def test_ours_tells_an_own_call_from_a_foreign_one(said: str, own: str, is_ours: bool) -> None:
    """Обе половины признака: свой путь и свой адрес — наши, чужой — нет, без имени — наш (051)."""
    assert module.ours(said, own) is is_ours
