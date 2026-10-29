"""Новый механизм называет, у кого из семьи спросили и что нашли (162, #1440).

Проверяется гейт тем, что он обязан отвергнуть: новый механизм без записи, запись
без ответа и запись, разорванная по абзацам. Законное — запись в одном абзаце,
прежний механизм и переименование — проходит.
"""

import subprocess
from pathlib import Path

import pytest

from tests.conftest import ROOT, RunScript, load_script

module = load_script("check_asked_family.py")

#: Адрес правила 162 у каталога — в нём слово «neighbours».
BARE = "https://example.org/rules/ru/162-a-gap-asks-the-neighbours-first.md"
#: Ссылка на правило так, как её пишут в тексте механизма.
LINK = f"[162]({BARE})"
#: Тот же адрес относительным путём — так ссылается на правила каталог.
REL = "../rules/ru/162-a-gap-asks-the-neighbours-first.md"
#: Запись, как её пишут у нас: номер правила в одной строке, ответ — в следующей.
RECORD = (
    "**Сперва спросили семью**\n"
    "([162](https://example.org/162-a-gap-asks-the-neighbours-first.md)):\n"
    "приём взят у навыка каталога — ссылкой, а не копией.\n"
)


@pytest.mark.parametrize(
    ("text", "said"),
    [
        (RECORD, True),
        ("# СПЕРВА СПРОСИЛИ СЕМЬЮ (162).\n# Ни у кого нет — строим своё.\n", True),
        ("Спросили соседей (162): у Token есть, но только для себя.\n", True),
        ("Держит правило 162.\n", False),
        ("Спросили соседей (162).\n", False),
        ("Приём взят у каталога (162).\n", True),
        ("Сперва спросили семью (162).\n\nПриём взят у каталога.\n", False),
        ("# Спросили семью (162).\n#\n# Ни у кого нет.\n", False),
        ("Семь шагов (1620): подключили.\n", False),
        # Адрес ссылки — не слова абзаца: «neighbours» стоит в адресе самого 162.
        (f"Держит ({LINK}): приём взят у Token.\n", False),
        (f"Ни у кого нет, спросили семью — {BARE}\n", True),
        # Словоформы: приёмка, приемлемо, соседний и подключение — не ответ семьи.
        (f"Спросили семью ([162]({BARE})): приёмка — пунктами.\n", False),
        ("Спросили семью (162): приемлемо.\n", False),
        ("Соседний гейт (162): приём взят у Token.\n", False),
        ("Спросили семью (162): подключение потребителя описано.\n", False),
        ("Сосед (162) подключён готовым.\n", True),
        ("Спросили соседей (162): приёмы у них свои, для себя.\n", True),
        # Формы адреса (210, взгляды на #1490): любая из них — не слова абзаца.
        (f"Держит ([162]({REL})): приём взят у Token.\n", False),
        (f"Держит [162]: приём взят у Token.\n[162]: {REL}\n", False),
        (f"Держит 162 — {REL.removeprefix('../')}: приём взят у Token.\n", False),
        ("Держит 162 (162-a-gap-asks-the-neighbours-first.md): приём взят у Token.\n", False),
        ("Спросили семью/соседа (162): ни у кого нет.\n", True),
        (f"Спросили семью — {REL} — ни у кого нет.\n", True),
        # Строгое правило (build-a-gate, 3а): ответ — только русскими словами,
        # и латиница не бывает ответом ни в какой форме адреса (взгляд на #1496).
        ("Держит ([162](#162-a-gap-asks-the-neighbours-first)): приём взят у Token.\n", False),
        ("Держит 162-a-gap-asks-the-neighbours-first: приём взят у Token.\n", False),
        ("Asked the family (162): nobody has it.\n", False),
        ("Asked family/neighbours (162): no one has it.\n", False),
        # Исход судится связью с источником, а не словом (210, взгляды на #1490).
        ("Спросили семью (162): шаг пишет отчёт для себя.\n", False),
        ("Спросили семью (162): взятие пошлины описано у нас.\n", False),
        ("Спросили семью (162): идейный разбор у нас.\n", False),
        ("Спросили семью (162): приём у Token свой.\n", False),
        ("Спросили семью (162). Приём взят. У каталога своё.\n", False),
        ("Спросили семью (162): у каталога взяли приём.\n", True),
        ("Спросили семью (162): идею взяли у Token.\n", True),
        # Подключённое — только готовое (взгляд на #1509).
        ("Спросили семью (162): шаг подключили к ci.yml.\n", False),
        ("Спросили семью (162): подключили готовый шаг каталога.\n", True),
        ("Спросили семью (162): всё готово, подключили.\n", False),
    ],
    ids=[
        "наш-абзац",
        "комментарий-кода",
        "у-соседа-для-себя",
        "голый-номер",
        "без-того-что-нашли",
        "каталог-и-приём",
        "разорвано-абзацем",
        "разорвано-пустым-комментарием",
        "семь-и-чужое-число",
        "у-кого-только-в-адресе",
        "номер-в-голой-ссылке",
        "приёмка-не-приём",
        "приемлемо-не-приём",
        "соседний-не-сосед",
        "подключение-не-подключили",
        "сосед-подключён",
        "приёмы-у-соседей",
        "относительная-ссылка",
        "определение-ссылки",
        "голый-путь",
        "голое-имя-файла",
        "слова-через-косую",
        "номер-в-относительном-пути",
        "якорь",
        "голый-слаг",
        "по-английски",
        "по-английски-через-косую",
        "для-себя-без-источника",
        "взятие-не-взятое",
        "идейный-не-идея",
        "голый-приём-не-исход",
        "источник-в-другом-предложении",
        "источник-перед-глаголом",
        "идея-у-соседа",
        "подключили-не-готовое",
        "подключили-готовое",
        "готово-не-готовое",
    ],
)
def test_a_record_names_the_rule_whom_and_what(text: str, said: bool) -> None:
    """Запись — абзац с номером 162, тем, у кого спросили, и тем, что нашли."""
    assert module.recorded(text) is said


