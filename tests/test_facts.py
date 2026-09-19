"""Факты о проекте и их публикация проверяются отказом, а не осмотром.

Предмет двойной: числа обязаны приходить из источников (иначе значок врёт
уверенно), а производное обязано оставаться вне общей ветки (иначе оно там
протухает молча). Проверяется и то, и другое.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from tests.conftest import FAKE_VERSION, ROOT, RunScript, badges_shown, found_by, load_script

facts = load_script("build_facts.py")

WORKFLOW = ROOT / ".github" / "workflows" / "badges.yml"
CHECKS = 'schema: 4\ncontract: ">=9.9,<9.10"\nchecks:\n  lint: required\n'


def bindings(**rules: dict[str, Any]) -> str:
    """Ответ каталогу в том виде, в каком его читает механизм."""
    return json.dumps({"schema": "1.0", "rules": rules}, ensure_ascii=False)


def tree(root: Path, answer: str) -> Path:
    """Собирает дерево-источник: версия, ответ каталогу, ответ по проверкам."""
    (root / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    (root / ".rules").mkdir(exist_ok=True)
    (root / ".rules" / "bindings.json").write_text(answer, encoding="utf-8")
    (root / ".pipeline.yml").write_text(CHECKS, encoding="utf-8")
    return root


def test_numbers_come_from_the_sources(tmp_path: Path) -> None:
    """Каждое число собрано из источника, а не вписано в механизм."""
    tree(
        tmp_path,
        bindings(
            **{
                "001": {"status": "active", "mechanism": "gate", "where": "тут"},
                "002": {"status": "active", "mechanism": "document", "where": "там"},
                "003": {"status": "unreviewed"},
                "004": {"status": "rejected", "why": "не наш предмет"},
            }
        ),
    )
    collected = facts.collect(tmp_path, "голова")
    assert collected["contract"] == FAKE_VERSION
    assert collected["rules"]["total"] == 4
    assert collected["rules"]["answered"] == 3
    assert collected["rules"]["by_mechanism"] == {"document": 1, "gate": 1}
    assert collected["checks"]["required"] == 1
    assert collected["generated"]["sha"] == "голова"


def test_unknown_status_is_refused(tmp_path: Path) -> None:
    """Статус вне схемы — дефект ответа, а не новая тонкость (068)."""
    tree(tmp_path, bindings(**{"001": {"status": "почти"}}))
    with pytest.raises(facts.NotRun, match="статус"):
        facts.collect(tmp_path, "")


def test_active_without_a_mechanism_is_refused(tmp_path: Path) -> None:
    """«Действует» без названного механизма — обещание, а не ответ (002)."""
    tree(tmp_path, bindings(**{"001": {"status": "active"}}))
    with pytest.raises(facts.NotRun, match="чем — не сказано"):
        facts.collect(tmp_path, "")


def test_empty_answer_is_an_input_error(tmp_path: Path) -> None:
    """Пустой ответ каталогу — ошибка входа, а не «правил нет» (075)."""
    tree(tmp_path, bindings())
    with pytest.raises(facts.NotRun):
        facts.collect(tmp_path, "")


def test_missing_version_is_an_input_error(tmp_path: Path) -> None:
    """Без версии контракта факты не собираются: публиковать нечего.

    Отказ приходит из счёта версии, а не из сборки: та спрашивает версию у
    НАЗВАННОГО дерева. Пока корень не передавался, версия читалась из текущего
    рабочего каталога — то есть из настоящего дерева проекта, — и подделанное
    дерево без файла версии всё равно получало число. Нашёл внешний взгляд
    на #106.
    """
    tree(tmp_path, bindings(**{"001": {"status": "unreviewed"}}))
    (tmp_path / "CONTRACT_VERSION").unlink()
    with pytest.raises((facts.NotRun, facts.version.NotRun)):
        facts.collect(tmp_path, "")


def test_badge_shows_the_number_it_measured() -> None:
    """Значок несёт то же число, что и факты: второго источника у него нет.

    Считаются держащиеся МАШИНОЙ, а не отвеченные: `answered` равен `total` по
    построению — проект отвечает по каждому правилу каталога (129), — и такой
    значок не сдвинулся бы никогда.
    """
    drawn = facts.rules_badge(
        {"rules": {"by_mechanism": {"gate": 60, "pipeline": 6, "document": 129}}}
    )
    assert "66/195" in drawn
    assert "держится машиной" in drawn


def test_badge_colour_follows_the_share() -> None:
    """Цвет говорит о доле, а не о настроении: три доли — три цвета."""
    low = facts.rules_badge({"rules": {"by_mechanism": {"gate": 10, "document": 90}}})
    mid = facts.rules_badge({"rules": {"by_mechanism": {"gate": 50, "document": 50}}})
    high = facts.rules_badge({"rules": {"by_mechanism": {"gate": 90, "document": 10}}})
    assert len({low.split('fill="')[2], mid.split('fill="')[2], high.split('fill="')[2]}) == 3


#: Разрезы витрины, публикующие ДОЛЮ, и два числа, из которых она сделана.
#: Список разрешительный (068): доля, которой здесь нет, гейтом отвергается —
#: она обязана приехать со своими слагаемыми либо быть объявлена тут с ними.
A_SHARE_AND_ITS_NUMBERS: dict[str, tuple[str, str]] = {
    "coverage.percent": ("coverage.covered", "coverage.lines"),
    "family.share": ("family.closed_by_shared", "family.held_by_machine"),
}


def flat(said: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Витрина в один уровень: «разрез.ключ» → значение."""
    found: dict[str, Any] = {}
    for key, value in said.items():
        where = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            found |= flat(value, where)
        else:
            found[where] = value
    return found


