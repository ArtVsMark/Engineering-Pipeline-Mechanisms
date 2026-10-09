"""Обход клонов семьи: кто ВЗЯЛ наши шаги, а не кто о них сказал.

Подключившийся молча невидим реестру адресов, а молчаливое подключение —
обычный случай. Проверяется здесь то, без чего обход был бы распечаткой
памяти: вызов отличается от упоминания (166), список семьи берётся из
выгрузки каталога, а непрочитанный клон называется незнанием, а не нулём
подключений (045).
"""

import subprocess
import time
from pathlib import Path

import pytest
import yaml

from tests.conftest import ROOT, load_script

module = load_script("family_uptake.py")

CALL = (
    "jobs:\n  lint:\n    uses: ArtVsMark/Engineering-Pipeline-Mechanisms"
    "/.github/workflows/step-lint.yml@v1.2.0\n"
)


def test_a_call_is_found_with_its_step_and_version() -> None:
    """Вызов даёт и имя шага, и версию: без версии «взял» ничего не говорит."""
    steps, refs = module.calls_in(CALL)
    assert steps == ("step-lint",)
    assert refs == ("v1.2.0",)


def test_a_call_in_another_case_is_found() -> None:
    """Адрес в `uses:` площадка читает без регистра — и обход тоже."""
    steps, _refs = module.calls_in(CALL.replace("ArtVsMark/Engineering", "artvsmark/engineering"))
    assert steps == ("step-lint",)


def test_a_mention_is_not_a_call() -> None:
    """Имя проекта в прозе — не подключение (166).

    Наше имя встречается у соседей в комментариях и ссылках, и считать их
    подключением значило бы объявить взявшими всех разом.
    """
    said = (
        "# берём шаги из ArtVsMark/Engineering-Pipeline-Mechanisms, когда дойдут руки\n"
        "# см. https://github.com/ArtVsMark/Engineering-Pipeline-Mechanisms/blob/main/docs/use/onboarding.md\n"
    )
    assert module.calls_in(said) == ((), ())


def test_two_versions_at_one_consumer_are_named() -> None:
    """Разные версии у одного потребителя — находка, а не мелочь (152).

    Так выглядит недоведённый переезд: часть шагов уехала на новый тег, часть
    осталась, и снаружи это неотличимо от осознанного выбора.
    """
    said = CALL + CALL.replace("step-lint.yml@v1.2.0", "step-debt.yml@v1.1.0")
    steps, refs = module.calls_in(said)
    assert steps == ("step-debt", "step-lint")
    assert refs == ("v1.1.0", "v1.2.0")
    line = module.Took(repo="o/r", steps=steps, refs=refs).said()
    assert "разные версии" in line, line


def test_one_version_is_not_a_finding() -> None:
    """Вторая половина: одна версия у потребителя — не находка.

    Без неё строка кричала бы на каждом исправном подключении, а такое учат
    пропускать (051).
    """
    line = module.Took(repo="o/r", steps=("step-lint",), refs=("v1.2.0",)).said()
    assert "разные версии" not in line
    assert "v1.2.0" in line and "step-lint" in line


def test_taking_nothing_is_said_in_words() -> None:
    """«Не взял ничего» — состояние, названное словом, а не пустая строка."""
    assert "не взял ничего" in module.Took(repo="o/r", steps=(), refs=()).said()


def test_we_are_not_counted_among_the_family(monkeypatch: pytest.MonkeyPatch) -> None:
    """Себя обход не считает: мы свой первый потребитель, но не сосед.

    Иначе сводка всегда показывала бы одного взявшего — нас, — и «никто не
    взял» стало бы невыразимым.
    """
    monkeypatch.setattr(
        module.ghrest,
        "raw_json",
        lambda *_: {"consumers": [{"repo": module.OURS}, {"repo": "o/сосед"}]},
    )
    assert module.family() == ["o/сосед"]


def test_a_family_of_only_us_is_the_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """В сводке только мы — обходить некого, и это отказ, а не «никто не взял» (075)."""
    monkeypatch.setattr(
        module.ghrest, "raw_json", lambda *_: {"consumers": [{"repo": module.OURS}]}
    )
    with pytest.raises(module.NotRun, match="обходить некого"):
        module.family()


