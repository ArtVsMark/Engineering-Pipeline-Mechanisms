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


def test_a_closed_acceptance_allows_the_major() -> None:
    """С закрытой приёмкой мажор проходит; с открытой — нет.

    Разбор проверяется данными, а не подделкой транспорта: состояние приходит
    в `refusals` готовым ответом.
    """

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
    lines = [line for line in str(found[0]["run"]).splitlines() if not line.lstrip().startswith("#")]
    return "\n".join(lines)


def test_the_tag_leaves_only_after_the_commit_landed() -> None:
    """Тег отправляется ПОСЛЕ ветки, отдельным толчком, а не вместе с ней.

    Замер 12.09.2026, прогон `release #3`: здесь стоял `git push origin HEAD
    --follow-tags` — один заход на два ref'а без порядка между ними. Площадка
    отвергла ветку (набор правил общей ветки требует `ci-complete`, а у
    коммита выпуска проверки нет) и приняла тег: `v1.0.0` повис на коммите,
    которого в общей ветке не было, а необратимое при этом уже случилось
    ([109](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/109-every-exit-from-a-transient-state-must-be-terminal.md)).
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
