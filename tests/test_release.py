"""Выпуск проверяется тем, что обязан ОТВЕРГНУТЬ, — до необратимого шага.

Тег не переставляется. Значит проверка живёт ПЕРЕД ним, а не разбирает
последствия после
([074](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/074-one-shot-irreversible-steps-get-their-own-guard.md)),
и проверяется здесь именно она: каждая причина не выпускать — отдельным
случаем, потому что выпуск делают редко и увидеть их надо сразу все.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest import FAKE_VERSION, ROOT, RunScript, load_script

module = load_script("release.py")


def tree(
    root: Path, version: str = FAKE_VERSION, *, fragments: tuple[str, ...] = ("a.added.md",)
) -> Path:
    """Собирает дерево, готовое к выпуску: версия, фрагменты, чистый git."""
    (root / "CONTRACT_VERSION").write_text(f"{version}\n", encoding="utf-8")
    kits = root / "changelog.d"
    kits.mkdir(exist_ok=True)
    (kits / "README.md").write_text("правила фрагментов\n", encoding="utf-8")
    for name in fragments:
        (kits / name).write_text("текст\n\n#1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    # ПОДПИСЬ ЗАДАЁТСЯ В САМОЙ ПОДДЕЛКЕ, а не берётся у окружения. У исполнителя
    # площадки её нет вовсе, и `git commit`/`git tag -a` там падают — то есть
    # проверка зелена только на машине, где подпись настроена глобально. Замер
    # 10.09.2026: набор прошёл локально и покраснел на всех версиях сразу.
    subprocess.run(["git", "config", "user.email", "a@b"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "выпуск"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)
    return root


def test_the_next_version_raises_the_minor() -> None:
    """Минор растёт, когда поверхность тронута: есть фрагмент рода `contract`.

    Патч при этом обнуляется: новый минор начинается с нуля.
    """
    assert module.next_after("9.9.0", contract=True) == "9.10.0"
    assert module.next_after("9.9.73", contract=True) == "9.10.0"


def test_a_contract_fragment_leaves_the_major_alone() -> None:
    """Правка поверхности мажор НЕ поднимает — его поднимает приёмка.

    Прежняя редакция этого теста повторяла соседний слово в слово и не
    проверяла ничего своего; нашёл внешний взгляд на #229. Предмет здесь
    именно мажор: он обязан остаться на месте при ЛЮБОМ роде фрагмента
    (decisions/009, decisions/015).
    """
    for current in ("2.5.0", "9.9.73"):
        was = current.split(".")[0]
        for contract in (True, False):
            assert module.next_after(current, contract=contract).split(".")[0] == was


def test_the_major_needs_a_named_acceptance(run_script: RunScript, tmp_path: Path) -> None:
    """Мажор поднимает не выпуск, а ЗАКРЫТАЯ приёмка (decisions/009).

    Договор и механизм говорили разное: договор — «единицу выпускает закрытая
    приёмка эпика», механизм — «назовите первого потребителя». Расхождение
    нашёл внешний взгляд на #198, и оно было не косметическим: исполнял
    механизм СТАРОЕ правило, то есть договор не значил ничего (002).
    """
    tree(tmp_path)
    run = run_script("release.py", "--version", "10.0.0", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "приёмка" in run.text.lower()
    assert "--acceptance" in run.text


def test_a_named_but_unread_acceptance_is_still_a_refusal(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Названная, но НЕ прочитанная приёмка выпуск не пускает.

    Три состояния вместо двух: закрыта, открыта, не прочитана. Свести третье к
    первому значило бы завести обход ровно там, где стоит проверка перед
    необратимым (045, 074) — ключ стал бы подписью под тем, чего никто не
    видел.
    """
    tree(tmp_path)
    run = run_script(
        "release.py",
        "--version",
        "10.0.0",
        "--acceptance",
        "196",
        cwd=tmp_path,
        env={"GH_TOKEN": "", "GITHUB_TOKEN": ""},
    )
    assert run.code == 1, run.text
    assert "не прочитано" in run.text


