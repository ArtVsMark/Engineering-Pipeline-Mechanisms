"""Ответ «неприменимо» держится исполняемым предикатом, а не ручным перемером (#1171).

Ответ называет границу, при которой станет ложным (184), и предикат по дереву
(205). Пока предикат жил прозой в `.rules/bindings.json`, его перемеряли рукой
— и пропустили: подмена файла появилась 05.10.2026 (#1154), ответ на 066 после
перемера 02.10 говорил «станет ложным на первой подмене», и никто его не
перечитал. Здесь каждая команда из `.rules/inapplicable.json` исполняется на
каждом изменении, и новая строка вывода — красное: условие вступления
наступило, ответ перечитывается.
"""

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePath
from typing import Any, Final

import pytest

from tests.conftest import ROOT, load_script

paths = load_script("paths.py")

#: Ответ, чей предикат исполняется здесь.
INAPPLICABLE_STATUS: Final = "not-applicable"


def predicates() -> dict[str, Any]:
    """Таблица предикатов: исполняемые и названные немеханизуемыми."""
    said: dict[str, Any] = json.loads((ROOT / paths.INAPPLICABLE).read_text(encoding="utf-8"))
    return said


def answers() -> dict[str, Any]:
    """Ответы проекта по правилам каталога."""
    said: dict[str, Any] = json.loads((ROOT / paths.BINDINGS).read_text(encoding="utf-8"))
    return dict(said["rules"])


def hits(argv: list[str], root: Path, locale: str | None = None) -> list[str]:
    """Строки вывода команды предиката: отсортированные, без пустых.

    У `git grep` код 1 — «совпадений нет», законный вход; прочий отказ —
    отказ, а не пустота: молчание сломанной команды читалось бы как «условие не
    наступило» (045).
    """
    # `python3` — ИНТЕРПРЕТАТОР НАБОРА, а не первый из PATH: тот бывает старше
    # планки, и предикат краснел бы отказом, к ответу не относящимся (взгляд
    # на #1177).
    run = [sys.executable, *argv[1:]] if argv[:1] == ["python3"] else argv
    # Локаль — явно, когда её задаёт тест: регистр кириллицы `git grep -i`
    # сворачивает только при UTF-8, и тест в локали раннера иначе не видит
    # разницы (взгляд на #1373).
    env = {**os.environ, "LC_ALL": locale} if locale else None
    done = subprocess.run(
        run, cwd=root, capture_output=True, text=True, encoding="utf-8", check=False, env=env
    )
    nothing = argv[:2] == ["git", "grep"] and done.returncode == 1 and not done.stderr.strip()
    if done.returncode != 0 and not nothing:
        raise AssertionError(f"предикат не исполнился ({done.returncode}): {argv}: {done.stderr}")
    # СПИСОК ПУТЕЙ — ПО NUL: путь с переводом строки законен, и построчный
    # разбор развалил бы его надвое (`tests/test_source_hygiene.py`).
    # Строка вывода не обрезается: путь с пробелом по краю законен и иначе
    # не совпал бы со своей записью в `allowed` (взгляд на #1177).
    parts = done.stdout.split("\0") if "-z" in argv else done.stdout.splitlines()
    return sorted({one for one in parts if one.strip()})


def checks(rule: str) -> list[dict[str, Any]]:
    """Предикаты правила: один или несколько — по половине границы ответа на каждый."""
    said = predicates()["predicates"][rule]
    return list(said) if isinstance(said, list) else [said]


def arrived(rule: str, root: Path = ROOT) -> list[str]:
    """Строки вывода сверх законных по всем предикатам правила: не пусто — условие наступило."""
    return [
        line
        for one in checks(rule)
        for line in hits(one["argv"], root)
        if line not in one["allowed"]
    ]


def test_every_inapplicable_answer_is_held_here_and_nothing_else_is() -> None:
    """Каждое «неприменимо» стоит ровно в одном разделе, и ничего лишнего (обе стороны, 154)."""
    table = predicates()
    run, named = set(table["predicates"]), set(table["unmechanized"])
    inapplicable = {
        rule for rule, one in answers().items() if one.get("status") == INAPPLICABLE_STATUS
    }
    assert inapplicable, "ответов «неприменимо» нет — предмет исчез (075)"
    assert not run & named, f"номер в обоих разделах: {sorted(run & named)}"
    assert inapplicable == run | named, (
        f"без предиката: {sorted(inapplicable - run - named)}; "
        f"предикат у ответа, который не «неприменимо»: {sorted((run | named) - inapplicable)}"
    )


