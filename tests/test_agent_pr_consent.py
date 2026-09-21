"""Согласие отдать изменение очереди ставит механизм, а снимает человек.

Ветка с приставкой конвейера и есть заявленное согласие: окно резало её под
задачу, а не для того, чтобы зелёное изменение стояло и ждало метки. Ждать
руки значит вернуть ровно ту беду, от которой очередь заведена, — и у соседа
по семье это уже пройдено: там согласие ставится сразу при открытии.

Обратное направление тоньше и важнее. Отличить «метку ещё не ставили» от
«поставили и сняли» по состоянию изменения нельзя — оно одинаковое, — поэтому
снятое человеком согласие вернулось бы следующим толчком, и отмена не работала
бы вовсе. Отзыв выражается явно стоп-меткой, и она сильнее
([147](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/147-a-cancelling-switch-needs-an-addressee.md)).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import load_script

module = load_script("agent_pr.py")


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, Any]]:
    """Записывает обращения к площадке вместо того, чтобы их выполнять."""
    seen: list[tuple[str, str, Any]] = []

    def remember(method: str, path: str, token: str, body: Any = None) -> Any:
        seen.append((method, path, body))
        return {}

    monkeypatch.setattr(module.ghrest, "request", remember)
    return seen


def test_a_fresh_change_is_handed_to_the_queue(platform: list[tuple[str, str, Any]]) -> None:
    """Только что открытому изменению согласие ставится сразу."""
    module.apply_consent("о/р", 7, "токен", set(), dry_run=False)
    assert platform == [("POST", "repos/о/р/issues/7/labels", {"labels": [module.CONSENT]})]


def test_the_stop_label_takes_the_consent_off(platform: list[tuple[str, str, Any]]) -> None:
    """Стоп-метка не просто держит очередь — она снимает согласие.

    Иначе след врёт: изменение помечено отданным автоматике, а автоматика его
    не двигает, и по меткам этого не видно.
    """
    module.apply_consent("о/р", 7, "токен", {module.HOLD, module.CONSENT}, dry_run=False)
    method, path, _ = platform[0]
    assert method == "DELETE" and path.endswith(f"/labels/{module.CONSENT}")


def test_a_refused_label_does_not_lose_the_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ разметки не роняет шаг: изменение уже открыто (084).

    Потерять открытие из-за метки — худший размен: метку поставит человек, а
    заново открытое изменение сменит автора.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise module.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    module.apply_consent("о/р", 7, "токен", set(), dry_run=False)


def test_a_dry_run_touches_nothing(platform: list[tuple[str, str, Any]]) -> None:
    """Пробный заход площадку не трогает — ни в ту, ни в другую сторону."""
    module.apply_consent("о/р", 7, "токен", set(), dry_run=True)
    module.apply_consent("о/р", 7, "токен", {module.HOLD}, dry_run=True)
    assert platform == []


def test_nothing_to_remove_is_not_a_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Согласия нет и стоп-метка на месте — обычное состояние повторного захода.

    Толчков в ветку с висящей стоп-меткой бывает много, и каждый звал снятие
    уже снятой метки: площадка отвечала отказом, а механизм жаловался на
    исправно работающую отмену (045).
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("снимать нечего — площадку звать незачем")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    module.apply_consent("о/р", 7, "токен", {module.HOLD}, dry_run=False)
    assert "не будет" in capsys.readouterr().out


def test_a_lost_race_is_the_same_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Метку сняли раньше нас — тот же успех, достигнутый не нами."""

    def gone(*args: object, **kwargs: object) -> None:
        raise module.ghrest.NotFound("404")

    monkeypatch.setattr(module.ghrest, "request", gone)
    module.apply_consent("о/р", 7, "токен", {module.HOLD, module.CONSENT}, dry_run=False)
    printed = capsys.readouterr().out
    assert "уже нет" in printed and "не снято" not in printed


def test_a_real_refusal_on_removal_is_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Настоящий отказ транспорта называется отказом, а не «уже снято» (045)."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise module.ghrest.TransportError("площадка недоступна")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    module.apply_consent("о/р", 7, "токен", {module.HOLD, module.CONSENT}, dry_run=False)
    assert "не снято" in capsys.readouterr().out


