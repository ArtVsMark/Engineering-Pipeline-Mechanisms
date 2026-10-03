#!/usr/bin/env python3
"""Свой прогон перед толчком: красное чинится здесь, а не по логам площадки.

ПОЧЕМУ ЭТО МЕХАНИЗМ, А НЕ СТРОКА В СВОДЕ. Правило без механизма — пожелание
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
Строка «прогоните проверки перед толчком» держится памятью окна, а память —
первое, что теряется к концу смены. Цена красного толчка названа прямо: цикл
площадки и доверие ревьюера; один проверенный толчок дешевле трёх пробных.

ЧТО ЗАПУСКАЕТСЯ, БЕРЁТСЯ ИЗ ДЕРЕВА, А НЕ ПЕРЕЧИСЛЯЕТСЯ ЗДЕСЬ ЗАНОВО. Команды
читаются из шагов `ci.yml`: второй список тех же команд разошёлся бы с первым
молча, и разошёлся бы незаметно — обе стороны выглядели бы правдоподобно
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
Поэтому добавленный в прогон гейт появляется здесь сам, а не через полгода.

ГРАНИЦА НАЗВАНА, А НЕ СГЛАЖЕНА. Часть проверок без площадки невыполнима:
атрибуция считается по истории относительно базы, разметка изменения читается у
площадки, внешний взгляд идёт чужим прогоном. Объявить их «пройденными
локально» значило бы завести тихий запасной путь
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
Невыполнимое здесь называется НЕВЫПОЛНЕННЫМ и печатается списком — это не
«пропущено», а «проверит площадка».

Исходы (правило 039): ``0`` всё зелено · ``2`` шаг не отработал ·
``3`` есть красное, толкать рано.
"""

import argparse
import hashlib
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import agent_pr
import check_agent_silenced
import check_branch_revival
import check_env
import ghrest
import gitcall
import paths
import report
import yaml

CI: Final = paths.WORKFLOWS / "ci.yml"
#: Вызов прогона ИЗ ЭТОГО ЖЕ ДЕРЕВА.
OUR_CALL: Final = "./"

#: Команда шага прогона: строка, начинающаяся с зовомого инструмента. Читается
#: список РАЗРЕШЁННОГО (068): что не узнано, то не запускается, а называется.
RUNNABLE: Final = ("ruff ", "mypy ", "pytest", "python scripts/")
#: Переменная окружения с каталогом кода конвейера у общего шага (#990): её
#: ставит общий шаг, её же ставит предполётная и читает гейт шагов.
MECHANISMS: Final = "MECHANISMS"
#: Вызов нашего кода из checkout общего шага (#990). Перед сверкой со списками
#: разрешённого и требующего площадки он приводится к прямому `python scripts/`:
#: иначе предполётная молча потеряла бы вынесенные проверки, а отложенные
#: площадкой — запускала бы (045).
#:
#: ФОРМА ОДНА, И ЭТО ПРАВИЛО, А НЕ РАЗБОР. `plain` узнаёт только её, а иную —
#: в кавычках, в скобках, через `python3`, не в начале команды — краснит гейт
#: шагов `tests/test_reusable_steps.py::test_our_script_is_called_in_the_one_form`:
#: учить предполётную каждой форме значило бы чинить потерю по одной (взгляд на
#: #997, `e803a73`).
FROM_CHECKOUT: Final = f"python ${MECHANISMS}/scripts/"
#: Подстановка площадки. Блок с ней локально не раскрывается, и запускать его
#: значит проверять не ту команду.
PLATFORM_MARK: Final = "${{"
#: Шаги, отложенные разбором с названной причиной. Заполняется КАЖДЫМ чтением
#: заново и печатается вместе с прочим невыполнимым: пропуск без имени
#: неотличим от «шага не было» (046).
#:
#: Прежде словарь копился между вызовами в одном процессе и требовал ручной
#: очистки в тесте — то есть механизм отвечал не про то дерево, которое у него
#: спросили, а про все, что он видел за жизнь процесса. Нашёл внешний взгляд
#: на #101.
UNRUNNABLE: Final[dict[str, str]] = {}
#: Шаги, которым нужна площадка: их команды сюда не берутся, а перечисляются
#: как невыполнимые. Ключ — начало команды, значение — почему.
NEEDS_PLATFORM: Final = {
    "python scripts/check_pr_meta.py": "разметку изменения читает площадка",
    "python scripts/debt.py": "долг читается из задач площадки",
    "python scripts/ci_complete.py": "опрашивает записи проверок на голове у площадки",
    # ФЕТЧ ДЕЛАЕТ СОСЕДНЯЯ СТРОКА ШАГА, А НЕ САМ СКРИПТ, и разница не
    # придирка: блок шага несёт `git fetch` с записью в
    # `refs/remotes/origin/<база>`, и запускать локально надо не скрипт, а
    # блок — то есть правку чужого дерева. Сам гейт поверхности прогоняется
    # руками (`python scripts/check_contract.py`) и базу берёт ту, что уже
    # есть. Прежняя запись приписывала фетч скрипту; нашёл внешний взгляд
    # на #123, а разбор самого шага — на #108.
    "python scripts/check_contract.py": "фетч базы делает соседняя строка шага, а не скрипт",
    # Локально канон берётся у `origin`, а он хранит написание клонировавшего:
    # регистр там не сверить, и половина гейта была бы вхолостую.
    "python scripts/check_own_name.py": "каноничное имя знает только площадка",
    # Имена правил читаются из выгрузки каталога по сети: локально её может не
    # быть, и падение говорило бы о канале, а не о ссылках.
    "python scripts/check_rule_links.py": "имена правил берутся из выгрузки каталога",
    # Нарисован ли артефакт на своей ветке, знает только площадка: в дереве его
    # нет и быть не должно — ровно в этом предмет правила 196.
    "python scripts/check_derived_refs.py": "нарисовано ли производное, знает площадка",
}