def test_every_inapplicable_answer_has_a_catalogue_probe_or_says_why_not() -> None:
    """У «неприменимо» сказано, что держит проба каталога `refuted_by`, или почему её нет (#1274).

    Пробу исполняет действие каталога в джобе `answer` (`ci.yml`), а не этот
    набор: копия исполнителя разъехалась бы с ним на подъёме формы (090). Здесь
    держится только то, что молчания нет: и отсутствие пробы, и проба уже
    предиката отсюда объясняются ключом `_refuted_by` — пояснением, которое
    форма 1.9 пропускает.
    """
    silent = sorted(
        rule
        for rule, one in answers().items()
        if one.get("status") == INAPPLICABLE_STATUS and not str(one.get("_refuted_by", "")).strip()
    )
    assert not silent, f"«неприменимо» без пояснения к пробе каталога: {silent}"


@pytest.mark.parametrize("rule", sorted(predicates()["predicates"]))
def test_the_condition_of_entry_has_not_arrived(rule: str) -> None:
    """Предикат ответа не нашёл нового: правило по-прежнему без предмета в дереве.

    Красное здесь — не дефект кода, а наступившее условие: ответ в
    `.rules/bindings.json` перечитывается (навык `answer-a-rule`), и либо
    правило становится действующим, либо новая строка уходит в `allowed` с
    причиной.
    """
    new = arrived(rule)
    assert not new, (
        f"ответ «неприменимо» на {rule}: условие вступления наступило — {new}. "
        "Перечитайте ответ, а не расширяйте allowed молча"
    )


@pytest.mark.parametrize("rule", sorted(predicates()["predicates"]))
def test_every_allowed_line_is_still_found(rule: str) -> None:
    """Законная строка, которой больше нет, снимается: список законного не копит мёртвое (005)."""
    gone = sorted(
        line for one in checks(rule) for line in set(one["allowed"]) - set(hits(one["argv"], ROOT))
    )
    assert not gone, f"{rule}: в allowed строки, которых вывод больше не даёт: {gone}"


#: Класс маски по смыслу fnmatch: после `[` — необязательный `!`, затем `]`
#: первым знаком читается буквой, а не концом класса. `^` отрицанием не
#: бывает: fnmatch кладёт его в набор буквой (взгляд на #1373).
MASK_CLASS: Final = re.compile(r"\[!?\]?[^\]]*\]")


def class_member(found: re.Match[str]) -> str:
    """Знак, который класс маски `[…]` допускает, — по ответу самого fnmatch.

    Смысл класса (отрицание, диапазон, `]` первым знаком) не разбирается здесь
    второй раз (правило 214): кандидатов спрашивают у `fnmatch.fnmatchcase`,
    и первый допущенный подкладывается (взгляд на #1373, правило 210).
    """
    cls = found.group(0)
    for one in dict.fromkeys(cls[1:-1] + "pqxyz0123456789_"):
        if one not in "[]!" and fnmatch.fnmatchcase(one, cls):
            return one
    raise AssertionError(f"класс {cls} не допускает ни одного пробного знака")


def planted_paths(glob: str) -> list[str]:
    """Пути, которые маска пробы каталога находит, — не один образец, а края маски.

    `**/` раскрывается и в ноль каталогов, и в один: проба каталога
    (`Path.glob`) находит обе глубины, и сверка «не шире» обязана видеть обе
    (взгляд на #1336). `*` — слово, `?` — буква, `[…]` — знак, который класс
    допускает по ответу fnmatch. Каждый путь сверяется с маской
    `PurePath.full_match`: подложенное, которого маска не находит, ничего бы не
    проверило (взгляд на #1373).
    """
    filled = MASK_CLASS.sub(class_member, glob).replace("?", "p")
    planted = sorted(
        {filled.replace("**/", depth).replace("*", "probe") for depth in ("", "probe/")}
    )
    stray = [path for path in planted if not PurePath(path).full_match(glob)]
    assert not stray, f"маска {glob} не находит подложенного: {stray}"
    return planted


#: Пробы, которые обещают ПОЛНОТУ относительно образца предиката: каждое слово
#: чередования в образце стоит в пробе во всех названных написаниях. Проба
#: каталога регистра не сворачивает и образца не знает, поэтому полнота — это
#: перечень форм, и держит его тест, а не память (взгляд на #1336).
PROBE_FORMS: Final[dict[str, tuple[str, ...]]] = {
    "048": ("{w}", "{W}", "{WW}"),
    "065": ('name: "{w}', "name: '{w}", "name: {w}"),
    "066": ("{w}",),
}


