"""Шаг, который принимает решение, говорит о нём не только в лог.

ЧТО ЗДЕСЬ ПРЕДМЕТ. Лог прогона читается не из всякого окна: облачному
хранилище закрыто, и от захода остаётся код возврата, по которому не
разобрать ничего. Шаг, чей вывод — РАЗБОР (почему голова пропущена, кто
взведён, что признано пустым), обязан сказать его туда, откуда его достанет
REST.

ДОСТАЁТ ИМЕННО АННОТАЦИЮ, И ЭТО ЗАМЕР, А НЕ ДОГАДКА. 13.09.2026 у джоба
`ci-complete` на изменении #290 REST отдаёт `annotations_count: 1`, а
`output.summary` — пустую строку. Сводка джоба остаётся для человека в окне
площадки; наружу говорит аннотация. Механизм, поставленный на сводку, читался
бы как работающий и не давал бы ничего (044).

ПОЧЕМУ ЭТО ГЕЙТ, А НЕ ПРИВЫЧКА. 13.09.2026 починку пустой головы нечем было
подтвердить: механизм отработал, а показать это было нечем — очередь свой
разбор в сводку не писала (#287). Правило прямое: механизм подтверждается
прогоном
([139](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/139-a-mechanism-is-confirmed-by-a-run.md)),
а подтвердить нечем, если прогон молчит наружу.

Список разрешительный
([068](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/068-allowlist-not-denylist.md)):
шаг попадает сюда осознанно. Сводку пишет не всякий — гейту довольно кода и
аннотации; здесь только те, чей вывод разбирают задним числом.
"""

from __future__ import annotations

import re
from typing import Final

import pytest

from tests.conftest import ROOT

#: Прогоны, чей вывод — разбор решения, а не отметка «прошло».
SPEAKS_OUT: Final = ("automerge.yml", "ci-complete.yml")

SUMMARY: Final = "GITHUB_STEP_SUMMARY"

#: Экранирование переводов строк для аннотации. Без него площадка обрежет
#: сообщение первым же переводом, и разбор снаружи станет одной строкой.
ESCAPED: Final = "%0A"


@pytest.mark.parametrize("run", SPEAKS_OUT)
def test_a_deciding_step_speaks_through_an_annotation(run: str) -> None:
    """Разбор уходит АННОТАЦИЕЙ — единственным, что отдаёт REST наружу."""
    text = (ROOT / ".github" / "workflows" / run).read_text(encoding="utf-8")
    assert "::notice::" in text or "::error::" in text, (
        f"{run} печатает разбор только в лог и сводку: из окна, которому закрыто "
        "хранилище прогонов, от захода останется один код возврата"
    )
    assert ESCAPED in text, (
        f"{run} шлёт аннотацию без экранирования переводов строк — площадка обрежет "
        "разбор первой же строкой"
    )


@pytest.mark.parametrize("run", SPEAKS_OUT)
def test_a_deciding_step_also_fills_the_summary(run: str) -> None:
    """Сводка джоба остаётся: она для человека в окне площадки."""
    text = (ROOT / ".github" / "workflows" / run).read_text(encoding="utf-8")
    assert SUMMARY in text, f"{run} не заполняет сводку джоба"


@pytest.mark.parametrize("run", SPEAKS_OUT)
def test_the_log_keeps_the_output_too(run: str) -> None:
    """Перенаправление в файл не уносит вывод из лога: `cat` возвращает его.

    Иначе сводка появляется ценой лога, и тот, у кого лог есть, теряет вывод.
    """
    text = (ROOT / ".github" / "workflows" / run).read_text(encoding="utf-8")
    assert "cat " in text, f"{run} увёл вывод в файл и не вернул его в лог"


@pytest.mark.parametrize("run", SPEAKS_OUT)
def test_the_summary_body_cannot_be_broken_by_its_own_text(run: str) -> None:
    """Тело сводки подаётся отступом, а не забором из кавычек.

    В вывод попадают заголовки изменений и тексты отказов, а их пишет человек:
    три кавычки подряд закрывают забор раньше времени, и остаток разбора
    разъезжается по разметке. Отступ ломать нечем. Нашли внешние взгляды на
    #292.
    """
    text = (ROOT / ".github" / "workflows" / run).read_text(encoding="utf-8")
    assert "echo '```'" not in text, (
        f"{run} заворачивает тело сводки в забор из кавычек: текст из заголовка "
        "изменения закроет его раньше времени"
    )
    assert "sed 's/^/    /'" in text, f"{run} не подаёт тело сводки отступом"