def test_the_live_record_of_our_skill_is_seen() -> None:
    """Запись навыка `a-gate-obeys-every-rule` — та форма, которую гейт признаёт."""
    text = (ROOT / ".claude" / "skills" / "a-gate-obeys-every-rule" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert module.recorded(text)


def test_this_gate_names_the_family_itself() -> None:
    """Гейт — сам новый механизм, и запись о семье у него есть (162)."""
    assert module.recorded((ROOT / "scripts" / "check_asked_family.py").read_text("utf-8"))


@pytest.mark.parametrize(
    ("path", "said"),
    [
        ("scripts/check_x.py", True),
        (".claude/hooks/guard.sh", True),
        (".github/workflows/x.yaml", True),
        (".github/actions/a/action.yml", True),
        (".github/actions/a/action.yaml", True),
        (".claude/skills/s/SKILL.md", True),
        ("scripts/x.py", False),
        ("scripts/sub/check_x.py", False),
        ("docs/x.md", False),
    ],
)
def test_a_mechanism_is_known_by_its_place(path: str, said: bool) -> None:
    """Механизм — файл на местах `MECHANISMS`; соседние пути — не механизмы."""
    assert module.is_mechanism(path) is said


#: Прежний механизм на общей ветке: двадцать строк, а не одна.
OLD = '"""Прежний."""\n' + "".join(f"STEP_{one} = {one}\n" for one in range(20))


def _git(where: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=where, check=True, capture_output=True, timeout=60)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Дерево с одним механизмом на общей ветке и веткой изменения."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "them@example.com")
    _git(tmp_path, "config", "user.name", "Кто-то")
    (tmp_path / "scripts").mkdir()
    # Тело длинное: правка одной строки и переименование оставляют файлу
    # сходство, по которому git узнаёт переименование, а не удаление с добавлением.
    (tmp_path / "scripts" / "check_old.py").write_text(OLD, encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "прежний механизм")
    _git(tmp_path, "checkout", "-q", "-b", "change")
    return tmp_path


def commit(repo: Path) -> None:
    """Фиксирует всё, что лежит в дереве."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "изменение")


def test_only_an_added_mechanism_is_asked(repo: Path, run_script: RunScript) -> None:
    """Правка прежнего механизма и переименование не спрашиваются; новый — да."""
    (repo / "scripts" / "check_old.py").write_text(OLD + "# правка\n", "utf-8")
    commit(repo)
    run = run_script("check_asked_family.py", "--base", "main", cwd=repo)
    assert (run.code, "нет" in run.out) == (0, True), run.text
    _git(repo, "mv", "scripts/check_old.py", "scripts/check_moved.py")
    commit(repo)
    run = run_script("check_asked_family.py", "--base", "main", cwd=repo)
    assert run.code == 0, run.text
    (repo / "scripts" / "check_new.py").write_text('"""Новый гейт."""\n', encoding="utf-8")
    commit(repo)
    run = run_script("check_asked_family.py", "--base", "main", cwd=repo)
    assert run.code == 1 and "scripts/check_new.py" in run.out, run.text


def test_a_file_moved_onto_a_mechanism_place_is_asked(
    repo: Path, run_script: RunScript, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Переезд с немеханизменного пути на место механизма — новый механизм (#1490)."""
    _git(repo, "checkout", "-q", "main")
    (repo / "scripts" / "helper.py").write_text(OLD, encoding="utf-8")
    commit(repo)
    _git(repo, "checkout", "-q", "-B", "change", "main")
    _git(repo, "mv", "scripts/helper.py", "scripts/check_helper.py")
    commit(repo)
    monkeypatch.chdir(repo)
    assert module.added_mechanisms("main") == ["scripts/check_helper.py"]
    run = run_script("check_asked_family.py", "--base", "main", cwd=repo)
    assert run.code == 1 and "scripts/check_helper.py" in run.out, run.text


def test_the_refusal_names_the_language_and_the_skill_address(
    repo: Path, run_script: RunScript
) -> None:
    """Отказ называет строгое правило языка и полный адрес навыка — у потребителя тоже."""
    (repo / "scripts" / "check_new.py").write_text('"""Новый гейт."""\n', encoding="utf-8")
    commit(repo)
    run = run_script("check_asked_family.py", "--base", "main", cwd=repo)
    assert run.code == 1, run.text
    assert "русскими словами" in run.out and module.ASK_SKILL in run.out, run.text


def test_a_new_mechanism_with_its_record_passes(repo: Path, run_script: RunScript) -> None:
    """Новый механизм с записью о семье — зелёный."""
    (repo / "scripts" / "check_new.py").write_text(f'"""{RECORD}"""\n', encoding="utf-8")
    commit(repo)
    run = run_script("check_asked_family.py", "--base", "main", cwd=repo)
    assert run.code == 0 and "называют семью: 1" in run.out, run.text


def test_an_unknown_base_does_not_run(repo: Path, run_script: RunScript) -> None:
    """База не разобрана — третий исход, а не «новых механизмов нет» (039)."""
    run = run_script("check_asked_family.py", "--base", "нет-такой-ветки", cwd=repo)
    assert run.code == 2 and "не отработала" in run.err, run.text


def test_paragraphs_split_on_blank_and_bare_comment_lines() -> None:
    """Абзац кончается пустой строкой и строкой из одних знаков комментария."""
    text = "# первый\n# абзац\n#\n# второй\n\nтретий\n  ;;  \nчетвёртый\n"
    assert module.paragraphs(text) == ["первый абзац", "второй", "третий", "четвёртый"]


def test_added_mechanisms_are_only_the_added_ones(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Добавленный механизм — в ответе; правленый прежний и не механизм — нет."""
    (repo / "scripts" / "check_old.py").write_text(OLD + "# правка\n", "utf-8")
    (repo / "scripts" / "check_new.py").write_text('"""Новый."""\n', encoding="utf-8")
    (repo / "scripts" / "helper.py").write_text('"""Не механизм."""\n', encoding="utf-8")
    commit(repo)
    monkeypatch.chdir(repo)
    assert module.added_mechanisms("main") == ["scripts/check_new.py"]


SIGN = "# SPDX-License-Identifier: MIT — https://github.com/{}\n"
THIN = (
    "on: push\njobs:\n  lint:\n    name: lint\n"
    "    uses: {}/.github/workflows/step-lint.yml@v1.12.0\n"
)


@pytest.mark.parametrize(
    ("path", "text", "asked"),
    [
        ("scripts/check_kit.py", SIGN.format("o/поставщик") + '"""Гейт."""\n', False),
        ("scripts/check_mine.py", SIGN.format("o/свой") + '"""Гейт."""\n', True),
        (".github/workflows/ci.yml", THIN.format("o/поставщик"), False),
        (".github/workflows/ci.yml", THIN.format("o/свой"), True),
        (".github/workflows/own.yml", "on: push\njobs:\n  a:\n    steps:\n      - run: x\n", True),
    ],
    ids=["подпись-поставщика", "своя-подпись", "тонкий-вызов", "вызов-своего", "свой-прогон"],
)
def test_a_mechanism_connected_ready_is_not_asked(
    repo: Path, path: str, text: str, asked: bool
) -> None:
    """Заготовка поставщика — ответ 162 подписью или тонким вызовом; своё судится (#1743)."""
    _git(repo, "remote", "add", "origin", "https://github.com/o/свой.git")
    where = repo / path
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_text(text, encoding="utf-8")
    quiet, ready = module.silent([path], repo)
    assert (quiet, ready) == (([path], []) if asked else ([], [path]))


def test_an_unknown_self_lets_nothing_through(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Своё имя не узнать — подпись поставщика ничего не отпускает: судится как прежде (045)."""
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    (repo / "scripts" / "check_kit.py").write_text(
        SIGN.format("o/поставщик") + '"""Гейт."""\n', encoding="utf-8"
    )
    assert module.silent(["scripts/check_kit.py"], repo) == (["scripts/check_kit.py"], [])
