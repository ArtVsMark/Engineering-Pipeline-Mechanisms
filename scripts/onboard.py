#!/usr/bin/env python3
"""Команда подключения: собирает потребителю заготовку вызова, а не инструкцию.

ОТДАЁТСЯ НАРУЖУ: этим заходом проект подключают к себе.

ПОЧЕМУ ЭТО МЕХАНИЗМ, А НЕ АБЗАЦ В README. Порядок подключения, живущий прозой,
исполняется по-разному каждым, кто его прочёл: один забудет объявить класс
проверки, другой напишет имя записи голым, третий прибьётся к подвижной метке
вместо версии. Ровно так и разошлись конвейеры семьи — замер копий в договоре,
`docs/use/pipeline.md`
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

СОСТАВ ВЫВОДИТСЯ ИЗ ДЕРЕВА, А НЕ ПЕРЕЧИСЛЯЕТСЯ ЗДЕСЬ. Шаги берутся те, что
помечены маркером «отдаётся наружу» (`scripts/check_shipped.py`), прибивка —
тег ВЫПУСКА из истории (`pin_of` ниже говорит, почему не `CONTRACT_VERSION`).
Второй список тех же имён отстал бы на первом же вынесенном
шаге, и отстал бы молча
([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md),
[049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).

ШАГ КОНВЕЙЕРА И УПРАВЛЯЮЩИЙ МЕХАНИЗМ ПОДКЛЮЧАЮТСЯ ПО-РАЗНОМУ, И РАЗНИЦА
ВЫВОДИТСЯ ИЗ ДЕРЕВА (#993). Шаг конвейера зовёт `ci.yml` — его заготовка
джоб в своём `ci.yml`. Управляющий механизм (план работ и соседи) зовёт свой
прогон со своими событиями и правами: джобом в `ci.yml` он шёл бы на каждом
изменении и без права записи в задачу. Поэтому шаг, у которого в нашем
дереве есть СВОЙ вызывающий прогон, печатается этим прогоном целиком, с
адресом по тегу вместо внутреннего пути (`own_callers`). Второго списка
таких шагов нет: вызывающий и есть ответ.

ИМЯ ЗАПИСИ ПРОВЕРКИ СОСТАВНОЕ, И ЗАГОТОВКА НАЗЫВАЕТ ЕГО ПРАВИЛЬНО. Площадка
зовёт запись вызванного джоба `<имя вызывающего> / <имя вызванного>` — замер
прогоном на живой площадке. Потребитель, написавший в своём ответе голое имя,
получил бы сводный гейт, ждущий записи, которой никто не выдаст
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

ЗАГОТОВКА НЕ РЕШАЕТ ЗА ПОТРЕБИТЕЛЯ, КАКОЙ КЛАСС У ПРОВЕРКИ. Класс — свойство
потребителя, а не механизма: объём документа обязателен там, где документ
выпускается наружу, и совещателен там, где он внутренний
(174).
Поэтому все шаги выходят с классом «в очереди разбора» — объявленным
состоянием, а не молчанием, — и потребитель отвечает по каждому сам.

ЗАГОТОВКА НЕ ПЕЧАТАЕТСЯ, ПОКА ПРИБИВКА ЕЁ НЕ НЕСЁТ. Вызов по адресу с
версией работает ровно тогда, когда названный тег этот файл содержит, и это
НЕ следует из того, что файл лежит у нас: работа слита, выпуск не нарезан —
самый обычный день. Замер 20.09.2026: помечено наружу одиннадцать файлов, в
выпуске `v1.1.0` их ноль, то есть заготовка была нерабочей целиком, и узнал
бы об этом потребитель на СВОЁМ красном
([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
Третий исход называет предмет: нарезать выпуск
([158](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/158-the-third-outcome-names-its-subject.md)).

ЧЕГО ЗАХОД НЕ ДЕЛАЕТ: не правит чужое дерево и не трогает защиту ветки.
По умолчанию он печатает, а потребитель кладёт. С ключом `--write` (решение
владельца 04.10.2026 по #992, вариант 3) он кладёт заготовку сам — но только
в свободные пути: файл, который уже есть, называется, и не пишется ни один.
Иначе «подключено» и «подправлено на ходу» стали бы неотличимы. Сводный гейт
`ci-complete.yml` заготовка не кладёт: он пока копируется, а не зовётся
(`tests/test_portable.py::STILL_COPIED`, вынос — #993).

Исходы (правило 039): ``0`` заготовка собрана · ``2`` не отработал ·
``3`` отдавать нечего: ни один шаг не помечен · ``4`` прибивка не несёт
помеченного: выпуск отстал от дерева · ``5`` с ``--write``: путь заготовки в
дереве потребителя уже занят.
"""