def test_every_probe_with_strings_declares_its_forms() -> None:
    """Каждая проба со строками стоит в `PROBE_FORMS`: полноту новой не держит память (#1336).

    Перечень ведётся рукой, и без этой сверки проба, добавленная в ответ,
    оставалась бы без проверки полноты — ровно то, против чего заведён перечень.
    """
    with_strings = {
        rule
        for rule, one in answers().items()
        if isinstance(one.get("refuted_by"), dict) and one["refuted_by"].get("contains")
    }
    assert with_strings == set(PROBE_FORMS), (
        f"без форм: {sorted(with_strings - set(PROBE_FORMS))}; "
        f"форм без пробы: {sorted(set(PROBE_FORMS) - with_strings)}"
    )


@pytest.mark.parametrize(
    ("glob", "planted"),
    [
        ("x/[!a]b", "x/pb"),
        ("x/[^pa]b", "x/^b"),
        ("x/[ab]c", "x/ac"),
        ("x/[!a-z]b", "x/-b"),
        ("x/[a-c]b", "x/ab"),
        ("x/[!]a]b", "x/pb"),
        ("x/[]a]b", "x/ab"),
    ],
    ids=[
        "отрицание",
        "крышка-буквой",
        "набор",
        "отрицание-диапазона",
        "диапазон",
        "скобка-в-отрицании",
        "скобка-первой",
    ],
)
def test_a_mask_class_plants_a_member_by_fnmatch(glob: str, planted: str) -> None:
    """Класс подкладывает знак, который допускает fnmatch (взгляды на #1336 и #1373).

    `[^…]` у fnmatch не отрицание, а набор с `^`; у `[!a-z]` исключён весь
    диапазон; `]` первым знаком — буква класса.
    """
    assert planted_paths(glob) == [planted]


#: Кириллическая буква в чередовании регистров «(к|К)» — так её видит любая
#: локаль; голая буква в предикате с `-i` видна только при UTF-8.
CASE_PAIR_RE = re.compile(r"\(([а-яё])\|([А-ЯЁ])\)")


def alternatives(pattern: str) -> list[str]:
    """Слова чередования образца: из скобок, если они есть, иначе весь образец.

    Чередование регистров «(к|К)» сворачивается в строчную букву: это одна
    буква слова, а не группа чередования слов.
    """
    pattern = CASE_PAIR_RE.sub(lambda pair: pair.group(1), pattern)
    group = re.search(r"\(([^()]*)\)", pattern)
    return (group.group(1) if group else pattern).split("|")


@pytest.mark.parametrize("rule", sorted(PROBE_FORMS))
def test_a_catalogue_probe_names_every_form_of_the_predicate(rule: str) -> None:
    """Проба называет каждое слово образца предиката во всех обещанных написаниях (#1336).

    Обратная сторона сверки «не шире»: без неё удалённое из пробы написание
    (прописная форма слова, имя метки без кавычек) оставляло набор зелёным, и починка
    откатывалась молча.
    """
    pattern = next(arg for arg in checks(rule)[0]["argv"] if "|" in arg)
    contains = set(answers()[rule]["refuted_by"]["contains"])
    missing = [
        form.format(w=word, W=word.capitalize(), WW=word.upper())
        for word in alternatives(pattern)
        for form in PROBE_FORMS[rule]
        if form.format(w=word, W=word.capitalize(), WW=word.upper()) not in contains
    ]
    assert not missing, f"{rule}: в пробе нет написаний {missing}"


