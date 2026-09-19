"""Чужое «почему» — ссылка, а не копия (правило 153).

Разбор правила живёт в каталоге, и мы на него ССЫЛАЕМСЯ. Переписанный к себе,
он расходится с источником при первой же правке каталога — и расходится молча:
копия выглядит прежней, а правило под ней уже другое.

ЦИТАТА НЕ ЗАПРЕЩЕНА — ЗАПРЕЩЕНА КОПИЯ БЕЗ АДРЕСА. Привести чужие слова, чтобы
довод читался на месте, законно; правило требует, чтобы читатель мог дойти до
источника.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import ROOT, RunScript, load_script, walk

module = load_script("check_foreign_why.py")

#: Разбор правила, длиннее окна: короче — совпадут обороты речи, а не
#: заимствование.
CLAIM = (
    "чужое почему приводится ссылкой на источник а не переписывается к себе "
    "потому что копия расходится с оригиналом молча"
)


def tree(root: Path, text: str) -> Path:
    """Дерево под git с одним документом: гейт читает отслеживаемое."""
    subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=root, check=True)
    (root / "документ.md").write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    return root


def catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подделывает выгрузку каталога: сеть в наборе не трогается."""
    monkeypatch.setattr(module, "claims", lambda: {"153": CLAIM})


def test_pieces_are_counted_by_words_not_by_letters() -> None:
    """Куски режутся ПО СЛОВАМ: перенос строки и лишний пробел — оформление.

    Разбор, чувствительный к вёрстке, ловил бы её вместо заимствования: тот же
    текст, перенесённый иначе, переставал бы считаться копией.
    """
    ровно = " ".join(str(at) for at in range(module.WINDOW))
    врозь = "\n".join(str(at) for at in range(module.WINDOW))
    assert module.pieces(ровно) == module.pieces(врозь)
    assert len(module.pieces(ровно)) == 1
    assert module.pieces("коротко") == set(), "кусок короче окна куском не считается"


