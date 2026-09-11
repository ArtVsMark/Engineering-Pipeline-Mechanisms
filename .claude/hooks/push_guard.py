#!/usr/bin/env python3
"""Толчок не туда отвергается ДО вызова git, а не ловится после.

Держит два критических запрета свода, и адреса у них разные. «НЕ писать в main
напрямую» опирается на 131: операция, которая должна нести личность человека, из
агентского окна не выполняется — прокси подменяет учётные данные НА ЗАПИСИ, и
прямой толчок в общую ветку ровно такая операция. «НЕ пушить в ветку чужого
изменения» — из 012, и правило 131 к нему отношения не имеет: там речь не об
авторстве, а о том, что ветку ведёт своё окно. Общая ссылка «(012, 131)» на оба
запрета сразу приписывала 131 то, чего в нём нет; нашёл внешний взгляд на #143.

ПОЧЕМУ ХУК, А НЕ ГЕЙТ. Конвейер видит АРТЕФАКТ, а не действие: к запуску
прогона толчок уже состоялся, и ветка уже сдвинута. Отвергать надо до вызова
git — единственное место, где это возможно, стоит перед инструментом.

ПРИЗНАК ВЫБРАН ДОСТУПНЫЙ, А НЕ ЖЕЛАЕМЫЙ. «Чужая ветка» машине недоступна: чья
она, знает человек. Зато доступен признак, которым пользуются все три соседа:
имя ветки в команде не совпадает с текущей головой. Промах пальцем,
скопированная из передачи строка, старое имя из прошлой смены — все три дают
одно наблюдаемое: содержимое уезжает не туда, куда смотрит окно.

ИНЦИДЕНТ, ИЗ-ЗА КОТОРОГО СТОРОЖ ЗАВЕДЁН, СВОЙ. 10.09.2026 окно, стоя на ветке
`agent/items-sweep`, толкнуло в `agent/marking-moves-out-of-the-queue`. Обе
свои, обе законные — а следствие такое же, как у чужой: конвейер открыл ВТОРОЕ
изменение на ту же работу (#116), его пришлось закрывать руками, и ветка
осталась висеть, потому что прав удалить её у окна нет.

ЧТО РАЗРЕШЕНО. Толчок без имени ветки (`git push`) и толчок текущей ветки под
её собственным именем. Всё остальное с явным именем отвергается — включая
`HEAD:<другая-ветка>`: «своя голова под чужим именем» и есть форма инцидента
#116, а не исключение из него. Общая ветка отвергается всегда: писать в неё
напрямую нельзя ни из какой головы.

Законный случай «работа должна уехать под другим именем» решается переходом на
эту ветку, а не толчком мимо головы: тогда окно и конвейер смотрят на одно.

ТЕЛО ДОКУМЕНТА НА ВХОДЕ — ДАННЫЕ, А НЕ КОМАНДА. `cat > файл <<'EOF' … EOF`
пишет файл, и `git push` внутри него — текст. Сторож смотрит на действие:
разбор идёт по словам команды, а не поиском подстроки.

Приём взят у соседей (162), файл — нет: у них запреты свои и собраны под их
конвейеры.

Вход: JSON события PreToolUse на stdin. Выход: 0 — пропустить, 2 — отвергнуть
с причиной в stderr.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import Final

#: Ветка, в которую писать напрямую нельзя ни из какой головы (131).
SHARED: Final = "main"
#: Ключи `git push`, за которыми идёт значение, а не имя ветки.
WITH_VALUE: Final = frozenset({"--repo", "-o", "--push-option", "--exec", "--receive-pack"})
#: Глобальные ключи самого git со значением: `git -C путь push`. Отделять их
#: нужно, потому что подкоманда — первое слово без ключа.
GLOBAL_WITH_VALUE: Final = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
)
#: Приставка ссылки: в `refs/heads/agent/x` предметом сверки служит имя ветки.
REF_PREFIX: Final = "refs/heads/"
#: Обёртки, за которыми идёт команда, и КЛЮЧИ КАЖДОЙ, несущие значение.
#:
#: ПОЧЕМУ КЛЮЧИ НАЗВАНЫ ПОИМЁННО, А НЕ УГАДЫВАЮТСЯ. Обёртке нужно пропустить её
#: собственные ключи и взять СЛЕДУЮЩЕЕ слово как программу. «Пропустить всё, что
#: начинается с дефиса» не работает: `nice -n 5` оставляет `5` первым словом, то
#: есть командой. Поиск `git` дальше по словам — тоже: он находит его в ДАННЫХ
#: чужой программы, и `env echo git push origin main` отвергалось как толчок в
#: общую ветку (нашёл внешний взгляд на #186). Поэтому у каждой обёртки назван
#: её набор: список закрытый, а ключ вне его делает сторожа слепым, и слепой
#: отвергает (068).
WRAPPERS: Final[dict[str, frozenset[str]]] = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
    "command": frozenset(),
    "nice": frozenset({"-n", "--adjustment"}),
    "nohup": frozenset(),
    "stdbuf": frozenset({"-i", "-o", "-e", "--input", "--output", "--error"}),
    "time": frozenset({"-f", "--format", "-o", "--output"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
}
#: Ключи обёрток БЕЗ значения: их пропускают по одному слову. Тоже поимённо и
#: по той же причине.
WRAPPER_FLAGS: Final[dict[str, frozenset[str]]] = {
    "env": frozenset({"-i", "--ignore-environment", "-0", "--null", "-v", "--debug"}),
    "command": frozenset({"-p", "-v", "-V"}),
    "nice": frozenset(),
    "nohup": frozenset(),
    "stdbuf": frozenset(),
    "time": frozenset({"-p", "-v", "--verbose", "--portability", "-a", "--append"}),
    "timeout": frozenset({"--preserve-status", "--foreground", "-v", "--verbose"}),
}
#: ЧТО ДЕЛАЕТ НЕПОЛНОТА ЭТИХ СПИСКОВ, И ПОЧЕМУ ОНА ТЕРПИМА. Набор ключей у
#: утилиты растёт с версиями, и список по памяти отстаёт — `env -C`, `env -S`,
#: `time -a` первая редакция не знала (нашёл внешний взгляд на #189). Цена
#: отставания названа и идёт в безопасную сторону: неизвестный ключ делает
#: сторожа слепым, а слепой ОТВЕРГАЕТ. То есть законная команда получит отказ с
#: названной причиной — «ключ сторожу неизвестен», — и человек либо перепишет
#: её проще, либо допишет ключ сюда. Обратная ошибка — угадать и пропустить
#: толчок — здесь невозможна по построению, и это и есть смысл выбора (051).
#: Сколько СВОИХ позиционных слов обёртка съедает перед командой. У `timeout`
#: это длительность (`timeout 30 git push …`) — не ключ, а обычное слово, и без
#: этого числа разбор принимал его за имя программы и уходил ни с чем.
WRAPPER_ARGS: Final[dict[str, int]] = {"timeout": 1}
#: Обёртки, которые принимают СКРИПТ строкой: `bash -c "git push …"`. Их
#: содержимое разбирается заново, как отдельная команда.
SHELLS: Final = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
#: Короткие ключи оболочки БЕЗ значения, которые законно стоят в одной связке
#: перед `-c`: `bash -lc "…"`, `sh -xc "…"`. Список закрытый, и это важно:
#: `-norc` содержит `c`, но `c` в нём не последний и `o` несёт значение —
#: принять такую связку за `-c` значит прочитать не тот аргумент как скрипт, а
#: толчок под ней пройдёт необнаруженным (нашёл внешний взгляд на #186).
SHELL_FLAGS: Final = "ilsrxevh"
#: Насколько глубоко сторож идёт внутрь вложенных оболочек. Предел нужен:
#: `bash -c "bash -c …"` без него ушёл бы в бесконечность. ИСЧЕРПАНИЕ ПРЕДЕЛА —
#: ОТКАЗ, А НЕ ПРОПУСК: сторож, не дочитавший команду, не знает, толчок это или
#: нет, и «не знаю» здесь обязано значить «не пущу» — как и у неузнанной головы.
#: Прежде предел молча отдавал команду дальше, и это расходилось с фейл-клоузом,
#: выбранным в том же изменении для `head()`. Нашёл внешний взгляд на #181.
DEPTH: Final = 4


def is_git(word: str) -> bool:
    """Слово вызывает git — под любым написанием пути.

    Сторож ловил только буквальное `git`, и `/usr/bin/git push` проходил мимо
    целиком. Признак — ИМЯ программы, а не строка вызова: путь до неё дело
    окружения, а не намерения. Нашёл внешний взгляд на #143.
    """
    return word.rsplit("/", 1)[-1] == "git"


@dataclass(frozen=True, slots=True)
class Look:
    """Что сторож разглядел в команде: цели толчка либо причину слепоты.

    ТРИ ОТВЕТА, А НЕ ДВА. «Это толчок вот туда», «это не толчок» и «разобрать
    не удалось» — разные состояния, и сваливать третье во второе значит
    пропускать ровно то, чего не понял (045). Прежде разбор отдавал `None` и
    на «не толчок», и на исчерпанный предел вложенности.
    """

    targets: tuple[str, ...] = ()
    blind: str = ""


def script_of(segment: list[str]) -> tuple[str | None, str]:
    """Скрипт, переданный оболочке ключом `-c`, и причина слепоты.

    КЛЮЧ БЫВАЕТ СОВМЕЩЁННЫМ, НО НЕ ЛЮБАЯ СВЯЗКА С БУКВОЙ `c` — ЭТО `-c`.
    `bash -lc "…"`, `sh -xc "…"` — обычные написания, и разбор, искавший ровно
    слово `-c`, на них ломался. Но `-norc` тоже содержит `c`, а значит совсем
    другое: `c` в нём не последний, а `o` несёт значение. Принять такую связку
    за `-c` — прочитать не тот аргумент как скрипт, и толчок под ней пройдёт
    необнаруженным. Нашёл внешний взгляд на #186, оба конца.

    Поэтому связка принимается, только если `c` в ней ПОСЛЕДНИЙ, а всё до него —
    известные короткие ключи без значения. Всё прочее с буквой `c` делает
    сторожа слепым: он не берётся угадывать, какой из аргументов скрипт.
    """
    for place, word in enumerate(segment[1:], start=1):
        if word == "--":
            return None, ""
        if not word.startswith("-") or word.startswith("--") or len(word) < 2:
            continue
        cluster = word[1:]
        if "c" not in cluster:
            continue
        if cluster.endswith("c") and all(letter in SHELL_FLAGS for letter in cluster[:-1]):
            if place + 1 < len(segment):
                return segment[place + 1], ""
            return None, f"у оболочки ключ «{word}» без скрипта — читать нечего"
        return None, f"связка ключей «{word}» неоднозначна: где в ней скрипт, сторожу неизвестно"
    return None, ""


def split_string_of(segment: list[str]) -> tuple[str | None, str]:
    """Строка `env -S «…»`, если она есть: `env` разбивает её сам, как оболочка."""
    for place, word in enumerate(segment[1:], start=1):
        if word == "--":
            return None, ""
        head, sign, joined = word.partition("=")
        if head in ("-S", "--split-string"):
            if sign:
                return joined, ""
            if place + 1 < len(segment):
                return segment[place + 1], ""
            return None, "у `env -S` нет строки — читать нечего"
        if word.startswith("-S") and len(word) > 2:
            return word[2:], ""
    return None, ""


def after_wrapper(name: str, rest: list[str]) -> tuple[list[str], str]:
    """Слова после ключей обёртки — начиная с программы, которую она запускает.

    КЛЮЧИ ПРОПУСКАЮТСЯ ПО ИМЕНИ, А КОМАНДА БЕРЁТСЯ СЛЕДУЮЩИМ СЛОВОМ. Прежде
    здесь стояло сканирование — «найти `git` дальше по словам», — и оно
    дотягивалось до ДАННЫХ чужой программы: `env echo git push origin main`
    отвергалось как толчок в общую ветку. Ключ, которого нет в наборе обёртки,
    делает сторожа слепым: угадать, несёт он значение или нет, нечем, а ошибка
    в любую сторону молча меняет, что считается командой.
    """
    values, flags = WRAPPERS.get(name, frozenset()), WRAPPER_FLAGS.get(name, frozenset())
    place = 0
    eaten = 0
    while place < len(rest):
        word = rest[place]
        if word == "--":
            return rest[place + 1 + WRAPPER_ARGS.get(name, 0) - eaten :], ""
        if not word.startswith("-"):
            # `VAR=value` перед командой — то же присваивание, что и на верхнем
            # уровне: своё написание того же вызова.
            if "=" in word and not word.startswith("="):
                place += 1
                continue
            if eaten < WRAPPER_ARGS.get(name, 0):
                eaten += 1
                place += 1
                continue
            return rest[place:], ""
        head, _, joined = word.partition("=")
        if head in values:
            place += 1 if joined else 2
            continue
        if head in flags:
            place += 1
            continue
        # Совмещённый короткий ключ со значением: `stdbuf -oL`, `nice -n5`.
        if len(word) > 2 and word[:2] in values:
            place += 1
            continue
        return [], f"ключ «{word}» у обёртки «{name}» сторожу неизвестен"
    return [], f"после обёртки «{name}» команды нет"


def unwrap(segment: list[str], depth: int) -> tuple[list[list[str]], str]:
    """Снимает обёртки и раскрывает `bash -c «…»`; отдаёт команды и слепоту.

    ОБЁРТКА — НЕ МАСКИРОВКА, И СПИСОК ЕЁ ЗАКРЫТ. `env git push`, `nohup git
    push`, `bash -c "git push …"` — законные написания того же действия, и
    сторож, смотрящий только на первое слово, пропускал их все. Список
    разрешительный: что не названо обёрткой, обёрткой не считается (068).

    ОБЁРТКА ВОКРУГ ОБОЛОЧКИ — ТОЖЕ ОБЁРТКА. `env bash -c "git push …"`
    проходил необнаруженным: разбор снимал `env` и на этом останавливался,
    потому что дальше шёл не `git`. Снятие идёт по кругу, пока снимается.

    ВТОРЫМ ОТДАЁТСЯ ПРИЧИНА СЛЕПОТЫ. Предел вложенности исчерпан, ключ обёртки
    неизвестен, связка ключей оболочки неоднозначна — команда не дочитана, и
    сторож об этом говорит, а не отдаёт её дальше молча.
    """
    if not segment:
        return [segment], ""
    if depth <= 0:
        return [], "предел вложенности оболочек исчерпан — команда не дочитана"
    first = segment[0].rsplit("/", 1)[-1]
    # `VAR=value git push` — присваивания перед командой, своё написание того же.
    if "=" in first and not first.startswith("=") and len(segment) > 1:
        return unwrap(segment[1:], depth - 1)
    if first in SHELLS:
        script, blind = script_of(segment)
        if blind:
            return [], blind
        if script is None:
            return [segment], ""
        try:
            inner = shlex.split(script)
        except ValueError:
            return [], f"скрипт оболочки не разбирается: {script[:60]}"
        found: list[list[str]] = []
        for part in segments(inner):
            deeper, blind = unwrap(part, depth - 1)
            if blind:
                return [], blind
            found.extend(deeper)
        return found or [segment], ""
    if first == "env":
        # `env -S "git push …"` — та же передача СКРИПТА строкой, что и `-c` у
        # оболочки: `env` сам разбивает её на слова. Пропустить её как обычное
        # значение ключа значило бы остаться без команды — сторож отвергал бы
        # такую строку слепотой, не назвав ветки. Нашёл внешний взгляд на #189.
        script, blind = split_string_of(segment)
        if blind:
            return [], blind
        if script is not None:
            try:
                inner = shlex.split(script)
            except ValueError:
                return [], f"строка `env -S` не разбирается: {script[:60]}"
            split: list[list[str]] = []
            for part in segments(inner):
                deeper, blind = unwrap(part, depth - 1)
                if blind:
                    return [], blind
                split.extend(deeper)
            return split or [segment], ""
    if first in WRAPPERS and len(segment) > 1:
        rest, blind = after_wrapper(first, segment[1:])
        if blind:
            return [], blind
        # Внутри обёртки может стоять другая обёртка или оболочка — снятие идёт
        # по кругу, а не один раз.
        return unwrap(rest, depth - 1)
    return [segment], ""


def push_targets(command: str) -> Look:
    """Что сторож разглядел: цели толчка, «не толчок» или причину слепоты.

    Разбор по СЛОВАМ: подстрока `git push` встречается и в тексте документа, и
    в сообщении коммита, а действие — только у разобранной команды.

    НЕРАЗОБРАННАЯ КОМАНДА — НЕ «НЕ ТОЛЧОК». Строка с незакрытой кавычкой и
    исчерпанный предел вложенности прежде отдавались тем же ответом, что и
    безобидный `ls`, — то есть сторож пропускал ровно то, чего не понял (045).
    Нашёл внешний взгляд на #181.
    """
    try:
        words = shlex.split(command)
    except ValueError:
        return Look(blind="команда не разбирается на слова — кавычки не закрыты")
    for part in segments(words):
        found, blind = unwrap(part, DEPTH)
        if blind:
            return Look(blind=blind)
        for segment in found:
            if not segment or not is_git(segment[0]):
                continue
            rest = segment[1:]
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in GLOBAL_WITH_VALUE else rest[1:]
            if rest and rest[0] == "push":
                return Look(targets=tuple(named_branches(rest[1:])))
    return Look()


def segments(words: list[str]) -> list[list[str]]:
    """Части составной строки: `cd … && git push …` — это две команды.

    Без разбиения вызов git, стоящий не первым, проходил мимо сторожа: живой
    промах при постройке — `cd x && git push origin main` не отвергался.
    """
    found: list[list[str]] = [[]]
    for word in words:
        if word in {"&&", "||", ";", "|", "&"}:
            found.append([])
            continue
        found[-1].append(word)
    return found


def named_branches(arguments: list[str]) -> list[str]:
    """Ветки-цели из аргументов `git push`, кроме первого (удалённого имени)."""
    found: list[str] = []
    skip = False
    seen_remote = False
    for word in arguments:
        if skip:
            skip = False
            continue
        if word in WITH_VALUE:
            skip = True
            continue
        if word.startswith("-"):
            continue
        if not seen_remote:
            seen_remote = True
            continue
        found.append(word)
    return found


def head() -> tuple[str, str]:
    """Текущая ветка и причина, по которой её не узнать.

    ДВА ОТВЕТА, А НЕ ОДИН, и разница здесь стоит половины сторожа. Прежде отказ
    `git rev-parse` отдавался пустой строкой — той же, что и отсоединённая
    голова, — и половина проверки («толчок мимо своей ветки») исчезала МОЛЧА.
    Докстрока при этом уверяла, что пусто бывает только при отсоединённой
    голове; на деле пусто бывает и когда git не нашёлся, и когда каталог не
    репозиторий. Нашёл внешний взгляд на #143.

    Отсоединённая голова даёт `HEAD` и код 0 — это не отказ, и сюда не
    попадает.
    """
    said = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if said.returncode != 0:
        return "", said.stderr.strip() or f"git rev-parse вернул {said.returncode}"
    return said.stdout.strip(), ""


def refused(targets: list[str], current: str) -> str:
    """Причина отказа; пусто — толчок разрешён."""
    for target in targets:
        # У формы `откуда:куда` предмет — правая часть: именно её имя получит
        # площадка, и именно по нему конвейер откроет изменение.
        if ":" in target:
            target = target.split(":", 1)[1]
        target = target.removeprefix(REF_PREFIX)
        if target == SHARED:
            return (
                f"«{SHARED}» — общая ветка: писать в неё напрямую нельзя, только изменением "
                "через ветку (критический запрет свода)"
            )
        if current and target != current:
            return (
                f"толчок в «{target}», а голова стоит на «{current}». Ветку изменения ведёт "
                "своё окно (012). Если это ваша работа — перейдите на неё, иначе конвейер "
                "откроет второе изменение на ту же работу: 10.09.2026 так и вышло с #116"
            )
    return ""


def main() -> int:
    """Точка входа: читает событие, решает, пускать ли команду."""
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Событие не разобралось — сторож молчит: ронять чужой инструмент из-за
        # своего разбора хуже, чем пропустить одну команду (084).
        return 0
    command = str(((event or {}).get("tool_input") or {}).get("command") or "")
    look = push_targets(command)
    if look.blind:
        # РАЗБОР, НЕ ДОШЕДШИЙ ДО КОНЦА, НЕ МАШЕТ РУКОЙ. Сторож не знает, толчок
        # перед ним или нет, и «не знаю» здесь обязано значить «не пущу» — как
        # и у неузнанной головы ниже. Толчок необратим, цена уже оплачена
        # (#116), а команду можно переписать проще.
        print(
            f"Толчок отвергнут до вызова git: {look.blind}. Сторож не смог "
            "разобрать команду, а значит и не проверил её — перепишите проще.",
            file=sys.stderr,
        )
        return 2
    targets = list(look.targets)
    if not targets:
        return 0
    current, broken = head()
    # ЗАПРЕТ НА ОБЩУЮ ВЕТКУ ГОЛОВЫ НЕ ТРЕБУЕТ, и спрашивается он первым: его
    # причина точнее, чем «сторож ослеп», и читателю нужна именно она (154).
    shared = refused(targets, "")
    if shared:
        print(f"Толчок отвергнут до вызова git: {shared}", file=sys.stderr)
        return 2
    if broken:
        # СТОРОЖ, КОТОРЫЙ НЕ СМОГ ПРОВЕРИТЬ, НЕ МАШЕТ РУКОЙ. Толчок необратим:
        # отправленную ветку окно удалить не может, и цена этого уже оплачена
        # (#116, воскрешённая ветка после слияния). Пропустить здесь значило бы
        # завести тихий запасной ответ ровно в том месте, ради которого сторож
        # и стоит (045).
        print(
            "Толчок отвергнут до вызова git: сторож не смог узнать текущую ветку — "
            f"{broken}. Проверка «толчок мимо своей ветки» не выполнена, а не пройдена. "
            "Почините git в этом каталоге и повторите.",
            file=sys.stderr,
        )
        return 2
    why = refused(targets, current)
    if not why:
        return 0
    print(f"Толчок отвергнут до вызова git: {why}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
