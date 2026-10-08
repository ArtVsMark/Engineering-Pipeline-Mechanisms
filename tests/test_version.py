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

import subprocess
from functools import partial
from pathlib import Path

import pytest

from tests.conftest import FAKE_VERSION, ROOT, RunScript, load_script, needs_history

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
    assert module.is_release_tag("v1.10.0")
    assert not module.is_release_tag("v-checkpoint-2026-06-24")
    assert not module.is_release_tag("v1.10.0-rc")


def test_the_declared_version_is_read_from_its_single_source() -> None:
    """MAJOR.MINOR до тега берутся из объявленного контракта, а не из воздуха."""
    assert module.is_release_tag(f"v{module.declared()}")


@needs_history
def test_the_project_version_is_computed_not_written() -> None:
    """Версия проекта считается механизмом и имеет вид X.Y.N."""
    number, whole = module.version()
    assert module.is_release_tag(f"v{number}"), number
    assert whole is True, "релизных тегов не видно — в дереве с историей это дефект входа"


@needs_history
def test_the_patch_is_the_count_of_accepted_changes() -> None:
    """PATCH — число принятых изменений после тега, а не номер патч-релиза.

    СПРАШИВАЕТСЯ ОБЩАЯ ВЕТКА, А НЕ ГОЛОВА РАБОТЫ. Счёт — свойство принятого, и
    на ветке в работе он ещё не определён: её коммиты номера не имеют, пока их
    не приняли.

    СВЕРЯЕТСЯ СО СЧЁТОМ, А НЕ С «БОЛЬШЕ ОДНОГО». Прежняя проверка опиралась на
    то, что изменений после тега «заведомо больше одного», — верно в любой
    день, кроме дня выпуска: 13.09.2026 тег встал на голову, счёт стал нулём, и
    проверка покраснела на исправном механизме. Ноль сразу после выпуска —
    законное состояние, а не дефект
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    """
    tag = module.release_tag()
    span = f"{tag}..origin/main"
    counted = module.changes_in(span)
    # Независимая оценка: первопредки общей ветки после тега. Признак другой —
    # рёбра графа, а не сущности, — и на нашей истории они обязаны сойтись:
    # каждое принятое изменение приезжает в общую ветку одним уплотнением.
    listed = subprocess.run(
        ["git", "rev-list", "--count", "--first-parent", span],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=True,
    ).stdout.strip()
    assert counted == int(listed), (
        f"механизм насчитал {counted} принятых изменений после {tag}, а первопредков там {listed}"
    )


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


def test_a_project_without_any_version_is_not_applicable(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Ни тега, ни CONTRACT_VERSION — сверка неприменима, а без `--check` это отказ (#1187)."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    run = run_script("version.py", "--check", cwd=tmp_path)
    assert run.code == 0, run.text
    assert "неприменимо" in run.text
    assert run_script("version.py", cwd=tmp_path).code == 2


def test_a_shallow_clone_without_any_version_is_still_partial(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Мелкий клон без тегов и файла — третий исход с подсказкой, а не «неприменимо» (#1192)."""
    origin = tmp_path / "исток"
    origin.mkdir()
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "а"]):
        subprocess.run(
            ["git", "-c", "user.name=т", "-c", "user.email=т@т", *args], cwd=origin, check=True
        )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=т",
            "-c",
            "user.email=т@т",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "б",
        ],
        cwd=origin,
        check=True,
    )
    clone = tmp_path / "клон"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{origin}", str(clone)], check=True
    )
    run = run_script("version.py", "--check", cwd=clone)
    assert run.code == 3, run.text
    assert "мелкий" in run.text and "неприменимо" not in run.text


def _repo_with_a_release(where: Path) -> None:
    """Источник с одним коммитом и выпускным тегом."""
    where.mkdir()
    for args in (
        ["init", "-q"],
        ["commit", "-q", "--allow-empty", "-m", "а"],
        ["tag", "v1.0.0"],
    ):
        subprocess.run(
            ["git", "-c", "user.name=т", "-c", "user.email=т@т", *args], cwd=where, check=True
        )