def test_a_closed_acceptance_allows_the_major() -> None:
    """С закрытой приёмкой мажор проходит; с открытой — нет.

    Разбор проверяется данными, а не подделкой транспорта: состояние приходит
    в `refusals` готовым ответом.
    """

    def said(state: str) -> list[str]:
        return [
            one for one in module.refusals("1.0.0", acceptance="196", state=state) if "мажор" in one
        ]

    assert said(module.ACCEPTANCE_CLOSED) == []
    assert "ОТКРЫТА" in "".join(said(module.ACCEPTANCE_OPEN))
    assert "не прочитано" in "".join(said(module.ACCEPTANCE_UNREAD))
    # Несуществующий номер чинится НОМЕРОМ, и причина обязана сказать об этом,
    # а не отправить искать токен (154). Нашёл внешний взгляд на #204.
    missing = "".join(said(module.ACCEPTANCE_MISSING))
    assert "НЕТ" in missing and "номером" in missing
    # Форма входа — пятое состояние: «#196» не число, и причина обязана сказать
    # именно это, а не «нет токена» (154). Нашёл внешний взгляд на #204.
    shape = "".join(said(module.ACCEPTANCE_NOT_A_NUMBER))
    assert "не разобрано как номер" in shape


def test_the_acceptance_state_separates_the_two_unknowns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """«Такой задачи нет» и «не прочитано» — разные состояния и разная починка.

    Первое чинится номером, второе токеном. Сведение их в одно отправляло бы
    человека искать секрет там, где неверна цифра. Здесь проверяется и путь
    отказа транспорта, которого прежде не касался ни один тест (#204).
    """

    def answer(exc: Exception | None, state: str | None = None) -> Callable[..., dict[str, str]]:
        def _ask(*_: object, **__: object) -> dict[str, str]:
            if exc is not None:
                raise exc
            return {"state": state} if state else {}

        return _ask

    monkeypatch.setattr(module.ghrest, "request", answer(module.ghrest.NotFound("404")))
    assert module.acceptance_state("o/r", 999, "t") == module.ACCEPTANCE_MISSING

    monkeypatch.setattr(module.ghrest, "request", answer(module.ghrest.TransportError("молчит")))
    assert module.acceptance_state("o/r", 196, "t") == module.ACCEPTANCE_UNREAD

    monkeypatch.setattr(module.ghrest, "request", answer(None, "closed"))
    assert module.acceptance_state("o/r", 196, "t") == module.ACCEPTANCE_CLOSED

    monkeypatch.setattr(module.ghrest, "request", answer(None, "open"))
    assert module.acceptance_state("o/r", 196, "t") == module.ACCEPTANCE_OPEN

    monkeypatch.setattr(module.ghrest, "request", answer(None))
    assert module.acceptance_state("o/r", 196, "t") == module.ACCEPTANCE_UNREAD
    assert module.acceptance_state("", 196, "t") == module.ACCEPTANCE_UNREAD
    assert module.acceptance_state("o/r", 196, "") == module.ACCEPTANCE_UNREAD


