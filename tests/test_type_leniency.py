"""Послабление разбора типов соответствует тому, что набор реально импортирует.

ШАГ «ТИПЫ» СТАВИТ СЕБЕ НЕ ТО, ЧТО СТОИТ У ОКНА. Он ставит `ruff`, `mypy` и
`pyyaml` — и всё; `pytest` он не ставит ни под каким именем. Импорты набора
видны ему только через `[[tool.mypy.overrides]]` с `ignore_missing_imports`, а
список этот записан **перечислением имён** и ведётся руками. У окна же `pytest`
установлен, поэтому его зелёное площадку по этому шагу не предсказывает —
`scripts/check_env.py` сверяет ВЕРСИИ, а здесь расходится СОСТАВ.

ИНЦИДЕНТ 19.09.2026, изменение #509. Проверка живой настройки стала спрашивать
её через `import _pytest.config`. В послаблении стояло `["yaml", "pytest"]`;
формы `_pytest.config` там не было, и шаг покраснел уже на площадке:

    tests/test_suite_kit.py: Cannot find implementation or library stub
    for module named "_pytest.config"  [import-not-found]

Это ровно форма записи, которой гейт не видит
([206](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/206-a-form-the-gate-cannot-see-is-a-bypass.md)).

ПРЕДИКАТ ЗДЕСЬ — СООТВЕТСТВИЕ, А НЕ ОТСУТСТВИЕ. Проверка «есть ли импорт,
неизвестный шагу» даёт сегодня НОЛЬ: список починен, и гейт вокруг пустоты
доказывал бы только себя
([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
Предмет есть у соответствия, и он двусторонний: запись без предмета — это
послабление, выданное вперёд, а форма без записи — красный шаг.

ЗАМЕР 19.09.2026, СДЕЛАННЫЙ ПРОГОНОМ, А НЕ РАССУЖДЕНИЕМ. Записей четыре, форм
под ними в дереве три. Счёт сначала назвал простаивающими ДВЕ записи, `yaml` и
`_pytest`, — и список имён показал, что предикат шире предмета: `pyyaml` шагом
СТАВИТСЯ, но типов не несёт, и `yaml` нужен. Решил это не довод, а снятие
каждой записи порознь с прогоном `mypy` в окружении шага: без `yaml` — 3 ошибки,
без `pytest` — 6, без `_pytest.*` — 2, **без `_pytest` — чисто**. Простаивает
одна запись из четырёх, и комментарий рядом с ней утверждал обратное
([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).

ЧЕГО ГЕЙТ НЕ ЛОВИТ, и это названо, а не выровнено: он судит СООТВЕТСТВИЕ имён, а
не разрешимость — про неё знает только сам `mypy` в окружении шага. Библиотека,
которую шаг ставит, но которая не несёт типов, послабления требует, и отличить
её от лишней записи по дереву нечем: такую запись гейт считает нужной, если её
имя в дереве импортируется
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

from __future__ import annotations

import ast
import contextlib
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Final

import pytest
import yaml

from tests.conftest import ROOT, found_by, walk_deep

SETTINGS: Final = ROOT / "pyproject.toml"
#: Откуда берётся, ЧТО разбирает шаг. Список каталогов здесь не пишется второй
#: копией: разъехавшись с прогоном, он судил бы не то дерево, и разъехался бы
#: молча ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
#:
#: ШАГ ИЩЕТСЯ ПО ВСЕМУ КАТАЛОГУ ПРОГОНОВ, А НЕ В ОДНОМ ФАЙЛЕ. Прибитый к
#: `ci.yml` поиск сломался на первом же выносе шага в переиспользуемый прогон:
#: файл — адрес шага, а не его личность, и адрес вправе меняться (168).
STEPS: Final = ROOT / ".github" / "workflows"
#: Имя шага, чьи доводы и есть предмет.
STEP_NAME: Final = "типы"
#: Хвост образца mypy: `X.*` покрывает потомков `X`, но НЕ сам `X`. Различие не
#: косметическое: `pytest` в списке не покрывает `_pytest.config`, и ровно этим
#: инцидент 19.09.2026 и кончился. Голая запись `_pytest` рядом со звёздчатой
#: СТОЯЛА и оказалась лишней — снятие её порознь с прогоном в окружении шага
#: ничего не покрасило, и запись убрана (139).
DESCENDANTS: Final = ".*"


def judged() -> tuple[str, ...]:
    """Каталоги, которые разбирает шаг «типы», — ИЗ САМОГО ПРОГОНА.

    Читается строка шага, а не пишется список рядом. Второй список тех же
    каталогов разошёлся бы с прогоном молча, и гейт судил бы не то дерево
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    """
    for path in walk_deep(STEPS, "*.yml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in ((doc or {}).get("jobs") or {}).values():
            for step in (job or {}).get("steps") or []:
                if str(step.get("name", "")).strip() != STEP_NAME:
                    continue
                said = str(step.get("run", "")).split()
                return tuple(one.rstrip("/") for one in said[1:] if not one.startswith("-"))
    raise AssertionError(f"в {STEPS} нет шага «{STEP_NAME}» — предмет гейта не найден (075)")


def leniencies() -> list[str]:
    """Имена, которым разбор типов прощает ненайденность, — как они записаны."""
    doc = tomllib.loads(SETTINGS.read_text(encoding="utf-8"))
    found: list[str] = []
    for one in doc["tool"]["mypy"].get("overrides", []):
        if not one.get("ignore_missing_imports"):
            continue
        said = one["module"]
        found += [said] if isinstance(said, str) else list(said)
    return found


def carried(where: Path) -> list[Path]:
    """Модули каталога, которые ВЕЗЁТ ЧЕКАУТ, — вглубь и без произведённого.

    ПРОИЗВЕДЁННОЕ ОТСЕКАЕТСЯ ИСТОЧНИКОМ, А НЕ СПИСКОМ ИМЁН. Рекурсивный обход
    подхватывал бы копии модулей из `build/`, `dist/` и `*.egg-info`, которые
    заводит сборка пакета, — у окна они есть, у прогона на свежем чекауте их
    нет, и гейт отвечал бы о ДРУГОМ дереве, чем то, на котором краснеет
    площадка. Нашёл внешний взгляд (`54955e7`).

    Запретительный список таких имён пропускал бы неугаданное — ровно то, за
    что их и отвергают
    ([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)).
    Источник здесь один и он же у прогона: `git ls-files --cached`, то есть в
    точности содержимое чекаута
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

    СПРАШИВАЕТСЯ ИНДЕКС, А НЕ ДЕРЕВО, И `--others` ЗДЕСЬ БЫЛ ЛИШНИМ. С ним в
    предмет попадали файлы, которых в чекауте нет вовсе: неотслеживаемый черновик
    у окна краснил бы гейт там, где площадка зелена, — то есть проверка отвергала
    бы верную работу
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    Нашёл внешний взгляд (`beb5427`).

    ГРАНИЦЫ НАЗВАНЫ, ОБЕ. Модуль, ещё не внесённый в индекс, гейт не судит — и
    это верно: до площадки он тоже не доедет, а внесут его тем же `git add`, что
    и всё остальное перед толчком. И произведённое, которое прогон делает САМ и
    до шага типов, сюда не попадёт: сегодня такого нет, а появится — гейт о нём
    промолчит
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
    """
    return sorted(carried_text(where))


def carried_text(where: Path) -> dict[Path, str]:
    """То же, но СОДЕРЖИМОЕ тоже из индекса, а не с диска.

    ПУТЬ ИЗ ИНДЕКСА, А ТЕКСТ С ДИСКА — ЭТО ДВА РАЗНЫХ ДЕРЕВА В ОДНОМ ОТВЕТЕ.
    Модуль, внесённый в индекс с одним содержимым и правленный после в рабочем
    дереве, разбирался бы по правке, которой на площадке нет: гейт отвечал бы о
    том, чего не поедет. Разойдётся это ровно там, где окно и работает —
    посреди правки, — и разойдётся молча
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Нашёл внешний взгляд (`834a95b`).

    ЧИТАЕТСЯ ОДНИМ ЗАХОДОМ: `ls-files -s` даёт отпечатки содержимого, а
    `cat-file --batch` отдаёт их разом. Заход на файл стоил бы полутора сотен
    вызовов git на каждый прогон.

    СОСЕДИ ПО РОДУ НАЗВАНЫ, И ЗАМЕР ПРИВЕДЁН
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    Список путей от `git ls-files` с последующим чтением текста стоит в дереве
    ещё в шести местах — замер 19.09.2026, `grep -rn "ls-files" scripts/ tests/`
    с чтением каждого. Пять из них перечисляют `--cached --others
    --exclude-standard`, то есть ВМЕСТЕ с рабочим деревом, и чтение с диска там
    согласовано: `scripts/check_rule_links.py`, `scripts/check_own_name.py`,
    `scripts/check_version.py`, `tests/test_citation_applicability.py`,
    `tests/test_doc_links.py`. Расходилось одно — `scripts/check_foreign_why.py`,
    — и оно починено тем же изменением, только в ДРУГУЮ сторону: гейт советует
    окну перед толчком, и судить ему надо то, что окно отправит. Здесь наоборот,
    потому что договор здесь — «предскажи площадку».
    """
    listed = subprocess.run(
        ["git", "ls-files", "-s", "-z", "--cached", "--", str(where)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if listed.returncode != 0:
        raise AssertionError(f"список файлов чекаута не получен: {listed.stderr.strip()}")
    blobs: dict[Path, str] = {}
    for row in listed.stdout.split("\0"):
        if not row:
            continue
        head, _, name = row.partition("\t")
        if not name.endswith(".py"):
            continue
        blobs[ROOT / name] = head.split()[1]
    if not blobs:
        raise AssertionError(
            f"в «{where}» чекаут не везёт ни одного модуля — предмет проверки исчез,"
            " и зелёное здесь ничего не значит (075)"
        )
    got = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        input=("\n".join(blobs.values()) + "\n").encode(),
        capture_output=True,
    )
    if got.returncode != 0:
        raise AssertionError(f"содержимое из индекса не прочитано: {got.stderr!r}")
    found: dict[Path, str] = {}
    rest = got.stdout
    for path in blobs:
        line, _, rest = rest.partition(b"\n")
        size = int(line.split()[2])
        found[path] = rest[:size].decode("utf-8")
        rest = rest[size + 1 :]
    return found


def imported() -> dict[str, set[str]]:
    """Полные пути модулей, которые импортирует дерево, → где именно.

    Путь берётся ЦЕЛИКОМ, а не верхним именем: `_pytest.config` и `_pytest` —
    для mypy разные вопросы, и вся беда инцидента была ровно в этой разнице.
    """
    found: dict[str, set[str]] = {}
    for where in judged():
        # ВГЛУБЬ, ПОТОМУ ЧТО ШАГ ИДЁТ ВГЛУБЬ, И ПО ЧЕКАУТУ — ПУТЬ И ТЕКСТ, —
        # ПОТОМУ ЧТО ИМ ЖЕ живёт прогон. `mypy scripts/` разбирает подкаталоги,
        # но видит там ровно то, что приехало с чекаутом: не сборочные копии у
        # окна и не правку, ещё не внесённую в индекс. Нашли внешним взглядом:
        # `d58e2b3`, `54955e7`, `834a95b`.
        for path, text in sorted(carried_text(ROOT / where).items()):
            said = str(path.relative_to(ROOT))
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        found.setdefault(alias.name, set()).add(said)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    found.setdefault(node.module, set()).add(said)
    return found


def covers(pattern: str, name: str) -> bool:
    """Покрывает ли образец послабления этот путь модуля — по правилам mypy."""
    if pattern.endswith(DESCENDANTS):
        return name.startswith(pattern[: -len(DESCENDANTS)] + ".")
    return name == pattern


def own_names() -> set[str]:
    """Имена, которые разбор типов находит в самом дереве, а не в окружении.

    Три источника, и все три — из дерева: модули `scripts/` (шаг разбирает их
    как модули), каталоги из `mypy_path`, и собственные пакеты набора.
    """
    doc = tomllib.loads(SETTINGS.read_text(encoding="utf-8"))
    # ИМЯ МОДУЛЯ — ВЕРХНЕЕ ОТНОСИТЕЛЬНО РАЗБИРАЕМОГО КОРНЯ. Для `scripts/x.py`
    # это `x` (ключ `scripts_are_modules`), для `tests/…` — сам `tests`.
    found: set[str] = {"conftest"}
    for where in judged():
        root = ROOT / where
        found.add(root.name)
        found |= {path.stem for path in carried(root) if path.parent == root}
        found |= {path.parent.name for path in found_by(root, "*/__init__.py")}
    for where in str(doc["tool"]["mypy"].get("mypy_path", "")).split(":"):
        if not where:
            continue
        # ПУСТОЙ КАТАЛОГ ИЗ `mypy_path` — ОБРЫВ, а не ответ: разбор типов тогда
        # ищет общий низ и не находит. Отказ на пустоте даёт сам `carried`.
        found |= {path.stem for path in carried(ROOT / where)}
        # ОБХОД-ВОПРОС: пакетов рядом может не быть вовсе, и это законный ответ.
        found |= {path.parent.name for path in found_by(ROOT / where, "*/__init__.py")}
    return found


def foreign(found: dict[str, set[str]]) -> dict[str, set[str]]:
    """Импорты, которых шаг «типы» в дереве не найдёт, — ПРЕДМЕТ гейта.

    ПРЕДМЕТ ИДЁТ ОТ ДЕРЕВА, А НЕ ОТ СПИСКА, И ЭТО НЕ ОФОРМЛЕНИЕ. Первая редакция
    брала формы «под именами из послабления» — и тогда снятие записи убирало
    форму из предмета ВОВСЕ: гейт переставал её судить и зеленел. Поймано
    откатом: возврат списка к тому виду, что был до инцидента, проверку не
    покрасил. Откат, который не покраснел, — находка, а не облегчение
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    mine = own_names()
    return {
        name: where
        for name, where in found.items()
        if name.split(".")[0] not in sys.stdlib_module_names and name.split(".")[0] not in mine
    }