import argparse
import sys
from pathlib import Path
from typing import Final

import check_shipped
import paths
import pipeline_checks as policy
import version

EXIT_OK: Final = 0
EXIT_BROKEN: Final = 2
EXIT_NOTHING: Final = 3
#: Прибивка есть, а помеченного в ней нет. Отдельный исход, а не «нечего
#: отдавать»: предмет тот же, причина и выход РАЗНЫЕ (039, 104).
EXIT_UNREACHABLE: Final = 4
#: Заход с `--write` нашёл файл, который положил бы: чужое не перезаписывается,
#: а называется (#992). Выход — свой: убрать файл или сверить его руками.
EXIT_OCCUPIED: Final = 5

#: Приставка вынесенного шага. Помеченным бывает и не шаг — пакет, действие, —
#: а заготовку вызова собирают только из прогонов, которые ЗОВУТ.
STEP_PREFIX: Final = "step-"
#: Что читается ответом «выпусков ещё не было». Пустота тут законна и обязана
#: быть названа, а не выдана за версию (154).
NO_RELEASE: Final = "выпусков ещё не было"
#: Внутренний путь, которым наш прогон зовёт наш же шаг. В заготовке он
#: заменяется адресом с тегом: потребитель ходит внешним путём.
LOCAL_CALL: Final = "./.github/workflows/"
#: Прогон, джобами которого подключаются шаги конвейера.
PIPELINE_FLOW: Final = "ci.yml"
#: Сводный гейт: заготовка его не кладёт, а называет — он пока копируется.
SUMMARY_FLOW: Final = "ci-complete.yml"


class NotRun(RuntimeError):
    """Заход не отработал: третий исход, а не пустая заготовка."""


def steps(root: Path) -> list[str]:
    """Имена вынесенных шагов — из пометок дерева, а не списком.

    Имя шага — это имя его файла без приставки и расширения, и оно же имя
    джоба внутри: составное имя записи собирается из них двоих.
    """
    found = [
        Path(said).stem[len(STEP_PREFIX) :]
        for said in check_shipped.shipped(root)
        if Path(said).name.startswith(STEP_PREFIX) and Path(said).suffix in {".yml", ".yaml"}
    ]
    return sorted(found)


def own_callers(root: Path, names: list[str]) -> dict[str, Path]:
    """Шаги со СВОИМ вызывающим прогоном в нашем дереве: имя шага → файл прогона.

    Вызывающий ищется по внутреннему пути `uses: ./.github/workflows/step-<имя>.yml`
    у прогонов дерева, кроме самих шагов. Нечитаемый прогон — третий исход, а
    не «вызывающего нет»: молча он перевёл бы управляющий механизм в джоб
    `ci.yml` (045).

    ЗОВЁТ `ci.yml` — ЗНАЧИТ ШАГ КОНВЕЙЕРА, кто бы ещё его ни звал (взгляд на
    #1050). Иначе любой соседний прогон, позвавший шаг локально, молча вывел бы
    его из джобов `ci.yml` в заготовке и из пробы передачи. Управляющий механизм
    — шаг, которого `ci.yml` не зовёт, а зовёт ровно один свой прогон. Два своих
    прогона у одного шага — неоднозначность, и это отказ, а не выбор первого.
    """
    wanted = {f"{LOCAL_CALL}{STEP_PREFIX}{one}.yml": one for one in names}
    callers: dict[str, list[Path]] = {}
    for flow in sorted((root / paths.WORKFLOWS).glob("*.yml")):
        if flow.name.startswith(STEP_PREFIX):
            continue
        try:
            said = policy.run_of(flow)
        except policy.BadPolicy as exc:
            raise NotRun(f"{flow.name} не прочитан: {exc}") from exc
        for job in (said.get("jobs") or {}).values():
            name = wanted.get(str((job or {}).get("uses") or ""))
            if name is not None and flow not in callers.setdefault(name, []):
                callers[name].append(flow)
    found: dict[str, Path] = {}
    for name, flows in callers.items():
        if any(flow.name == PIPELINE_FLOW for flow in flows):
            continue
        if len(flows) > 1:
            raise NotRun(
                f"шаг {STEP_PREFIX}{name} зовут несколько своих прогонов "
                f"({', '.join(flow.name for flow in flows)}) — какой из них заготовка, неизвестно"
            )
        found[name] = flows[0]
    return found