def test_an_empty_summary_is_the_third_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сводка пуста — предмета нет, и заход это говорит."""
    monkeypatch.setattr(module.ghrest, "raw_json", lambda *_: {"consumers": []})
    with pytest.raises(module.NotRun, match="обходить некого"):
        module.family()


def test_an_unreadable_summary_is_not_an_empty_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ транспорта и пустая сводка — разные ответы (045)."""

    def broken(*_a: object) -> None:
        raise module.ghrest.TransportError("снимок не прочитан")

    monkeypatch.setattr(module.ghrest, "raw_json", broken)
    with pytest.raises(module.NotRun, match="не прочитана"):
        module.family()


def test_an_unread_clone_is_not_a_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Клон не взят — сосед попадает в «не прочитано», а не в «не взял».

    Частный репозиторий, упавшая сеть и отсутствие ветки снаружи одинаковы, а
    значат разное: выдать их за ноль подключений значило бы объявить сводку
    полной там, где она неполна.
    """

    def refuse(repo: str, _where: Path, **_: object) -> None:
        raise module.NotRun(f"{repo}: клон не взят")

    monkeypatch.setattr(module, "took", refuse)
    seen, unread = module.sweep(["o/один", "o/два"], tmp_path)
    assert seen == []
    assert unread == ["o/один", "o/два"]
    lines = module.report_lines(seen, unread, ["lint"])
    assert any("не прочитано клонов: 2" in line for line in lines), lines
    assert any("незнание" in line for line in lines), lines


def test_one_refusal_does_not_fell_the_sweep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Вторая половина: отказ по одному соседу не прячет состояние остальных."""

    def half(repo: str, _where: Path, **_: object):  # type: ignore[no-untyped-def]
        if repo == "o/один":
            raise module.NotRun("клон не взят")
        return module.Took(repo=repo, steps=("step-lint",), refs=("v1.2.0",))

    monkeypatch.setattr(module, "took", half)
    seen, unread = module.sweep(["o/один", "o/два"], tmp_path)
    assert [one.repo for one in seen] == ["o/два"]
    assert unread == ["o/один"]


def test_a_neighbour_without_workflows_took_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Каталога прогонов нет — «не взял», а не отказ: конвейера у соседа может не быть.

    Настоящий клон здесь не делается: предмет проверки — разбор ОТСУТСТВИЯ
    каталога, а не работа git.
    """
    monkeypatch.setattr(module, "shallow_clone", lambda _repo, _where, **_: tmp_path)
    got = module.took("o/пустой", tmp_path)
    assert got.steps == () and got.refs == ()


def test_the_clone_is_shallow_and_sparse() -> None:
    """Клон берётся поверхностным и частичным, а не целиком.

    Прогонов у соседа до тринадцати, а дерево целиком нам не нужно: за трафик
    платит и он тоже. Признак назван ключами команды, а не замером скорости —
    скорость зависит от сети, а ключи от нас.
    """
    source = (Path("scripts") / "family_uptake.py").read_text(encoding="utf-8")
    for key in ("--depth", "--filter=blob:none", "--sparse", "sparse-checkout"):
        assert key in source, f"клон берётся без «{key}» — это уже не поверхностный обход"


def test_the_sweep_reaches_its_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Оба исхода захода ПРОГОНЯЮТСЯ, а не только объявлены (039, 145)."""
    monkeypatch.setattr(module, "family", lambda **_: ["o/сосед"])
    monkeypatch.setattr(
        module, "took", lambda repo, _where, **_: module.Took(repo=repo, steps=(), refs=())
    )
    assert module.main([]) == module.EXIT_OK

    def refuse(repo: str, _where: Path, **_: object) -> None:
        raise module.NotRun(f"{repo}: клон не взят")

    monkeypatch.setattr(module, "took", refuse)
    assert module.main([]) == module.EXIT_UNREAD