def test_every_published_share_stands_beside_its_two_numbers(tmp_path: Path) -> None:
    """Доля публикуется вместе с числами, из которых сделана (041).

    «77 %» отвечает на «много ли» и не отвечает на «много ЧЕГО»: та же доля у
    дерева в сто строк и в десять тысяч значит разное, а падение с 77 до 70
    бывает и новым кодом без проверок, и удалением покрытого. Читатель одной
    доли этого не различит и различить не может.

    ЗАМЕР 18.09.2026: долей в витрине две, слагаемые были у ОДНОЙ. У семьи доля
    ехала рядом с `closed_by_shared` из `held_by_machine`, у покрытия — одна.
    То есть ответ проекта «витрина публикует несколько честных чисел и ни одного
    усреднённого» о покрытии был неверен, и опровергался одной командой
    ([175](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/175-an-absence-claim-that-a-command-can-refute-must-be-a-gate.md)).

    ЧИСЛА БЕРУТСЯ ИЗ СОБРАННОЙ ВИТРИНЫ, А НЕ ИЗ СПИСКА: новая доля, добавленная
    мимо объявления, краснеет здесь, а не расходится с ним молча.
    """
    collected = facts.collect(
        tree(
            tmp_path,
            bindings(**{"001": {"status": "active", "mechanism": "gate", "where": "x.py"}}),
        ),
        "голова",
    )
    numbers = flat(collected)
    bare = [
        f"{where} = {value}"
        for where, value in numbers.items()
        if isinstance(value, float) and where not in A_SHARE_AND_ITS_NUMBERS
    ]
    assert not bare, (
        "доля опубликована без чисел, из которых сделана (041):\n  "
        + "\n  ".join(bare)
        + "\n  Публикуйте рядом числитель и знаменатель и объявите пару в"
        " A_SHARE_AND_ITS_NUMBERS: читатель одной доли не отличит рост от усадки."
    )