@dataclass(frozen=True, slots=True)
class Step:
    """Одна команда прогона: чем названа и что запускает."""

    name: str
    command: str
    #: Строка установки джоба, в котором стоит шаг (`pip install …`), как
    #: написана; пусто — джоб ничего не ставит. Нужна шагу типов: `mypy`
    #: видит пакеты окружения, а не только код, и их состав решает вердикт.
    installs: str = ""


#: Шаг, которому важен СОСТАВ окружения, а не только версии инструментов (#1069).
TYPES: Final = "mypy "
#: Формы вызова шага типов: сам инструмент и он же модулем интерпретатора.
TYPES_CALLS: Final = (TYPES, "python -m mypy ", "python3 -m mypy ")
#: Признак строки установки внутри блока шага.
INSTALL: Final = "pip install"
#: Где лежат окружения шагов — вне дерева проекта, по одному на строку установки.
LINT_ENVS: Final = paths.PREFLIGHT_ENVS
#: Метка завершённой сборки окружения шага: без неё окружение не готово.
READY: Final = "READY"
#: Срок окружения шага, секунд: площадка разрешает диапазоны в каждом прогоне.
ENV_MAX_AGE: Final = 24 * 3600


#: Проверки ПЕРЕД ТОЛЧКОМ, которых нет шагом прогона ни у кого. Это не второй
#: список тех же команд (022): в `ci.yml` их нет вовсе, потому что предмет у
#: них — ветка до открытия изменения. Приставка ветки и связь с задачей видны
#: на дереве целиком, а ловились до сих пор отказом `agent-pr` — то есть уже
#: после толчка. Замер 10.09.2026: три ветки подряд ушли без связи, и каждая
#: вернулась ни с чем: изменение не открылось, красного тоже не было.
BEFORE_PUSH: Final = (Step("ветка откроет изменение", "python scripts/agent_pr.py --dry-run"),)

#: Проверки прогона, у которых здесь нет команды вовсе: они живут не шагом с
#: командой, а действием площадки или чужим прогоном.
ELSEWHERE: Final = {
    "attribution": "считается по истории относительно базы изменения",
    "ci-complete": "опрашивает записи проверок на голове у площадки",
    "review": "идёт отдельным прогоном и чужим исполнителем",
    "automerge": "это само слияние, а не проверка перед ним",
}

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_RED: Final = 3


class NotRun(RuntimeError):
    """Шаг не отработал: третий исход, а не «всё зелено»."""


