"""Дерево сверяется с договором о конвейере.

Настройка защиты ветки живёт вне дерева, и её расхождение с прогоном не видит
ни ревью, ни сам прогон. Единственное, что можно удержать здесь, — чтобы имена
в дереве и в договоре не разъезжались: тогда расхождение с площадкой сводится
к одному имени, а не к поиску по всем файлам.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
GATES = WORKFLOWS / "ci.yml"
CONTRACT = ROOT / "docs" / "pipeline.md"
SUMMARY = "ci-complete"


def load_gates() -> dict[Any, Any]:
    """Читает описание гейтов.

    Ключи здесь не только строки: YAML 1.1 читает `on:` как булево `True`, и
    раздел событий лежит под этим ключом, а не под строкой «on». Тип словаря
    назван честно, чтобы это не всплыло на первой же правке теста.
    """
    document: dict[Any, Any] = yaml.safe_load(GATES.read_text(encoding="utf-8"))
    return document


def contract_rows() -> list[tuple[str, str]]:
    """Строки таблицы шагов договора парами «файл прогона, имя джоба».

    Номер шага бывает с буквой (`6a`, `12b`) и бывает прочерком — у релиза
    номера в скелете нет. Читаются все три вида: строка, выпавшая из образца,
    молча выводит свой джоб из сверки, и расхождение с деревом становится
    невидимым.

    Буква обязана быть ЛАТИНСКОЙ, и это проверяется отдельно: кириллическая
    «а» выглядит неотличимо, а под образец не подходит. Поймано на себе
    10.09.2026 — дважды за одну смену.
    """
    text = CONTRACT.read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*(?:\d+[a-z]?|—)\s*\|.*$", text, re.MULTILINE)
    assert rows, "в договоре не нашлось таблицы шагов — предмет сверки отсутствует"

    stray = re.findall(r"^\|\s*\d+[а-яё]\s*\|", text, re.MULTILINE | re.IGNORECASE)
    assert not stray, (
        f"номер подшага записан кириллицей: {stray} — такая строка выпадает "
        "из сверки молча, буква обязана быть латинской"
    )

    found: list[tuple[str, str]] = []
    for row in rows:
        cells = [cell.strip().strip("`*") for cell in row.split("|")]
        if len(cells) < 6:
            continue
        # У файла бывает пояснение рядом — `review.yml` (кнопкой, по номеру).
        found.append((cells[3].split()[0].strip("`¹²³"), cells[4]))
    return found


def tree_jobs() -> dict[str, str]:
    """Джобы ВСЕХ прогонов дерева: имя джоба → файл, который его несёт."""
    found: dict[str, str] = {}
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        for job_id, job in (document.get("jobs") or {}).items():
            found[str((job or {}).get("name") or job_id)] = path.name
    return found


def test_jobs_match_the_contract() -> None:
    """Джобы гейтов и джобы договора совпадают, а не «примерно соответствуют»."""
    assert set(load_gates()["jobs"]) == {
        job for workflow, job in contract_rows() if workflow == GATES.name
    }


def test_every_job_in_the_tree_is_described_by_the_contract() -> None:
    """У КАЖДОГО джоба дерева есть строка договора — не только у гейтов.

    Прежде сверялся один `ci.yml`, и шесть джобов жили вне договора: разбор
    слитого, запись находок, поздний взгляд, состав меток, сверка контекста и
    входящие каталога. Джоб без строки не сверяется ничем, и расхождение имени
    с деревом становится невидимым — а имя джоба это ВХОД механизмов: по нему
    очередь читает вердикт, а защита ветки — обязательный контекст.
    """
    described = {job for _, job in contract_rows()}
    stray = sorted(set(tree_jobs()) - described)
    assert not stray, f"джобы дерева не описаны договором: {stray}"


def test_a_built_step_of_the_contract_exists_in_the_tree() -> None:
    """Шаг договора, чей файл ПОСТРОЕН, обязан выдавать названный джоб.

    Обратная сторона той же сверки, и здесь важна граница. Договор описывает и
    то, чего ещё нет — разморозку, застрявшие изменения, релиз: это скелет, и
    строка без файла законна. Незаконно другое: файл есть, а джоба с таким
    именем в нём нет — значит договор отстал от дерева и врёт о построенном
    ([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).

    Замер 10.09.2026: шаг 13 называл джоб `rules-inbox`, а прогон выдаёт
    `inbox`; шаг 12b называл `review`, а поздний взгляд уехал в свой джоб.
    """
    jobs = tree_jobs()
    lying = [
        (workflow, job)
        for workflow, job in contract_rows()
        if (WORKFLOWS / workflow).is_file() and jobs.get(job) != workflow
    ]
    assert not lying, (
        f"договор называет джобы, которых нет в построенных прогонах: {lying} — "
        "файл есть, значит это не пробел скелета, а отставший договор"
    )


def test_the_skeleton_may_name_what_is_not_built_yet() -> None:
    """Предмет проверки найден: непостроенные шаги в договоре ЕСТЬ (075).

    Без этой проверки предыдущая зеленела бы и на договоре, из которого убрали
    весь скелет: «все описанные построены» верно и тогда, когда описанных нет.
    """
    planned = [
        (workflow, job) for workflow, job in contract_rows() if not (WORKFLOWS / workflow).is_file()
    ]
    assert planned, "в договоре не осталось ни одного непостроенного шага — скелет исчез"


def test_summary_has_no_needs() -> None:
    """Сводный гейт собран опросом: `needs` превращает отказ соседа в пропуск."""
    assert "needs" not in load_gates()["jobs"][SUMMARY]


def test_job_name_equals_context_name() -> None:
    """Имя джоба и имя контекста совпадают: иначе в защите окажется имя-призрак."""
    for job_id, job in load_gates()["jobs"].items():
        assert job.get("name", job_id) == job_id, f"джоб {job_id} выдаёт другое имя контекста"


def test_summary_is_not_a_matrix() -> None:
    """Матричные имена в список обязательных не попадают никогда."""
    assert "strategy" not in load_gates()["jobs"][SUMMARY]


def test_summary_takes_its_subject_from_data() -> None:
    """Наполнение опроса приходит из данных проекта, а не из файла прогона.

    Список именами, вписанный в прогон, делает класс проверки свойством
    механизма. Он свойство проекта: у одного `e2e` обязателен, у другого
    невозможен, и подключение к общему конвейеру не должно требовать правки
    workflow.
    """
    step = load_gates()["jobs"][SUMMARY]["steps"][-1]["run"]
    assert "--policy" in step, "сводный джоб не называет, откуда берёт наполнение"
    assert "--required" not in step, "список именами в прогоне — это класс проверки в механизме"


def test_every_job_of_the_tree_is_answered() -> None:
    """По каждому джобу дерева есть ответ, а не только по обязательным."""
    checks = yaml.safe_load((ROOT / ".pipeline.yml").read_text(encoding="utf-8"))["checks"]
    assert set(load_gates()["jobs"]) - {SUMMARY} <= set(checks)


def test_summary_does_not_answer_for_itself() -> None:
    """Сводный гейт в ответе не объявляется: его класс задан построением."""
    checks = yaml.safe_load((ROOT / ".pipeline.yml").read_text(encoding="utf-8"))["checks"]
    assert SUMMARY not in checks


def test_the_shared_branch_is_checked_too() -> None:
    """Гейты идут и на общей ветке, а не только на изменении.

    Замер 09.09: на `main` не шло ни одной проверки, кроме публикации фактов.
    Два изменения, зелёных по отдельности, после слияния могли дать красное, и
    узнать об этом было неоткуда — а «красная общая ветка» стоит источником 0 в
    порядке работ. Источник без сигнала не источник.
    """
    triggers = load_gates()[True]
    assert "push" in triggers, "общая ветка не проверяется ничем"
    assert triggers["push"]["branches"] == ["main"]


#: Условие, которым объявляется «шаг идёт только на изменении». Сверяется
#: равенством, а не вхождением слова: подстрока «push» есть и у перевёрнутого
#: `== 'push'`, то есть у шага, который пойдёт ТОЛЬКО на общей ветке.
CHANGE_ONLY = "github.event_name != 'push'"


def runs_only_on_a_change(condition: str) -> bool:
    """Объявляет ли условие «этот шаг идёт только на изменении»."""
    return " ".join(condition.split()) == CHANGE_ONLY


def test_change_only_jobs_do_not_run_on_the_shared_branch() -> None:
    """Шаги, чей предмет — изменение, на общей ветке не идут.

    У них там нет предмета: разметки изменения, фрагмента относительно базы и
    вердикта по изменению на `main` не существует. Пропуск объявлен условием, а
    не молчаливым отказом внутри шага (154).

    Проверяется НАПРАВЛЕНИЕ условия, а не наличие в нём слова «push». Прежняя
    проверка искала подстроку и пропустила бы перевёрнутую полярность: шаг с
    `== 'push'` идёт ровно наоборот — только там, где предмета нет, — и такую
    подмену набор не заметил бы вовсе.

    На это условие опирается и очередь: `scripts/automerge.py` считает пропуск
    на общей ветке объявленным состоянием, а не краснотой, — и держится это
    именно здесь.
    """
    jobs = load_gates()["jobs"]
    for name in ("pr-meta", "journal", "attribution", SUMMARY):
        condition = str(jobs[name].get("if", ""))
        assert runs_only_on_a_change(condition), (
            f"{name}: условие «{condition}» не объявляет «только на изменении» — "
            f"ожидалось «{CHANGE_ONLY}»"
        )


def test_an_inverted_condition_would_be_caught() -> None:
    """Перевёрнутая полярность отвергается, а не проходит по вхождению слова.

    Гейт проверяется тем, что обязан отвергнуть (140): подстрока «push» есть в
    обоих условиях, и разводит их только направление.

    ПРЕДМЕТ ЗДЕСЬ — РАЗБОР УСЛОВИЯ, И ЭТО НАЗВАНО, А НЕ ПОДРАЗУМЕВАЕТСЯ.
    Проверить поведением — «шаг действительно не пошёл на общей ветке» — можно
    только прогоном площадки: условие вычисляет она, и локально его исполнить
    нечем (045). Разбор же связан с настоящим деревом соседней проверкой,
    `test_change_only_jobs_do_not_run_on_the_shared_branch`: она гоняет ту же
    функцию по живому `ci.yml`. Порознь каждая из них говорила бы о себе,
    вместе — о конвейере. Нашёл внешний взгляд на #107.
    """
    assert runs_only_on_a_change("github.event_name != 'push'")
    assert not runs_only_on_a_change("github.event_name == 'push'")
    assert not runs_only_on_a_change("")


def test_label_events_reach_the_gates() -> None:
    """Разметка — вход механизма, значит её правка обязана менять вердикт."""
    # `on:` — булев ключ, см. load_gates.
    triggers = load_gates()[True]["pull_request"]["types"]
    assert {"labeled", "unlabeled"} <= set(triggers)


#: Программа, встроенная прямо в шаг прогона: оболочка меняет экранирование по
#: дороге, и один и тот же код в файле и в строке ведёт себя по-разному (013).
EMBEDDED_CODE_RE = re.compile(r"python3?\s+(?:-c\b|-\s*<<)|<<\s*['\"]?(?:PY|PYTHON|EOF_PY)")


def test_workflows_do_not_embed_code() -> None:
    """Логика зовётся файлом, а не встраивается строкой в шаг прогона (013).

    Escape-последовательности проходят через оболочку и меняются, а встроенный
    код вдобавок не виден ни линтеру, ни типизации, ни набору тестов: три гейта
    разом перестают его касаться.
    """
    embedded = [
        path.name
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        if EMBEDDED_CODE_RE.search(path.read_text(encoding="utf-8"))
    ]
    assert not embedded, f"код встроен в прогон, а не вызван файлом: {embedded}"


def test_branch_prefixes_match_the_workflow() -> None:
    """Приставка ветки — вход механизма, и она одна и та же у прогона и у скрипта.

    Разъехавшись, они дают худший из отказов: прогон стартует, скрипт отвечает
    «ветка без объявленной приставки» и выходит нулём — изменение не открыто, и
    красного нигде нет (003, 094).
    """
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "agent-pr.yml").read_text("utf-8"))
    # `on` в YAML читается как True: ключ приходится искать по обоим написаниям.
    triggers = workflow.get("on") or workflow.get(True)
    branches = list(triggers["push"]["branches"])

    source = (ROOT / "scripts" / "agent_pr.py").read_text(encoding="utf-8")
    declared = re.search(r"PREFIXES: Final = \(([^)]*)\)", source)
    assert declared, "в scripts/agent_pr.py не нашлось PREFIXES — предмет проверки не найден (075)"
    prefixes = re.findall(r'"([^"]+)"', declared.group(1))

    assert [f"{prefix}**" for prefix in prefixes] == branches, (
        f"приставки разъехались: прогон слушает {branches}, скрипт берёт {prefixes}"
    )


def test_the_aggregate_does_not_go_red_on_a_cancelled_matrix() -> None:
    """Агрегат версий не краснеет, когда матрицу ОТМЕНИЛИ.

    Погашенный группой отмены прогон отменяет матрицу, но агрегат при
    `always()` остаётся жив и честно возвращает красное — оставляя на голове
    красную запись МЁРТВОГО прогона. Пока новый прогон не дойдёт до агрегата (а
    он ждёт всю матрицу), очередь видит эту запись и считает изменение красным.
    Замер 10.09.2026: #105 получил метку источника 2 при идущих зелёных
    проверках.

    Вердикта у отменённого прогона нет, и выдавать за вердикт нечего (045).
    """
    condition = str(load_gates()["jobs"]["test"]["if"])
    assert "always()" in condition, (
        "без always() красная матрица делает агрегат пропущенным, а пропущенный "
        "обязательный контекст защита ветки засчитывает за пройденный (040)"
    )
    assert "cancelled" in condition, (
        "агрегат краснеет на отменённой матрице — это красная запись мёртвого прогона"
    )


#: Пометка, которой договор называет ОБЪЯВЛЕННЫЙ, но ещё не построенный шаг.
#: Прочерк без слова читался бы как «файла нет и не нужно», а слово — как «шаг
#: обещан и его ждут» (154).
NOT_BUILT = "не построен"


def test_every_file_named_by_the_contract_exists() -> None:
    """Прогон, названный в таблице шагов, лежит в дереве — или помечен непостроенным.

    Договор, обещающий механизм, которого нет, — это не пробел, а ложь о
    действительности: читатель видит имя файла и считает шаг существующим.
    Замер 10.09.2026: так стояли `thaw.yml` (шаг 10) и `stuck-prs.yml` (шаг 11),
    причём второй не был назван и в таблице пробелов — то есть не существовал
    вовсе нигде, кроме обещания (046, 175).
    """
    doc = (ROOT / "docs" / "pipeline.md").read_text(encoding="utf-8")
    live = {path.name for path in (ROOT / ".github" / "workflows").glob("*.yml")}
    missing: list[str] = []
    for row in doc.splitlines():
        if not row.startswith("|"):
            continue
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if len(cells) < 3:
            continue
        for name in re.findall(r"`([\w.-]+\.yml)`", cells[2]):
            if name not in live and NOT_BUILT not in cells[2]:
                missing.append(name)
    assert not missing, (
        f"договор называет прогоны, которых в дереве нет: {sorted(set(missing))}. "
        f"Постройте их или пометьте строку словом «{NOT_BUILT}»"
    )


def test_an_unbuilt_step_is_named_among_the_gaps() -> None:
    """Непостроенный шаг назван в таблице пробелов свода, а не только помечен.

    Пометка в договоре говорит «этого нет», но не говорит, КОГДА появится и чем
    держится сейчас. Раздел «Чего в проекте ещё нет» несёт адрес задачи — то
    есть переводит отсутствие в работу, а не оставляет фактом (046).

    СВЕРЯЕТСЯ ИМЯ ПРОГОНА, А НЕ НОМЕР ШАГА. Первая редакция искала «шаг 11» и
    столкнулась с соседним гейтом: в строках пробелов числа прозой запрещены
    (005, 175), и номер пришлось писать словом. Имя прогона цифр не содержит,
    уникально и не зависит от того, как в своде записаны числа.
    """
    doc = (ROOT / "docs" / "pipeline.md").read_text(encoding="utf-8")
    gaps = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for row in doc.splitlines():
        if not row.startswith("|") or NOT_BUILT not in row:
            continue
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        name = cells[3].strip().strip("`") if len(cells) > 3 else ""
        assert name and f"`{name}`" in gaps, (
            f"шаг «{name}» помечен непостроенным в договоре, а в таблице пробелов свода его нет"
        )