def test_the_subject_of_this_gate_exists() -> None:
    """Формы под послаблением в дереве есть — иначе судить нечего (075)."""
    written = leniencies()
    assert written, "в разборе типов нет ни одного послабления — предмет исчез"
    forms = foreign(imported())
    print(f"\nзаписей послабления: {len(written)} — {written}")
    print(f"чужих импортов в дереве: {len(forms)}")
    for name, where in sorted(forms.items()):
        which = [one for one in written if covers(one, name)]
        print(f"  {name:22} ← {which or 'НЕ ПОКРЫТА'}  ({len(where)} мест)")
    assert forms, (
        "набор не импортирует ничего, чего шаг «типы» не нашёл бы в дереве — предмет"
        " исчез, и зелёное здесь ничего не значит"
    )


def test_every_imported_form_is_covered_as_it_is_written() -> None:
    """Каждая форма под послаблением покрыта ИМЕННО в том виде, как записана.

    Половина «гейт ловит». `pytest` в списке не покрывает `_pytest.config`, и
    даже `_pytest` не покрывает его: mypy спрашивает про полный путь. Пока этого
    не проверял никто, форму находила площадка — то есть после толчка (206).
    """
    written = leniencies()
    bare = [
        f"{name} ({', '.join(sorted(where)[:2])})"
        for name, where in sorted(foreign(imported()).items())
        if not any(covers(one, name) for one in written)
    ]
    assert not bare, (
        "форма импорта под послаблением не покрыта — шаг «типы» покраснеет на площадке"
        " (206):\n  " + "\n  ".join(bare) + f"\n  Записано сейчас: {written}."
        "\n  Помните: образец «X.*» покрывает потомков X, но не сам X."
    )


