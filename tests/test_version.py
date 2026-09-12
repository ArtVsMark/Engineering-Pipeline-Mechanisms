"""Версия считается по сущностям, а не по форме истории.

Методика взята у грейдера, и вместе с ней взяты его замеры — то есть случаи,
на которых ломались топологические формулы. Здесь проверяется, что перенос
сохранил именно СУТЬ, а не только имена функций
([162](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/162-a-gap-asks-the-neighbours-first.md)):

* одно изменение считается один раз, на сколько бы коммитов его ни раздробили;
* одно изменение, попавшее в историю дважды — своим коммитом и уплотнением с
  площадки, — тоже один раз;
* след сборки значков и склеивающий мерж `git pull` изменениями не считаются;
* тегов не видно — версия не выдумывается, а объявляется неполной.

Две проверки идут по ЖИВОЙ истории и помечены `needs_history`: в чекауте без
тегов их предмета попросту нет. Что история приходит туда, где нужна, держит
гейт `version.py --check` в прогоне, а не падение проверки о чужой причине.
"""

from __future__ import annotations

import subprocess
from functools import partial
from pathlib import Path

import pytest

from tests.conftest import ROOT, RunScript, load_script, needs_history

module = load_script("version.py")


def test_a_squashed_change_is_counted_by_its_number() -> None:
    """Изменение опознаётся по номеру в теме уплотнения."""
    assert module.numbers_in(["feat(x): что-то (#42)"]) == {"42"}


def test_a_merge_commit_names_the_same_change() -> None:
    """`Merge pull request #N` — та же форма номера, что и `(#N)`.

    В истории этого проекта есть обе: ранние изменения слиты мержем, поздние
    уплотнением. Читать только одну значило бы потерять половину счёта.
    """
    assert module.numbers_in(["Merge pull request #6 from ArtVsMark/agent/x"]) == {"6"}


def test_one_change_counted_once_however_it_was_split() -> None:
    """Раздробленная на коммиты работа даёт ОДНО изменение.

    Считаются сущности, а не рёбра графа: иначе дробление работы завышало бы
    версию, а это решение автора, к принятым изменениям отношения не имеющее.
    """
    assert module.numbers_in(["a (#42)", "b (#42)", "Merge pull request #42 from x"]) == {"42"}


@pytest.mark.parametrize(
    "subject",
    [
        "факты и значок на abc1234",
        "Merge branch 'main' of https://github.com/o/r",
        "Merge remote-tracking branch 'origin/main'",
    ],
    ids=["значки", "pull по url", "мерж отслеживаемой"],
)
def test_a_trace_of_machinery_is_not_a_change(subject: str) -> None:
    """След сборки и склеивающий мерж изменениями не считаются.

    Первый не изменение вовсе, второй — не СВОЁ изменение: он сводит две копии
    одной ветки. Оба приходят от механики, а не от работы.
    """
    assert module.counts_alone(subject) is False


def test_a_merge_of_a_work_branch_is_a_change() -> None:
    """Мерж ветки-работы считается: в нём и есть принятая работа.

    Граница со склеивающим мержем тонкая и названа образцом: `Merge branch 'x'
    of <url>` сводит копии одной ветки, `Merge branch 'feat'` вливает работу.
    """
    assert module.counts_alone("Merge branch 'agent/feature'") is True


def test_a_release_tag_is_strictly_shaped() -> None:
    """Релизный тег — строго `vX.Y.Z`, служебный за него не сходит.

    У соседа служебный тег вида `v-checkpoint-…` подходил под наивную маску
    `v*`, оказывался ближе релизного и ронял разбор версии вместе со сборкой
    значка.
    """
    assert module.RELEASE_TAG_RE.match("v1.10.0")
    assert not module.RELEASE_TAG_RE.match("v-checkpoint-2026-06-24")
    assert not module.RELEASE_TAG_RE.match("v1.10.0-rc")


def test_the_declared_version_is_read_from_its_single_source() -> None:
    """MAJOR.MINOR до тега берутся из объявленного контракта, а не из воздуха."""
    assert module.RELEASE_TAG_RE.match(f"v{module.declared()}")


@needs_history
def test_the_project_version_is_computed_not_written() -> None:
    """Версия проекта считается механизмом и имеет вид X.Y.N."""
    number, whole = module.version()
    assert module.RELEASE_TAG_RE.match(f"v{number}"), number
    assert whole is True, "релизных тегов не видно — в дереве с историей это дефект входа"


