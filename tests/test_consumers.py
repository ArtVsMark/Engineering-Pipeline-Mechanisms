"""Сверка потребителей: факты читаются у них, адреса ведутся у нас.

Версия, на которой стоит потребитель, и то, какие шаги он обошёл, лежат в ЕГО
`.pipeline.yml`: факты о проекте публикует сам проект (174). Реестр, ведомый за
потребителя, разошёлся бы с ним молча — и разошёлся бы в ту сторону, где мы
считаем, что всё хорошо. Проверяется здесь то, без чего сверка была бы вторым
реестром:

* адреса берутся из объявленного реестра, а запись обязана назвать себя целиком;
* обход виден как обход, и обход БЕЗ ПРИЧИНЫ назван отдельно (154);
* пустой список — состояние, а не отказ и не тишина;
* непрочитанный ответ — третий исход, а не «все на свежей версии» (045).
"""

import base64
import json
from pathlib import Path
from typing import Any, Final

import pytest

from tests.conftest import ROOT, load_script

module = load_script("consumers.py")
policy = load_script("pipeline_checks.py")


def registry_with(tmp_path: Path, *rows: dict[str, Any]) -> Path:
    """Дерево с реестром адресов — настоящим файлом, а не подменённым чтением."""
    (tmp_path / ".rules").mkdir(parents=True)
    (tmp_path / ".rules" / "consumers.json").write_text(
        json.dumps({"connected": list(rows)}, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


def empty_sweep(tmp_path: Path) -> Path:
    """Файл обхода семьи, прочитавшего всех и не заставшего никого."""
    path = tmp_path / "sweep.json"
    path.write_text(json.dumps({"by": [], "projects": {"unread_repos": []}}), encoding="utf-8")
    return path


def answering(monkeypatch: pytest.MonkeyPatch, said: str) -> None:
    """Потребитель отдаёт свой ответ — так, как его отдаёт площадка: в base64."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")
    monkeypatch.setattr(
        module.ghrest,
        "request",
        lambda *_, **__: {"content": base64.b64encode(said.encode()).decode()},
    )


def test_an_empty_registry_is_a_state_not_a_refusal(tmp_path: Path) -> None:
    """Подключённых нет — состояние, а не отказ и не тишина (154).

    Отказ здесь означал бы «проект обязан иметь потребителей», а тишина —
    «все на свежей версии», чего никто не проверял. Пустота — состояние, только
    когда обход семьи прочитан целиком; без него молча подключённые не видны, и
    это третий исход, а не «никого» (взгляд на #1443).
    """
    uptake = tmp_path / "uptake.json"
    uptake.write_text(json.dumps({"by": [], "projects": {"unread_repos": []}}), encoding="utf-8")
    root = registry_with(tmp_path)
    assert module.main(["--root", str(root), "--uptake", str(uptake)]) == module.EXIT_OK
    assert module.main(["--root", str(root)]) == module.EXIT_UNREAD


def test_a_row_must_name_itself(tmp_path: Path) -> None:
    """Запись без адреса, даты или причины — отказ входа, а не полузапись."""
    root = registry_with(tmp_path, {"repo": "o/r"})
    with pytest.raises(module.NotRun, match="since"):
        module.registry(root)


def test_a_missing_registry_does_not_run(tmp_path: Path) -> None:
    """Реестра нет — у кого спрашивать, взять неоткуда (075)."""
    assert module.main(["--root", str(tmp_path)]) == module.EXIT_BROKEN


def test_a_bypass_is_seen_as_a_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Шаг, объявленный выключенным, виден обходом — с причиной и без."""
    answering(monkeypatch, 'checks:\n  "lint / lint":\n    class: off\n    why: свой линтер\n')
    assert module.bypassed(module.answer_of("o/r", "токен")) == ["lint / lint"]


def test_a_bypass_without_a_reason_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обход БЕЗ причины называется отдельно: это молчание, а не состояние.

    Вторая половина. Без неё сверка показывала бы объявленный и необъявленный
    обход одинаково — то есть ровно то, ради чего объявление и заведено (154).
    """
    answering(monkeypatch, 'checks:\n  "lint / lint": off\n')
    assert module.bypassed(module.answer_of("o/r", "токен")) == ["lint / lint — БЕЗ ПРИЧИНЫ"]


def test_a_live_step_is_not_a_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подключённый шаг обходом не считается — иначе предикат шире предмета."""
    answering(monkeypatch, 'checks:\n  "lint / lint": required\n  "debt / debt": advisory\n')
    assert module.bypassed(module.answer_of("o/r", "токен")) == []


def test_an_unread_answer_is_its_own_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ответ не прочитан — третий исход, а не «все на свежей версии» (045)."""
    root = registry_with(tmp_path, {"repo": "o/r", "since": "2026-09-19", "why": "берёт линтер"})
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")

    def broken(*_: object, **__: object) -> Any:
        raise module.ghrest.TransportError("404")

    monkeypatch.setattr(module.ghrest, "request", broken)
    assert module.main(["--root", str(root), "--uptake", str(empty_sweep(tmp_path))]) == (
        module.EXIT_UNREAD
    )


def test_without_a_token_the_answers_are_not_guessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Токена нет — ответы НЕ прочитаны, и это сказано, а не выдано за чистоту."""
    root = registry_with(tmp_path, {"repo": "o/r", "since": "2026-09-19", "why": "берёт линтер"})
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")
    assert module.main(["--root", str(root), "--uptake", str(empty_sweep(tmp_path))]) == (
        module.EXIT_UNREAD
    )


def test_the_live_registry_is_readable() -> None:
    """Живой реестр дерева разбирается и называет свою пустоту словами (139)."""
    said = json.loads((ROOT / module.paths.CONSUMERS).read_text(encoding="utf-8"))
    assert module.CONNECTED in said, "в реестре нет раздела подключённых"
    assert not said[module.CONNECTED], "подключённые появились — перемерьте этот прогон"
    assert any("пуст" in key for key in said), "пустота реестра не названа причиной (154)"


#: Реестры не той формы: каждый обязан дойти до объявленного исхода, а не
#: уронить заход. Снаружи `AttributeError` неотличим от поломки механизма.
MALFORMED: Final = (
    ("реестр — список", "[]"),
    ("реестр — строка", '"ничего"'),
    ("раздел — словарь", '{"connected": {"o/r": "да"}}'),
    ("запись — строка", '{"connected": ["o/r"]}'),
    ("запись — число", '{"connected": [7]}'),
)


@pytest.mark.parametrize(("case", "said"), MALFORMED, ids=[one[0] for one in MALFORMED])
def test_a_malformed_registry_reaches_its_outcome(tmp_path: Path, case: str, said: str) -> None:
    """Реестр не той формы доходит до ОБЪЯВЛЕННОГО исхода, а не роняет заход.

    Модуль объявляет исходы в своей докстроке (039), и `AttributeError` мимо
    них — не один из них: снаружи он читается как поломка механизма, а не как
    ошибка входа (075). Нашёл внешний взгляд (`0612be4`).
    """
    (tmp_path / ".rules").mkdir(parents=True)
    (tmp_path / ".rules" / "consumers.json").write_text(said, encoding="utf-8")
    assert module.main(["--root", str(tmp_path)]) == module.EXIT_BROKEN, case


def test_the_entry_is_parsed_by_the_owner_of_the_form() -> None:
    """Запись ответа разбирает тот, кто владеет формой, — обе её формы.

    Форм две: голый класс и словарь. Выемка класса делалась в двух местах, и
    общим было сделано только приведение к строке: поменяйся форма у владельца,
    здесь она осталась бы прежней, и объявленный обход стал бы невидим (090).
    """
    assert policy.entry_of({"class": "off", "why": "своё"}) == (policy.OFF, "своё", "")
    assert policy.entry_of(False) == (policy.OFF, "", "")
    assert policy.entry_of("required") == (policy.REQUIRED, "", "")


def test_a_project_found_by_the_sweep_is_connected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Подключённый молча виден из обхода семьи и спрашивается так же (#1389)."""
    root = registry_with(tmp_path)
    uptake = tmp_path / "uptake.json"
    uptake.write_text(json.dumps({"by": [{"repo": "o/тихий"}]}), encoding="utf-8")
    answering(monkeypatch, 'checks:\n  "lint / lint": required\n')
    assert module.main(["--root", str(root), "--uptake", str(uptake)]) == module.EXIT_OK
    out = capsys.readouterr().out
    assert "o/тихий: найден обходом семьи" in out and "o/тихий: диапазон" in out


def test_a_sweep_file_of_another_shape_does_not_run(tmp_path: Path) -> None:
    """Файл не той формы — отказ, а не «никто не взял» (045)."""
    root = registry_with(tmp_path)
    uptake = tmp_path / "uptake.json"
    uptake.write_text(json.dumps({"projects": {}}), encoding="utf-8")
    assert module.main(["--root", str(root), "--uptake", str(uptake)]) == module.EXIT_BROKEN
    with pytest.raises(module.NotRun):
        module.swept(uptake.with_name("нет.json"))


def test_the_sweep_names_whom_it_did_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Непрочитанные обходом названы, и заход не выдаёт часть семьи за всю (045)."""
    root = registry_with(tmp_path)
    uptake = tmp_path / "uptake.json"
    uptake.write_text(
        json.dumps({"by": [], "projects": {"unread_repos": ["o/закрытый"]}}), encoding="utf-8"
    )
    assert module.swept(uptake) == ([], ["o/закрытый"])
    answering(monkeypatch, 'checks:\n  "lint / lint": required\n')
    assert module.main(["--root", str(root), "--uptake", str(uptake)]) == module.EXIT_UNREAD
    assert "o/закрытый: обход семьи его дерево не прочитал" in capsys.readouterr().out


def test_a_declared_project_is_not_found_twice_in_another_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Регистр имени не значим: объявленный не становится «найденным обходом» вторично."""
    row = {"repo": "Owner/Repo", "since": "2026-09-19", "why": "берёт линтер"}
    root = registry_with(tmp_path, row)
    uptake = tmp_path / "uptake.json"
    uptake.write_text(json.dumps({"by": [{"repo": "OWNER/REPO"}]}), encoding="utf-8")
    answering(monkeypatch, 'checks:\n  "lint / lint": required\n')
    assert module.main(["--root", str(root), "--uptake", str(uptake)]) == module.EXIT_OK
    assert "найден обходом семьи" not in capsys.readouterr().out


def test_without_a_sweep_the_silent_are_named_unseen(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Обход не передан — сказано, что молча подключённых не видно, и пустота не «никого»."""
    assert module.main(["--root", str(registry_with(tmp_path))]) == module.EXIT_UNREAD
    out = capsys.readouterr().out
    assert out.strip().splitlines()[-1] == module.NO_SWEEP
    assert out.count(module.NO_SWEEP) == 1, "итог без обхода сказан дважды"
    assert "среди тех, кого видно" in out and "это состояние" not in out


def test_a_declared_registry_without_a_sweep_is_not_read_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Реестр не пуст, ответы прочитаны, обхода нет — исход 3: молча подключённых не видно."""
    root = registry_with(tmp_path, {"repo": "o/r", "since": "2026-09-19", "why": "берёт линтер"})
    answering(monkeypatch, 'checks:\n  "lint / lint": required\n')
    assert module.main(["--root", str(root)]) == module.EXIT_UNREAD
    out = capsys.readouterr().out
    # Строка — по константе, а не по началу (находка `d380055`): вступление и
    # итог начинались одинаково, и тест их не различал (`f4a5c14`).
    assert out.strip().splitlines()[-1] == module.NO_SWEEP
    assert out.count(module.NO_SWEEP) == 1, "итог без обхода сказан дважды"
    assert module.main(["--root", str(root), "--uptake", str(empty_sweep(tmp_path))]) == (
        module.EXIT_OK
    )


def test_the_sweep_drops_repeats_without_case(tmp_path: Path) -> None:
    """Повтор найденного в другом регистре — один проект, первое написание (находка `e775d7d`)."""
    uptake = tmp_path / "uptake.json"
    uptake.write_text(
        json.dumps({"by": [{"repo": "Owner/Repo"}, {"repo": "owner/repo"}, {"repo": "o/r"}]}),
        encoding="utf-8",
    )
    assert module.swept(uptake) == (["Owner/Repo", "o/r"], [])


def test_unread_answers_are_said_in_the_stream_of_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Итог «не прочитано ответов» — в stdout, где и «обход не прочитал» (находка `9695b0a`).

    Отказ по отдельному проекту остаётся диагностикой — в stderr.
    """
    root = registry_with(tmp_path, {"repo": "o/r", "since": "2026-09-19", "why": "берёт линтер"})
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")

    def refuse(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("502")

    monkeypatch.setattr(module.ghrest, "request", refuse)
    assert module.main(["--root", str(root), "--uptake", str(empty_sweep(tmp_path))]) == (
        module.EXIT_UNREAD
    )
    said = capsys.readouterr()
    assert said.out.strip().splitlines()[-1] == "не прочитано ответов: 1 из 1"
    assert "o/r: не прочитан" in said.err


# --- все исходы неполноты — одним путём (взгляд на #1483, правило 210) --------


def refusing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка отвечает отказом на чтение ответа потребителя."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "токен")

    def refuse(*_: Any, **__: Any) -> Any:
        raise module.ghrest.TransportError("502")

    monkeypatch.setattr(module.ghrest, "request", refuse)


def without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Токена площадки нет."""
    monkeypatch.setattr(module.ghrest, "token_from_env", lambda: "")


def reading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ответ потребителя читается целиком."""
    answering(monkeypatch, 'checks:\n  "lint / lint": required\n')


ROW: Final = {"repo": "o/r", "since": "2026-09-19", "why": "берёт линтер"}


@pytest.mark.parametrize(
    ("rows", "platform"),
    [((), reading), ((ROW,), without_token), ((ROW,), refusing), ((ROW,), reading)],
    ids=["пустой-реестр", "без-токена", "ответ-не-прочитан", "ответ-прочитан"],
)
def test_every_exit_without_a_sweep_names_it_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    rows: tuple[dict[str, Any], ...],
    platform: Any,
) -> None:
    """Без обхода любой выход захода говорит `NO_SWEEP` ровно раз, в stdout, и исход 3.

    Прежде ранние выходы — без токена и с непрочитанным ответом — возвращали 3
    и молчали, что молча подключённые не видны (взгляд на #1483).
    """
    platform(monkeypatch)
    assert module.main(["--root", str(registry_with(tmp_path, *rows))]) == module.EXIT_UNREAD
    said = capsys.readouterr()
    assert said.out.count(module.NO_SWEEP) == 1
    assert module.NO_SWEEP not in said.err


def test_without_a_token_the_verdict_is_in_the_stream_of_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """«Ответы НЕ ПРОЧИТАНЫ» — итог неполноты, и он в stdout, как и прочие (взгляд на #1483)."""
    without_token(monkeypatch)
    root = registry_with(tmp_path, ROW)
    assert module.main(["--root", str(root), "--uptake", str(empty_sweep(tmp_path))]) == (
        module.EXIT_UNREAD
    )
    said = capsys.readouterr()
    assert said.out.strip().splitlines() == [module.NO_TOKEN]
    assert said.err == ""


def test_the_sweep_drops_unread_repeats_without_case(tmp_path: Path) -> None:
    """Непрочитанные сводятся без регистра, как и найденные (взгляд на #1483)."""
    uptake = tmp_path / "uptake.json"
    uptake.write_text(
        json.dumps({"by": [], "projects": {"unread_repos": ["Owner/Repo", "owner/repo", "o/x"]}}),
        encoding="utf-8",
    )
    assert module.swept(uptake) == ([], ["Owner/Repo", "o/x"])


@pytest.mark.parametrize(
    ("given", "said"),
    [
        ({"swept_given": True, "unswept": 0, "unread": 0, "total": 2, "token": True}, []),
        (
            {"swept_given": False, "unswept": 0, "unread": 0, "total": 2, "token": True},
            [module.NO_SWEEP],
        ),
        (
            {"swept_given": False, "unswept": 0, "unread": 2, "total": 2, "token": False},
            [module.NO_TOKEN, "не прочитано ответов: 2 из 2", module.NO_SWEEP],
        ),
        (
            {"swept_given": True, "unswept": 1, "unread": 1, "total": 3, "token": True},
            [
                "не прочитано ответов: 1 из 3",
                "обход семьи не прочитал проектов: 1 — список выше неполон",
            ],
        ),
    ],
    ids=["полна", "без-обхода", "без-токена-и-обхода", "непрочитанное"],
)
def test_the_gaps_are_named_together_and_decide_the_outcome(
    given: dict[str, Any], said: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Неполнота называется вся разом, каждая строка один раз, и она же решает исход."""
    gaps = module.gaps_of(**given)
    assert gaps == said
    code = module.finish(gaps)
    assert code == (module.EXIT_UNREAD if said else module.EXIT_OK)
    out = capsys.readouterr()
    assert out.out.splitlines() == said and not out.err
