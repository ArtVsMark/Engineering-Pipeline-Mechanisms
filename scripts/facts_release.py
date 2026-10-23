#!/usr/bin/env python3
"""Готовит выпуск договора фактов семьи: тег ``facts-v<номер>`` и файлы для страницы.

ЧТО ВЫПУСКАЕТСЯ. Не механизмы — их выпуски ``vX.Y.Z`` ставит ``step-release``, —
а ДОГОВОР фактов: схема, проза, проверка, номер и образец. С 22.10.2026 договор
держат механизмы (#1563); выпуски ``facts-v1.x`` остались у витрины, а
``facts-v2.0.0`` каталога — у каталога как история.
Издатель прибивает проверку к тегу, а не к ветке и не к коммиту: живая
``main`` сменила бы требование под ним молча, а коммит не говорит, какой это
договор.

СБОРКА НИЧЕГО НЕ ПУБЛИКУЕТ. Она собирает пять файлов плоско в один каталог —
ровно так они лягут у издателя, — и проверяет их ТАМ, отдельным
интерпретатором с ``-I``: образец обязан отвечать договору (исход 0), номер —
сходиться с заголовками. Выпуск, чья проверка у издателя не запускается, хуже
отсутствующего: его прибьют и получат трассировку.

ПУБЛИКАЦИЯ — ОТДЕЛЬНЫМ ВХОДОМ ``--publish``, ТОКЕНОМ ЧЕЛОВЕКА (131). Тег и
страница несут личность владельца, поэтому ставит их прогон
``facts-release.yml`` кнопкой и токеном владельца. Страница и файлы ставятся
общим транспортом ``ghrest`` (правило 001), а не ``gh release create``, как у
каталога: второй транспорт к площадке у механизмов не заводится (решение
владельца 22.10.2026, #1563).

ТЕГ НЕ ПЕРЕСТАВЛЯЕТСЯ. Стоящий тег — отказ, а не перезапись: выпуск, на
который уже прибились, меняться не вправе. Сверка точная, а не по шаблону —
``git tag --list`` понимает образцы, и ``facts-v1.4.*`` ответил бы «есть» на
тег, которого нет.

Перенесено из витрины в каталог вместе с договором (ArtVsMark/ArtVsMark:
scripts/facts_release.py), из каталога — к механизмам (каталог #930).

Реализует правила каталога:
  035 — номер живёт в одном месте, тег выводится из него, а не вписывается;
  131 — тег несёт личность человека: ставит его кнопка с токеном владельца;
  039 — три исхода: собран · выпускать нельзя · шаг не отработал.

Запуск::

    python scripts/facts_release.py --dist КАТАЛОГ --notes ФАЙЛ
    python scripts/facts_release.py --dist КАТАЛОГ --notes ФАЙЛ --publish --target SHA
    python scripts/facts_release.py --selftest

Исходы: 0 — выпуск собран и проверен (и с ``--publish`` поставлен); 1 —
выпускать нельзя: номер разошёлся с заголовками, тег уже стоит или собранная
проверка у издателя не отработала бы — причина названа; 2 — шаг не отработал:
файл договора или история тегов не прочитаны, площадка не приняла страницу или
файл.
"""

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

import check_facts
import ghrest
import gitcall

#: Издатель договора фактов — механизмы (#1563). Имя нужно, когда прогон
#: не назвал репозиторий: сухой заход окна выпускает за того же издателя.
PUBLISHER = "ArtVsMark/Engineering-Pipeline-Mechanisms"

#: Корень дерева: шаг для CI издателя читает файлы из дерева тега по этим путям.
ROOT = pathlib.Path(__file__).resolve().parent.parent
#: Откуда шаг для CI берёт файлы — дерево издателя договора по тегу.
TREE_RAW = f"https://raw.githubusercontent.com/{PUBLISHER}"

#: Что лежит на странице выпуска — плоско, под своими именами. Порядок — порядок
#: чтения издателем: проза, схема, номер, проверка, образец.
ASSETS = (
    check_facts.CONTRACT_PATH,
    check_facts.SCHEMA_PATH,
    check_facts.VERSION_PATH,
    pathlib.Path(check_facts.__file__).resolve(),
    check_facts.EXAMPLE_PATH,
)


def tag_for(number: str) -> str:
    """Тег выпуска договора: ``facts-v`` и номер из ``export/facts/facts.version``."""
    return f"facts-v{check_facts.contract_version(number)}"


