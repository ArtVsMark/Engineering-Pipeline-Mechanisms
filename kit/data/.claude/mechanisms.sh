# Запускатель механизмов у потребителя (#1552): скрипт поставщика — против вашего дерева.
#
#   bash .claude/mechanisms.sh work_plan.py            # скрипт из scripts/ механизмов
#   bash .claude/mechanisms.sh finding_kinds.py --help
#
# КОД — ТОТ ЖЕ, ЧТО У ПЛОЩАДКИ. Поставщик и тег берутся из `uses:` ваших
# прогонов (`<владелец>/<репо>/.github/workflows/step-*.yml@vX.Y.Z`), механизмы
# этого тега выкачиваются один раз в кеш окна, и оттуда зовётся их скрипт из
# корня вашего дерева. Копий скриптов в вашем дереве нет: реализация на семью
# одна (090). Этим путём навыки окна зовут скрипты механизмов, а предполётная
# (`preflight.sh` рядом) — частный случай.
#
# Скрипту выставлены `MECHANISMS` — каталог выкачки, как в прогоне площадки, — и
# `MECHANISMS_SUPPLIER`. Предполётной заход передаёт корень, выкачку и
# поставщика ключами: она судит ваше дерево, а не выкачку.
#
# Исходы: код скрипта; 2 — запускатель не отработал (вызовов нет, вызовы
# расходятся, ссылка не тег, выкачка не удалась, такого скрипта нет).
# Интерпретатор — `PYTHON`; по умолчанию `python<планка>` из `.claude/hooks/floor.sh`,
# если он есть, иначе `python3`. Ему нужны планка механизмов и `pyyaml` — оба
# ставит хук старта (`install_floor.sh`, #1771).
set -euo pipefail

refuse() {
  echo "механизмы не запущены: $1" >&2
  exit 2
}