def test_a_branch_with_commits_but_no_diff_is_not_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    """Коммиты есть, а диффа против общей ветки нет — открывать нечего.

    Так выходит, когда работа уже уехала в общую ветку соседним изменением:
    коммиты в ветке остались, содержимого сверх базы нет. Такое изменение
    объявляло бы работу, которой не делает — замер 12.09.2026: #224 заявлял два
    исправления при пустом диффе, и нашёл это внешний взгляд, а не механизм
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """

    def git(*args: str) -> str:
        if args[0] == "merge-base":
            return "base-sha\n"
        if args[0] == "diff":
            return "\0"
        return "fix: работа, уже слитая соседом\n\nRefs #224\n"

    monkeypatch.setattr(module, "git", git)
    with pytest.raises(module.NotRun, match="диффа против main нет"):
        module.describe("agent/окно", "main")


def test_a_branch_with_a_real_diff_is_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    """Здоровый вход обязан пройти: дифф есть — изменение открывается.

    Иначе гейт нулевого диффа неотличим от «открытие сломалось» (097).
    """

    def git(*args: str) -> str:
        if args[0] == "merge-base":
            return "base-sha\n"
        if args[0] == "diff":
            return "scripts/x.py\0"
        return "fix: настоящая работа\n\nRefs #224\n"

    monkeypatch.setattr(module, "git", git)
    said = module.describe("agent/окно", "main")
    title, body = said.title, said.body
    # Подделка отдаёт один и тот же текст на любую команду, поэтому строк
    # «предмета» в нём выходит две и заголовок получает «(+1)». Проверяется
    # здесь другое: заход НЕ отказал и собрал описание.
    assert title.startswith("fix: настоящая работа")
    assert "Refs #224" in body


# --- опубликованное перечитывают (188) ----------------------------------------