def own_kit(flow: Path, name: str, repo: str, pin: str) -> str:
    """Свой прогон управляющего механизма — с адресом по тегу вместо внутреннего пути.

    ПОДМЕНА СВЕРЯЕТСЯ С РАЗБОРОМ (взгляд на #1050). Вызывающего находит разбор
    YAML, а переписывается текст; вызов, записанный иной формой (`uses:
    "./…"`, два пробела), разбор признал бы, а подмена пропустила бы — и
    внутренний путь молча ушёл бы в заготовку. Поэтому число подмен обязано
    равняться числу вызовов по разбору; не равно — отказ с названной формой.
    """
    inner = f"uses: {LOCAL_CALL}{STEP_PREFIX}{name}.yml"
    outer = f"uses: {repo}/.github/workflows/{STEP_PREFIX}{name}.yml@{pin}"
    try:
        jobs = (policy.run_of(flow).get("jobs") or {}).values()
    except policy.BadPolicy as exc:
        raise NotRun(f"{flow.name} не прочитан: {exc}") from exc
    calls = sum(
        1
        for job in jobs
        if str((job or {}).get("uses") or "") == f"{LOCAL_CALL}{STEP_PREFIX}{name}.yml"
    )
    text = flow.read_text(encoding="utf-8")
    if text.count(inner) != calls:
        raise NotRun(
            f"{flow.name}: вызов {STEP_PREFIX}{name} записан не формой «{inner}» — "
            "заготовка не перепишет его на адрес по тегу, а внутренний путь потребителю не годится"
        )
    return text.replace(inner, outer)


def thin_ci(names: list[str], repo: str, pin: str) -> str:
    """Тонкий `ci.yml` потребителя: вызовы шагов по тегу — и ничего своего (#992).

    РЕШЕНИЕ ВЛАДЕЛЬЦА 04.10.2026 по #992, вариант 3. «Что проверяется» у
    потребителя — набор этих вызовов, а класс каждой проверки — его
    `.pipeline.yml`. Сверяет одно с другим общий шаг `pipeline`
    (`check_pipeline.py`): у каждой проверки дерева есть ответ, у каждого
    ответа — проверка. Поэтому вызовы и есть данные, и второго списка «что
    включено» не заводится.

    СОБЫТИЯ И ОЧЕРЕДЬ — КАК У НАШЕГО `ci.yml` (взгляд на #1114). `push` на
    общую ветку нужен заготовке дежурного (`main-red.yml`): она ждёт
    `workflow_run` прогона `ci` на `main`, и без него сигнал не пришёл бы ни
    разу. Голова в группе очереди (179): последнее слово остаётся за прогоном
    последнего коммита, а не устаревшего.

    Пустой набор — отказ: прогон без джобов площадка не примет, а заход
    назвал бы его готовым.
    """
    if not names:
        raise NotRun("шагов к подключению в ci.yml нет — тонкий ci.yml был бы прогоном без джобов")
    head = (
        "# Тонкий вызов шагов конвейера: собран `scripts/onboard.py` поставщика.\n"
        "# Что проверяется — эти вызовы; класс каждой проверки — `.pipeline.yml`.\n"
        "# Сверяет одно с другим шаг `pipeline`: правьте оба вместе.\n"
        "name: ci\n\n"
        "on:\n"
        "  push:\n"
        f"    branches: [{paths.TRUNK}]\n"
        "  pull_request:\n"
        "    types: [opened, synchronize, reopened, labeled, unlabeled, edited]\n"
        "  workflow_dispatch:\n\n"
        "permissions:\n"
        "  contents: read\n"
        "  checks: read\n"
        "  pull-requests: read\n"
        "  issues: read\n\n"
        "concurrency:\n"
        "  group: ci-${{ github.event.pull_request.number || github.ref }}"
        "-${{ github.event.pull_request.head.sha || github.sha }}\n"
        "  cancel-in-progress: true\n\n"
        "jobs:\n"
    )
    return head + "\n".join(caller(one, repo, pin) for one in names)


def occupied(root: Path, files: dict[Path, str]) -> list[Path]:
    """Файлы заготовки, которые в дереве потребителя уже есть: их заход не трогает."""
    return sorted(path for path in files if (root / path).exists())


def lay(root: Path, files: dict[Path, str]) -> None:
    """Кладёт заготовку в дерево потребителя; занятое проверяет зовущий (`occupied`)."""
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")