[ $# -ge 1 ] || refuse "не назван скрипт — bash .claude/mechanisms.sh <скрипт.py> [доводы]"
script=$1
shift
# Только имя файла из `scripts/` выкачки: путь с `/` или `..` вывел бы вызов из неё.
[[ $script =~ ^[A-Za-z0-9_]+\.py$ ]] || refuse "«$script» — не имя скрипта вида имя.py из scripts/ механизмов"

root=$(git rev-parse --show-toplevel) || refuse "не дерево git"
cd "$root"

# ИНТЕРПРЕТАТОР ПО УМОЛЧАНИЮ — ПЛАНКА, А НЕ ГОЛЫЙ python3 (#1771). Хук старта
# ставит `pyyaml` в `python<планка>`, а системный `python3` окна — ниже
# планки и без `yaml`. Число читается из `floor.sh` строкой, а не исполнением
# файла. Нет файла или интерпретатора — `python3`, как прежде.
if [ -z "${PYTHON:-}" ]; then
  want=$(sed -n 's/^want=\([0-9.]*\)$/\1/p' .claude/hooks/floor.sh 2>/dev/null | head -n 1)
  if [ -n "$want" ] && command -v "python$want" >/dev/null 2>&1; then
    PYTHON="python$want"
  else
    PYTHON=python3
  fi
fi

# Запись вызова — с кавычками или без: `uses: o/m/…@v1` и `uses: "o/m/…@v1"`.
# Берутся только ОБЩИЕ ШАГИ механизмов (`step-*.yml`) и только незакомментированные
# строки: чужой переиспользуемый прогон и старый `# uses:` поставщиком не
# считаются (взгляд на #1618).
calls=$(grep -rhE "^[[:space:]]*uses:" .github/workflows 2>/dev/null \
  | grep -oE "uses:[[:space:]]*[\"']?[^[:space:]/\"']+/[^[:space:]/]+/\.github/workflows/step-[^@[:space:]]+@[^[:space:]\"']+" \
  | sed -E "s/^uses:[[:space:]]*[\"']?([^/]+\/[^/]+)\/.*@(.*)$/\1 \2/" | sort -u || true)
[ -n "$calls" ] || refuse "в .github/workflows нет вызова общих шагов механизмов — тег взять неоткуда"
[ "$(printf '%s\n' "$calls" | wc -l)" -eq 1 ] \
  || refuse "прогоны зовут механизмы по разным ссылкам — сведите их к одному тегу: $(printf '%s' "$calls" | tr '\n' ';' | sed 's/;/; /g')"
supplier=${calls% *}
tag=${calls#* }
[[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] \
  || refuse "механизмы зовутся по «$tag», а не по закреплённому тегу vX.Y.Z — выкачка не повторила бы площадку"

cache="${XDG_CACHE_HOME:-$HOME/.cache}/mechanisms/${supplier//\//_}@$tag"
if [ ! -f "$cache/scripts/preflight.py" ]; then
  origin="${MECHANISMS_ORIGIN:-https://github.com}/$supplier.git"
  # ДЕДЛАЙН ВЫКАЧКИ (100). `timeout` есть в GNU coreutils, на macOS — только
  # `gtimeout` из coreutils Homebrew. Нет ни одного — отказ с причиной, а не
  # код 127, который читался бы «механизмы не выкачаны» (взгляд на #1618).
  if command -v timeout >/dev/null 2>&1; then
    deadline=timeout
  elif command -v gtimeout >/dev/null 2>&1; then
    deadline=gtimeout
  else
    refuse "нет ни timeout, ни gtimeout — выкачку нечем ограничить по времени; на macOS: brew install coreutils"
  fi
  # ОКОН-ПИСАТЕЛЕЙ МОЖЕТ БЫТЬ ДВА (066, взгляд на #1618): рабочие копии одного
  # окна делят кеш. Поэтому выкачка идёт в СВОЙ каталог (`.part.<pid>`), а на
  # место кеша встаёт ОДНИМ переименованием, которое на занятом месте
  # отказывает: первый побеждает, второй бросает свою копию. Готовый кеш не
  # стирается и не подменяется — подмены живой цели нет, и блокировать нечего.
  # Прежде здесь стояло `rm -rf "$cache"; mv`, и второй писатель между проверкой
  # и `mv` стирал кеш под скриптом первого (находка на #1626). `os.rename`, а не
  # `mv`: `mv` на занятый каталог кладёт копию ВНУТРЬ него. Отказ переноса —
  # код 1 без слов; интерпретатор, который не запускается, назван заранее, а
  # не читается «кеш неполон» (взгляд на #1640).
  # ОСТАТОК — недокачанный кеш без `preflight.py` — оставляют прежние
  # запускатели: писавший прямо в кеш и ставившие на место кеша выкачку без
  # проверки её состава (до #1642 — запускатели #1626 и #1640); нынешний кладёт
  # кеш одним переименованием проверенной копии. Остаток не уносится, а называется:
  # любой перенос каталога кеша мог бы унести готовый кеш соседа, ставший на
  # его место между проверкой и переносом (взгляды на #1640), — без переноса
  # гонке негде случиться. Стереть разовый остаток — одно действие человека.
  [ -d "$cache" ] && [ ! -f "$cache/scripts/preflight.py" ] \
    && refuse "кеш механизмов $cache неполон — остаток прежнего запускателя; удалите его, и следующий заход выкачает заново"
  "$PYTHON" -c '' 2>/dev/null \
    || refuse "интерпретатор $PYTHON не запускается — переносить кеш нечем"
  swap() {
    "$PYTHON" -c '
import os, sys
try:
    os.rename(sys.argv[1], sys.argv[2])
except OSError:
    sys.exit(1)' "$1" "$2"
  }
  part="$cache.part.$$"
  rm -rf "$part"
  "$deadline" 300 git -c advice.detachedHead=false clone -q --depth 1 --branch "$tag" "$origin" "$part" \
    || { rm -rf "$part"; refuse "механизмы $supplier@$tag не выкачаны из $origin"; }
  # Выкачка без `preflight.py` — не механизмы (ссылка `uses:` не на поставщика
  # или тег не того дерева): на место кеша она не встаёт, иначе следующий заход
  # назвал бы её «остатком прежнего запускателя» (взгляд на #1642).
  [ -f "$part/scripts/preflight.py" ] \
    || { rm -rf "$part"; refuse "в $supplier@$tag нет scripts/preflight.py — по тегу выкачаны не механизмы"; }
  swap "$part" "$cache" || rm -rf "$part"
  [ -f "$cache/scripts/preflight.py" ] \
    || refuse "кеш механизмов $cache не встал на место: перенос выкачки отказал"
fi
[ -f "$cache/scripts/$script" ] || refuse "в механизмах $supplier@$tag нет scripts/$script"
# ТАБЛИЦА ПУТЕЙ БЕЗ ТОЧКИ ВХОДА — ОТКАЗ, А НЕ ПУСТОЙ АДРЕС (взгляд на #1653).
# На теге старше #1653 у `paths.py` нет `__main__`: вызов выходит кодом 0 и
# ничего не печатает, и навык, положенный с новой версии, получил бы пустой
# адрес молча — `$EDITOR "$(…)"` открылся бы без файла.
if [ "$script" = paths.py ] && ! grep -q '__name__ == "__main__"' "$cache/scripts/paths.py"; then
  refuse "у scripts/paths.py в $supplier@$tag нет точки входа — тег старше таблицы путей с адресом по ключу; поднимите тег в uses:"
fi

export MECHANISMS="$cache" MECHANISMS_SUPPLIER="$supplier"
export PYTHONPATH="$cache/packages/transport${PYTHONPATH:+:$PYTHONPATH}"
if [ "$script" = preflight.py ]; then
  set -- --root "$root" --mechanisms "$cache" --supplier "$supplier" "$@"
fi
exec "$PYTHON" "$cache/scripts/$script" "$@"
