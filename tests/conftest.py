"""Общее для тестов: корень репозитория и запуск скриптов как процессов."""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Версия для ПОДДЕЛОК в проверках. Настоящая живёт в `CONTRACT_VERSION`, и
#: любое совпадение с ней ловит гейт «версия не правится руками»: он видит
#: число в дереве и не знает, что это фикстура. За одну смену 10.09.2026 на
#: этом попались трижды — поэтому подделки берут заведомо чужой номер, а
#: `test_conftest_fixture_version.py` держит, что он останется чужим.
FAKE_VERSION = "9.9.0"


def history_is_whole() -> bool:
    """Виден ли в этом чекауте релизный тег — то есть пришла ли история.

    Проверки, которые идут по ЖИВОМУ дереву, осмысленны только там, где дерево
    целое. `actions/checkout` без `fetch-depth: 0` тегов не приносит, и такой
    чекаут есть у канала ревью: он читает диф, а не историю. Падение проверки
    там говорило бы о площадке, а не о механизме, — а красное, называющее не
    свою причину, учит не смотреть на красное (`045`).

    Что вход полон там, где это нужно, держит не эта функция, а гейт
    `version.py --check` в прогоне: он падает на неполной истории вслух.
    """
    return bool(
        subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*.[0-9]*.[0-9]*"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
        ).returncode
        == 0
    )


#: Пометка для проверок по живой истории: обрезанный чекаут — не их предмет.
needs_history = pytest.mark.skipif(
    not history_is_whole(),
    reason="чекаут без тегов: история не пришла, живую версию считать не из чего",
)


@dataclass(frozen=True, slots=True)
class Run:
    """Результат прогона скрипта: код возврата и оба потока."""

    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        """Оба потока разом — исход печатается в любой из них."""
        return self.out + self.err


RunScript = Callable[..., "Run"]


#: Ключ, которым заход объявляет себя ЗАМЕРОМ покрытия. Пусто — обычный
#: прогон, и никакой счётчик не поднимается: платить за измерение на каждом
#: заходе незачем.
MEASURING: Final = "COVERAGE_SUBPROCESS"


def under_counter(script: Path, args: tuple[str, ...]) -> list[str]:
    """Команда запуска механизма — при замере обёрнутая счётчиком покрытия.

    ПОЧЕМУ ЭТО ВООБЩЕ НУЖНО. Гейты этого проекта проверяются ЗАПУСКОМ: тест
    зовёт модуль отдельным процессом и смотрит исход. Счётчик покрытия
    подпроцессов не видит, и четыре полностью проверенных модуля показывали
    ноль при семнадцати вызовах из набора — то есть число, на котором собрались
    строить порог, было ложным
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).

    ПОЧЕМУ ОБЁРТКОЙ, А НЕ ПОДМЕНОЙ ЗАПУСКА PYTHON. Обычный приём — положить
    `.pth` в каталог пакетов и поднимать счётчик у КАЖДОГО процесса — правит
    чужое дерево и работает молча: сломается — никто не заметит. Здесь замер
    объявлен ключом, виден в команде и выключен по умолчанию.

    `--parallel-mode` обязателен: процессов много, и без него они переписывали
    бы один файл данных друг за другом. Сводит их `coverage combine`.
    """
    plain = [sys.executable, str(script), *args]
    if not os.environ.get(MEASURING):
        return plain
    return [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--parallel-mode",
        f"--source={ROOT / 'scripts'}",
        str(script),
        *args,
    ]


