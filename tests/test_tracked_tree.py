"""Что лежит в дереве под учётом — и чего там лежать не должно.

Порождённое учётом не ведут: файл, который собирается из источника, второй
раз хранить негде, и хранимая копия расходится с источником молча
([125](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/125-a-generated-file-is-not-a-store.md)).

ЗАЧЕМ ГЕЙТ, ЕСЛИ ЕСТЬ `.gitignore`. Список игнора действует на НЕОТСЛЕЖИВАЕМОЕ:
файл, однажды взятый под учёт, он не отпускает. То есть запись в нём выглядит
защитой и ею не является — ровно тот случай, когда правило есть, а механизма
под ним нет
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ЗАМЕР 15.09.2026. Перенос общего низа в пакет притащил под учёт четыре файла
`*.egg-info/`, порождённых установкой: `PKG-INFO`, `SOURCES.txt`,
`dependency_links.txt`, `top_level.txt`. Строка `*.egg-info/` в `.gitignore`
при этом стояла и молчала. Нашёл внешний взгляд — дважды, находками `47cc3e2`
и `559cfa0` на #367, и оба раза механизм ничего не сказал.
"""

from __future__ import annotations

import subprocess
from fnmatch import fnmatch
from typing import Final

import pytest

from tests.conftest import ROOT

#: Что установка и сборка пишут рядом с `pyproject.toml` локального пакета.
#: Список ОБЪЯВЛЕН, а не выведен: имена задаёт setuptools и `python -m build`, и
#: угадывать их по дереву нечем — на чистой выкладке их там нет вовсе. Каждое имя
#: стоит здесь потому, что его пишет инструмент, а не «на всякий случай» (154).
#: Метки, ограничивающие список производного сборки в `.gitignore`. Строка одна
#: на обе стороны проверки: второе написание разошлось бы с первым молча (022).
IGNORE_BEGIN: Final = "# начало списка производного сборки"
IGNORE_END: Final = "# конец списка производного сборки"

BUILD_OUTPUTS: Final = (
    ("<пакет>.egg-info/PKG-INFO", "метаданные, которые пишет `pip install`"),
    ("build/lib/модуль.py", "промежуточная сборка `python -m build`"),
    ("dist/пакет-0.1.0.tar.gz", "готовый архив выпуска"),
    ("dist/пакет-0.1.0-py3-none-any.whl", "готовое колесо выпуска"),
)


def packages() -> list[str]:
    """Локальные пакеты дерева — по объявлению, а не по списку имён (005)."""
    return sorted(
        str(one.parent.relative_to(ROOT)) for one in ROOT.glob("packages/*/pyproject.toml")
    )


def tracked_but_ignored() -> list[str]:
    """Пути под учётом, которые дерево само объявило игнорируемыми.

    Список читается по NUL (165): имя с пробелом или кириллицей git иначе
    экранирует, путь не разрешается, и файл выпадает из проверки молча.
    """
    done = subprocess.run(
        ["git", "ls-files", "-z", "-i", "-c", "--exclude-standard"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=True,
    )
    return [one for one in done.stdout.split("\0") if one]


def test_nothing_ignored_is_also_tracked() -> None:
    """Файл не бывает одновременно под учётом и в списке игнора.

    Это ПРОТИВОРЕЧИЕ дерева самому себе, а не мелочь оформления: запись в
    `.gitignore` объявляет файл порождённым, учёт — хранимым, и второе молча
    отменяет первое. Дальше он живёт в истории, приезжает в каждое изменение
    шумом и расходится с тем, из чего порождён (125, 045).
    """
    found = tracked_but_ignored()
    assert not found, (
        "под учётом лежит игнорируемое — снять командой `git rm -r --cached <путь>`: "
        + ", ".join(found)
    )


def test_the_gate_has_a_subject_to_look_at() -> None:
    """Проверка обращается к настоящему дереву, а не к пустоте (075).

    Ноль путей — законный ответ ТОЛЬКО если git вообще ответил про это дерево.
    Гейт, молчащий потому, что не нашёл репозитория, читался бы как «чисто».
    """
    done = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=True,
    )
    assert [one for one in done.stdout.split("\0") if one], "git не видит дерева проекта"


