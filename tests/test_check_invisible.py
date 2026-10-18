"""Гейт невидимых символов: что краснеет, что законно и как он молчит на исправном (#1429)."""

import hashlib
import subprocess
import sys
import unicodedata
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.conftest import RunScript, load_script

module = load_script("check_invisible.py")

REJECTED = 1
CLEAN = 0
BROKEN = 2


def tree(root: Path, files: dict[str, str]) -> Path:
    """Репозиторий теста с отслеживаемыми файлами."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


@pytest.mark.parametrize(
    "char",
    [
        "\u200b",
        "\u200e",
        "\u202e",
        "\u2066",
        "\u2060",
        "\u061c",
        "\u180e",
        "\U000e0041",
        "\u00ad",
        "\u3164",
        "\u034f",
        "\ufe0f\ufe0f",
        "\U000e0100",
        "\u2800",
        "\u2028",
        "\u2029",
        "\U0001f3f4\U000e0067\U000e0062",
        "\U0001f3f4\U000e0069\U000e0067\U000e006e\U000e006f\U000e0072\U000e0065\U000e007f",
        "\x85",
        "\x0b",
        "\x0c",
        "\x1c",
        "\u17b4",
        "\u180b",
        "\r",
        "\u2192\u200d\u2192",
        "\U0001f600\u180b",
        "\u1820\ufe00",
        "\u1820\U000e0100",
        "\U0001f600\ufe0f",
        "1\ufe0f\u200d\U0001f4bb",
    ],
    ids=[
        "zwsp",
        "lrm",
        "rlo",
        "lri",
        "wj",
        "alm",
        "mvs",
        "tag",
        "shy",
        "hangul-filler",
        "cgj",
        "selectors",
        "selector-after-letter",
        "braille-blank",
        "line-separator",
        "paragraph-separator",
        "flag-without-cancel",
        "flag-with-any-string",
        "nel",
        "vertical-tab",
        "form-feed",
        "file-separator",
        "khmer-inherent",
        "mongolian-selector-after-letter",
        "lone-carriage-return",
        "zwj-between-arrows",
        "mongolian-selector-after-emoji",
        "standard-selector-after-mongolian",
        "ideographic-selector-after-mongolian",
        "emoji-selector-without-variant",
        "zwj-after-a-digits-selector",
    ],
)
def test_each_class_is_rejected(run_script: RunScript, tmp_path: Path, char: str) -> None:
    """Каждый класс невидимого краснит гейт и называет место."""
    tree(tmp_path, {"SKILL.md": f"делай так{char} и только так\n"})
    result = run_script("check_invisible.py", cwd=tmp_path)
    assert result.code == REJECTED, result.text
    assert "SKILL.md:1:" in result.text


def test_legal_forms_pass(run_script: RunScript, tmp_path: Path) -> None:
    """BOM в начале, составной эмодзи, один селектор и кириллица — чисто."""
    tree(
        tmp_path,
        {
            "a.md": "\ufeffзаголовок — «кавычки» и ё\n",
            "b.md": "## 🧑\u200d💻 окно\n## ⚠\ufe0f внимание\n🐈\u200d\u2b1b кот\n",
            "c.md": "1\ufe0f\u20e3 шаг · \u845b\U000e0100 иероглиф\n",
            "d.md": "флаг \U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f\n",
            "e.md": "\U0001f642\u200d\u2194\ufe0f · \U0001f469\U0001f3fd\u200d\U0001f4bb · "
            "\U0001f3f3\ufe0f\u200d\U0001f308 · \u00a9\ufe0f · \u2229\ufe00\r\n",
        },
    )
    result = run_script("check_invisible.py", cwd=tmp_path)
    assert result.code == CLEAN, result.text


def test_code_is_not_judged(run_script: RunScript, tmp_path: Path) -> None:
    """Литерал в коде законен (снятие BOM у грейдера): предмет — текст-указание (195)."""
    tree(tmp_path, {"strip.py": "text.lstrip('\ufeff\u200b')\n", "a.md": "чисто\n"})
    result = run_script("check_invisible.py", cwd=tmp_path)
    assert result.code == CLEAN, result.text


def test_the_borders_of_the_legal_forms_are_held() -> None:
    """Законная форма не на своём месте — находка: BOM внутри, ZWJ между буквами."""
    assert module.hidden("а\ufeffб")
    assert module.hidden("а\u200dб")
    assert not module.hidden("\ufeffа")


def test_an_ignored_file_and_a_binary_are_not_judged(run_script: RunScript, tmp_path: Path) -> None:
    """Предмет — текст дерева: игнорируемый файл и не-UTF-8 гейт не судит."""
    tree(tmp_path, {"a.md": "чисто\n", ".gitignore": "ignored.md\n"})
    (tmp_path / "ignored.md").write_text("\u202e", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00\x2e\x20")
    subprocess.run(["git", "add", "blob.bin"], cwd=tmp_path, check=True)
    result = run_script("check_invisible.py", cwd=tmp_path)
    assert result.code == CLEAN, result.text


def test_a_new_file_not_yet_added_is_judged(run_script: RunScript, tmp_path: Path) -> None:
    """Файл вне индекса, но не игнорируемый, судится: предполётная видит его до толчка."""
    tree(tmp_path, {"a.md": "чисто\n"})
    (tmp_path / "new.md").write_text("а\u202eб\n", encoding="utf-8")
    result = run_script("check_invisible.py", "--root", str(tmp_path))
    assert result.code == REJECTED, result.text
    assert "new.md:1:2" in result.text


def test_outside_a_repository_it_did_not_run(run_script: RunScript, tmp_path: Path) -> None:
    """Без git дерева судить нечего — «не отработал», а не «чисто» (075)."""
    result = run_script("check_invisible.py", cwd=tmp_path)
    assert result.code == BROKEN, result.text


def test_selector_and_emoji_name_their_blocks() -> None:
    """Селектор — из обоих блоков; эмодзи — `Extended_Pictographic`, а не весь блок стрелок."""
    assert module.selector(chr(0xFE0F)) and module.selector(chr(0xE0100))
    assert not module.selector("а")
    assert module.emoji(chr(0x1F9D1)) and module.emoji(chr(0x26A0)) and module.emoji("\u2194")
    assert not module.emoji("б") and not module.emoji("\u2192") and not module.emoji("\u2200")
    assert not module.emoji(chr(0xE0067)), "тег — не эмодзи, хоть и выше U+1F000"


@pytest.mark.parametrize(
    ("base", "mark", "said"),
    [
        ("\u26a0", "\ufe0f", True),
        ("1", "\ufe0f", True),
        ("\u2229", "\ufe00", True),
        ("\u845b", "\U000e0100", True),
        ("\u1820", "\u180b", True),
        ("а", "\ufe0f", False),
        ("\U0001f600", "\ufe0f", False),
        ("\u845b", "\ufe0f", False),
        ("\U0001f600", "\u180b", False),
        ("\u1820", "\ufe00", False),
        ("\u1820", "\U000e0100", False),
        ("\u4e00", "\u180b", False),
    ],
    ids=[
        "эмодзи-и-его-вариант",
        "цифра-клавиши",
        "математика-стандартный",
        "иероглиф-идеографический",
        "монгольская-буква-свободный",
        "буква",
        "эмодзи-без-варианта",
        "иероглиф-и-эмодзи-селектор",
        "эмодзи-и-монгольский",
        "монгольская-и-стандартный",
        "монгольская-и-идеографический",
        "иероглиф-и-монгольский",
    ],
)
def test_a_selector_fits_only_a_base_of_its_kind(base: str, mark: str, said: bool) -> None:
    """Род селектора сверен с основой: пара из данных, иероглиф или монгольская буква (#1444)."""
    assert module.fits(base, mark) is said


def gate_python() -> str:
    """Версия языка, которой шаг конвейера исполняет гейт у потребителя."""
    import yaml

    from tests.conftest import ROOT

    steps = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "step-pipeline.yml").read_text(encoding="utf-8")
    )["jobs"]["pipeline"]["steps"]
    said = [
        str(one["with"]["python-version"])
        for one in steps
        if "setup-python" in str(one.get("uses") or "")
    ]
    assert len(said) == 1, f"интерпретатор шага не назван однозначно: {said}"
    return said[0]