def listed(out: str, tag: str) -> bool:
    """Есть ли ``tag`` среди строк вывода ``git tag --list`` — целиком, а не образцом."""
    return tag in out.split()


def tag_exists(tag: str) -> bool:
    """Стоит ли такой тег — точной сверкой, а не по образцу."""
    # Отказ, отсутствие git и истёкший дедлайн — OSError, его ловит `main` (039).
    return listed(gitcall.output(["tag", "--list", tag], OSError, timeout=60), tag)


def assemble(dist: pathlib.Path) -> list[pathlib.Path]:
    """Файлы выпуска плоско в ``dist``. Отдаёт пути копий."""
    dist.mkdir(parents=True, exist_ok=True)
    return [pathlib.Path(shutil.copy(source, dist / source.name)) for source in ASSETS]


def verify(dist: pathlib.Path, repo: str) -> list[str]:
    """Собранный выпуск у издателя: образец — 0, номер против заголовков — 0.

    Запуск отдельным интерпретатором с ``-I`` в каталоге выпуска: дерево
    каталога не подхватится — ровно положение издателя.
    """
    found: list[str] = []
    runs = (
        (
            "образец проходит проверку договора фактов",
            ["--file", check_facts.EXAMPLE_PATH.name, "--repo", repo],
        ),
        ("номер сходится с заголовками", ["--contract"]),
    )
    for name, args in runs:
        try:
            run = subprocess.run(
                [sys.executable, "-I", pathlib.Path(check_facts.__file__).name, *args],
                cwd=dist,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=600,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            found.append(f"у издателя не отработало бы: {name} — не запустилось: {exc}")
            continue
        if run.returncode != 0:
            last = (
                run.stderr.strip().splitlines() or run.stdout.strip().splitlines() or ["вывода нет"]
            )[-1]
            found.append(
                f"у издателя не отработало бы: {name} — исход {run.returncode}, "
                f"последняя строка: {last}"
            )
    return found


def step_files(step: str) -> list[str]:
    """Пути, которые шаг для CI скачивает из дерева тега (строка ``for f in``)."""
    for line in step.splitlines():
        words = line.split()
        if words[:2] == ["for", "f"] and "in" in words:
            return [
                word.rstrip(";")
                for word in words[words.index("in") + 1 :]
                if word not in (";", "do")
            ]
    return []


def step_refusals(step: str, root: pathlib.Path = ROOT) -> list[str]:
    """Что не так с шагом для CI издателя: пусто — шаг читает файлы из дерева тега.

    ИЗ ДЕРЕВА ПО ТЕГУ, А НЕ С ФАЙЛОВ СТРАНИЦЫ (взгляд). Файлы страницы выпуска
    заменяются, не трогая тега, и проверку, которую издатель запускает, это
    подменило бы молча. Дерево тега так не меняется. Каждый путь строки
    ``for f in`` обязан быть файлом дерева, которое тег прибьёт: иначе у
    издателей ``curl`` упал бы на 404 после выпуска.
    """
    wanted = step_files(step)
    if not wanted:
        return ["шаг для CI не называет, что скачивать: нет строки for f in"]
    found = [
        f"шаг для CI скачивает {one}, а в дереве его нет"
        for one in wanted
        if not (root / one).is_file()
    ]
    if f"{TREE_RAW}/$FACTS_CONTRACT/$f" not in step:
        found.append(
            f"шаг для CI читает не из дерева тега: нет адреса {TREE_RAW}/$FACTS_CONTRACT/$f"
        )
    return found


def notes(number: str, repo: str) -> str:
    """Текст страницы выпуска: что приложено, как запустить, шаг для CI, где источник."""
    tag = tag_for(number)
    step = check_facts.ci_step(check_facts.CONTRACT_PATH.read_text(encoding="utf-8")) or ""
    tree = f"https://github.com/{repo}/blob/{tag}"
    # не проза: номер версии «мажор.минор.патч».
    series = ".".join(number.split(".")[:2])
    return "\n".join(
        [
            f"Договор фактов семьи, номер **{number}**: издатель пишет в "
            f'`facts.json` поле `"schema": "{series}"`.',
            "",
            "Приложено — пять файлов, класть в один каталог:",
            "",
            *(f"- `{source.name}`" for source in ASSETS),
            "",
            "Проверить свой файл — тем же кодом, что судит его читатель:",
            "",
            "```",
            f"python check_facts.py --file {check_facts.BADGES_DIR}/facts.json --repo владелец/имя",
            "```",
            "",
            "Исход `0` — договору отвечает, `1` — расхождения названы, `2` — проверка не "
            "отработала; предупреждения `⚠` кода не меняют.",
            "",
            "Шаг для CI — вставить в прогон, публикующий `facts.json`, перед публикацией:",
            "",
            step,
            "",
            "Источник по тегу — [`export/facts/facts-contract.md`]"
            f"({tree}/export/facts/facts-contract.md); "
            f"как договор меняется — там же, раздел «Как контракт меняется».",
        ]
    )


def publish(
    repo: str, tag: str, number: str, target: str, dist: pathlib.Path, body: str, token: str
) -> str:
    """Ставит страницу выпуска с тегом на ``target`` и прикладывает файлы из ``dist``.

    Площадка ставит тег сама — по ``tag_name`` и ``target_commitish`` страницы;
    отдельного толчка тега нет. Не последним выпуском (``make_latest``): у
    механизмов «последний» — выпуск ``vX.Y.Z`` конвейера, и страница договора его
    не подменяет. Файл, который площадка не приняла, — отказ: страница без
    проверки хуже отсутствующей (см. шапку).

    ТЕГ — ПОСЛЕДНИМ ШАГОМ (находка взгляда на #1582). Страница ставится
    черновиком: у черновика тега ещё нет. Файлы прикладываются к нему, и только
    когда легли все, черновик снимается — тогда площадка ставит тег. Опубликуй
    страницу сразу, и сбой одной загрузки (транспорт POST не повторяет) оставил
    бы тег со страницей без части файлов, а перезапуск отказал бы «тег уже
    стоит». Не легла загрузка — черновик удаляется, и перезапуск начинает с
    чистого места; не удалился — это названо в отказе. Не снялся черновик —
    `undraft`.
    """
    if not token:
        raise ghrest.TransportError("нет токена: GH_TOKEN — тег несёт личность человека (131)")
    if not target:
        raise ghrest.TransportError("не назван коммит тега: --target или GITHUB_SHA")
    page = ghrest.request(
        "POST",
        f"repos/{repo}/releases",
        token,
        {
            "tag_name": tag,
            "target_commitish": target,
            "name": f"Договор фактов {number}",
            "body": body,
            "make_latest": "false",
            "draft": True,
        },
    )
    if not isinstance(page, dict) or not page.get("upload_url") or not page.get("id"):
        raise ghrest.TransportError(f"страница {tag} поставлена без адреса загрузки: {page!r}")
    draft = f"repos/{repo}/releases/{page['id']}"
    try:
        for source in ASSETS:
            ghrest.upload_asset(
                str(page["upload_url"]), source.name, (dist / source.name).read_bytes(), token
            )
    except ghrest.TransportError as exc:
        try:
            ghrest.request("DELETE", draft, token)
        except ghrest.TransportError as left:
            raise ghrest.TransportError(
                f"файлы {tag} не легли ({exc}); черновик {draft} не удалён ({left}) — "
                "удалите его руками, тега нет"
            ) from exc
        raise ghrest.TransportError(
            f"файлы {tag} не легли ({exc}); черновик удалён, тега нет"
        ) from exc
    undraft(draft, tag, token)
    return f"выпуск {tag} поставлен на {target}: файлов {len(ASSETS)}"


def undraft(draft: str, tag: str, token: str) -> None:
    """Снимает черновик ``draft`` — тогда площадка ставит тег. Сбой — отказ с исходом.

    ИСХОД ОБРЫВА НЕИЗВЕСТЕН (взгляд). Транспорт ``PATCH`` повторяет, и после
    обрыва неизвестно, снят ли черновик. Поэтому сбой не удаляет вслепую —
    удаление снятой страницы оставило бы тег без файлов, — а спрашивает
    страницу: снята — выпуск стоит; черновик — удаляется, как при сбое
    загрузки, и перезапуск начинает с чистого места; не ответила — названо,
    что смотреть руками, иначе перезапуск завёл бы второй черновик.
    """
    try:
        ghrest.request("PATCH", draft, token, {"draft": False, "make_latest": "false"})
        return
    except ghrest.TransportError as exc:
        failed = exc
    try:
        page = ghrest.request("GET", draft, token)
    except ghrest.TransportError as unread:
        raise ghrest.TransportError(
            f"файлы {tag} легли, черновик {draft} не снят ({failed}), и страница не ответила "
            f"({unread}): снят ли он, неизвестно — посмотрите руками до перезапуска"
        ) from failed
    if isinstance(page, dict) and page.get("draft") is False:
        return
    try:
        ghrest.request("DELETE", draft, token)
    except ghrest.TransportError as left:
        raise ghrest.TransportError(
            f"файлы {tag} легли, черновик {draft} не снят ({failed}) и не удалён ({left}) — "
            "удалите его руками, тега нет"
        ) from failed
    raise ghrest.TransportError(
        f"файлы {tag} легли, черновик не снят ({failed}); черновик удалён, тега нет"
    ) from failed


def selftest() -> int:
    """Обе стороны (140): собранный выпуск проверяется, порча и стоящий тег — отказ."""
    import contextlib
    import io
    import tempfile

    broken: list[str] = []
    repo = json.loads(check_facts.EXAMPLE_PATH.read_text(encoding="utf-8"))["repo"]

    if tag_for("1.4.0") != "facts-v1.4.0":
        broken.append(f"тег: {tag_for('1.4.0')!r} вместо facts-v1.4.0")
    for bad in ("1.4", "v1.4.0"):
        try:
            tag_for(bad)
            broken.append(f"тег: номер «{bad}» принят")
        except ValueError:
            pass
    print("  да  — тег: facts-v и три числа, иная форма номера — отказ")

    # Шаг для CI издателя: скачивает из дерева тега только то, что в дереве
    # есть (иначе у издателя curl упадёт на 404), прибит к тегу текущего номера
    # и попадает на страницу выпуска — из прозы, а не копией.
    number = check_facts.contract_version(check_facts.VERSION_PATH.read_text(encoding="utf-8"))
    step = check_facts.ci_step(check_facts.CONTRACT_PATH.read_text(encoding="utf-8")) or ""
    wanted = step_files(step)
    said_step = step_refusals(step)
    if said_step:
        broken.append(f"шаг для CI: {said_step}")
    if f"FACTS_CONTRACT: {tag_for(number)}" not in step or step not in notes(number, repo):
        broken.append("шаг для CI не прибит к текущему тегу или не попал на страницу")
    if step_files("    for f in a.py b.json; do") != ["a.py", "b.json"] or step_files("x") != []:
        broken.append("разбор строки for f in в шаге для CI неверен")
    print(
        f"  {'да ' if not said_step else 'НЕТ'} — шаг для CI: "
        f"скачивает {len(wanted)} файла из дерева тега, прибит к {tag_for(number)}"
    )

    with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP")) as tmp:
        dist = pathlib.Path(tmp) / "dist"
        copied = assemble(dist)
        if sorted(p.name for p in copied) != sorted(p.name for p in ASSETS) or len(copied) != 5:
            broken.append(f"сборка: в каталоге {sorted(p.name for p in copied)}")
        said = verify(dist, repo)
        if said:
            broken.append(f"сборка из дерева не проверилась у «издателя»: {said}")
        print(
            f"  {'да ' if not said else 'НЕТ'} — сборка из дерева: пять файлов, у издателя исход 0"
        )

        # Порча — обе проверки обязаны её заметить: образец не отвечает
        # договору, проза разошлась с номером.
        (dist / check_facts.EXAMPLE_PATH.name).write_text(
            json.dumps({"schema": "1.4"}), encoding="utf-8"
        )
        prose = dist / check_facts.CONTRACT_PATH.name
        prose.write_text(
            prose.read_text(encoding="utf-8").replace(
                "## Единые требования · договор", "## Требования · договор"
            ),
            encoding="utf-8",
        )
        said = verify(dist, repo)
        if len(said) != 2:
            broken.append(f"порча выпуска: ждали два отказа, вышло {said}")
        print(f"  {'да ' if len(said) == 2 else 'НЕТ'} — порча выпуска: оба отказа названы")

    for shown, asked, expected in (
        ("facts-v1.4.0\n", "facts-v1.4.0", True),
        ("facts-v1.4.0\n", "facts-v1.4.*", False),
        ("facts-v1.4.10\n", "facts-v1.4.1", False),
    ):
        got = listed(shown, asked)
        if got is not expected:
            broken.append(f"сверка тега «{asked}» среди «{shown.strip()}»: {got}")
    print("  да  — сверка тега точная, а не по образцу")

    # Живой путь main — обе стороны отказа: стоящий тег — 1, нечитаемый
    # договор — 2. Сравнение прямо с main(): так его считает храповик
    # непрогнанных исходов (check_mechanisms).
    saved_exists, saved_assets, saved_argv = tag_exists, ASSETS, sys.argv
    before = len(broken)
    with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP")) as tmp:
        sys.argv = ["facts_release.py", "--dist", f"{tmp}/dist", "--notes", f"{tmp}/notes.md"]
        try:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                globals()["tag_exists"] = lambda _tag: True
                if main() != 1:
                    broken.append("стоящий тег не отвергнут — выпуск переставил бы его")
                globals()["tag_exists"] = lambda _tag: False
                globals()["ASSETS"] = (*saved_assets, pathlib.Path(tmp) / "нет-такого.md")
                if main() != 2:
                    broken.append("нечитаемый файл договора не назван «не отработал»")
                globals()["ASSETS"] = saved_assets
                if main() != 0:
                    broken.append("исправный выпуск не собран")
                if "check_facts.py --file" not in pathlib.Path(f"{tmp}/notes.md").read_text(
                    encoding="utf-8"
                ):
                    broken.append("текст страницы не говорит, как запустить проверку")
        finally:
            globals()["tag_exists"], globals()["ASSETS"] = saved_exists, saved_assets
            sys.argv = saved_argv
    print(
        f"  {'да ' if len(broken) == before else 'НЕТ'} — main: стоящий тег — 1, "
        f"нечитаемый договор — 2, исправный — 0"
    )

    if broken:
        print(check_facts.annotate("error", "самопроверка провалена"), file=sys.stderr)
        for line in broken:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("самопроверка пройдена: выпуск договора собирается и проверяется у издателя")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--dist", type=pathlib.Path, help="каталог файлов выпуска")
    parser.add_argument("--notes", type=pathlib.Path, help="куда записать текст страницы")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", PUBLISHER),
    )
    parser.add_argument("--publish", action="store_true", help="поставить страницу и файлы")
    parser.add_argument("--target", default=os.environ.get("GITHUB_SHA", ""), help="коммит тега")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not args.dist or not args.notes:
        print("шаг не отработал: нужны --dist и --notes", file=sys.stderr)
        return 2

    try:
        number = check_facts.contract_version(check_facts.VERSION_PATH.read_text(encoding="utf-8"))
        schema = json.loads(check_facts.SCHEMA_PATH.read_text(encoding="utf-8"))
        drift = check_facts.contract_drift(
            number, schema, check_facts.CONTRACT_PATH.read_text(encoding="utf-8")
        )
        tag = tag_for(number)
        standing = tag_exists(tag)
        missing = [str(source) for source in ASSETS if not source.is_file()]
        if missing:
            raise OSError(f"нет файлов договора фактов — {', '.join(missing)}")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(check_facts.annotate("error", f"шаг не отработал: {error}"), file=sys.stderr)
        return 2

    refusals = list(drift)
    # Шаг для CI раздаётся пятерым издателям разом: скачивай он файл, которого
    # в дереве тега нет, — у всех пятерых curl упал бы на 404 после выпуска.
    step = check_facts.ci_step(check_facts.CONTRACT_PATH.read_text(encoding="utf-8")) or ""
    refusals += step_refusals(step)
    if standing:
        refusals.append(
            f"тег {tag} уже стоит: выпуск, на который прибились, не "
            f"переставляется — поднимите номер в export/facts/facts.version"
        )
    if not refusals:
        assemble(args.dist)
        refusals += verify(
            args.dist, json.loads(check_facts.EXAMPLE_PATH.read_text(encoding="utf-8"))["repo"]
        )
    if refusals:
        for line in refusals:
            print(check_facts.annotate("error", line), file=sys.stderr)
        return 1

    args.notes.write_text(notes(number, args.repo) + "\n", encoding="utf-8")
    if args.publish:
        try:
            body = args.notes.read_text(encoding="utf-8")
            token = ghrest.token_from_env()
            print(publish(args.repo, tag, number, args.target, args.dist, body, token))
        except (OSError, ghrest.TransportError) as error:
            print(check_facts.annotate("error", f"выпуск не поставлен: {error}"), file=sys.stderr)
            return 2
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"tag={tag}\nnumber={number}\n")
    print(f"выпуск {tag} собран: файлов {len(ASSETS)} в {args.dist}, проверка у издателя — 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