@pytest.mark.parametrize(
    "rule",
    sorted(r for r, one in answers().items() if isinstance(one.get("refuted_by"), dict)),
)
def test_a_catalogue_probe_is_no_wider_than_the_predicate(rule: str, tmp_path: Path) -> None:
    """Что находит проба каталога `refuted_by`, находит и предикат отсюда (взгляд на #1332).

    Две записи одной границы — проба в ответе и предикат здесь — без сверки
    разошлись бы на первой правке одной из них (071, `c6b40dd`). Проба вправе
    быть УЖЕ предиката: это названо в её `_refuted_by`. Шире — нет: тогда
    действие каталога опровергло бы ответ тем, чего наш набор не видит. Каждая
    маска и каждая строка пробы кладутся файлом в пустое git-дерево, и хоть
    один предикат правила обязан его найти. Предикат командой `python3` читает
    настоящее дерево, а не подложенный файл, и здесь не исполняется.
    """
    probe = answers()[rule]["refuted_by"]
    runnable = [one for one in checks(rule) if one["argv"][:1] != ["python3"]]
    assert runnable, f"у {rule} есть проба, а сверить её не с чем (075)"
    missed: list[str] = []
    for at, (path, text) in enumerate(
        (path, text)
        for glob in probe["globs"]
        for path in planted_paths(glob)
        for text in probe["contains"] or ["x"]
    ):
        where = tmp_path / str(at)
        where.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=where, check=True)
        planted = where / path
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_text(f"{text}\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=where, check=True)
        if not any(
            line not in one["allowed"] for one in runnable for line in hits(one["argv"], where)
        ):
            missed.append(f"{path} + «{text}»")
    assert not missed, f"{rule}: проба находит, а предикат нет — {missed}"


#: Локали, в которых предикат обязан видеть одно и то же: регистр кириллицы
#: `git grep -i` сворачивает только при UTF-8 (взгляд на #1373).
LOCALES: Final = ("C", "C.UTF-8")


def planted_hits(tmp_path: Path, rule: str, path: str, text: str, locale: str) -> bool:
    """Видит ли предикат правила подложенную строку в заданной локали."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{text}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return any(hits(one["argv"], tmp_path, locale) for one in checks(rule))


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize(
    "label",
    [
        "name: Good first issue",
        "name: GOOD FIRST",
        "name: Новичкам",
        "name: НОВИЧКАМ",
        "name: нОвИчКам",
    ],
    ids=["с-прописной", "прописными", "кириллица-с-прописной", "кириллица-прописными", "смешанно"],
)
def test_the_newcomer_label_is_seen_in_any_case(tmp_path: Path, label: str, locale: str) -> None:
    """Предикат 065 видит метку в любом регистре и при ЯВНОЙ локали (взгляд на #1373)."""
    assert planted_hits(tmp_path, "065", ".github/labels.yml", f"- {label}", locale), label


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("word", ["калибр", "Калибр", "КАЛИБР", "КаЛибр", "сВеТоФоР"])
def test_the_calibration_word_is_seen_in_any_case(tmp_path: Path, word: str, locale: str) -> None:
    """Предикат 048 видит шкалу в любом регистре кириллицы при любой локали (взгляд на #1373)."""
    assert planted_hits(tmp_path, "048", "docs/x.md", f"наша {word} по чужому", locale), word


def unpaired(part: str) -> list[str]:
    """Кириллица образца вне верного чередования регистров: голые буквы и чужие пары.

    Пара с опечаткой — «(к|Л)» — тоже не чередование: слово «К…» с ней не
    найдётся ни в одной локали (взгляд на #1393).
    """
    wrong = [f"({low}|{up})" for low, up in CASE_PAIR_RE.findall(part) if low.upper() != up]
    return wrong + re.findall("[а-яёА-ЯЁ]", CASE_PAIR_RE.sub("", part))


@pytest.mark.parametrize(
    ("part", "found"),
    [("(к|К)(а|А)", []), ("(к|Л)", ["(к|Л)"]), ("к(а|А)", ["к"]), ("calibrat", [])],
    ids=["верная-пара", "чужая-пара", "голая-буква", "латиница"],
)
def test_unpaired_names_every_wrong_letter(part: str, found: list[str]) -> None:
    """Обе половины: верная пара законна, чужая пара и голая буква — нет."""
    assert unpaired(part) == found


def test_no_predicate_carries_bare_cyrillic() -> None:
    """Строгое правило (210): кириллица в предикате — только чередованием регистров.

    Перечень написаний «калибр|Калибр|КАЛИБР» дважды оставлял дыру: при локали
    C смешанный регистр не виден (взгляды на #1336 и #1373). Чередование по
    буквам покрывает все сочетания при любой локали, и следующий предикат
    обязан писаться так же, а не перечнем.
    """
    bare = []
    seen = 0
    for rule in predicates()["predicates"]:
        for one in checks(rule):
            for part in one["argv"]:
                seen += len(CASE_PAIR_RE.findall(part))
                bare += [f"{rule}: {wrong}" for wrong in unpaired(part)]
    assert seen, "кириллицы в предикатах нет — предмет проверки не найден (075)"
    assert not bare, f"кириллица вне чередования регистров: {bare}"


def test_a_planted_condition_turns_the_gate_red(tmp_path: Path) -> None:
    """Обе половины на настоящем git: чистое дерево зелёное, файл перевода — красное."""

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "x.py").write_text("print(1)\n", encoding="utf-8")
    git("add", "-A")
    argv = checks("077")[0]["argv"]
    assert hits(argv, tmp_path) == []
    (tmp_path / "ru.po").write_text('msgid "x"\n', encoding="utf-8")
    git("add", "-A")
    assert hits(argv, tmp_path) == ["ru.po"]
    assert "-z" in argv, "список путей предиката читается не по NUL"
    grep = ["git", "grep", "-nE", "flock", "--", "."]
    assert hits(grep, tmp_path) == [], "«совпадений нет» у git grep — не отказ"


def test_a_broken_command_is_a_refusal_not_silence(tmp_path: Path) -> None:
    """Сломанная команда — отказ, а не «условие не наступило» (045)."""
    with pytest.raises(AssertionError, match="не исполнился"):
        hits(["git", "rev-parse", "--verify", "HEAD"], tmp_path)


def test_every_predicate_names_the_border_it_holds() -> None:
    """Предикат цитирует границу ответа, которую держит, — у КАЖДОГО правила (взгляд на #1177).

    Прежде гейт смотрел одно 066 и подстроки в собственном `why` предиката:
    связь предиката с ответом не проверялась ничем, и у 120 вторая половина
    границы осталась без предиката. Теперь `border` — дословная цитата из
    ответа в `.rules/bindings.json`, и стоит она там РОВНО ОДИН РАЗ: цитата,
    повторённая соседней фразой, пережила бы правку самой границы, и гейт
    остался бы зелёным (взгляд на #1182). Правка границы в ответе без правки
    предиката краснеет.

    ПРЕДЕЛ НАЗВАН: полноту — все ли половины границы названы — держит
    чтение: перечислить половины прозы разбор не умеет.
    """
    said = answers()
    off = [
        f"{rule}: «{one.get('border', '')}»"
        for rule in predicates()["predicates"]
        for one in checks(rule)
        if not one.get("border") or said[rule]["why"].count(one["border"]) != 1
    ]
    assert not off, f"предикат не цитирует границу своего ответа ровно один раз: {off}"


@pytest.mark.parametrize(
    ("rule", "borders"),
    [("066", 2), ("120", 2)],
    ids=["блокировка и второй писатель", "корпус правил и указатель решений"],
)
def test_a_composite_border_has_a_predicate_per_half(rule: str, borders: int) -> None:
    """Составная граница держится по половине на предикат: обе половины 066 и 120 названы."""
    assert len({one["border"] for one in checks(rule)}) == borders


def test_a_new_replace_inside_a_known_file_arrives(tmp_path: Path) -> None:
    """Вторая подмена в уже известном файле меняет вывод: сверяется строка, а не файл."""

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "scripts").mkdir()
    known = "    os.replace(a, b)\n"
    (tmp_path / "scripts" / "x.py").write_text(known, encoding="utf-8")
    git("add", "-A")
    argv = checks("066")[1]["argv"]
    before = hits(argv, tmp_path)
    (tmp_path / "scripts" / "x.py").write_text(known + "    os.replace(c, d)\n", encoding="utf-8")
    git("add", "-A")
    assert set(hits(argv, tmp_path)) - set(before), "новая подмена в известном файле не видна"