def test_a_broken_family_list_is_its_own_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Список семьи не прочитан — второй исход, а не пустая сводка."""

    def broken(**_: object) -> None:
        raise module.NotRun("сводка семьи не прочитана")

    monkeypatch.setattr(module, "family", broken)
    assert module.main([]) == module.EXIT_BROKEN


def test_a_timeout_is_caught_like_any_other_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Зависший сосед не вешает обход: предел ожидания объявлен и ловится.

    Без предела заход стоит на недоступном соседе и не доходит до остальных —
    то есть один медленный прячет состояние всех.
    """

    def slow(repo: str, _where: Path, **_: object) -> None:
        raise subprocess.TimeoutExpired(cmd=["git", "clone", repo], timeout=module.TIMEOUT)

    monkeypatch.setattr(module, "took", slow)
    seen, unread = module.sweep(["o/медленный"], tmp_path)
    assert seen == [] and unread == ["o/медленный"]


def test_a_shallow_clone_brings_only_the_workflows(tmp_path: Path) -> None:
    """Клон берётся по-настоящему — на локальном репозитории, без сети.

    Подменять `shallow_clone` во всех проверках значило бы не проверить его ни
    разу: подменённое имя снаружи неотличимо от непроверенного (146). Источник
    здесь локальный, поэтому проверка не зависит ни от сети, ни от соседей.
    """
    source = tmp_path / "сосед"
    (source / ".github" / "workflows").mkdir(parents=True)
    (source / ".github" / "workflows" / "ci.yml").write_text(CALL, encoding="utf-8")
    (source / "лишнее.txt").write_text("не нужно", encoding="utf-8")
    run = ["git", "-C", str(source)]
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(source)], check=True)
    subprocess.run([*run, "config", "user.email", "т@т"], check=True)
    subprocess.run([*run, "config", "user.name", "т"], check=True)
    subprocess.run([*run, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*run, "commit", "--quiet", "-m", "прогоны"], check=True)

    into = tmp_path / "клоны"
    into.mkdir()
    got = module.shallow_clone("сосед", into, host=str(tmp_path))
    assert (got / ".github" / "workflows" / "ci.yml").is_file(), "прогоны не приехали"


def test_a_clone_that_refuses_is_named(tmp_path: Path) -> None:
    """Источника нет — отказ с причиной, а не пустой клон (075)."""
    with pytest.raises(module.NotRun, match="клон не взят"):
        module.shallow_clone("нет-такого", tmp_path, host=str(tmp_path))


