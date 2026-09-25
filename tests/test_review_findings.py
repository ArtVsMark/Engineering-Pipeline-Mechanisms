"""Разбор вердикта ревьюера и живая задача-адресат.

Находка читается СТРОКАМИ, а не прозой (166): формулировка ревьюера меняется от
прогона к прогону, а строка — нет. Здесь проверяется именно это чтение, потому
что на нём держится всё остальное: не распознанная строка равна потерянной
находке, и потеря выглядит как «находок нет».
"""

from __future__ import annotations

import itertools
import re
from typing import Any, Final

import pytest
import yaml

from tests.conftest import ROOT, load_script

module = load_script("review_findings.py")
findings_module = load_script("findings.py")


def comment(body: str) -> dict[str, Any]:
    """Комментарий в том виде, в каком его отдаёт площадка."""
    return {"body": body}


def test_fingerprint_survives_reflow() -> None:
    """Отпечаток не зависит от переносов и лишних пробелов.

    Заголовок находки переносят при правке — если бы отпечаток от этого менялся,
    снятая запись возвращалась бы следующим заходом как новая.
    """
    one = module.fingerprint("гейт не проверяет свой предмет")
    two = module.fingerprint("гейт  не проверяет\n  свой предмет")
    assert one == two
    assert len(one) == 7


def test_findings_are_read_in_order_without_repeats() -> None:
    """Находки берутся по порядку и без повторов между комментариями."""
    comments = [
        comment("НАХОДКА[дефект]: первая\nтекст\nНАХОДКА[риск]: вторая"),
        comment("НАХОДКА[дефект]: первая\nВЕРДИКТ: находок 2"),
    ]
    assert module.findings_of(comments) == [("дефект", "первая", "код"), ("риск", "вторая", "код")]


def test_finding_survives_markdown_decoration() -> None:
    """Оформление вокруг заголовка не мешает: ревьюер пишет прозой вокруг строк."""
    assert module.findings_of([comment("НАХОДКА[замечание]: **жирный заголовок**")]) == [
        ("замечание", "жирный заголовок", "код")
    ]


def test_a_key_survives_emphasis_around_it() -> None:
    """Выделение ВОКРУГ КЛЮЧА не теряет находку — ревьюер пишет в markdown.

    ЗАМЕР 21.09.2026, РАДИ КОТОРОГО ПРОВЕРКА ЗАВЕДЕНА. По шестидесяти
    изменениям разбор видел 166 строк ключа и СЕМЬ терял молча: `**НАХОДКА…**`
    на #538, #548, #550 (две), #577, #598, #611. Работа взгляда пропадала
    целиком — находки не доезжали до реестра #23, и снять их было нечем,
    потому что записи не существовало
    ([016](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/016-no-silent-truncation.md)).

    Соседка выше проверяла выделение ВНУТРИ заголовка и была зелёной; её
    докстрока при этом обещала «оформление вокруг заголовка не мешает» —
    обещание шире проверенного. Здесь проверяется обещанное.
    """
    said = [
        comment("**НАХОДКА[дефект]:** маркер жирный, заголовок снаружи"),
        comment("**НАХОДКА[риск]: строка жирная целиком**"),
        comment("### НАХОДКА[замечание]: ключ заголовком раздела"),
    ]
    assert module.findings_of(said) == [
        ("дефект", "маркер жирный, заголовок снаружи", "код"),
        ("риск", "строка жирная целиком", "код"),
        ("замечание", "ключ заголовком раздела", "код"),
    ]


def test_a_verdict_survives_emphasis_around_it() -> None:
    """То же у вердикта, и цена потери здесь ВЫШЕ, а не ниже.

    Потерянная находка — минус одна запись; потерянный вердикт — отказ всего
    захода: `verdict_of` отдаёт `None`, и разбор объявляет третий исход. Замер
    нашёл такие строки на #548, #603 и #611.
    """
    assert module.verdict_of([comment("**ВЕРДИКТ: находок 1**")]) == 1
    assert module.verdict_of([comment("### ВЕРДИКТ: находок 4")]) == 4
    assert module.verdict_of([comment("ВЕРДИКТ: находок 0")]) == 0


def test_prose_about_findings_is_not_a_finding() -> None:
    """Вторая половина: ЗАГОЛОВОК РАЗДЕЛА ключом не становится.

    Без неё послабление превращается в «упомянуто слово» — такой разбор завёл
    бы запись с пустым или служебным заголовком, и снять её было бы нечем:
    работы, которая её чинит, не существует. Ровно этот призрак разбирался на
    #414, и ради него заведён словарь отрицаний
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md),
    [140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).

    В том же замере таких строк пятнадцать — больше, чем самих потерь: «###
    Находка», «**Находка:**», «Находка одна:». Предмет у них идёт СЛЕДУЮЩЕЙ
    строкой, и ключом они не являются.
    """
    for said in ("### Находка", "**Находка:**", "Находка одна:", "## Находки"):
        assert module.findings_of([comment(said)]) == [], f"«{said}» записано находкой"


def test_a_quoted_key_is_not_the_reviewers_own() -> None:
    """Цитата `>` ключом не считается: пересказ чужого — не находка.

    Граница названа вслух, а не оставлена на память
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    Иначе ответ, пересказывающий прошлый заход, заводил бы записи заново — той
    же бедой, от которой заведён `existing_mark`.
    """
    assert module.findings_of([comment("> НАХОДКА[дефект]: это пересказ чужого")]) == []
    assert module.verdict_of([comment("> ВЕРДИКТ: находок 9")]) is None


#: Разметка, которой ревьюер окружает строку ключа. Набор взят ЗАМЕРОМ по ленте
#: обзоров 21.09.2026, а не перечислением по памяти — ровно этого требует 206.
#: Буллет со звёздочкой стоит рядом с жирным намеренно: их сочетание и уронило
#: первую редакцию починки, как до того роняло соседа на #415.
DRESSED: Final = (
    "{key}",
    "**{key}**",
    "__{key}__",
    "*{key}*",
    "### {key}",
    "- {key}",
    "* {key}",
    "* **{key}**",
    "  {key}",
)
#: Формы, которые обязаны остаться НЕПРОЧИТАННЫМИ. Цитата — чужая находка;
#: заголовок раздела — проза, предмет у неё идёт следующей строкой.
NOT_A_KEY: Final = ("> {key}", ">> {key}")


@pytest.mark.parametrize("dress", DRESSED)
def test_every_key_survives_the_markup_it_is_written_in(dress: str) -> None:
    """Каждый ключ обзора читается во ВСЕХ формах, которыми его пишут (206).

    ПРАВИЛО 206 ОТПРАВЛЕНО КАТАЛОГУ ЭТИМ ПРОЕКТОМ, А ЗДЕСЬ НЕ ДЕРЖАЛОСЬ.
    «Гейт, ищущий предмет по форме записи, обязан читать ВСЕ формы, которыми
    этот предмет пишут в его дереве». Разбор находок читал одну форму из
    нескольких и терял семь строк за шестьдесят изменений — и терял молча
    ([206](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/206-a-form-the-gate-cannot-see-is-a-bypass.md),
    [016](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/016-no-silent-truncation.md)).

    ПРОВЕРЯЮТСЯ ВСЕ ТРИ КЛЮЧА РАЗОМ, а не один. Чинить их порознь значило бы
    ждать, пока та же потеря случится третий раз: у `ПРЕМИСА:` предмета в ленте
    ещё нет — верификатор не отвечал ни разу, — и потому она держится
    построением, а не замером (075).
    """
    said = dress.format(key="НАХОДКА[дефект]: заголовок находки")
    assert module.findings_of([comment(said)]) == [("дефект", "заголовок находки", "код")], said

    said = dress.format(key="ВЕРДИКТ: находок 3")
    assert module.verdict_of([comment(said)]) == 3, said

    said = dress.format(key="ПРЕМИСА: не подтвердилась — чинено раньше")
    assert module.premise_of([comment(said)]) == ("не подтвердилась", "чинено раньше"), said


@pytest.mark.parametrize("dress", NOT_A_KEY)
def test_a_quoted_key_stays_unread(dress: str) -> None:
    """Вторая половина: ЦИТАТА ключом не становится ни у одного из трёх.

    Без неё послабление читало бы пересказ чужого ответа как свой и заводило бы
    записи заново. Цена несимметрична: пропущенная своя находка теряется, а
    принятая чужая ложится записью, снять которую нечем — работы, её чинящей,
    не существует
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md),
    [140](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/140-a-gate-is-tested-by-what-it-must-reject.md)).
    """
    assert module.findings_of([comment(dress.format(key="НАХОДКА[дефект]: чужая"))]) == []
    assert module.verdict_of([comment(dress.format(key="ВЕРДИКТ: находок 3"))]) is None
    assert module.premise_of([comment(dress.format(key="ПРЕМИСА: подтверждена"))]) is None


def test_the_markup_is_stripped_per_line_not_across_the_body() -> None:
    """Обёртка — свойство СТРОКИ, и снимается она построчно.

    Пара `**…**` ищется от начала до конца ОДНОЙ строки. На теле целиком
    «конец строки» дал бы не тот хвост: жирное слово в одном абзаце и жирное в
    другом спарились бы через всё, что между ними, и ключ посередине уехал бы
    внутрь мнимой обёртки.

    Поэтому `bare_lines` режет текст на строки ПЕРЕД снятием, и здесь это
    проверяется на теле, где выделение есть и выше, и ниже ключа.
    """
    said = "**важный абзац**\n\nНАХОДКА[дефект]: предмет посередине\n\n**и ещё жирное**"
    assert module.bare_lines(said) == [
        "важный абзац",
        "",
        "НАХОДКА[дефект]: предмет посередине",
        "",
        "и ещё жирное",
    ]
    assert module.findings_of([comment(said)]) == [("дефект", "предмет посередине", "код")]
    assert module.bare_lines("") == [], "пустое тело — пустой список, а не строка из пустоты"


