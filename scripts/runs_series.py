#!/usr/bin/env python3
"""Ряд прогонов: как конвейер работает НА САМОМ ДЕЛЕ, а не по памяти.

Записи проверок живут, пока живёт изменение; логи прогонов из части окон не
читаются вовсе. Поэтому вопрос «как отработал конвейер» отвечался руками и по
памяти, а разбор гонки сводного гейта 13.09.2026 стоил часа именно поэтому.

ИНТЕРЕСНОЕ ЖИВЁТ В РЯДЕ, А НЕ В ОДНОМ ПРОГОНЕ. Ни один заход не показывает, что
треть заходов гаснет группой отмены, что ежечасное расписание площадка исполняет
раз из пяти и что одно имя мигало пятнадцать раз подряд. Предмет здесь —
накопленный ряд, и вопросы у него названы заранее, иначе выйдет витрина, которую
никто не читает: какое имя чаще краснеет · сколько заходов гаснет впустую ·
растёт ли время прогона.

СТРОКА РЯДА — ДЕНЬ И ПРОГОН, А НЕ ОТДЕЛЬНЫЙ ЗАХОД. Заходов у площадки полторы
тысячи в сутки, и ряд из них был бы не рядом, а копией её базы. День на прогон
сжимает сутки в две дюжины строк и отвечает на все названные вопросы: числа
складываются, а не перечисляются.

ПОСЛЕДНИЕ ДНИ ПЕРЕСЧИТЫВАЮТСЯ, СТАРЫЕ ЗАМОРОЖЕНЫ. Пока записи прогонов живы,
день — зеркало живых артефактов
([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)):
пропущенный заход по расписанию не оставляет в ряду дыру, потому что следующий
пересчитает тот же день заново. Дальше окна пересчёта день уже не меняется —
артефактов под ним нет, и трогать его было бы выдумыванием.

ГРАНИЦЫ ОБЪЯВЛЕНЫ ДАННЫМИ (`.rules/series.json`), а не зашиты здесь: окно — это
решение о цене хранения, и менять его правкой числа в коде значило бы менять
договор молча (042). Где ряд лежит и почему не в ветке значков —
`docs/decisions/022-the-series-of-runs-lives-in-its-own-branch.md`.

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО: счёта миганий. Мигание — «красное, затем зелёное на
той же голове», и его считает шаг 9 в реестре #99. Второй счёт того же разошёлся
бы с первым молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

Исходы (правило 039): ``0`` ряд обновлён · ``2`` заход не отработал. Третьего у
накопления нет, и это названо, а не пропущено: «обновил, но с находками» здесь
не существует — механизм либо прочитал прогоны и свёл день, либо не смог (154).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import ghrest
import paths
import yaml
from report import announce

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2

#: Границы ряда: объявление, а не догадка. Адрес берётся у общего якоря, а не
#: строится здесь: второй адрес того же файла разошёлся бы с первым молча (090).
BOUNDS_FILE: Final = paths.SERIES

#: Исходы, которые считаются настоящим красным. Слово в слово как у шага 9:
#: отменённая не пройдена, но и не отказ, а «идёт» вердикта не несёт вовсе.
REAL_RED: Final = frozenset({"failure", "timed_out", "action_required"})

#: Витрина проекта: факты, опубликованные шагом значков в ветку-сироту `badges`.
#: Адрес тот же, что этот шаг печатает по окончании; читается по прямой ссылке,
#: без клона — ради этого производное туда и уезжает (125).
FACTS_URL: Final = "https://raw.githubusercontent.com/{repo}/badges/facts.json"


class NotRun(RuntimeError):
    """Заход не отработал: второй исход, а не пустой ряд."""


@dataclass(frozen=True, slots=True)
class Bounds:
    """Границы ряда, прочитанные из объявления."""

    window_days: int
    recount_days: int

    @classmethod
    def read(cls, path: Path) -> Bounds:
        """Читает границы; отсутствие объявления — отказ входа, а не умолчание."""
        try:
            said = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NotRun(f"границы ряда не прочитаны ({path}): {exc}") from exc
        try:
            window, recount = int(said["window_days"]), int(said["recount_days"])
        except (KeyError, TypeError, ValueError) as exc:
            raise NotRun(f"в {path} нет объявленных window_days и recount_days: {exc}") from exc
        if not 0 < recount <= window:
            raise NotRun(
                f"окно пересчёта {recount} не помещается в окно хранения {window} — "
                "границы противоречат друг другу (075)"
            )
        return cls(window_days=window, recount_days=recount)


def day_of(run: dict[str, Any]) -> str:
    """День захода по его началу у площадки: `ГГГГ-ММ-ДД`."""
    return str(run.get("created_at") or "")[:10]


def elapsed(run: dict[str, Any]) -> int | None:
    """Сколько секунд заход занял у площадки; `None` — время НЕ СКАЗАНО.

    Ноль и «не сказано» — разные вещи, и сводить их к нулю нельзя: заход,
    уложившийся в секунду, существует, а средний по дню считается только по
    тем, у кого время известно. Молча подставить ноль значило бы занижать
    среднее ровно на числе неразобранных
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    started, ended = run.get("run_started_at"), run.get("updated_at")
    if not started or not ended:
        return None
    try:
        began = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        done = datetime.fromisoformat(str(ended).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((done - began).total_seconds()))