def test_a_wrong_minor_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Номер, не следующий за текущим, отвергается с названным ожиданием."""
    tree(tmp_path)
    run = run_script("release.py", "--version", "9.50.0", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "ожидается 9.9.1" in run.text


def test_an_empty_release_is_an_input_error(run_script: RunScript, tmp_path: Path) -> None:
    """Выпуск без единого фрагмента — ошибка входа, а не пустой выпуск (075)."""
    tree(tmp_path, fragments=())
    run = run_script("release.py", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "ни одного фрагмента" in run.text


def test_a_dirty_tree_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Выпуск с грязного дерева отвергается: тег указал бы не на то, что выпущено."""
    tree(tmp_path)
    (tmp_path / "лишнее.txt").write_text("не в коммите\n", encoding="utf-8")
    run = run_script("release.py", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "дерево грязно" in run.text


def test_an_existing_tag_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Тег уже стоит — выпуск отвергается: тег не переставляется (074).

    Это главный необратимый шаг: переставленный тег меняет то, на что уже
    прибит потребитель, и заметить это он не обязан.
    """
    tree(tmp_path)
    # Тег ставится на ОЖИДАЕМЫЙ номер: фрагмент здесь не о поверхности, значит
    # ожидается патч, а не минор (decisions/015).
    subprocess.run(["git", "tag", "v9.9.1"], cwd=tmp_path, check=True)
    run = run_script("release.py", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "не переставляется" in run.text


def test_a_bad_version_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Номер не той формы отвергается до всего остального."""
    tree(tmp_path)
    run = run_script("release.py", "--version", "9.9", cwd=tmp_path)
    assert run.code == 1, run.text


def test_nothing_irreversible_happens_without_apply(run_script: RunScript, tmp_path: Path) -> None:
    """Без ключа `--apply` не делается ничего необратимого.

    Половина смысла разделения: человек читает, из чего собран выпуск, и только
    потом решает. Заход, делающий это одним движением, читать было бы поздно.
    """
    tree(tmp_path)
    run = run_script("release.py", cwd=tmp_path)
    assert run.code == 0, run.text
    assert "--apply" in run.text
    assert not (tmp_path / "changelog.d" / "released").exists()
    assert (
        subprocess.run(
            ["git", "tag", "--list"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout.strip()
        == ""
    )


def test_the_release_moves_fragments_and_tags(run_script: RunScript, tmp_path: Path) -> None:
    """Настоящий выпуск: фрагменты переезжают, версия поднята, тег стоит.

    Фрагменты именно ПЕРЕЕЗЖАЮТ, а не удаляются: собранный журнал производный,
    и источником остаются они ([125](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/125-a-generated-file-is-not-a-store.md)).
    """
    tree(tmp_path)
    run = run_script("release.py", "--apply", cwd=tmp_path)
    assert run.code == 0, run.text
    assert (tmp_path / "changelog.d" / "released" / "9.9.1" / "a.added.md").is_file()
    assert not (tmp_path / "changelog.d" / "a.added.md").exists()
    assert (tmp_path / "CONTRACT_VERSION").read_text(encoding="utf-8").strip() == "9.9.1"
    tags = subprocess.run(
        ["git", "tag", "--list"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.split()
    assert tags == ["v9.9.1"]


def test_the_procedure_matches_the_contract() -> None:
    """Порядок выпуска в механизме тот же, что записан в договоре (029).

    Договор описывает порядок с самого начала; механизм обязан ему отвечать, а
    не заводить свой.
    """
    text = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    assert "## Порядок выпуска" in text
    assert "тег не переставляется" in text.lower()


def test_a_hash_prefixed_acceptance_names_the_input_not_the_token(
    run_script: RunScript, tmp_path: Path
) -> None:
    """«#196» отвергается по ФОРМЕ, а не как «состояние не прочитано».

    Прежде нечисловой вход молча становился «нет токена или площадка молчит» —
    и человек шёл искать секрет там, где лишняя решётка (154). Нашёл внешний
    взгляд на #204.
    """
    tree(tmp_path)
    run = run_script("release.py", "--version", "10.0.0", "--acceptance", "#196", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "не разобрано как номер" in run.text
    assert "нет токена" not in run.text


def test_the_contract_names_every_state_the_mechanism_tells_apart() -> None:
    """Договор о выпуске называет ВСЕ состояния приёмки, что различает механизм.

    Расхождение договора и механизма здесь уже было и стоило дороже прочего:
    новое правило мажора жило в `docs/release.md`, пока `release.py` исполнял
    старое (#198). Пять состояний — пять строк таблицы, и сверяет их машина, а
    не внимание автора
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    """
    contract = (ROOT / "docs" / "release.md").read_text(encoding="utf-8").lower()
    missing = [said for said in module.ACCEPTANCE_SAID.values() if said.lower() not in contract]
    assert not missing, f"механизм различает, а договор не называет: {missing}"