def test_the_title_keeps_the_signs_that_belong_to_it() -> None:
    """Знаки, принадлежащие ТЕКСТУ заголовка, не срезаются вместе с обёрткой.

    Срезание по набору знаков (`strip("*_` ")`) съедало их там, где они часть
    предмета. Это видно в реестре #23 прямо сейчас: запись лежит как
    «SERVICE_STEPS` объявлен» — с висящей кавычкой вместо парной. Сосед
    заплатил за тот же урок внешним взглядом на своём #413, и довод у него
    записан: «**kwargs игнорируется» становилось «kwargs игнорируется».

    Снимается ПАРА вокруг всей строки, а не знаки по краям, — и тогда заголовок
    не трогается вовсе.
    """
    for said in (
        "`SERVICE_STEPS` объявлен, но не вызывается",
        "**kwargs игнорируется молча",
        "аргумент называется id_",
    ):
        got = module.findings_of([comment(f"НАХОДКА[дефект]: {said}")])
        assert got == [("дефект", said, "код")], got


def test_a_finding_without_a_weight_says_so() -> None:
    """Вес не назван — так и записано, а не подставлен самый лёгкий.

    Подстановка решила бы за ревьюера в сторону, удобную разбирающему, и
    сделала бы «он не назвал» неотличимым от «он назвал лёгкое» (154).
    """
    assert module.findings_of([comment("НАХОДКА: без веса")]) == [
        (module.UNWEIGHED, "без веса", "код")
    ]


def test_a_weight_outside_the_scale_is_not_a_weight() -> None:
    """Слово вне шкалы весом не считается и к ближайшему не приводится.

    Шкала закрытая, как роды у фрагментов журнала: приведение «критично» к
    «дефекту» — догадка механизма о том, что имел в виду ревьюер (068).
    """
    assert module.findings_of([comment("НАХОДКА[критично]: чужое слово")]) == [
        (module.UNWEIGHED, "чужое слово", "код")
    ]


def test_the_heaviest_finding_is_written_first() -> None:
    """Порядок записей — по весу, а не по приходу.

    Иначе разбирающий читает двадцать записей подряд, чтобы понять, с какой
    начинать, и порядок разбора становится делом настроения (053).

    Неназванный вес стоит ПЕРВЫМ: прежде эта проверка закрепляла его в конце —
    то есть держала ровно то расхождение обещания с кодом, ради которого её и
    писали. Порядок исправлен по находке позднего взгляда на #73.
    """
    body = module.render_body(
        {
            "aaaaaaa": module.Entry(1, "замечание", "лёгкая"),
            "bbbbbbb": module.Entry(2, "дефект", "тяжёлая"),
            "ccccccc": module.Entry(3, module.UNWEIGHED, "неназванная"),
        }
    )
    order = [line for line in body.splitlines() if line.startswith("- `")]
    assert "неназванная" in order[0] and "тяжёлая" in order[1] and "лёгкая" in order[2], body


def test_last_verdict_wins() -> None:
    """Вердикт берётся последний: ревьюер обновляет свой комментарий по ходу."""
    comments = [comment("ВЕРДИКТ: находок 1"), comment("ВЕРДИКТ: находок 3")]
    assert module.verdict_of(comments) == 3


def test_absent_verdict_is_not_zero() -> None:
    """Нет строки вердикта — это не «находок нет», а отсутствие ответа (075)."""
    assert module.verdict_of([comment("просто текст")]) is None


# --- граница захода взгляда ---------------------------------------------------


def test_a_finding_of_an_earlier_look_does_not_come_back() -> None:
    """Разобранная находка прошлого захода не переезжает в новый.

    Строки находок остаются на изменении навсегда, а снятие живёт в теле
    слитого изменения и уходит из окна последних тридцати. Значит вернувшаяся
    запись не снимается уже ничем: работа сделана, а реестр говорит обратное
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).

    Замер 16.09.2026 на #333: поздний взгляд объявил «находок 2», а записал
    три — третьей уехала находка от 13.09, снятая изменением #348 14.09.
    """
    comments = [
        comment("НАХОДКА[дефект]: старое, уже починенное"),
        comment("ВЕРДИКТ: находок 1"),
        comment("НАХОДКА[риск]: новое, этого захода"),
        comment("ВЕРДИКТ: находок 1"),
    ]
    titles = [title for _, title, _ in module.findings_of(module.last_look(comments))]
    assert titles == ["новое, этого захода"], titles


def test_a_single_look_is_read_whole() -> None:
    """Вердикт один — отрезать нечего: находки лежат ДО него.

    Обратное — «брать всё после последнего вердикта» — выбросило бы находки
    единственного захода целиком, то есть превратило бы работающий канал в
    «находок нет»
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """
    comments = [
        comment("НАХОДКА[дефект]: первая"),
        comment("НАХОДКА[риск]: вторая"),
        comment("ВЕРДИКТ: находок 2"),
    ]
    look = module.last_look(comments)
    assert module.verdict_of(look) == 2
    assert len(module.findings_of(look)) == 2


def test_a_finding_written_after_the_verdict_belongs_to_that_look() -> None:
    """Находку дописывают и после числа — отрезок идёт до конца ленты.

    Границей взят вердикт ПРЕДЫДУЩЕГО захода, а не последнего: иначе находка,
    добавленная тем же заходом следом за числом, терялась бы — и терялась бы
    молча, с уже объявленным расхождением числа и списка.
    """
    comments = [
        comment("НАХОДКА[дефект]: прошлый заход"),
        comment("ВЕРДИКТ: находок 1"),
        comment("ВЕРДИКТ: находок 2"),
        comment("НАХОДКА[риск]: дописано следом"),
    ]
    titles = [title for _, title, _ in module.findings_of(module.last_look(comments))]
    assert titles == ["дописано следом"], titles


def test_the_registry_does_not_get_the_earlier_look_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Заход целиком: в реестр уезжает последний взгляд, а не вся лента.

    Проверка берёт ход механизма, а не отдельную функцию: границу захода можно
    посчитать верно и не применить, и снаружи это выглядит ровно как её
    отсутствие.
    """
    feed = [
        comment("НАХОДКА[дефект]: старое, уже починенное"),
        comment("ВЕРДИКТ: находок 1"),
        comment("НАХОДКА[риск]: новое, этого захода"),
        comment("ВЕРДИКТ: находок 1"),
    ]
    written: dict[str, Any] = {}
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "live_issue", lambda repo, token: (1, ""))
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, token: iter(feed))
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since="": ({}, since))
    monkeypatch.setattr(
        module, "save", lambda repo, token, entries, apply, swept_to=0: written.update(entries)
    )
    module.main(["--repo", "o/r", "--pr", "333"])
    titles = sorted(entry.title for entry in written.values())
    assert titles == ["новое, этого захода"], titles


def test_the_verdict_and_its_list_are_read_off_one_stretch() -> None:
    """Число и строки читаются с ОДНОГО отрезка, а не с разных (022).

    Пока число брали с последнего захода, а строки — со всей ленты, они спорили
    по устройству механизма, а не по вине ревьюера: предупреждение о расхождении
    звучало на каждом втором взгляде и переставало что-либо значить (051).
    """
    comments = [
        comment("НАХОДКА[дефект]: прошлый заход\nВЕРДИКТ: находок 1"),
        comment("НАХОДКА[риск]: этот заход\nВЕРДИКТ: находок 1"),
    ]
    look = module.last_look(comments)
    assert module.verdict_of(look) == len(module.findings_of(look)) == 1


def test_entries_survive_a_round_trip() -> None:
    """Тело живой задачи разбирается обратно в те же записи.

    Задача — единственное хранилище состояния этого механизма, и читает он его
    из собственного вывода. Значит вывод обязан разбираться обратно точно,
    иначе заметки теряются при каждом заходе.
    """
    entries = {
        "abc1234": module.Entry(18, "дефект", "первая находка"),
        "def5678": module.Entry(21, "замечание", "вторая находка"),
    }
    parsed = module.parse_entries(module.render_body(entries))
    assert parsed == entries


def test_body_carries_the_marker() -> None:
    """Скрытый маркер в теле есть всегда: по нему задача находится снова."""
    assert module.MARKER in module.render_body({})
    assert module.MARKER in module.render_body({"abc1234": module.Entry(1, "риск", "находка")})


def test_empty_body_says_so_explicitly() -> None:
    """Пустое состояние объявляется, а не выглядит как обрыв (027)."""
    assert "Пусто" in module.render_body({})


def test_resolution_line_is_recognised() -> None:
    """Строка снятия читается из тела изменения, включая отступ и регистр.

    Разбор общий с шагом открытия (`changerefs`): тот переносит строку из
    коммита в тело изменения, этот читает её оттуда. Второе чтение той же
    строки разошлось бы с первым молча — и снятие терялось бы по дороге.
    """
    found = module.changerefs.resolved_in("текст\n  Разобрано: ABC1234 — починено\nещё")
    assert found == ["abc1234"]


# --- одна живая задача, а не пять ---------------------------------------------
#
# ЗАМЕР 09.09.2026: за смену завелось ПЯТЬ живых задач-адресатов вместо одной
# (#23, #42, #49, #50, #51), и находки разъехались по ним. Ломался не поиск, а
# порядок: «найти» и «завести» — разные обращения, а группа отмены прогона
# названа по изменению, поэтому прогоны разных изменений шли параллельно.
# Владение общим ресурсом лечится группой у джоба записи; здесь проверяется
# вторая половина — что механизм, увидев копии, не выбирает молча.


def issue(number: int, body: str) -> dict[str, Any]:
    """Задача в том виде, в каком её отдаёт площадка."""
    return {"number": number, "body": body}


def test_the_earliest_live_issue_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Из нескольких копий берётся самая ранняя, а не первая в ответе площадки.

    Ранняя, а не любая: она старше, в ней больше записей и на неё уже
    ссылаются. Порядок ответа площадки решать это не должен — иначе записи
    гуляют между копиями от захода к заходу.
    """
    monkeypatch.setattr(
        module.findings.ghrest,
        "paginate",
        lambda *_, **__: iter(
            [issue(51, module.MARKER + "\nпоздняя"), issue(23, module.MARKER + "\nранняя")]
        ),
    )
    number, body = module.live_issue("o/r", "token")
    assert number == 23
    assert "ранняя" in body