#: Служебные шаги, которые ставит САМА ПЛОЩАДКА: падение на них говорит о ней, а
#: не о дереве. Список разрешительный (068), имена английские и приходят от
#: GitHub — своих шагов здесь нет и быть не может.
PLATFORM_STEPS: Final = (
    "set up job",
    "checkout",
    "set up python",
    "post ",
    "complete job",
)

#: Чем шаг ставит зависимости. Признак — КОМАНДА, а не имя: имя шага пишет
#: автор на своём языке, и перечислять имена значило бы вести список, который
#: устаревает молча при первом же новом шаге (005, 049).
INSTALLERS: Final = ("pip install", "npm install", "npm ci")


#: Знаки кавычек, внутри которых оболочка не видит ни связок, ни комментария.
QUOTES: Final = "'\""

#: Связки оболочки, по которым строка делится на команды. Двухзнаковые стоят
#: первыми: разбор идёт слева направо и берёт первое совпадение, иначе `||`
#: прочиталось бы как две одиночные черты.
JOINERS: Final = ("&&", "||", ";", "|")


def bare_of(line: str) -> str:
    """Строка без комментария оболочки — так, как его видит сама оболочка.

    ДВА ПРАВИЛА, И ОБА ИЗМЕРЕНЫ, А НЕ ВЗЯТЫ ИЗ ГОЛОВЫ.

    **Решётка в кавычках комментария не начинает.** В дереве ЧЕТЫРЕ строки
    `run:` несут её именно так: `echo "…записан в #196"`, `echo "смотрим
    названное: #$ASKED"` и две соседних. Наивная обрезка искалечила бы все
    четыре.

    **Решётка внутри слова комментария тоже не начинает.** `pip install
    pkg@git+URL#egg=x` — обычный адрес, и оболочка режет по решётке, только
    когда та стоит первым знаком слова. Прежняя редакция звала `shlex` с
    `comments=True`, а его правило ШИРЕ оболочкиного: `echo foo#bar` он
    обрезал до `echo foo`, чего `bash` не делает. Нашёл внешний взгляд на #657.

    ПОЧЕМУ РАЗБОР СВОЙ, А НЕ `shlex`. Тот же заход выявил вторую беду: `shlex`
    отдаёт ТОКЕНЫ, и собрать из них строку обратно нельзя — кавычки теряются, и
    `echo "a | b"` превращался в `echo a | b`, то есть в две команды вместо
    одной. Здесь строка не пересобирается вовсе: разбор только НАХОДИТ границу
    и отдаёт исходный кусок
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    said = line.strip()
    quote = ""
    for place, sign in enumerate(said):
        if quote:
            if sign == quote:
                quote = ""
            continue
        if sign in QUOTES:
            quote = sign
            continue
        if sign == "#" and (place == 0 or said[place - 1].isspace()):
            return said[:place].strip()
    return said


def apart(said: str) -> list[str]:
    """Команды одной строки: связки оболочки режут, кавычки — нет.

    СВЯЗКА В КАВЫЧКАХ КОМАНДЫ НЕ РАЗДЕЛЯЕТ. `echo "a | b"` — одна команда с
    чертой внутри строки, и разбор, не знающий кавычек, дробил её надвое.
    Нашёл внешний взгляд на #657.
    """
    found: list[str] = []
    start = place = 0
    quote = ""
    while place < len(said):
        sign = said[place]
        if quote:
            if sign == quote:
                quote = ""
            place += 1
            continue
        if sign in QUOTES:
            quote = sign
            place += 1
            continue
        hit = next((one for one in JOINERS if said.startswith(one, place)), "")
        if hit:
            found.append(said[start:place])
            place += len(hit)
            start = place
            continue
        place += 1
    found.append(said[start:])
    return [one.strip() for one in found if one.strip()]


def commands(run: str) -> list[str]:
    """Команды блока `run:` — по одной, без комментариев и пустых строк.

    КОММЕНТАРИЙ КОМАНДОЙ НЕ СЧИТАЕТСЯ, и это не мелочь. Прежняя редакция
    требовала признака установки от КАЖДОЙ непустой строки — а проект объясняет
    границы версий пакетов именно строчным комментарием внутри `run: |`
    (`step-lint.yml`, `labels-sync.yml`). Такая строка признака не несла и
    молча вышибала шаг из состава служебных, то есть воспроизводила беду #634
    на новом месте. Нашёл внешний взгляд на #635.

    СТРОКА ДЕЛИТСЯ ПО СВЯЗКАМ ОБОЛОЧКИ. `pip install X && pytest` — это две
    команды, и вторая делает работу. Поиск подстроки видел в такой строке
    установку и объявлял шаг служебным целиком; падение настоящей работы
    пряталось бы за площадкой. Нашёл внешний взгляд там же.

    ХВОСТОВОЙ КОММЕНТАРИЙ СРЕЗАЕТСЯ ТОЖЕ, и это третий конец той же беды:
    `pytest  # не забыть pip install` читался установкой, потому что маркер
    находился в пояснении. Нашёл внешний взгляд на #641.
    """
    return [one for line in run.splitlines() for one in apart(bare_of(line))]


def only_installs(run: str) -> bool:
    """Делает ли блок ТОЛЬКО установку зависимостей.

    Пустой блок установкой не считается: «команд нет» и «все команды ставят» —
    разные состояния, и сливать их значило бы объявить служебным шаг, о котором
    не известно ничего
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    said = commands(run)
    return bool(said) and all(any(mark in one for mark in INSTALLERS) for one in said)