def unicode_version(said: str) -> tuple[int, ...]:
    """Версия Unicode кортежем — для сравнения «не новее»."""
    return tuple(int(one) for one in said.split("."))


def version_problem(running: str, gate: str, data: str, base: str) -> str:
    """Что не так с версией данных на этом интерпретаторе; пусто — всё в порядке."""
    if running == gate:
        return (
            "" if data == base else f"на интерпретаторе шага {running} данные {data}, база {base}"
        )
    if unicode_version(data) <= unicode_version(base):
        return ""
    return f"данные Unicode {data} новее базы {base} интерпретатора {running}"


@pytest.mark.parametrize(
    ("running", "data", "base", "fine"),
    [
        ("3.14", "16.0.0", "16.0.0", True),
        ("3.14", "16.0.0", "17.0.0", False),
        ("3.15", "16.0.0", "17.0.0", True),
        ("3.15", "18.0.0", "17.0.0", False),
    ],
    ids=["шаг-совпало", "шаг-разошлось", "новее-законно", "данные-новее-базы"],
)
def test_the_version_rule_holds_both_cells(running: str, data: str, base: str, fine: bool) -> None:
    """На интерпретаторе шага — равенство, на прочих — данные не новее базы."""
    assert (version_problem(running, "3.14", data, base) == "") is fine