def test_a_script_that_calls_the_findings_base_is_a_second_writer(tmp_path: Path) -> None:
    """Скрипт, зовущий базу находок, — второй писатель, даже если прогон зовёт не её саму."""

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "findings_db.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "scripts" / "prose.py").write_text('"""Зовёт `findings_db` рукой."""\n', "utf-8")
    git("add", "-A")
    argv = checks("066")[2]["argv"]
    assert hits(argv, tmp_path) == [], "упоминание в прозе — не вызов"
    (tmp_path / "scripts" / "nightly.py").write_text("import findings_db\n", encoding="utf-8")
    git("add", "-A")
    assert hits(argv, tmp_path) == ["scripts/nightly.py"]


def test_python3_runs_as_the_suite_interpreter(tmp_path: Path) -> None:
    """Предикат `python3` исполняется интерпретатором набора, а не первым из PATH."""
    said = hits(["python3", "-c", "import sys; print(sys.executable)"], tmp_path)
    assert said == [sys.executable]


def test_a_path_keeps_its_edges(tmp_path: Path) -> None:
    """Путь с пробелом по краю читается как есть, а не обрезанным (взгляд на #1177)."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / " x.po").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    assert hits(["git", "ls-files", "-z", "*.po"], tmp_path) == [" x.po"]