def installing_steps(directory: Path = paths.WORKFLOWS) -> frozenset[str]:
    """Имена шагов дерева, которые ТОЛЬКО ставят зависимости.

    ЗАМЕР 22.09.2026, РАДИ КОТОРОГО ЭТО ЗАВЕДЕНО. Шагов, ставящих зависимости, в
    дереве ПЯТНАДЦАТЬ, и список площадочных умолчаний не видел служебным НИ
    ОДНОГО: он знает только `set up job`, `checkout`, `set up python`, `post `,
    `complete job` — все английские, все от GitHub. Наши шаги названы
    по-русски: «поставить проверки» (три), «поставить разбор состава» (шесть),
    «поставить проверки ревьюеру» (два) и ещё три имени.

    ЭТО ОБЕСЦЕНИЛО СОБСТВЕННЫЙ ЗАМЕР ОТЧЁТА, и признать это важнее, чем
    починить. Отчёт утверждал «130 упавших джобов из 130 упали на СВОЁМ шаге,
    служебных ноль», и на этом числе стоял вывод, что теория «у всех одна
    ошибка площадки» подтверждения не имеет. Число было АРТЕФАКТОМ СПИСКА:
    служебным не мог оказаться ни один наш шаг, как бы он ни падал. Правило 206
    называет это прямо — «набор форм берётся замером, а не перечислением по
    памяти; невидимая форма чаще всего оказывается самой частой», — и правило
    это отправил каталогу ЭТОТ проект
    ([206](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/206-a-form-the-gate-cannot-see-is-a-bypass.md)).

    ЖИВОЙ СЛУЧАЙ, КОТОРЫЙ ЭТО ВСКРЫЛ. 22.09.2026 на общей ветке `test-next
    (3.15)` упал на шаге «поставить проверки» — на `pip install`, ДО единого
    теста, на предрелизном интерпретаторе. Владелец перезапустил рукой, вторая
    попытка зелена (прогон 35714755550). Механизм записал бы это «своим шагом».

    «ТОЛЬКО СТАВИТ» — ГРАНИЦА, И ОНА НАЗВАНА. Шаг, который ставит И делает,
    служебным не считается: его падение может быть о чём угодно. В дереве такой
    ровно один — «сосчитать покрытие»: он ставит набор и тут же считает
    покрытие, и относить его к площадке значило бы прятать настоящий отказ
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).

    БЕЗЫМЯННЫЕ ШАГИ СЮДА НЕ ПОПАДАЮТ, и это тоже граница: площадка зовёт такой
    шаг текстом его команды, и сопоставить его по имени нечем.

    ИМЯ, КОТОРОЕ ГДЕ-ТО ДЕЛАЕТ РАБОТУ, СЛУЖЕБНЫМ НЕ СТАНОВИТСЯ НИГДЕ. Площадка
    отдаёт упавший шаг ОДНИМ ИМЕНЕМ, без файла и джоба, — и пока состав
    собирался по первому же совпадению, одноимённый сосед, который ставит И
    делает, наследовал чужую отметку «площадка», и его настоящее падение
    пряталось. Поэтому имя вычитается: попало хоть раз в работающие — выбыло из
    служебных. Ошибка тогда идёт в дешёвую сторону: служебное падение назовут
    своим, и его увидят, а не наоборот
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    Нашёл внешний взгляд на #635.

    ПОЧЕМУ НЕ ПАРА «ДЖОБ И ШАГ», хотя имя джоба у отчёта есть. У вынесенного
    шага площадка пишет составное имя вызывающего и вызванного (`debt / debt`),
    и сопоставить его с джобом дерева нечем без второго разбора вызовов. Пара
    была бы точнее, но держалась бы на совпадении, которого механизм не
    проверяет; вычитание точнее не станет, зато не соврёт
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    """
    if not directory.is_dir():
        return frozenset()
    installs: set[str] = set()
    works: set[str] = set()
    for path in sorted(directory.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job in (document.get("jobs") or {}).values():
            for step in (job or {}).get("steps") or []:
                said = str((step or {}).get("name") or "").strip()
                run = str((step or {}).get("run") or "")
                if not said or not run.strip():
                    continue
                (installs if only_installs(run) else works).add(said.lower())
    return frozenset(installs - works)


#: Признаки осечки в тексте отчёта. Каждый назван с причиной, и каждый ИЗМЕРЕН
#: на нашей истории 21.09.2026 — иначе это была бы догадка (044):
#:
#: * «ждём соседей» — собственное сообщение сводного гейта: он опросил голову
#:   раньше, чем соседи зарегистрировались. Замер: 16 красных `ci-complete` из
#:   16 несут его, то есть признак стопроцентный;
#: * «exit code 128» — отказ git: сеть или доступ. Замер: 1 случай;
#: * осечка обвязки площадки. Замер: 4 случая на `late-queue`.
#:
#: Список ничего не решает сам: он КОПИТ наблюдение, чтобы зависимость стала
#: видна на числах, а не на памяти (005, 049).
REPORT_MARKS: Final = {
    "ждём соседей": "сводный гейт опросил голову раньше соседей",
    "exit code 128": "отказ git — сеть или доступ",
    "Unable to process file command": "осечка обвязки площадки",
    "Invalid format": "осечка обвязки площадки",
}


#: Отказ чтения аннотаций. Он НЕ «признака нет»: у отказа и у пустоты одинаковое
#: значение сделало бы счёт признаков ложным — отказы попадали бы в долю «осечек
#: не найдено» и разбавляли её тем, чего никто не смотрел
#: ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
#: Нашёл внешний взгляд находкой `24fd8f7`: докстрока обещала третий исход у
#: зовущего, а зовущий писал ту же пустую строку.
MARK_UNREAD: Final = "отчёт не прочитан"

#: Шаг падения свой — то есть о дереве. Пишется словом, а не пустотой: пустота
#: у `whose` значила бы «шагов площадка не отдала», и два разных наблюдения
#: слиплись бы в одно.
WHOSE_OWN: Final = "свой"
#: Шаг падения служебный — то есть о площадке.
WHOSE_SERVICE: Final = "площадки"
#: Шагов в ответе нет — сказать о падении нечего.
WHOSE_UNKNOWN: Final = ""


def whose_step(step: str, ours: frozenset[str] | None = None) -> str:
    """Чей шаг упал: площадки или наш. Пусто — шага площадка не отдала.

    ЗАЧЕМ ОТДЕЛЬНОЙ ФУНКЦИЕЙ. `SERVICE_STEPS` был объявлен и не вызывался
    ниоткуда — то есть различение, ради которого собирается отчёт, не
    происходило вовсе, а докстрока соседа его обещала. Нашёл внешний взгляд
    находкой `f7b99be`; список, который ничего не находит, доказывает только
    себя ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).

    СЕГОДНЯ ОН НЕ НАХОДИТ НИЧЕГО, И ЭТО ЗАПИСЬ, А НЕ ПРОБЕЛ. Замер 21.09.2026:
    130 упавших джобов из 130 упали на СВОЁМ шаге — И ЭТО ЧИСЛО БОЛЬШЕ НЕ
    ДЕЙСТВУЕТ: снято оно списком, который не видел служебным ни один НАШ шаг
    установки, а их в дереве пятнадцать. Счёт начат заново 22.09.2026. Пока
    площадкиных ноль, у теории «у
    всех одна ошибка площадки» подтверждения нет — и сказать это можно только
    потому, что различение считается, а не подразумевается
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
    """
    if not step:
        return WHOSE_UNKNOWN
    said = step.strip().lower()
    if said.startswith(PLATFORM_STEPS):
        return WHOSE_SERVICE
    # НАШ ШАГ УСТАНОВКИ — ТОЖЕ СЛУЖЕБНЫЙ. Он падает от индекса пакетов, сети
    # или отсутствующего колеса, а не от дерева: до кода проекта управление
    # ещё не дошло. Состав таких имён читается ИЗ ДЕРЕВА (`installing_steps`),
    # а не перечисляется здесь — иначе список устаревал бы молча (049, 206).
    return WHOSE_SERVICE if said in (ours or frozenset()) else WHOSE_OWN


def report_mark(repo: str, job: int, token: str) -> str:
    """Признак осечки из отчёта джоба; пусто — признака нет.

    Читаются АННОТАЦИИ, а не логи: логи окну недоступны (площадка отвечает 403
    через прокси), а аннотации приходят обычным чтением. Отказ чтения даёт
    `MARK_UNREAD` — отдельное значение, а не ту же пустоту: иначе непрочитанное
    попало бы в счёт «признака нет» (045).
    """
    try:
        found = ghrest.request("GET", f"repos/{repo}/check-runs/{job}/annotations", token)
    except ghrest.TransportError:
        return MARK_UNREAD
    text = " ".join(str((one or {}).get("message") or "") for one in (found or []))
    for mark, why in REPORT_MARKS.items():
        if mark in text:
            return why
    return ""


def red_details(repo: str, run: int, token: str) -> list[dict[str, str]]:
    """Упавшие джобы захода: имя, шаг падения и признак осечки из отчёта.

    ОДИН ОБХОД, А НЕ ТРИ. Имя, шаг и признак спрашиваются у одного и того же
    ответа площадки: три обхода того же стоили бы вызовов из общей квоты и
    разошлись бы между собой молча
    ([058](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/058-when-the-quota-is-out-stop.md),
    [022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).

    Признак стоит ВТОРЫМ вызовом и только для красных: аннотации спрашиваются у
    каждого упавшего джоба, а их за сутки единицы.

    ПОЧЕМУ ДЖОБЫ СПРАШИВАЮТСЯ ТОЛЬКО У КРАСНЫХ — ЗАМЕР, А НЕ ОСТОРОЖНОСТЬ.
    Джобы КАЖДОГО захода стоили бы полутора тысяч вызовов в сутки, а красных за
    те же сутки было ТРИНАДЦАТЬ: вопрос «какое имя чаще краснеет» отвечается по
    ним, и цена остаётся счётной (058). Довод переехал сюда вместе с предметом
    из `red_jobs` — та отдавала одни имена, эта отдаёт имя, шаг, признак и чей
    шаг упал, и рабочий путь идёт через неё. Перенос без перечитывания — род,
    на котором проект уже спотыкался, поэтому числа названы здесь целиком, а не
    пересказаны (022).
    """
    payload = ghrest.request("GET", f"repos/{repo}/actions/runs/{run}/jobs", token) or {}
    # СОСТАВ ЧИТАЕТСЯ ОДИН РАЗ НА ЗАХОД, а не на джоб: он выводится из дерева и
    # за время захода не меняется, а тридцать файлов на каждый упавший джоб —
    # цена без предмета (058).
    ours = installing_steps()
    found: list[dict[str, str]] = []
    for job in payload.get("jobs") or []:
        if job.get("conclusion") not in REAL_RED:
            continue
        number = int(job.get("id") or 0)
        step = failed_step(job)
        found.append(
            {
                "name": str(job.get("name") or ""),
                "step": step,
                # ЧЕЙ ШАГ — ПИШЕТСЯ, А НЕ ВЫВОДИТСЯ ЧИТАТЕЛЕМ. Ровно этот
                # вопрос назвал владелец: «у всех джобов одна ошибка платформы
                # — перезапустить все?» Ответ на него считается здесь один раз
                # и ложится в запись; второе понимание «служебный ли шаг»
                # разошлось бы с первым молча (022).
                "whose": whose_step(step, ours),
                "mark": report_mark(repo, number, token) if number else MARK_UNREAD,
            }
        )
    return sorted(found, key=lambda one: one["name"])


def failed_step(job: dict[str, Any]) -> str:
    """Имя шага, на котором джоб упал; пусто — шагов площадка не отдала.

    ЗАЧЕМ ЭТО СОБИРАЕТСЯ. Вопрос «дефект это или осечка площадки» по имени
    ДЖОБА не решается: имя одно и то же в обоих случаях. Решает его ШАГ —
    служебный (чекаут, установка) против своего (тесты, типы). Замер
    21.09.2026 дал «130 из 130 на своём шаге», но ОБЕСЦЕНЕН: список не видел
    служебным ни один наш шаг установки. Счёт перемеряется с 22.09.2026 — и это
    тоже наблюдение, которое стоит копить
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
    """
    for step in job.get("steps") or []:
        if step.get("conclusion") in REAL_RED:
            return str(step.get("name") or "")
    return ""


def swept(repo: str, token: str, since: str) -> dict[str, dict[str, dict[str, Any]]]:
    """Сводит заходы площадки от дня `since` в строки «день → прогон → числа»."""
    days: dict[str, dict[str, dict[str, Any]]] = {}
    seen = 0
    for run in ghrest.paginate(
        f"repos/{repo}/actions/runs?created=%3E%3D{since}&status=completed",
        token,
        key="workflow_runs",
    ):
        day, name = day_of(run), str(run.get("name") or "")
        if not day or not name or day < since:
            continue
        seen += 1
        row = days.setdefault(day, {}).setdefault(
            name,
            {
                "runs": 0,
                "red": 0,
                "cancelled": 0,
                "seconds": 0,
                "timed": 0,
                "red_jobs": {},
                # ОТЧЁТ ПО КРАСНЫМ КОПИТСЯ, А НЕ РЕШАЕТ (#606). Владелец назвал
                # предмет: «нужен отчёт по красным, и на основе него принимать
                # решение». Сегодня решает история мигания — в отчёте нашей
                # истории платформенных отказов НЕ НАЙДЕНО — но прежний замер
                # «130 из 130 на своём шаге» обесценен: список не видел
                # служебным ни один наш шаг установки, и счёт начат заново
                # 22.09.2026. У соседей по семье такие отказы бывают, и
                # увидеть зависимость можно только на собранных числах (049).
                "red_steps": {},
                "red_marks": {},
                # ЧЕЙ ШАГ УПАЛ — СЧЁТ, А НЕ ПОЛЕ В ЗАПИСИ. Различение,
                # посчитанное и не сведённое, отвечает ровно так же, как
                # несчитанное: вопрос «у всех одна ошибка площадки?» задаётся
                # ряду, а не одному джобу.
                "red_whose": {},
            },
        )
        row["runs"] += 1
        end = str(run.get("conclusion") or "")
        if end in REAL_RED:
            row["red"] += 1
            number = int(run.get("id") or 0)
            if number:
                for job in red_details(repo, number, token):
                    label = job["name"]
                    row["red_jobs"][label] = int(row["red_jobs"].get(label, 0)) + 1
                    if job["step"]:
                        key = f"{label} · {job['step']}"
                        row["red_steps"][key] = int(row["red_steps"].get(key, 0)) + 1
                    if job["mark"]:
                        key = f"{label} · {job['mark']}"
                        row["red_marks"][key] = int(row["red_marks"].get(key, 0)) + 1
                    side = job["whose"]
                    if side:
                        row["red_whose"][side] = int(row["red_whose"].get(side, 0)) + 1
        elif end == "cancelled":
            row["cancelled"] += 1
        spent = elapsed(run)
        if spent is not None:
            row["seconds"] += spent
            row["timed"] += 1
    if not seen:
        raise NotRun(f"заходов от {since} площадка не отдала ни одного — сводить нечего (075)")
    return days


def merge(
    known: dict[str, Any],
    fresh: dict[str, dict[str, dict[str, Any]]],
    bounds: Bounds,
    today: str,
    coverage: float | None = None,
) -> dict[str, Any]:
    """Сливает прежний ряд со свежим замером: пересчёт молодых, окно у старых.

    ОКНО ОГРАНИЧЕНО С ОБЕИХ СТОРОН. Старое уходит — это и есть окно. День ПОСЛЕ
    нынешнего уходит тоже: заход из будущего означает сбитые часы или подделку, а
    оставленный, он вытеснил бы из окна настоящий день, то есть чистка теряла бы
    не старое, а нужное (075).

    ПЕРЕСЧЁТ ТРОГАЕТ ТОЛЬКО ЗАХОДЫ. Покрытие за прошлый день заново не прочесть:
    витрина публикует ТЕКУЩЕЕ число, а не вчерашнее. Поэтому пересчёт заменяет
    заходы дня и оставляет его покрытие как было — иначе ряд терял бы вчерашнее
    покрытие на каждом заходе, и «ряда всё ещё нет» получалось бы само собой (045).
    """
    edge = str(
        (
            datetime.fromisoformat(f"{today}T00:00:00+00:00")
            - timedelta(days=bounds.window_days - 1)
        ).date()
    )
    days: dict[str, Any] = {day: dict(rows) for day, rows in known.items() if edge <= day <= today}
    for day, runs in fresh.items():
        if edge <= day <= today:
            days.setdefault(day, {})["runs"] = runs
    # Условия о крае здесь нет намеренно: окно хранения не бывает короче суток
    # (это проверяет `Bounds.read`), значит нынешний день в окно входит всегда.
    # Условие, которое не может быть ложным, читается как проверка и ею не
    # является (075; нашёл внешний взгляд, `a6a8a5f`).
    if coverage is not None:
        days.setdefault(today, {})["coverage"] = coverage
    return dict(sorted(days.items()))


def coverage_now(repo: str) -> float | None:
    """Доля покрытых строк с витрины проекта; ``None`` — НЕ ПРОЧИТАНО.

    ЧИСЛО НЕ СЧИТАЕТСЯ ЗДЕСЬ. Покрытие считает шаг значков прогоном набора под
    счётчиком и публикует в `facts.json`; второй счёт того же разошёлся бы с
    первым молча
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    Ряд его только ЗАПИСЫВАЕТ, и в этом весь смысл: у порога покрытия нет ряда, а
    назначить порог по одной точке значит решать на непроверенном замере
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).

    «НЕ ПРОЧИТАНО» ОСТАЁТСЯ СОСТОЯНИЕМ, А НЕ НУЛЁМ. Витрина отвечает об этом
    полем `read`, и подставить ноль вместо незнания значило бы записать в ряд
    обвал покрытия там, где его не было (045). День без покрытия остаётся днём
    без покрытия, и отчёт это называет.
    """
    try:
        facts = ghrest.raw_json(FACTS_URL.format(repo=repo))
    except (ghrest.TransportError, OSError, ValueError):
        return None
    said = facts.get("coverage") or {}
    if not said.get("read"):
        return None
    try:
        return round(float(said.get("percent") or 0.0), 1)
    except (TypeError, ValueError):
        return None


def since_day(today: str, back: int) -> str:
    """День, от которого идёт пересчёт: `back` дней назад, считая нынешний."""
    return str(
        (datetime.fromisoformat(f"{today}T00:00:00+00:00") - timedelta(days=back - 1)).date()
    )


def runs_of(days: dict[str, Any], day: str) -> dict[str, Any]:
    """Заходы одного дня. Строка дня несёт два поля, и это разные вопросы."""
    return dict((days.get(day) or {}).get("runs") or {})


def total(days: dict[str, Any], field: str) -> int:
    """Сумма поля по всему ряду."""
    return sum(int(row.get(field, 0)) for day in days for row in runs_of(days, day).values())


def reds(days: dict[str, Any]) -> Counter[str]:
    """Сколько раз каждое имя джоба краснело за весь ряд."""
    found: Counter[str] = Counter()
    for day in days:
        for row in runs_of(days, day).values():
            for name, count in (row.get("red_jobs") or {}).items():
                found[name] += int(count)
    return found


def whose(days: dict[str, Any]) -> Counter[str]:
    """Чьи шаги роняли прогоны за весь ряд: свои против площадкиных.

    ЭТО И ЕСТЬ ТОТ ВТОРОЙ ШАГ, РАДИ КОТОРОГО ОТЧЁТ СОБИРАЕТСЯ. Владелец назвал
    его прямо: «у других проектов такие случаи были, просто у данного не
    происходило — нужно собирать статистику, и тогда возможно что-то увидим».
    Пока счёт говорит «площадки: 0», теория подтверждения не имеет, и это
    наблюдение, а не пробел
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md),
    [049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).
    """
    found: Counter[str] = Counter()
    for day in days:
        for row in runs_of(days, day).values():
            for name, count in (row.get("red_whose") or {}).items():
                found[name] += int(count)
    return found


def minutes_of(days: dict[str, Any], name: str, day: str) -> float:
    """Среднее время захода прогона `name` в минутах за один день; ноль — не было."""
    row = runs_of(days, day).get(name) or {}
    timed = int(row.get("timed", 0))
    return round(int(row.get("seconds", 0)) / timed / 60, 1) if timed else 0.0


def covered(days: dict[str, Any]) -> list[tuple[str, float]]:
    """Дни, у которых покрытие ПРОЧИТАНО, и само число — по возрастанию дня."""
    return [
        (day, float(row["coverage"]))
        for day, row in sorted(days.items())
        if isinstance(row, dict) and row.get("coverage") is not None
    ]


def report(days: dict[str, Any], bounds: Bounds, today: str) -> str:
    """Отчёт по ряду: ответы на названные вопросы ЧИСЛОМ С ДАТОЙ.

    Отчёт — не витрина: он существует потому, что логи прогонов из части окон не
    читаются, а живой файл ряда читается по прямой ссылке. Число без даты
    устаревает молча (005), поэтому у каждого ответа стоит окно, за которое он
    получен.
    """
    runs, cancelled = total(days, "runs"), total(days, "cancelled")
    red = total(days, "red")
    known = sorted(days)
    share = round(100 * cancelled / runs, 1) if runs else 0.0
    lines = [
        "# Ряд прогонов: чем отвечает конвейер",
        "",
        "> **Читатель:** окно и владелец. Здесь ответы о работе конвейера числом,",
        "> а не по памяти. Источник — `runs.json` в этой же ветке.",
        "",
        f"Собрано {today}. Дней в ряду: {len(known)}"
        + (f" ({known[0]} — {known[-1]})" if known else "")
        + f", окно хранения {bounds.window_days} дней, пересчёт последних"
        f" {bounds.recount_days}.",
        "",
        "## Сколько заходов гаснет впустую",
        "",
        f"Отменённых {cancelled} из {runs} завершённых заходов — **{share} %**. Отмена здесь"
        " штатна: группа отмены гасит устаревший заход на той же голове, и это цена"
        " свежести, а не поломка.",
        "",
        "## Какое имя чаще краснеет",
        "",
    ]
    top = reds(days).most_common(5)
    if top:
        lines += [f"Красных заходов {red}, и красное разошлось по джобам так:", ""]
        lines += [f"- `{name}` — {count}" for name, count in top]
        lines += [""]
    else:
        lines += [
            f"Красных заходов за окно {red}, и ни одного имени джоба назвать нельзя:"
            " площадка отдаёт джобы только пока хранит заход.",
            "",
        ]
    lines += ["## Дефект это или осечка площадки", ""]
    чьи = whose(days)
    if not чьи:
        lines += [
            "Ни одного разобранного падения: у красных джобов за окно площадка не"
            " отдала шагов, и сказать, чей шаг упал, не из чего. Пусто здесь значит"
            " «не прочитано», а не «площадка не виновата» (045).",
            "",
        ]
    else:
        свои, площадки = чьи.get(WHOSE_OWN, 0), чьи.get(WHOSE_SERVICE, 0)
        lines += [
            f"Разобрано падений {свои + площадки}: на СВОЁМ шаге — {свои}, на служебном"
            f" шаге площадки (чекаут, установка, окружение) — {площадки}.",
            "",
        ]
        if not площадки:
            lines += [
                "**Служебных падений за окно ноль.** Значит теория «у всех джобов одна"
                " ошибка платформы, и перезапускать надо все» на нашем ряду"
                " подтверждения НЕ имеет: каждое красное считало дерево. У соседей по"
                " семье такие отказы бывают — потому счёт и ведётся, а не выводится"
                " из памяти (044, 049).",
                "",
            ]
    lines += ["## Растёт ли время прогона", ""]
    if len(known) >= 2:
        first, last = known[0], known[-1]
        было, стало = minutes_of(days, "ci", first), minutes_of(days, "ci", last)
        lines += [
            f"Средний заход `ci`: {было} мин {first} → {стало} мин {last}. Два дня — это"
            " не ряд, и вывода здесь пока нет; ответ появится, когда дней станет"
            " достаточно, а не когда его захочется получить (044).",
            "",
        ]
    else:
        lines += ["Дней в ряду меньше двух — сравнивать нечего.", ""]
    ряд = covered(days)
    lines += ["## Растёт ли покрытие", ""]
    if not ряд:
        lines += [
            "Ни одного прочитанного числа: витрина отвечает «не прочитано», и ряд честно"
            " пуст. Ноль вместо незнания записал бы обвал покрытия там, где его не было"
            " (045).",
            "",
        ]
    else:
        (первый, было), (последний, стало) = ряд[0], ряд[-1]
        lines += [
            f"Прочитанных дней {len(ряд)} из {len(known)}: {было} % {первый} → {стало} %"
            f" {последний}.",
            "",
            "**Порога покрытия здесь нет, и это не забывчивость.** Порог — решение"
            " владельца, и берётся он из РЯДА («не ниже достигнутого», только вверх,"
            " 050), а не из одной точки. Ряд для этого и копится.",
            "",
        ]
    lines += [
        "## Чего здесь нет",
        "",
        "Счёта миганий: «красное, затем зелёное на той же голове» считает шаг 9 и"
        " ведёт реестр #99. Второй счёт того же разошёлся бы с первым молча (022).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: пересчитывает молодые дни ряда и пишет ряд с отчётом."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="владелец/имя"
    )
    parser.add_argument("--store", required=True, help="файл ряда (runs.json) — читается и пишется")
    parser.add_argument("--report", default="", help="куда положить отчёт по ряду")
    parser.add_argument("--bounds", default=str(BOUNDS_FILE), help="объявление границ ряда")
    parser.add_argument("--apply", action="store_true", help="писать файлы, а не только считать")
    args = parser.parse_args(argv)
    announce(not args.apply)

    store = Path(args.store)
    try:
        if not args.repo:
            raise NotRun("не сказано, чей ряд считать (--repo) — предмет не найден (075)")
        bounds = Bounds.read(Path(args.bounds))
        token = ghrest.token_from_env()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        known: dict[str, Any] = {}
        if store.exists():
            said = json.loads(store.read_text(encoding="utf-8"))
            known = dict(said.get("days") or {})
        fresh = swept(args.repo, token, since_day(today, bounds.recount_days))
        # Покрытие берётся ОДИН раз и только за нынешний день: витрина публикует
        # текущее число, и записать его во вчерашний день значило бы подделать
        # замер, которого не было (005).
        days = merge(known, fresh, bounds, today, coverage_now(args.repo))
        body = {
            "_": "Ряд прогонов конвейера: день → прогон → числа. Ведёт scripts/runs_series.py.",
            "window_days": bounds.window_days,
            "recount_days": bounds.recount_days,
            "updated": datetime.now(UTC).isoformat(timespec="seconds"),
            "days": days,
        }
    except NotRun as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except ghrest.TransportError as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    except json.JSONDecodeError as exc:
        print(f"заход не отработал: прежний ряд не читается ({store}): {exc}", file=sys.stderr)
        return EXIT_BROKEN

    said = report(days, bounds, today)
    if args.apply:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.report:
            Path(args.report).write_text(said + "\n", encoding="utf-8")
    print(
        f"дней в ряду {len(days)}, из них пересчитано {len(fresh)}; "
        f"заходов за окно {total(days, 'runs')}" + ("" if args.apply else " — записи не было")
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
