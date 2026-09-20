"""Инструмент, отданный наружу, назван на входе (правило 163).

Гейт судит не полноту описания, а НАЗВАН ЛИ инструмент: полнота — связность
текста, машине недоступная. Проверяется и обратная сторона — пока отдавать
нечего, вход обязан говорить это словом: молчание входа и отсутствие
механизмов снаружи неотличимы.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.conftest import ROOT, RunScript, load_script

module = load_script("check_shipped.py")
paths = load_script("paths.py")

#: Шапка помеченного инструмента: объявление стоит НАЧАЛОМ строки.
MARKED = f'"""{module.MARK}: берут прогоном, а не копией."""\n'


def tree(root: Path, *, says: str, marked: dict[str, str] | None = None) -> Path:
    """Дерево с входом и, возможно, помеченными инструментами."""
    (root / "README.md").write_text(says, encoding="utf-8")
    (root / "scripts").mkdir()
    (root / ".github" / "workflows").mkdir(parents=True)
    for where, text in (marked or {}).items():
        (root / where).write_text(text, encoding="utf-8")
    return root


def test_bare_strips_the_opening_markup(tmp_path: Path) -> None:
    """Голое начало строки: разметка докстроки, Python и YAML снимается."""
    assert module.bare(f'    """{module.MARK}: берут прогоном').startswith(module.MARK)
    assert module.bare(f"  # {module.MARK}").startswith(module.MARK)
    assert module.bare(f"#: {module.MARK}").startswith(module.MARK)
    assert not module.bare(f"MARK = «{module.MARK}»").startswith(module.MARK)


def test_declares_reads_the_head_only(tmp_path: Path) -> None:
    """Объявление живёт в шапке: ниже это слово внутри разбора."""
    вверху = tmp_path / "вверху.py"
    вверху.write_text(f'"""{module.MARK}."""\n', encoding="utf-8")
    внизу = tmp_path / "внизу.py"
    внизу.write_text("\n" * module.HEAD_LINES + f"# {module.MARK}\n", encoding="utf-8")
    assert module.declares(вверху)
    assert not module.declares(внизу)


def test_shipped_lists_marked_tools_by_address(tmp_path: Path) -> None:
    """Список помеченного — адреса относительно корня, по одному на инструмент."""
    root = tree(
        tmp_path,
        says="# Проект\n",
        marked={
            "scripts/раздача.py": MARKED,
            "scripts/своё.py": '"""Обычный механизм."""\n',
            ".github/workflows/общий.yml": f"# {module.MARK}\n",
        },
    )
    assert module.shipped(root) == [".github/workflows/общий.yml", "scripts/раздача.py"]


def test_entrance_reads_the_visitor_document(tmp_path: Path) -> None:
    """Вход читается целиком: назвать инструмент можно в любом его месте."""
    root = tree(tmp_path, says="# Проект\n\nвнизу: `scripts/раздача.py`\n")
    assert "scripts/раздача.py" in module.entrance(root)


def test_apart_is_silent_when_the_entrance_agrees() -> None:
    """Сходится — молчание; расходится — названо чем именно."""
    assert module.apart(f"## {module.SAYS_EMPTY}", []) == ""
    assert module.apart("`scripts/раздача.py`", ["scripts/раздача.py"]) == ""
    assert "не названо" in module.apart("# Проект", ["scripts/раздача.py"])


def test_an_empty_shipment_must_be_named(tmp_path: Path) -> None:
    """Помечать нечего — и вход об этом молчит: отвергается.

    Это и есть работа гейта сегодня: помеченных инструментов ноль, и зелень на
    пустом предмете не проверяла бы ничего (075).
    """
    root = tree(tmp_path, says="# Проект\n\nМеханизмы конвейера.\n")
    assert module.main(["--root", str(root)]) == module.EXIT_REJECTED


def test_an_empty_shipment_named_passes(tmp_path: Path) -> None:
    """Пустота, названная словом, законна: это ответ, а не умолчание (154)."""
    root = tree(tmp_path, says=f"# Проект\n\n## Состояние: {module.SAYS_EMPTY}\n")
    assert module.main(["--root", str(root)]) == module.EXIT_OK


