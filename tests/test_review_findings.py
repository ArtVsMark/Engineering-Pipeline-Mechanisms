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
    assert module.findings_of(comments) == [("дефект", "первая"), ("риск", "вторая")]


def test_finding_survives_markdown_decoration() -> None:
    """Оформление вокруг заголовка не мешает: ревьюер пишет прозой вокруг строк."""
    assert module.findings_of([comment("НАХОДКА[замечание]: **жирный заголовок**")]) == [
        ("замечание", "жирный заголовок")
    ]


def test_a_finding_without_a_weight_says_so() -> None:
    """Вес не назван — так и записано, а не подставлен самый лёгкий.

    Подстановка решила бы за ревьюера в сторону, удобную разбирающему, и
    сделала бы «он не назвал» неотличимым от «он назвал лёгкое» (154).
    """
    assert module.findings_of([comment("НАХОДКА: без веса")]) == [(module.UNWEIGHED, "без веса")]


def test_a_weight_outside_the_scale_is_not_a_weight() -> None:
    """Слово вне шкалы весом не считается и к ближайшему не приводится.

    Шкала закрытая, как роды у фрагментов журнала: приведение «критично» к
    «дефекту» — догадка механизма о том, что имел в виду ревьюер (068).
    """
    assert module.findings_of([comment("НАХОДКА[критично]: чужое слово")]) == [
        (module.UNWEIGHED, "чужое слово")
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
    titles = [title for _, title in module.findings_of(module.last_look(comments))]
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
    titles = [title for _, title in module.findings_of(module.last_look(comments))]
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
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since=0: (set(), since))
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


def merged(number: int, body: str) -> dict[str, Any]:
    """Слитое изменение в том виде, в каком его отдаёт площадка."""
    return {"number": number, "body": body}


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
    page = [merged(50, "Разобрано: aaaaaaa"), merged(49, "Разобрано: bbbbbbb")]
    monkeypatch.setattr(module.ghrest, "merged_changes", lambda repo, token, limit: page)
    marks, mark = module.resolved_marks("o/r", "токен", 49)
    assert marks == {"aaaaaaa"}, "прочитано не от отметки уборки"
    assert mark == 50, "отметка не сдвинулась на прочитанное"


def test_the_sweep_mark_survives_a_round_trip() -> None:
    """Отметка уборки читается обратно из тела: другого хранилища у неё нет."""
    body = module.render_body({}, 417)
    assert module.parse_swept(body) == 417
    assert module.parse_swept("") == 0, "пустое тело — ноль, а не догадка"


def test_a_full_page_beyond_the_sweep_mark_is_said_out_loud(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Страница заполнена, а до отметки не дочитано — сказано, а не проглочено.

    Окно остаётся пределом ЗАПРОСА, а не сроком хранения. Молча передвинуть
    отметку через неувиденное значило бы объявить прочитанным то, чего заход не
    унёс (045).
    """
    page = [merged(number, "") for number in range(100, 97, -1)]
    monkeypatch.setattr(module.ghrest, "merged_changes", lambda repo, token, limit: page)
    module.resolved_marks("o/r", "токен", 10, limit=3)
    said = capsys.readouterr().err
    assert "::warning::" in said and "#10" in said, said


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
        module, "findings_of", lambda look: [("дефект", "тот же дефект другими словами")]
    )
    monkey.setattr(module, "existing_mark", lambda entries, pr, title, strict=False: "abc1234")
    monkey.setattr(module, "resolved_marks", lambda repo, token, since=0: (set(), since))
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
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since=0: (set(), since))
    monkeypatch.setattr(module, "save", lambda *a, **k: None)
    assert module.main(["--sweep", "--repo", "o/r"]) == module.EXIT_NOTHING


def test_a_registry_with_entries_stays_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    """Неразобранное осталось — исход «ждёт», и он не тот же, что пустой реестр."""
    kept = {"abc1234": findings_module.Entry(131, "дефект", "очередь читает не то")}
    monkeypatch.setenv("GH_TOKEN", "токен")
    monkeypatch.setattr(module, "live_issue", lambda repo, token: (1, ""))
    monkeypatch.setattr(module, "parse_entries", lambda body: dict(kept))
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since=0: (set(), since))
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
        module, "findings_of", lambda comments: [("дефект", "очередь читает не то")]
    )
    monkeypatch.setattr(module, "resolved_marks", lambda repo, token, since=0: (set(), since))
    monkeypatch.setattr(module, "save", lambda *a, **k: None)
    module.main(["--repo", "o/r", "--pr", "131"])
    said = capsys.readouterr().err
    assert "::warning::" in said, "расхождение осталось в логе — наружу его не видно"
    assert "находок 3" in said and "строк находок 1" in said, "числа не названы"