def test_a_resolution_that_did_not_survive_publication_is_named(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Снятие, не пережившее публикацию, называется вслух, а не теряется молча.

    Строка «Разобрано: <отпечаток>» — команда ДРУГОМУ механизму: уборка реестра
    находок читает её из тела изменения и по ней уносит запись. Успешный код
    ответа доказывает приём запроса, а не доставку смысла
    ([188](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/188-published-is-not-delivered.md)):
    перепиши площадка тело — снятие исчезнет, работа окажется сделанной, а
    запись останется висеть неразобранной. Ровно такую потерю проект уже
    пережил 16.09.2026, хотя и по другой причине.

    ПРЕДУПРЕЖДЕНИЕ, А НЕ ОТКАЗ: изменение уже открыто, и ронять шаг значило бы
    менять потерю записи на потерю изменения (084).
    """
    sent = "тело\n\nРазобрано: abc1234\nРазобрано: def5678\n"
    module.say_lost_marks("тело\n\nРазобрано: abc1234\n", sent)
    said = capsys.readouterr().err
    assert "::warning::" in said and "def5678" in said, said


def test_a_body_that_arrived_whole_says_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    """Тело доехало — предупреждения нет: сигнал, звучащий всегда, не читают (051)."""
    sent = "тело\n\nРазобрано: abc1234\n"
    module.say_lost_marks(sent, sent)
    assert capsys.readouterr().err == ""


def test_the_platform_may_normalise_whitespace() -> None:
    """Судятся ОТПЕЧАТКИ, а не тело побайтово.

    Площадка вправе нормализовать перевод строки и пробел, и требовать точного
    совпадения значило бы краснеть на исправном (051). Предмет — ровно то, что
    кто-то обязан прочитать и по чему обязан действовать.
    """
    sent = "тело\n\nРазобрано: abc1234\n"
    assert module.kept_the_marks(sent.replace("\n", "\r\n"), sent) == []


# --- задержка объявляется ДО открытия (#551) ----------------------------------


def held_branch(monkeypatch: pytest.MonkeyPatch, body: str) -> Any:
    """Разбор ветки, чьи коммиты несут заданное тело."""

    def git(*args: str) -> str:
        if args[0] == "merge-base":
            return "базаbaseSHA"
        if args[0] == "diff":
            return "scripts/x.py\0"
        return body

    monkeypatch.setattr(module, "git", git)
    return module.describe("agent/окно", "main")


def test_a_hold_trailer_is_read_before_the_change_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Причина задержки читается из КОММИТА, то есть раньше открытия.

    Стоп-метку можно поставить только после открытия, а согласие ставится
    сразу — между этими мгновениями изменение полностью готово к слиянию.
    Замер по живой ленте #549: `automerge` в 19:40:09, снят в 19:40:40,
    `hold` в 19:40:41 — тридцать одна секунда.
    """
    said = held_branch(monkeypatch, "ЗАМЕР: две минуты\n\nЖдёт: временные прогоны\n\nRefs #224\n")
    assert said.hold == "временные прогоны"
    assert "Задержано автором" in said.body
    assert "временные прогоны" in said.body


def test_a_change_without_the_trailer_is_not_held(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вторая половина: обычное изменение задержанным не объявляется.

    Без неё «всегда задержано» остановило бы конвейер целиком, а такой
    механизм обходят первым же ручным слиянием (051).
    """
    said = held_branch(monkeypatch, "fix: обычная работа\n\nRefs #224\n")
    assert said.hold is None
    assert "Задержано автором" not in said.body


def test_a_held_change_gets_the_stop_label(platform: list[tuple[str, str, Any]]) -> None:
    """Объявленная задержка ставит стоп-метку."""
    module.apply_hold("о/р", 7, "токен", "временные прогоны", dry_run=False)
    assert platform == [("POST", "repos/о/р/issues/7/labels", {"labels": [module.HOLD]})]


def test_a_held_change_never_gets_consent(platform: list[tuple[str, str, Any]]) -> None:
    """Согласия задержанное изменение не получает НИ НА МИНУТУ — приёмка #551.

    Проверяется не проза, а состав обращений к площадке: стоп-метка уже в
    руках, и `apply_consent` про согласие даже не спрашивает.
    """
    module.apply_consent("о/р", 7, "токен", {module.HOLD}, dry_run=False)
    assert platform == [], f"задержанное изменение трогало метки: {platform}"


def test_a_refused_stop_label_is_said_out_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ разметки шаг не роняет, но и не молчит (084, 045).

    Без метки задержанное изменение уйдёт в очередь, и автор узнает об этом от
    слияния — то есть тишина здесь дороже красного.
    """

    def broken(*_a: object, **_k: object) -> None:
        raise module.ghrest.TransportError("площадка молчит")

    monkeypatch.setattr(module.ghrest, "request", broken)
    module.apply_hold("о/р", 7, "токен", "временные прогоны", dry_run=False)


def test_a_dry_run_does_not_hold_either(platform: list[tuple[str, str, Any]]) -> None:
    """Сухой заход ничего не ставит — ни согласия, ни стоп-метки."""
    module.apply_hold("о/р", 7, "токен", "временные прогоны", dry_run=True)
    assert platform == []


def test_the_described_answer_is_named_not_a_pair() -> None:
    """Состав ответа `describe` именован: третье значение не теряется в распаковке.

    Проверяется ровно то, ради чего заведён `Described`: добавь третье значение
    к паре — и оно либо сломает каждого зовущего `title, body = …`, либо, что
    хуже, уедет тише
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Поэтому у задержки ИМЯ, а не место в кортеже.
    """
    said = module.Described(title="заголовок", body="тело", hold="замер")
    assert (said.title, said.body, said.hold) == ("заголовок", "тело", "замер")

    # Пары здесь нет и быть не должно: распаковка на двоих обязана отказать,
    # а не тихо отдать два поля из трёх.
    with pytest.raises(TypeError):
        _title, _body = said


def test_a_change_without_a_trailer_is_described_unheld() -> None:
    """Обычное изменение приезжает НЕзадержанным: `hold` пуст, а не пустая строка.

    Половина предиката, которую забывают: гейт, объявляющий задержку всегда,
    неотличим от исправного по одной только первой проверке.
    """
    assert module.Described(title="з", body="т", hold=None).hold is None


# --- тема коммита не несёт номера (#582) --------------------------------------


def test_a_subject_carrying_a_number_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Шаг открытия отказывает теме с номером — до толчка, а не после слияния.

    ЗАМЕР (21.09.2026, #582): номер в теме пишет автор, а площадка приписывает
    свой при уплотнении. Тема #579 вышла «… (#551) (+2) (#579)», счёт принятых
    изменений разошёлся, и покраснела ОБЩАЯ ветка — там тему уже не переписать
    ([123](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/123-attribution-is-verified-on-the-final-history.md)).

    Отказ стоит там, где тема рождается: предполётная зовёт этот шаг сухим
    прогоном ПЕРЕД толчком.
    """

    def git(*args: str) -> str:
        if args[0] == "merge-base":
            return "base-sha\n"
        if args[0] == "diff":
            return "scripts/x.py\0"
        if args[0] == "log" and "--format=%s" in args:
            return "Работа и её предмет (#551)\n"
        return "тело\n\nRefs #551\n"

    monkeypatch.setattr(module, "git", git)
    with pytest.raises(module.NotRun) as refused:
        module.describe("agent/окно", "main")
    assert "номер" in str(refused.value), "отказ не называет свой предмет (154)"


def test_a_clean_subject_is_not_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вторая половина: обычная тема проходит.

    Без неё отказ неотличим от «не открывать ничего»: первая половина зеленеет
    и на предикате, который отвергает всё подряд.
    """

    def git(*args: str) -> str:
        if args[0] == "merge-base":
            return "base-sha\n"
        if args[0] == "diff":
            return "scripts/x.py\0"
        if args[0] == "log" and "--format=%s" in args:
            return "Работа и её предмет без номера\n"
        return "тело\n\nRefs #551\n"

    monkeypatch.setattr(module, "git", git)
    said = module.describe("agent/окно", "main")
    assert said.title.startswith("Работа и её предмет без номера")


# --- задержка, названная трейлером, не считается забытой меткой (#587) --------


def test_a_held_change_is_not_called_a_forgotten_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тело, собранное по трейлеру, читается реестром застрявших как названное.

    НАХОДКА ВНЕШНЕГО ВЗГЛЯДА (`fb95a71` на #579), и она была верна. Автор писал
    `Hold:`, шаг открытия клал в тело прозу «Это изменение не для слияния: …»,
    а `stuck.py` искал `Ждёт:` — и не находил. Вердикт выходил
    `STUCK_HOLD_MUTE`: «стоп-метка не называет, чего ждёт». То есть задержка с
    ЯВНО названной причиной попадала в реестр застрявших как ЗАБЫТАЯ.

    Смысл задачи #551 — «причина обязательна: задержка без причины неотличима
    от забытой метки» — выполнялся ровно наполовину: причину требовали, а в
    формат, который умеет отличать названное от забытого, не переносили.

    Проверяется СТЫК, а не один механизм: тело строит `agent_pr`, читает его
    `stuck`, и утверждение верно только если оба согласны про одну строку.
    """
    stuck = load_script("stuck.py")
    said = held_branch(monkeypatch, "ЗАМЕР\n\nЖдёт: временные прогоны\n\nRefs #224\n")

    assert said.hold == "временные прогоны"
    assert stuck.waits_for(said.body) == "временные прогоны", (
        "реестр застрявших не нашёл условия в теле, которое собрал шаг открытия — "
        "задержка с названной причиной будет названа забытой меткой"
    )

    verdict = stuck.judge(
        {
            "number": 1,
            "draft": False,
            "mergeable_state": "clean",
            "labels": [{"name": "hold"}],
            "body": said.body,
            "head": {"sha": "deadbee"},
        },
        [],
        (),
        armed=False,
        fresh=False,
    )
    assert verdict.why != stuck.STUCK_HOLD_MUTE, (
        "задержка с названным условием всё ещё зовётся забытой меткой"
    )