def _jobs_of(job: dict[str, Any], caller: Path) -> list[list[dict[str, Any]]]:
    """Шаги джоба — свои либо шаги прогона, который он зовёт, ПО ДЖОБАМ.

    Вызванный прогон отдаёт свои джобы порознь, а не одним списком: строка
    установки живёт в пределах джоба, и общий список отдал бы строку одного
    джоба шагу следующего (находка `daee131` на #1073).

    Адрес вызова отсчитывается от корня дерева, а не от каталога прогонов, и
    остаётся СТРОКОЙ: `Path("./x")` нормализует ведущее `./` прочь, и признак
    «свой вызов» переставал бы срабатывать. Чужой вызов раскрыть нечем — его
    прогона в дереве нет, — и он называется невыполнимым, а не пропускается
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
    """
    said = str(job.get("uses") or "")
    if not said:
        return [list(job.get("steps") or [])]
    if not said.startswith(OUR_CALL):
        UNRUNNABLE[said] = "вызов чужого прогона: его шагов в дереве нет"
        return []
    # КОРЕНЬ ВЫВОДИТСЯ ИЗ ОБЪЯВЛЕННОГО ПУТИ, А НЕ ПОДЪЁМОМ ПО ДЕРЕВУ: подъём
    # угадывал бы глубину, на которой лежат прогоны, и соврал бы молча, изменись
    # она. Запрет держит `tests/test_settings_anchor.py`, он же это и назвал —
    # второй раз за смену, тем же приёмом, что у разбора состава проверок.
    tail = str(paths.WORKFLOWS)
    said_caller = str(caller.parent)
    if not said_caller.endswith(tail):
        raise NotRun(
            f"каталог прогонов «{said_caller}» не оканчивается объявленным «{tail}» — "
            "корень дерева из него не выводится (075)"
        )
    where = Path(said_caller[: -len(tail)] or ".") / said[len(OUR_CALL) :].split("@")[0]
    if not where.is_file():
        raise NotRun(f"вызов «{said}» указывает на прогон, которого в дереве нет (075)")
    called = yaml.safe_load(where.read_text(encoding="utf-8"))
    if not isinstance(called, dict):
        raise NotRun(f"{where}: вызываемый прогон не разбирается")
    return [list((inner or {}).get("steps") or []) for inner in (called.get("jobs") or {}).values()]


def steps(path: Path = CI) -> list[Step]:
    """Команды прогона, выполнимые без площадки, — в порядке объявления.

    Разбор идёт по ДЕРЕВУ, а не по строкам, и это не вкус. Команда шага живёт в
    блоке `run:` вместе с оболочечной обвязкой — `set -euo pipefail`,
    подготовкой базы, `git fetch`, — и строка, выдернутая из середины такого
    блока, запускается без неё. Итог выглядит как проверка, а проверяет другое:
    зелёное там, где площадка краснеет, и наоборот
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Замер — находка ревью по #94.

    Поэтому берётся ВЕСЬ блок шага, и берётся он целиком либо не берётся вовсе.

    ВЫЗОВ РАСКРЫВАЕТСЯ, А НЕ ПРОПУСКАЕТСЯ. Джоб, зовущий переиспользуемый прогон
    (`uses: ./…`), своих шагов не имеет — они лежат в вызываемом. Разбор,
    читающий один файл, потерял бы их МОЛЧА: предполётная обещает «площадка
    скажет то же», и тихо уменьшившийся список превращает обещание в ложь
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Первый же вынос восьми шагов это и показал: зелёное осталось зелёным,
    проверив вдвое меньше.
    """
    if not path.is_file():
        raise NotRun(f"нет {path}: список проверок взять неоткуда (075)")

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise NotRun(f"{path} не разбирается: {exc}") from exc
    if not isinstance(document, dict):
        raise NotRun(f"{path}: ожидалось отображение, пришло {type(document).__name__}")

    # Чтение начинается с чистого листа: отложенное относится к ЭТОМУ дереву.
    UNRUNNABLE.clear()
    found: list[Step] = []
    seen: set[str] = set()
    jobs = [
        inner
        for job in (document.get("jobs") or {}).values()
        for inner in _jobs_of(job or {}, path)
    ]
    for job_steps in jobs:
        # Строка установки — ПОСЛЕДНЯЯ перед шагом в его джобе: так её видит
        # площадка, ставящая окружение раньше команд (#1069). Джобы вызванного
        # прогона приходят порознь (`_jobs_of`), и строка одного не достаётся
        # шагу другого.
        installs = ""
        for step in job_steps:
            command = str((step or {}).get("run") or "").strip()
            name = str((step or {}).get("name") or "").strip()
            if INSTALL in command:
                installs = command
            if not command or command in seen:
                continue
            lines = [plain(line) for line in command.splitlines()]
            if not any(line.startswith(RUNNABLE) for line in lines):
                continue
            # Площадка нужна блоку целиком, если её требует ХОТЯ БЫ одна его
            # строка: запустить остальное без неё значит проверить половину и
            # назвать это проверкой.
            if any(line.startswith(prefix) for line in lines for prefix in NEEDS_PLATFORM):
                continue
            if PLATFORM_MARK in command:
                # Подстановка площадки локально не раскрывается: запустить блок
                # с ней значит проверить не ту команду. Названо, а не выкинуто
                # молча (046) — такие шаги перечисляет `report_gaps`.
                UNRUNNABLE[name or command] = "в команде подстановка площадки"
                continue
            seen.add(command)
            found.append(Step(name or command.splitlines()[0], command, installs))

    if not found:
        raise NotRun(f"{path}: ни одной выполнимой команды не нашлось — предмет не найден (075)")
    return found


