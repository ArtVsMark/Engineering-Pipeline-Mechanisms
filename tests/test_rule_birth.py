"""Судьба правила проверяется тем, что гейт обязан отвергнуть.

Прогоняется каждый объявленный исход, включая третий — «не отработал»
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md),
[145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).

ОТДЕЛЬНО ДЕРЖИТСЯ ТО, ЧЕГО ГЕЙТ НЕ ДЕЛАЕТ: он не решает, правило это или нет.
Оба ответа проходят, и ни один не считается лучше другого — иначе он выбирал бы
за человека (154).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, git, load_script

module = load_script("check_rule_birth.py")

BROKEN: Final = 2
FOUND: Final = 1
CLEAN: Final = 0

SAID_OWN: Final = "**Каталогу:** своё — предмет наш, у каталога такого нет"
SAID_SENT: Final = "**Каталогу:** предложено — a-red-that-survived-the-merge"


def tree(tmp_path: Path, *, queue: tuple[str, ...] = ()) -> Path:
    """Дерево с общей веткой, очередью предложений и одной записью решения."""
    root = tmp_path / "tree"
    (root / "docs" / "decisions").mkdir(parents=True)
    (root / ".rules").mkdir()
    (root / ".rules" / "proposals.json").write_text(
        json.dumps(
            {"schema": "1.1", "proposals": [{"slug": one} for one in queue]}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    (root / "docs" / "decisions" / "001-старое.md").write_text(
        "прежнее решение\n", encoding="utf-8"
    )
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "Artem Markitanov")
    git(root, "config", "user.email", "a@b.c")
    git(root, "add", "-A")
    git(root, "commit", "-m", "основание")
    return root


def run(root: Path) -> int:
    """Заход гейта по подготовленному дереву."""
    done = subprocess.run(
        ["git", "diff", "--diff-filter=A", "--name-only", "-z", "main..HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    new = [
        path
        for path in done.stdout.split("\0")
        if path.startswith("docs/decisions/") and path.endswith(".md")
    ]
    told = module.missing(new, module.queued(root / ".rules" / "proposals.json"), root)
    return FOUND if told else CLEAN


def born(root: Path, name: str, body: str) -> None:
    """Добавляет запись решения и коммитит её."""
    (root / "docs" / "decisions" / name).write_text(body, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-m", f"решение {name}")


def test_a_record_declaring_it_is_ours_passes(tmp_path: Path) -> None:
    """Ответ «своё» с причиной — законный, и гейт его пропускает.

    Он не решает, правило это или нет: оба ответа равны, и предпочесть один
    значило бы выбирать за человека (154).
    """
    root = tree(tmp_path)
    git(root, "checkout", "-b", "work")
    born(root, "002-своё.md", f"# 002\n\n{SAID_OWN}\n")
    assert run(root) == CLEAN


def test_a_record_naming_a_queued_slug_passes(tmp_path: Path) -> None:
    """Ответ «предложено» проходит, если слаг ЕСТЬ в очереди предложений."""
    root = tree(tmp_path, queue=("a-red-that-survived-the-merge",))
    git(root, "checkout", "-b", "work")
    born(root, "002-предложено.md", f"# 002\n\n{SAID_SENT}\n")
    assert run(root) == CLEAN


def test_a_record_without_the_line_is_refused(tmp_path: Path) -> None:
    """Молчание отвергается — это и есть предмет гейта.

    Пустая очередь предложений неотличима от «никто не спросил», и различить их
    можно только ответом в самой записи (045).
    """
    root = tree(tmp_path)
    git(root, "checkout", "-b", "work")
    born(
        root, "002-молчит.md", "# 002\n\nКонтекст, решение, последствия — и ни слова о каталоге.\n"
    )
    assert run(root) == FOUND


def test_a_promise_without_a_proposal_is_refused(tmp_path: Path) -> None:
    """«Предложено» при пустой очереди — обещание того, чего не отправили.

    Это хуже молчания: молчание видно, а ложное обещание выглядит ответом.
    """
    root = tree(tmp_path)
    git(root, "checkout", "-b", "work")
    born(root, "002-обещано.md", f"# 002\n\n{SAID_SENT}\n")
    assert run(root) == FOUND


def test_an_empty_reason_is_not_an_answer(tmp_path: Path) -> None:
    """«Своё —» без причины ответом не считается (154)."""
    root = tree(tmp_path)
    git(root, "checkout", "-b", "work")
    born(root, "002-пусто.md", "# 002\n\n**Каталогу:** своё — \n")
    assert run(root) == FOUND


def test_a_third_kind_of_answer_is_not_accepted(tmp_path: Path) -> None:
    """«Потом посмотрим» — молчание, записанное словами, и его тоже отвергают."""
    root = tree(tmp_path)
    git(root, "checkout", "-b", "work")
    born(root, "002-потом.md", "# 002\n\n**Каталогу:** потом посмотрим\n")
    assert run(root) == FOUND


def test_a_change_without_a_decision_is_clean(tmp_path: Path) -> None:
    """Изменение без записи решения этому правилу не подчиняется.

    Отсутствие предмета ЗДЕСЬ законно — в отличие от гейта, которому предмет
    обязан найтись: у этого есть свой прогон на подделках (075).
    """
    root = tree(tmp_path)
    git(root, "checkout", "-b", "work")
    (root / "файл.txt").write_text("работа без решения\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-m", "просто работа")
    assert run(root) == CLEAN


def test_an_unreadable_queue_is_the_third_outcome(tmp_path: Path) -> None:
    """Очередь предложений не прочитана — «не отработал», а не «ответ есть» (039)."""
    with pytest.raises(module.NotRun, match="очередь предложений не прочитана"):
        module.queued(tmp_path / "нет-такого.json")


def test_a_missing_base_is_the_third_outcome(capsys: pytest.CaptureFixture[str]) -> None:
    """База не разрешается — «не отработал», а не «записей не добавлено».

    Прогоняется ТОЧКА ВХОДА, а не только подъём отказа: объявленный исход и
    поднятое исключение — разные вещи, и снаружи проверяется первое (145).
    """
    with pytest.raises(module.NotRun, match="состав изменения не прочитан"):
        module.added("не-существующая-база")
    assert module.main(["--base", "не-существующая-база"]) == BROKEN
    assert "гейт не отработал" in capsys.readouterr().err


def test_an_unreadable_queue_reaches_the_entry_point(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Нечитаемая очередь тоже доезжает до исхода «не отработал», а не до зелёного."""
    root = tree(tmp_path)
    git(root, "checkout", "-b", "work")
    born(root, "002-своё.md", f"# 002\n\n{SAID_OWN}\n")
    (root / ".rules" / "proposals.json").unlink()
    assert module.main(["--base", "main", "--root", str(root)]) == BROKEN
    assert "гейт не отработал" in capsys.readouterr().err