def test_extra_live_issues_are_said_out_loud(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """О лишних копиях механизм говорит, а не молчит.

    Адресат, размноженный на пять, — это отсутствующий адресат (142): часть
    находок лежит там, куда никто не смотрит. Снаружи «одна задача» и «пять
    задач» выглядят одинаково, пока об этом не сказано.
    """
    monkeypatch.setattr(
        module.findings.ghrest,
        "paginate",
        lambda *_, **__: iter([issue(23, module.MARKER), issue(42, module.MARKER)]),
    )
    module.live_issue("o/r", "token")
    printed = capsys.readouterr().err
    assert "#42" in printed, "о лишней копии не сказано"
    assert "#23" in printed, "не названо, куда пойдут записи"


def test_one_live_issue_says_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Одна задача — тишина: предупреждение, звучащее всегда, не значит ничего (051)."""
    monkeypatch.setattr(
        module.findings.ghrest, "paginate", lambda *_, **__: iter([issue(23, module.MARKER)])
    )
    module.live_issue("o/r", "token")
    assert capsys.readouterr().err == ""


def test_a_change_is_not_mistaken_for_the_live_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изменение с тем же маркером в теле задачей-адресатом не считается.

    REST кладёт изменения в `/issues` наравне с задачами, а маркер попадает в
    тело изменения всякий раз, когда оно правит этот механизм.
    """
    change = {"number": 5, "body": module.MARKER, "pull_request": {"url": "…"}}
    monkeypatch.setattr(
        module.findings.ghrest,
        "paginate",
        lambda *_, **__: iter([change, issue(23, module.MARKER)]),
    )
    assert module.live_issue("o/r", "token")[0] == 23


def test_the_writing_job_owns_the_shared_issue() -> None:
    """Запись в живую задачу идёт джобом с репозиторной группой, а не по изменению.

    Группа, названная по изменению, разгораживает прогоны там, где ресурс
    общий, — и каждый в своём окне между «найти» и «завести» не видит чужой
    ещё не созданной задачи (149). Проверяется описание прогона: механизм тут
    ни при чём, лечится это владением.
    """
    document = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "review.yml").read_text(encoding="utf-8")
    )
    writing = [
        (name, job)
        for name, job in document["jobs"].items()
        if "review_findings.py" in yaml.dump(job, allow_unicode=True)
    ]
    assert writing, "джоба, пишущего находки, в прогоне не нашлось — предмет не найден (075)"
    for name, job in writing:
        group = (job.get("concurrency") or {}).get("group", "")
        assert group, f"{name}: у джоба записи нет группы — общий ресурс без владельца"
        assert "${{" not in group, (
            f"{name}: группа «{group}» названа контекстом изменения — значит она "
            "разная у разных изменений, и запись снова идёт параллельно"
        )
        assert (job.get("concurrency") or {}).get("cancel-in-progress") is False, (
            f"{name}: запись вытесняется — это дописывание в общий список, а не гонка за свежесть"
        )


def test_an_unweighed_finding_is_not_lighter_than_the_lightest() -> None:
    """Неназванный вес идёт ПЕРВЫМ, а не за самой лёгкой категорией.

    Прежде он получал место после «замечания» — то есть на практике
    трактовался как «легче самого лёгкого», ровно в ту сторону, которую модуль
    обещает не выбирать: «не подставляет самый лёгкий, а объявляется отдельно».
    Обещание и код разошлись молча.

    Первым — не потому, что тяжелее, а потому, что неизвестное требует взгляда,
    чтобы перестать быть неизвестным. Нашёл поздний взгляд по общей ветке на
    #73 — первая находка этого канала.
    """
    entries = {
        "a1": findings_module.Entry(1, "замечание", "лёгкое"),
        "b2": findings_module.Entry(2, findings_module.UNWEIGHED, "неназванное"),
        "c3": findings_module.Entry(3, "дефект", "тяжёлое"),
    }
    order = [
        line.split("·")[2].split("—")[0].strip()
        for line in module.render_body(entries).splitlines()
        if line.startswith("- `")
    ]
    assert order[0] == findings_module.UNWEIGHED, order
    assert order.index("дефект") < order.index("замечание"), order


# --- срок жизни снятия ---------------------------------------------------------


def merged(number: int, body: str, when: str = "") -> dict[str, Any]:
    """Слитое изменение в том виде, в каком его отдаёт площадка.

    ВРЕМЯ ЗДЕСЬ ОБЯЗАТЕЛЬНО, И ЭТО НЕ УКРАШЕНИЕ. Уборка ведёт отметку по
    ВРЕМЕНИ СЛИЯНИЯ, а не по номеру: номер говорит, когда изменение открыто, и
    изменение, простоявшее открытым, сливается ПОСЛЕ соседей с бо́льшими
    номерами. Подделка без времени умела бы то, чего площадка не отдаёт, и
    держала бы проверку зелёной на механизме, который времени не читает (170).
    """
    return {
        "number": number,
        "body": body,
        "merged_at": when or f"2026-09-17T{number % 24:02d}:00:00Z",
        "closed_at": when or f"2026-09-17T{number % 24:02d}:00:00Z",
    }


def closed(number: int, when: str) -> dict[str, Any]:
    """Закрытое БЕЗ слияния: время закрытия есть, времени слияния нет."""
    return {"number": number, "body": "", "merged_at": None, "closed_at": when}


def test_a_resolution_is_read_from_the_sweep_mark_not_a_fixed_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Снятие живёт до того, как его ПРОЧЛИ, а не тридцать слияний с публикации.

    Прежде окно было «последние тридцать закрытых»: снятие обязано было попасть
    под уборку раньше, чем тридцать соседей сольются следом. Отсчёт шёл от
    ПУБЛИКАЦИИ, и жило снятие тем меньше, чем быстрее движется очередь — ровно
    признак правила
    ([079](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/079-ttl-counts-from-completion.md)):
    «результат длинной операции исчезает раньше, чем результат короткой».

    ЗАМЕР 16.09.2026: находку `a98cee5` сняло #348, а к появлению записи в
    реестре #348 лежало за тридцатым закрытым — уборка на него уже не смотрела.
    """
    page = [
        merged(50, "Разобрано: aaaaaaa", "2026-09-16T12:00:00Z"),
        merged(49, "Разобрано: bbbbbbb", "2026-09-16T11:00:00Z"),
    ]
    # Читается СТРАНИЦА, а не только слитое на ней: полнота страницы
    # меряется её размером (находка #418).
    monkeypatch.setattr(module.ghrest, "merged_page", lambda repo, token, limit: (page, page))
    marks, mark = module.resolved_marks("o/r", "токен", "2026-09-16T11:00:00Z")
    assert marks == {"aaaaaaa": {50}}, "прочитано не от отметки уборки (или не названо, кем)"
    assert mark == "2026-09-16T12:00:00Z", "отметка не сдвинулась на прочитанное"


def test_the_sweep_mark_survives_a_round_trip() -> None:
    """Отметка уборки читается обратно из тела: другого хранилища у неё нет."""
    body = module.render_body({}, "2026-09-17T14:41:00Z")
    assert module.parse_swept(body) == "2026-09-17T14:41:00Z"
    assert module.parse_swept("") == "", "пустое тело — пусто, а не догадка"
    # ПРЕЖНЯЯ ФОРМА ПЕРЕВОДИТСЯ В ПУСТО, А НЕ В ВРЕМЯ ТОГО ИЗМЕНЕНИЯ: времени в
    # номере нет, и догадка здесь стоила бы ровно того пропуска, ради которого
    # форма и меняется.
    assert module.parse_swept("Убрано до: #442") == "", "старая отметка выдана за время"


def test_a_full_page_beyond_the_sweep_mark_is_said_out_loud(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Страница заполнена, а до отметки не дочитано — сказано, а не проглочено.

    Окно остаётся пределом ЗАПРОСА, а не сроком хранения. Молча передвинуть
    отметку через неувиденное значило бы объявить прочитанным то, чего заход не
    унёс (045).
    """
    page = [
        merged(number, "", f"2026-09-1{number - 96}T10:00:00Z") for number in range(100, 97, -1)
    ]
    # Читается СТРАНИЦА, а не только слитое на ней: полнота страницы
    # меряется её размером (находка #418).
    monkeypatch.setattr(module.ghrest, "merged_page", lambda repo, token, limit: (page, page))
    module.resolved_marks("o/r", "токен", "2026-09-10T10:00:00Z", limit=3)
    said = capsys.readouterr().err
    assert "::warning::" in said and "2026-09-10T10:00:00Z" in said, said


# --- верификатор: вход от ОДНОЙ находки ---------------------------------------


def test_the_premise_answer_is_read_from_a_closed_scale() -> None:
    """Ответ верификатора — слово из двух, и причина едет вместе с ним."""
    assert module.premise_of([comment("ПРЕМИСА: подтверждена")]) == ("подтверждена", "")
    assert module.premise_of([comment("ПРЕМИСА: не подтвердилась — починено изменением #348")]) == (
        "не подтвердилась",
        "починено изменением #348",
    )


def test_no_premise_line_is_not_a_confirmation() -> None:
    """Молчание верификатора — не «премиса подтверждена», а отсутствие ответа (075).

    Принять тишину за подтверждение значило бы дать находке вес, которого ей
    никто не давал: заход мог не запуститься вовсе.
    """
    assert module.premise_of([comment("просто текст")]) is None


def test_the_last_premise_answer_wins() -> None:
    """Заход повторяют, и свежий ответ отменяет прежний — как и вердикт находок."""
    said = [comment("ПРЕМИСА: подтверждена"), comment("ПРЕМИСА: не подтвердилась — уже чинено")]
    assert module.premise_of(said) == ("не подтвердилась", "уже чинено")


def test_a_refuted_premise_is_not_a_resolution() -> None:
    """Опровержение ДОПИСЫВАЕТСЯ к записи, а не снимает её.

    Находку снимает работа строкой «Разобрано»; верификатор лишь говорит, что
    чинить, возможно, нечего. Снимать по его слову значило бы отдать решение
    механизму, который премису не чинил и кода не менял (154).
    """
    entry = findings_module.Entry(333, "дефект", "resolutions_in_all теряет метку")
    after = module.verified(entry, "не подтвердилась", "починено изменением #348", "16.09.2026")
    assert after.title == entry.title and after.pr == entry.pr and after.weight == entry.weight
    assert after.checked.startswith(findings_module.REFUTED)
    assert "#348" in after.checked, "причина опровержения не доехала до записи"