def test_the_unicode_data_is_the_gates_interpreters_version() -> None:
    """Версия выдержек — база того интерпретатора, которым гейт исполняется у потребителя (210).

    Гейт исполняет шаг конвейера (`step-pipeline.yml`), и на его версии языка
    данные обязаны совпасть с `unicodedata` — иначе новые знаки гейт не знает,
    и поднять выдержки надо тем же изменением, что и версию шага. На прочих
    ячейках матрицы данные не новее базы интерпретатора: интерпретатор новее
    знает знаки, которых выдержка не знает, — это названная граница гейта, а не
    дефект. Прежнее точное равенство на любой ячейке краснило 3.15 с базой
    17.0.0 (взгляд CI на #1510).
    """
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    said = version_problem(
        running, gate_python(), module.UNICODE_VERSION, unicodedata.unidata_version
    )
    assert not said, said
    major_minor = module.UNICODE_VERSION.rsplit(".", 1)[0]
    for one in sorted(module.UNICODE.glob("*.txt")):
        head = "\n".join(one.read_text(encoding="utf-8").splitlines()[:15])
        assert major_minor in head, f"{one.name}: версия не названа в шапке"


def test_verbatim_copies_match_their_source() -> None:
    """Дословная копия файла стандарта совпадает с источником хешем — рукой не правится."""
    for name, (_, digest) in module.VERBATIM.items():
        body = (module.UNICODE / name).read_bytes()
        assert hashlib.sha256(body).hexdigest() == digest, name


def test_extracts_name_their_source_and_command() -> None:
    """Выдержка называет источник, хеш и команду: иначе её не перепроверить (210)."""
    extracts = sorted(
        set(module.UNICODE.glob("*.txt")) - {module.UNICODE / one for one in module.VERBATIM}
    )
    assert extracts, "выдержек нет"
    for one in extracts:
        head = one.read_text(encoding="utf-8")
        assert module.UNICODE_SOURCE in head and "sha256" in head and "grep" in head, one.name


@pytest.fixture
def fresh_tables() -> Iterator[None]:
    """Таблицы читаются заново до и после теста: кэш не переживает подмену данных."""
    module.tables.cache_clear()
    yield
    module.tables.cache_clear()


def test_missing_unicode_data_did_not_run(
    run_script: RunScript, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_tables: None
) -> None:
    """Нет данных Unicode — «не отработал», а не «чисто» и не трасса с кодом 1 (039)."""
    monkeypatch.setattr(module, "UNICODE", tmp_path / "нет")
    tree(tmp_path, {"a.md": "чисто\n"})
    monkeypatch.chdir(tmp_path)
    assert module.main([]) == BROKEN