#: Аннотация прогона: строка, которую площадка отдаёт по REST.
ANNOTATES: Final = re.compile(r'^\s*echo\s+"::(?:error|warning)::(?P<said>.*)"\s*$')

#: Тупик вместо причины. Строка названа дословно, потому что она и есть предмет:
#: «смотрите вывод» отправляет читателя туда, куда часть окон не смотрит вовсе.
DEAD_END: Final = ("смотрите вывод", "смотрите лог", "см. вывод")

#: Чем причина попадает в аннотацию: подстановкой оболочки.
CARRIES: Final = ("${reason}", "$(tr", "${said}")

#: Сколько текста обязано идти ПОСЛЕ кода. Мера именно такая, а не «длина
#: сообщения»: описание того, ЧТО упало, стоит в сообщении всегда — оно есть и у
#: негодного «Шаг разбора красноты не отработал (код 2).». Отличает годное от
#: негодного то, продолжается ли сообщение за кодом: там живёт следствие («взгляд
#: пойдёт без неё», «покрытие будет объявлено непрочитанным»). Первая редакция
#: мерила длину целиком, ничего не отвергала и была гейтом без предмета (075).
AFTER_THE_CODE: Final = 20

#: Сам код в сообщении — по нему и режут.
THE_CODE: Final = re.compile(r"\(код \$\{?rc\}?\)")


def annotated() -> list[tuple[str, int, str]]:
    """Все аннотации прогонов дерева: файл, строка, текст."""
    found: list[tuple[str, int, str]] = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            said = ANNOTATES.match(line)
            if said:
                found.append((path.name, number, said["said"]))
    return found


def test_the_tree_has_annotations_to_look_at() -> None:
    """Аннотации найдены: без них проверки ниже — поверхность без предмета (075)."""
    assert len(annotated()) >= 10, (
        f"аннотаций найдено {len(annotated())} — разбор не видит прогонов"
    )


@pytest.mark.parametrize(
    "said",
    annotated(),
    ids=lambda one: f"{one[0]}:{one[1]}" if isinstance(one, tuple) else str(one),
)
def test_an_annotation_never_sends_the_reader_to_the_log(said: tuple[str, int, str]) -> None:
    """Аннотация не отправляет читателя в лог, а несёт причину сама.

    ЗАМЕР 16.09.2026. Заход дежурного по общей ветке упал кодом 2 в 10:42:42 на
    ТОЙ ЖЕ голове, где заход 10:42:11 прошёл, — и причина осталась неизвестной:
    аннотация несла «смотрите вывод выше», а лог прогона из облачного окна не
    читается вовсе. Разбор красного механизма превратился в угадывание (142).

    Дефект оказался КЛАССОМ, а не случаем: тот же тупик стоял в шести шагах —
    открытие изменения, очередь, синхронизация меток, два шага разбора задач и
    сам дежурный. Починка по одному найденному случаю оставила бы пять.
    """
    name, number, text = said
    dead = [one for one in DEAD_END if one in text]
    assert not dead, (
        f"{name}:{number}: аннотация отправляет в лог ({dead[0]}) вместо того, чтобы "
        "нести причину — из части окон лог не читается (142)"
    )


@pytest.mark.parametrize(
    "said",
    annotated(),
    ids=lambda one: f"{one[0]}:{one[1]}" if isinstance(one, tuple) else str(one),
)
def test_an_annotation_naming_a_code_also_names_the_reason(said: tuple[str, int, str]) -> None:
    """Аннотация, называющая КОД возврата, называет причину ИЛИ следствие.

    Номер кода сам по себе ничего не говорит: «не отработал (код 2)» снаружи
    неотличимо от такого же отказа по любой другой причине.

    ГОДНЫХ ОТВЕТОВ ДВА, и второй не хуже первого. Причина — вывод шага,
    попавший в аннотацию подстановкой. Следствие — что теперь будет («карта не
    собрана: взгляд пойдёт без неё», «покрытие будет объявлено непрочитанным»).
    Требовать только причину значило бы красить четыре исправных сообщения
    дерева (051, 068).
    """
    name, number, text = said
    if "код $rc" not in text and "код ${rc}" not in text:
        pytest.skip("аннотация не про код возврата")
    if any(one in text for one in CARRIES):
        return
    tail = THE_CODE.split(text, maxsplit=1)[-1].strip(" .—:-")
    assert len(tail) >= AFTER_THE_CODE, (
        f"{name}:{number}: за кодом не сказано ничего — снаружи такое сообщение "
        f"неотличимо от любого другого отказа того же шага. Нужна ПРИЧИНА "
        f"(подстановка с выводом шага) или СЛЕДСТВИЕ словами"
    )