def test_the_declared_pairs_are_not_a_promise(tmp_path: Path) -> None:
    """Объявленная пара действительно публикуется, а не обещана списком.

    Список, о котором сказано «доля едет со слагаемыми», обязан быть тем, что
    витрина собирает. Иначе это обещание в прозе, и снаружи полная пара и
    отсутствующая выглядят одинаково
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

    Разрез, который в этом прогоне НЕ прочитан, из предмета выпадает и назван:
    сводка семьи приходит из чужого дерева, и требовать её здесь значило бы
    требовать сети от набора (084).
    """
    root = tree(
        tmp_path, bindings(**{"001": {"status": "active", "mechanism": "gate", "where": "x.py"}})
    )
    report = tmp_path / "coverage.json"
    # Отчёт счётчика в той форме, в какой его отдаёт `coverage json`. Поля взяты
    # у настоящего отчёта, а не по памяти: имена проверены прогоном 18.09.2026.
    report.write_text(
        json.dumps(
            {"totals": {"percent_covered": 77.0, "covered_lines": 226, "num_statements": 293}}
        ),
        encoding="utf-8",
    )
    collected = facts.collect(root, "голова", coverage=report)
    numbers = flat(collected)
    checked = 0
    for share, pair in A_SHARE_AND_ITS_NUMBERS.items():
        if share not in numbers:
            continue
        section = share.split(".")[0]
        if not (collected.get(section) or {}).get("read"):
            continue
        checked += 1
        for one in pair:
            assert one in numbers, f"{share} объявлена с {one}, а витрина его не публикует"
    assert checked, (
        "ни один разрез с долей не прочитан — проверка зеленеет вокруг пустоты (075)."
        " Подайте разрез, который читается: отчёт покрытия собирается прямо здесь"
    )


def derived_names() -> list[str]:
    """Имена производного — ВСЕ, какие объявляет сборка, а не список руками.

    Список руками отстаёт молча: значков стало четыре, а гейт проверял два —
    `family.svg` и `version.svg` появились вместе с витриной и в проверку не
    попали (049). Имена читаются из модуля: добавится пятое — попадёт само.
    Нашёл внешний взгляд на #134.

    ЧИТАЕТСЯ ИНВЕНТАРЬ, А НЕ ПРОСТРАНСТВО ИМЁН МОДУЛЯ. Прежняя редакция
    соскребала строковые константы через `vars()` по хвосту имени файла —
    приём работал ровно до тех пор, пока у значков не появился один список: он
    видит имена, объявленные КОНСТАНТОЙ, и слеп к тем же именам, объявленным
    данными. Признак взят тот, которым пользуется сама сборка.
    """
    found = sorted({*facts.BADGES, facts.FACTS})
    assert len(found) >= 5, f"имён производного разобрано {found} — предмет не найден (075)"
    return found


def test_derived_output_is_not_in_the_shared_branch() -> None:
    """Производного нет в дереве: оно живёт в ветке `badges` (125).

    Гейт написан на ИМЕНА вывода, а не на его содержимое: файл, случайно
    закоммиченный рядом с источником, выглядит безобидно ровно до того дня,
    когда число в нём разойдётся с источником.
    """
    for name in derived_names():
        assert not found_by(ROOT, f"**/{name}"), f"{name} лежит в общей ветке рядом с источником"


def shown_badges() -> list[str]:
    """Значки, на которые ссылается витрина: второй источник тех же имён.

    Витрина — ИСТОЧНИК, НЕЗАВИСИМЫЙ от сборки: её пишет человек, а имена берёт
    у площадки. Сверять список гейта с тем же модулем, из которого он собран,
    значит проверять равенство самому себе — ровно это и делала редакция,
    найденная внешним взглядом на #183.

    Сам образец адреса живёт в `tests/conftest.py`: спрашивающих трое, и
    экземпляр здесь был третьим (022).
    """
    found = sorted(badges_shown((ROOT / "README.md").read_text("utf-8")))
    assert len(found) >= 4, f"витрина показывает {found} — предмет проверки не найден (075)"
    return found


