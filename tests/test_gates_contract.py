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

from tests.conftest import load_script, walk

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
GATES = WORKFLOWS / "ci.yml"
CONTRACT = ROOT / "docs" / "use" / "pipeline.md"
SUMMARY = "ci-complete"


def load_gates() -> dict[Any, Any]:
    """Читает описание гейтов.

    Ключи здесь не только строки: YAML 1.1 читает `on:` как булево `True`, и
    раздел событий лежит под этим ключом, а не под строкой «on». Тип словаря
    назван честно, чтобы это не всплыло на первой же правке теста.
    """
    document: dict[Any, Any] = yaml.safe_load(GATES.read_text(encoding="utf-8"))
    return document


def summary_lives_in() -> tuple[Path, dict[Any, Any]]:
    """Где объявлен сводный джоб: файл и его прогон целиком.

    Джоб ищется ПО ИМЕНИ во всех прогонах, а не по адресу файла. 11.09.2026 он
    переехал из `ci.yml` в собственный прогон, чтобы группа отмены `ci` не
    гасила обязательный контекст, — и набор, прибитый к имени файла, сломался
    бы этим переездом, ничего не сказав о существе. Имя джоба — предмет
    договора с защитой ветки, файл — его адрес (168).
    """
    found = [
        (path, document)
        for path in walk(WORKFLOWS, "*.yml")
        if SUMMARY
        in ((document := yaml.safe_load(path.read_text(encoding="utf-8"))) or {}).get("jobs", {})
    ]
    assert len(found) == 1, f"сводный джоб «{SUMMARY}» объявлен {len(found)} раз — ожидался один"
    return found[0]


def summary_job() -> dict[Any, Any]:
    """Сводный джоб, где бы он ни жил."""
    job: dict[Any, Any] = summary_lives_in()[1]["jobs"][SUMMARY] or {}
    return job


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


#: Разбор состава прогонов ОДИН на всех читателей, и берётся он у механизма.
#: Здесь стоял свой, и он разошёлся с общим на первом же вызываемом прогоне:
#: имя проверки у вызванного джоба СОСТАВНОЕ, а этот разбор отдавал голое —
#: то есть договор сверялся с именем, которого площадка не выдаст. Второй
#: разбор одной формы — это второе её понимание, и расходятся они молча
#: ([090](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/090-shared-helpers-move-up-not-sideways.md),
#: [022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
policy = load_script("pipeline_checks.py")


