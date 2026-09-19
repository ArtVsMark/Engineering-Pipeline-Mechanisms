"""Канал обратной связи от потребителя: три двери, и каждая объявлена.

Без обратного канала общий модуль слепнет: он узнаёт о своих пробелах
последним, а потребитель молча обходит его и возвращается к своей копии — то
есть к тому дрейфу, ради которого всё и затевалось (#14).

ТРИ ВИДА, И ПУТАТЬ ИХ НЕЛЬЗЯ: у них разные адресаты, разная срочность и разный
исход. Затор — тревога с адресатом-человеком
([142](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/142-a-scheduled-red-needs-an-addressee.md));
пробел — гипотеза до третьего случая
([093](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/093-seam-early-generalisation-late.md));
расхождение — объявленный обход
([154](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/154-none-must-name-its-reason.md)).

ЧТО ЗДЕСЬ ДЕРЖИТСЯ, А ЧТО НЕТ. Держится СООТВЕТСТВИЕ: дверей столько же,
сколько объявленных меток канала, и каждая дверь спрашивает адрес обратившегося.
Не держится качество обращения — это суждение о смысле, и машине оно недоступно
([057](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/057-unmechanizable-rules-are-named-explicitly.md)).
"""

from __future__ import annotations

from typing import Any, Final

import pytest
import yaml

from tests.conftest import ROOT, walk

TEMPLATES: Final = ROOT / ".github" / "ISSUE_TEMPLATE"
LABELS: Final = ROOT / ".github" / "labels.yml"
#: Приставка метки канала. Метку ставит ШАБЛОН, а не рука: поставленная рукой
#: она означает «кто-то вспомнил», а не «пришло этим каналом».
MARK: Final = "consumer/"
#: Без чего обращение не отработать: адрес обратившегося. След — это адрес в
#: чужом дереве, а не копия чужого разбора
#: ([185](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/185-a-trail-is-an-address-and-its-owner-keeps-it-alive.md)).
WHO: Final = "repo"


def doors() -> dict[str, dict[str, Any]]:
    """Двери канала: имя файла → разобранный шаблон обращения."""
    return {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in walk(TEMPLATES, "*.yml")
    }


def declared() -> set[str]:
    """Метки канала, объявленные составом."""
    said = yaml.safe_load(LABELS.read_text(encoding="utf-8")) or []
    return {str(one["name"]) for one in said if str(one.get("name", "")).startswith(MARK)}


def fields_of(door: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Поля шаблона по их идентификаторам — без пояснительных блоков."""
    return {str(one["id"]): one for one in door.get("body") or [] if one.get("id")}


def test_the_channel_has_doors() -> None:
    """Двери в дереве есть: канал без дверей — обещание, а не канал (075)."""
    assert doors(), "шаблонов обращения нет ни одного — потребителю некуда прийти"


@pytest.mark.parametrize("name", sorted(doors()), ids=lambda one: one)
def test_every_door_declares_its_label(name: str) -> None:
    """Дверь ставит метку канала САМА, и метка объявлена составом.

    Метка, поставленная рукой, означает «кто-то вспомнил», а не «пришло этим
    каналом»: свести такие обращения нечем. Метка, не объявленная в составе,
    заводится площадкой на лету и живёт без описания
    ([064](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/064-labels-are-machine-input-not-decoration.md)).
    """
    marks = {one for one in doors()[name].get("labels") or [] if str(one).startswith(MARK)}
    assert len(marks) == 1, f"{name}: дверь обязана ставить ровно одну метку канала, стоит {marks}"
    assert marks <= declared(), f"{name}: метка {marks} не объявлена в .github/labels.yml"


def test_the_doors_and_the_labels_correspond() -> None:
    """Дверей столько же, сколько меток канала, — соответствие в обе стороны.

    Метка без двери — канал, которым не прийти: снаружи он неотличим от
    работающего. Дверь без метки — обращение, которое ничем не свести.
    Обе половины проверяются разом, потому что разъезжаются они молча
    ([022](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/022-one-canonical-document.md)).
    """
    used = {
        str(one)
        for door in doors().values()
        for one in door.get("labels") or []
        if str(one).startswith(MARK)
    }
    assert used == declared(), (
        f"двери ставят {sorted(used)}, а состав объявляет {sorted(declared())} — "
        "метка без двери или дверь без метки"
    )


@pytest.mark.parametrize("name", sorted(doors()), ids=lambda one: one)
def test_every_door_asks_who_is_calling(name: str) -> None:
    """Дверь спрашивает АДРЕС обратившегося, и спрашивает обязательным полем.

    Без адреса обращение не отработать: ответить некуда, перемерить нечем, а
    след в чужом дереве — это адрес, а не копия разбора (185). Необязательное
    поле здесь не годится: пустое оно неотличимо от незаданного.
    """
    said = fields_of(doors()[name])
    assert WHO in said, f"{name}: дверь не спрашивает, чей это проект"
    assert (said[WHO].get("validations") or {}).get("required"), (
        f"{name}: адрес обратившегося необязателен — пустой он неотличим от незаданного"
    )


def test_the_jam_is_marked_as_an_alarm() -> None:
    """У затора метка тревоги, а не только метка канала.

    Затор — не место в бэклоге: конвейер встал, работа стоит, и ждать разбора
    она не будет. Адресат у такого красного — человек (142).
    """
    jams = [
        name
        for name, door in doors().items()
        if f"{MARK}jam" in [str(one) for one in door.get("labels") or []]
    ]
    assert len(jams) == 1, f"дверей затора должно быть ровно одна, есть: {jams}"
    labels = [str(one) for one in doors()[jams[0]].get("labels") or []]
    assert "blocker" in labels, f"{jams[0]}: затор не помечен как держащий работу"


def test_the_jam_asks_the_version_it_stands_on() -> None:
    """Затор спрашивает версию, на которой стоит потребитель.

    Без неё неизвестно, о каком коде речь: у нас на общей ветке он давно
    другой, и разбирать пришлось бы не то, что у него (157).
    """
    said = fields_of(next(door for name, door in doors().items() if "jam" in name))
    assert "pin" in said and (said["pin"].get("validations") or {}).get("required"), (
        "дверь затора не спрашивает версию обязательным полем"
    )