def test_every_lenience_has_something_to_cover() -> None:
    """У каждой записи есть что покрывать — иначе послабление выдано вперёд.

    Половина «гейт не ловит лишнего», и без неё список растёт именами «про
    запас»: снаружи такой неотличим от выверенного, а прощает он в том числе то,
    чего никто не проверял (068).

    ЗАПИСЬ ПРОСТАИВАЮЩУЮ НАШЁЛ ПРОГОН, А НЕ ДОВОД. Комментарий рядом с ней
    утверждал, что mypy требует обе формы `_pytest`; снятие каждой записи
    порознь с прогоном в окружении шага показало обратное (139).
    """
    written = leniencies()
    found = imported()
    idle = [one for one in written if not any(covers(one, name) for name in found)]
    assert not idle, (
        "послабление выдано вперёд — покрывать в дереве нечего: "
        + ", ".join(idle)
        + ".\n  Уберите запись либо назовите, что она покрывает."
    )


#: Что образец послабления покрывает, а что нет, — по правилам mypy.
#: Таблица, а не проза: ровно это различие и стоило инцидента 19.09.2026.
COVERAGE: Final = (
    ("голое имя покрывает себя", "pytest", "pytest", True),
    ("голое имя НЕ покрывает потомка", "_pytest", "_pytest.config", False),
    ("голое имя не покрывает соседа", "pytest", "_pytest", False),
    ("звезда покрывает потомка", "_pytest.*", "_pytest.config", True),
    ("звезда покрывает внука", "_pytest.*", "_pytest.a.b", True),
    ("звезда НЕ покрывает сам корень", "_pytest.*", "_pytest", False),
    ("звезда не покрывает похожее имя", "_pytest.*", "_pytestx.config", False),
    ("приставка не значит покрытия", "py", "pytest", False),
)