def tree_jobs() -> dict[str, str]:
    """Проверки ВСЕХ прогонов дерева: имя записи → файл, который её несёт.

    Имя берётся у общего разбора: у обычного джоба это его собственное имя, у
    джоба, зовущего переиспользуемый прогон, — составное «вызывающий /
    вызванный». Сам вызываемый прогон записей не даёт и сюда не попадает.
    """
    found: dict[str, str] = {}
    for path in walk(WORKFLOWS, "*.y*ml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        if policy.CALLED in [str(one) for one in (document.get("on", document.get(True)) or {})]:
            continue
        for job_id, job in (document.get("jobs") or {}).items():
            for name in policy.check_names(job_id, job or {}, WORKFLOWS):
                found[name] = path.name
    return found


def gate_checks() -> set[str]:
    """Имена ЗАПИСЕЙ, которые даёт прогон гейтов, — тем же разбором, что у всех.

    Идентификатор джоба именем записи быть перестал: джоб, зовущий
    переиспользуемый прогон, даёт составное имя. Сверять договор и ответ по
    идентификатору значило бы сверять их с тем, чего площадка не выдаёт (045).
    """
    document = load_gates()
    return {
        name
        for job_id, job in (document.get("jobs") or {}).items()
        for name in policy.check_names(job_id, job or {}, WORKFLOWS)
    }


def test_jobs_match_the_contract() -> None:
    """Джобы гейтов и джобы договора совпадают, а не «примерно соответствуют»."""
    assert gate_checks() == {job for workflow, job in contract_rows() if workflow == GATES.name}


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


def test_the_contract_rows_have_a_built_subject() -> None:
    """Предмет проверки найден: строки с ПОСТРОЕННЫМ файлом в договоре есть (075).

    Без этого предыдущая зеленела бы и на договоре, из которого убрали весь
    скелет: «ни одна построенная строка не врёт» верно и тогда, когда
    построенных строк нет вовсе.

    ЗДЕСЬ СТОЯЛО ОБРАТНОЕ ТРЕБОВАНИЕ, и оно держалось лишь тем, что скелет был
    неполон: «непостроенный шаг обязан остаться». 12.09.2026 построен шаг 11 —
    последний объявленный без файла, — и проверка покраснела на ЗАКРЫТОМ
    пробеле, то есть запретила доделать работу. Предмет соседней проверки —
    строки с файлом, их и надо спрашивать
    ([044](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/044-check-the-premise-before-fixing.md)).
    """
    built = [
        (workflow, job) for workflow, job in contract_rows() if (WORKFLOWS / workflow).is_file()
    ]
    assert built, "в договоре не осталось ни одной построенной строки — сверять нечего"


def test_summary_has_no_needs() -> None:
    """Сводный гейт собран опросом: `needs` превращает отказ соседа в пропуск."""
    assert "needs" not in summary_job()


def test_job_name_equals_context_name() -> None:
    """Имя джоба и имя контекста совпадают: иначе в защите окажется имя-призрак."""
    for job_id, job in load_gates()["jobs"].items():
        assert job.get("name", job_id) == job_id, f"джоб {job_id} выдаёт другое имя контекста"


def test_summary_is_not_a_matrix() -> None:
    """Матричные имена в список обязательных не попадают никогда."""
    assert "strategy" not in summary_job()


def test_summary_takes_its_subject_from_data() -> None:
    """Наполнение опроса приходит из данных проекта, а не из файла прогона.

    Список именами, вписанный в прогон, делает класс проверки свойством
    механизма. Он свойство проекта: у одного `e2e` обязателен, у другого
    невозможен, и подключение к общему конвейеру не должно требовать правки
    workflow.
    """
    step = summary_job()["steps"][-1]["run"]
    assert "--policy" in step, "сводный джоб не называет, откуда берёт наполнение"
    assert "--required" not in step, "список именами в прогоне — это класс проверки в механизме"


def test_every_job_of_the_tree_is_answered() -> None:
    """По каждому джобу дерева есть ответ, а не только по обязательным."""
    checks = yaml.safe_load((ROOT / ".pipeline.yml").read_text(encoding="utf-8"))["checks"]
    assert gate_checks() - {SUMMARY} <= set(checks)


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
    for name in ("pr-meta", "journal", "attribution"):
        condition = str(jobs[name].get("if", ""))
        assert runs_only_on_a_change(condition), (
            f"{name}: условие «{condition}» не объявляет «только на изменении» — "
            f"ожидалось «{CHANGE_ONLY}»"
        )


def test_the_summary_never_comes_to_the_shared_branch_at_all() -> None:
    """Сводный гейт на общую ветку не приходит ВОВСЕ, а не пропускается условием.

    Пока он жил джобом в `ci`, событие толчка в общую ветку до него доходило, и
    не идти ему приходилось условием. Со своим прогоном условие не нужно: у него
    просто нет события `push`. Это сильнее — условие вычисляет площадка уже
    ПОСЛЕ создания записи, а отсутствующее событие записи не создаёт.

    Проверяется именно отсутствие события, а не отсутствие условия: джоб без
    `if` в прогоне, который ходит на `push`, шёл бы на общей ветке каждый раз.
    """
    _, document = summary_lives_in()
    # YAML 1.1 читает `on:` как булево `True` — раздел событий лежит под ним.
    events = document.get(True) or document.get("on") or {}
    assert "push" not in events, (
        f"прогон сводного гейта ходит на {sorted(events)}: событие толчка в общую ветку "
        "создаёт запись там, где сводить нечего"
    )
    assert "pull_request" in events, "сводный гейт не ходит на изменение — сводить будет нечего"


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

    Сводного гейта в том списке больше нет: он ушёл в свой прогон, и там
    «не идти на общей ветке» держится ОТСУТСТВИЕМ события, а не условием, —
    это проверяет `test_the_summary_never_comes_to_the_shared_branch_at_all`.
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
        for path in walk(ROOT / ".github" / "workflows", "*.yml")
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
    doc = (ROOT / "docs" / "use" / "pipeline.md").read_text(encoding="utf-8")
    live = {path.name for path in walk(ROOT / ".github" / "workflows", "*.yml")}
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
    doc = (ROOT / "docs" / "use" / "pipeline.md").read_text(encoding="utf-8")
    gaps = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for row in doc.splitlines():
        if not row.startswith("|") or NOT_BUILT not in row:
            continue
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        name = cells[3].strip().strip("`") if len(cells) > 3 else ""
        assert name and f"`{name}`" in gaps, (
            f"шаг «{name}» помечен непостроенным в договоре, а в таблице пробелов свода его нет"
        )


def test_the_summary_is_not_cancelled_together_with_the_gates() -> None:
    """Группа отмены `ci` сводного гейта не касается — ради этого он и переехал.

    У `ci` стоит `cancel-in-progress: true`, и гасит она ВЕСЬ прогон целиком.
    Пока сводный гейт жил внутри, новый толчок оставлял на прежней голове
    `cancelled` там, где защита ветки ждёт вердикт: отменённая запись слияния
    не держит, но и зелёной не является. Замер 10.09.2026 — #105 получил
    красный обязательный контекст при полностью зелёных проверках.

    Проверяется РАЗНИЦА ГРУПП, а не наличие своей: одинаковое имя группы в двух
    файлах гасило бы их вместе ровно так же, как один файл.
    """
    summary_file, summary = summary_lives_in()
    assert summary_file != GATES, "сводный гейт снова живёт в прогоне гейтов"
    mine = str((summary.get("concurrency") or {}).get("group") or "")
    theirs = str((load_gates().get("concurrency") or {}).get("group") or "")
    assert mine and theirs, "у одного из прогонов нет группы отмены — сравнивать нечего"
    assert mine != theirs, f"группа отмены общая ({mine}): гаснуть они будут вместе"


def test_the_summary_names_the_head_in_its_own_group() -> None:
    """Своя группа отмены называет голову, а не только номер изменения (179).

    Иначе последнее слово осталось бы за заходом на устаревшем коммите — и
    обязательный контекст отвечал бы о чужой голове.
    """
    group = str((summary_lives_in()[1].get("concurrency") or {}).get("group") or "")
    assert "head.sha" in group or "github.sha" in group, (
        f"группа «{group}» не называет головы: вердикт о старом коммите вытеснит новый"
    )


#: Прогоны, которые ОТМЕНЯЮТ предыдущий и голову в группе НЕ называют намеренно:
#: предмет проверки у них не коммит, а СОСТОЯНИЕ. Правило 179 само называет эту
#: границу, и голова в группе вернула бы гонку за свежесть вместо гашения
#: старого поколения целиком. Список разрешительный, и причина у каждого своя
#: ([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md),
#: [154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).
STATE_NOT_A_COMMIT: dict[str, str] = {
    "badges.yml": "пересобирает витрину с общей ветки: старое поколение значков гасится целиком",
    "drift.yml": "сводит внешнее состояние в одну живую задачу — предмет не коммит, а мир вокруг",
    "rules-inbox.yml": "разбирает входящее от каталога: предмет — чужая выгрузка, а не наша голова",
    "attribution-history.yml": "считает авторство по ИСТОРИИ общей ветки, а не по одному коммиту",
}


#: ДЖОБЫ, чья группа отменяет прежний заход и голову не называет намеренно.
#: Цена 179 — «на актуальной голове нет ОБЯЗАТЕЛЬНОЙ проверки» — у совещательного
#: джоба не наступает: снятый взгляд слияние не держит, а слитое без взгляда
#: догоняет поздний взгляд. Устаревшая голова, пришедшая последней, агента не
#: зовёт: ворота взгляда сверяют её с головой изменения (`look_waits.stale`).
ADVISORY_JOBS: dict[str, str] = {
    "review.yml:review": "новый толчок снимает взгляд прежней головы (#848); взгляд совещательный",
}


def cancelling_groups() -> dict[str, str]:
    """Отменяющие группы прогонов и ДЖОБОВ: `прогон` или `прогон:джоб` → группа.

    ГРУППЫ ДЖОБОВ ГЕЙТ ПРЕЖДЕ НЕ ВИДЕЛ. Он читал только группу прогона, и
    группа джоба `review` без головы (#855) прошла мимо него — нашёл аудит
    ответа на 179 26.09.2026 (#829).
    """
    found: dict[str, str] = {}
    for path in walk(WORKFLOWS, "*.yml"):
        flow = yaml.safe_load(path.read_text(encoding="utf-8"))
        places = [(path.name, flow.get("concurrency"))]
        places += [
            (f"{path.name}:{name}", job.get("concurrency"))
            for name, job in (flow.get("jobs") or {}).items()
            if isinstance(job, dict)
        ]
        for name, group in places:
            if isinstance(group, dict) and group.get("cancel-in-progress") is True:
                found[name] = str(group.get("group") or "")
    return found


def test_a_job_group_is_seen_by_the_head_gate() -> None:
    """Группа джоба входит в предмет гейта: без неё `review` не был бы виден (#829)."""
    assert "review.yml:review" in cancelling_groups()


def test_a_cancelling_group_names_the_head_or_declares_why_not() -> None:
    """Каждый отменяющий прогон называет голову — либо объявлен состоянием.

    ПРОВЕРЯЛИСЬ ДВА ПРОГОНА ИЗ СЕМИ. Голову в своей группе держали поимённо
    сводный гейт и ревью; остальные пять не проверял никто, и новый отменяющий
    прогон без головы прошёл бы молча. Замер 17.09.2026: отменяют семь,
    голову называют три (`ci`, `ci-complete`, `review`), четыре объявлены
    состоянием.

    ЦЕНА ПРОПУСКА НАЗВАНА САМИМ ПРАВИЛОМ: события площадки доставляются не в
    том порядке, в каком сделаны коммиты, и без головы в группе вытеснить может
    прогон на УСТАРЕВШЕМ коммите. Тогда на актуальном обязательной проверки нет
    вовсе, а создать её больше нечем
    ([179](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/179-cancellation-group-must-name-the-head.md)).

    Нашёл внешний взгляд на #427: ответ по 179 называл три прогона, и из них
    один головы не имел, а другой не отменял вовсе.
    """
    cancelling = cancelling_groups()
    assert cancelling, "отменяющих прогонов в дереве нет — предмета у проверки нет (075)"
    headless = {
        name: said
        for name, said in cancelling.items()
        if "sha" not in said and name not in STATE_NOT_A_COMMIT and name not in ADVISORY_JOBS
    }
    assert not headless, (
        "прогон отменяет предыдущий, а голову в группе не называет: "
        + "; ".join(f"{name} → «{said}»" for name, said in sorted(headless.items()))
        + " — вытеснить может прогон на устаревшем коммите, и красного нигде не будет"
    )


def test_the_state_list_has_no_dead_or_silent_entries() -> None:
    """Список состояний живой и с причинами: иначе он разрешает несуществующее."""
    for name, why in STATE_NOT_A_COMMIT.items():
        assert why.strip(), f"{name}: объявлен состоянием без причины (154)"
        assert (WORKFLOWS / name).is_file(), f"{name}: объявлен состоянием, а прогона нет"
    live = cancelling_groups()
    for name, why in ADVISORY_JOBS.items():
        assert why.strip(), f"{name}: объявлен совещательным без причины (154)"
        assert name in live, f"{name}: объявлен совещательным, а отменяющей группы у него нет"
