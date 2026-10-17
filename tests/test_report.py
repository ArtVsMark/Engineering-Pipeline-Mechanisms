"""Обрезка вывода: сказать, что урезано, и насколько.

Молчаливая обрезка выглядит как полный ответ — читатель ищет причину в первых
трёхстах знаках, когда она в четырёхсот первом. Копий обрезки было четыре, у
каждого механизма своя; здесь проверяется и поведение, и то, что копия одна.
"""

import ast
import re
from typing import Final

import pytest
import report
import yaml

from tests.conftest import ROOT, code_files, load_script, walk

runs_series = load_script("runs_series.py")


def test_short_text_is_left_alone() -> None:
    """Короткий вывод не трогают: обрезки не было — и говорить не о чем."""
    assert report.cut("коротко") == "коротко"


def test_long_text_says_how_much_was_cut() -> None:
    """Урезанный вывод называет полный объём, а не ставит многоточие."""
    cut = report.cut("я" * 400)
    assert cut.endswith("(обрезано, всего 400 знаков)")
    assert len(cut) < 400 + 40


def test_the_limit_is_the_boundary_not_a_suggestion() -> None:
    """На самой границе обрезки нет: 300 знаков — ещё полный ответ."""
    assert report.cut("я" * report.LIMIT) == "я" * report.LIMIT


#: С какой длины срез строки — обрезка вывода, а не разбор её формы. Замер
#: 17.10.2026 по коду механизмов и хукам окна: срезы формы — сокращение хэша
#: (7, 8, 12 знаков) и время из штампа ISO (`[11:19]`); срезы текста — 60, 70,
#: 80 и 300 знаков. Граница лежит между ними. Прежде она стояла на 100 и только
#: у верхнего конца: хвост `[-300:]` и короткие срезы причин отказа проходили
#: молча (взгляд на #1462). ПРЕДЕЛ НАЗВАН: срез именованной границей
#: (`text[:limit]`) признак не видит — так режет и сам `report.cut`.
CUT_FROM: Final = 20


def bound(node: ast.expr | None) -> int | None:
    """Постоянная граница среза со знаком; не число — `None`."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = bound(node.operand)
        return None if inner is None else -inner
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def silent_cuts(source: str) -> list[int]:
    """Строки, где строка режется на месте постоянной границей не короче `CUT_FROM`."""
    return sorted(
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Slice)
        and any(
            (one := bound(end)) is not None and abs(one) >= CUT_FROM
            for end in (node.slice.lower, node.slice.upper)
        )
    )


def test_no_mechanism_cuts_output_silently() -> None:
    """Гейт на дрейф: срез строки-вывода не пишут заново в каждом механизме.

    Копий было четыре — шаг открытия, гейт журнала, транспорт и сборка тела
    уплотнения, — и каждая обрезала молча. Разошлись бы они так же молча.

    Копия в стороже толчка — намеренная, а не пятая: хук не импортирует дерево
    (046), и срез у него назван. Совпадение с каноном держит
    `tests/test_push_guard.py::test_the_cut_is_the_transport_one`.
    """
    # Корни — из `paths.SOURCES` и хуки окна: транспорт был среди тех четырёх
    # копий (#1254), а механизм тоже предмет правил о механизмах (220, #1439).
    found = {
        path.relative_to(ROOT).as_posix(): lines
        for path in code_files()
        if path.name != "report.py" and (lines := silent_cuts(path.read_text(encoding="utf-8")))
    }
    assert not found, (
        f"вывод режется на месте, а не общим механизмом (016): {found} — "
        "`report.cut` для начала, `report.tail` для конца"
    )


@pytest.mark.parametrize(
    ("source", "silent"),
    [
        ("said[:300]", True),
        ("said.strip()[-300:]", True),
        ("script[:60]", True),
        ("title[:CUT_FROM]", False),
        ("sha[:7]", False),
        ("sha[:12]", False),
        ("stamp[11:19]", False),
        ("word[2:]", False),
        ("lines[-1]", False),
    ],
    ids=[
        "начало",
        "хвост",
        "короткий",
        "именованный",
        "хэш",
        "длинный-хэш",
        "время",
        "форма",
        "индекс",
    ],
)
def test_the_cut_sign_tells_text_from_form(source: str, silent: bool) -> None:
    """Обе половины признака: срез текста виден с любого конца, срез формы — нет."""
    assert bool(silent_cuts(source)) is silent


def test_a_tail_says_how_much_was_cut() -> None:
    """Конец вывода остаётся, и сказано, сколько было: причина отказа — последней строкой."""
    cut = report.tail("а" * 100 + "причина", 20)
    assert cut.endswith("причина") and "обрезано, всего 107 знаков" in cut
    assert report.tail("коротко", 300) == "коротко"


def test_the_mode_prefix_speaks_in_the_diagnostic_stream(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Приставка режима идёт в `stderr`, а не в ответ механизма.

    ЭТО ПРО ПОТОК, А НЕ ПРО ТЕКСТ. У части механизмов `stdout` читает не
    человек, а оболочка: шаг взгляда берёт очередь как
    ``numbers=$(python scripts/unlooked.py --queue)``. Приставка на том же
    потоке давала ВТОРУЮ строку, обе уезжали в `$GITHUB_OUTPUT`, площадка
    отвечала ``Invalid format '[]'`` и роняла джоб — 18 и 19.09.2026.
    """
    report.announce(True)
    said = capsys.readouterr()
    assert report.DRY in said.err, "приставка режима не названа вовсе (045)"
    assert said.out == "", f"приставка режима попала в ответ механизма: {said.out!r}"