def test_every_badge_the_showcase_shows_is_covered_by_the_gate() -> None:
    """Гейт видит все значки витрины, а не те, что помнил автор (находка #183).

    ДВА ИСТОЧНИКА, А НЕ ОДИН. Прежняя редакция брала имена из того же модуля,
    из которого их берёт и сам гейт, — и проверяла равенство самому себе.
    `release.svg` в ней не был назван вовсе, а он выпал бы из проверки вместе
    со всеми, потому что и список, и сверка читали один список.
    """
    said = derived_names()
    missing = [name for name in shown_badges() if name not in said]
    assert not missing, f"витрина показывает {missing}, а гейт производного их не видит"


def test_every_badge_the_build_draws_is_shown() -> None:
    """Обратная сторона: нарисованное сборкой доезжает до витрины.

    Значок, который рисуется и никому не показан, — это работа прогона в
    никуда; значок, который показан и не рисуется, — сломанная картинка (196).
    Оба конца сверяются здесь, потому что источники у них разные.

    СПИСОК НАРИСОВАННОГО СПРАШИВАЕТСЯ У СБОРКИ, А НЕ ПОМНИТСЯ. Прежняя
    редакция держала здесь множество из ЧЕТЫРЁХ имён, выписанных рукой, при
    шести рисуемых: `scripts.svg` и `coverage.svg` в него не попали, и
    проверка два месяца сверяла память автора с README — зелёная при том, что
    два значка рисовались каждым прогоном и не были показаны нигде. Обещание
    докстринга «нарисованное сборкой» при этом стояло на месте, то есть гейт
    утверждал о себе неправду
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
    """
    drawn = set(facts.BADGES)
    assert len(drawn) >= 5, f"сборка рисует {sorted(drawn)} — предмет проверки не найден (075)"
    assert drawn == set(shown_badges()), (
        f"сборка рисует {sorted(drawn)}, витрина показывает {shown_badges()}"
    )


def push_command(step: str) -> str:
    """Склеивает команду толчка вместе с её переносами строк."""
    joined = step.replace("\\\n", " ")
    commands = [line for line in joined.splitlines() if "git push" in line]
    assert commands, "шаг публикации ничего не толкает — предмет проверки не найден (075)"
    return commands[0]


def test_publication_writes_only_to_the_derived_branch() -> None:
    """Прогон толкает в `badges`, и никуда больше.

    Право на запись у этого прогона единственное во всём конвейере, поэтому
    проверяется не намерение, а сама команда: имя общей ветки в ней означало бы
    механизм, способный переписать источник своим же выводом.
    """
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    command = push_command(document["jobs"]["badges"]["steps"][-1]["run"])
    assert command.rstrip().endswith("badges"), f"толчок идёт не в производную ветку: {command}"
    assert "main" not in command, "шаг публикации называет общую ветку"


def test_publication_is_not_a_check_on_a_change() -> None:
    """Публикация не идёт на изменении: она не проверка и вердикта не выносит."""
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "pull_request" not in document[True]


def test_build_refuses_to_write_next_to_the_sources(run_script: RunScript) -> None:
    """Каталог вывода обязателен: умолчания «рядом с источником» нет."""
    run = run_script("build_facts.py")
    assert run.code != 0, run.text
    assert "--out-dir" in run.text


def test_the_facts_carry_the_computed_version() -> None:
    """Факты несут ПОСЧИТАННУЮ версию рядом с объявленным контрактом.

    Числа разные и оба нужны: контракт объявляет поверхность механизмов и
    поднимается решением человека, версия проекта считается по истории —
    «столько изменений принято после выпуска». Свести их в одно значило бы либо
    скрыть работу, либо объявить выпуском каждое изменение (035).
    """
    collected = facts.collect(ROOT, "abc1234")
    assert collected["contract"], "объявленный контракт исчез из фактов"
    assert collected["version"], "посчитанной версии в фактах нет"
    assert collected["version"] != collected["contract"] or collected["version"].endswith(".0")


def test_the_facts_say_whether_the_version_is_whole() -> None:
    """Неполнота названа рядом с числом, а не выброшена.

    Клон без тегов даёт правдоподобное число: MAJOR.MINOR берутся из
    объявленного контракта вместо выпущенного. Потребитель фактов должен видеть
    это в данных, а не догадываться (046).
    """
    assert "version_whole" in facts.collect(ROOT, "abc1234")