def plain(line: str) -> str:
    """Строка команды без отступа, вызов из checkout — как прямой (#990)."""
    line = line.strip()
    return (
        "python scripts/" + line[len(FROM_CHECKOUT) :] if line.startswith(FROM_CHECKOUT) else line
    )


def environment() -> dict[str, str]:
    """Окружение прогона: инструменты берутся оттуда же, откуда запущен механизм.

    Иначе `pytest` и `ruff` придут из системного пути — то есть с ДРУГИМ
    интерпретатором, чем тот, на котором окно собиралось их гонять. Ровно этот
    разрыв и ловит `check_env.py`, и повторять его внутри своего же прогона
    значило бы проверять не то окружение (022).
    """
    where = str(Path(sys.executable).parent)
    room = dict(os.environ)
    room["PATH"] = where + os.pathsep + room.get("PATH", "")
    return room


def packages_of(installs: str) -> list[str]:
    """Пакеты строки установки, как их ставит площадка; флаги `pip` отброшены.

    Путь к дереву (`$MECHANISMS/…`, `./…`) отдаётся отказом: окружение
    шага собирается вне дерева, и путь, ставший бы здесь пакетом, был бы ДРУГИМ
    кодом, чем у площадки (045). Шаг типов на площадке пакетов дерева не
    ставит; встретится такой — предел станет виден, а не съеден.
    """
    line = next((one for one in installs.splitlines() if INSTALL in one), "")
    words = shlex.split(line.partition(INSTALL)[2])
    found = [word for word in words if not word.startswith("-")]
    tree = [word for word in found if "/" in word or word.startswith(("$", "."))]
    if tree:
        raise NotRun(
            f"строка установки шага ставит пакеты дерева {tree} — собрать её вне дерева нечем"
        )
    if not found:
        raise NotRun(f"в строке установки «{line.strip()}» пакетов нет (075)")
    return found


def env_dir(installs: str, root: Path) -> tuple[Path, str]:
    """Каталог окружения шага и то, из чего собран его ключ.

    Интерпретатор окна — в ключе: после смены Python прежнее окружение
    собрано другим, и `--python-executable` указал бы на него (`64dd097`).
    """
    said = " ".join([sys.executable, platform.python_version(), *packages_of(installs)])
    return root / LINT_ENVS / hashlib.sha1(said.encode()).hexdigest()[:12], said