def test_two_addresses_without_a_space_do_not_swallow_the_prose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Адрес кончается там, где его заканчивает разметка, а не пробел.

    Жадное `\\S+` съело бы всё до следующего пробела: две ссылки подряд без
    разделителя вычистились бы вместе с прозой между ними, и гейт молча
    перестал бы видеть там копию. В дереве такого пока нет — находка названа
    риском, а не дефектом (внешний взгляд на #318), и класс закрыт до первого
    случая (051).
    """
    подряд = "[а](https://example.com/один)[б](https://example.com/два)"
    assert module.ADDRESS_RE.sub(" ", подряд).split() == ["[а](", ")[б](", ")"], (
        "между двумя адресами осталась разметка, а не пустота: проза уцелела бы тоже"
    )
    слова = f"начало {подряд} конец"
    assert "начало" in module.ADDRESS_RE.sub(" ", слова)
    assert "конец" in module.ADDRESS_RE.sub(" ", слова)


def test_an_address_is_not_words(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Адрес ссылки словами не считается: иначе два документа, ссылающиеся на
    одно правило, выглядели бы копиями друг друга.

    Замер 13.09.2026: из 2592 кусков `AGENTS.md` 343 — разобранная по словам
    ссылка. В разборах каталога ссылок нет, так что вреда пока не было; класс
    закрыт заранее (051).
    """
    адрес = (
        "https://github.com/ArtVsMark/Engineering-Incidents-Playbook"
        "/blob/main/rules/ru/153-foreign-why-is-a-link-not-a-copy.md"
    )
    assert module.pieces(адрес) == set()
    monkeypatch.setattr(module, "claims", lambda: {"153": адрес + " " + адрес})
    root = tree(tmp_path, f"см. {адрес}\n")
    assert module.main(["--root", str(root)]) == module.EXIT_OK


def test_a_claim_of_the_wrong_shape_does_not_crash_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Отклонение формы в чужой выгрузке — не четвёртый исход.

    `claim` приходит из каталога, и «(… or {}).get» бросал AttributeError на
    любом не-словаре: гейт падал трассировкой мимо всех трёх объявленных
    исходов (039). Правило с негодной формой пропускается вместе со своим
    разбором и не роняет разбор остальных — нашёл внешний взгляд на #315.
    """
    кривая = {
        "rules": [
            {"id": "153", "claim": "строка вместо словаря"},
            {"id": "154", "claim": {"ru": ["список вместо строки"]}},
            {"id": "155", "claim": {"ru": "настоящий разбор правила"}},
            {"id": "156"},
            "вовсе не словарь",
        ]
    }
    monkeypatch.setattr(module.catalogue.ghrest, "raw_json", lambda url: кривая)
    assert module.claims() == {"155": "настоящий разбор правила"}


def test_an_export_without_a_single_claim_is_the_third_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Выгрузка, где ни одной годной формы, — «не отработал», а не «чисто»."""
    monkeypatch.setattr(module.catalogue.ghrest, "raw_json", lambda url: {"rules": [{"id": "153"}]})
    with pytest.raises(module.NotRun, match="ни одного разбора"):
        module.claims()


def test_a_silent_catalogue_is_its_own_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Каталог не ответил — свой исход, не красный и не зелёный.

    Предмет этого гейта лежит в ЧУЖОЙ выгрузке. Молчание канала говорит о сети,
    а не о нашем дереве, и держать слияние оно не вправе (084). Зелёное здесь
    было бы молчаливым отключением гейта (045). Разбор — решение `027`.
    """

    def broken(*_: object, **__: object) -> object:
        raise module.catalogue.ghrest.TransportError("нет сети")

    monkeypatch.setattr(module.catalogue.ghrest, "raw_json", broken)
    assert module.main([]) == module.EXIT_SILENT
    assert module.EXIT_SILENT not in (module.EXIT_OK, module.EXIT_FOUND, module.EXIT_BROKEN)


def test_the_silent_outcome_names_the_channel(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Исход канала НАЗЫВАЕТ причину и адрес: молчание — не состояние (154)."""

    def broken(*_: object, **__: object) -> object:
        raise module.catalogue.ghrest.TransportError("нет сети")

    monkeypatch.setattr(module.catalogue.ghrest, "raw_json", broken)
    module.main([])
    said = capsys.readouterr()
    assert "каталог молчит" in said.out, "исход не назван читателю"
    assert "нет сети" in said.out, "причина отказа потеряна"
    assert not said.err, "отказ канала уехал в поток ошибок — он не поломка шага"


def test_a_file_in_another_encoding_is_named_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Не-UTF8 в дереве читается как «не прочитан», а не роняет гейт (039)."""
    catalogue(monkeypatch)
    root = tree(tmp_path, "обычный документ\n")
    (root / "чужая-кодировка.md").write_bytes("привет".encode("cp1251"))
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    assert module.main(["--root", str(root)]) == module.EXIT_BROKEN


def test_a_copy_is_seen_and_a_paraphrase_is_not() -> None:
    """Копия — дословный кусок; пересказ теми же словами врозь ею не является."""
    said = {"153": " ".join(f"слово{at}" for at in range(module.WINDOW + 2))}
    дословно = "вводные слова " + said["153"]
    assert module.copied(дословно, said) == {"153"}
    вразбивку = " и ".join(said["153"].split())
    assert module.copied(вразбивку, said) == set()


def test_a_link_is_read_by_its_address() -> None:
    """Ссылка узнаётся адресом файла правила, а не упоминанием номера.

    «Правило 153» в прозе адресом не является: по нему читатель никуда не
    дойдёт, а гейт ради этого и стоит.
    """
    адрес = (
        "https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/"
        "rules/ru/153-foreign-why-is-a-link-not-a-copy.md"
    )
    assert module.linked(f"см. [153]({адрес})") == {"153"}
    assert module.linked("см. правило 153") == set()


def test_a_copy_without_a_link_is_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Переписанный разбор без ссылки — находка, ради которой гейт и есть (140)."""
    catalogue(monkeypatch)
    root = tree(tmp_path, f"Мы считаем так: {CLAIM}.\n")
    assert module.main(["--root", str(root)]) == module.EXIT_FOUND
    assert "разбор правила 153 переписан" in capsys.readouterr().err


def test_a_quote_with_a_link_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Та же цитата со ссылкой на источник — не находка.

    Гейт судит не заимствование, а потерю адреса: читатель обязан дойти до
    правила, а не поверить нашему пересказу.
    """
    catalogue(monkeypatch)
    root = tree(
        tmp_path,
        f"Мы считаем так: {CLAIM} "
        "([153](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/"
        "rules/ru/153-foreign-why-is-a-link-not-a-copy.md)).\n",
    )
    assert module.main(["--root", str(root)]) == module.EXIT_OK
    assert "чисто" in capsys.readouterr().out


def test_a_short_echo_is_not_a_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Короткое совпадение оборотов копией не считается.

    Окно в десять слов выбрано замером: короче гейт ловил бы язык, а не
    заимствование, и приучал бы себя обходить
    ([051](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/051-warn-on-likely-block-on-certain.md)).
    """
    catalogue(monkeypatch)
    root = tree(tmp_path, "копия расходится с оригиналом молча — об этом и речь\n")
    assert module.main(["--root", str(root)]) == module.EXIT_OK


def test_a_silent_catalogue_is_the_third_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Каталог не ответил — «не отработал», а не «копий нет» (045)."""

    def refuse() -> dict[str, str]:
        raise module.NotRun("выгрузка каталога не прочитана: 503")

    monkeypatch.setattr(module, "claims", refuse)
    assert module.main([]) == module.EXIT_BROKEN
    assert "не отработал" in capsys.readouterr().err


def test_an_empty_export_is_not_a_clean_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустая выгрузка — ошибка входа: сверять не с чем (075)."""
    monkeypatch.setattr(module.catalogue.ghrest, "raw_json", lambda url: {"rules": []})
    with pytest.raises(module.NotRun, match="сверять не с чем"):
        module.claims()


def test_a_tree_without_documents_is_the_third_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Документов нет вовсе — предмета нет, и это отказ, а не «чисто» (075)."""
    catalogue(monkeypatch)
    subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=tmp_path, check=True)
    assert module.main(["--root", str(tmp_path)]) == module.EXIT_BROKEN
    assert "ни одного документа" in capsys.readouterr().err


def test_the_gate_runs_on_the_live_tree(run_script: RunScript) -> None:
    """Гейт объявлен в прогоне: механизм без шага остаётся обещанием (139).

    ИЩЕТСЯ ПО ВСЕМУ КАТАЛОГУ, А НЕ В `ci.yml`. Файл — АДРЕС шага, а не его
    личность, и адрес вправе меняться: вынос шага в переиспользуемый прогон
    сломал бы проверку, прибитую к одному имени, хотя шаг остался на месте
    ([168](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/168-one-aggregating-required-check.md)).
    Тот же приём уже применён у сверки обязательного контекста.
    """
    where = [
        path.name
        for path in walk(ROOT / ".github" / "workflows", "*.yml")
        if "check_foreign_why.py" in path.read_text(encoding="utf-8")
    ]
    assert where, "гейт не подключён ни к одному прогону"


def test_the_window_is_declared_not_guessed() -> None:
    """Окно — объявленное число, а не литерал посреди разбора (005)."""
    assert isinstance(module.WINDOW, int) and module.WINDOW >= 8


def test_the_catalogue_address_is_shared(monkeypatch: Any) -> None:
    """Адрес выгрузки берётся из общего объявления, а не пишется заново."""
    shared = load_script("catalogue.py")
    assert module.EXPORT_URL is shared.EXPORT_URL


def test_a_new_document_not_yet_in_the_index_is_judged(tmp_path: Path) -> None:
    """Перечень и чтение берут ОДНО дерево — то, что окно отправит.

    Перечень шёл по индексу, а текст читался с диска: новый документ не судился
    вовсе, хотя уедет вместе с остальными, а правленный после внесения судился
    по правке. Два дерева в одном ответе расходятся молча
    ([045](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/045-no-silent-fallback.md)).
    Нашёл внешний взгляд (`63c5843`).

    ВЫРОВНЕНО В СТОРОНУ ДИСКА, потому что гейт советует окну ПЕРЕД толчком.
    У соседа с договором «предскажи площадку» выровнено наоборот, и это сказано
    там же (`tests/test_type_leniency.py::carried_text`).
    """
    subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "внесён.md").write_text("внесённый\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "новый.md").write_text("ещё не внесён\n", encoding="utf-8")

    found = {path.name for path in module.documents(tmp_path)}
    assert "новый.md" in found, (
        "новый документ не судится: перечень идёт по индексу, а уедет он вместе"
        f" с остальными — видно только {sorted(found)}"
    )
    assert "внесён.md" in found, "внесённый документ выпал из перечня"