def test_a_live_run_names_nothing_in_either_stream(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Вторая половина: боевой заход молчит в ОБОИХ потоках.

    Без неё проверка прошла бы и у приставки, стоящей всегда, — а такая ничего
    не различает (051).
    """
    report.announce(False)
    said = capsys.readouterr()
    assert said.out == "" and said.err == ""


#: Как оболочка сливает `stderr` в `stdout` или оба потока в один файл:
#: `2>&1` (и с пробелом, `2>& 1`), `&>`/`&>>` и `>&слово` без номера потока
#: впереди (`cmd >& "$F"`). `>&2` и `1>&2` — обратное направление, в выходы
#: оно ничего не несёт, и цифра после `>&` из счёта выводит (`85ec323`).
#: ГРАНИЦА: номер потока в переменной (`>&$fd`, `>&"$FD"`) от файла в
#: переменной (`>& "$F"`) не отличить, и оба считаются слиянием — ложная
#: тревога на шаге, пишущем выходы, дешевле пропуска, и в дереве таких нет
#: (`69b9bcf`).
MERGE_RE: Final = re.compile(r"2>&\s*1(?!\d)|&>|(?<![\d&])>&\s*(?![\d\s-])\S")


def merges_streams(command: str) -> bool:
    """Сливает ли команда оба потока в один.

    `|&` разбор команд режет по черте, и от него остаётся команда, начатая с
    `&`; её и узнаём по первому знаку.
    """
    return bool(MERGE_RE.search(command)) or command.startswith("&")


def run_steps() -> list[tuple[str, list[str]]]:
    """Все шаги прогонов с их командами — комментарии вынуты."""
    found: list[tuple[str, list[str]]] = []
    for path in walk(ROOT / ".github" / "workflows", "*.yml"):
        for job, body in (
            yaml.safe_load(path.read_text(encoding="utf-8")).get("jobs") or {}
        ).items():
            for step in body.get("steps") or []:
                said = runs_series.commands(str(step.get("run") or ""))
                where = f"{path.name}:{job} «{step.get('name')}»"
                found.append((where, said))
    return found


def test_a_step_writing_its_outputs_never_merges_the_streams() -> None:
    """Шаг, пишущий в `$GITHUB_OUTPUT`, не сливает потоки ни в одной команде.

    Механизм разводит потоки сам (`report.announce` пишет в `stderr`), и
    шаг прогона не вправе слить их обратно. Замер 23.09.2026: ровно так
    верификатор взгляда отвечал «Invalid format» на каждом запуске — `2>&1`
    увозил приставку пробного захода в выходы шага (#673).

    СУДИТСЯ ШАГ, А НЕ ФОРМА ЗАПИСИ. Прежняя редакция ловила одну — файл
    `>"$ИМЯ" 2>&1` и затем `cat "$ИМЯ" >> "$GITHUB_OUTPUT"`; переменная
    `x=$(cmd 2>&1)` с `echo "k=$x"`, скобки `{ …; } 2>&1`, `|& tee` и
    прямое `cmd >> "$GITHUB_OUTPUT" 2>&1` проходили (`9a59aa8`). Проследить
    поток до выходов по всем формам оболочки нельзя, а шаг, пишущий выходы,
    сливать потоки не обязан ни для чего — поэтому запрет на весь шаг.
    Комментарии вынуты тем же разбором, что у счёта цены прогонов.

    Замер 24.09.2026: шагов в прогонах 187, пишущих выходы — 12, сливающих
    потоки — 15, и оба сразу — ни одного. Слова `2>&1` и `GITHUB_OUTPUT`
    вместе стоят в одном шаге, и `2>&1` там — только в комментарии.

    ГРАНИЦА: слияние, собранное из частей (`exec 2>&1` в начале шага тоже
    ловится, а переменная с текстом `2>&1` — нет), машина не видит (057).
    """
    steps = run_steps()
    writing = [(where, said) for where, said in steps if any("GITHUB_OUTPUT" in c for c in said)]
    assert writing, "шагов, пишущих $GITHUB_OUTPUT, нет — предмет проверки исчез (075)"
    merging = [where for where, said in steps if any(merges_streams(c) for c in said)]
    assert merging, "шагов со слиянием потоков нет вовсе — вторая половина проверки пуста (075)"
    found = [where for where, said in writing if any(merges_streams(c) for c in said)]
    assert not found, "шаг пишет выходы и сливает потоки: " + "; ".join(found)


@pytest.mark.parametrize(
    ("command", "merges"),
    [
        ("cmd 2>&1", True),
        ("cmd 2>& 1", True),
        ('cmd &> "$F"', True),
        ('cmd &>> "$F"', True),
        ('cmd >& "$F"', True),
        ('cmd >&"$F"', True),
        ("& tee -a out", True),
        ("cmd >&2", False),
        ("cmd 1>&2", False),
        ("cmd 2>&12", False),
        ("cmd >&-", False),
        ('echo "a && b"', False),
        # ГРАНИЦА, закреплённая примером (`4d85855`): номер потока в переменной
        # считается слиянием — от файла в переменной его не отличить.
        ("cmd >&$fd", True),
        ('cmd >&"$FD"', True),
    ],
)
def test_the_merge_form_is_pinned_by_examples(command: str, merges: bool) -> None:
    """Выражение слияния закреплено примерами обеих сторон (`ab75ecc`).

    В дереве совпадений ноль, и порча выражения оставалась бы зелёной на
    гейте по дереву; здесь каждая форма и каждое исключение названы.
    """
    assert merges_streams(command) is merges


def test_a_pipe_with_stderr_leaves_the_mark_merges_streams_reads() -> None:
    """`|&` узнаётся связкой двух функций: разбор команд и предикат слияния (`bba2855`).

    Пример `"& tee -a out"` проверял только остаток, написанный руками; что
    `commands` отдаёт от `cmd |& tee` ровно такой остаток — не закреплял никто.
    """
    said = runs_series.commands('cmd |& tee -a "$GITHUB_OUTPUT"')
    assert said == ["cmd", '& tee -a "$GITHUB_OUTPUT"'], said
    assert any(merges_streams(one) for one in said)
