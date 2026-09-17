"""Разбор вердикта ревьюера и живая задача-адресат.

Находка читается СТРОКАМИ, а не прозой (166): формулировка ревьюера меняется от
прогона к прогону, а строка — нет. Здесь проверяется именно это чтение, потому
что на нём держится всё остальное: не распознанная строка равна потерянной
находке, и потеря выглядит как «находок нет».
"""

from __future__ import annotations

from typing import Any

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
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since="": (set(), since))
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
    assert marks == {"aaaaaaa"}, "прочитано не от отметки уборки"
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
    entries = {"abc1234": findings_module.Entry(333, "дефект", "старый заголовок", kept)}
    monkey = pytest.MonkeyPatch()
    monkey.setenv("GH_TOKEN", "токен")
    monkey.setattr(module, "live_issue", lambda repo, token: (1, ""))
    monkey.setattr(module, "parse_entries", lambda body: dict(entries))
    monkey.setattr(module.ghrest, "paginate", lambda path, token: iter([]))
    monkey.setattr(module, "verdict_of", lambda look: 1)
    monkey.setattr(
        module, "findings_of", lambda look: [("дефект", "тот же дефект другими словами", "код")]
    )
    monkey.setattr(module, "existing_mark", lambda entries, pr, title, strict=False: "abc1234")
    monkey.setattr(module, "resolved_marks", lambda repo, token, since="": (set(), since))
    written: dict[str, Any] = {}
    monkey.setattr(
        module, "save", lambda repo, token, entries, apply, swept_to=0: written.update(entries)
    )
    module.main(["--repo", "o/r", "--pr", "333"])
    monkey.undo()
    assert written["abc1234"].checked == kept, "ответ верификатора стёрт пересказом находки"


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
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since="": (set(), since))
    monkeypatch.setattr(module, "save", lambda *a, **k: None)
    assert module.main(["--sweep", "--repo", "o/r"]) == module.EXIT_NOTHING


def test_a_registry_with_entries_stays_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    """Неразобранное осталось — исход «ждёт», и он не тот же, что пустой реестр."""
    kept = {"abc1234": findings_module.Entry(131, "дефект", "очередь читает не то")}
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "live_issue", lambda repo, token: (1, ""))
    monkeypatch.setattr(module, "parse_entries", lambda body: dict(kept))
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since="": (set(), since))
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
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since="": (set(), since))
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
    assert marks == set(), "прочитано то, чего на странице нет"
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
    assert marks == {"aaaaaaa", "ccccccc"}, (
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
    assert marks == {"eeeeeee"}, "прочитано слитое без времени"
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
    берём, держим = module.closable("o/r", "t", {"abc1234"}, entries)
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
    берём, держим = module.closable("o/r", "t", {"abc1234"}, entries)
    assert берём == {"abc1234"} and not держим


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
    берём, держим = module.closable("o/r", "t", {"abc1234"}, entries)
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
    берём, держим = module.closable("o/r", "t", {"abc1234"}, entries)
    assert берём == {"abc1234"} and not держим