def lint_python(installs: str, root: Path) -> Path:
    """Интерпретатор окружения того же СОСТАВА, что у шага на площадке (#1069).

    ЗАМЕР 03.10.2026, #1063. Шаг `lint` ставит `ruff`, `mypy` и `pyyaml`, а
    `.venv` окна несёт ещё и `pytest`. `mypy` видит пакеты окружения: с
    `pytest` вызов `pytest.skip` — `NoReturn`, без него — `Any`, и функция,
    кончающаяся этим вызовом, на площадке краснела «Missing return statement»,
    а здесь предполётная давала «зелено». Версии инструментов сверял
    `check_env` — состав не сверял никто.

    Окружение собирается на строку установки И интерпретатор окна — ключ их
    отпечаток — в `LINT_ENVS` под корнем дерева. Сбор не удался (сети нет) —
    отказ с названной причиной, а не тихий `mypy` в `.venv`: это было бы ровно
    то зелёное, от которого механизм заведён (045).

    ГОТОВО ТОЛЬКО ТО, ЧТО СБОРКА ОБЪЯВИЛА ГОТОВЫМ. Прежде признаком был
    `bin/python`, а его оставляет и сборка, упавшая на `pip install`: второй
    заход брал пустое окружение за готовое (находки `567ad6d`, `55c6ddd`,
    `0f379a2`). Метку `READY` пишет только завершившаяся сборка; нет метки —
    каталог стирается и собирается заново.

    СРОК — СУТКИ. Площадка разрешает диапазоны пакетов заново в каждом
    прогоне, а окружение окна застыло бы на первом разрешении навсегда
    (`793ebcd`). Сутки — компромисс: пересборка стоит секунды, а выход нового
    `mypy` в пределах диапазона окно увидит не позже следующего дня. Предел
    назван: в эти сутки состав может разойтись с площадкой.
    """
    packages = packages_of(installs)
    where, said = env_dir(installs, root)
    python = where / "bin" / "python"
    ready = where / READY
    if ready.is_file() and time.time() - ready.stat().st_mtime < ENV_MAX_AGE:
        return python
    shutil.rmtree(where, ignore_errors=True)
    for command in (
        [sys.executable, "-m", "venv", str(where)],
        [str(python), "-m", "pip", "install", "--quiet", *packages],
    ):
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            raise NotRun(
                f"окружение шага типов не собрано ({' '.join(command[:4])}…): "
                f"{(done.stderr or done.stdout).strip()[-300:]}"
            )
    ready.write_text(said + "\n", encoding="utf-8")
    return python


def types_call(line: str) -> str | None:
    """Форма вызова `mypy`, которой начинается строка, или ``None``.

    Один предикат на подстановку и на её проверку: тест искал шаг подстрокой
    `"mypy " in command`, а подстановка — началом строки, и шаг вида
    `python -m mypy …` тест видел, а подстановка нет (находка `f875389`).
    """
    said = line.strip()
    return next((call for call in TYPES_CALLS if said.startswith(call)), None)


def as_on_the_platform(step: Step, root: Path) -> str:
    """Команда шага в окружении площадки: `mypy` смотрит пакеты окружения шага (#1069).

    Подставляется ровно `--python-executable` — ключ самого `mypy`, по
    которому он ищет пакеты в чужом интерпретаторе. Инструменты и код остаются
    прежними, меняется только то, что `mypy` видит установленным. Прочих
    шагов это не касается, и предел назван: `pytest` и `ruff` состав окружения
    в вердикт не берут так, как берёт `mypy`, а импорты шагов держит
    `test_workflow_installs_what_its_scripts_import`.
    """
    if not step.installs or not any(types_call(line) for line in step.command.splitlines()):
        return step.command
    python = lint_python(step.installs, root)
    lines = []
    for line in step.command.splitlines():
        call = types_call(line)
        lines.append(
            line.replace(call, f"{call}--python-executable {shlex.quote(str(python))} ", 1)
            if call
            else line
        )
    return "\n".join(lines)


def run(step: Step, root: Path) -> tuple[int, str]:
    """Запускает команду шага и отдаёт код с выводом."""
    try:
        command = as_on_the_platform(step, root)
    except NotRun as exc:
        return EXIT_BROKEN, f"шаг не отработал: {exc}"
    done = subprocess.run(
        command,
        shell=True,
        # ОБОЛОЧКА ТА ЖЕ, ЧТО У ПЛОЩАДКИ. Умолчание `shell=True` — `/bin/sh`, а
        # площадка запускает шаги в bash: `set -o pipefail` в sh не понят, и
        # здоровый шаг краснел здесь с «Illegal option». Прогон, идущий другой
        # оболочкой, проверяет не то, что проверит площадка (022).
        executable="/bin/bash",
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        # КОД КОНВЕЙЕРА ЛОКАЛЬНО — ЭТО ДЕРЕВО. На площадке общий шаг берёт его
        # своим checkout на коммите вызова (#990); здесь проверяется дерево, в
        # котором лежит и код.
        env={**environment(), MECHANISMS: str(root.resolve())},
    )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def report_gaps() -> None:
    """Называет то, что здесь проверить нечем, — списком, а не молчанием."""
    print("\nчего этот прогон не проверяет (проверит площадка):")
    for name, why in UNRUNNABLE.items():
        print(f"  {name} — {why}")
    for command, why in NEEDS_PLATFORM.items():
        print(f"  {command} — {why}")
    for check, why in ELSEWHERE.items():
        print(f"  {check} — {why}")