def test_the_badge_run_fetches_the_tags() -> None:
    """Прогон значков берёт всю историю и теги — иначе версия считается ложно."""
    text = (ROOT / ".github" / "workflows" / "badges.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 0" in text
    assert "fetch-tags: true" in text


def test_checks_facts_count_both_sections(tmp_path: Path) -> None:
    """Факты считают проверки обоих разделов, а не половину на изменении.

    Умолчание у `names_of` — первый раздел, и без явного «из любого» число
    совещательных занизилось бы ровно на те прогоны, которые второй раздел и
    завёл. Факты публикуются наружу и говорят о конвейере целиком. Нашёл
    внешний взгляд на #155 — на том же изменении, которое умолчание ввело.
    """
    answer = tmp_path / ".pipeline.yml"
    answer.write_text(
        'schema: 4\ncontract: ">=9.9,<9.10"\n'
        "checks:\n  lint: required\n"
        "beyond_the_change:\n  nightly:\n    class: advisory\n"
        "    why: идёт по толчку в общую ветку\n    addressee: none\n",
        encoding="utf-8",
    )
    (tmp_path / "CONTRACT_VERSION").write_text(f"{FAKE_VERSION}\n", encoding="utf-8")
    counted = facts.checks_facts(answer)
    assert counted["required"] == 1
    assert counted["advisory"] == 1, "прогон вне изменения не попал в счёт"


# --- отставание от семьи: непосчитанное называется ---------------------------


def where_snapshot(tmp_path: Path) -> Path:
    """Сводка каталога с одним чужим ответом, который держится гейтом."""
    path = tmp_path / "where.json"
    path.write_text(
        json.dumps(
            {
                "schema": "1.2",
                "consumers": [
                    {
                        "repo": "ArtVsMark/Glossary-Python",
                        "holds": {"077": {"mechanism": "gate", "where": "scripts/x.py"}},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def answers(tmp_path: Path, body: str) -> Path:
    """Наши ответы каталогу — файлом, как их читает сборщик."""
    path = tmp_path / "bindings.json"
    path.write_text(body, encoding="utf-8")
    return path


def test_the_gap_is_counted_when_both_sides_are_named(tmp_path: Path) -> None:
    """Названы и наше имя, и файл ответов — отставание посчитано.

    Здоровый вход обязан пройти: иначе «не посчитано» неотличимо от «нечего
    считать» (097).
    """
    ours = answers(tmp_path, '{"rules": {"077": {"mechanism": "document", "status": "active"}}}')
    got = facts.family_facts(
        where_snapshot(tmp_path), mine="ArtVsMark/Engineering-Pipeline-Mechanisms", answers=ours
    )
    assert got["behind_read"] is True
    assert got["behind"] == 1 and got["behind_rules"] == ["077"]


def test_an_uncounted_gap_says_so_instead_of_showing_zero(tmp_path: Path) -> None:
    """Имя не названо — отставание НЕ посчитано, и это сказано словами.

    Молчание читалось бы как «отставания нет», а отсутствие числа и нулевое
    число — разные состояния
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Нашёл внешний взгляд на #240.
    """
    got = facts.family_facts(where_snapshot(tmp_path), mine="", answers=None)
    assert got["behind_read"] is False
    assert "behind" not in got, "непосчитанное отставание вышло числом"
    assert "не посчитано" in got["behind_why"]


def test_a_broken_answers_file_refuses_instead_of_counting_everything(tmp_path: Path) -> None:
    """Дефектный ответ — отказ, а не пустой словарь.

    Пустой дал бы отставание, равное числу ВСЕХ машинных ответов семьи:
    правдоподобное число, которое ложь. Нашёл внешний взгляд на #240.
    """
    for body in ('{"правила": {}}', "{ это не json", '{"rules": []}', '{"rules": {}}'):
        got = facts.family_facts(
            where_snapshot(tmp_path),
            mine="ArtVsMark/Engineering-Pipeline-Mechanisms",
            answers=answers(tmp_path, body),
        )
        assert got["behind_read"] is False, body
        assert "behind" not in got, body


#: Что рисовалке значка МОЖНО звать. Список РАЗРЕШИТЕЛЬНЫЙ: имя вне его делает
#: проверку слепой, а слепая отвергает (068).
#:
#: ПЕРВАЯ РЕДАКЦИЯ БЫЛА ЗАПРЕТИТЕЛЬНОЙ — перечисляла «нельзя», — и потому
#: держала не запрет, а список УГАДАННЫХ имён: `read_bytes`, `listdir`,
#: `check_output`, `urlopen` прошли бы незамеченными. Нашёл внешний взгляд.
#: Разрешительный список ошибается в безопасную сторону: новый законный вызов
#: получит отказ с названной причиной и будет дописан сюда осознанно.
#:
#: СПИСОК РАВЕН ЗАМЕРУ, А НЕ ШИРЕ ЕГО. Первая редакция дописала сюда `len`,
#: `max`, `min`, `sorted`, `abs`, `.keys`, `.join`, `.format` — ничего из этого
#: рисовалки не зовут, и разрешение выдавалось впрок. Разрешительный список,
#: выданный впрок, держит ровно столько же, сколько запретительный: он перестаёт
#: быть замером и становится догадкой о будущем (005). Нашёл внешний взгляд.
#:
#: Замер 18.09.2026: шесть рисовалок зовут ровно `badge`, `sum`, `int`, `float`,
#: `str`, `bool`, `round`, `isinstance` и методы отображения `.get`, `.items`,
#: `.values` — ничего сверх счёта по переданным фактам. Понадобится новое имя —
#: оно дописывается вместе с вызовом, а не заранее.
INSIDE_THE_FACTS: Final = frozenset(
    {
        "badge",
        "sum",
        "int",
        "float",
        "str",
        "bool",
        "round",
        "isinstance",
        ".get",
        ".items",
        ".values",
    }
)


def badge_makers() -> list[ast.FunctionDef]:
    """Рисовалки значков — те, что объявлены в инвентаре BADGES, а не по имени.

    ИМЯ БРАТЬ НЕЛЬЗЯ: признак «функция кончается на `_badge`» — подстрока, и
    рисовалка, названная иначе, ушла бы из-под проверки молча
    ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
    Инвентарь `BADGES` — тот же источник, по которому значки и собираются, так что
    предмет проверки и предмет сборки совпадают по построению (022).
    """
    named = {maker.__name__ for maker in facts.BADGES.values()}
    tree = ast.parse((ROOT / "scripts" / "build_facts.py").read_text(encoding="utf-8"))
    found = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in named
    ]
    assert len(found) == len(named), (
        "в дереве найдены не все рисовалки инвентаря: "
        f"{sorted(named)} против {sorted(node.name for node in found)}"
    )
    return found


def test_a_badge_shows_only_what_the_facts_already_say() -> None:
    """Значок рисуется ТОЛЬКО из переданных фактов — тогда сырое лежит рядом всегда.

    Форматирование — операция с потерей, и разбор строки обратно есть
    восстановление того, что сам же и уничтожил. Поэтому рядом с показанной
    величиной отдаётся исходное число
    ([122](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/122-ship-the-raw-value-next-to-the-formatted-one.md)).

    У нас это держится УСТРОЙСТВОМ: рисовалка получает факты и больше ничего, а
    факты публикуются рядом со значками тем же прогоном. Рисовалка, посчитавшая
    число сама — обходом дерева, чтением файла, запуском команды, — оставила бы
    потребителю только картинку, и сырого рядом не было бы вовсе.

    ЗАМЕР 18.09.2026: рисовалок шесть, сторонних источников у них ноль, единственный
    аргумент у каждой — факты. То есть требование исполнялось и не держалось ничем
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    """
    guilty: list[str] = []
    for maker in badge_makers():
        names = [arg.arg for arg in maker.args.args]
        if names != ["facts"]:
            guilty.append(f"{maker.name} берёт {names}, а не одни факты")
        called: set[str] = set()
        for node in ast.walk(maker):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(f".{node.func.attr}")
            else:
                called.add("<вызов неразобранной формы>")
        reached = sorted(called - INSIDE_THE_FACTS)
        if reached:
            guilty.append(f"{maker.name} зовёт не из разрешённого: {', '.join(reached)}")
    assert not guilty, (
        "значок получает число не из фактов — сырого рядом с показанным не будет (122):\n  "
        + "\n  ".join(guilty)
        + "\n  Считайте число в сборке фактов и передайте его сюда: публикуется оно"
        " рядом со значком.\n  Если вызов законен и ничего не читает — допишите его"
        " в INSIDE_THE_FACTS осознанно."
    )


def test_every_badge_maker_is_in_the_inventory() -> None:
    """Каждая рисовалка в коде стоит в инвентаре — иначе проверка выше говорит о части.

    ЗДЕСЬ НУЖЕН НЕЗАВИСИМЫЙ СВИДЕТЕЛЬ, И ЭТО НЕ ПРИДИРКА. Первая редакция
    сравнивала инвентарь с функциями, найденными ПО ЭТОМУ ЖЕ инвентарю, — то есть
    сама с собой, и снятие значка из `BADGES` она не замечала: рисовалка уходила из
    предмета вместе с записью о ней. Поймано откатом
    ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).

    Свидетель — имя функции, кончающееся на `_badge`. Признак это слабый, и
    основным он быть не может (166), но роль у него обратная: он ищет рисовалку,
    которую инвентарь ЗАБЫЛ. Ошибётся он в безопасную сторону — потребует записать
    в инвентарь то, что и так там должно быть.
    """
    assert facts.BADGES, "инвентарь значков пуст — предмет проверки не найден (075)"
    tree = ast.parse((ROOT / "scripts" / "build_facts.py").read_text(encoding="utf-8"))
    in_code = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.endswith("_badge")
    }
    assert in_code, "рисовалок значков в дереве не нашлось — предмет проверки не найден (075)"
    forgotten = sorted(in_code - {maker.__name__ for maker in facts.BADGES.values()})
    assert not forgotten, (
        "рисовалка есть в коде, но не в инвентаре — значок собирается в обход, и"
        f" проверка выше его не судит: {', '.join(forgotten)}"
    )


def test_the_allowed_list_equals_the_measurement() -> None:
    """Разрешено ровно то, что рисовалки зовут, — ни именем больше.

    Разрешительный список, выданный впрок, держит столько же, сколько
    запретительный: он перестаёт быть замером и становится догадкой о будущем.
    Нашёл внешний взгляд.
    """
    called: set[str] = set()
    for maker in badge_makers():
        for node in ast.walk(maker):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(f".{node.func.attr}")
    assert called, "рисовалки не зовут ничего — предмет замера не найден (075)"
    spare = sorted(INSIDE_THE_FACTS - called)
    assert not spare, (
        "разрешено впрок то, чего рисовалки не зовут: " + ", ".join(spare) + "\n  Разрешение"
        " дописывают вместе с вызовом, а не заранее."
    )


def test_an_empty_answer_is_refused_before_the_count(tmp_path: Path) -> None:
    """Пустой ответ каталогу отвергается РАЗБОРОМ, а не счётчиком нулей.

    В списке `counted` у сборки стояло и `rules.total` — запись недостижимая:
    до неё `rules_facts` уже отказал входу. Два места, отвергающие одно,
    расходятся молча, и починив одно, про второе забывают
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    Запись убрана, а отказ обязан остаться ровно один — этот
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    empty = tmp_path / "bindings.json"
    empty.write_text('{"rules": {}}', encoding="utf-8")
    with pytest.raises(facts.NotRun):
        facts.rules_facts(empty)
