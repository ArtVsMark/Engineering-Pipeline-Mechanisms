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
        (f"Держит ({LINK}): приём взят.\n", False),
        (f"Ни у кого нет, спросили семью — {BARE}\n", True),
        # Словоформы: приёмка, приемлемо, соседний и подключение — не ответ семьи.
        (f"Спросили семью ([162]({BARE})): приёмка — пунктами.\n", False),
        ("Спросили семью (162): приемлемо.\n", False),
        ("Соседний гейт (162): приём взят.\n", False),
        ("Спросили семью (162): подключение потребителя описано.\n", False),
        ("Сосед (162) подключён готовым.\n", True),
        ("Спросили соседей (162): приёмы у них свои, для себя.\n", True),
        # Формы адреса (210, взгляды на #1490): любая из них — не слова абзаца.
        (f"Держит ([162]({REL})): приём взят.\n", False),
        (f"Держит [162]: приём взят.\n[162]: {REL}\n", False),
        (f"Держит 162 — {REL.removeprefix('../')}: приём взят.\n", False),
        ("Держит 162 (162-a-gap-asks-the-neighbours-first.md): приём взят.\n", False),
        ("Спросили семью/соседа (162): ни у кого нет.\n", True),
        (f"Спросили семью — {REL} — ни у кого нет.\n", True),
        # Строгое правило (build-a-gate, 3а): ответ — только русскими словами,
        # и латиница не бывает ответом ни в какой форме адреса (взгляд на #1496).
        ("Держит ([162](#162-a-gap-asks-the-neighbours-first)): приём взят.\n", False),
        ("Держит 162-a-gap-asks-the-neighbours-first: приём взят.\n", False),
        ("Asked the family (162): nobody has it.\n", False),
        ("Asked family/neighbours (162): no one has it.\n", False),
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