def test_the_verifier_word_is_matched_whole_not_by_prefix() -> None:
    """Слово верификатора сверяется целиком, а не по началу.

    Прежде здесь стояло `said.startswith("не")`. Пока шкалу держит образец
    `PREMISE_RE`, это безопасно, — но связь невидима у самого сравнения, а
    функция открыта и принимает любую строку: «нейтрально», «независимо»,
    «нельзя» прочлись бы как ОПРОВЕРЖЕНИЕ премисы, то есть находка была бы
    объявлена ложной по первым двум буквам чужого слова
    ([141](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/141-a-marker-is-matched-whole-not-by-prefix.md)).
    """
    было = module.Entry(1, "дефект", "что-то")
    опровергнуто = module.verified(было, module.SAYS_NO, "починено раньше", "18.09.2026")
    assert опровергнуто.checked.startswith(findings_module.REFUTED), опровергнуто.checked
    подтверждено = module.verified(было, module.SAYS_YES, "", "18.09.2026")
    assert подтверждено.checked.startswith(findings_module.CONFIRMED), подтверждено.checked
    for чужое in ("нейтрально", "независимо", "нельзя", "не знаю"):
        ответ = module.verified(было, чужое, "", "18.09.2026")
        assert ответ.checked.startswith(findings_module.CONFIRMED), (
            f"«{чужое}» прочитано как опровержение премисы по приставке: {ответ.checked}"
        )


def test_the_verifier_answer_survives_a_round_trip() -> None:
    """Хвост проверки разбирается обратно вместе с записью.

    Тело задачи — единственное хранилище этого механизма: не прочитанный
    обратно хвост означал бы, что проверку придётся делать заново каждый заход.
    """
    entries = {
        "abc1234": findings_module.Entry(
            18, "дефект", "первая", f"{findings_module.REFUTED} 16.09.2026: уже чинено"
        ),
        "def5678": findings_module.Entry(21, "замечание", "вторая"),
    }
    assert module.parse_entries(module.render_body(entries)) == entries


def test_the_verifier_answer_survives_a_retelling() -> None:
    """Пересказ находки на новом заходе не стирает ответ верификатора.

    Отпечаток сохраняется намеренно, и вместе с ним обязана сохраниться уже
    сделанная проверка: она о ПРЕМИСЕ, а не о формулировке (022).
    """
    kept = f"{findings_module.REFUTED} 16.09.2026: уже чинено"
    entries = {
        "abc1234": findings_module.Entry(333, "дефект", "старый заголовок", kept, role="архитектор")
    }
    monkey = pytest.MonkeyPatch()
    monkey.setenv("GH_TOKEN", "токен")
    monkey.setattr(module, "live_issue", lambda repo, token: (1, ""))
    monkey.setattr(module, "parse_entries", lambda body: dict(entries))
    monkey.setattr(module.ghrest, "paginate", lambda path, token: iter([]))
    monkey.setattr(module, "verdict_of", lambda look: 1)
    monkey.setattr(
        module, "findings_of", lambda look: [("дефект", "тот же дефект другими словами", "код")]
    )
    monkey.setattr(module, "pair_up", lambda *_, **__: ["abc1234"])
    monkey.setattr(module, "resolved_marks", lambda repo, token, since="": ({}, since))
    written: dict[str, Any] = {}
    monkey.setattr(
        module, "save", lambda repo, token, entries, apply, swept_to=0: written.update(entries)
    )
    module.main(["--repo", "o/r", "--pr", "333"])
    monkey.undo()
    assert written["abc1234"].checked == kept, "ответ верификатора стёрт пересказом находки"
    assert written["abc1234"].role == "архитектор", "роль стёрта пересказом без роли (#763)"


def test_the_subject_of_a_check_comes_from_the_registry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Предмет верификатора читается из реестра, а не передаётся кнопкой второй раз.

    Номер изменения у находки уже записан. Второй его источник разошёлся бы с
    первым молча, а проверить премису не на том изменении хуже, чем не
    проверять вовсе (022, 049).
    """
    kept = {"abc1234": findings_module.Entry(333, "дефект", "resolutions_in_all теряет метку")}
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "live_issue", lambda repo, token: (1, ""))
    monkeypatch.setattr(module, "parse_entries", lambda body: dict(kept))
    module.main(["--repo", "o/r", "--tell", "abc1234"])
    said = capsys.readouterr().out
    assert "pr=333" in said and "дефект" in said and "resolutions_in_all" in said, said


def test_an_unknown_mark_is_not_an_empty_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отпечатка нет в реестре — это отказ, а не «проверять нечего» (039, 075).

    Молча отдать пустой предмет значило бы отправить верификатора смотреть в
    никуда, и его ответ выглядел бы добросовестным.
    """
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "live_issue", lambda repo, token: (1, ""))
    monkeypatch.setattr(module, "parse_entries", lambda body: {})
    assert module.main(["--repo", "o/r", "--tell", "0000000"]) == module.EXIT_BROKEN


# --- объявленные исходы захода -----------------------------------------------


def test_an_empty_registry_is_its_own_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Реестр пуст — свой исход, а не «есть неразобранное» и не «не смог».

    «Разобрано всё» и «разбирать нечего, потому что не прочитали» снаружи
    одинаковы, и различает их только отдельный исход
    ([039](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/039-three-outcomes-not-two.md)).
    """
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "live_issue", lambda repo, token: (1, ""))
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since="": ({}, since))
    monkeypatch.setattr(module, "save", lambda *a, **k: None)
    assert module.main(["--sweep", "--repo", "o/r"]) == module.EXIT_NOTHING


def test_a_registry_with_entries_stays_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    """Неразобранное осталось — исход «ждёт», и он не тот же, что пустой реестр."""
    kept = {"abc1234": findings_module.Entry(131, "дефект", "очередь читает не то")}
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "live_issue", lambda repo, token: (1, ""))
    monkeypatch.setattr(module, "parse_entries", lambda body: dict(kept))
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since="": ({}, since))
    monkeypatch.setattr(module, "save", lambda *a, **k: None)
    assert module.main(["--sweep", "--repo", "o/r"]) == module.EXIT_PENDING


def test_a_verdict_that_disagrees_with_its_list_is_announced(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Вердикт спорит со списком находок — это сказано наружу, а не в лог.

    Вердикт и строки находок пишет ОДИН ответ: если они спорят, доверять
    нечему ни тому, ни другому. Машинная половина правила 136 держится именно
    здесь — «вердикт после перечисления всех предметов» проверяется тем, что
    число и перечисление сошлись
    ([182](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/182-an-unmechanisable-answer-is-split-in-two.md)).
    Аннотация выбрана намеренно: её отдаёт REST, а лог прогона читается не из
    всякого окна.
    """
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "live_issue", lambda repo, token: (1, ""))
    monkeypatch.setattr(module, "parse_entries", lambda body: {})
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, token: iter([]))
    monkeypatch.setattr(module, "verdict_of", lambda comments: 3)
    monkeypatch.setattr(
        module, "findings_of", lambda comments: [("дефект", "очередь читает не то", "код")]
    )
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since="": ({}, since))
    monkeypatch.setattr(module, "save", lambda *a, **k: None)
    module.main(["--repo", "o/r", "--pr", "131"])
    said = capsys.readouterr().err
    assert "::warning::" in said, "расхождение осталось в логе — наружу его не видно"
    assert "находок 3" in said and "строк находок 1" in said, "числа не названы"


def test_a_full_page_of_closed_warns_even_when_few_were_merged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Полнота страницы меряется СТРАНИЦЕЙ, а не слитыми на ней.

    Запрос идёт за ЗАКРЫТЫМИ, и слитые — их подмножество. Счёт по слитым молчал
    бы ровно тогда, когда закрытых без слияния много, — то есть в том самом
    случае, ради которого предупреждение и заведено: за полной страницей
    остаётся неувиденное. Нашёл внешний взгляд на #418.

    ЗДЕСЬ СЛИТОЕ ОДНО, А СТРАНИЦА ПОЛНА: прежний счёт (`len(merged) >= limit`)
    дал бы 1 >= 3 и промолчал.
    """
    page = [merged(300, "", "2026-09-17T10:00:00Z")]
    monkeypatch.setattr(
        module.ghrest, "merged_page", lambda repo, token, limit: (page, page * limit)
    )
    module.resolved_marks("o/r", "t", since="2026-09-01T00:00:00Z", limit=3)
    assert "страница закрытых заполнена" in capsys.readouterr().err


def test_a_page_with_room_left_says_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Страница не полна — предупреждения нет: крик о законном учит не слушать (051)."""
    page = [merged(300, "", "2026-09-17T10:00:00Z")]
    monkeypatch.setattr(module.ghrest, "merged_page", lambda repo, token, limit: (page, page))
    module.resolved_marks("o/r", "t", since="2026-09-01T00:00:00Z", limit=3)
    assert "страница закрытых заполнена" not in capsys.readouterr().err


def test_the_page_comes_back_whole_not_just_its_filtered_part() -> None:
    """Транспорт отдаёт САМУ СТРАНИЦУ, а не только отфильтрованное на ней.

    Форма держит смысл: зовущему нужны обе величины — слитое и страница
    целиком, — и вывести вторую из первой нельзя, фильтр их разводит. Полнота
    страницы меряется страницей, а её край — временем закрытия, которое есть у
    каждого закрытого и которого у отфильтрованного может не быть вовсе.

    ДОКСТРОКА ГОВОРИЛА «размер страницы отдельным ЧИСЛОМ» — контракт, которого
    у транспорта уже нет: он отдаёт страницу, а не её длину. Проверка при этом
    сверяла `tuple` и проходила, то есть текст разошёлся с предметом молча
    (нашёл внешний взгляд на #434).
    """
    import inspect

    said = str(inspect.signature(module.ghrest.merged_page).return_annotation)
    assert "tuple" in said, "страница обязана возвращаться вторым значением"
    assert said.count("list") == 2, f"вторым значением возвращается не страница целиком: {said}"