@pytest.fixture
def run_script() -> RunScript:
    """Запускает скрипт проекта отдельным процессом, как это делает прогон."""

    def _run(
        script: str,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> Run:
        environment = dict(os.environ)
        # Файл данных — АБСОЛЮТНЫЙ: тесты бегают в своих временных каталогах, и
        # относительное имя завело бы по файлу на каталог, а свести их потом
        # было бы нечем.
        if environment.get(MEASURING):
            environment["COVERAGE_FILE"] = str(ROOT / ".coverage")
        if env is not None:
            for key, value in env.items():
                if value == "":
                    environment.pop(key, None)
                else:
                    environment[key] = value
        completed = subprocess.run(
            under_counter(ROOT / "scripts" / script, args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd or ROOT,
            env=environment,
        )
        return Run(completed.returncode, completed.stdout, completed.stderr)

    return _run


#: Значок в витрине: имя внутри ЦЕЛИ КАРТИНКИ `![подпись](…/badges/<имя>.svg)`.
#: ПОКАЗАН — ЭТО КАРТИНКА, А НЕ УПОМИНАНИЕ АДРЕСА. Два гейта витрины мерили
#: «показан ли значок» вхождением имени файла в текст README, и проза этому
#: предикату удовлетворяет: строка «собирает `facts.json` и `rules.svg` на
#: каждое слияние» держала проверку зелёной при снятой картинке. Поймано
#: откатом 17.09.2026
#: ([146](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/146-a-green-gate-does-not-verify-its-premise.md)).
#:
#: ТОГДАШНЯЯ ПОЧИНКА СУЗИЛА ПОДСТРОКУ, А НЕ СДЕЛАЛА ЕЁ ССЫЛКОЙ: признак стал
#: `badges/<имя>.svg` вместо `<имя>.svg` — и остался подстрокой, которой проза
#: удовлетворяет так же. Замер откатом 18.09.2026: картинка покрытия снята,
#: имя оставлено в обратных кавычках — оба гейта ЗЕЛЕНЫ. Всякая проверка
#: ОТНОШЕНИЯ через присутствие подстроки зеленеет там, где отношения нет
#: ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
#:
#: Предикат здесь ОДИН на всех спрашивающих: их трое, и прежде он был у каждого
#: свой — двое мерили подстрокой, третий адресом (022, 049).
BADGE_IN_SHOWCASE: Final = re.compile(r"!\[[^\]]*\]\([^)\s]*badges/(?P<name>[\w.-]+\.svg)[^)\s]*\)")


def badges_shown(readme: str) -> set[str]:
    """Значки, которые витрина ПОКАЗЫВАЕТ: имена в цели картинки, а не в прозе."""
    return set(BADGE_IN_SHOWCASE.findall(readme))


def names_used(path: Path) -> set[str]:
    """Имена, которые исходник УПОТРЕБЛЯЕТ, — обе формы записи разом.

    `token_from_env(...)`, `env.token_from_env(...)`, `from x import
    token_from_env` — одно употребление, записанное по-разному. Поиск подстроки
    видит их все одинаково и потому видит ещё и слово в докстроке; разбор видит
    ровно употребление
    ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).

    ОТБОР ФАЙЛОВ ПОДСТРОКОЙ ОПАСНЕЕ ПРЕДИКАТА. Промах предиката краснеет;
    промах отбора выбрасывает файл из проверки МОЛЧА, и гейт остаётся зелёным,
    ничего не проверив
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            # ОБА ИМЕНИ, А НЕ ОДНО ИЗ ДВУХ. `from x import имя as другое`
            # употребляет ОБА: `имя` — у соседа, `другое` — здесь. Прежде
            # бралось `asname or name`, и настоящее имя терялось: файл,
            # импортирующий механизм под псевдонимом, выпадал из отбора МОЛЧА, а
            # промах отбора опаснее промаха предиката — гейт остаётся зелёным,
            # ничего не проверив (045). Нашёл внешний взгляд (`71621f8`).
            # Замер 19.09.2026: таких импортов в дереве ноль, то есть правится
            # расхождение обещания с механизмом, а не найденный пропуск (002).
            for alias in node.names:
                found.add(alias.name)
                if alias.asname:
                    found.add(alias.asname)
    return found


def string_args_of(path: Path, called: str) -> list[str]:
    """Строковые доводы каждого вызова `called` — обе формы имени.

    Заменяет образец по тексту: `load_script("paths.py")` и
    `helpers.load_script('paths.py')` — один вызов, а кавычка и точка к делу не
    относятся.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        head = node.func
        name = head.attr if isinstance(head, ast.Attribute) else getattr(head, "id", "")
        if name != called:
            continue
        found += [
            one.value
            for one in node.args
            if isinstance(one, ast.Constant) and isinstance(one.value, str)
        ]
    return found


def walk(where: Path, pattern: str = "*", *, may_be_empty: str = "") -> list[Path]:
    """Обход дерева, который ОТКАЗЫВАЕТ на пустоте, — или принимает её с причиной.

    ПУСТОЙ ОБХОД — САМАЯ ТИХАЯ ИЗ ПОЛОМОК. Проверка, идущая по списку из дерева,
    при пустом списке проходит все свои утверждения ноль раз и зеленеет: снаружи
    она неотличима от прошедшей. Переименуй каталог, смени расширение, перенеси
    механизмы — и гейт перестанет проверять что-либо, не сказав ни слова
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

    ПОЧЕМУ ОБЩИЙ ОБХОДЧИК, А НЕ ПРЕДИКАТ ПО ТЕКСТУ. Признак «непустота где-то
    утверждается» пробовался и ОТВЕРГНУТ замером 19.09.2026: он назвал семь
    подозрительных, из которых три были ложными — непустота там утверждается
    ПРОИЗВОДНЫМ именем, а не самим обходом. Отличить одно от другого предикатом
    значит повторить суждение о смысле
    ([057](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/057-unmechanizable-rules-are-named-explicitly.md)).
    Обходчик же не судит текст: он просто не отдаёт пустоту молча.

    ПУСТОТА БЫВАЕТ ЗАКОННОЙ, И ТОГДА У НЕЁ ЕСТЬ ПРИЧИНА. `may_be_empty` — не
    выключатель, а место, где причина записана рядом с обходом: «выпусков ещё не
    было», «расширение .yaml в дереве не встречается». Молчаливое исключение
    неотличимо от недосмотра
    ([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    if not where.is_dir():
        raise AssertionError(
            f"обход {where}/{pattern}: такого каталога нет — предмет проверки не найден (075)"
        )
    found = sorted(where.glob(pattern))
    if not found and not may_be_empty:
        raise AssertionError(
            f"обход {where}/{pattern} не нашёл ничего — проверка прошла бы ноль раз и"
            " зеленела (075).\n  Каталог переименован или образец устарел — поправьте"
            " обход.\n  Если пустота ЗАКОННА, назовите причину: walk(..., may_be_empty=«…»)"
        )
    return found


def walk_deep(where: Path, pattern: str = "*", *, may_be_empty: str = "") -> list[Path]:
    """То же, но вглубь: `rglob` вместо `glob`.

    Заведён отдельным именем, а не доводом: «вглубь или нет» — это ДРУГОЙ обход,
    и читатель вызова должен видеть его, не заглядывая в доводы.
    """
    if not where.is_dir():
        raise AssertionError(
            f"обход {where}/**/{pattern}: такого каталога нет — предмет не найден (075)"
        )
    found = sorted(where.rglob(pattern))
    if not found and not may_be_empty:
        raise AssertionError(
            f"обход {where}/**/{pattern} не нашёл ничего — проверка прошла бы ноль раз"
            " и зеленела (075).\n  Если пустота ЗАКОННА, назовите причину:"
            " walk_deep(..., may_be_empty=«…»)"
        )
    return found


def found_by(where: Path, pattern: str) -> list[Path]:
    """Обход-ВОПРОС: «есть ли такое?» — и пустота здесь есть ОТВЕТ, а не поломка.

    Третье имя рядом с :func:`walk` и :func:`walk_deep` заведено замером, а не
    для удобства. Обходы в наборе двух пород, и различает их не форма, а то,
    ЧЕМ для вызывающего является пустой ответ:

    * у :func:`walk` пустота — обрыв: предмет проверки исчез, и проверка прошла
      бы ноль раз;
    * здесь пустота — сам результат: «адрес, названный ответом, в дереве не
      разрешается», «производного в общей ветке нет». Требовать от такого обхода
      непустоты значило бы требовать, чтобы ответ всегда был «да».

    Порода объявляется В ТОЧКЕ ВЫЗОВА и потому видна читателю; разбирать её по
    тексту предикатом нельзя — это суждение о смысле
    ([057](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/057-unmechanizable-rules-are-named-explicitly.md)).
    """
    return sorted(where.glob(pattern)) if where.is_dir() else []


def code_files(*, with_tests: bool = False) -> list[Path]:
    """Файлы кода проекта — из ОБЪЯВЛЕННОГО списка, а не из глоба по каталогу.

    Где живёт код, названо один раз — `scripts/paths.py::SOURCES`, — и до сих
    пор это объявление не читал никто: каждый гейт строил свой глоб. Пока
    источник был один, глобы совпадали; после переноса транспорта в пакет один
    гейт молча перестал видеть общий низ, а объявление продолжало утверждать,
    что источников два
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md),
    [022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

    Набор добавляется отдельным словом: он не «источник проекта» — потребители
    его не ставят, — но правилам прозы и живых ссылок подчиняется наравне.
    """
    paths = load_script("paths.py")
    found: list[Path] = []
    for where in paths.SOURCES:
        found += walk(ROOT / where, "*.py")
    if with_tests:
        found += walk(ROOT / "tests", "*.py")
    return found


def load_script(name: str) -> ModuleType:
    """Импортирует скрипт проекта как модуль, чтобы проверять его логику прямо.

    Скрипты живут в `scripts/` и пакета не образуют: каждый запускается сам по
    себе. Общее у них всё же есть — транспорт `ghrest` и состав меток
    `labels`, — и остальные их импортируют, иначе обвязка расползается копиями.
    Отсюда и добавление пути ниже: без него импорт общего модуля не найдётся.

    ЭКЗЕМПЛЯР ОДИН НА ИМЯ, И ЭТО ПРЕДМЕТ, А НЕ ЭКОНОМИЯ НА ЗАПУСКЕ. Повторное
    исполнение файла клало в `sys.modules` ВТОРОЙ экземпляр и затирало первый.
    Кто импортировал скрипт раньше, оставался с прежним; кто позже — получал
    новый. Два «одинаковых» модуля расходились по личности, и проверка «`on:`
    разбирается одной функцией» краснела от одного лишь ПОРЯДКА сбора:
    `pytest $(ls -r tests/test_*.py)` её ронял, обычный прогон — нет. Настоящий
    запуск исполняет файл ровно один раз, и тест обязан видеть модуль так же,
    как его видит прогон.
    """
    path = ROOT / "scripts" / name
    # Механизмы делят общий транспорт (`ghrest`), и при запуске файла его
    # находит сам интерпретатор: каталог скрипта попадает в путь первым. При
    # импорте отсюда этого не происходит, поэтому путь добавляется явно —
    # тест обязан видеть модуль ровно так же, как его видит прогон.
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)

    # Источник истины — `sys.modules`, а не свой словарь рядом с ним: скрипты
    # импортируют друг друга обычным `import`, и тот смотрит именно туда. Свой
    # кэш разошёлся бы с ним при первом же таком импорте, и вернулась бы та же
    # двойная личность, только незаметнее (022).
    ready = sys.modules.get(path.stem)
    if ready is not None and getattr(ready, "__file__", None) == str(path):
        return ready

    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"не собрать модуль из {path}")
    module = importlib.util.module_from_spec(spec)
    # Модуль кладётся в sys.modules ДО исполнения — ровно так же, как это делает
    # сам интерпретатор. Без этого dataclass со `slots=True` не собирается:
    # `dataclasses` ищет модуль класса по имени, чтобы разобрать отложенные
    # аннотации (`from __future__ import annotations`), не находит его и падает
    # на пустом месте. Тест обязан видеть модуль так же, как прогон.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- ПОДГОТОВЛЕННОЕ ДЕРЕВО С ОКНАМИ -------------------------------------------
#
# Живут здесь, а не в одном из тестов: их спрашивают двое — гейт срока жизни
# окна (006) и гейт свежести свода (047), — и оба строят одно и то же дерево с
# трейлерами окна и заданными датами. Второй экземпляр этих помощников
# разошёлся бы с первым молча: правка формата трейлера в одном месте из двух
# выглядит полной
# ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).

#: Начало отсчёта в подготовленном дереве. Дата заведомо своя: гейт считает
#: РАЗНОСТЬ, и привязка к «сегодня» сделала бы тест зависимым от дня прогона.
START: Final = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)

WINDOW_A: Final = "session_AAA"
WINDOW_B: Final = "session_BBB"

COAUTHOR: Final = "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"


def git(
    cwd: Path, *args: str, when: datetime | None = None, committed: datetime | None = None
) -> None:
    """Зовёт git в подготовленном дереве, при нужде подставляя даты."""
    env = dict(os.environ)
    if when is not None:
        env["GIT_AUTHOR_DATE"] = when.isoformat()
        env["GIT_COMMITTER_DATE"] = (committed or when).isoformat()
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def tail(session: str | None, *, by_window: bool = True) -> str:
    """Хвостовой блок трейлеров: соавторство и адрес окна (156)."""
    lines = []
    if by_window:
        lines.append(COAUTHOR)
    if session:
        lines.append(
            f"Claude-Session: https://claude.ai/code/session_{session.removeprefix('session_')}"
        )
    return ("\n\n" + "\n".join(lines)) if lines else ""


def commit(
    root: Path,
    subject: str,
    *,
    day: float,
    session: str | None = WINDOW_A,
    by_window: bool = True,
    committed_day: float | None = None,
) -> None:
    """Один коммит на указанный день от начала отсчёта."""
    when = START + timedelta(days=day)
    committed = START + timedelta(days=committed_day) if committed_day is not None else None
    (root / "file.txt").write_text(subject, encoding="utf-8")
    git(root, "add", "file.txt")
    git(
        root,
        "commit",
        "-m",
        subject + tail(session, by_window=by_window),
        when=when,
        committed=committed,
    )
