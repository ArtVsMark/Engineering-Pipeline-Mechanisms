"""Ссылка на правило каталога ведёт туда, куда обещает.

Ссылками на правила проект обосновывает решения: почти каждый механизм называет
правило, из которого вырос. Битая ссылка обесценивает довод дважды — читатель
не может ни проверить его, ни отличить «правила нет» от «адрес переврали».

Замер 10.09.2026: битых ссылок в дереве оказалось 29 из 300. Номер везде был
верным, а имя файла писалось по памяти, близко к смыслу.
"""

import codecs
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("check_rule_links.py")


def test_a_wrong_name_at_a_right_number_is_found() -> None:
    """Номер верный, имя выдумано — это находка.

    Ровно так выглядели все 29: `046-a-red-must-name-its-cause.md` вместо
    `046-name-the-gaps-do-not-level-them.md`. Площадка отдаёт по такой ссылке
    404, и ни один прогон об этом не говорил.
    """
    found = [(Path("a.py"), 7, "046", "a-red-must-name-its-cause")]
    problems = module.broken(found, {"046": "name-the-gaps-do-not-level-them"})
    assert len(problems) == 1
    assert "046" in problems[0] and "a.py:7" in problems[0]


def test_a_missing_number_is_told_apart_from_a_wrong_name() -> None:
    """«Правила нет» и «адрес переврали» — разные находки и разные починки (154)."""
    found = [(Path("a.py"), 1, "999", "made-up")]
    problems = module.broken(found, {"046": "name-the-gaps-do-not-level-them"})
    assert "в каталоге нет" in problems[0]


def test_a_correct_link_is_not_a_finding() -> None:
    """Совпало — молчим."""
    found = [(Path("a.py"), 1, "046", "name-the-gaps-do-not-level-them")]
    assert module.broken(found, {"046": "name-the-gaps-do-not-level-them"}) == []


def test_an_empty_catalogue_is_the_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Выгрузка пуста — гейт падает, а не объявляет «чисто» (045, 075)."""
    monkeypatch.setattr(module.catalogue.ghrest, "raw_json", lambda *_: {"rules": []})
    with pytest.raises(module.NotRun):
        module.known()


def test_an_unreachable_catalogue_is_its_own_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Каталог недоступен — СВОЙ исход: не «не спросили» и не «всё сошлось».

    ЗДЕСЬ БЫЛА ЧЕТВЁРТАЯ СТОРОНА ОДНОГО РЕШЕНИЯ. Прежде молчание канала давало
    «не отработал», то есть красную ОБЯЗАТЕЛЬНУЮ проверку — и очередь вставала
    из-за сети. Замер 16.09.2026, голова #370: `journal` дала зелёное, красное и
    снова зелёное на ОДНОМ дереве; общая ветка за те три минуты не двигалась, а
    упал шаг «чужой разбор приведён ссылкой» — на чтении выгрузки.

    Зелёным это тоже не стало: гейт, молча зеленеющий при недоступном предмете,
    снаружи неотличим от работающего (045). Разбор — решение `027`.
    """

    def broken(*_: Any, **__: Any) -> Any:
        raise module.catalogue.ghrest.TransportError("нет сети")

    monkeypatch.setattr(module.catalogue.ghrest, "raw_json", broken)
    with pytest.raises(module.catalogue.Silent, match="каталог не ответил"):
        module.known()
    assert module.main([]) == module.EXIT_SILENT
    assert module.EXIT_SILENT not in (module.EXIT_OK, module.EXIT_FOUND, module.EXIT_BROKEN), (
        "исход канала совпал с другим — снаружи они неразличимы (039)"
    )


def test_the_live_tree_has_no_broken_links() -> None:
    """Живое дерево проходит гейт — иначе он был бы объявлением намерения.

    Ссылки читаются из дерева, а имена — из каталога по сети. Без сети проверка
    пропускается: её предмет тогда недоступен, и падение говорило бы о канале.
    """
    try:
        real = module.known()
    except module.NotRun as exc:
        pytest.skip(f"каталог недоступен: {exc}")
    found = module.links(Path())
    assert found, "ссылок на правила в дереве нет — предмет не найден"
    assert module.broken(found, real) == []


def test_links_that_resolve_are_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Все ссылки разрешились — чистый исход, и охват назван числом.

    Охват печатается ВСЕГДА: проверка, читающая список, без числа неотличима
    от той, что не нашла ничего
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    monkeypatch.setattr(module, "known", lambda: {"044": "check-the-premise-before-fixing"})
    monkeypatch.setattr(
        module,
        "links",
        lambda root: [("AGENTS.md", 1, "044", "check-the-premise-before-fixing")],
    )
    assert module.main([]) == module.EXIT_OK
    assert "проверено 1" in capsys.readouterr().out


