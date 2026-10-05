"""Сверяет обязательный контекст защиты ветки с тем, что выдаёт дерево.

Настройка защиты живёт **вне дерева**: её не видит ни ревью, ни прогон. Поэтому
расхождение между именем джоба и именем в списке обязательных не ловится ничем
и обнаруживается простоем — у соседнего проекта защита требовала контекста,
которого не выдавал ни один прогон, и не сливалось ничего при зелёных
проверках.

Что проверяется:

* в списке обязательных **ровно одно** имя — список, перечисляющий матрицу,
  ломается при добавлении версии;
* это имя выдаёт джоб, объявленный в дереве прогонов;
* матричные имена в список не попали;
* способ слияния ограничен уплотнением — решение ``006``, а держится оно тоже
  настройкой вне дерева.

ПРО СПОСОБ СЛИЯНИЯ — ЭТО ВТОРАЯ НАСТРОЙКА ТОГО ЖЕ РОДА, И МЕСТО ЕЙ ЗДЕСЬ.
Проект решил сливать уплотнением (``docs/decisions/006-merge-by-squash.md``), а
площадка по-прежнему разрешает merge-коммит и перестановку. Гейт
``tests/test_squash_only.py`` ловит нарушение ПОСЛЕ слияния — по истории общей
ветки, когда чинить уже нечем. Дешёвый способ предотвратить его вместо того,
чтобы ловить повторение, — снять лишние кнопки в настройках; сделать это может
только владелец, а увидеть разрыв — эта сверка. Нашёл внешний взгляд на #167.

ТОКЕНЫ У ДВУХ ПОЛОВИН РАЗНЫЕ, И ЭТО ЗАМЕР. Набор правил общей ветки площадка
отдаёт любому токену. Настройки слияния (`allow_*`) — нет: токену прогона с
``contents: read`` она их не отдаёт (замер 29.09.2026, #953). Без токена
владельца вторая половина не выполняется и говорит об этом исходом ``2``, а не
зеленеет: несказанный ключ — «не прочитано», а не «выключено».

Исходы (правило 039): ``0`` совпадает · ``2`` не отработало · ``3``
расхождение.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Final

import ghrest
import paths
import protection
import yaml

#: Где живёт сводный джоб. Файл НЕ назван одним именем намеренно: 11.09.2026
#: гейт переехал из `ci.yml` в собственный прогон, чтобы группа отмены `ci` не
#: гасила обязательный контекст, — и сверка, прибитая к имени файла, сломалась
#: бы этим переездом. Ищется джоб по ИМЕНИ во всех прогонах: имя и есть предмет
#: договора с защитой ветки, а файл — его адрес, и адрес вправе меняться (168).
GATES_DIR: Final = paths.WORKFLOWS

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
#: Единицу отдаёт сам Python при необработанном сбое, поэтому объявленным
#: состоянием она быть не может: иначе сломанный механизм читается как
#: работающий. Объявленные исходы — 0, 2 и 3; всё прочее отказ (068).
EXIT_FINDINGS: Final = 3


class NotRun(RuntimeError):
    """Сверка не отработала: третий исход, а не «совпадает»."""


def declared_context(summary_job: str) -> str:
    """Отдаёт имя контекста, которое выдаст сводный джоб дерева.

    Джоб ищется ПО ИМЕНИ во всех прогонах, а не по адресу файла: имя — предмет
    договора с защитой ветки, файл — его адрес, и адрес вправе меняться. Найтись
    он обязан ровно в одном месте: два джоба с именем обязательного контекста
    дали бы на голове две записи, и защита ветки зачла бы любую из них (187).
    """
    if not GATES_DIR.is_dir():
        raise NotRun(f"нет каталога прогонов: {GATES_DIR}")
    found: list[tuple[Path, Any]] = []
    for path in sorted(GATES_DIR.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        jobs = document.get("jobs") or {}
        if summary_job in jobs:
            found.append((path, jobs[summary_job] or {}))
    if not found:
        raise NotRun(
            f"ни один прогон в {GATES_DIR} не объявляет джоба «{summary_job}» — "
            "предмет сверки не найден (075)"
        )
    if len(found) > 1:
        where = ", ".join(path.name for path, _ in found)
        raise NotRun(
            f"джоб «{summary_job}» объявлен дважды ({where}): на голове окажутся две "
            "записи с именем обязательного контекста, и защита зачтёт любую (187)"
        )
    job = found[0][1]
    if "strategy" in job:
        raise NotRun(
            f"джоб «{summary_job}» матричный: матричные имена в список обязательных "
            "не попадают никогда"
        )
    # Имя контекста — это `name:` джоба, а если его нет, идентификатор джоба.
    return str(job.get("name") or summary_job)


def live_contexts(repo: str, branch: str, token: str) -> tuple[list[str], bool]:
    """Обязательные контексты ветки и признак «защита есть, но другой формы».

    ЧИТАЕТСЯ ТАМ, ГДЕ ЗАЩИТА ЖИВЁТ. Прежде здесь спрашивалась КЛАССИЧЕСКАЯ
    защита (`branches/<ветка>/protection/...`), а проект защищён НАБОРОМ ПРАВИЛ —
    и та же настройка по второму адресу выглядела отсутствующей. Первый же
    настоящий заход сверки объявил находку «у ветки нет обязательных контекстов»
    на здоровой настройке. Разбор и общее чтение — `scripts/protection.py` (090).

    Пустой набор правил на ЗАЩИЩЁННОЙ ветке — это «защита другой формы», а не
    «защиты нет»: у соседей по семье защита классическая, и выдать одно за другое
    значило бы отправить человека чинить не то
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md),
    [154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
    """
    try:
        rules = protection.live(repo, branch, token)
        if rules:
            return protection.contexts(rules), False
        return [], protection.guarded(repo, branch, token)
    except protection.NotRead as exc:
        raise NotRun(str(exc)) from exc


#: Способ слияния, объявленный решением 006. Остальные кнопки площадки лишние:
#: пока они включены, слить мимо очереди можно одним щелчком, и гейт узнает об
#: этом по истории, а не до неё.
MERGE_WAYS: Final = {
    "allow_merge_commit": "merge-коммит",
    "allow_rebase_merge": "перестановка",
}


#: Почему площадка молчит о настройках слияния. Токен здесь не известен:
#: кнопка передаёт токен владельца первым, а без него — токен прогона, и дрейф
#: передаёт токен владельца (#953), — поэтому причина названа через права, а
#: не через то, чей токен (взгляд на #957).
UNSAID_REASON: Final = (
    "у этого токена нет прав на настройки репозитория; токену прогона их не отдают никогда (#953)"
)


def merge_settings(repo: str, token: str) -> dict[str, Any]:
    """Поля способов слияния из настроек репозитория — и только они.

    Отдельно от разбора, потому что дрейф читает их ОТДЕЛЬНЫМ шагом: секрет
    владельца получает только этот запрос, а разбор идёт без секрета (#993).
    Отсутствующий у площадки ключ в ответ не попадает и разбором читается как
    «не сказано», а не как «выключено».
    """
    try:
        answer = ghrest.request("GET", f"repos/{repo}", token) or {}
    except ghrest.TransportError as exc:
        raise NotRun(f"настройки репозитория не прочитаны: {exc}") from exc
    return {key: answer[key] for key in MERGE_WAYS if key in answer}


#: Секрет владельца, которым читаются настройки слияния. Тот же секрет
#: объявляют у себя дрейф и очередь — общей константы нет, это дубль (071).
OWNER_TOKEN_ENV: Final = "MERGE_QUEUE_TOKEN"

#: Что говорит половина «способ слияния», когда заход с секретом не отработал
#: или не звался вовсе: файла нет — и это молчание с причиной, а не «сошлось».
UNPASSED: Final = (
    "настройки слияния не переданы: заход с секретом владельца "
    "(`--save-merge-ways`) не отработал или не звался (#993)"
)


def merge_settings_said(repo: str, owner_token: str) -> dict[str, Any]:
    """Поля способов слияния токеном владельца — либо причина, по которой их нет.

    ЧИТАЕТСЯ ТОКЕНОМ ВЛАДЕЛЬЦА, И ТОЛЬКО ИМ. Токену прогона площадка полей
    `allow_*` не отдаёт никогда (замер 29.09.2026), и запасной ход на него дал
    бы ту же немоту, только позже. Секрета нет — причина приходит раньше
    запроса, как у открытия изменения (взгляд на #865).
    """
    if not owner_token:
        return {
            "reason": f"{OWNER_TOKEN_ENV} не задан — настройки слияния читает только токен "
            "владельца, токену прогона площадка полей allow_* не отдаёт (#953)"
        }
    try:
        return {"settings": merge_settings(repo, owner_token)}
    except NotRun as exc:
        return {"reason": str(exc)}


def save_merge_settings(repo: str, owner_token: str, path: Path) -> None:
    """Единственный заход с секретом владельца: один запрос, в файл — поля `allow_*`.

    СЕКРЕТ ПОЛУЧАЕТ ОДИН ШАГ (#993). Прежде `MERGE_QUEUE_TOKEN` лежал в
    окружении всего захода — у дрейфа и у этой сверки. Теперь секрет получает
    отдельный шаг прогона, а всё остальное идёт без секрета вовсе. Это держит
    устройство. Что этот шаг делает ровно один запрос и кладёт в файл только
    поля способов слияния, держит код — эта функция и ветка
    `--save-merge-ways`, а не права (взгляд на #1117). Цена из #953 прежняя:
    токен пишущий, и сузилось время его жизни в заходе, а не его права. Читают
    файл оба механизма — дрейф и эта сверка, — и разбор у файла один (090).
    """
    path.write_text(
        json.dumps(merge_settings_said(repo, owner_token), ensure_ascii=False), encoding="utf-8"
    )


def load_merge_settings(path: Path | None) -> dict[str, Any]:
    """Сказанное заходом с секретом; файла нет или он испорчен — причина, а не пустота."""
    if path is None or not path.is_file():
        return {"reason": UNPASSED}
    try:
        said = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"reason": f"настройки слияния не прочитаны из {path}: {exc}"}
    return said if isinstance(said, dict) else {"reason": f"в {path} не словарь"}


def extra_ways_said(said: dict[str, Any]) -> list[str]:
    """Лишние способы слияния по сказанному чтением; причины вместо полей — `NotRun`."""
    settings = said.get("settings")
    if not isinstance(settings, dict):
        raise NotRun(str(said.get("reason") or UNPASSED))
    return extra_ways(settings)


def merge_ways(repo: str, token: str) -> list[str]:
    """Лишние способы слияния, оставшиеся включёнными у площадки."""
    return extra_ways(merge_settings(repo, token))


def extra_ways(answer: dict[str, Any]) -> list[str]:
    """Лишние способы слияния по прочитанным полям; несказанное — отказ, а не «выключено»."""
    # НЕ СКАЗАНО — НЕ ЗНАЧИТ ВЫКЛЮЧЕНО. Поля `allow_*` площадка отдаёт не всякому
    # вызывающему, и отсутствующий ключ, прочитанный как `False`, делал бы
    # непрочитанное «сошлось» каждую ночь (045). Нашёл внешний взгляд на #951.
    unsaid = [key for key in MERGE_WAYS if not isinstance(answer.get(key), bool)]
    if unsaid:
        raise NotRun(
            f"настройки репозитория не прочитаны: площадка не сказала {', '.join(unsaid)} — "
            + UNSAID_REASON
        )
    return [said for key, said in MERGE_WAYS.items() if answer[key]]


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает исход и возвращает его код."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--branch", default=paths.TRUNK)
    parser.add_argument("--summary-job", default="ci-complete")
    parser.add_argument(
        "--save-merge-ways",
        type=Path,
        metavar="ФАЙЛ",
        help=f"только прочитать настройки слияния токеном {OWNER_TOKEN_ENV} и положить в файл",
    )
    parser.add_argument(
        "--merge-ways-from",
        type=Path,
        metavar="ФАЙЛ",
        help="настройки слияния, положенные заходом --save-merge-ways",
    )
    args = parser.parse_args(argv)

    if args.save_merge_ways:
        try:
            save_merge_settings(
                args.repo, os.environ.get(OWNER_TOKEN_ENV, ""), args.save_merge_ways
            )
        except OSError as exc:
            print(f"сверка не отработала: настройки слияния не записаны: {exc}", file=sys.stderr)
            return EXIT_BROKEN
        print(f"настройки слияния положены: {args.save_merge_ways}")
        return EXIT_OK

    try:
        expected = declared_context(args.summary_job)
    except NotRun as exc:
        print(f"сверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    # ТОКЕН ВЛАДЕЛЬЦА — ПЕРВЫМ, ЛЮБОЙ ДРУГОЙ — ЗАПАСОМ. Набор правил площадка
    # отдаёт любому токену, и первой половине прав владельца не нужно. Настройки
    # слияния — только токену с правами на репозиторий (замер 29.09.2026, #953).
    # Замер 15.09.2026 касался ДВУХ АДРЕСОВ НАБОРА ПРАВИЛ (`scripts/protection.py`)
    # и верен; ошибкой было распространить его на `repos/{repo}`, которого он
    # не читал. Без токена владельца вторая половина говорит «не прочитано».
    # С файлом настроек секрета в окружении нет вовсе: наборам правил хватает
    # токена прогона (#993, взгляд на #1117).
    token = (
        ghrest.token_from_env()
        if args.merge_ways_from
        else os.environ.get(OWNER_TOKEN_ENV) or ghrest.token_from_env()
    )

    try:
        actual, guarded_otherwise = live_contexts(args.repo, args.branch, token)
    except NotRun as exc:
        print(f"сверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not actual and guarded_otherwise:
        print(
            f"находка: ветка «{args.branch}» защищена, но не набором правил — эта сверка\n"
            "читает набор правил и о классической защите сказать ничего не может.\n"
            "Либо переведите защиту в набор правил, либо научите сверку второй форме:\n"
            "молча зеленеть на непрочитанном она не будет.",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    if not actual:
        print(
            f"находка: у ветки «{args.branch}» нет обязательных контекстов.\n"
            f"Дерево выдаёт «{expected}» — поставьте его единственным обязательным.",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    if actual != [expected]:
        print(
            f"находка: защита требует {actual}, а дерево выдаёт «{expected}».\n"
            "В списке обязано быть ровно одно имя, и это имя сводного джоба:\n"
            "перечисление матрицы ломается при добавлении версии, а имя, которого\n"
            "не выдаёт никто, оставляет изменение в вечном ожидании.",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    print(f"совпадает: защита «{args.branch}» требует ровно «{expected}»")

    try:
        extra = (
            extra_ways_said(load_merge_settings(args.merge_ways_from))
            if args.merge_ways_from
            else merge_ways(args.repo, token)
        )
    except NotRun as exc:
        print(f"сверка не отработала: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if extra:
        print(
            f"находка: площадка разрешает {', '.join(extra)} — а решение 006 говорит\n"
            "сливать уплотнением. Пока кнопки включены, слить мимо очереди можно одним\n"
            "щелчком, и гейт узнает об этом по истории общей ветки, когда чинить уже\n"
            "нечем. Снимите лишние способы в настройках репозитория.",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    print("способ слияния ограничен уплотнением — как и решено в 006")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