def test_the_gate_reads_its_own_record() -> None:
    """Решение, заводящее этот гейт, само несёт требуемую строку.

    Механизм, не подчиняющийся собственному требованию, учит его обходить.
    """
    text = (ROOT / "docs" / "decisions" / "028-a-decision-names-the-fate-of-its-rule.md").read_text(
        encoding="utf-8"
    )
    said = module.fate(text)
    assert said is not None, "своя же запись молчит о судьбе правила"
    assert said[0] == "своё" and said[1], said


def test_a_slug_in_backticks_is_still_the_slug(tmp_path: Path) -> None:
    """Слаг в обратных кавычках гейт узнаёт: он судит существо, а не разметку.

    ИМЯ В ЭТОМ ПРОЕКТЕ ПИШУТ В КАВЫЧКАХ ПОВСЮДУ, и первая же запись с ответом
    «предложено» была написана так — `имя`. с точкой на конце. Гейт брал первое
    слово целиком, видел «`имя`.» и честного ответа не признавал: красное на
    законном
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    До 17.09.2026 у этой ветки разбора не было живого предмета вовсе — очередь
    предложений стояла пустой, и проверял её только тест на подделке.
    """
    root = tree(tmp_path, queue=("a-red-that-survived-the-merge",))
    git(root, "checkout", "-b", "work")
    born(
        root,
        "002-в-кавычках.md",
        "# 002\n\n**Каталогу:** предложено — `a-red-that-survived-the-merge`. "
        "И дальше проза о предмете.\n",
    )
    assert run(root) == CLEAN


def test_markup_does_not_invent_a_slug(tmp_path: Path) -> None:
    """Снятие оформления НЕ превращает чужой слаг в свой.

    Обратная половина: гейт стал мягче к разметке и не должен стать мягче к
    существу. Имени, которого в очереди нет, кавычки не помогают.
    """
    root = tree(tmp_path, queue=("a-red-that-survived-the-merge",))
    git(root, "checkout", "-b", "work")
    born(root, "002-чужой.md", "# 002\n\n**Каталогу:** предложено — `совсем-другое-имя`.\n")
    assert run(root) == FOUND


def test_slug_of_takes_the_name_and_drops_the_dressing() -> None:
    """Разбор слага прогнан НАПРЯМУЮ, а не только через вердикт гейта.

    Через вердикт проверяется, что гейт в целом не отказывает на верном; здесь
    — что именно снимается. Разница важна: пройди оформление мимо, вердикт всё
    равно мог бы сойтись по другой причине.
    """
    assert module.slug_of("`имя-правила`. И проза дальше") == "имя-правила"
    assert module.slug_of("имя-правила — причина") == "имя-правила"
    assert module.slug_of("«имя-правила»,") == "имя-правила"
    assert module.slug_of("(имя-правила)") == "имя-правила"


def test_slug_of_answers_an_empty_line_without_guessing() -> None:
    """Пустая строка даёт пустой слаг, а не падение и не выдуманное имя.

    Пустое имя в очереди не найдётся, и отказ придёт от сверки — то есть от
    того, кто про очередь знает, а не от разбора строки (045).
    """
    assert module.slug_of("") == ""
    assert module.slug_of("   ") == ""
    assert module.slug_of("``") == ""


def test_an_empty_slug_is_not_a_match(tmp_path: Path) -> None:
    """Ответ «предложено» с пустым именем отвергается.

    Сверка идёт ВХОЖДЕНИЕМ в текст очереди, а пустая строка входит в любой
    текст: ответ «предложено — ``» проходил гейт целиком, и очередь при этом
    могла быть любой. Нашёл внешний взгляд на #428 — при том что соседний тест
    держал, что разбор даёт на такой строке пустое имя, и последствия этого не
    замечал: зелёное на подделке тоже гипотеза
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    """
    root = tree(tmp_path, queue=("a-red-that-survived-the-merge",))
    git(root, "checkout", "-b", "work")
    born(root, "002-пусто.md", "# 002\n\n**Каталогу:** предложено — ``\n")
    assert run(root) == FOUND