def test_outside_a_repository_the_check_is_a_refusal(run_script: RunScript, tmp_path: Path) -> None:
    """Вне репозитория git не отвечает — «не отработал», а не «неприменимо» (взгляд на #1192)."""
    run = run_script("version.py", "--check", cwd=tmp_path)
    assert run.code == 2, run.text
    assert "неприменимо" not in run.text


def test_a_full_clone_without_tags_whose_origin_has_them_is_partial(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Полный клон `--no-tags` проекта с тегами — подсказка подтянуть теги, а не «неприменимо»."""
    origin = tmp_path / "исток"
    _repo_with_a_release(origin)
    clone = tmp_path / "клон"
    subprocess.run(["git", "clone", "-q", "--no-tags", str(origin), str(clone)], check=True)
    run = run_script("version.py", "--check", cwd=clone)
    assert run.code == 3, run.text
    assert "git fetch --tags" in run.text and "неприменимо" not in run.text


def test_a_silent_origin_does_not_prove_the_absence(run_script: RunScript, tmp_path: Path) -> None:
    """Источник не ответил о тегах — отсутствие не доказано, третий исход, а не «неприменимо»."""
    origin = tmp_path / "исток"
    _repo_with_a_release(origin)
    clone = tmp_path / "клон"
    subprocess.run(["git", "clone", "-q", "--no-tags", str(origin), str(clone)], check=True)
    subprocess.run(
        ["git", "remote", "set-url", "origin", str(tmp_path / "нет")], cwd=clone, check=True
    )
    run = run_script("version.py", "--check", cwd=clone)
    assert run.code == 3, run.text
    assert "не доказано" in run.text


def test_the_provider_keeps_its_version_source() -> None:
    """У поставщика источник версии есть: «неприменимо» не спрячет его пропажу (#1187)."""
    paths = load_script("paths.py")
    assert (ROOT / paths.VERSION).is_file()


def test_a_whole_clone_reports_the_version_and_says_nothing_else(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Полное дерево: версия печатается, исход чистый.

    Прогонялся только НЕПОЛНЫЙ вход — обрезанный клон. «Чисто» у этого шага
    объявлено, но не проверялось ни разу, а объявление поведением не является
    ([145](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/145-every-declared-outcome-is-run.md)).
    """
    git = partial(subprocess.run, cwd=tmp_path, check=True, capture_output=True)
    git(["git", "init", "--quiet", "-b", "main"])
    git(["git", "config", "user.email", "кто@то"])
    git(["git", "config", "user.name", "Кто-то"])
    (tmp_path / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    git(["git", "add", "-A"])
    git(["git", "commit", "--quiet", "-m", "начало"])
    git(["git", "tag", f"v{FAKE_VERSION}"])

    run = run_script("version.py", "--check", cwd=tmp_path)
    assert run.code == module.EXIT_OK, run.text
    assert FAKE_VERSION in run.text


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


def test_a_subject_with_two_numbers_counts_as_one_change() -> None:
    """Из темы берётся ОДИН номер — последний, приписанный площадкой (#582).

    ЗАМЕР, РАДИ КОТОРОГО ПРАВКА И ПОЯВИЛАСЬ. Общая ветка покраснела на слиянии
    #579: тема вышла «… (#551) (+2) (#579)» — номер задачи от автора и номер
    изменения от площадки, — и два независимых счёта принятых изменений
    разошлись: по сущностям 14, по рёбрам графа 13.

    Вторая половина здесь же: обычная тема с одним номером читается как прежде,
    иначе «берём последний» неотличимо от «не берём ничего».
    """
    said = module.numbers_in(["Заголовок работы (#551) (+2) (#579)"])
    assert said == {"579"}, f"из темы с двумя номерами взято не одно изменение: {said}"
    assert module.numbers_in(["Обычная тема (#578)"]) == {"578"}
    assert module.numbers_in(["Тема без номера вовсе"]) == set()


def test_a_merge_subject_still_names_its_change() -> None:
    """Слияние мержем читается по-прежнему: у него номер стоит НЕ в скобках.

    Половина, которую забывают: «берём последний из скобок» не должно отменять
    вторую форму, у которой скобок нет вовсе.
    """
    assert module.numbers_in(["Merge pull request #42 from ArtVsMark/x"]) == {"42"}


def test_digits_read_the_number_by_the_shared_form() -> None:
    """Разряды берутся общим разбором; не номер — отказ, а не нарезка (214)."""
    assert module.digits("1.10.3") == (1, 10, 3)
    assert module.bare("v1.10.3") == "1.10.3"
    with pytest.raises(module.NotRun):
        module.digits("1.10")


def test_absence_names_why_the_tags_are_missing(tmp_path: Path) -> None:
    """`absence` различает: нет у проекта, не принесли, источник молчит, git не ответил."""
    with pytest.raises(module.NotRun):
        module.absence(tmp_path)
    origin = tmp_path / "исток"
    _repo_with_a_release(origin)
    assert module.absence(origin) == module.ABSENCE_NONE
    clone = tmp_path / "клон"
    subprocess.run(["git", "clone", "-q", "--no-tags", str(origin), str(clone)], check=True)
    assert module.absence(clone) == module.ABSENCE_UNFETCHED
    subprocess.run(
        ["git", "remote", "set-url", "origin", str(tmp_path / "нет")], cwd=clone, check=True
    )
    assert module.absence(clone) == module.ABSENCE_UNASKED


def _bare_repo(where: Path) -> None:
    """Источник с коммитом и без единого тега."""
    where.mkdir()
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "а"]):
        subprocess.run(
            ["git", "-c", "user.name=т", "-c", "user.email=т@т", *args], cwd=where, check=True
        )


def test_a_full_clone_whose_origin_answered_without_tags_is_not_applicable(
    tmp_path: Path,
) -> None:
    """Главная ветка: клон полный, источник ответил, тегов нет — `NONE` (взгляд на #1200)."""
    origin = tmp_path / "исток"
    _bare_repo(origin)
    clone = tmp_path / "клон"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    assert module.absence(clone) == module.ABSENCE_NONE


def test_a_release_tag_off_the_head_history_is_not_an_absence(tmp_path: Path) -> None:
    """Тег в клоне есть, но не в истории HEAD — у проекта теги есть, и это не «нет» (#1200)."""
    origin = tmp_path / "исток"
    _bare_repo(origin)
    run = partial(subprocess.run, cwd=origin, check=True, capture_output=True)
    run(["git", "checkout", "-q", "-b", "сбоку"])
    run(
        [
            "git",
            "-c",
            "user.name=т",
            "-c",
            "user.email=т@т",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "б",
        ]
    )
    run(["git", "tag", "v1.0.0"])
    run(["git", "checkout", "-q", "-"])
    assert module.release_tag(origin) is None
    assert module.absence(origin) == module.ABSENCE_ELSEWHERE


def test_the_source_is_the_upstream_then_origin_then_the_only_one(tmp_path: Path) -> None:
    """Источник — upstream, иначе `origin`, иначе единственный; иначе спросить не у кого (#1200)."""
    origin = tmp_path / "исток"
    _bare_repo(origin)
    clone = tmp_path / "клон"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    subprocess.run(["git", "remote", "add", "afork", str(origin)], cwd=clone, check=True)
    upstream = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "@{u}"],
        cwd=clone,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    assert module.source_of(["afork", "origin"], clone) == upstream.split("/", 1)[0]
    subprocess.run(["git", "checkout", "-q", "--detach"], cwd=clone, check=True)
    assert module.source_of(["afork", "origin"], clone) == "origin", "без upstream — не origin"
    lone = tmp_path / "одинокий"
    _bare_repo(lone)
    assert module.source_of(["один"], lone) == "один"
    assert module.source_of(["а", "б"], lone) is None


def test_asking_the_source_names_its_tags_or_says_it_did_not_answer(tmp_path: Path) -> None:
    """`ask_tags` отдаёт выпускные теги источника, а молчащий источник — `None`, не пустоту."""
    origin = tmp_path / "исток"
    _repo_with_a_release(origin)
    assert "refs/tags/v1.0.0" in (module.ask_tags(str(origin), tmp_path) or "")
    assert module.ask_tags(str(tmp_path / "нет"), tmp_path) is None