@needs_history
def test_the_patch_is_the_count_of_accepted_changes() -> None:
    """PATCH — число принятых изменений, а не номер патч-релиза.

    Проверяется по живой истории: изменений после тега у проекта заведомо
    больше одного, и счёт обязан это показывать.
    """
    number, _ = module.version()
    assert int(number.split(".")[2]) > 1


def test_a_clone_without_tags_says_so(run_script: RunScript, tmp_path: Path) -> None:
    """Тегов не видно — версия объявляется неполной, а не выдумывается.

    Так клонирует облачное окно и `actions/checkout` без `fetch-depth: 0`:
    `0.0.N` выглядел бы правдоподобно, будучи ложью (045).
    """
    (tmp_path / "CONTRACT_VERSION").write_text("9.9.0\n", encoding="utf-8")
    run = run_script("version.py", "--check", cwd=tmp_path)
    assert run.code == 3, run.text
    assert "тегов не видно" in run.text
    assert "git fetch --tags" in run.text


def test_the_tag_and_the_contract_version_are_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Расхождение тега с версией контракта — ЗАКОННОЕ состояние, а не дефект.

    Числа развязаны решением
    `docs/decisions/017-a-release-moves-the-minor-the-contract-moves-itself.md`:
    выпуск двигает минор тега всегда, а версия контракта поднимается только
    вместе с тронутой поверхностью. Прежняя сверка называла такое расхождение
    дефектом — и после развязки ругалась бы на каждом заходе, то есть приучала
    бы себя обходить (051). Поэтому её не стало, и держится это тем, что имени
    в модуле больше нет.
    """
    assert not hasattr(module, "agrees"), "сверка вернулась: она спорит с решением 017"
    monkeypatch.setattr(module, "release_tag", lambda root=None: "v9.9.0")
    number, whole = module.version()
    assert number.startswith("9.9."), number
    assert whole is True


def test_the_version_is_not_written_by_hand() -> None:
    """Механизм не вписывает версию в дерево — он её считает.

    Правило 035 держится тем, что второго места, откуда версию можно прочитать,
    не заводится: `CONTRACT_VERSION` объявляет MAJOR.MINOR, всё остальное
    выводится из истории.
    """
    source = (ROOT / "scripts" / "version.py").read_text(encoding="utf-8")
    assert "write_text" not in source, "механизм версии пишет в дерево"


def test_a_prerelease_tag_does_not_swallow_the_release(tmp_path: Path) -> None:
    """Предрелизный тег рядом не делает «выпусков не видно вовсе».

    Прежде спрашивался ближайший тег по образцу, и предрелизный под образец
    подходит, а под строгую форму — нет: ответом становилось `None`, хотя рядом
    лежал настоящий выпуск. Один предрелизный тег обнулял бы версию проекта и
    значок. Нашёл внешний взгляд на #106.
    """
    run = partial(subprocess.run, cwd=tmp_path, check=True, capture_output=True)
    run(["git", "init", "--quiet", "-b", "main"])
    (tmp_path / "readme.md").write_text("раз\n", encoding="utf-8")
    run(["git", "add", "-A"])
    run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "раз"])
    run(["git", "tag", "v7.3.0"])
    (tmp_path / "readme.md").write_text("два\n", encoding="utf-8")
    run(["git", "add", "-A"])
    run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "два (#7)"])
    run(["git", "tag", "v7.4.0-rc1"])

    assert module.release_tag(tmp_path) == "v7.3.0"
    number, whole = module.version(tmp_path)
    assert whole is True
    assert number == "7.3.1"


@needs_history
def test_the_tree_is_the_one_asked_about(tmp_path: Path) -> None:
    """Версия считается по НАЗВАННОМУ дереву, а не по текущему каталогу.

    Помечено историей: вторая половина спрашивает НАСТОЯЩЕЕ дерево, а в
    обрезанном чекауте тегов нет вовсе — тест краснел бы на здоровом дереве, о
    котором ему нечего сказать. Нашёл внешний взгляд на #158.

    Сборка фактов принимает корень и передаёт его во всё — кроме версии, и та
    отвечала про настоящее дерево проекта, каким бы дерево ни назвал зовущий.
    """
    run = partial(subprocess.run, cwd=tmp_path, check=True, capture_output=True)
    run(["git", "init", "--quiet", "-b", "main"])
    (tmp_path / "readme.md").write_text("раз\n", encoding="utf-8")
    run(["git", "add", "-A"])
    run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "раз"])
    assert module.release_tag(tmp_path) is None
    assert module.release_tag() is not None
