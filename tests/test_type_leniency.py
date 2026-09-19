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
import sys
import tomllib
from typing import Final

import pytest
import yaml

from tests.conftest import ROOT, found_by, walk_deep

SETTINGS: Final = ROOT / "pyproject.toml"
#: Откуда берётся, ЧТО разбирает шаг. Список каталогов здесь не пишется второй
#: копией: разъехавшись с прогоном, он судил бы не то дерево, и разъехался бы
#: молча ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
STEP: Final = ROOT / ".github" / "workflows" / "ci.yml"
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
    doc = yaml.safe_load(STEP.read_text(encoding="utf-8"))
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if str(step.get("name", "")).strip() != STEP_NAME:
                continue
            said = str(step.get("run", "")).split()
            return tuple(one.rstrip("/") for one in said[1:] if not one.startswith("-"))
    raise AssertionError(f"в {STEP} нет шага «{STEP_NAME}» — предмет гейта не найден (075)")


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


def imported() -> dict[str, set[str]]:
    """Полные пути модулей, которые импортирует дерево, → где именно.

    Путь берётся ЦЕЛИКОМ, а не верхним именем: `_pytest.config` и `_pytest` —
    для mypy разные вопросы, и вся беда инцидента была ровно в этой разнице.
    """
    found: dict[str, set[str]] = {}
    for where in judged():
        # ВГЛУБЬ, ПОТОМУ ЧТО ШАГ ИДЁТ ВГЛУБЬ. `mypy scripts/` разбирает и
        # подкаталоги; нерекурсивный обход отвечал бы о МЕНЬШЕМ дереве, чем то,
        # на котором краснеет площадка, — и первый же модуль в подкаталоге
        # уехал бы мимо гейта молча (045). Нашёл внешний взгляд (`d58e2b3`).
        for path in walk_deep(ROOT / where, "*.py"):
            if "__pycache__" in path.parts:
                continue
            said = str(path.relative_to(ROOT))
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
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
        found |= {path.stem for path in walk_deep(root, "*.py") if path.parent == root}
        found |= {path.parent.name for path in found_by(root, "*/__init__.py")}
    for where in str(doc["tool"]["mypy"].get("mypy_path", "")).split(":"):
        if not where:
            continue
        # ОБХОД-ПРЕДМЕТ: каталог из `mypy_path`, в котором нет ни одного модуля,
        # — обрыв, а не ответ: разбор типов тогда ищет общий низ и не находит.
        found |= {path.stem for path in walk_deep(ROOT / where, "*.py")}
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
    step = yaml.safe_load(STEP.read_text(encoding="utf-8"))
    runs = [
        str(one.get("run", ""))
        for job in (step.get("jobs") or {}).values()
        for one in (job.get("steps") or [])
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
        for path in walk_deep(ROOT / where, "*.py")
        if path.parent != ROOT / where and "__pycache__" not in path.parts
    ]
    assert deeper, (
        "в разбираемых каталогах нет ни одного модуля глубже первого уровня —"
        " разницу между обходом вглубь и обычным здесь не на чем проверить (075)"
    )
    known = own_names() | {name.split(".")[0] for name in foreign(imported())}
    missed = [path for path in deeper if path.stem not in known and path.name != "__init__.py"]
    assert not missed, f"модуль из подкаталога не попал в предмет гейта: {missed}"