def test_the_tree_declares_local_packages_at_all() -> None:
    """Локальные пакеты находятся: без них проверка ниже — поверхность без предмета (075)."""
    assert packages(), "в дереве не найдено ни одного локального пакета"


@pytest.mark.parametrize("package", packages())
@pytest.mark.parametrize("output,why", BUILD_OUTPUTS, ids=lambda one: str(one).split("/")[0])
def test_every_build_output_of_a_package_is_ignored(package: str, output: str, why: str) -> None:
    """Производное сборки объявлено игнорируемым ДО того, как его кто-то соберёт.

    Спрашивается у самого git, а не разбором `.gitignore`: свой толкователь его
    синтаксиса разошёлся бы с настоящим молча — и разошёлся бы в сторону «всё
    покрыто» (049).

    ПОЧЕМУ ЭТОГО НЕ ЛОВИТ СОСЕДНЯЯ ПРОВЕРКА. Та спрашивает «под учётом и в
    игноре одновременно», и файл, которого в игноре НЕТ, её предикату не
    подходит вовсе: пока его не закоммитили, он невидим, а после — уже поздно.
    Здесь предмет обратный и проверяется заранее. Нашёл внешний взгляд находкой
    `789055e` на #371.
    """
    path = f"{package}/{output}"
    done = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert done.returncode == 0, (
        f"{path} не покрыт `.gitignore` — это {why}, и однажды собранный он "
        f"уедет в дерево первым же `git add -A`"
    )


def declared_ignores() -> list[str]:
    """Имена производного сборки, объявленные в `.gitignore` между метками."""
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    if IGNORE_BEGIN not in lines or IGNORE_END not in lines:
        return []
    inside = lines[lines.index(IGNORE_BEGIN) + 1 : lines.index(IGNORE_END)]
    return [one.strip() for one in inside if one.strip() and not one.startswith("#")]


def test_the_declared_list_is_found_at_all() -> None:
    """Метки списка на месте: без них проверка ниже молчала бы на пустоте (075)."""
    assert declared_ignores(), (
        f"в `.gitignore` не найден список между «{IGNORE_BEGIN}» и «{IGNORE_END}» — "
        "либо метки переписали, либо список пуст, и тогда гейт ниже ничего не держит"
    )


@pytest.mark.parametrize("name", declared_ignores())
def test_every_declared_ignore_names_what_writes_it(name: str) -> None:
    """У каждого имени в списке названо, ЧТО ИМЕННО его пишет.

    Иначе сюда попадает имя «на всякий случай»: так здесь оказался `wheels/`,
    которого не пишет ни один инструмент проекта. Комментарий при этом обещал,
    что список держит гейт, — и обещание было неверным, потому что проверялась
    обратная сторона (покрыт ли путь игнором), а не эта (154, 068).

    Сверка идёт по ПЕРВОМУ сегменту пути: `build/` покрывает `build/lib/…`, а
    `*.egg-info/` — `<пакет>.egg-info/PKG-INFO`.
    """
    stem = name.rstrip("/")
    # ШИРОКИЙ ШАБЛОН ПРОХОДИЛ БЫ, НИЧЕГО НЕ НАЗВАВ. `*` совпадает с любым
    # выводом, и строка «покрыта» всем сразу — то есть не названа ничем. Проба
    # посторонним именем отвергает такой шаблон: законный (`build/`,
    # `*.egg-info/`) с ним не совпадает. Нашёл внешний взгляд находкой `e3a960f`
    # на #375.
    assert not fnmatch("совершенно-посторонний-каталог", stem), (
        f"`{name}` — шаблон настолько широкий, что совпадает с чем угодно: он "
        "«покрывает» весь список, не назвав ни одного инструмента (154)"
    )
    covered = [
        why
        for output, why in BUILD_OUTPUTS
        if fnmatch(output.split("/")[0], stem) or output.split("/")[0] == stem
    ]
    assert covered, (
        f"`{name}` объявлен игнорируемым, но в BUILD_OUTPUTS его никто не пишет — "
        "либо назовите инструмент, либо уберите строку"
    )