def pin_of(root: Path) -> str:
    """Тег ВЫПУСКА, к которому прибивается потребитель, — из истории.

    НЕ `CONTRACT_VERSION`, И РАЗНИЦА СТОИЛА БЫ НЕРАБОЧЕЙ ЗАГОТОВКИ. Там лежит
    версия ПОВЕРХНОСТИ, а выпуски помечены своими тегами, и это РАЗНЫЕ числа:
    прибивка к первой указала бы на тег, которого нет, и вызов
    отказал бы у потребителя, а не у нас
    ([157](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/157-a-contract-version-bump-is-a-re-read.md)).

    Тег читается ТЕМ ЖЕ разбором, что у механизма версии: второй разбор той же
    формы — это второе её понимание, и расходятся они молча
    ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md)).
    """
    tag = version.release_tag(root or None)
    if tag is None:
        raise NotRun(
            f"{NO_RELEASE}: прибиваться потребителю не к чему. Заготовка с подвижной"
            " меткой вместо версии меняла бы у него исполняемый код без его ведома (152)"
        )
    return tag


def caller(name: str, repo: str, pin: str) -> str:
    """Джоб вызывающего для одного шага — то, что потребитель кладёт к себе."""
    return (
        f"  {name}:\n"
        f"    name: {name}\n"
        f"    uses: {repo}/.github/workflows/{STEP_PREFIX}{name}.yml@{pin}\n"
        f"    permissions:\n"
        f"      contents: read\n"
        f"      checks: read\n"
        f"      pull-requests: read\n"
        f"      issues: read\n"
    )


def check_name(name: str) -> str:
    """Имя записи проверки, которое выдаст площадка, — составное."""
    return f"{name}{policy.COMPOSED}{name}"


def own_records(flow: Path) -> tuple[list[str], bool]:
    """Имена записей своего прогона механизма и идёт ли он на изменении.

    ИМЯ БЕРЁТСЯ У РАЗБОРА ПРОГОНА, А НЕ У ИМЕНИ ФАЙЛА ШАГА (#993). Джоб обхода
    застрявших зовётся `stuck-prs`, а шаг — `step-stuck.yml`: имя, собранное
    из файла, назвало бы запись, которой площадка не выдаст, и сводный гейт
    потребителя ждал бы её вечно (045). Разбор тот же, что у ответа по
    классам (`policy.check_names`), — второго понимания составного имени нет
    (090).

    РАЗДЕЛ ОТВЕТА ВЫВОДИТСЯ ИЗ СОБЫТИЙ, А НЕ ИЗ РОДА. Очередь — управляющий
    механизм, но идёт и на изменении: её запись живёт на голове, и ответ по ней
    обязан стоять в `checks`, а не в `beyond_the_change` — там его разбор
    потребителя отверг бы как ответ о проверке, которой вне изменения нет.
    """
    try:
        said = policy.run_of(flow)
        names = [
            one
            for job_id, body in (said.get("jobs") or {}).items()
            for one in policy.check_names(str(job_id), body or {}, flow.parent)
        ]
    except policy.BadPolicy as exc:
        raise NotRun(f"{flow.name} не прочитан: {exc}") from exc
    return names, policy.ON_CHANGE in policy.triggers_of(said)


def answer(
    names: list[str], beyond: list[str] | None = None, *, on_change: list[str] | None = None
) -> str:
    """Заготовка ответа потребителя: по строке на проверку, класс — не решён.

    `unreviewed` здесь не заглушка, а объявленная очередь разбора: молча
    обязательной проверка не становится, и молча совещательной тоже.
    `names` — шаги конвейера, их имя составное из имени шага. `beyond` и
    `on_change` — уже готовые имена записей своих прогонов механизмов
    (`own_records`): вне изменения и на нём.
    """
    rows = [f'  "{check_name(one)}": {policy.UNREVIEWED}' for one in names]
    rows += [f'  "{one}": {policy.UNREVIEWED}' for one in on_change or []]
    said = "checks:\n" + "\n".join(rows) + "\n"
    if beyond:
        more = "\n".join(f'  "{one}": {policy.UNREVIEWED}' for one in beyond)
        said += f"{policy.BEYOND}:\n{more}\n"
    return said