def test_a_link_leading_nowhere_is_the_found_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ссылка на имя, которого у номера нет, — исход «найдено» точкой входа (#687).

    Прежде этот исход засчитывался прогнанным по `len(problems) == 1`: число
    совпадало с кодом, а точку входа с находкой не звал никто.
    """
    monkeypatch.setattr(module, "known", lambda: {"044": "check-the-premise-before-fixing"})
    monkeypatch.setattr(module, "links", lambda root: [("AGENTS.md", 1, "044", "not-that-name")])
    assert module.main([]) == module.EXIT_FOUND
    assert "ведущих не туда: 1 из 1" in capsys.readouterr().out


def test_an_empty_tree_is_broken_whatever_the_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Пустое дерево — «не отработал» и при молчащем каталоге: дерево читается первым (#1255).

    Прежде выгрузка спрашивалась раньше дерева, и тот же пустой вход отвечал
    «каталог молчит», стоило сети моргнуть: исход третьего пути решала сеть.
    """
    asked: list[str] = []

    def silent() -> dict[str, str]:
        asked.append("каталог")
        raise module.catalogue.Silent("каталог не ответил")

    monkeypatch.setattr(module, "known", silent)
    monkeypatch.setattr(module, "links", lambda root: [])
    assert module.main([]) == module.EXIT_BROKEN
    assert "ссылок на правила в дереве нет" in capsys.readouterr().err
    assert asked == [], "пустое дерево спросило каталог — исход снова зависит от сети"


def test_a_document_in_another_encoding_is_read_by_its_bytes(tmp_path: Path) -> None:
    """Файл не в UTF-8 не роняет гейт и не выпадает: ссылка в нём найдена (взгляд на #1300).

    Прежде такой файл сперва молча пропускался, затем ронял весь гейт в «не
    отработал» — без способа исключить фикстуру кодировки.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    link = "rules/ru/045-no-silent-fallback.md"
    (tmp_path / "doc.md").write_bytes("правило ".encode("cp1251") + b"\xff " + link.encode())
    assert module.links(tmp_path) == [(Path("doc.md"), 1, "045", "no-silent-fallback")]


def test_a_listed_file_missing_on_disk_is_broken_whatever_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Перечисленный, но не прочитанный файл — «не отработал», и раньше сети (#1300)."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "doc.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "doc.md"], check=True)
    (tmp_path / "doc.md").unlink()
    asked: list[str] = []

    def silent() -> dict[str, str]:
        asked.append("каталог")
        raise module.catalogue.Silent("каталог не ответил")

    monkeypatch.setattr(module, "known", silent)
    assert module.main(["--root", str(tmp_path)]) == module.EXIT_BROKEN
    assert "doc.md не прочитан" in capsys.readouterr().err
    assert asked == [], "непрочитанный файл спросил каталог — исход снова зависит от сети"


@pytest.mark.parametrize("codec", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
def test_a_wide_file_with_a_mark_is_read(tmp_path: Path, codec: str) -> None:
    """Файл UTF-16/32 с меткой порядка байтов перекодируется: ссылка найдена (взгляд на #1302).

    Прежде такой файл молча считался проверенным: байтовый образец ссылок в нём не видел.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    mark = {
        "utf-16-le": codecs.BOM_UTF16_LE,
        "utf-16-be": codecs.BOM_UTF16_BE,
        "utf-32-le": codecs.BOM_UTF32_LE,
        "utf-32-be": codecs.BOM_UTF32_BE,
    }[codec]
    text = "правило rules/ru/045-no-silent-fallback.md\n"
    (tmp_path / "data.json").write_bytes(mark + text.encode(codec))
    assert module.links(tmp_path) == [(Path("data.json"), 1, "045", "no-silent-fallback")]


def test_a_wide_file_without_a_mark_is_the_named_limit(tmp_path: Path) -> None:
    """UTF-16 без метки не отличить от двоичного: ссылки в нём не видны — предел назван (#1302).

    Проба держит предел словами кода: изменится поведение — она скажет об этом.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    link = "rules/ru/045-no-silent-fallback.md"
    (tmp_path / "data.json").write_bytes(link.encode("utf-16-le"))
    assert module.links(tmp_path) == []


def test_a_broken_wide_file_still_shows_its_link(tmp_path: Path) -> None:
    """Битое тело после широкой метки не красит гейт: ASCII-ссылка найдена (#1310)."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    link = "rules/ru/045-no-silent-fallback.md\n"
    body = codecs.BOM_UTF16_LE + link.encode("utf-16-le") + b"\x00\xd8"
    (tmp_path / "data.json").write_bytes(body)
    assert module.links(tmp_path) == [(Path("data.json"), 1, "045", "no-silent-fallback")]


def test_only_a_wide_file_is_recoded() -> None:
    """Перекодируется только файл с широкой меткой; прочие байты — как есть (#1302)."""
    plain = "правило".encode("cp1251")
    assert module.as_ascii_compatible(plain) == plain
    wide = codecs.BOM_UTF16_LE + "rules/ru/045".encode("utf-16-le")
    assert module.as_ascii_compatible(wide) == b"rules/ru/045"


#: Подставка в форме ссылки — нарочно битая: в литерале кода она вход проверки.
FAKE = "rules/ru/" + "001-a.md"


@pytest.mark.parametrize(
    ("source", "judged"),
    [
        (f'"""Модуль.\n\n{FAKE}\n"""\n', True),
        (f"x = 1  # {FAKE}\n", True),
        (f'CASE = "{FAKE}"\n', False),
        (f'def f():\n    """Функция."""\n    return f"путь {FAKE}"\n', False),
        (f'CASE = "{FAKE}"  # {FAKE}\n', True),
        (f"не python: ( {FAKE}\n", True),
    ],
    ids=["докстрока", "комментарий", "литерал", "f-строка", "литерал-и-комментарий", "не-разобран"],
)
def test_a_code_literal_is_an_input_not_a_link(tmp_path: Path, source: str, judged: bool) -> None:
    """В `.py` судятся докстроки и комментарии, а литерал кода — вход проверки (#1571).

    Подставки каталога (`001-a.md` в самопроверке гейта и в тестах) — литералы,
    и правильное имя там сломало бы сам случай. Исходник, который не
    разобрался, судится целиком: сужение не даёт права пропускать непрочитанное.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
    (tmp_path / "case.py").write_text(source, encoding="utf-8")
    assert bool(module.links(tmp_path)) is judged


def test_a_literal_is_judged_outside_python(tmp_path: Path) -> None:
    """Вне `.py` литералов нет: подставка в документе — ссылка и судится."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
    (tmp_path / "doc.md").write_text(f'`CASE = "{FAKE}"`\n', encoding="utf-8")
    assert module.links(tmp_path) == [(Path("doc.md"), 1, "001", "a")]


def test_code_literals_and_inside_name_the_places() -> None:
    """`code_literals` называет литерал кода, но не докстроку; `inside` судит по символам."""
    spans = module.code_literals('"""doc"""\nX = "abc"\n')
    assert spans == [(2, 4, 2, 9)]
    assert module.inside(spans, 2, 5)
    assert not module.inside(spans, 2, 9)
    assert not module.inside(spans, 1, 1)
    assert module.code_literals("def (") is None


def test_a_comment_between_concatenated_strings_is_judged(tmp_path: Path) -> None:
    """Склеенные строки — две части, комментарий между ними судится (взгляд на #1588).

    Ast отдаёт склейку одним узлом от первой части до последней, и ссылка в
    комментарии между частями прежде молча выпадала из суда.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
    source = f'CASE = (\n    "a"  # {FAKE}\n    "b"\n)\n'
    (tmp_path / "case.py").write_text(source, encoding="utf-8")
    assert module.links(tmp_path) == [(Path("case.py"), 2, "001", "a")]


def test_a_declared_encoding_keeps_the_comment_after_a_literal(tmp_path: Path) -> None:
    """Объявленная кодировка: ссылка в комментарии за не-ASCII литералом судится (#1588).

    Смещения ast — байты UTF-8; у исходника в cp1251 они разошлись бы с байтами
    файла, и конец места литерала съехал бы на комментарий.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
    source = f'# coding: cp1251\nX = "правило"  # {FAKE}\n'
    (tmp_path / "case.py").write_bytes(source.encode("cp1251"))
    assert module.links(tmp_path) == [(Path("case.py"), 2, "001", "a")]


def test_python_text_and_python_links_name_their_outcomes() -> None:
    """`python_text` читает объявленную кодировку; `python_links` — None, когда судить целиком."""
    assert module.python_text("# coding: cp1251\nX = 'ы'\n".encode("cp1251")) == (
        "# coding: cp1251\nX = 'ы'\n"
    )
    assert module.python_text(b"# coding: no-such-codec\n") is None
    assert module.python_links("x.py", b"def (") is None
    said = module.python_links("x.py", f'X = "{FAKE}"  # {FAKE}\n'.encode())
    assert said == [(Path("x.py"), 1, "001", "a")]