@pytest.mark.parametrize(("case", "pattern", "name", "want"), COVERAGE)
def test_the_mypy_pattern_semantics_are_held_by_a_run(
    case: str, pattern: str, name: str, want: bool
) -> None:
    """Семантика образца закреплена таблицей, а не доводом в одной функции.

    ПРОВЕРКА ЗАВЕЛАСЬ ОТКАТОМ, КОТОРЫЙ НЕ ПОКРАСНЕЛ. Огрубление `covers` до
    «голое имя покрывает и потомков» вместе с записью `_pytest` вместо
    `_pytest.*` оставило гейт ЗЕЛЁНЫМ — то есть он объявлял покрытым ровно то,
    на чём площадка краснеет. Разницу между `X` и `X.*` не держало ничего:
    тот самый случай, когда откат, не покрасивший проверку, есть находка
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    assert covers(pattern, name) is want, case


def test_the_subject_is_taken_from_the_step_not_written_beside_it() -> None:
    """Разбираемые каталоги читаются у прогона — второй список разошёлся бы молча.

    Здесь они были написаны рядом константой, и один из трёх — `packages/transport`
    вместо `packages` — уже расходился с прогоном: гейт судил ДРУГОЕ дерево, чем
    то, на котором краснеет площадка
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    """
    said = judged()
    assert said, "шаг «типы» не назвал ни одного каталога — предмет гейта исчез (075)"
    runs = [
        str(one.get("run", ""))
        for path in walk_deep(STEPS, "*.yml")
        for job in (
            (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("jobs") or {}
        ).values()
        for one in ((job or {}).get("steps") or [])
        if str(one.get("name", "")).strip() == STEP_NAME
    ]
    assert len(runs) == 1, f"шаг «{STEP_NAME}» объявлен не один раз: {len(runs)}"
    for where in said:
        assert f"{where}/" in runs[0], f"каталог «{where}» шагу не отдаётся: {runs[0]}"
        assert (ROOT / where).is_dir(), f"каталог «{where}» шагу отдаётся, а в дереве его нет"


def test_the_walk_goes_as_deep_as_the_step_does() -> None:
    """Обход идёт ВГЛУБЬ, потому что вглубь идёт и сам шаг.

    `mypy scripts/` разбирает подкаталоги тоже. Нерекурсивный обход отвечал бы о
    МЕНЬШЕМ дереве, чем то, на котором краснеет площадка, и первый же модуль,
    уехавший в подкаталог, прошёл бы мимо гейта молча
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Нашёл внешний взгляд (`d58e2b3`).

    ПРЕДМЕТ У ПРОВЕРКИ ЕСТЬ: модули в подкаталогах разбираемых корней в дереве
    сегодня живут — `packages/transport/*.py`, два штуки. Была бы их пустота,
    проверка сторожила бы то, чего нет (075).

    ЧТО ИМЕННО ДЕРЖИТ ЭТА ПРОВЕРКА, СКАЗАНО ТОЧНО, А НЕ ШИРОКО. Она держит, что
    модуль из подкаталога ИЗВЕСТЕН предмету: убери ветку `mypy_path` из
    `own_names` — и краснеет соседняя половина, «форма не покрыта». Чего она НЕ
    держит и что проверено откатом: сделай `imported` нерекурсивным — и НИЧЕГО
    не покраснеет, потому что оба здешних подкаталожных модуля чужого не
    импортируют вовсе. То есть рекурсия здесь — названная защита БЕЗ предмета
    сегодня, а не проверенное поведение; выдать её за проверенную значило бы
    поставить слово там, где нет прогона
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md),
    [139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)).
    """
    deeper = [
        path.relative_to(ROOT)
        for where in judged()
        for path in carried(ROOT / where)
        if path.parent != ROOT / where
    ]
    assert deeper, (
        "в разбираемых каталогах нет ни одного модуля глубже первого уровня —"
        " разницу между обходом вглубь и обычным здесь не на чем проверить (075)"
    )
    known = own_names() | {name.split(".")[0] for name in foreign(imported())}
    missed = [path for path in deeper if path.stem not in known and path.name != "__init__.py"]
    assert not missed, f"модуль из подкаталога не попал в предмет гейта: {missed}"


def test_a_build_copy_in_the_tree_is_not_the_subject() -> None:
    """Сборочная копия модуля в предмет не попадает — её нет у прогона.

    `pip install -e` и `python -m build` кладут копии модулей в `build/`,
    `dist/` и `*.egg-info`. У окна они есть, у прогона на свежем чекауте — нет,
    и гейт, читающий их, отвечал бы о ДРУГОМ дереве, чем то, на котором
    краснеет площадка
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Нашёл внешний взгляд (`54955e7`).

    ПРОВЕРЯЕТСЯ НА НАСТОЯЩЕЙ КОПИИ, А НЕ НА ИМЕНИ КАТАЛОГА. Копия заводится в
    дереве под тем же `git`, которым живёт чекаут: подделка подтверждала бы
    согласие кода с нашим представлением об игнорировании, а не с ним самим
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    """
    where = judged()[0]
    made = ROOT / where / "build" / "lib" / "поддельный_модуль.py"
    # УБОРКА СНОСИТ РОВНО ТО, ЧТО ЗАВЕЛА. `rmdir` каталога, который уже был у
    # окна, отказывает — и отказ уборки читался бы как красный гейт, хотя
    # проверяемое сошлось. Поэтому запоминается, какие каталоги создала эта
    # проверка, и сносятся только они. Нашёл внешний взгляд (`81ffda3`).
    mine = [one for one in (made.parent, made.parent.parent) if not one.is_dir()]
    made.parent.mkdir(parents=True, exist_ok=True)
    try:
        made.write_text("import такого_имени_нет_нигде\n", encoding="utf-8")
        seen = {path.name for path in carried(ROOT / where)}
        assert made.name not in seen, (
            f"сборочная копия попала в предмет: {made.relative_to(ROOT)} — гейт судит"
            " дерево окна, а не то, что приезжает с чекаутом"
        )
        assert "такого_имени_нет_нигде" not in imported(), (
            "импорт из сборочной копии засчитан чужим — гейт покраснеет там, где площадка зелена"
        )
    finally:
        made.unlink(missing_ok=True)
        for one in mine:
            # Чужое содержимое не трогаем: каталог, ставший непустым от соседа,
            # оставляем как есть — уборка не вправе сносить чужое.
            with contextlib.suppress(OSError):
                one.rmdir()


def test_an_untracked_draft_is_not_the_subject() -> None:
    """Неотслеживаемый черновик у окна предметом не является — его нет в чекауте.

    С `--others` он попадал в предмет, и гейт краснел бы там, где площадка
    зелена: отвергать верную работу дороже, чем пропустить неверную
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    Нашёл внешний взгляд (`beb5427`).

    ЧЕРНОВИК ЗАВОДИТСЯ НАСТОЯЩИЙ — в дереве, под тем же `git`, каким живёт
    чекаут, и в каталоге, который НЕ игнорируется: иначе проверка спрашивала бы
    про игнорирование, а не про индекс
    ([170](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/170-green-on-a-forgery-is-a-hypothesis-too.md)).
    """
    where = judged()[0]
    draft = ROOT / where / "черновик_окна.py"
    assert not draft.exists(), f"имя занято: {draft}"
    try:
        draft.write_text("import такого_имени_нет_нигде\n", encoding="utf-8")
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(draft.relative_to(ROOT))],
            cwd=ROOT,
            capture_output=True,
        )
        assert ignored.returncode != 0, (
            "черновик оказался в игнорируемом каталоге — проверка спросила бы про"
            " игнорирование, а не про индекс"
        )
        assert draft.name not in {path.name for path in carried(ROOT / where)}, (
            "неотслеживаемый черновик попал в предмет: гейт судит дерево окна, а не"
            " то, что приезжает с чекаутом"
        )
    finally:
        draft.unlink(missing_ok=True)


def test_an_edit_not_yet_in_the_index_is_not_read() -> None:
    """Содержимое берётся из индекса: правка на диске площадке ещё не видна.

    Путь из индекса, а текст с диска — это два разных дерева в одном ответе.
    Модуль, внесённый с одним содержимым и правленный после, разбирался бы по
    правке, которой на площадке нет, и гейт отвечал бы о том, чего не поедет
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Нашёл внешний взгляд (`834a95b`).

    ПРАВКА НАСТОЯЩАЯ И В ОТСЛЕЖИВАЕМОМ ФАЙЛЕ: своё содержимое дописывается на
    диск и снимается обратно. Подделка подтверждала бы наше представление об
    индексе, а не сам индекс (170).
    """
    # ИМЯ СОБИРАЕТСЯ, А НЕ ПИШЕТСЯ ЦЕЛИКОМ: написанное целиком лежало бы в этом
    # же файле, и проверка нашла бы САМУ СЕБЯ в содержимом из индекса — зелёное
    # или красное там говорило бы о литерале, а не об источнике чтения.
    mark = "не" + "внесённая" + "_правка"
    mine = Path(__file__).resolve()
    was = mine.read_bytes()
    try:
        mine.write_bytes(was + f"\nimport {mark}\n".encode())
        text = carried_text(ROOT / "tests").get(mine)
        assert text is not None, f"{mine.name} не найден в индексе — предмет не тот"
        assert mark not in text, (
            "содержимое прочитано с диска: гейт судит правку, которой на площадке нет"
        )
        assert mark not in imported(), (
            "импорт из невнесённой правки засчитан — гейт покраснеет там, где площадка зелена"
        )
    finally:
        mine.write_bytes(was)