def say_the_look_is_silenced(root: Path) -> None:
    """Называет тишину взгляда — НА КАЖДОМ заходе, а не только перед толчком.

    ЗДЕСЬ БЫЛ ДЕФЕКТ, И НАШЁЛ ЕГО ВНЕШНИЙ ВЗГЛЯД (`8fb329e`, #616). Вызов
    стоял внутри `push_branch`, то есть срабатывал ТОЛЬКО при `--push`. А
    предполётную зовут и без него — посмотреть, что скажет площадка, — и
    именно в этом заходе предупреждение нужнее всего: до толчка ещё можно
    решить, разводить ли правку файла прогона отдельным изменением.
    Предупреждение, достижимое одним путём из двух, для второго пути не
    существует
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

    ОТКАЗ КАНАЛА НЕ ДЕРЖИТ ЗАХОД, НО И НЕ МОЛЧИТ: непроверенное называется
    непроверенным, а не «чисто»
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    try:
        # ОБЩАЯ ВЕТКА НАЗВАНА ОДНИМ ИСТОЧНИКОМ, а не строкой здесь: с чем
        # сравнивает площадка, знает `paths.TRUNK`, и второе написание того же
        # разошлось бы с первым молча (022).
        verdict, about = check_agent_silenced.look(root, f"origin/{paths.TRUNK}")
    except (check_agent_silenced.NotRun, OSError) as exc:
        print(f"тишина взгляда не проверена: {report.cut(str(exc))}", file=sys.stderr)
        return
    if verdict == check_agent_silenced.EXIT_SILENCED:
        print(about, file=sys.stderr)


def branch_now(root: Path) -> str:
    """Имя текущей ветки — из дерева, а не из памяти зовущего."""
    try:
        said = gitcall.output(
            ["rev-parse", "--abbrev-ref", "HEAD"], NotRun, cwd=str(root) if root else None
        )
    except NotRun as exc:
        raise NotRun(f"ветка не прочитана: {exc}") from exc
    return said.strip()


def push_branch(root: Path) -> int:
    """Толкает текущую ветку — и зовётся ТОЛЬКО после зелёного вердикта.

    ВЕРДИКТ, КОТОРЫЙ ЧИТАЕТ ТОТ ЖЕ, КТО ДЕЙСТВУЕТ, — НЕ МЕХАНИЗМ, А
    НАПОМИНАНИЕ. Проверка перед толчком считала своё дело сделанным, напечатав
    «толкать рано»: держать толчок ей было нечем, а толкал тот же, кто её и
    запускал. Замер 17.09.2026: за смену ТРИ толчка из примерно пятнадцати ушли
    при красном вердикте — и каждый раз вердикт был напечатан на экран тем же
    заходом, что и толчок. Вреда не вышло только потому, что ветки были новыми,
    и каждый раз это ловил человек, а не механизм.

    ЗДЕСЬ ПРОВЕРКА И ДЕЙСТВИЕ СТАЛИ ОДНИМ ЗАХОДОМ. Красное просто не доходит до
    этой строки: толкать нечем, а не «не следует».

    ВТОРОЙ ЗАПРЕТ ЗДЕСЬ — ВОСКРЕШЕНИЕ СЛИТОЙ ВЕТКИ, и он спрашивает ПЛОЩАДКУ.
    Сторож перед git ловит тот же случай локальными ссылками и потому устаревает
    до первого фетча; 19.09.2026 он ровно поэтому и не сработал. Отказ ставится
    на ДОСТОВЕРНОМ — слитое изменение по этой же голове, — а отказ канала и
    отсутствие токена толчок не держат: блокировать на вероятном значит учить
    обходить проверку
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

    ЧЕГО ЭТО НЕ ДЕЛАЕТ: не мешает толкнуть руками. Запретить `git push` проект
    не может и не должен — обход законен, когда он назван (154), а неназванный
    обход стоил ровно тех трёх раз.
    """
    branch = branch_now(root)
    # ПРИСТАВКА — ПЕРЕКЛЮЧАТЕЛЬ, И ПРОВЕРЯЕТСЯ ОНА, А НЕ ДВА ИМЕНИ. Первая
    # редакция отвергала `main` и `HEAD` — и пропускала всё остальное, включая
    # `claude/<окно>`, ветку, которую окну выдаёт площадка. Толчок туда
    # изменения НЕ ОТКРОЕТ: приставку читает `agent-pr`, — то есть работа
    # уезжала в никуда, а заход рапортовал успех. Сообщение при этом ссылалось
    # на 003 и проверяло не то, о чём 003 говорит. Нашёл внешний взгляд на #433.
    #
    # СПИСОК ПРИСТАВОК БЕРЁТСЯ У ТОГО, КТО ПО НЕМУ И РЕШАЕТ (`agent_pr`), а не
    # пишется здесь второй копией: разъехавшись, они дали бы худший из отказов —
    # толчок прошёл, изменение не открылось, красного нет нигде (022, 090).
    if not branch.startswith(agent_pr.PREFIXES):
        print(
            f"толчок не сделан: ветка «{branch}» без приставки "
            f"{' или '.join(agent_pr.PREFIXES)} — изменения по ней не откроется (003)",
            file=sys.stderr,
        )
        return EXIT_BROKEN
    try:
        verdict, about = check_branch_revival.look(root, branch)
    except (check_branch_revival.NotRun, ghrest.TransportError, OSError) as exc:
        # ОТКАЗ КАНАЛА ТОЛЧОК НЕ ДЕРЖИТ, НО И НЕ МОЛЧИТ. Площадка бывает
        # недоступна, а красное, которое чинится ожиданием, учат обходить (051).
        print(f"воскрешение ветки не проверено: {report.cut(str(exc))}", file=sys.stderr)
    else:
        print(about, file=sys.stderr if verdict else sys.stdout)
        if verdict == check_branch_revival.EXIT_REVIVED:
            return EXIT_BROKEN
    # СВОЯ ФОРМА, А НЕ `gitcall`: вывод толчка печатается целиком и при
    # успехе, а отказ — код выхода, а не исключение. Отсутствие git ловится
    # здесь же, у самого вызова (#1027).
    try:
        said = subprocess.run(
            ["git", "push", "-u", "origin", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=root or None,
        )
    except OSError as exc:
        print(f"толчок не прошёл: git не запустился — {exc}", file=sys.stderr)
        return EXIT_BROKEN
    print(said.stdout.rstrip() or said.stderr.rstrip())
    if said.returncode != 0:
        print(f"толчок не прошёл: {report.cut(said.stderr.strip())}", file=sys.stderr)
        return EXIT_BROKEN
    print(f"толкнуто: {branch}")
    return EXIT_OK


def environment_gap(root: Path) -> list[str]:
    """Чем окружение окна расходится с тем, что ставит прогон, — или пусто.

    ШОВ ЗДЕСЬ ЗАВЕДЁН НАРОЧНО, наравне с `steps` и `run`: прогоны вердикта
    подменяют соседей и судят ОТНОШЕНИЕ «красное → не толкаем», а не состав
    чужой машины. Без шва три таких прогона стали бы зависеть от того, стоит ли
    у запустившего `mypy`, — и краснели бы на матричной ячейке площадки, где его
    нет
    ([150](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/150-a-test-asks-the-mechanism-not-its-condition.md)).

    СВЕРКА ИДЁТ ТОЛЬКО ДЛЯ СВОЕГО ДЕРЕВА. Она отвечает на вопрос «предскажет ли
    зелёное площадку», а площадка есть у ОДНОГО дерева — того, в котором лежит
    сама предполётная. На синтетическом корне сверка сравнивала бы установленное
    у запустившего с объявлениями чужого дерева
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).

    СВОЁ ДЕРЕВО УЗНАЁТСЯ ЧЕРЕЗ ЯКОРЬ, а не ходом вверх: `.parent.parent` краснел
    бы у гейта поиска вверх по дереву — и краснел бы ЛОЖНО, потому что предмет
    того гейта розыск настройки, а тут вычисляется собственный корень. Обходить
    чужой гейт формулировкой нельзя, поэтому ход вверх снят вовсе (115, 051).
    """
    here = Path(__file__).resolve().parent
    # СРАВНИВАЕТСЯ ОДИН КАТАЛОГ, И ЭТО НЕ СУЖЕНИЕ. Прежде перебирались оба
    # источника дерева (`scripts` и `packages/transport`), но `here` — каталог
    # ЭТОГО файла, а предполётная лежит в `scripts/` и нигде больше: ветка с
    # транспортом не могла совпасть ни при каком корне. Перебор по двум читался
    # как «проверяем оба», хотя проверял один, — мёртвая ветка, и нашёл её
    # внешний взгляд (`74e5cd3`). Переедет предполётная — сравнение переедет
    # вместе с ней, потому что адрес берётся у самого файла.
    if (root / paths.SCRIPTS).resolve() != here:
        # МОЛЧАТЬ ОБ ЭТОМ НЕЛЬЗЯ: пропущенная сверка и сошедшаяся снаружи
        # одинаковы, и зелёное ниже говорит тогда меньше, чем кажется (045).
        print(
            f"окружение НЕ сверено: корень {root} — не то дерево, в котором лежит"
            " предполётная, и объявления в нём про чужую площадку",
            file=sys.stderr,
        )
        return []
    try:
        return check_env.survey(root).problems
    except (check_env.NotRun, OSError, ValueError) as exc:
        # Дерево без строк установки бывает: так выглядит синтетический корень.
        print(f"окружение НЕ сверено: {exc}", file=sys.stderr)
        print(
            "  зелёное ниже говорит только о дереве, но не о том, что площадка скажет то же.",
            file=sys.stderr,
        )
        return []


def main(argv: list[str] | None = None) -> int:
    """Точка входа: прогоняет проверки дерева и объявляет исход."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень дерева")
    parser.add_argument("--list", action="store_true", help="только показать, что будет запущено")
    parser.add_argument(
        "--push",
        action="store_true",
        help="толкнуть текущую ветку, ЕСЛИ зелено: проверка и действие одним заходом",
    )
    args = parser.parse_args(argv)

    # ОКРУЖЕНИЕ СВЕРЯЕТСЯ ДО ВСЕГО, И ЭТО НЕ ФОРМАЛЬНОСТЬ. Зелёная предполётная
    # обещает ровно одно: «площадка скажет то же». Обещание держится, пока
    # инструменты окна тех же версий, что ставит прогон, — иначе проверено было
    # ДРУГОЕ, и зелёное здесь ничего не предсказывает
    # ([073](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/073-tool-version-from-one-source-with-an-upper-bound.md)).
    #
    # ЗАМЕР 18.09.2026, ИЗ-ЗА КОТОРОГО ШАГ И ПОЯВИЛСЯ: окно гоняло mypy 2.3.1
    # при объявленных `>=1.11,<2`, предполётная давала «зелено: 18», а площадка
    # краснела на шаге типов. Сверка окружения лежала рядом (`check_env.py`) и
    # не звалась ничем — то есть существовала, а работала по памяти (002).
    if not args.list:
        gap = environment_gap(args.root)
        if gap:
            print("окружение окна расходится с тем, что ставит прогон:")
            for line in gap:
                print(f"  {line}")
            print(
                "\nпредполётная НЕ ЗАПУЩЕНА: её зелёное предсказывало бы площадку"
                " только на тех же версиях."
                "\nПоставьте объявленные границы — `python scripts/check_env.py`"
                " печатает команду — и повторите."
            )
            return EXIT_BROKEN

    say_the_look_is_silenced(args.root)

    try:
        # Проверки ветки идут ПЕРВЫМИ: их предмет — то, откроется ли изменение
        # вообще, и красное здесь делает остальное бессмысленным.
        found = [*BEFORE_PUSH, *steps(args.root / CI)]
    except NotRun as exc:
        print(f"шаг не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if args.list:
        for step in found:
            print(f"{step.name}: {step.command}")
        report_gaps()
        return EXIT_OK

    red: list[Step] = []
    for step in found:
        code, output = run(step, args.root)
        print(f"{'✓' if code == 0 else '✗'} {step.name}: {step.command}")
        if code != 0:
            red.append(step)
            print(output.rstrip())

    report_gaps()
    if red:
        print(f"\nкрасных проверок: {len(red)} — толкать рано, чинится здесь:")
        for step in red:
            print(f"  {step.name}: {step.command}")
        return EXIT_RED
    print(f"\nзелено: {len(found)} проверок дерева прошли")
    if args.push:
        return push_branch(args.root)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