def test_a_marked_tool_must_be_named_at_the_entrance(tmp_path: Path) -> None:
    """Помеченный инструмент, не названный на входе, отвергается."""
    root = tree(
        tmp_path,
        says="# Проект\n\nБерут прогоном.\n",
        marked={"scripts/раздача.py": MARKED},
    )
    assert module.main(["--root", str(root)]) == module.EXIT_REJECTED


def test_a_marked_tool_named_at_the_entrance_passes(tmp_path: Path) -> None:
    """Назван адресом — сходится."""
    root = tree(
        tmp_path,
        says="# Проект\n\nПодключается `scripts/раздача.py`.\n",
        marked={"scripts/раздача.py": MARKED},
    )
    assert module.main(["--root", str(root)]) == module.EXIT_OK


def test_the_entrance_cannot_say_both(tmp_path: Path) -> None:
    """Вход не может одновременно называть инструмент и объявлять пустоту.

    Это класс, ради которого гейт и заведён: объявление отстаёт от дерева
    молча, и читатель верит объявлению (005).
    """
    root = tree(
        tmp_path,
        says=f"# Проект\n\n`scripts/раздача.py`\n\n## Состояние: {module.SAYS_EMPTY}\n",
        marked={"scripts/раздача.py": MARKED},
    )
    assert module.main(["--root", str(root)]) == module.EXIT_REJECTED


def test_a_yaml_run_declares_itself_too(tmp_path: Path) -> None:
    """Наружу отдают и прогоны: маркер читается из комментария YAML."""
    root = tree(
        tmp_path,
        says="# Проект\n\nБерут `.github/workflows/общий.yml`.\n",
        marked={".github/workflows/общий.yml": f"# {module.MARK}: зовут через workflow_call.\n"},
    )
    assert module.main(["--root", str(root)]) == module.EXIT_OK


def test_the_mark_is_the_start_of_a_line_not_a_word_inside_it(tmp_path: Path) -> None:
    """Маркер — объявление, а не упоминание.

    Файл, который ГОВОРИТ о маркере (как сам гейт и его прогоны), наружу себя
    не объявляет: иначе гейт пометил бы сам себя и покраснел на собственном
    определении.
    """
    root = tree(
        tmp_path,
        says="# Проект\n\nМеханизмы конвейера.\n",
        marked={"scripts/разбор.py": f'"""Гейт ищет слово {module.MARK} в шапке."""\n'},
    )
    assert module.main(["--root", str(root)]) == module.EXIT_REJECTED, (
        "упоминание маркера объявлением не является — значит, помечено ноль, "
        "и отвергается уже молчание входа"
    )


def test_a_mark_below_the_head_is_not_a_declaration(tmp_path: Path) -> None:
    """Ниже шапки маркер — слово внутри разбора, а не объявление."""
    низко = "\n" * module.HEAD_LINES + f"# {module.MARK}\n"
    root = tree(tmp_path, says="# Проект\n", marked={"scripts/поздно.py": низко})
    assert module.main(["--root", str(root)]) == module.EXIT_REJECTED


def test_a_missing_entrance_is_the_third_outcome(tmp_path: Path) -> None:
    """Входа нет — сверять не с чем: третий исход, а не «сходится» (039)."""
    (tmp_path / "scripts").mkdir()
    assert module.main(["--root", str(tmp_path)]) == module.EXIT_BROKEN


def test_nowhere_to_look_is_the_third_outcome(tmp_path: Path) -> None:
    """Ни одного каталога поиска — «не помечено ничего» было бы незнанием."""
    (tmp_path / "README.md").write_text("# Проект\n", encoding="utf-8")
    assert module.main(["--root", str(tmp_path)]) == module.EXIT_BROKEN


