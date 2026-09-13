"""Выпуск проверяется тем, что обязан ОТВЕРГНУТЬ, — до необратимого шага.

Тег не переставляется. Значит проверка живёт ПЕРЕД ним, а не разбирает
последствия после
([074](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/074-one-shot-irreversible-steps-get-their-own-guard.md)),
и проверяется здесь именно она: каждая причина не выпускать — отдельным
случаем, потому что выпуск делают редко и увидеть их надо сразу все.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
import yaml

from tests.conftest import FAKE_VERSION, ROOT, RunScript, load_script

module = load_script("release.py")


def tree(
    root: Path,
    version: str = FAKE_VERSION,
    *,
    fragments: tuple[str, ...] = ("a.added.md",),
    tag: str = "",
) -> Path:
    """Собирает дерево, готовое к выпуску: версия, ответ проекта, фрагменты, git.

    ОТВЕТ ПРОЕКТА ЗДЕСЬ НЕ УКРАШЕНИЕ: выпуск спрашивает объявленный диапазон
    совместимости, чтобы отказать ДО необратимого, если подъём версии контракта
    в него не поместится. Без файла заход честно говорит «диапазон спросить не
    у чего», и подделка без него проверяла бы не выпуск, а этот отказ.
    """
    (root / "CONTRACT_VERSION").write_text(f"{version}\n", encoding="utf-8")
    major, minor = version.split(".")[:2]
    (root / ".pipeline.yml").write_text(
        f'schema: 4\ncontract: ">={major}.{minor},<{major}.{int(minor) + 1}"\n'
        "checks:\n  lint: required\n",
        encoding="utf-8",
    )
    kits = root / "changelog.d"
    kits.mkdir(exist_ok=True)
    (kits / "README.md").write_text("правила фрагментов\n", encoding="utf-8")
    for name in fragments:
        (kits / name).write_text("текст\n\n#1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    # ПОДПИСЬ ЗАДАЁТСЯ В САМОЙ ПОДДЕЛКЕ, а не берётся у окружения. У исполнителя
    # площадки её нет вовсе, и `git commit`/`git tag -a` там падают — то есть
    # проверка зелена только на машине, где подпись настроена глобально. Замер
    # 10.09.2026: набор прошёл локально и покраснел на всех версиях сразу.
    subprocess.run(["git", "config", "user.email", "a@b"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "выпуск"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)
    # ЛИНИЮ ВЫПУСКОВ ЗАДАЁТ ТЕГ, а не версия контракта: числа развязаны
    # решением 017, и «какой номер ожидается следующим» считается от тега.
    if tag:
        subprocess.run(["git", "tag", "-a", tag, "-m", tag], cwd=root, check=True)
    return root


def test_a_release_always_raises_the_minor() -> None:
    """ВЫПУСК двигает минор на единицу — всегда, и обнуляет патч.

    Патч выпуском не бывает: это разряд ГОЛОВЫ, число принятых изменений после
    тега. `1.0.1` — версия дерева, а не выпуск. Замер по семье 12.09.2026:
    каталог `v1.0.0 → v1.1.0 → v1.2.0`, грейдер `v1.4.0 … v1.11.0`, токен
    `v0.1 → v0.2` — патч-тегов нет ни у кого
    (`docs/decisions/017-a-release-moves-the-minor-the-contract-moves-itself.md`).
    """
    assert module.next_after("9.9.0") == "9.10.0"
    assert module.next_after("9.9.73") == "9.10.0"
    assert module.next_after("1.0.0") == "1.1.0"


def test_the_contract_version_moves_only_with_the_surface() -> None:
    """Версия КОНТРАКТА поднимается только вместе с тронутой поверхностью.

    Довод решения 015 сохранён целиком: подъём её минора — требование
    перечитать ответы, и требовать его на каждом выпуске значило бы требовать
    зря. Поверхность не тронута — число не меняется ВОВСЕ, ни минором, ни
    патчем.
    """
    assert module.next_contract("3.1.0", touched=True) == "3.2.0"
    assert module.next_contract("3.1.0", touched=False) == "3.1.0"
    assert module.next_contract("1.4.7", touched=False) == "1.4.7"


def test_the_two_numbers_are_independent() -> None:
    """Тег и версия контракта расходятся ЗАКОННО — это и есть развязка.

    Выпуск с тронутой поверхностью двигает оба числа, но по своим правилам, а
    выпуск без неё двигает только тег. Проверяется именно расхождение: пока
    числа были одним, каждый тег требовал перечитать ответы.
    """
    tag, contract = "1.0.0", "3.1.0"
    assert module.next_after(tag) == "1.1.0"
    assert module.next_contract(contract, touched=False) == "3.1.0"
    assert module.next_after(tag) != module.next_contract(contract, touched=True)


def test_a_contract_fragment_leaves_the_major_alone() -> None:
    """Правка поверхности мажор НЕ поднимает — его поднимает приёмка.

    Прежняя редакция этого теста повторяла соседний слово в слово и не
    проверяла ничего своего; нашёл внешний взгляд на #229. Предмет здесь
    именно мажор: он обязан остаться на месте при ЛЮБОМ роде фрагмента
    (decisions/009, decisions/015).
    """
    for current in ("2.5.0", "9.9.73"):
        was = current.split(".")[0]
        assert module.next_after(current).split(".")[0] == was
        for touched in (True, False):
            assert module.next_contract(current, touched=touched).split(".")[0] == was


def test_a_contract_bump_outside_the_declared_span_is_refused(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Подъём версии контракта не помещается в объявленный диапазон — отказ ДО тега.

    Мы сами потребитель своего контракта: `.pipeline.yml` объявляет диапазон, и
    версия вне него роняет ОБЯЗАТЕЛЬНУЮ проверку `pipeline` на общей ветке.
    То есть выпуск покрасил бы ветку сразу после себя, и чинить пришлось бы
    уже после необратимого
    ([074](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/074-one-shot-irreversible-steps-get-their-own-guard.md)).
    Склейка «фрагмент поверхности → подъём → диапазон» тестом не держалась
    вовсе — нашёл внешний взгляд на #253.
    """
    tree(tmp_path, tag="v9.9.0", fragments=("a.contract.md",))
    run = run_script("release.py", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "не принимает" in run.text
    assert "перечитайте ответы" in run.text.lower()


def test_a_bump_inside_the_declared_span_passes(run_script: RunScript, tmp_path: Path) -> None:
    """Диапазон принимает подъём — выпуск не возражает.

    Здоровый вход обязан пройти: иначе отказ неотличим от «шаг всегда против»
    (097). Диапазон здесь держит ДВА минора — окно миграции, ровно как у нас
    самих на время перехода.
    """
    root = tree(tmp_path, tag="v9.9.0", fragments=("a.contract.md",))
    (root / ".pipeline.yml").write_text(
        'schema: 4\ncontract: ">=9.9,<9.11"\nchecks:\n  lint: required\n', encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "окно миграции"], cwd=root, check=True)
    run = run_script("release.py", cwd=root)
    assert run.code == 0, run.text
    assert "условия сошлись" in run.text