def test_a_full_page_with_nothing_merged_still_warns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ПРЕДЕЛЬНЫЙ СЛУЧАЙ СОБСТВЕННОГО ОПИСАНИЯ: полная страница, ноль слитых.

    Предупреждение обещает сказать, когда за страницей осталось неувиденное.
    Считало оно самый старый номер по СЛИТЫМ, и при нуле слитых `default=0`
    делал условие ложным ВСЕГДА — механизм молчал ровно в том случае, ради
    которого заведён, и молчал тем вернее, чем хуже дело: чем больше закрытых
    без слияния, тем дальше за страницу уехали снятия.

    Нашёл внешний взгляд на #431 и назвал ТРИЖДЫ подряд — первая починка
    закрыла только половину предиката.
    """
    page = [closed(n, f"2026-09-1{n - 198}T10:00:00Z") for n in range(200, 203)]
    monkeypatch.setattr(module.ghrest, "merged_page", lambda repo, token, limit: ([], page))
    marks, mark = module.resolved_marks("o/r", "t", since="2026-09-01T00:00:00Z", limit=3)
    said = capsys.readouterr().err
    assert "страница закрытых заполнена" in said, "механизм молчит в своём предельном случае"
    assert "2026-09-12T10:00:00Z" in said, "край страницы взят не со страницы, а со слитых"
    assert marks == {}, "прочитано то, чего на странице нет"
    assert mark == "2026-09-01T00:00:00Z", "отметка двинулась по непрочитанному"


def test_the_page_edge_comes_from_the_page_not_the_merged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Самый старый номер — со страницы: слитое на ней может быть свежее всех."""
    page = [
        merged(300, "", "2026-09-17T10:00:00Z"),
        closed(201, "2026-09-13T10:00:00Z"),
        closed(200, "2026-09-12T10:00:00Z"),
    ]
    monkeypatch.setattr(module.ghrest, "merged_page", lambda repo, token, limit: ([page[0]], page))
    module.resolved_marks("o/r", "t", since="2026-09-01T00:00:00Z", limit=3)
    said = capsys.readouterr().err
    assert "2026-09-12T10:00:00Z" in said, f"назван не тот край страницы: {said}"
    assert "2026-09-17T10:00:00Z" not in said, f"край взят со слитого, а не со страницы: {said}"