def test_the_live_tree_agrees_with_its_entrance(run_script: RunScript) -> None:
    """Живое дерево: вход называет ровно то, что помечено, — и ничего сверх.

    ЗАМЕР БОЛЬШЕ НЕ ВПИСАН СЮДА ЧИСЛОМ. До 19.09.2026 здесь стояло «помечено
    ноль, и вход это говорит»: передача была отложена, и проверка держала
    объявленную пустоту. Пустота кончилась — девять шагов вынесены в
    переиспользуемые прогоны и помечены, — и вписанное число стало бы неверным
    на следующем же вынесенном шаге
    ([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).
    Проверяется теперь ОТНОШЕНИЕ: помеченное и названное на входе совпадают, а
    какое из двух состояний нынешнее — решает дерево, а не этот файл.
    """
    done = run_script("check_shipped.py")
    assert done.code == module.EXIT_OK, done.err or done.out
    entrance = module.entrance(ROOT)
    marked = module.shipped(ROOT)
    if marked:
        assert module.SAYS_EMPTY not in entrance, (
            "вход объявляет пустоту, а помеченное есть — отстающий вход читают как дерево"
        )
        assert not module.apart(entrance, marked), "вход не называет всё помеченное"
    else:
        assert module.SAYS_EMPTY in entrance, "пустота законна, но обязана быть названа (154)"


def history(root: Path, *, tag_first: bool) -> Path:
    """Дерево с настоящей историей: помеченный файл ДО или ПОСЛЕ тега.

    История настоящая, а не подделанный ответ git: на подделке проверка
    подтверждала бы согласие кода с нашим представлением о тегах, а не с git
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    """
    (root / "scripts").mkdir(exist_ok=True)
    (root / "README.md").write_text("# вход\n", encoding="utf-8")
    run = ["git", "-C", str(root)]
    subprocess.run([*run, "init", "--quiet", "-b", "main"], check=True)
    subprocess.run([*run, "config", "user.email", "т@т"], check=True)
    subprocess.run([*run, "config", "user.name", "т"], check=True)

    def commit(message: str) -> None:
        subprocess.run([*run, "add", "-A"], check=True, capture_output=True)
        subprocess.run([*run, "commit", "--quiet", "-m", message], check=True)

    if tag_first:
        commit("до выпуска")
        subprocess.run([*run, "tag", "v1.0.0"], check=True)
    (root / "scripts" / "раздача.py").write_text(MARKED, encoding="utf-8")
    commit("помеченный инструмент")
    if not tag_first:
        subprocess.run([*run, "tag", "v1.0.0"], check=True)
    return root


def test_at_ref_reads_history_not_the_tree(tmp_path: Path) -> None:
    """Спрашивается, что несёт ССЫЛКА, а не что лежит в рабочем дереве.

    Между этими двумя ответами и живёт предмет: у нас файл есть, у
    потребителя по названному тегу — нет.
    """
    root = history(tmp_path, tag_first=True)
    assert "scripts/раздача.py" not in (module.at_ref("v1.0.0", root) or set())
    assert "scripts/раздача.py" in (module.at_ref("HEAD", root) or set())


def test_at_ref_does_not_escape_non_ascii_names(tmp_path: Path) -> None:
    """Имя с не-ASCII знаками приходит как есть, а не в кавычках с escape-ами.

    Иначе сверка молча решила бы, что выпуск не несёт НИЧЕГО с русским
    именем, — то есть отказывала бы зря и объясняла бы это правдоподобно.
    """
    carried = module.at_ref("HEAD", history(tmp_path, tag_first=False)) or set()
    assert "scripts/раздача.py" in carried
    assert not any(one.startswith('"') for one in carried), carried


def test_an_unknown_ref_is_not_an_empty_release(tmp_path: Path) -> None:
    """Ссылки не видно — это незнание, а не «выпуск пуст» (045)."""
    root = history(tmp_path, tag_first=False)
    assert module.at_ref("v9.9.9", root) is None
    with pytest.raises(module.NotRun, match=re.escape("v9.9.9")):
        module.unreleased("v9.9.9", root)


def test_unreleased_names_what_the_pin_does_not_carry(tmp_path: Path) -> None:
    """Помеченное, которого тег не несёт, названо поимённо (046)."""
    assert module.unreleased("v1.0.0", history(tmp_path, tag_first=True)) == ["scripts/раздача.py"]


def test_unreleased_is_empty_when_the_pin_carries_everything(tmp_path: Path) -> None:
    """Вторая половина: тег несёт помеченное — находок нет.

    Без неё предикат был бы неотличим от «всегда отказывать», а такой учат
    обходить (051).
    """
    assert module.unreleased("v1.0.0", history(tmp_path, tag_first=False)) == []
