"""Что лежит в дереве под учётом — и чего там лежать не должно.

Порождённое учётом не ведут: файл, который собирается из источника, второй
раз хранить негде, и хранимая копия расходится с источником молча
([125](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/125-a-generated-file-is-not-a-store.md)).

ЗАЧЕМ ГЕЙТ, ЕСЛИ ЕСТЬ `.gitignore`. Список игнора действует на НЕОТСЛЕЖИВАЕМОЕ:
файл, однажды взятый под учёт, он не отпускает. То есть запись в нём выглядит
защитой и ею не является — ровно тот случай, когда правило есть, а механизма
под ним нет
([002](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/002-rule-without-mechanism.md)).

ЗАМЕР 15.09.2026. Перенос общего низа в пакет притащил под учёт четыре файла
`*.egg-info/`, порождённых установкой: `PKG-INFO`, `SOURCES.txt`,
`dependency_links.txt`, `top_level.txt`. Строка `*.egg-info/` в `.gitignore`
при этом стояла и молчала. Нашёл внешний взгляд — дважды, находками `47cc3e2`
и `559cfa0` на #367, и оба раза механизм ничего не сказал.
"""

from __future__ import annotations

import subprocess

from tests.conftest import ROOT


def tracked_but_ignored() -> list[str]:
    """Пути под учётом, которые дерево само объявило игнорируемыми.

    Список читается по NUL (165): имя с пробелом или кириллицей git иначе
    экранирует, путь не разрешается, и файл выпадает из проверки молча.
    """
    done = subprocess.run(
        ["git", "ls-files", "-z", "-i", "-c", "--exclude-standard"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=True,
    )
    return [one for one in done.stdout.split("\0") if one]


def test_nothing_ignored_is_also_tracked() -> None:
    """Файл не бывает одновременно под учётом и в списке игнора.

    Это ПРОТИВОРЕЧИЕ дерева самому себе, а не мелочь оформления: запись в
    `.gitignore` объявляет файл порождённым, учёт — хранимым, и второе молча
    отменяет первое. Дальше он живёт в истории, приезжает в каждое изменение
    шумом и расходится с тем, из чего порождён (125, 045).
    """
    found = tracked_but_ignored()
    assert not found, (
        "под учётом лежит игнорируемое — снять командой `git rm -r --cached <путь>`: "
        + ", ".join(found)
    )


def test_the_gate_has_a_subject_to_look_at() -> None:
    """Проверка обращается к настоящему дереву, а не к пустоте (075).

    Ноль путей — законный ответ ТОЛЬКО если git вообще ответил про это дерево.
    Гейт, молчащий потому, что не нашёл репозитория, читался бы как «чисто».
    """
    done = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        check=True,
    )
    assert [one for one in done.stdout.split("\0") if one], "git не видит дерева проекта"