def main(argv: list[str] | None = None) -> int:
    """Точка входа: печатает заготовку вызова и заготовку ответа."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(), help="корень ЭТОГО дерева")
    parser.add_argument(
        "--repo",
        default="ArtVsMark/Engineering-Pipeline-Mechanisms",
        help="откуда потребитель зовёт шаги",
    )
    parser.add_argument(
        "--write",
        type=Path,
        metavar="КОРЕНЬ",
        help="положить заготовку в дерево потребителя, а не печатать; занятое не трогается",
    )
    args = parser.parse_args(argv)

    try:
        names = steps(args.root)
        own = own_callers(args.root, names)
        records = {one: own_records(flow) for one, flow in own.items()}
        pin = pin_of(args.root)
    except (NotRun, check_shipped.NotRun) as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN

    if not names:
        print(
            "отдавать нечего: ни один шаг не помечен как отдаваемый наружу — "
            "подключать не к чему, и это состояние, а не заготовка (075)",
            file=sys.stderr,
        )
        return EXIT_NOTHING

    # СВЕРКА ИДЁТ ДО ПЕЧАТИ, А НЕ ПОСЛЕ. Напечатанную заготовку забирают
    # целиком; предупреждение под ней читают не все, а вызов по адресу,
    # которого по названному тегу нет, отказывает у потребителя.
    try:
        missing = check_shipped.unreleased(pin, args.root)
    except (NotRun, check_shipped.NotRun) as exc:
        print(f"заход не отработал: {exc}", file=sys.stderr)
        return EXIT_BROKEN
    if missing:
        print(
            f"прибивка «{pin}» не несёт помеченного наружу: {len(missing)} из "
            f"{len(check_shipped.shipped(args.root))} — {', '.join(missing)}.\n"
            "Заготовка с такой прибивкой отказала бы у потребителя, а не у нас (045).\n"
            f"Выход: нарезать выпуск, содержащий эти файлы, и позвать заход заново (158).",
            file=sys.stderr,
        )
        return EXIT_UNREACHABLE

    pipeline = [one for one in names if one not in own]
    beyond = [name for one in sorted(own) if not records[one][1] for name in records[one][0]]
    on_change = [name for one in sorted(own) if records[one][1] for name in records[one][0]]
    if args.write:
        # КЛАДЁТСЯ ТОЛЬКО ПО ЯВНОМУ КЛЮЧУ И ТОЛЬКО В СВОБОДНОЕ (#992). Чужое
        # дерево заход не правит: занятый путь называется, и не пишется ни
        # один файл — половина заготовки хуже никакой.
        try:
            files = {
                paths.WORKFLOWS / PIPELINE_FLOW: thin_ci(pipeline, args.repo, pin),
                paths.PIPELINE: answer(pipeline, beyond, on_change=on_change),
                **{
                    paths.WORKFLOWS / flow.name: own_kit(flow, one, args.repo, pin)
                    for one, flow in sorted(own.items())
                },
            }
        except NotRun as exc:
            print(f"заход не отработал: {exc}", file=sys.stderr)
            return EXIT_BROKEN
        taken = occupied(args.write, files)
        if taken:
            print(
                "заготовка не положена: в дереве уже есть "
                + ", ".join(str(one) for one in taken)
                + ". Заход чужое не перезаписывает — уберите файл или сверьте его с "
                "выводом захода без --write",
                file=sys.stderr,
            )
            return EXIT_OCCUPIED
        lay(args.write, files)
        print(f"положено в {args.write}: " + ", ".join(str(one) for one in sorted(files)))
        print("Класс каждой проверки в .pipeline.yml — СВОЙ выбор; в защиту ветки — одно имя.")
        print(
            f"Сводный гейт заготовка не кладёт: скопируйте `{paths.WORKFLOWS}/{SUMMARY_FLOW}` "
            "поставщика — его имя и ставится в защиту ветки."
        )
        return EXIT_OK

    print(f"# шагов к подключению: {len(names)} · прибивка: {pin}\n")
    print(f"# 1. В свой `{paths.WORKFLOWS}/{PIPELINE_FLOW}` — джобы вызова:\n")
    print("jobs:")
    print("\n".join(caller(one, args.repo, pin) for one in pipeline))
    for one, flow in sorted(own.items()):
        print(f"# 1. Свой `{paths.WORKFLOWS}/{flow.name}` — управляющий механизм своим прогоном:\n")
        print(own_kit(flow, one, args.repo, pin))
    print(f"# 2. В свой `{paths.PIPELINE}` — ответ по каждой проверке.")
    print("#    Класс — СВОЙ выбор: `required`, `advisory` или `off` с причиной.")
    print(f"#    Здесь все выходят «{policy.UNREVIEWED}»: это очередь разбора, а не умолчание.\n")
    print(answer(pipeline, beyond, on_change=on_change))
    print("# 3. В защиту ветки — ОДНО имя: имя своего сводного гейта.")
    print(
        f"#    Сводный гейт — копия `{paths.WORKFLOWS}/{SUMMARY_FLOW}` поставщика: он не зовётся."
    )
    print("#    Перечислять здесь шаги нельзя: список ломается добавлением версии")
    print("#    в матрицу, и защита начинает ждать имя, которого никто не выдаёт (168).")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