def test_a_change_merged_late_with_a_lower_number_is_still_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отметка идёт по ВРЕМЕНИ СЛИЯНИЯ, а не по номеру изменения.

    Номер говорит, когда изменение ОТКРЫТО. Изменение, простоявшее открытым,
    пока соседи с бо́льшими номерами уехали в общую ветку, оказывалось НИЖЕ
    курсора в тот самый заход, который его впервые увидел, — и его снятия не
    читались уже никогда.

    ЗАМЕР 17.09.2026 ПО ВСЕЙ ИСТОРИИ: из 386 слитых изменений 36 слились не в
    порядке номера, и в них 76 отметок снятия, которых уборка не прочла ни разу.
    Последний случай — #438: слит в 14:41, курсор к тому времени стоял на #442,
    пять отметок остались в реестре неразобранными при сделанной работе.
    """
    page = [
        merged(442, "Разобрано: ccccccc", "2026-09-17T14:52:00Z"),
        merged(438, "Разобрано: aaaaaaa", "2026-09-17T14:41:00Z"),
        merged(440, "Разобрано: bbbbbbb", "2026-09-17T13:51:00Z"),
    ]
    monkeypatch.setattr(module.ghrest, "merged_page", lambda repo, token, limit: (page, page))
    marks, mark = module.resolved_marks("o/r", "токен", "2026-09-17T13:51:00Z")
    assert set(marks) == {"aaaaaaa", "ccccccc"}, (
        "снятие изменения с МЕНЬШИМ номером, слитого позже, не прочитано — "
        "отметка идёт по номеру, а не по времени слияния"
    )
    assert mark == "2026-09-17T14:52:00Z"


def test_a_merge_without_a_time_does_not_move_the_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """«Не знаю когда» значит «не прочитано», а не «прочитано сейчас».

    Одна запись без времени иначе перепрыгнула бы курсор через всё, что ниже
    неё, — то есть сделала бы ровно то, что чинится (045, 068).
    """
    page = [
        {"number": 500, "body": "Разобрано: ddddddd", "merged_at": None, "closed_at": "2026-09-18"},
        merged(499, "Разобрано: eeeeeee", "2026-09-17T15:00:00Z"),
    ]
    monkeypatch.setattr(module.ghrest, "merged_page", lambda repo, token, limit: (page, page))
    marks, mark = module.resolved_marks("o/r", "токен", "2026-09-17T14:00:00Z")
    assert set(marks) == {"eeeeeee"}, "прочитано слитое без времени"
    assert mark == "2026-09-17T15:00:00Z", "отметка сдвинулась по записи без времени"


@pytest.mark.parametrize(
    "cursor", ["", "2026-09-17T14:41:00Z", "2026-01-01T00:00:00Z"], ids=lambda c: c or "пусто"
)
def test_the_sweep_mark_reads_back_exactly_what_was_written(cursor: str) -> None:
    """Что записано в тело, то и прочитано обратно — включая ПУСТО.

    Тело задачи — единственное хранилище отметки, и круговорот здесь предмет, а
    не аккуратность. Первая редакция писала при пустом курсоре заполнитель «—» и
    читала его ЗНАЧЕНИЕМ: тире (U+2014) больше любой даты ISO, то есть записанный
    однажды курсор пропускал бы ВСЁ и навсегда — уборка перестала бы читать
    снятия вообще, оставаясь зелёной. Нашёл внешний взгляд на #444.
    """
    assert module.parse_swept(module.render_body({}, cursor)) == cursor


def test_the_never_swept_placeholder_sorts_above_every_date() -> None:
    """ПОЧЕМУ ЭТО БЫЛО ОПАСНО, А НЕ НЕОПРЯТНО — замером, а не на слово.

    Сравнение курсора со временем слияния лексикографическое, и заполнитель,
    прочитанный значением, оказывается выше всякой даты. Проверка держит сам
    довод: пропади перевод в пусто — запись ниже заполнителя не прочтётся.
    """
    assert module.NEVER_SWEPT >= "2026-09-17T15:26:04Z", (
        "заполнитель перестал быть выше дат — довод проверки устарел"
    )
    assert module.parse_swept(f"Убрано до: {module.NEVER_SWEPT}") == "", (
        "заполнитель прочитан значением курсора — уборка пропустит всё"
    )


def test_a_line_saying_there_are_none_is_not_a_finding() -> None:
    """«НАХОДКА: нет» — ответ «предмета нет», а не находка с таким заголовком.

    Формат требует строки `НАХОДКА:`, и при пустом заходе ревьюер пишет в неё
    отрицание. ЗАМЕР: на #414 взгляд написал «ВЕРДИКТ: находок 0» и рядом
    «НАХОДКА: нет»; разбор завёл запись с заголовком «нет», и она пролежала в
    реестре сутки, пережив пять заходов уборки — снять её нечем, работы, которая
    бы её починила, не существует.
    """
    said = [comment("НАХОДКА: нет\n\nВЕРДИКТ: находок 0")]
    assert module.findings_of(said) == [], "отрицание записано находкой"


#: Слова отрицания, названные ЗДЕСЬ, а не взятые у механизма. Второй источник
#: нужен: перебор самого словаря доказывает лишь, что перечисленное в нём
#: отвергается, и молчит, если список УРЕЗАЛИ. Поймано откатом — урезание до
#: одного слова проверку не покрасило (014).
ABSENCE_EXPECTED: Final = frozenset({"нет", "нет находок", "находок нет", "none", "no findings"})


def test_the_absence_vocabulary_is_what_it_was_declared_to_be() -> None:
    """Словарь отрицаний сверяется с независимым перечнем, а не сам с собой."""
    assert module.ABSENCE == ABSENCE_EXPECTED, (
        "словарь отрицаний разошёлся с объявленным: слово ушло или пришло молча"
    )


@pytest.mark.parametrize("said", sorted(ABSENCE_EXPECTED))
def test_every_word_of_the_absence_vocabulary_is_refused(said: str) -> None:
    """Прогнан КАЖДЫЙ вариант словаря, а не один из пяти.

    Проверка одного слова из закрытого списка говорит о списке ровно столько же,
    сколько о нём говорит его длина: четыре остальных могли бы быть написаны с
    опечаткой, и набор был бы зелен (нашёл внешний взгляд на #453).
    """
    assert module.findings_of([comment(f"НАХОДКА: {said}")]) == [], f"«{said}» записано находкой"
    assert module.findings_of([comment(f"НАХОДКА: {said.upper()}")]) == [], "регистр решает"


@pytest.mark.parametrize("знак", list(module.ENDINGS))
def test_an_ending_sign_does_not_revive_the_phantom(знак: str) -> None:
    """Знак конца не возвращает призрака: «нет!» и «нет?» — то же отрицание.

    `rstrip(".")` снимал точку и пропускал остальные — призрак заводился снова,
    просто с восклицательным знаком в заголовке.
    """
    assert module.findings_of([comment(f"НАХОДКА: нет{знак}")]) == [], f"«нет{знак}» прошло"


def test_a_title_that_merely_starts_with_no_is_still_a_finding() -> None:
    """Вторая половина: «нет проверки на …» — законный заголовок, и он проходит.

    Отвергать всё, что начинается с «нет», значило бы запретить целый класс
    формулировок, и такой запрет обходится перестановкой слов (051).
    """
    said = [comment("НАХОДКА[дефект]: нет проверки на пустой ввод\n\nВЕРДИКТ: находок 1")]
    assert module.findings_of(said) == [("дефект", "нет проверки на пустой ввод", "код")]


def test_the_reviewer_can_mark_a_finding_as_being_about_the_answer() -> None:
    """Род предмета читается из той же скобки, что и вес, и не портит его.

    Прежний разбор брал скобку ЦЕЛИКОМ и искал её в шкале весов: `[дефект ·
    ответ]` не нашлось бы там, и новая пометка обнулила бы старую (090).
    """
    сказано = "НАХОДКА[дефект · ответ]: правило объявлено неприменимым, а предмет есть"
    said = [comment(сказано)]
    вес, _, род = module.findings_of(said)[0]
    assert вес == "дефект", "род съел вес"
    assert род == findings_module.ANSWER_KIND
    # порядок слов в скобке не решает: ревьюер пишет как видит
    обратно = [comment("НАХОДКА[ответ, дефект]: то же самое другими словами")]
    assert module.findings_of(обратно)[0][0] == "дефект"
    assert module.findings_of(обратно)[0][2] == findings_module.ANSWER_KIND


def test_a_finding_naming_the_answer_file_is_about_the_answer_unmarked() -> None:
    """МЕХАНИЧЕСКИЙ ПОЛ: назвал файл ответа — значит об ответе, помечено или нет.

    Пометка ревьюера шире (находка об ответе может файла не называть), признак
    по адресу уже — зато не забывается. Это требование и его нижняя граница, а
    не два ответа на один вопрос (051).
    """
    said = [comment("НАХОДКА[риск]: .rules/bindings.json:120 утверждает то, чего в дереве нет")]
    assert module.findings_of(said)[0][2] == findings_module.ANSWER_KIND


def test_a_plain_finding_stays_about_the_code() -> None:
    """Второй конец: обычная находка родом не меняется.

    Без него «об ответе» стало бы значить «любая находка», и раздел, куда их
    выносят первыми, перестал бы что-либо выделять (051).
    """
    said = [comment("НАХОДКА[дефект]: scripts/arm.py роняет заход на пустом ответе")]
    assert module.findings_of(said)[0][2] == findings_module.CODE


def test_the_registry_puts_answer_findings_first_and_names_the_section() -> None:
    """Реестр разводит находки по разделам, и об ответе идут первыми.

    Карта, которую проект выдаёт взгляду, говорит, что такая находка «дороже
    любой другой». Пока род не записывался, механизм объявлял их ценнее и терял
    различие при записи — отдачу канала по ответам посчитать было нечем.
    """
    entries = {
        "aaaaaaa": findings_module.Entry(10, "дефект", "о коде, и тяжёлая"),
        "bbbbbbb": findings_module.Entry(
            11, "замечание", "об ответе, и лёгкая", kind=findings_module.ANSWER_KIND
        ),
    }
    body = module.render_body(entries)
    место_ответа = body.index("bbbbbbb")
    место_кода = body.index("aaaaaaa")
    assert место_ответа < место_кода, "лёгкая находка об ОТВЕТЕ ушла за тяжёлую о коде"
    assert "### Об ОТВЕТЕ каталогу" in body and "### О коде" in body
    assert module.parse_entries(body) == entries, "род не пережил круговорот"


def test_without_answer_findings_the_registry_has_no_empty_section() -> None:
    """Раздела «об ответе» нет, когда таких находок нет: пустой заголовок — шум."""
    entries = {"aaaaaaa": findings_module.Entry(10, "дефект", "о коде")}
    body = module.render_body(entries)
    assert "### Об ОТВЕТЕ каталогу" not in body
    assert module.parse_entries(body) == entries


def test_marks_in_splits_the_bracket_by_either_separator() -> None:
    """Скобка режется точкой-разделителем И запятой — ревьюер пишет как видит.

    Требовать одного знака значило бы ронять запись из-за оформления: слово
    названо верно, а механизм его не увидел (051).
    """
    assert module.marks_in("дефект · ответ") == ["дефект", "ответ"]
    assert module.marks_in("ответ, дефект") == ["ответ", "дефект"]
    assert module.marks_in("**Дефект**") == ["дефект"], "оформление не должно мешать"
    assert module.marks_in("замечание") == ["замечание"]


def test_kind_of_reads_the_mark_and_falls_back_to_the_address() -> None:
    """Разбор рода прогнан ПРЯМО, а не только через вердикт.

    Сойдись вердикт по другой причине — род назывался бы неверно, и находка
    легла бы не в тот раздел.
    """
    ответ = findings_module.ANSWER_KIND
    assert findings_module.kind_of("что угодно", "ответ") == ответ, "пометка не прочитана"
    assert findings_module.kind_of("что угодно", "об ответе") == ответ, "форма записи не прочитана"
    assert findings_module.kind_of(f"{findings_module.ANSWER_FILE}:12 врёт") == ответ, (
        "механический пол не сработал"
    )
    assert findings_module.kind_of("обычная находка о коде") == findings_module.CODE


def отметка(pr: int, kind: str) -> dict[str, Any]:
    """Реестр из одной записи заданного рода — общий вход для проверок снятия."""
    return {"abc1234": findings_module.Entry(pr, "дефект", "находка", kind=kind)}


def test_an_answer_finding_is_not_closed_without_touching_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Снятие находки ОБ ОТВЕТЕ не принимается, если ответ не правили.

    У находки о коде предмет размыт — починить её можно где угодно в дереве, — а
    у находки об ответе он ровно один файл. Изменение, объявившее её разобранной
    и не тронувшее этот файл, говорит о работе, которой не делало.
    """
    entries = отметка(10, findings_module.ANSWER_KIND)
    monkeypatch.setattr(module, "touched", lambda repo, token, number: {"scripts/arm.py"})
    берём, держим = module.closable("o/r", "t", entries, {"abc1234": {20}})
    assert берём == set(), "снятие принято при нетронутом ответе"
    assert "abc1234" in держим and module.ANSWER_FILE in держим["abc1234"]


def test_an_answer_finding_is_closed_when_the_answer_was_edited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Вторая половина: ответ правили — снятие принимается.

    Без неё проверка была бы неотличима от «находки об ответе не снимаются
    никогда» (051).
    """
    entries = отметка(10, findings_module.ANSWER_KIND)
    monkeypatch.setattr(
        module, "touched", lambda repo, token, number: {module.ANSWER_FILE, "scripts/arm.py"}
    )
    берём, держим = module.closable("o/r", "t", entries, {"abc1234": {20}})
    assert берём == {"abc1234"} and not держим


def test_the_answer_is_asked_of_the_closer_not_of_the_finder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Файлы спрашиваются у СНЯВШЕГО изменения, а не у того, где нашли (#834).

    Находку об ответе нашли на #10, где ответ не правили; сняло её #20, которое
    ответ правило. Прежде проверялось #10, и такую находку не снимало ничто.
    """
    entries = отметка(10, findings_module.ANSWER_KIND)
    files = {10: {"scripts/arm.py"}, 20: {module.ANSWER_FILE}}
    monkeypatch.setattr(module, "touched", lambda repo, token, number: files[number])
    берём, держим = module.closable("o/r", "t", entries, {"abc1234": {20}})
    assert берём == {"abc1234"} and not держим
    берём, держим = module.closable("o/r", "t", entries, {"abc1234": {10}})
    assert not берём and f"#10 {module.UNTOUCHED_ONE}" in держим["abc1234"]


def test_one_closer_that_edited_the_answer_is_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    """Из нескольких снявших хватает одного, правившего ответ; ни одного — отказ (#838)."""
    entries = отметка(10, findings_module.ANSWER_KIND)
    files = {20: {"scripts/arm.py"}, 30: {module.ANSWER_FILE}, 40: {"docs/x.md"}}
    monkeypatch.setattr(module, "touched", lambda repo, token, number: files[number])
    берём, _ = module.closable("o/r", "t", entries, {"abc1234": {20, 30}})
    assert берём == {"abc1234"}
    берём, держим = module.closable("o/r", "t", entries, {"abc1234": {20, 40}})
    assert not берём and f"#20, #40 {module.UNTOUCHED_MANY}" in держим["abc1234"]


def test_a_merged_change_without_a_number_is_unread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Слитое без номера не читается вовсе — как слитое без времени (#838, #843, 210)."""
    page = [
        {
            "merged_at": "2026-09-25T12:00:00Z",
            "closed_at": "2026-09-25T12:00:00Z",
            "body": "Разобрано: abc1234",
        },
        {
            "number": 7,
            "merged_at": "2026-09-25T12:30:00Z",
            "closed_at": "2026-09-25T12:30:00Z",
            "body": "Разобрано: def5678",
        },
    ]
    monkeypatch.setattr(module.ghrest, "merged_page", lambda repo, token, limit: (page, page))
    marks, _ = module.resolved_marks("o/r", "t", "2026-09-25T11:00:00Z")
    assert marks == {"def5678": {7}}


def test_a_code_finding_is_closed_without_asking_the_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """У находки о КОДЕ файлы не спрашиваются вовсе: предмет размыт, и цена зря.

    Проверяется именно НЕВЫЗОВ: лишний запрос к площадке на каждое снятие —
    плата, которой требование не оправдывает.
    """
    entries = отметка(10, findings_module.CODE)

    def нельзя(repo: str, token: str, number: int) -> set[str]:
        raise AssertionError("файлы спрошены у находки о коде")

    monkeypatch.setattr(module, "touched", нельзя)
    берём, держим = module.closable("o/r", "t", entries, {"abc1234": {20}})
    assert берём == {"abc1234"} and not держим


def test_a_silent_platform_lets_the_resolution_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ТРЕТИЙ ИСХОД ИДЁТ В СТОРОНУ СНЯТИЯ, и это выбор с названной ценой.

    Площадка не ответила о файлах — мы не знаем, правили ответ или нет. Держать
    запись по НЕЗНАНИЮ значило бы наказывать за отказ сети того, кто работу
    сделал: отметка уже стоит в теле слитого, то есть утверждение сделано
    человеком (039, 084).
    """
    entries = отметка(10, findings_module.ANSWER_KIND)
    monkeypatch.setattr(module, "touched", lambda repo, token, number: set())
    берём, держим = module.closable("o/r", "t", entries, {"abc1234": {20}})
    assert берём == {"abc1234"} and not держим


def test_a_refusing_platform_is_caught_by_the_reader_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Перехват отказа проверен НА САМОМ ОТКАЗЕ, а не через подделку читателя.

    Прежде наружное поведение проверялось моком `touched`, то есть перехват
    `TransportError` не исполнялся ни разу: проверка зеленела бы и при снятом
    `try`. Нашёл внешний взгляд на #458.
    """

    def отказ(repo: str, number: int, token: str) -> frozenset[str]:
        raise findings_module.ghrest.TransportError("площадка молчит")

    monkeypatch.setattr(module.ghrest, "files_of", отказ)
    assert module.touched("o/r", "токен", 7) == set(), "отказ площадки не перехвачен"


def test_the_reader_passes_a_real_answer_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """Второй конец: площадка ответила — состав доезжает как есть.

    Без него перехват был бы неотличим от «всегда пусто» (051).
    """
    monkeypatch.setattr(
        module.ghrest, "files_of", lambda repo, number, token: frozenset({"scripts/x.py"})
    )
    assert module.touched("o/r", "токен", 7) == {"scripts/x.py"}


#: Две РАЗНЫЕ находки по одному адресу — ровно те, что слиплись на #635.
TWO_AT_ONE_PLACE: Final = (
    "scripts/runs_series.py:194 — множество `ours` строится по имени шага без привязки "
    "к файлу/джобу; одноимённый шаг «ставит И делает» унаследует чужую классификацию.",
    "scripts/runs_series.py:194 — подстрочный поиск `pip install` в строке классифицирует "
    "её как installer-only, даже если та же строка через `&&` ещё и выполняет работу.",
)


def harvest(entries: dict[str, Any], pr: int, titles: tuple[str, ...]) -> dict[str, Any]:
    """Жатва одного захода тем же приёмом, что в `main`: пары решаются целиком."""
    for title, mark in zip(titles, module.pair_up(entries, pr, list(titles)), strict=True):
        if mark is None:
            entries[module.fingerprint(title)] = module.findings.Entry(pr, "риск", title)
    return entries


def test_two_findings_of_one_look_at_one_place_stay_two() -> None:
    """Две находки одного ответа по одному адресу дают ДВЕ записи.

    Совпавший адрес считался точным признаком «та же находка». Для пересказа он
    точный, для соседства — нет: у одной строки бывает две разные беды, а
    ревьюер не называет одну находку дважды в одном ответе.

    Замер 23.09.2026 по ста изменениям: внутри одного ответа слиплось две
    находки — на #635 и #657, обе в тот же день, и реестр терял их молча
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    said = harvest({}, 635, TWO_AT_ONE_PLACE)
    assert len(said) == 2, f"две находки по одному адресу слиплись: {list(said)}"


def test_a_later_look_retells_by_words_and_a_new_word_is_a_new_record() -> None:
    """Пересказ близкими словами садится на прежнюю запись, другими словами — новая запись.

    Первая половина: без неё починка неотличима от «никогда не склеивать», и
    каждый новый заход размножал бы записи о той же беде (замер 10.09.2026:
    четыре записи об одной беде на #149)
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).

    Вторая половина — находка внешнего взгляда на #669 (`7b62e1a`): совпавший
    адрес решал сам, при любых словах, и новая беда по месту прежней ложилась
    на её запись — а снятие прежней уносило обе. Теперь другие слова по тому же
    адресу — вторая запись: цена — дубль, а не потеря.
    """
    entries = harvest({}, 635, TWO_AT_ONE_PLACE)
    close = (TWO_AT_ONE_PLACE[1].replace("классифицирует", "относит"),)
    harvest(entries, 635, close)
    assert len(entries) == 2, f"близкий пересказ завёл лишнюю запись: {list(entries)}"
    other = (
        "scripts/runs_series.py:194 — поиск подстроки `pip install` объявляет служебной "
        "строку, которая через `&&` дальше делает работу.",
    )
    harvest(entries, 635, other)
    assert len(entries) == 3, f"другие слова по адресу легли на чужую запись: {list(entries)}"


#: Две записи, различимые одним словом, — и строка, близкая к обеим (#662).
NEIGHBOUR_A: Final = (
    "scripts/r.py:194 — множество ours строится по имени шага без привязки к файлу и джобу"
)
NEIGHBOUR_B: Final = NEIGHBOUR_A.replace("джобу", "матрице")


def test_a_retelling_lands_on_the_closest_of_its_neighbours() -> None:
    """Если близких записей несколько, пересказ садится на ближайшую по словам.

    Иначе пересказ второй находки на позднем заходе садился бы на ПЕРВУЮ
    попавшуюся — и та, о которой говорили, висела бы неразобранной навсегда
    ([195](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/195-a-narrowed-predicate-names-its-neighbour.md)).
    Сходство строки — 0.93 к одной записи и 0.86 к другой: обе выше порога.
    """
    entries = {
        module.fingerprint(t): module.findings.Entry(635, "риск", t)
        for t in (NEIGHBOUR_A, NEIGHBOUR_B)
    }
    retold = NEIGHBOUR_B.replace("файлу", "пути")
    mark = module.existing_mark(entries, 635, retold)
    assert mark == module.fingerprint(NEIGHBOUR_B), "пересказ сел на чужую запись"


#: Прежняя запись, её пересказ одним словом и строка, отличная двумя, — обе
#: выше порога, и обе претендуют на запись: 0.93 и 0.86.
OLD_AT_TEN: Final = (
    "scripts/x.py:10 — разбор роняет пустую строку и молча теряет последнюю запись "
    "реестра при переносе"
)
RETOLD_AT_TEN: Final = OLD_AT_TEN.replace("переносе", "переносах")
NEW_AT_TEN: Final = OLD_AT_TEN.replace("последнюю", "первую").replace("реестра", "журнала")


def test_the_order_of_lines_does_not_decide_who_retells() -> None:
    """Пересказ находится, где бы в ответе ни стояла соседняя новая находка.

    Проверено прогоном до починки: новая находка, стоящая РАНЬШЕ
    пересказа старой, забирала старую запись себе — запись хранит прежний
    заголовок, и новая находка пропадала молча, а пересказ заводил дубль. Счёт
    записей при этом сходился, расходилось содержимое
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    """
    old = module.fingerprint(OLD_AT_TEN)
    for order in ((NEW_AT_TEN, RETOLD_AT_TEN), (RETOLD_AT_TEN, NEW_AT_TEN)):
        entries = {old: module.findings.Entry(1, "риск", OLD_AT_TEN)}
        said = dict(zip(order, module.pair_up(entries, 1, list(order)), strict=True))
        assert said[RETOLD_AT_TEN] == old, f"пересказ не нашёл свою запись при порядке {order}"
        assert said[NEW_AT_TEN] is None, f"новая находка села на чужую запись при порядке {order}"


def test_two_retellings_pair_up_as_a_whole() -> None:
    """Два пересказа двух близких записей разбираются вместе, а не жадно по очереди.

    Случай внешнего взгляда на #662: ранний пересказ отбирал запись, которая
    ближе позднему, и тому доставалась дальняя. Здесь ранняя строка ближе к
    первой записи (0.93 против 0.86), а поздняя совпадает с первой дословно:
    жадный разбор отдал бы первую запись ранней строке. Сильнейшие пары
    занимаются первыми, поэтому каждый пересказ садится на свою запись.
    """
    entries = {
        module.fingerprint(t): module.findings.Entry(635, "риск", t)
        for t in (NEIGHBOUR_A, NEIGHBOUR_B)
    }
    early = NEIGHBOUR_A.replace("файлу", "пути")
    said = module.pair_up(entries, 635, [early, NEIGHBOUR_A])
    assert said == [module.fingerprint(NEIGHBOUR_B), module.fingerprint(NEIGHBOUR_A)], said


#: Две строки, РАВНО близкие к прежней записи: у каждой одно слово из
#: одиннадцати другое, и сходство у обеих одно и то же до последнего знака —
#: 0.91, выше порога. Друг к другу они ближе порога не подходят (0.82).
TIED_OLD: Final = "scripts/a.py:5 — разбор роняет пустую строку и теряет запись реестра молча"
TIED: Final = (
    TIED_OLD.replace("реестра", "журнала"),
    TIED_OLD.replace("запись", "строку"),
)


def test_a_tie_between_two_lines_gives_the_record_to_neither() -> None:
    """Две строки с РАВНЫМ сходством к одной записи — запись не достаётся никому.

    НАХОДКА ВНЕШНЕГО ВЗГЛЯДА НА #666 (`939c19b`). Сортировка «сильнейшие
    первыми» при точном равенстве сходства решала по месту строки в ответе —
    то есть ровно тем порядком, от которого разбор обещал не зависеть. Какая из
    двух строк пересказ, в ничьей не знает никто; угадав не ту, разбор
    поглотил бы новую находку молча. Поэтому обе заводятся новыми: цена —
    дубль в реестре, а не потеря (та же асимметрия, что у `same_finding`).
    """
    first, second = TIED
    old = module.fingerprint(TIED_OLD)
    entries = {old: module.findings.Entry(5, "риск", TIED_OLD)}
    assert module.pair_up(entries, 5, [first, second]) == [None, None]
    assert module.pair_up(entries, 5, [second, first]) == [None, None]


def test_a_line_between_two_equal_records_is_decided_by_the_fingerprint() -> None:
    """Одна строка, равно близкая к двум записям, садится на одну — и не по порядку.

    Такая ничья потерь не несёт: строка пересказывает одну из записей, обе
    остаются в реестре. Поэтому здесь выбор делается, но его решает отпечаток
    записи, а не порядок, в котором реестр их отдал.
    """
    one, other = "scripts/a.py:5 — первая беда", "scripts/a.py:5 — вторая беда"
    line = "scripts/a.py:5 — беда"
    marks = sorted(module.fingerprint(title) for title in (one, other))
    forward = {module.fingerprint(t): module.findings.Entry(5, "риск", t) for t in (one, other)}
    backward = dict(reversed(list(forward.items())))
    assert module.pair_up(forward, 5, [line]) == [marks[0]]
    assert module.pair_up(backward, 5, [line]) == [marks[0]]


def test_no_order_of_lines_changes_who_retells_whom() -> None:
    """Любая перестановка строк ответа даёт те же пары «строка — запись».

    Проверка по всем перестановкам, а не по двум подобранным: ничья внутри
    одного уровня сходства бывает не только «две строки на одну запись», но и
    цепочкой — строка равно близка к двум записям, а одну из них делит с
    соседом. Разбор, решающий уровень по очереди, отдавал бы записи
    по-разному в зависимости от того, чья пара встретилась первой.
    """
    records = ("scripts/a.py:5 — первая беда", "scripts/a.py:5 — вторая беда")
    # Первая строка равно близка к обеим записям (6/7), вторая — к первой
    # записи с тем же сходством (6/7) и дальше от второй (4/7).
    lines = ["scripts/a.py:5 — беда", "scripts/a.py:5 — первая"]
    entries = {module.fingerprint(t): module.findings.Entry(5, "риск", t) for t in records}
    seen = {
        tuple(sorted(zip(order, module.pair_up(entries, 5, list(order)), strict=True)))
        for order in itertools.permutations(lines)
    }
    assert len(seen) == 1, f"пары зависят от порядка строк: {seen}"


#: Образец ключа, как его показывает промпт: строка с отступом, начинающаяся
#: `НАХОДКА[<вес>]:`. Отступ обязателен — так образец отличается от прозы
#: вокруг него, где ключ упомянут словами.
PROMPT_KEY_RE: Final = re.compile(r"^\s+НАХОДКА\[<вес>\]:\s*(?P<form>.+?)\s*$", re.M)


def prompt_forms() -> list[str]:
    """Формы ключа из всех промптов, выдающих находки (#668)."""
    text = (ROOT / ".github" / "workflows" / "review.yml").read_text(encoding="utf-8")
    return PROMPT_KEY_RE.findall(text)


def test_the_form_the_prompt_asks_for_is_harvested_with_its_address() -> None:
    """Ключ, заполненный ровно по образцу промпта, жатва читает — и с адресом.

    Промпт и разбор живут в разных файлах, и расходятся молча: промпт попросит
    форму, которую жатва не узнает, и находки начнут пропадать без единой
    красной строки. Поэтому образец берётся ИЗ ПРОМПТА, а не переписывается
    сюда — и адрес обязан стоять первым, как того требует #668.
    """
    forms = prompt_forms()
    # Взгляд и поздний взгляд: оба выдают находки, и оба обязаны просить
    # одну форму (#668, пункт «во ВСЕХ промптах»).
    assert len(forms) == 2, f"образцов ключа в промптах {len(forms)}, ждали два: {forms}"
    assert len(set(forms)) == 1, f"промпты просят разную форму ключа: {forms}"
    form = forms[0]
    assert form.startswith("<путь/от/корня.py:12> — "), f"адрес не первым: «{form}»"
    filled = form.replace("<путь/от/корня.py:12>", "scripts/work_plan.py:12").replace(
        "<что не так, одной строкой>", "строка без адреса роняет план"
    )
    found = module.findings_of([comment(f"НАХОДКА[риск]: {filled}")])
    assert [weight for weight, _, _ in found] == ["риск"]
    assert found[0][1] == "scripts/work_plan.py:12 — строка без адреса роняет план", found


def test_a_finding_without_a_place_is_harvested_without_an_address() -> None:
    """`(без места)` — находка, а не адрес: запись заводится, место не выдумывается."""
    found = module.findings_of(
        [comment("НАХОДКА[дефект]: (без места) — тело изменения называет не то число")]
    )
    assert [weight for weight, _, _ in found] == ["дефект"]
    assert found[0][1] == "(без места) — тело изменения называет не то число", found


def test_the_role_that_saw_a_finding_is_read_from_its_bracket() -> None:
    """Роль — слово скобки из карты ролей: `[риск · архитектор]` (#763).

    Незнакомое слово ролью не считается и к ближайшей роли не приводится —
    как и вес (154): запись ляжет без роли, а не с выдуманной.
    """
    known = sorted(module.findings.roles())
    assert known, "карта ролей не прочитана — пометке нечем узнаваться"
    role = known[0]
    got = module.found_in([comment(f"НАХОДКА[риск · {role}]: смотрено ролью")])
    assert got == [("риск", "смотрено ролью", "код", role)]
    assert module.findings_of([comment(f"НАХОДКА[риск · {role}]: смотрено ролью")]) == [
        ("риск", "смотрено ролью", "код")
    ]
    stranger = module.found_in([comment("НАХОДКА[риск · прохожий]: чужое слово")])
    assert stranger == [("риск", "чужое слово", "код", "")]


def test_a_new_entry_keeps_the_role_that_saw_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Запись в реестре несёт роль взгляда: роль не теряется между разбором и записью (#763)."""
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "live_issue", lambda repo, token: (1, ""))
    monkeypatch.setattr(module, "parse_entries", lambda body: {})
    monkeypatch.setattr(module.ghrest, "paginate", lambda path, token: iter([]))
    monkeypatch.setattr(module, "verdict_of", lambda look: 1)
    monkeypatch.setattr(
        module, "found_in", lambda look: [("риск", "увидено архитектором", "код", "архитектор")]
    )
    monkeypatch.setattr(module, "pair_up", lambda *_, **__: [None])
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since="": ({}, since))
    written: dict[str, Any] = {}
    monkeypatch.setattr(
        module, "save", lambda repo, token, entries, apply, swept_to=0: written.update(entries)
    )
    module.main(["--repo", "o/r", "--pr", "333"])
    assert [one.role for one in written.values()] == ["архитектор"]


TWIN_A = "scripts/x.py:12 — отказ площадки не перехвачен и роняет весь заход реестра"
TWIN_B = "scripts/x.py:12 — отказ площадки не перехвачен и роняет весь заход реестра целиком"
OTHER_PLACE = "scripts/y.py:12 — отказ площадки не перехвачен и роняет весь заход реестра"
OTHER_WORDS = "scripts/x.py:40 — число в докстроке вписано рукой и отстаёт от замера"


def test_a_twin_of_a_resolved_finding_leaves_with_it() -> None:
    """Дубль снятой — то же место и то же сходство слов, что у реестра — уходит с ней (#807)."""
    entries = {
        module.fingerprint(one): module.findings.Entry(1, "риск", one)
        for one in (TWIN_A, TWIN_B, OTHER_PLACE, OTHER_WORDS)
    }
    twins = module.twins_of_resolved({module.fingerprint(TWIN_A)}, entries)
    assert twins == {module.fingerprint(TWIN_B): module.fingerprint(TWIN_A)}


def test_the_same_place_alone_is_not_a_twin() -> None:
    """Совпавшее место без сходства слов — другая беда, она не уходит (#657)."""
    entries = {
        module.fingerprint(one): module.findings.Entry(1, "риск", one)
        for one in (TWIN_A, "scripts/x.py:12 — имя переменной вводит в заблуждение")
    }
    assert module.twins_of_resolved({module.fingerprint(TWIN_A)}, entries) == {}


def test_dropping_a_resolved_finding_drops_its_twin_too() -> None:
    """Уборка уносит снятую и её дубль, чужое место оставляет (#807)."""
    entries = {
        module.fingerprint(one): module.findings.Entry(1, "риск", one)
        for one in (TWIN_A, TWIN_B, OTHER_PLACE)
    }
    twins = module.drop_resolved(entries, {module.fingerprint(TWIN_A)})
    assert list(twins) == [module.fingerprint(TWIN_B)]
    assert list(entries) == [module.fingerprint(OTHER_PLACE)]


def test_a_look_alike_on_another_change_is_not_a_twin() -> None:
    """Похожие слова на ДРУГОМ изменении — не дубль: реестр держит их раздельно (#818)."""
    entries = {
        module.fingerprint(TWIN_A): module.findings.Entry(1, "риск", TWIN_A),
        module.fingerprint(TWIN_B): module.findings.Entry(2, "риск", TWIN_B),
    }
    assert module.twins_of_resolved({module.fingerprint(TWIN_A)}, entries) == {}


def test_a_strict_sweep_keeps_retold_titles_apart() -> None:
    """Под `--strict` уборка не сводит недословные заголовки — как и запись (102, #818)."""
    entries = {
        module.fingerprint(one): module.findings.Entry(1, "риск", one) for one in (TWIN_A, TWIN_B)
    }
    swept = {module.fingerprint(TWIN_A)}
    assert module.twins_of_resolved(swept, entries, strict=True) == {}
    assert module.drop_resolved(dict(entries), swept, strict=True) == {}


def test_an_answer_finding_is_no_twin_of_a_code_finding() -> None:
    """Находка об ответе не уходит дублем находки о коде: её снимает правка ответа (#818)."""
    answer = module.findings.ANSWER_KIND
    entries = {
        module.fingerprint(TWIN_A): module.findings.Entry(1, "риск", TWIN_A),
        module.fingerprint(TWIN_B): module.findings.Entry(1, "риск", TWIN_B, kind=answer),
    }
    assert module.twins_of_resolved({module.fingerprint(TWIN_A)}, entries) == {}


def test_a_verifier_answer_is_not_a_look_for_the_registry() -> None:
    """Ответ верификатора не режет отрезок и не несёт находку в реестр (взгляд на #833)."""
    late_look = load_script("late_look.py")
    look = {
        "user": {"login": "claude[bot]"},
        "body": "НАХОДКА[риск]: a.py:1 — своя\nВЕРДИКТ: находок 1",
    }
    answer = {
        "user": {"login": module.LATE_AUTHOR},
        "body": late_look.compose_verification(
            "ПРЕМИСА: да\nНАХОДКА[риск]: b.py:1 — цитата\nВЕРДИКТ: находок 1"
        ),
    }
    titles = [title for _, title, _ in module.findings_of(module.last_look([look, answer]))]
    assert titles == ["a.py:1 — своя"]
    assert module.verdict_of(module.last_look([look, answer])) == 1


def test_is_verification_needs_the_run_author_and_the_first_line() -> None:
    """Метка верификатора узнаётся только от прогона и только первой строкой."""
    run = {"login": module.LATE_AUTHOR}
    assert module.is_verification({"user": run, "body": f"\n {module.VERIFY_MARKER}\nда"})
    assert not module.is_verification(
        {"user": {"login": "claude[bot]"}, "body": module.VERIFY_MARKER}
    )
    assert not module.is_verification({"user": run, "body": f"цитата {module.VERIFY_MARKER}"})
    late = load_script("unlooked.py").LATE_MARKER
    assert not module.is_verification({"user": run, "body": f"{late}\nда"})


def test_the_sweep_hands_the_closers_to_the_answer_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`main` отдаёт в проверку снявших из `resolved_marks`, а не пустоту (взгляд на #838).

    Находку об ответе нашли на #10, сняло её #20, правившее ответ: запись уходит.
    Сняло #30, ответа не правившее: запись остаётся и отказ назван.
    """
    kept = {
        "abc1234": findings_module.Entry(10, "дефект", "находка", kind=findings_module.ANSWER_KIND)
    }
    files = {20: {module.ANSWER_FILE}, 30: {"scripts/arm.py"}}
    saved: list[dict[str, Any]] = []
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "live_issue", lambda repo, token: (1, ""))
    monkeypatch.setattr(module, "parse_entries", lambda body: dict(kept))
    monkeypatch.setattr(module, "touched", lambda repo, token, number: files[number])
    monkeypatch.setattr(module, "save", lambda repo, token, entries, *a, **k: saved.append(entries))
    for closer, left in ((20, {}), (30, kept)):
        monkeypatch.setattr(
            module,
            "resolved_marks",
            lambda repo, token, since="", c=closer: ({"abc1234": {c}}, since),
        )
        module.main(["--sweep", "--repo", "o/r"])
        assert set(saved[-1]) == set(left), f"снявший #{closer}: реестр не тот"
        said = capsys.readouterr().err
        assert ("не принято" in said) == bool(left), f"снявший #{closer}: отказ не назван"
