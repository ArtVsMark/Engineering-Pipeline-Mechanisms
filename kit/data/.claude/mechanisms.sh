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
# Интерпретатор — `PYTHON` (по умолчанию `python3`): ему нужны планка механизмов
# и `pyyaml`.
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
  # окна делят кеш. Поэтому выкачка идёт в СВОЙ каталог (`.part.<pid>`), а
  # готовый кеш не стирается никогда: кто выкачал вторым, бросает свою копию.
  # Остаток — недокачанный кеш без `preflight.py` — заменяется; окно между
  # проверкой и `mv` названо, а не закрыто: блокировки переносимой у оболочки нет.
  part="$cache.part.$$"
  rm -rf "$part"
  "$deadline" 300 git -c advice.detachedHead=false clone -q --depth 1 --branch "$tag" "$origin" "$part" \
    || { rm -rf "$part"; refuse "механизмы $supplier@$tag не выкачаны из $origin"; }
  if [ -f "$cache/scripts/preflight.py" ]; then
    rm -rf "$part"
  else
    rm -rf "$cache"
    mv "$part" "$cache"
  fi
fi
[ -f "$cache/scripts/$script" ] || refuse "в механизмах $supplier@$tag нет scripts/$script"

export MECHANISMS="$cache" MECHANISMS_SUPPLIER="$supplier"
export PYTHONPATH="$cache/packages/transport${PYTHONPATH:+:$PYTHONPATH}"
if [ "$script" = preflight.py ]; then
  set -- --root "$root" --mechanisms "$cache" --supplier "$supplier" "$@"
fi
exec "${PYTHON:-python3}" "$cache/scripts/$script" "$@"
