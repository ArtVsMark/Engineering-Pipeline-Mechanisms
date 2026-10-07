"""Повторённый ключ YAML — отказ, а не молчаливая победа последнего (взгляд на #1183).

PyYAML на повторённом ключе молча оставляет последний. Так общий шаг фактов
`step-facts.yml` пришёл на изменение с двумя `inputs:` под `workflow_call`:
второй блок затёр первый, входы, которые передаёт вызывающий, пропали, а
гейты прогонов — все читают YAML тем же PyYAML — остались зелёными. Площадка
такой файл либо не примет, либо прочтёт иначе, чем набор.

Замер 07.10.2026 по дереву: файлов YAML под `.github/` и `.pipeline.yml` —
48, с повторённым ключом — ровно этот один. Гейт читает их загрузчиком,
который на повторе отказывает, и называет файл и строку.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import ROOT, walk_deep


# У PyYAML нет заглушек типов: базовый класс для mypy — Any.
class Strict(yaml.SafeLoader):  # type: ignore[misc]
    """Загрузчик, отказывающий на повторённом ключе отображения."""


def unique_mapping(loader: Strict, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    """Отображение без повторов: второй такой же ключ — отказ с местом."""
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"ключ {key!r} повторён", key_node.start_mark
            )
        seen.add(key)
    said: dict[Any, Any] = yaml.SafeLoader.construct_mapping(loader, node, deep)
    return said


Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def documents() -> list[Path]:
    """Файлы YAML, которые читают площадка и гейты: всё под `.github/` и ответ по классам."""
    found = walk_deep(ROOT / ".github", "*.yml") + walk_deep(
        ROOT / ".github",
        "*.yaml",
        may_be_empty="прогоны пишутся с .yml; .yaml законен, но не обязан быть",
    )
    return sorted([*found, ROOT / ".pipeline.yml"])


def test_the_subject_exists() -> None:
    """Предмет гейта есть: без файлов он доказывал бы только себя (075)."""
    assert len(documents()) > 1


@pytest.mark.parametrize("path", documents(), ids=lambda one: one.relative_to(ROOT).as_posix())
def test_no_key_is_repeated(path: Path) -> None:
    """Ни в одном файле YAML ключ не повторён на одном уровне."""
    yaml.load(path.read_text(encoding="utf-8"), Loader=Strict)


@pytest.mark.parametrize(
    ("text", "repeated"),
    [
        ("on:\n  workflow_call:\n    inputs:\n      a: 1\n    inputs:\n      b: 2\n", True),
        ("on:\n  workflow_call:\n    inputs:\n      a: 1\n      b: 2\n", False),
        ("a:\n  x: 1\nb:\n  x: 2\n", False),
    ],
    ids=["повтор на одном уровне", "без повтора", "один ключ на разных уровнях"],
)
def test_the_loader_tells_a_repeat_from_a_neighbour(text: str, repeated: bool) -> None:
    """Обе половины: повтор на одном уровне — отказ, тот же ключ у соседей — нет."""
    if repeated:
        with pytest.raises(yaml.constructor.ConstructorError, match="повторён"):
            yaml.load(text, Loader=Strict)
    else:
        yaml.load(text, Loader=Strict)
