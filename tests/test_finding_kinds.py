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

from __future__ import annotations

import json
import re
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
    assert isinstance(met, list) and met, f"{name}: встречи не перечислены поштучно"
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
    """Заход процессом называет роды и выходит нулём — исход прогоняется."""
    done = run_script("finding_kinds.py")
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
    assert "записей архива без рода: 1 — снято работой 0, дублем 0" in said
    assert "род архива вне словаря:" not in said


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
    assert "АРХИВ НЕПОЛОН" in capsys.readouterr().out


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
