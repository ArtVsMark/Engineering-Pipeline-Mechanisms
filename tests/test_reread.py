"""Подпись под перечитыванием проверяется подделанной подписью.

Предмет гейта — утверждение, которое нельзя увидеть в дереве: «я перечитал
ответы». Снаружи честное перечитывание и механическое поднятие числа выглядят
одинаково — файл изменён, число выросло, дрейф замолчал. Поэтому обе стороны
подделываются
([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import RunScript, load_script

module = load_script("check_reread.py")


def answers(read_at: str, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ответы проекта: номер прочитанной выгрузки и сами ответы."""
    return {
        "schema": "1.3",
        "answers_to": read_at,
        "rules": rules if rules is not None else {"001": {"status": "active"}},
    }


def test_a_raised_number_without_a_touched_answer_is_refused() -> None:
    """Номер поднят, ответы не тронуты — подпись под несделанным.

    Механическое поднятие гасит сигнал дрейфа: после него молчание означает
    «ответы под новой выгрузкой», а они под прежней.
    """
    said = module.lonely(answers("1.6"), answers("1.7"))
    assert said
    assert "1.6" in said and "1.7" in said, "оба числа названы, а не «номер сдвинулся»"


def test_a_raised_number_with_a_touched_answer_passes() -> None:
    """Номер поднят и ответы тронуты — это и есть перечитывание."""
    assert not module.lonely(answers("1.6"), answers("1.7", {"001": {"status": "not-applicable"}}))


def test_a_touched_answer_without_raising_the_number_passes() -> None:
    """Обратное направление законно: починка одной строки перечитыванием не является.

    Гейт судит одно направление, и сосед назван, а не подразумевается
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    assert not module.lonely(answers("1.6"), answers("1.6", {"001": {"status": "off"}}))


def test_an_untouched_file_passes() -> None:
    """Ничего не менялось — сказать нечего."""
    assert not module.lonely(answers("1.7"), answers("1.7"))


def test_an_unreadable_base_is_the_third_outcome() -> None:
    """База не прочитана — гейт не отработал, а не «подпись честна» (045)."""
    with pytest.raises(module.NotRun):
        module.at("нет-такой-ревизии", ".rules/bindings.json")


def test_the_refusal_names_both_repairs() -> None:
    """Отказ называет обе починки: перечитать или вернуть номер (154).

    Названная одна оставляла бы вторую на догадку читателя, а они
    противоположны по смыслу.
    """
    said = module.lonely(answers("1.6"), answers("1.7"))
    assert "перечитайте" in said.lower() and "верните номер" in said.lower()


def test_a_lowered_number_is_a_different_statement_and_passes() -> None:
    """Понижение номера — другое утверждение, и оно законно.

    Им говорят «наши ответы сняты против выгрузки постарше, чем мы думали».
    Подписью под несделанным оно не является — наоборот, снимает её. Прежде
    сравнение шло на неравенство: понижение отвергалось наравне с подъёмом, а
    сообщение всё равно говорило «поднят», то есть гейт обвинял в том, чего не
    было. Нашёл внешний взгляд на #279.
    """
    assert not module.lonely(answers("1.7"), answers("1.6"))


def test_a_two_digit_minor_is_compared_by_number_not_by_text() -> None:
    """«1.10» новее «1.9», хотя по строке — младше.

    Сравнение текстом объявило бы подъём понижением на первой же двузначной
    минорной, и гейт замолчал бы ровно там, где ряд вырос.
    """
    said = module.lonely(answers("1.9"), answers("1.10"))
    assert said, "двузначная минорная прочитана как понижение"
    assert module.order("1.10") > module.order("1.9")


def repo_with(tmp_path: Path, said: dict[str, Any]) -> Path:
    """Крошечный репозиторий с ответами проекта на общей ветке."""
    root = tmp_path / "дерево"
    (root / ".rules").mkdir(parents=True)
    (root / ".rules" / "bindings.json").write_text(
        json.dumps(said, ensure_ascii=False), encoding="utf-8"
    )
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "a@b"),
        ("config", "user.name", "подделка"),
        ("add", "-A"),
        ("commit", "-qm", "ответы"),
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return root


def test_the_gate_refuses_a_lonely_raise_when_it_is_run(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Гейт ПРОГОНЯЕТСЯ по пути отказа, а не только разбирается по частям.

    Чистые функции проверяли решение, но не проводку: заход мог решить
    «отвергнуть» и вернуть ноль, и набор этого бы не заметил. Ровно этот класс
    за смену уже случался дважды
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
    """
    root = repo_with(tmp_path, answers("1.6"))
    (root / ".rules" / "bindings.json").write_text(
        json.dumps(answers("1.7"), ensure_ascii=False), encoding="utf-8"
    )
    done = run_script("check_reread.py", "--base", "main", cwd=root)
    assert done.code == module.EXIT_REJECTED, done.text
    assert "перечитыван" in done.text


def test_the_gate_passes_a_raise_that_carries_its_work(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Обратная сторона того же прогона: честный подъём проходит (097)."""
    root = repo_with(tmp_path, answers("1.6"))
    (root / ".rules" / "bindings.json").write_text(
        json.dumps(answers("1.7", {"001": {"status": "off"}}), ensure_ascii=False), encoding="utf-8"
    )
    done = run_script("check_reread.py", "--base", "main", cwd=root)
    assert done.code == module.EXIT_OK, done.text
