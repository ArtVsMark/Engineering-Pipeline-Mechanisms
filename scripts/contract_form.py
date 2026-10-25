"""Форма раздела `contract-surface:`: что поверхность проекта и каким родом её правку зовут (#1664).

Разбор уже прочитанного значения раздела, а не файла: YAML ответа читает один
модуль, `pipeline_checks` (090), — тем же приёмом, что `shipped_form`. Гейт —
`check_contract`; здесь только форма, чтобы сверка ответа судила раздел, не
зовя гейт.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import journal


class NotRun(RuntimeError):
    """Раздел не той формы: отказ с причиной, а не молчаливое умолчание (045)."""


#: Раздел ответа проекта. Не `contract:` — тот ключ занят окном версий контракта.
SECTION: Final = "contract-surface"
#: Род фрагмента, которым правка поверхности объявляется по умолчанию.
DEFAULT_KIND: Final = "contract"


@dataclass(frozen=True)
class Form:
    """Объявленная поверхность и род фрагмента; пустой `surface` — наша поверхность."""

    surface: tuple[Path, ...]
    kind: str


#: Наша форма: поверхность — прогоны, классы проверок и ключи путей; род `contract`.
DEFAULT_FORM: Final = Form((), DEFAULT_KIND)


def form_of(section: Any) -> Form:
    """Форма из раздела `contract-surface:`; раздела нет (`None`) — наша.

    ПОВЕРХНОСТЬ — НАПОЛНЕНИЕ, А НЕ УСТРОЙСТВО (#1664). У каталога наружу идут
    выгрузка и действия, а прогоны не зовёт никто: наш снимок прогонов краснел
    бы на каждой правке его `ci.yml`. Устройство общее — правка поверхности
    объявляется фрагментом; что поверхность и каким родом её называют, решает
    проект, как вход отданного (#1625). Род — из родов журнала (`journal.KINDS`):
    шаг `journal` потребителя другого не разберёт.
    """
    if section is None:
        return DEFAULT_FORM
    if not isinstance(section, dict):
        raise NotRun(f"раздел {SECTION}: ожидалось отображение, пришло {type(section).__name__}")
    unknown = sorted(str(key) for key in set(section) - {"surface", "kind"})
    if unknown:
        raise NotRun(
            f"раздел {SECTION}: незнакомые ключи {', '.join(unknown)} — читаются surface и kind"
        )
    raw = section.get("surface", [])
    if not isinstance(raw, list) or not raw:
        raise NotRun(f"раздел {SECTION}: surface — непустой список путей")
    surface: list[Path] = []
    for one in raw:
        if not isinstance(one, str) or not one.strip():
            raise NotRun(f"раздел {SECTION}: путь поверхности — непустая строка, пришло {one!r}")
        where = Path(one.strip())
        if where.is_absolute() or ".." in where.parts:
            raise NotRun(f"раздел {SECTION}: путь «{one}» вне дерева — путь от корня без `..`")
        if not where.parts:
            # `.` — всё дерево: в голове в обход попал бы `.git` и мусор, которого
            # нет в архиве базы (взгляд на #1672). Поверхность называется путями.
            raise NotRun(
                f"раздел {SECTION}: путь «{one}» — всё дерево, назовите файлы или каталоги"
            )
        surface.append(where)
    kind = section.get("kind", DEFAULT_KIND)
    if not isinstance(kind, str) or kind not in journal.KINDS:
        raise NotRun(
            f"раздел {SECTION}: род «{kind}» журналу неизвестен — один из "
            + ", ".join(journal.KINDS)
        )
    return Form(tuple(surface), str(kind))


def missing(form: Form, root: Path) -> list[str]:
    """Объявленные пути, которых в дереве нет: поверхность из несуществующего — молчание."""
    return [where.as_posix() for where in form.surface if not (root / where).exists()]