def test_a_refused_narrowing_is_not_an_empty_neighbour(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Сужение отказало — сосед «не прочитан», а не «не взял ничего».

    Без сужения каталога прогонов в клоне нет, и обход ответил бы нулём: отказ
    инструмента выглядел бы состоянием соседа (045). Нашёл внешний взгляд на
    #569.

    ИСХОД ЧУЖОГО ИНСТРУМЕНТА ЗДЕСЬ ПОДДЕЛАН, И ЭТО ГРАНИЦА, А НЕ ПОБЛАЖКА.
    `sparse-checkout set` отказывает у git без поддержки частичных клонов —
    такой версии в окне нет, а на здешней команда принимает даже заведомо
    негодный довод. Подделывается ровно исход внешней команды; всё, что
    проверяется, — как обход его ЧИТАЕТ
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    """
    real = subprocess.run

    def refuse_narrowing(args, **kwargs):  # type: ignore[no-untyped-def]
        if "sparse-checkout" in args:
            return subprocess.CompletedProcess(args, 1, "", "fatal: сужение не поддержано")
        return real(args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", refuse_narrowing)
    source = tmp_path / "сосед"
    (source / ".github" / "workflows").mkdir(parents=True)
    (source / ".github" / "workflows" / "ci.yml").write_text(CALL, encoding="utf-8")
    run = ["git", "-C", str(source)]
    real(["git", "init", "--quiet", "-b", "main", str(source)], check=True)
    real([*run, "config", "user.email", "т@т"], check=True)
    real([*run, "config", "user.name", "т"], check=True)
    real([*run, "add", "-A"], check=True, capture_output=True)
    real([*run, "commit", "--quiet", "-m", "прогоны"], check=True)

    into = tmp_path / "клоны"
    into.mkdir()
    with pytest.raises(module.NotRun, match="сузить"):
        module.shallow_clone("сосед", into, host=str(tmp_path))


def test_the_uptake_counts_projects_and_offered_steps() -> None:
    """Числа «взяли вызовом»: проект со шагом по тегу засчитан, позванное не отдаваемое — нет.

    Решение владельца 07.10.2026 (#1199): знаменатель проектов — вся семья без
    нас, непрочитанный клон в нём назван, а не засчитан «не взял»; знаменатель
    шагов — отдаваемые наружу.
    """
    # Имена шагов — из настоящего `calls_in`, а не собраны рукой: рукой
    # собранное «lint» прятало, что вызов называет файл `step-lint` (взгляд на #1241, 107).
    call = CALL.replace("step-lint", "step-secret") + CALL
    steps, refs = module.calls_in(call)
    took = module.Took(repo="o/a", steps=steps, refs=refs)
    none = module.Took(repo="o/b", steps=(), refs=())
    said = module.uptake([took, none], ["o/c"], ["lint", "facts"])
    assert said["projects"] == {"took": 1, "of": 3, "unread": 1, "unread_repos": ["o/c"]}
    assert said["steps"] == {"taken": 1, "of": 2, "names": ["lint"]}
    assert said["by"] == [
        {"repo": "o/a", "steps": ["step-lint", "step-secret"], "refs": ["v1.2.0"]}
    ]


def test_a_project_calling_only_what_we_do_not_offer_took_nothing() -> None:
    """Позвал только неотдаваемый шаг — проект не «взял»: числа проектов и шагов согласны."""
    steps, refs = module.calls_in(CALL.replace("step-lint", "step-secret"))
    said = module.uptake([module.Took("o/a", steps, refs)], [], ["lint"])
    assert said["projects"]["took"] == 0 and said["steps"]["taken"] == 0


def test_print_and_facts_count_the_same_takers() -> None:
    """Печать и факты одного захода считают «взял» одним правилом (взгляд на #1241, 022)."""
    ours, _ = module.calls_in(CALL)
    other, _ = module.calls_in(CALL.replace("step-lint", "step-secret"))
    seen = [module.Took("o/a", ours, ("v1",)), module.Took("o/b", other, ("v1",))]
    assert [one.repo for one in module.takers(seen, ["lint"])] == ["o/a"]
    assert module.report_lines(seen, [], ["lint"])[0] == "взяли наши шаги: 1 из 2 прочитанных"
    assert module.uptake(seen, [], ["lint"])["projects"]["took"] == 1


def test_a_spent_budget_keeps_what_was_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Время вышло — прочитанные остаются в числах, остальные названы непрочитанными."""
    ticks = iter([0.0, 0.0, 100.0])
    asked: list[float] = []

    def fast(repo: str, _where: Path, timeout: float = 0) -> object:
        asked.append(timeout)
        return module.Took(repo=repo, steps=(), refs=())

    monkeypatch.setattr(module, "took", fast)
    seen, unread = module.sweep(["o/a", "o/b"], tmp_path, budget=10, clock=lambda: next(ticks))
    assert [one.repo for one in seen] == ["o/a"] and unread == ["o/b"]
    assert asked == [10.0], "ожидание git не урезано до остатка бюджета"


def test_the_step_limit_covers_the_worst_sweep() -> None:
    """Предел шага обхода в `badges.yml` выше худшего случая самого обхода — с запасом.

    Худший случай — `BUDGET + 2 × TIMEOUT`: последний начатый сосед получает
    оба вызова git. Связь держит этот тест, а не комментарий: поднятый `BUDGET`
    при прежнем пределе снял бы шаг раньше обхода, и файл пропал бы вместе с
    прочитанными клонами (взгляд на #1246). Запас `STEP_MARGIN` — на запуск
    Python и уборку клонов: без него гейт проходил с запасом в секунды.
    """
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "badges.yml").read_text("utf-8"))
    limits = [
        step.get("timeout-minutes")
        for job in flow["jobs"].values()
        for step in job.get("steps") or []
        if "family_uptake.py" in str(step.get("run") or "")
    ]
    assert limits, "шаг обхода клонов в badges.yml не найден или без своего предела (075)"
    need = module.BUDGET + 2 * module.TIMEOUT + module.STEP_MARGIN
    assert all(limit is not None and limit * 60 >= need for limit in limits), (
        f"предел шага {limits} мин ниже худшего случая обхода с запасом: {need} с"
    )


def test_one_hung_neighbour_cannot_eat_the_whole_budget() -> None:
    """Оба вызова одного соседа короче бюджета: повисший первым не прячет остальных (#1246)."""
    assert 2 * module.TIMEOUT < module.BUDGET


def test_a_timed_out_call_does_not_wait_for_its_children() -> None:
    """Снятие по пределу возвращается сразу, даже если потомок держит каналы открытыми.

    Предел вызова git (`TIMEOUT`) настоящий только потому, что на POSIX
    `subprocess.run` после снятия зовёт `wait()` и каналы НЕ дочитывает —
    дочитывание есть лишь на Windows, а шаг идёт на ubuntu. Взгляд на #1246
    опасался обратного (`git-remote-https` держит каналы); этот прогон
    закрепляет поведение платформы, на котором держится предел, тем же
    вызовом, что у `shallow_clone`.
    """
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            ["sh", "-c", "sleep 30 & sleep 30"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=0.5,
        )
    assert time.monotonic() - started < 10


def test_offered_names_drop_the_file_prefix() -> None:
    """Имя файла шага приводится к имени отдаваемого, чужое без приставки — отброшено."""
    assert module.offered_names(("step-lint", "ci")) == ["lint"]


def test_a_namesake_without_our_call_is_not_taken(tmp_path: Path) -> None:
    """Одноимённый файл соседа без вызова по нашему адресу — не «взял» (#1199)."""
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    (folder / "step-lint.yml").write_text("jobs:\n  lint:\n    runs-on: x\n", encoding="utf-8")
    steps, refs = module.calls_in((folder / "step-lint.yml").read_text(encoding="utf-8"))
    assert steps == () and refs == ()


def test_main_writes_the_numbers_for_the_facts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--out` кладёт числа файлом — его читает сборка фактов, а не второй обход."""
    import json

    monkeypatch.setattr(module, "family", lambda **_: ["o/сосед"])
    monkeypatch.setattr(
        module,
        "took",
        lambda repo, _where, **_: module.Took(repo=repo, steps=("step-lint",), refs=("v1",)),
    )
    monkeypatch.setattr(module.onboard, "steps", lambda _root: ["lint", "facts"])
    out = tmp_path / "uptake.json"
    assert module.main(["--out", str(out)]) == module.EXIT_OK
    said = json.loads(out.read_text(encoding="utf-8"))
    assert said["projects"]["took"] == 1 and said["steps"] == {
        "taken": 1,
        "of": 2,
        "names": ["lint"],
    }


def test_no_offered_steps_is_a_refusal_not_a_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отдаваемых шагов не найдено — знаменателя нет, и это отказ, а не 0/0 (075)."""
    monkeypatch.setattr(module, "family", lambda **_: ["o/сосед"])
    monkeypatch.setattr(module.onboard, "steps", lambda _root: [])
    assert module.main([]) == module.EXIT_BROKEN


def test_a_local_summary_is_read_without_the_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Скачанная прогоном сводка читается с диска: разрез и обход считают по одному снимку."""
    import json

    def no_network(*_: object) -> None:
        raise AssertionError("локальная сводка ушла в сеть")

    monkeypatch.setattr(module.ghrest, "raw_json", no_network)
    path = tmp_path / "where.json"
    path.write_text(
        json.dumps({"consumers": [{"repo": module.OURS}, {"repo": "o/сосед"}]}), encoding="utf-8"
    )
    assert module.family(local=path) == ["o/сосед"]
    path.write_text("{не json", encoding="utf-8")
    with pytest.raises(module.NotRun):
        module.family(local=path)
