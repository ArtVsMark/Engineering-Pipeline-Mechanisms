"""Форма раздела `shipped:` ответа проекта: где вход и каким маркером объявляют отданное (#1625).

Разбор уже прочитанного значения раздела, а не файла: YAML ответа читает один
модуль, `pipeline_checks` (090). Гейт входа — `check_shipped`; здесь только
форма, чтобы сверка ответа судила раздел, не зовя гейт.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import paths


class NotRun(RuntimeError):
    """Раздел не той формы: отказ с причиной, а не молчаливое умолчание (045)."""


#: Маркер объявления: им инструмент говорит «меня берут наружу». Прописными —
#: чтобы не совпасть с прозой о передаче, которой в дереве хватает.
MARK: Final = "ОТДАЁТСЯ НАРУЖУ"

#: Раздел ответа проекта, которым потребитель называет СВОЙ вход и маркер (#1625).
SECTION: Final = "shipped"


@dataclass(frozen=True)
class Form:
    """Где вход называет отданное и чем отданное себя объявляет."""

    entry: Path
    marker: str


#: Наша форма: вход — `README.md`, маркер — «ОТДАЁТСЯ НАРУЖУ».
DEFAULT_FORM: Final = Form(paths.ENTRANCE, MARK)


def form_of(section: Any) -> Form:
    """Форма из раздела `shipped:`; раздела нет (`None`) — наша.

    ВХОД И МАРКЕР — НАПОЛНЕНИЕ, А НЕ УСТРОЙСТВО (#1625). У каталога вход —
    `CONNECT.md`, маркер — «ОТДАЁТСЯ ПОТРЕБИТЕЛЮ», и держит их его свой гейт:
    наш, ища другой файл и другой маркер, видел пустоту там, где отдаётся не
    ноль. Устройство общее — инструмент объявляет себя в шапке, вход его
    называет; где вход и каким словом объявляют — решает проект, как форму
    фрагмента журнала (#1570). Отказ разбора — `NotRun` с причиной, а не
    молчаливое умолчание (045).
    """
    if section is None:
        return DEFAULT_FORM
    if not isinstance(section, dict):
        raise NotRun(f"раздел {SECTION}: ожидалось отображение, пришло {type(section).__name__}")
    unknown = sorted(str(key) for key in set(section) - {"entry", "marker"})
    if unknown:
        raise NotRun(
            f"раздел {SECTION}: незнакомые ключи {', '.join(unknown)} — читаются entry и marker"
        )
    entry = section.get("entry", DEFAULT_FORM.entry.as_posix())
    if not isinstance(entry, str) or not entry.strip():
        raise NotRun(f"раздел {SECTION}: entry — непустой путь строкой")
    where = Path(entry.strip())
    if where.is_absolute() or ".." in where.parts:
        raise NotRun(f"раздел {SECTION}: entry «{entry}» вне дерева — путь от корня без `..`")
    marker = section.get("marker", DEFAULT_FORM.marker)
    if not isinstance(marker, str) or not marker.strip():
        raise NotRun(f"раздел {SECTION}: marker — непустая строка")
    return Form(where, marker.strip())
