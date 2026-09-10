"""Выпуск проверяется тем, что обязан ОТВЕРГНУТЬ, — до необратимого шага.

Тег не переставляется. Значит проверка живёт ПЕРЕД ним, а не разбирает
последствия после
([074](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/074-one-shot-irreversible-steps-get-their-own-guard.md)),
и проверяется здесь именно она: каждая причина не выпускать — отдельным
случаем, потому что выпуск делают редко и увидеть их надо сразу все.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

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
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init"],
        cwd=root,
        check=True,
    )
    return root


def test_the_next_version_raises_the_minor() -> None:
    """Минор растёт при каждой постановке тега — инвариант «каждый тег vX.Y.0».

    Патч-тегов не существует: патч это счётчик принятых изменений после тега, а
    не номер выпуска.
    """
    assert module.next_after("9.9.0", contract=False) == "9.10.0"
    assert module.next_after("9.9.73", contract=False) == "9.10.0"


def test_a_contract_fragment_does_not_raise_the_major() -> None:
    """Правка поверхности сама по себе мажор не поднимает.

    `0.x` живёт до первого потребителя: поверхность ещё никому не обещана, и
    ломать нечего.
    """
    assert module.next_after("9.9.0", contract=True) == "9.10.0"


def test_the_major_needs_a_named_consumer(run_script: RunScript, tmp_path: Path) -> None:
    """Мажор до единицы поднимает не выпуск, а появление первого потребителя.

    Это записано в договоре до первого потребителя и задним числом не вводится
    (113). Механизм требует назвать того, кто прибился, — иначе `1.0` было бы
    обещанием совместимости, данным никому.
    """
    tree(tmp_path)
    run = run_script("release.py", "--version", "10.0.0", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "первого потребителя" in run.text
    assert "--first-consumer" in run.text


def test_a_named_consumer_allows_the_major(run_script: RunScript, tmp_path: Path) -> None:
    """С названным потребителем мажор поднимается: обещание есть кому дать."""
    tree(tmp_path)
    run = run_script("release.py", "--version", "10.0.0", "--first-consumer", "o/r", cwd=tmp_path)
    assert run.code == 0, run.text
    assert "o/r" in run.text


def test_a_wrong_minor_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Номер, не следующий за текущим, отвергается с названным ожиданием."""
    tree(tmp_path)
    run = run_script("release.py", "--version", "9.50.0", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "ожидается 9.10.0" in run.text


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
    subprocess.run(["git", "tag", "v9.10.0"], cwd=tmp_path, check=True)
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
    и источником остаются они ([125](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/125-a-derived-file-is-not-a-store.md)).
    """
    tree(tmp_path)
    run = run_script("release.py", "--apply", cwd=tmp_path)
    assert run.code == 0, run.text
    assert (tmp_path / "changelog.d" / "released" / "9.10.0" / "a.added.md").is_file()
    assert not (tmp_path / "changelog.d" / "a.added.md").exists()
    assert (tmp_path / "CONTRACT_VERSION").read_text(encoding="utf-8").strip() == "9.10.0"
    tags = subprocess.run(
        ["git", "tag", "--list"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.split()
    assert tags == ["v9.10.0"]


def test_the_procedure_matches_the_contract() -> None:
    """Порядок выпуска в механизме тот же, что записан в договоре (029).

    Договор описывает порядок с самого начала; механизм обязан ему отвечать, а
    не заводить свой.
    """
    text = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    assert "## Порядок выпуска" in text
    assert "тег не переставляется" in text.lower()