def test_a_breaking_surface_raises_the_contract_major(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Несовместимая правка поднимает МАЖОР версии контракта, и объявляют её ключом.

    Род фрагмента `contract` не различает расширение от поломки, а гейт связи
    смотрит дифф изменения, которого у выпуска уже нет. Пути к мажору не было
    вовсе: несовместимость ушла бы минором, то есть обещанием «можно не
    читать». Нашёл внешний взгляд на #253.
    """
    assert module.next_contract("9.9.0", touched=True, breaking=True) == "10.0.0"
    assert module.next_contract("9.9.0", touched=False, breaking=True) == "9.9.0"

    root = tree(tmp_path, tag="v9.9.0", fragments=("a.contract.md",))
    (root / ".pipeline.yml").write_text(
        'schema: 4\ncontract: ">=9.9,<11.0"\nchecks:\n  lint: required\n', encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "окно миграции"], cwd=root, check=True)
    run = run_script("release.py", "--breaking", "--apply", cwd=root)
    assert run.code == 0, run.text
    assert (root / "CONTRACT_VERSION").read_text(encoding="utf-8").strip() == "10.0.0"
    assert "несовместимо" in run.text.lower()


def test_the_major_needs_a_named_acceptance(run_script: RunScript, tmp_path: Path) -> None:
    """Мажор поднимает не выпуск, а ЗАКРЫТАЯ приёмка (decisions/009).

    Договор и механизм говорили разное: договор — «единицу выпускает закрытая
    приёмка эпика», механизм — «назовите первого потребителя». Расхождение
    нашёл внешний взгляд на #198, и оно было не косметическим: исполнял
    механизм СТАРОЕ правило, то есть договор не значил ничего (002).
    """
    tree(tmp_path)
    run = run_script("release.py", "--version", "10.0.0", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "приёмка" in run.text.lower()
    assert "--acceptance" in run.text


def test_a_named_but_unread_acceptance_is_still_a_refusal(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Названная, но НЕ прочитанная приёмка выпуск не пускает.

    Три состояния вместо двух: закрыта, открыта, не прочитана. Свести третье к
    первому значило бы завести обход ровно там, где стоит проверка перед
    необратимым (045, 074) — ключ стал бы подписью под тем, чего никто не
    видел.
    """
    tree(tmp_path)
    run = run_script(
        "release.py",
        "--version",
        "10.0.0",
        "--acceptance",
        "196",
        cwd=tmp_path,
        env={"GH_TOKEN": "", "GITHUB_TOKEN": ""},
    )
    assert run.code == 1, run.text
    assert "не прочитано" in run.text


def test_the_release_page_is_a_summary_not_a_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тело страницы — сводка и адреса источника, а не копия журнала.

    Замер 13.09.2026: раздел журнала за 1.0.0 — 336 178 символов при пределе
    площадки 125 000. Копия туда не влезет и не должна: источник остаётся в
    дереве
    ([125](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/125-a-generated-file-is-not-a-store.md)).
    """
    monkeypatch.setattr(
        module.build_changelog,
        "read_fragments",
        lambda where: [
            module.build_changelog.Fragment("added", "раз", "текст"),
            module.build_changelog.Fragment("fixed", "два", "текст"),
            module.build_changelog.Fragment("fixed", "три", "текст"),
        ],
    )
    monkeypatch.setattr(module, "contract_at", lambda tag: FAKE_VERSION)
    said = module.page_body("9.10.0", "o/r")
    assert "Записей в выпуске: **3**" in said
    assert "| Исправлено | 2 |" in said
    assert "blob/v9.10.0/CHANGELOG.md" in said, "нет адреса собранного журнала"
    assert "changelog.d/released/9.10.0" in said, "нет адреса записей выпуска"
    assert len(said) < module.PAGE_LIMIT


def test_an_existing_page_is_seen_before_it_is_made(monkeypatch: pytest.MonkeyPatch) -> None:
    """Наличие страницы спрашивается у площадки, а не выводится из тега.

    Тег и страница — разные сущности: 13.09.2026 тег `v1.0.0` стоял, а страницы
    не было, и позже она появилась рукой. Судить о второй по первому значит
    угадывать.
    """
    asked: list[str] = []

    def answer(method: str, path: str, token: str, body: object = None) -> dict[str, str]:
        asked.append(path)
        return {"tag_name": "v9.10.0"}

    monkeypatch.setattr(module.ghrest, "request", answer)
    assert module.page_exists("o/r", "9.10.0", "токен") is True
    assert asked == ["repos/o/r/releases/tags/v9.10.0"]


def test_a_page_that_is_not_there_reads_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Нет такой страницы» — это ответ площадки, а не сбой транспорта (097)."""

    def answer(method: str, path: str, token: str, body: object = None) -> dict[str, str]:
        raise module.ghrest.NotFound(path)

    monkeypatch.setattr(module.ghrest, "request", answer)
    assert module.page_exists("o/r", "9.10.0", "токен") is False


def test_a_tag_of_the_tree_is_seen_and_a_stranger_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`tag_exists` отвечает по ДЕРЕВУ: тег — свойство истории, а не площадки."""
    root = tree(tmp_path, tag="v9.9.0")
    monkeypatch.chdir(root)
    assert module.tag_exists("v9.9.0") is True
    assert module.tag_exists("v9.9.1") is False
    # ОБРАЗЕЦ — НЕ ТЕГ. `git tag --list` понимает шаблоны, и на `v9.9.*` он
    # ответил бы «есть»: догоняющая кнопка сочла бы страницу заведённой для
    # выпуска, которого нет. Нашёл внешний взгляд на #303.
    assert module.tag_exists("v9.9.*") is False
    assert module.tag_exists("v9.9.?") is False


def test_the_contract_version_is_read_out_of_the_tagged_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Версия читается из дерева тега — даже когда голова ушла вперёд."""
    root = tree(tmp_path, version=FAKE_VERSION, tag="v9.9.0")
    (root / "CONTRACT_VERSION").write_text("9.9.9\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "голова ушла вперёд"], cwd=root, check=True)
    monkeypatch.chdir(root)
    assert module.contract_at("v9.9.0") == FAKE_VERSION
    assert module.declared_version() == "9.9.9"


def test_a_page_is_not_asked_for_a_tag_that_is_not_there(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тега нет — площадку не зовут вовсе: она завела бы тег сама.

    На запрос о странице для несуществующего тега площадка не отказывает, а
    создаёт его на голове общей ветки. Опечатка в догоняющей кнопке поставила
    бы тег там, где его никто не ставил, а тег не переставляется (074).
    Нашёл внешний взгляд на #299.
    """
    asked: list[str] = []
    monkeypatch.setattr(module, "tag_exists", lambda tag: False)

    def visited(*_args: object, **_kwargs: object) -> dict[str, str]:
        asked.append("зашли")
        return {}

    monkeypatch.setattr(module.ghrest, "request", visited)
    with pytest.raises(module.NotRun, match="не переставляется"):
        module.ensure_page("o/r", "9.10.0", "токен")
    assert asked == [], "площадку позвали, не проверив тег"


def test_the_page_takes_the_contract_version_of_its_own_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Версия контракта читается с дерева ТЕГА, а не с головы.

    Голова к моменту создания страницы уже ушла вперёд — особенно у догоняющей
    кнопки. Число с головы называло бы выпуску чужую версию, и заметить это
    было бы нечем: оно правдоподобно. Нашёл внешний взгляд на #299.
    """
    asked: list[tuple[str, ...]] = []

    def remember(*args: str) -> str:
        asked.append(args)
        return "9.1.0\n"

    monkeypatch.setattr(module, "git", remember)
    monkeypatch.setattr(
        module.build_changelog,
        "read_fragments",
        lambda where: [module.build_changelog.Fragment("added", "раз", "текст")],
    )
    said = module.page_body("9.10.0", "o/r")
    assert "`9.1.0`" in said
    assert ("show", f"v9.10.0:{module.paths.VERSION}") in asked


def test_a_second_run_does_not_make_a_second_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """Страница у тега одна: второй заход её не задваивает (074)."""
    monkeypatch.setattr(module, "tag_exists", lambda tag: True)
    posted: list[str] = []

    def answer(method: str, path: str, token: str, body: object = None) -> dict[str, str]:
        if method == "POST":
            posted.append(path)
        return {"tag_name": "v9.10.0"}

    monkeypatch.setattr(module.ghrest, "request", answer)
    said = module.ensure_page("o/r", "9.10.0", "токен")
    assert "уже есть" in said
    assert posted == [], "завели вторую страницу поверх существующей"


def test_a_missing_page_is_created(monkeypatch: pytest.MonkeyPatch) -> None:
    """Страницы нет — механизм её заводит, а не оставляет человеку."""
    monkeypatch.setattr(module, "tag_exists", lambda tag: True)
    posted: list[tuple[str, object]] = []

    def answer(method: str, path: str, token: str, body: object = None) -> dict[str, str]:
        if method == "GET":
            raise module.ghrest.NotFound(path)
        posted.append((path, body))
        return {}

    monkeypatch.setattr(module.ghrest, "request", answer)
    monkeypatch.setattr(module, "page_body", lambda version, repo: "сводка")
    said = module.ensure_page("o/r", "9.10.0", "токен")
    assert "создана" in said
    assert posted and posted[0][0] == "repos/o/r/releases"
    assert posted[0][1] == {"tag_name": "v9.10.0", "name": "v9.10.0", "body": "сводка"}


def test_a_dry_run_makes_no_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пробный заход рассказывает, а не заводит: у необратимого своя кнопка."""
    monkeypatch.setattr(module, "tag_exists", lambda tag: True)
    posted: list[str] = []

    def answer(method: str, path: str, token: str, body: object = None) -> dict[str, str]:
        if method == "GET":
            raise module.ghrest.NotFound(path)
        posted.append(path)
        return {}

    monkeypatch.setattr(module.ghrest, "request", answer)
    monkeypatch.setattr(module, "page_body", lambda version, repo: "сводка")
    said = module.ensure_page("o/r", "9.10.0", "токен", dry_run=True)
    assert "пробный заход" in said and posted == []


def test_a_body_over_the_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тело сверх предела площадки — отказ, а не обрезка на середине фразы."""
    monkeypatch.setattr(module, "tag_exists", lambda tag: True)

    def answer(method: str, path: str, token: str, body: object = None) -> dict[str, str]:
        raise module.ghrest.NotFound(path)

    monkeypatch.setattr(module.ghrest, "request", answer)
    monkeypatch.setattr(module, "page_body", lambda version, repo: "я" * (module.PAGE_LIMIT + 1))
    with pytest.raises(module.NotRun, match="сводкой"):
        module.ensure_page("o/r", "9.10.0", "токен")


def test_the_release_commit_is_signed_by_the_mechanism(monkeypatch: pytest.MonkeyPatch) -> None:
    """Машинный коммит выпуска несёт объявленного соавтора-механизм.

    Гейт атрибуции требует строку соавтора у КАЖДОГО первопредка общей ветки.
    Коммит выпуска собирает механизм — не окно и не рука, — и без подписи
    каждый выпуск красит общую ветку: замер 13.09.2026 на первом же выпуске
    `1.0.0`. Подписать его окном значило бы записать в историю неправду, а
    переписать её нечем
    ([123](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/123-attribution-is-verified-on-the-final-history.md)).
    """
    said: list[tuple[str, ...]] = []

    def remember(*args: str) -> str:
        said.append(args)
        return ""

    monkeypatch.setattr(module, "git", remember)
    monkeypatch.setattr(module.build_changelog, "main", lambda argv: 0)
    # Переезд фрагментов и сборка журнала — не предмет этой проверки: здесь
    # спрашивается ПОДПИСЬ коммита, и своё дерево ради неё не собирается.
    monkeypatch.setattr(module.build_changelog, "do_release", lambda version: None)
    # Версия контракта не двигается: поверхность не тронута — значит файл
    # версии никто не пишет, и подделывать запись на диск не нужно.
    monkeypatch.setattr(module, "declared_version", lambda: "9.9.0")
    monkeypatch.setattr(module, "touches_contract", lambda waiting: [])
    monkeypatch.setattr(module, "fragments", lambda: [Path("a.added.md")])
    module.do_release("9.10.0", breaking=False)
    committed = [one for one in said if one[0] == "commit"]
    assert committed, "коммита выпуска не было — предмет не найден (075)"
    assert module.MECHANISM in committed[0][-1], (
        f"коммит выпуска без объявленного соавтора: {committed[0][-1]!r}"
    )


def test_the_mechanism_signature_is_declared() -> None:
    """Подпись механизма есть в согласованном списке — иначе гейт её отвергнет.

    Написание сверяется целиком: расхождение между тем, что ставит механизм, и
    тем, что объявлено, снаружи выглядит как отсутствие подписи.
    """
    listed = (ROOT / ".github/authors.txt").read_text(encoding="utf-8")
    assert module.MECHANISM in listed, (
        f"«{module.MECHANISM}» не объявлен в .github/authors.txt — гейт атрибуции "
        "отвергнет коммит выпуска"
    )


def test_a_closed_acceptance_allows_the_major(monkeypatch: pytest.MonkeyPatch) -> None:
    """С закрытой приёмкой мажор проходит; с открытой — нет.

    Разбор проверяется данными, а не подделкой транспорта: состояние приходит
    в `refusals` готовым ответом.
    """

    # ЛИНИЯ ВЫПУСКОВ ЗАДАЁТСЯ ЗДЕСЬ, А НЕ БЕРЁТСЯ У ПРОЕКТА. Отказ про мажор
    # появляется, только когда мажор действительно двигается, а это считается
    # от ЖИВОГО тега. Пока проект стоял на `v0.1.0`, проверка проходила сама
    # собой; выпуск `1.0.0` 13.09.2026 обнулил её предмет — и она покраснела
    # на исправном коде. Тест, зависящий от того, что происходит в проекте,
    # проверяет не механизм, а день
    # ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    monkeypatch.setattr(module.project_version, "release_tag", lambda: "v0.9.0")

    def said(state: str) -> list[str]:
        return [
            one for one in module.refusals("1.0.0", acceptance="196", state=state) if "мажор" in one
        ]

    assert said(module.ACCEPTANCE_CLOSED) == []
    assert "ОТКРЫТА" in "".join(said(module.ACCEPTANCE_OPEN))
    assert "не прочитано" in "".join(said(module.ACCEPTANCE_UNREAD))
    # Несуществующий номер чинится НОМЕРОМ, и причина обязана сказать об этом,
    # а не отправить искать токен (154). Нашёл внешний взгляд на #204.
    missing = "".join(said(module.ACCEPTANCE_MISSING))
    assert "НЕТ" in missing and "номером" in missing
    # Форма входа — пятое состояние: «#196» не число, и причина обязана сказать
    # именно это, а не «нет токена» (154). Нашёл внешний взгляд на #204.
    shape = "".join(said(module.ACCEPTANCE_NOT_A_NUMBER))
    assert "не разобрано как номер" in shape


def test_the_acceptance_state_separates_the_two_unknowns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """«Такой задачи нет» и «не прочитано» — разные состояния и разная починка.

    Первое чинится номером, второе токеном. Сведение их в одно отправляло бы
    человека искать секрет там, где неверна цифра. Здесь проверяется и путь
    отказа транспорта, которого прежде не касался ни один тест (#204).
    """

    def answer(exc: Exception | None, state: str | None = None) -> Callable[..., dict[str, str]]:
        def _ask(*_: object, **__: object) -> dict[str, str]:
            if exc is not None:
                raise exc
            return {"state": state} if state else {}

        return _ask

    monkeypatch.setattr(module.ghrest, "request", answer(module.ghrest.NotFound("404")))
    assert module.acceptance_state("o/r", 999, "t") == module.ACCEPTANCE_MISSING

    monkeypatch.setattr(module.ghrest, "request", answer(module.ghrest.TransportError("молчит")))
    assert module.acceptance_state("o/r", 196, "t") == module.ACCEPTANCE_UNREAD

    monkeypatch.setattr(module.ghrest, "request", answer(None, "closed"))
    assert module.acceptance_state("o/r", 196, "t") == module.ACCEPTANCE_CLOSED

    monkeypatch.setattr(module.ghrest, "request", answer(None, "open"))
    assert module.acceptance_state("o/r", 196, "t") == module.ACCEPTANCE_OPEN

    monkeypatch.setattr(module.ghrest, "request", answer(None))
    assert module.acceptance_state("o/r", 196, "t") == module.ACCEPTANCE_UNREAD
    assert module.acceptance_state("", 196, "t") == module.ACCEPTANCE_UNREAD
    assert module.acceptance_state("o/r", 196, "") == module.ACCEPTANCE_UNREAD


def test_a_wrong_minor_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Номер, не следующий за линией выпусков, отвергается с названным ожиданием.

    Линия считается от ТЕГА: выпуск двигает минор на единицу, и `v9.9.0` ждёт
    `9.10.0`, а не что-нибудь дальше.
    """
    tree(tmp_path, tag="v9.9.0")
    run = run_script("release.py", "--version", "9.40.0", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "ожидается 9.10.0" in run.text


def test_the_first_release_starts_the_line(run_script: RunScript, tmp_path: Path) -> None:
    """Тегов нет вовсе — линия начинается с нуля, и ожидается первый минор.

    «Тега нет» и «тег есть» — разные состояния, и второе не подставляется
    вместо первого молча (045).
    """
    tree(tmp_path)
    # Мажор назван ТОТ ЖЕ, что в линии: иначе первым отказом придёт приёмка —
    # мажор поднимает она, и до разряда дело не дойдёт.
    run = run_script("release.py", "--version", "0.9.0", cwd=tmp_path)
    assert run.code == 1, run.text
    # Ожидаемое число СЧИТАЕТСЯ тем же механизмом, а не вписывается: вписанное
    # совпало бы с живой версией проекта, и гейт «версия не правится руками»
    # нашёл бы его в наборе (035).
    assert f"ожидается {module.next_after('0.0.0')}" in run.text


def test_an_empty_release_is_an_input_error(run_script: RunScript, tmp_path: Path) -> None:
    """Выпуск без единого фрагмента — ошибка входа, а не пустой выпуск (075)."""
    tree(tmp_path, fragments=())
    run = run_script("release.py", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "ни одного фрагмента" in run.text


def test_a_dirty_tree_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Выпуск с грязного дерева отвергается: тег указал бы не на то, что выпущено."""
    tree(tmp_path)
    (tmp_path / "лишнее.txt").write_text("не в коммите\n", encoding="utf-8")
    run = run_script("release.py", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "дерево грязно" in run.text


def test_an_existing_tag_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Тег уже стоит — выпуск отвергается: тег не переставляется (074).

    Это главный необратимый шаг: переставленный тег меняет то, на что уже
    прибит потребитель, и заметить это он не обязан.
    """
    # Тег стоит РОВНО на ожидаемом номере: линия `v9.8.0` ждёт `9.9.0`, и он же
    # уже помечен. Иначе отказ пришёл бы за номер, а не за переставляемый тег.
    tree(tmp_path, tag="v9.8.0")
    subprocess.run(["git", "tag", "-a", "v9.9.0", "-m", "v9.9.0"], cwd=tmp_path, check=True)
    run = run_script("release.py", "--version", "9.9.0", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "не переставляется" in run.text


def test_a_bad_version_is_refused(run_script: RunScript, tmp_path: Path) -> None:
    """Номер не той формы отвергается до всего остального."""
    tree(tmp_path)
    run = run_script("release.py", "--version", "9.9", cwd=tmp_path)
    assert run.code == 1, run.text


def test_nothing_irreversible_happens_without_apply(run_script: RunScript, tmp_path: Path) -> None:
    """Без ключа `--apply` не делается ничего необратимого.

    Половина смысла разделения: человек читает, из чего собран выпуск, и только
    потом решает. Заход, делающий это одним движением, читать было бы поздно.
    """
    tree(tmp_path)
    run = run_script("release.py", cwd=tmp_path)
    assert run.code == 0, run.text
    assert "--apply" in run.text
    assert not (tmp_path / "changelog.d" / "released").exists()
    assert (
        subprocess.run(
            ["git", "tag", "--list"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout.strip()
        == ""
    )


def test_the_release_moves_fragments_and_tags(run_script: RunScript, tmp_path: Path) -> None:
    """Настоящий выпуск: фрагменты переезжают, версия поднята, тег стоит.

    Фрагменты именно ПЕРЕЕЗЖАЮТ, а не удаляются: собранный журнал производный,
    и источником остаются они ([125](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/125-a-generated-file-is-not-a-store.md)).
    """
    tree(tmp_path, tag="v9.9.0")
    run = run_script("release.py", "--apply", cwd=tmp_path)
    assert run.code == 0, run.text
    assert (tmp_path / "changelog.d" / "released" / "9.10.0" / "a.added.md").is_file()
    assert not (tmp_path / "changelog.d" / "a.added.md").exists()
    # ВЕРСИЯ КОНТРАКТА НЕ ТРОНУТА: фрагмент здесь рода `added`, поверхность
    # цела, и требовать от потребителя перечитывания было бы ложным обещанием.
    assert (tmp_path / "CONTRACT_VERSION").read_text(encoding="utf-8").strip() == FAKE_VERSION
    tags = subprocess.run(
        ["git", "tag", "--list"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.split()
    assert tags == ["v9.10.0", "v9.9.0"]


def test_the_procedure_matches_the_contract() -> None:
    """Порядок выпуска в механизме тот же, что записан в договоре (029).

    Договор описывает порядок с самого начала; механизм обязан ему отвечать, а
    не заводить свой.
    """
    text = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    assert "## Порядок выпуска" in text
    assert "тег не переставляется" in text.lower()


def test_a_hash_prefixed_acceptance_names_the_input_not_the_token(
    run_script: RunScript, tmp_path: Path
) -> None:
    """«#196» отвергается по ФОРМЕ, а не как «состояние не прочитано».

    Прежде нечисловой вход молча становился «нет токена или площадка молчит» —
    и человек шёл искать секрет там, где лишняя решётка (154). Нашёл внешний
    взгляд на #204.
    """
    tree(tmp_path)
    run = run_script("release.py", "--version", "10.0.0", "--acceptance", "#196", cwd=tmp_path)
    assert run.code == 1, run.text
    assert "не разобрано как номер" in run.text
    assert "нет токена" not in run.text


def test_the_contract_names_every_state_the_mechanism_tells_apart() -> None:
    """Договор о выпуске называет ВСЕ состояния приёмки, что различает механизм.

    Расхождение договора и механизма здесь уже было и стоило дороже прочего:
    новое правило мажора жило в `docs/release.md`, пока `release.py` исполнял
    старое (#198). Пять состояний — пять строк таблицы, и сверяет их машина, а
    не внимание автора
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    """
    contract = (ROOT / "docs" / "release.md").read_text(encoding="utf-8").lower()
    missing = [said for said in module.ACCEPTANCE_SAID.values() if said.lower() not in contract]
    assert not missing, f"механизм различает, а договор не называет: {missing}"


def test_a_needless_breaking_flag_is_said_not_labelled(
    run_script: RunScript, tmp_path: Path
) -> None:
    """`--breaking` без фрагментов поверхности НЕ метит заход несовместимым.

    Сам дефект воспроизводился только заходом CLI: `next_contract` отдавала
    верное число, а печатала пометку `announce`. Юнит-теста числа для этого
    мало — гоняется именно то, что читает человек перед необратимым
    ([140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
    Нашёл внешний взгляд на #256.
    """
    tree(tmp_path, tag="v9.9.0", fragments=("a.added.md",))
    run = run_script("release.py", "--breaking", cwd=tmp_path)
    assert run.code == 0, run.text
    assert "не меняется" in run.text, run.text
    assert "двигать нечего" in run.text, run.text
    assert "несовместимо" not in run.text.lower(), "пометка поставлена там, где нечего двигать"


def test_a_breaking_flag_with_a_touched_surface_is_labelled(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Обратная сторона: поверхность тронута — пометка на месте.

    Без этого случая «пометка следует числу» держалось бы одним отказом, и
    пропажа пометки вовсе выглядела бы как починка (097).
    """
    root = tree(tmp_path, tag="v9.9.0", fragments=("a.contract.md",))
    (root / ".pipeline.yml").write_text(
        'schema: 4\ncontract: ">=9.9,<11.0"\nchecks:\n  lint: required\n', encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "окно миграции"], cwd=root, check=True)
    run = run_script("release.py", "--breaking", cwd=root)
    assert run.code == 0, run.text
    assert "несовместимо" in run.text.lower(), run.text
    assert "10.0.0" in run.text, run.text


def release_step() -> str:
    """ИСПОЛНЯЕМЫЙ текст необратимого шага выпуска: комментарии сняты.

    Сняты не для красоты: разбор, объясняющий старую ошибку, называет её же
    дословно, и гейт, читающий весь текст шага, видел бы `--follow-tags` в
    собственном объяснении и краснел на починенном механизме.
    """
    document = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8"))
    steps = document["jobs"]["release"]["steps"]
    found = [step for step in steps if step.get("name") == "выпустить"]
    if len(found) != 1:
        raise AssertionError(f"шаг «выпустить» найден {len(found)} раз — читать нечего (075)")
    said = str(found[0]["run"]).splitlines()
    return "\n".join(line for line in said if not line.lstrip().startswith("#"))


def test_the_tag_leaves_only_after_the_commit_landed() -> None:
    """Тег отправляется ПОСЛЕ ветки, отдельным толчком, а не вместе с ней.

    Один заход на два ref'а не даёт порядка между ними: площадка вправе
    принять тег и отвергнуть ветку, и метка остаётся на коммите, до общей
    ветки не доехавшем — необратимое случилось, а выход оказался
    нетерминальным
    ([109](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/109-every-exit-from-a-transient-state-must-be-terminal.md)).
    Чем это обошлось — в журнале, фрагмент
    `a-tag-follows-the-commit-that-landed`.
    """
    text = release_step()
    assert "--follow-tags" not in text, "тег снова уезжает вместе с веткой, без порядка"
    branch = text.find("git push origin HEAD")
    assert branch != -1, "ветка не отправляется вовсе"
    tag = text.find('git push origin "${tag}"')
    assert tag != -1, "тег не отправляется отдельным толчком"
    assert branch < tag, "тег отправляется раньше ветки — метить будет нечего"


def test_a_rejected_branch_is_named_not_swallowed() -> None:
    """Отказ общей ветки называется причиной, а не голым кодом возврата.

    Отказ был бы виден как «упал шаг», и искать стали бы в механизме выпуска,
    а искать надо в наборе правил общей ветки
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    text = release_step()
    assert "if ! git push origin HEAD; then" in text, "отказ ветки ничем не перехвачен"
    said = text[text.find("if ! git push origin HEAD; then") :]
    assert "::error::" in said, "отказ ветки не назван"
    assert "обход" in said.lower(), "причина отказа не названа: обход набора правил"


def test_a_rejected_tag_is_named_too_and_names_its_own_repair() -> None:
    """Отказ ВТОРОГО толчка называется тоже, и починка у него своя.

    Состояния разные: после отказа ветки не сделано ничего, после отказа тега
    коммит выпуска уже в общей ветке, а метки на нём нет. Свести их к одному
    «упало» значит отправить человека чинить не то
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    Нашёл внешний взгляд на #259: здесь толчок тега падал голым кодом возврата.
    """
    text = release_step()
    start = text.find('if ! git push origin "${tag}"; then')
    assert start != -1, "отказ тега ничем не перехвачен"
    said = text[start:]
    assert "::error::" in said, "отказ тега не назван"
    assert "git push origin ${tag}" in said, "починка отказа тега не названа"
    assert "не повторять" in said.lower(), "повтор выпуска после этого отказа не запрещён"


def test_a_branch_that_will_refuse_the_push_is_named_before_the_build(
    run_script: RunScript, tmp_path: Path
) -> None:
    """Право толкнуть спрашивается ДО сборки журнала, а не после неё.

    12.09.2026 выпуск `1.0.0` собрал журнал, поставил тег и упёрся в набор
    правил общей ветки: у машинного коммита выпуска нет проверки изменения.
    Порядок толчков починен тогда же, но узнавалось это по-прежнему после
    сборки. Шаг, который нельзя отменить, получает проверку ПЕРЕД собой
    ([074](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/074-one-shot-irreversible-steps-get-their-own-guard.md)).
    """
    tree(tmp_path, tag="v9.9.0")
    said = module.refusals("9.10.0", acceptance="", push="never")
    assert any("не примет коммит выпуска" in one for one in said), said
    assert any("Bypass" in one for one in said), "починка не названа"


@pytest.mark.parametrize("answer", ["never", "pull_requests_only"], ids=["никогда", "только PR"])
def test_both_refusing_answers_stop_the_release(answer: str, tmp_path: Path) -> None:
    """Прямому толчку помогает только «always».

    «pull_requests_only» разрешает обойти проверки через изменение, а выпуск
    толкает коммит напрямую: считать это разрешением значило бы пропустить
    выпуск, который наверняка не доедет (097).
    """
    tree(tmp_path, tag="v9.9.0")
    assert any(
        "право обхода" in one for one in module.refusals("9.10.0", acceptance="", push=answer)
    )


def test_an_unread_answer_does_not_block_the_release(tmp_path: Path) -> None:
    """Непрочитанный ответ площадки выпуск НЕ держит: запрета из незнания нет.

    Отказ только на определённом, предупреждение на вероятном
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)):
    порядок толчков и так не даст уехать тегу без ветки.
    """
    tree(tmp_path, tag="v9.9.0")
    said = module.refusals("9.10.0", acceptance="", push=module.MAY_PUSH)
    assert not any("обход" in one for one in said), said


def test_an_unread_answer_is_said_out_loud(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """…но молчанием оно не становится: непроверенное называется (154).

    И называет ОБЕ причины: площадка молчит либо токена владельца нет. Одна
    названная причина из двух отправляет искать поломку не там.
    """
    tree(tmp_path, tag="v9.9.0")
    module.announce("9.10.0", acceptance="", push="")
    said = capsys.readouterr().out
    assert "не проверено" in said
    assert module.PUSH_TOKEN_ENV in said, "не сказано, чей токен спрашивается"


def test_the_right_is_asked_of_the_token_that_pushes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Спрашивается токен ВЛАДЕЛЬЦА — тот, которым выпуск потом толкает.

    13.09.2026 проверка шла токеном прогона, а толкать собирался токен
    владельца. Площадка отвечала про спросившего — «обход: никогда» — и
    отвечала верно: обход прогону не положен, этого требует наше же
    объявление защиты. Выпуск отказывал ВСЕГДА, а владелец тем временем выдал
    обход своей роли и видел, что ничего не изменилось (044).
    """
    monkeypatch.setenv(module.PUSH_TOKEN_ENV, "владельца")
    monkeypatch.setenv("GH_TOKEN", "прогона")
    assert module.push_token() == "владельца"


def test_without_the_owners_token_the_question_is_not_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Токена владельца нет — вопрос не задаётся, и это не «толкать нельзя».

    Ответ про чужого актора хуже отсутствия ответа: он выглядит знанием.
    Выпуск без токена владельца и так остановит отдельный шаг, назвав причину.
    """
    monkeypatch.delenv(module.PUSH_TOKEN_ENV, raising=False)
    monkeypatch.setenv("GH_TOKEN", "прогона")
    assert module.push_token() == ""


#: Шаги прогона выпуска, которые зовут механизм. Спрашивается КАЖДЫЙ: проверка
#: получила токен владельца сразу, а необратимый шаг остался без него — и
#: вопрос о праве в нём не задавался вовсе. Нашёл внешний взгляд на #296.
CALLS_THE_MECHANISM: Final = ("проверить условия выпуска", "выпустить")


@pytest.mark.parametrize("step", CALLS_THE_MECHANISM)
def test_every_release_step_gets_the_owner_token(step: str) -> None:
    """Оба шага выпуска получают тот токен, которым идёт толчок.

    Механизм спрашивает правильного актора только если этот токен до него
    доехал: правка кода без правки прогона осталась бы обещанием
    ([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).
    Проверка по СПИСКУ, а не по одному шагу: один читатель был исправлен, а
    второй молчал — ровно то расхождение, которое список и закрывает.
    """
    run = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    steps = run["jobs"]["release"]["steps"]
    found = [one for one in steps if one.get("name") == step]
    assert found, f"шаг «{step}» не найден — предмет исчез (075)"
    assert module.PUSH_TOKEN_ENV in (found[0].get("env") or {}), (
        f"шаг «{step}» не получает токен владельца: он спросит площадку о токене "
        "прогона, а тот обхода не имеет и иметь не должен"
    )


def test_a_branch_without_rules_is_read_as_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Правил на ветке нет вовсе — толкать никто не мешает.

    Это не поблажка из незнания: пустой ответ площадки о правилах и есть
    ответ, в отличие от непрочитанного (097).
    """
    monkeypatch.setattr(module.ghrest, "request", lambda *a, **k: [])
    assert module.may_push("o/r", "main", "t") == module.MAY_PUSH


def test_an_unreachable_platform_reads_as_unasked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка не ответила — пусто, а не «обход есть» (045)."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise module.ghrest.TransportError("площадка не ответила")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    assert module.may_push("o/r", "main", "t") == ""