def test_our_code_carries_no_invisible() -> None:
    """Строки `.py` у себя судятся: задание взгляда уходит агенту из кода дословно (195)."""
    from tests.conftest import ROOT

    listed = subprocess.run(
        ["git", "ls-files", "-z", "*.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert listed.returncode == 0, listed.stderr
    names = [one for one in listed.stdout.split("\0") if one]
    assert names, "файлов .py не найдено"
    found = [
        f"{name}:{line}:{column}: {what}"
        for name in names
        for line, column, what in module.hidden((ROOT / name).read_text(encoding="utf-8"))
    ]
    assert not found, found


def test_flag_tags_are_legal_only_inside_a_whole_flag() -> None:
    """Теги законны между чёрным флагом и завершающим тегом — и нигде больше (`78f3abb`)."""
    england = "\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f"
    assert module.flag_tags(england) == set(range(1, len(england)))
    assert not module.hidden(f"а {england} б")
    assert module.flag_tags("\U0001f3f4\U000e0067") == set(), "оборвана — законна"
    assert module.flag_tags("\U0001f3f4\U000e007f") == set(), "один завершающий — законен"
    assert module.hidden("а\U000e0067\U000e007f"), "теги без основы не покраснели"


def test_line_and_paragraph_separators_are_named() -> None:
    """Разделители строки и абзаца краснеют со своей причиной, а не именем формата (`36f8b72`)."""
    assert "разделитель строки" in module.hidden("а\u2028б")[0][2]
    assert "разделитель абзаца" in module.hidden("а\u2029б")[0][2]
    assert "пустотой" in module.always("\u2800")


def test_every_rgi_tag_flag_is_legal_and_nothing_else() -> None:
    """Законны ровно три флага с тегами — Англия, Шотландия, Уэльс (взгляд на #1444)."""
    for name in ("gbeng", "gbsct", "gbwls"):
        tags = "".join(chr(0xE0000 + ord(one)) for one in name)
        assert not module.hidden(f"\U0001f3f4{tags}\U000e007f"), name
    hidden_text = "".join(chr(0xE0000 + ord(one)) for one in "ignore all")
    assert module.hidden(f"\U0001f3f4{hidden_text}\U000e007f"), "строка тегами прошла как флаг"


def test_plain_controls_and_mongolian_variants_pass() -> None:
    """Табуляция, CRLF и один свободный селектор после монгольской буквы — законны."""
    assert not module.hidden("а\tб\r\nв")
    assert not module.hidden("\u1820\u180b")
    assert module.hidden("\u1820\u180b\u180b"), "два селектора подряд прошли"


@pytest.mark.parametrize("code", [0x2065, 0xFFF0, 0xE0000, 0xE0002, 0xE0080, 0xE0FFF])
def test_unassigned_ignorables_are_judged(code: int) -> None:
    """Неназначенные точки Default_Ignorable краснеют; Cn вне них — нет (`e0b7e8a`)."""
    assert module.always(chr(code)), hex(code)
    assert not module.always(chr(0x0378)), "неназначенная точка вне игнорируемых покраснела"


def test_an_ignorable_range_is_judged_whatever_its_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Точка игнорируемого диапазона, назначенная новой базой не `Cf`, всё равно судится."""
    monkeypatch.setattr(module.unicodedata, "category", lambda _: "Mn")
    assert module.always(chr(0xE0080)), "назначенная игнорируемая точка ушла из-под гейта"
    assert not module.always(chr(0xE0100)), "селектор судится своим правилом, а не диапазоном"


def test_the_step_runs_the_gate_only_after_the_transport_is_installed() -> None:
    """Без пакета транспорта гейт не зовётся: падение импорта читалось бы находкой (#1437).

    `import gitcall` без пакета даёт исход 1 — «найден невидимый символ», —
    хотя докстрока обещает 2 («не отработал»). Отказ установки называет шаг
    установки, а не этот гейт (039).
    """
    import yaml

    from tests.conftest import ROOT

    steps = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "step-pipeline.yml").read_text(encoding="utf-8")
    )["jobs"]["pipeline"]["steps"]
    install = [one for one in steps if "packages/transport" in str(one.get("run") or "")]
    gate = [one for one in steps if "check_invisible.py" in str(one.get("run") or "")]
    assert install and gate, "шаг установки или шаг гейта не найден"
    assert install[0].get("id"), "шаг установки транспорта без id — условию не на что сослаться"
    assert f"steps.{install[0]['id']}.outcome == 'success'" in str(gate[0].get("if") or "")


def test_codes_reads_one_point_and_a_range() -> None:
    """Поле данных Unicode — одна точка или диапазон включительно."""
    assert module.codes("00AD") == range(0xAD, 0xAE)
    assert list(module.codes(" 115F..1160 ")) == [0x115F, 0x1160]
    with pytest.raises(ValueError):
        module.codes("нет")


def test_data_lines_keep_fields_and_drop_comments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Строка данных — поля до «#»; комментарий и пустая строка данными не считаются."""
    (tmp_path / "x.txt").write_text(
        "# шапка\n\n00AD  ; Prop # SOFT HYPHEN\n1820 180B; second form; isolate\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "UNICODE", tmp_path)
    assert module.data_lines("x.txt") == [
        ["00AD", "Prop"],
        ["1820 180B", "second form", "isolate"],
    ]
    with pytest.raises(module.NotRun, match="не прочитаны"):
        module.data_lines("нет.txt")


def test_property_codes_and_pairs_name_a_broken_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Свойство и пары читаются из файла; неразборное поле — «не отработал», а не находка (039)."""
    (tmp_path / "p.txt").write_text("0041..0042 ; A\n0043 ; B\n", encoding="utf-8")
    (tmp_path / "s.txt").write_text("2229 FE00; with vertical stroke;\n", encoding="utf-8")
    (tmp_path / "bad.txt").write_text("ZZZZ ; A\n", encoding="utf-8")
    monkeypatch.setattr(module, "UNICODE", tmp_path)
    assert module.property_codes("p.txt", "A") == frozenset({0x41, 0x42})
    assert module.sequence_pairs("s.txt") == frozenset({(0x2229, 0xFE00)})
    with pytest.raises(module.NotRun, match="не разобраны"):
        module.property_codes("bad.txt", "A")
    with pytest.raises(module.NotRun, match="не разобраны"):
        module.sequence_pairs("bad.txt")


def test_tables_hold_the_four_properties() -> None:
    """Таблицы — четыре свойства из `scripts/unicode/`, и каждое не пусто."""
    tables = module.tables()
    assert isinstance(tables, module.Tables)
    assert 0x034F in tables.ignorable and 0x1F9D1 in tables.pictographic
    assert 0x1F3FB in tables.modifiers and (0x26A0, 0xFE0F) in tables.variants


def test_within_holds_both_ends() -> None:
    """Диапазон — включительно с обоих концов."""
    assert module.within(0x180B, module.MONGOLIAN_SELECTORS)
    assert module.within(0x180F, module.MONGOLIAN_SELECTORS)
    assert not module.within(0x1810, module.MONGOLIAN_SELECTORS)


def test_joins_walks_back_over_the_selector_and_the_skin_tone() -> None:
    """Соединитель смотрит на основу за её тоном и селектором, а справа — на эмодзи."""
    worker = "\U0001f469\U0001f3fd\u200d\U0001f4bb"
    assert module.joins(worker, worker.index("\u200d"))
    flag = "\U0001f3f3\ufe0f\u200d\U0001f308"
    assert module.joins(flag, flag.index("\u200d"))
    assert not module.joins("1\ufe0f\u200d\U0001f4bb", 2)
    assert not module.joins("\U0001f9d1\u200d", 1), "справа ничего — соединять нечего"
    assert not module.joins("\u200d\U0001f4bb", 0), "слева ничего — соединять нечего"
