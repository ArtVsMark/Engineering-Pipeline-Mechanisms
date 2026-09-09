"""Состав меток: одно чтение файла на все механизмы.

Метка — вход механизма
([064](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/064-labels-are-machine-input-not-decoration.md)),
и её состав читают трое: синхронизатор приводит к нему площадку, гейт разметки
сверяет с ним изменение, шаг открытия проставляет по нему зоны.

Читали они его **по-разному**: синхронизатор с проверкой цвета и описания, гейт
без неё и в другом представлении, а шаг открытия не читал вовсе — и открывал
изменение, которое гейт тут же отвергал за отсутствие меток. Это тот же дрейф,
что и пять копий транспорта, только на данных: один файл, три понимания.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import paths
import yaml

DEFAULT_PATH: Final = paths.LABELS
COLOR_RE: Final = re.compile(r"^[0-9a-fA-F]{6}$")
ZONE_PREFIX: Final = "area/"


class BadConfig(RuntimeError):
    """Состав меток не разбирается или не проходит проверку.

    Это ошибка входа, а не пустой результат: механизм, не нашедший предмета
    проверки, обязан падать
    ([075](https://github.com/ArtVsMark/Engineering-Incidents-Playbook/blob/main/rules/ru/075-a-guard-that-finds-nothing-must-fail.md)).
    """


@dataclass(frozen=True, slots=True)
class Label:
    """Объявленная метка: имя, цвет, описание и пути зоны."""

    name: str
    color: str
    description: str
    paths: tuple[str, ...] = ()

    @property
    def is_zone(self) -> bool:
        """Зона ли это — по приставке имени."""
        return self.name.startswith(ZONE_PREFIX)


def load(path: Path = DEFAULT_PATH) -> list[Label]:
    """Читает состав меток, отвергая любой дефект входа."""
    if not path.is_file():
        raise BadConfig(f"состав меток не найден: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BadConfig(f"состав меток не разбирается: {exc}") from exc

    if not isinstance(raw, list) or not raw:
        raise BadConfig(f"состав меток пуст: {path} — это ошибка входа, а не «чисто»")

    labels: list[Label] = []
    problems: list[str] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            problems.append(f"запись {index}: не отображение")
            continue
        name = str(item.get("name", "")).strip()
        color = str(item.get("color", "")).strip().lstrip("#")
        description = str(item.get("description", "")).strip()
        paths = item.get("paths", []) or []
        if not name:
            problems.append(f"запись {index}: пустое имя")
        if not COLOR_RE.match(color):
            problems.append(f"{name or index}: цвет «{color}» не шесть шестнадцатеричных цифр")
        if not description:
            problems.append(f"{name or index}: пустое описание — метка без описания нечитаема")
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            problems.append(f"{name or index}: paths — не список строк")
            paths = []
        if not problems:
            labels.append(Label(name, color, description, tuple(paths)))

    if problems:
        raise BadConfig("состав меток не проходит проверку:\n  " + "\n  ".join(problems))

    names = [label.name for label in labels]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise BadConfig(f"имя метки объявлено дважды: {', '.join(duplicates)}")

    return labels


def zones_for(labels: list[Label], files: list[str]) -> set[str]:
    """Выводит зоны изменения из тронутых файлов по объявленным путям.

    Зона без путей не выводится: её механизмов ещё нет, и она ставится
    человеком при разборе. Считать такое изменение размеченным нельзя, поэтому
    хотя бы одна зона обязана стоять всегда — это проверяет гейт разметки.
    """
    zones: set[str] = set()
    for label in labels:
        if not label.is_zone or not label.paths:
            continue
        if any(fnmatch.fnmatch(path, pattern) for pattern in label.paths for path in files):
            zones.add(label.name)
    return zones
