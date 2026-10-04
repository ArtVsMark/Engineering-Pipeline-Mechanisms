"""Роды находок: форма держится машиной, существо — человеком.

Запись копит КОНТЕКСТ, в чём косяк, чтобы третий случай одного рода был отличим
от первого. Отличить их можно лишь тогда, когда род назван словами, по которым
его узнают в следующий раз, а встречи названы отпечатками, а не числом: число
рассохлось бы первой же новой находкой
([005](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/005-hand-written-numbers-rot.md)).

ЧЕГО ЭТОТ ГЕЙТ НЕ ЛОВИТ, и это названо, а не выровнено: ВЕРНОСТЬ отнесения
находки к роду. Отнесение — суждение, и машине оно недоступно; здесь держится
форма, как у таблицы послаблений
([046](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/046-name-the-gaps-do-not-level-them.md)).
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Final

import pytest

from tests.conftest import ROOT, load_script

module = load_script("finding_kinds.py")

#: Отпечаток находки: короткий хеш коммита, каким его печатает реестр.
FINGERPRINT: Final = re.compile(r"^[0-9a-f]{7}$")
#: Что похоже на адрес: путь с косой чертой либо имя файла с расширением, а
#: также номер правила или ответа. ЖИВОСТЬ ПРОВЕРЯЕТСЯ ОТНОШЕНИЕМ — существует
#: ли такой путь в дереве, — а не перечнем каталогов: перечень пропускал
#: корневые файлы, и встреча, названная `pyproject.toml`, объявлялась безадресной
#: (18.09.2026).
#:
#: НАЗНАЧЕНИЙ ДВА, И ВТОРОЕ НАЗВАНО ЗДЕСЬ, А НЕ ТОЛЬКО В МЕСТЕ ВЫЗОВА: этим же
#: образцом проверяется адрес встречи, пойманной ОКНОМ, — запись «окно: <адрес>»
#: обязана назвать живое место дерева, иначе она неотличима от воспоминания
#: ([166](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/166-check-the-link-not-the-path.md)).
LOOKS_LIKE_A_PATH: Final = re.compile(r"[\w.-]+(?:/[\w./-]+)*\.[a-z]{2,5}\b|[\w.-]+/[\w./-]+")
#: Номер правила каталога или нашего ответа — адрес не в дереве, а в договоре.
A_NUMBER: Final = re.compile(r"(?:правил|ответ)\w*\s+\d{3}")


def addressed(said: str) -> bool:
    """Назван ли в строке ЖИВОЙ адрес — путь дерева либо номер правила.

    Путь проверяется существованием, а не написанием: список каталогов угадал бы
    предмет и уже угадал — корневые файлы в него не попадали.
    """
    if A_NUMBER.search(said):
        return True
    return any((ROOT / one.split("::")[0]).exists() for one in LOOKS_LIKE_A_PATH.findall(said))


#: Короче этого признак рода — отписка, а не признак. Число то же, что у причин
#: витрины и пробелов: там оно взято у каталога, здесь берётся у них (022).
SIGN_AT_LEAST: Final = 60


def kinds() -> dict[str, dict[str, object]]:
    """Объявленные роды."""
    said: dict[str, dict[str, object]] = module.read()
    return said


def test_the_record_exists_and_is_not_empty() -> None:
    """Объявления нет — отказ, а не «родов нет» (075)."""
    assert kinds(), "роды находок не объявлены — предмет проверки не найден"


@pytest.mark.parametrize("name", sorted(kinds()), ids=lambda one: one)
def test_a_kind_says_what_the_mistake_is(name: str) -> None:
    """У рода назван ПРИЗНАК — то, по чему его узнают в следующий раз.

    Без него запись превращается в список ярлыков: имя рода есть, а отнести к
    нему новую находку не по чему, и счёт повторов становится вкусовым.
    """
    sign = str(kinds()[name].get("признак", "")).strip()
    assert len(sign) >= SIGN_AT_LEAST, (
        f"{name}: признак короче {SIGN_AT_LEAST} знаков — это ярлык, а не признак"
    )


@pytest.mark.parametrize("name", sorted(kinds()), ids=lambda one: one)
def test_a_kind_counts_by_fingerprints_not_by_a_number(name: str) -> None:
    """Встречи перечислены ПОШТУЧНО: число рассохлось бы первой же находкой (005).

    Штука — отпечаток находки внешнего взгляда либо запись «окно: <адрес>» о
    роде, пойманном собственным откатом до толчка. Второй формы до 18.09.2026
    не было, и это был не пробел оформления: род, дважды пойманный в окне,
    считался встреченным ноль раз и порога не достигал никогда.

    АДРЕС У ВСТРЕЧИ В ОКНЕ ОБЯЗАТЕЛЕН по той же причине, по какой обязателен у
    пометки «породил»: без него «поймали такое же» неотличимо от впечатления, а
    проверить нечем — коммита с находкой не существует.
    """
    met = kinds()[name].get("встречен")
    # ПУСТОЙ СПИСОК ЗАКОНЕН С 04.10.2026 (решение 038): список заморожен, и у
    # нового рода первая встреча — строка `Род:` в коммите, а не запись здесь.
    # Списком поле быть обязано: число рассохлось бы (005).
    assert isinstance(met, list), f"{name}: встречи не перечислены поштучно"
    wrong: list[str] = []
    for one in (str(each) for each in met):
        if FINGERPRINT.match(one):
            continue
        if one.startswith(module.IN_WINDOW):
            if not addressed(one[len(module.IN_WINDOW) :]):
                wrong.append(f"«{one}» — встреча в окне без адреса")
            continue
        wrong.append(f"«{one}» — ни отпечаток, ни «{module.IN_WINDOW}<адрес>»")
    assert not wrong, f"{name}: {'; '.join(wrong)}"


@pytest.mark.parametrize("name", sorted(kinds()), ids=lambda one: one)
def test_a_meeting_is_listed_once_per_kind(name: str) -> None:
    """Встреча стоит в списке рода один раз: дубль завысил бы счёт и порог (005).

    Так `bc5cb76` дважды стоял в «соседний текст описывает прежнее дерево» и
    прошёл зелёным (взгляд на #1077). ПРЕДЕЛ НАЗВАН (195): между РОДАМИ
    повтор законен — одна находка бывает двух родов, и таких отпечатков на
    04.10.2026 четыре (`dbf186b`, `ca9216b`, `4394e1f`, `1ad3e72`).
    """
    said = kinds()[name].get("встречен")
    # Повтор сверяется той же формой, что счёт (`mark_of`): `abc1234` в кавычках и
    # без — одна встреча (взгляд на #1092).
    met = [module.mark_of(one) for one in said] if isinstance(said, list) else []
    twice = sorted({one for one in met if met.count(one) > 1})
    assert not twice, f"{name}: встреча записана дважды — {twice}"


def test_the_word_no_is_matched_whole_not_by_prefix() -> None:
    """«Нет» узнаётся целым словом: приставка увела бы род в долг по первой букве.

    `startswith("нет")` читает «нетронутый», «нетривиально» и «нет-нет» как
    объявление отсутствия механизма — то есть род с ЖИВЫМ механизмом попал бы в
    долг, а долг перестал бы быть долгом
    ([141](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/141-a-marker-is-matched-whole-not-by-prefix.md)).
    """
    говорит_нет = ("нет", "НЕТ — причина", "нет, потому что", " нет — причина ")
    не_говорит = ("нетривиально держится разбором", "нетронутый гейт", "держится гейтом", "")
    wrong = [one for one in говорит_нет if not module.said_no(one)]
    assert not wrong, f"объявление отсутствия не опознано: {wrong}"
    wrong = [one for one in не_говорит if module.said_no(one)]
    assert not wrong, f"живой механизм прочитан как «нет» по приставке: {wrong}"


#: Куда отнести встречу: запись и сторона, на которой она обязана оказаться.
#: Таблица, а не сложение: сумма сходится у ЛЮБОГО разбиения, включая неверное.
ORIGINS = (
    ("отпечаток взгляда", "dbf186b", "взгляд"),
    ("отпечаток длиннее", "a1b2c3d4e5", "взгляд"),
    ("запись окна", "окно: tests/test_x.py — признак был шире", "окно"),
    # СЛОВО «ОКНО» ВНУТРИ ОПИСАНИЯ ВСТРЕЧЕЙ ОКНА НЕ ДЕЛАЕТ: приставка читается
    # с начала строки, а не где угодно в ней (141).
    ("слово «окно» в середине", "9661544 — окно перечитало свой же разбор", "взгляд"),
    ("похожее слово", "оконный гейт не видел формы", "взгляд"),
    # ФОРМА СТРОГАЯ, И ЭТО ПРОВЕРЕНО РЯДОМ: запись без пробела после двоеточия к
    # окну НЕ относится — и потому обязана быть отвергнута как встреча вовсе.
    # Тихо уехать в «взгляд» она не должна: там её приняли бы за отпечаток.
    ("окно без пробела — не эта форма", "окно:tests/test_x.py", "взгляд"),
)


@pytest.mark.parametrize(("case", "met", "side"), ORIGINS, ids=[one[0] for one in ORIGINS])
def test_each_meeting_lands_on_the_side_it_belongs_to(case: str, met: str, side: str) -> None:
    """Встреча относится к своей стороне: «взгляд» или «окно».

    ЗДЕСЬ БЫЛА ТАВТОЛОГИЯ, И НАШЁЛ ЕЁ ВЗГЛЯД. Прежняя редакция сверяла, что
    `взгляд + окно == len(встречен)` — а `origins` считает первое слагаемое
    ВЫЧИТАНИЕМ второго из длины, то есть равенство держалось по построению и не
    могло не сойтись. Проверка говорила о разбиении, ничего о нём не утверждая
    ([150](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/150-a-test-asks-the-mechanism-not-its-condition.md)).
    """
    seen, caught = module.origins({"встречен": [met]})
    got = "окно" if caught else "взгляд"
    assert (seen, caught) == ((0, 1) if side == "окно" else (1, 0)), (
        f"«{case}» отнесено к «{got}», а это {side}"
    )


@pytest.mark.parametrize("name", sorted(kinds()), ids=lambda one: one)
def test_the_split_of_origins_covers_every_meeting(name: str) -> None:
    """Ни одна встреча не теряется при разбиении: состав печатается сложением.

    Половина слабая, и сказано это вслух: сумма сходится у любого разбиения.
    Держит она другое — что `origins` не второй СПИСОК рядом с записью, а счёт
    по ней самой
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    Отнесение проверяет таблица выше.
    """
    body = kinds()[name]
    seen, caught = module.origins(body)
    met = body.get("встречен")
    assert seen + caught == len(met if isinstance(met, list) else []), (
        f"{name}: состав встреч не сходится с их числом — счёт разошёлся с записью"
    )


@pytest.mark.parametrize("name", sorted(kinds()), ids=lambda one: one)
def test_a_kind_says_what_holds_it_or_why_nothing_does(name: str) -> None:
    """Род держится механизмом либо называет причину, почему не держится (154)."""
    held = str(kinds()[name].get("закрыт", "")).strip()
    assert held, f"{name}: не сказано, чем род закрыт"
    if module.said_no(held):
        assert len(held) > len(module.NO_MECHANISM) + 10, (
            f"{name}: «{held}» — молчание под видом ответа; «нет» обязано назвать причину"
        )


@pytest.mark.parametrize("name", sorted(kinds()), ids=lambda one: one)
def test_what_the_kind_gave_birth_to_is_addressable(name: str) -> None:
    """Пометка «породил» называет АДРЕС, а не впечатление.

    Род бывает закрыт чужим, давно стоявшим механизмом, — а бывает тем, который
    из него и родился. Без пометки повторный род выглядит бесплодным, хотя из
    него вышло правило; с пометкой без адреса она неотличима от похвалы.
    """
    born = kinds()[name].get(module.BORN)
    if born is None:
        return
    assert isinstance(born, list) and born, f"{name}: «породил» объявлен пустым"
    mute = [str(one) for one in born if not addressed(str(one))]
    assert not mute, (
        f"{name}: «породил» без адреса — {'; '.join(one[:60] for one in mute)}."
        " Назовите механизм путём, а правило — номером."
    )


def test_a_repeated_kind_without_a_mechanism_is_named() -> None:
    """Повтор без механизма НАЗЫВАЕТСЯ, а не тонет среди прочих родов.

    Это и есть польза записи: род, встреченный трижды, — вход в гейт или в
    предложение правила. Пока роды жили в памяти окна, третий случай был
    неотличим от первого
    ([049](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/049-derive-state-from-live-artifacts.md)).
    """
    said = kinds()
    repeated = module.repeated(said)
    assert repeated, "повторяющихся родов нет вовсе — порог либо предмет выбран неверно"
    debt = module.unheld(said)
    for name, times in debt:
        assert times >= module.REPEATED_AT
        assert module.said_no(str(said[name].get("закрыт", "")))


def test_the_threshold_is_declared_not_buried() -> None:
    """Порог повтора объявлен именем, а не вписан числом посреди разбора (005)."""
    assert isinstance(module.REPEATED_AT, int)
    assert 2 <= module.REPEATED_AT <= 5, (
        f"порог повтора {module.REPEATED_AT}: два — это совпадение, больше пяти — уже не ряд"
    )


def test_the_skill_and_the_record_name_each_other() -> None:
    """Навык разбора находки зовёт эту запись, а запись зовётся им.

    Механизм без процедуры остаётся числом, которое некому заполнить: роды
    называет человек в минуту разбора
    ([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).
    """
    skill = ROOT / ".claude" / "skills" / "close-a-finding" / "SKILL.md"
    said = skill.read_text(encoding="utf-8")
    assert "scripts/finding_kinds.py" in said, "навык не зовёт механизма родов"
    assert "finding-kinds.json" in said, "навык не называет, куда записывать род"


def test_the_walk_names_the_kinds(run_script) -> None:  # type: ignore[no-untyped-def]
    """Заход процессом называет роды и выходит нулём; на мелком клоне — отказывает вслух.

    Счёт встреч читает историю (#1022), и глубина клона — свойство среды, а не
    дерева: взгляд идёт по `fetch-depth: 1` (взгляд на #1086). Прогоняются
    оба исхода — какой из двух, решает среда, а не пропуск.
    """
    done = run_script("finding_kinds.py")
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    if shallow == "true":
        assert done.code == module.EXIT_BROKEN, done.out
        assert module.trunk_log.SHALLOW in done.err, done.err
        return
    assert done.code == module.EXIT_OK, done.err
    assert "родов" in done.out, done.out


def test_a_missing_record_is_the_third_outcome(tmp_path, run_script) -> None:  # type: ignore[no-untyped-def]
    """Объявления нет — отказ с адресом, а не «родов ноль» (075).

    «Родов ноль» прозвучало бы как «повторов нет», то есть отказ входа выдал бы
    себя за вердикт (045).
    """
    done = run_script("finding_kinds.py", "--kinds", str(tmp_path / "нет.json"))
    assert done.code == module.EXIT_BROKEN
    assert "взять неоткуда" in done.err, done.err


def test_a_window_record_written_loosely_is_refused_not_recounted() -> None:
    """Запись «окно:» без пробела — не встреча вовсе, а не встреча взгляда.

    Разбиение относит её к «взгляду», потому что приставки там нет; если бы на
    этом всё и кончалось, кривая запись считалась бы отпечатком находки, которой
    не было. Поэтому форму держит отдельная проверка, и здесь прогоняется
    именно она — отказ, а не пересчёт
    ([141](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/141-a-marker-is-matched-whole-not-by-prefix.md)).
    """
    said = "окно:tests/test_finding_kinds.py"
    assert not FINGERPRINT.match(said), "кривая запись прошла бы за отпечаток"
    assert not said.startswith(module.IN_WINDOW), "форма встречи в окне требует пробела"


def test_a_repeated_kind_without_a_catalogue_answer_is_named() -> None:
    """Род у порога без ответа каталогу называется; с ответом или ниже порога — нет (#650)."""
    met = ["a", "b", "c"]
    kinds = {
        "молчит": {"встречен": met},
        "ответил": {"встречен": met, "каталогу": "своё — у каталога этого нет"},
        "не по форме": {"встречен": met, "каталогу": "потом посмотрим"},
        "редкий": {"встречен": ["a"]},
    }
    assert module.unanswered(kinds, "") == [("молчит", 3), ("не по форме", 3)]


def test_a_broken_kinds_file_is_a_refusal_not_a_crash(tmp_path: Path) -> None:
    """Битый словарь — `NotRun` для гейта и плана, а не сырой `JSONDecodeError` (`ff0aeef`)."""
    broken = tmp_path / "kinds.json"
    broken.write_text("{не json", encoding="utf-8")
    with pytest.raises(module.NotRun, match="не разбирается"):
        module.read(broken)


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ('{"kinds": "x"}', "раздел kinds не словарь, а str"),
        ('{"kinds": ["a"]}', "раздел kinds не словарь, а list"),
        ('["kinds"]', "не объект JSON"),
    ],
)
def test_kinds_of_a_foreign_shape_are_a_refusal_for_every_reader(text: str, said: str) -> None:
    """Не та форма словаря — `NotRun`, а не `ValueError` из `dict()` (`19fe125`, `948f893`).

    Разбор один на диск и на историю: план, гейт рождения правила и сам
    счёт родов ловят одно и то же исключение.
    """
    with pytest.raises(module.NotRun, match=said):
        module.kinds_in(text, "словарь")


def test_kinds_absent_from_the_text_are_empty_not_a_refusal() -> None:
    """Раздела kinds нет — пусто: у базы родов ещё могло не быть, а решает читающий."""
    assert module.kinds_in("{}", "словарь") == {}
    assert module.kinds_in('{"kinds": {"род": {}}}', "словарь") == {"род": {}}


def test_a_foreign_shape_reaches_the_entry_point(tmp_path, run_script) -> None:  # type: ignore[no-untyped-def]
    """Раздел kinds строкой доезжает до исхода «не отработал» точкой входа (145)."""
    broken = tmp_path / "kinds.json"
    broken.write_text('{"kinds": "x"}', encoding="utf-8")
    done = run_script("finding_kinds.py", "--kinds", str(broken))
    assert done.code == module.EXIT_BROKEN
    assert "раздел kinds не словарь" in done.err, done.err


def test_a_missing_queue_is_a_refusal_not_an_empty_queue(tmp_path: Path) -> None:
    """Очереди предложений нет — `NotRun`, а не `""` (`dd1da87`); есть — её текст."""
    with pytest.raises(module.NotRun, match="очередь предложений не прочитана"):
        module.queued(tmp_path / "нет.json")
    queue = tmp_path / "proposals.json"
    queue.write_text('{"proposals": [{"slug": "a"}]}', encoding="utf-8")
    assert '"a"' in module.queued(queue)


def test_an_answer_is_judged_by_one_function() -> None:
    """`answer_problem` судит ответ рода: форма, слаг в очереди, номер правила (`72397b3`)."""
    queue = '{"proposals": [{"slug": "a-list-is-read-to-the-end"}]}'
    assert module.answer_problem({"каталогу": "своё — у каталога такого нет"}, queue) is None
    assert module.answer_problem({"каталогу": "есть — 206"}, queue) is None
    assert (
        module.answer_problem({"каталогу": "предложено — `a-list-is-read-to-the-end`."}, queue)
        is None
    )
    assert "в очереди" in str(module.answer_problem({"каталогу": "предложено — other"}, queue))
    assert "номера" in str(module.answer_problem({"каталогу": "есть — где-то"}, queue))
    assert "нет или оно не по форме" in str(module.answer_problem({}, queue))
    assert module.slug_of("`имя`.") == "имя"


def test_a_kind_shows_its_fate_in_the_archive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--archive` читает судьбу встреч рода из архива: сколько в нём и сколько снято (#778)."""
    archive = {
        "findings": {
            "aaaaaaa": {"род": "подстрока вместо отношения", "resolved_by": 790},
            "bbbbbbb": {"род": "подстрока вместо отношения", "resolved_by": None},
            "ddddddd": {
                "род": "подстрока вместо отношения",
                "resolved_by": 791,
                "twin_of": "aaaaaaa",
            },
            "ccccccc": {"род": None},
        }
    }
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(archive, ensure_ascii=False), encoding="utf-8")
    # Дубль снят связью, а не работой — отдельным числом (взгляд на #817).
    # Запись без рода считается своей строкой, а не выпадает (взгляд на #822).
    found = ({"подстрока вместо отношения": (3, 1, 1), module.NO_KIND: (1, 0, 0)}, "")
    assert module.in_archive(path) == found
    assert module.main(["--archive", str(path)]) == module.EXIT_OK
    said = capsys.readouterr().out
    assert "архив: 3, снято работой 1, дублем 1" in said
    assert f"{module.KINDLESS} 1 — снято работой 0, дублем 0" in said
    assert module.OUTSIDE not in said


def test_an_unfilled_archive_says_so_in_the_kinds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Неполный архив называет себя, а счёт родов по нему не выдаётся за полный (045)."""
    gap = "наполнение не дошло до головы: не учтено слитых изменений — 5"
    archive = {"gaps": [gap], "findings": {"a": {"род": "р", "resolved_by": None}}}
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(archive, ensure_ascii=False), encoding="utf-8")
    assert module.in_archive(path)[1] == gap
    module.main(["--archive", str(path)])
    assert module.findings.UNFILLED_SAID in capsys.readouterr().out


def test_kinds_from_another_dictionary_are_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """С `--kinds` сказано, что роды архива заморожены на момент его сборки."""
    kinds = module.paths.FINDING_KINDS
    archive = tmp_path / "findings.json"
    archive.write_text(
        json.dumps({"findings": {"a": {"род": "р"}}}, ensure_ascii=False), encoding="utf-8"
    )
    module.main(["--kinds", str(kinds), "--archive", str(archive)])
    assert "не по --kinds" in capsys.readouterr().out


def test_an_unreadable_archive_is_a_refusal(tmp_path: Path) -> None:
    """Архив не читается — отказ с причиной, а не роды без судьбы."""
    assert module.main(["--archive", str(tmp_path / "нет.json")]) == module.EXIT_BROKEN


def test_a_kind_outside_the_dictionary_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Род архива, которого нет в словаре, печатается отдельно, а не выпадает (#817)."""
    path = tmp_path / "findings.json"
    archive = {"findings": {"a": {"род": "снятый род", "resolved_by": 1}}}
    path.write_text(json.dumps(archive, ensure_ascii=False), encoding="utf-8")
    module.main(["--archive", str(path)])
    assert (
        "род архива вне словаря: снятый род — архив: 1, снято работой 1" in capsys.readouterr().out
    )


def test_an_empty_kind_name_is_a_refusal() -> None:
    """Пустое имя рода — отказ: оно занято записями без рода (#830)."""
    with pytest.raises(module.NotRun, match="пустое имя"):
        module.kinds_in('{"kinds": {"": {"встречен": []}}}', "словарь")


def test_a_rule_answer_names_a_rule_the_project_answers(tmp_path: Path) -> None:
    """Ответ «есть — N» сверяется с `.rules/bindings.json`: опечатка номера краснеет (#887)."""
    bindings = tmp_path / "bindings.json"
    bindings.write_text('{"rules": {"212": {}}}', encoding="utf-8")
    known = module.known_rules(bindings)
    assert module.answer_problem({"каталогу": "есть — 212"}, "", known) is None
    assert "211" in str(module.answer_problem({"каталогу": "есть — 211"}, "", known))
    with pytest.raises(module.NotRun, match=f"^{module.ANSWERS_UNREAD}"):
        module.known_rules(tmp_path / "нет.json")
    bindings.write_text("{}", encoding="utf-8")
    with pytest.raises(module.NotRun, match=f"^{module.ANSWERS_UNREAD}"):
        module.known_rules(bindings)


def test_twins_are_counted_over_resolved_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Доля дублей отрезка — от разобранных; неразобранное дублем не считается (#859, #891)."""
    archive = tmp_path / "findings.json"
    archive.write_text(
        json.dumps(
            {
                "findings": {
                    "a": {"pr": 10},
                    "b": {"pr": 10},
                    "c": {"pr": 11},
                    "d": {"pr": 12},
                    "e": {"pr": 99},
                },
                "resolutions": {
                    "a": {"by": 10, "twin_of": "b"},
                    "b": {"by": 10, "twin_of": ""},
                    "c": {"by": 11, "twin_of": "", "fix_check": True},
                },
                "counted": [10, 11, 12, 99],
            }
        ),
        encoding="utf-8",
    )
    assert module.twins_between(archive, 10, 12) == ((3, 4, 3, 1, 1), "")
    assert module.main(["--archive", str(archive), "--twins", "10-12"]) == module.EXIT_OK
    assert f"33% {module.TWIN_SHARE}" in capsys.readouterr().out
    assert module.main(["--twins", "10-12"]) == module.EXIT_BROKEN


@pytest.mark.parametrize(
    "said",
    [
        [],
        {"findings": []},
        {"findings": {"a": "x"}},
        {"findings": {"a": {"pr": 10}}, "resolutions": []},
        {"findings": {"a": {"pr": 10}}, "resolutions": {"a": "x"}},
        {"findings": {"a": {"pr": [10]}}},
        {"findings": {"a": {"pr": {"x": 1}}}},
        {"findings": {"a": {"pr": "10"}}},
        {"findings": {"a": {"pr": True}}},
    ],
    ids=[
        "архив списком",
        "записи списком",
        "запись строкой",
        "разборы списком",
        "разбор строкой",
        "номер списком",
        "номер словарём",
        "номер строкой",
        "номер логическим",
    ],
)
def test_twins_refuse_an_archive_of_another_shape(tmp_path: Path, said: object) -> None:
    """Архив чужой формы — отказ `NotRun`, а не пустой счёт или трасса (039, #891)."""
    archive = tmp_path / "findings.json"
    archive.write_text(json.dumps(said), encoding="utf-8")
    with pytest.raises(module.NotRun):
        module.twins_between(archive, 10, 12)


def test_twins_name_an_unfilled_archive(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Неполный архив замер называет, как и счёт родов: ноль не выглядит полным (045, #891)."""
    archive = tmp_path / "findings.json"
    gap = f"{module.findings.UNFILLED} до #12"
    archive.write_text(
        json.dumps({"findings": {"a": {"pr": 10}}, "gaps": [gap], "counted": [10]}),
        encoding="utf-8",
    )
    assert module.twins_between(archive, 10, 12) == ((1, 1, 0, 0, 0), gap)
    assert module.main(["--archive", str(archive), "--twins", "10-12"]) == module.EXIT_OK
    assert gap in capsys.readouterr().out


@pytest.mark.parametrize(
    ("text", "named", "unnamed"),
    [
        ("855", "SPAN_FORM", "SPAN_INVERTED"),
        ("855-", "SPAN_FORM", "SPAN_INVERTED"),
        ("-890", "SPAN_FORM", "SPAN_INVERTED"),
        ("a-b", "SPAN_FORM", "SPAN_INVERTED"),
        ("890-855", "SPAN_INVERTED", "SPAN_FORM"),
    ],
    ids=["без дефиса", "без конца", "без начала", "не числа", "перевёрнут"],
)
def test_a_span_of_another_form_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, named: str, unnamed: str
) -> None:
    """Чужая запись отрезка — отказ со СВОЕЙ причиной, а не `int()` и не «находок 0»."""
    archive = tmp_path / "findings.json"
    archive.write_text("{}", encoding="utf-8")
    assert module.main(["--archive", str(archive), "--twins", text]) == module.EXIT_BROKEN
    said = capsys.readouterr().err
    assert getattr(module, named) in said
    assert getattr(module, unnamed) not in said


@pytest.mark.parametrize(
    ("text", "read"), [("855-890", (855, 890)), ("7-7", (7, 7))], ids=["отрезок", "одно изменение"]
)
def test_a_span_of_the_form_is_read(text: str, read: tuple[int, int]) -> None:
    """Отрезок по форме читается числами; его провал не прячется среди отказов (взгляд на #895)."""
    assert module.span(text) == read


@pytest.mark.parametrize(
    "counted", [[], [9, 13]], ids=["архив ничего не учёл", "учтено только вне отрезка"]
)
def test_a_span_the_archive_did_not_count_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], counted: list[int]
) -> None:
    """Отрезок без учтённых изменений — отказ, как у `finding_chains`, а не «находок 0» (045)."""
    archive = tmp_path / "findings.json"
    archive.write_text(
        json.dumps({"findings": {"a": {"pr": 11}}, "counted": counted}), encoding="utf-8"
    )
    with pytest.raises(module.NotRun, match=re.escape(module.findings.NONE_COUNTED)):
        module.twins_between(archive, 10, 12)
    assert module.main(["--archive", str(archive), "--twins", "10-12"]) == module.EXIT_BROKEN
    assert module.findings.NONE_COUNTED in capsys.readouterr().err


def test_rule_numbers_are_read_by_one_parser() -> None:
    """Номера правил — ключи раздела `rules`; неразборный текст — `ValueError` (#887)."""
    assert module.rule_numbers('{"rules": {"212": {}, "033": {}}}') == frozenset({"212", "033"})
    assert module.rule_numbers('{"rules": {}}') == frozenset(), "пустой раздел — сказанное «нет»"
    for broken in ("{", "[]", '"x"', '{"rules": []}', "{}", '{"rules": null}'):
        with pytest.raises(ValueError):
            module.rule_numbers(broken)


def test_a_partly_counted_span_names_what_the_archive_saw(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Отрезок, покрытый частично, печатает число учтённых изменений (взгляд на #897)."""
    archive = tmp_path / "findings.json"
    archive.write_text(
        json.dumps({"findings": {"a": {"pr": 11}}, "counted": [10, 11]}), encoding="utf-8"
    )
    assert module.twins_between(archive, 10, 8900)[0][0] == 2
    assert module.main(["--archive", str(archive), "--twins", "10-8900"]) == module.EXIT_OK
    assert f"{module.SPAN_SEEN} 2," in capsys.readouterr().out


def test_rule_answers_read_the_section_or_refuse() -> None:
    """Ответы — раздел `rules` целиком; без него или не объектом — `ValueError` (#900)."""
    assert module.rule_answers('{"rules": {"212": {"x": 1}}}') == {"212": {"x": 1}}
    assert module.rule_answers('{"rules": {}}') == {}
    for broken in ("{}", "[]", '{"rules": []}', '{"rules": {"1": "x"}}', '{"rules": {"1": []}}'):
        with pytest.raises(ValueError):
            module.rule_answers(broken)


def test_every_written_catalogue_answer_is_still_true() -> None:
    """Записанный ответ каталогу сходится с ЖИВОЙ очередью и номерами — у каждого рода.

    Гейт `check_rule_birth` судит ответ только у рода, дошедшего до порога в
    изменении (взгляд на #1044, `4e853a0`). Ответ стареет и без этого: когда
    предложение уходит из очереди — принято или снято, — род, который на него
    ссылается, продолжает отвечать «предложено — <слаг>», и ни одно изменение
    этого рода не трогает. Так #1020 снял предложение 215, а род «пересказ
    своей работы» до #1044 отвечал на него. Здесь сверяются все роды, у
    которых ответ записан; рода без ответа это не касается — его требует порог.
    """
    kinds = module.read(ROOT / ".rules" / "finding-kinds.json")
    queue = module.queued(ROOT / ".rules" / "proposals.json")
    known = module.known_rules(ROOT / ".rules" / "bindings.json")
    written = {name: body for name, body in kinds.items() if module.CATALOGUE in body}
    assert written, "ни у одного рода ответ каталогу не записан — сверять нечего (075)"
    stale = {
        name: problem
        for name, body in written.items()
        if (problem := module.answer_problem(body, queue, known)) is not None
    }
    assert not stale, f"ответ каталогу разошёлся с очередью или номерами: {stale}"


@pytest.fixture(autouse=True)
def no_trunk_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вход набора — подделки, а не история дерева, в котором он идёт (#1022).

    Без подмены `main` считал бы встречи по настоящей истории общей ветки, и
    число в проверке зависело бы от того, сколько строк `Род:` уже слито.
    """
    monkeypatch.setattr(module.trunk_log, "merged_bodies", lambda *_, **__: [])
    monkeypatch.setattr(module.trunk_log, "unseen", lambda *_, **__: 0)


def history_kinds(*met: str) -> dict[str, object]:
    """Словарь с одним родом «род» и замороженными встречами."""
    return {"род": {"признак": "x", "встречен": list(met), "закрыт": "нет — нечем"}}


def test_a_kind_line_counts_one_meeting_per_twin_root() -> None:
    """Одна встреча на корень дублей: «A дубль B» — одна, две пары — две (#1022)."""
    bodies = [
        "Разобрано: aaaaaaa дубль bbbbbbb — один дефект\nРод: род",
        "Разобрано: ccccccc дубль ddddddd, eeeeeee дубль fffffff\nРод: род",
        "Разобрано: 1111111, 2222222 дубль 3333333\nРод: род",
    ]
    assert module.met_in_history(bodies, {}) == {
        "род": ["bbbbbbb", "ddddddd", "fffffff", "3333333"]
    }


def test_twin_roots_name_the_root_and_the_whole_chain() -> None:
    """Корень — отпечаток без двойника, а группа несёт всю цепочку: по ней сверяют повтор."""
    (record,) = module.changerefs.resolutions_parsed(
        "Разобрано: aaaaaaa дубль bbbbbbb, ccccccc\nРод: род"
    )
    assert module.twin_roots(record) == [
        ("bbbbbbb", frozenset({"aaaaaaa", "bbbbbbb"})),
        ("ccccccc", frozenset({"ccccccc"})),
    ]


def test_a_chain_and_a_loop_are_one_meeting() -> None:
    """Цепочка «A дубль B дубль C» — одна встреча с корнем C; круг — одна, первым названным."""
    bodies = [
        "Разобрано: aaaaaaa дубль bbbbbbb дубль ccccccc\nРод: род",
        "Разобрано: ddddddd дубль ddddddd\nРод: род",
    ]
    assert module.met_in_history(bodies, {}) == {"род": ["ccccccc", "ddddddd"]}


def test_a_meeting_is_not_counted_twice() -> None:
    """Отпечаток в замороженном списке или раньше в истории — та же встреча."""
    bodies = [
        "Разобрано: aaaaaaa\nРод: род",
        "Разобрано: aaaaaaa\nРод: род",
        "Разобрано: bbbbbbb дубль ccccccc\nРод: род",
        "Разобрано: ddddddd\nРод: род",
    ]
    assert module.met_in_history(bodies, history_kinds("`ccccccc`", "ddddddd")) == {
        "род": ["aaaaaaa"]
    }


def test_no_kind_and_a_refused_kind_are_not_meetings() -> None:
    """Снятие без `Род:`, с пустой строкой между ними и `Род: нет — …` встреч не дают."""
    bodies = [
        "Разобрано: aaaaaaa",
        "Разобрано: bbbbbbb\n\nРод: род",
        "Разобрано: ccccccc\nРод: нет — находка про прозу, рода у неё нет",
    ]
    assert module.met_in_history(bodies, {}) == {}


def test_a_window_meeting_is_counted_once_by_its_place() -> None:
    """Встреча в окне — пара «род, место»: повтор в истории и в словаре не считается."""
    bodies = [
        "Род: род — окно: tests/test_x.py — первая редакция",
        "Род: род — окно: tests/test_x.py — первая редакция",
        "Род: род — окно: tests/test_y.py — откат зелёный",
    ]
    frozen = history_kinds("окно: tests/test_y.py — откат зелёный")
    assert module.met_in_history(bodies, frozen) == {
        "род": ["окно: tests/test_x.py — первая редакция"]
    }


def test_history_adds_to_the_frozen_list_and_names_the_outsiders() -> None:
    """`with_history`: встречи истории дописаны к роду, род вне словаря назван отдельно."""
    bodies = ["Разобрано: aaaaaaa\nРод: род", "Разобрано: bbbbbbb\nРод: опечатка"]
    merged, outside = module.with_history(history_kinds("1111111", "2222222"), bodies)
    assert merged["род"]["встречен"] == ["1111111", "2222222", "aaaaaaa"]
    assert outside == {"опечатка": ["bbbbbbb"]}
    assert module.repeated(merged) == [("род", 3)]


def test_without_kind_lines_the_count_is_the_frozen_one() -> None:
    """Приёмка #1022 числом: пока строк `Род:` нет, счёт совпадает с прежним."""
    kinds = module.read()
    merged, outside = module.with_history(kinds, ["Разобрано: aaaaaaa", "Тема без снятий"])
    assert merged == kinds and outside == {}


def test_the_entry_point_names_the_history_and_its_outsiders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`main` печатает долю истории в счёте и род истории вне словаря (045)."""
    kinds = tmp_path / "kinds.json"
    kinds.write_text(json.dumps({"kinds": history_kinds("1111111")}, ensure_ascii=False))
    bodies = ["Разобрано: aaaaaaa\nРод: род", "Разобрано: bbbbbbb\nРод: опечатка"]
    monkeypatch.setattr(module.trunk_log, "merged_bodies", lambda *_, **__: bodies)
    assert module.main(["--kinds", str(kinds)]) == module.EXIT_OK
    out = capsys.readouterr().out
    assert f"встреч 2 ({module.HISTORY_SAID} origin/main — 1)" in out
    assert f"{module.OUTSIDE_HISTORY} опечатка — встреч 1" in out


def test_merges_without_squash_are_named_by_number(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Слияния без уплотнения называются числом: их строк `Род:` счёт не видит (045)."""
    monkeypatch.setattr(module.trunk_log, "unseen", lambda *_, **__: 17)
    assert module.main([]) == module.EXIT_OK
    assert f"{module.UNSEEN_SAID} 17" in capsys.readouterr().out


def test_an_unreadable_history_is_the_third_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """История не прочитана — отказ, а не счёт по одному словарю (045)."""

    def refuse(*_: object, **__: object) -> list[str]:
        raise module.trunk_log.NotRun(module.trunk_log.SHALLOW)

    monkeypatch.setattr(module.trunk_log, "merged_bodies", refuse)
    assert module.main([]) == module.EXIT_BROKEN
    assert module.trunk_log.SHALLOW in capsys.readouterr().err


def test_an_old_name_in_history_counts_under_the_new_one() -> None:
    """Строка `Род:` со старым именем считается под нынешним: историю не переписать (#1090)."""
    kinds = {"новое": {"признак": "x", "встречен": ["1111111"], "прежде": ["старое"]}}
    merged, outside = module.with_history(kinds, ["Разобрано: aaaaaaa\nРод: старое"])
    assert merged["новое"]["встречен"] == ["1111111", "aaaaaaa"] and outside == {}


@pytest.mark.parametrize(
    ("said", "ok"),
    [
        ("нет — опечатка", True),
        ("нет потому что опечатка", True),
        ("нет; опечатка", True),
        ("нет: опечатка", True),
        ("нет, опечатка", True),
        ("нет—опечатка", True),
        ("нет – 1 случай", True),
        ("нет — —", False),
        ("нет", False),
    ],
)
def test_a_refused_kind_needs_a_reason_by_form(said: str, ok: bool) -> None:
    """Причина у «Род: нет» — по форме, а не по числу слов (взгляд на #1090)."""
    assert bool(module.REFUSED_RE.match(said)) is ok


def test_successor_of_maps_every_old_name() -> None:
    """Каждое имя из «прежде» указывает на нынешний род; без поля — ничего."""
    kinds = {"новое": {"прежде": ["a", "b"]}, "своё": {}}
    assert module.successor_of(kinds) == {"a": "новое", "b": "новое"}


def test_one_finding_may_meet_two_kinds() -> None:
    """Отпечаток в словаре у одного рода — встреча и другого, если `Род:` его называет (#1092)."""
    kinds = {
        "первый": {"встречен": ["aaaaaaa"]},
        "второй": {"встречен": []},
    }
    assert module.met_in_history(["Разобрано: aaaaaaa\nРод: второй"], kinds) == {
        "второй": ["aaaaaaa"]
    }
    # Вторая половина: под тем же родом повтор по-прежнему не считается.
    assert module.met_in_history(["Разобрано: aaaaaaa\nРод: первый"], kinds) == {}


def test_a_migrated_meeting_is_not_counted_again_under_the_old_name() -> None:
    """Перенесённый в нынешний род отпечаток под `Род: старое` не считается вновь (#1093)."""
    kinds = {"новое": {"встречен": ["aaaaaaa"], "прежде": ["старое"]}}
    assert module.met_in_history(["Разобрано: aaaaaaa\nРод: старое"], kinds) == {}


def test_one_chain_under_the_old_and_the_new_name_is_one_meeting() -> None:
    """Одна цепочка под строками `Род: старое` и `Род: новое` — одна встреча (#1093)."""
    kinds = {"новое": {"встречен": [], "прежде": ["старое"]}}
    bodies = ["Разобрано: bbbbbbb\nРод: старое", "Разобрано: bbbbbbb\nРод: новое"]
    assert module.met_in_history(bodies, kinds) == {"новое": ["bbbbbbb"]}


def test_one_old_name_under_two_kinds_is_refused() -> None:
    """Одно прежнее имя у двух родов — отказ, а не «последний побеждает» (#1093)."""
    kinds = {"первый": {"прежде": ["старое"]}, "второй": {"прежде": ["старое"]}}
    with pytest.raises(module.NotRun, match="у двух родов"):
        module.successor_of(kinds)


def test_mark_of_strips_the_backticks() -> None:
    """`mark_of` — одна форма встречи на счёт и на проверку повтора (#1092)."""
    assert module.mark_of("`abc1234`") == module.mark_of("abc1234") == "abc1234"
