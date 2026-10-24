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
  rm -rf "$cache.part"
  timeout 300 git -c advice.detachedHead=false clone -q --depth 1 --branch "$tag" "$origin" "$cache.part" \
    || refuse "механизмы $supplier@$tag не выкачаны из $origin"
  rm -rf "$cache"
  mv "$cache.part" "$cache"
fi
[ -f "$cache/scripts/$script" ] || refuse "в механизмах $supplier@$tag нет scripts/$script"

export MECHANISMS="$cache" MECHANISMS_SUPPLIER="$supplier"
export PYTHONPATH="$cache/packages/transport${PYTHONPATH:+:$PYTHONPATH}"
if [ "$script" = preflight.py ]; then
  set -- --root "$root" --mechanisms "$cache" --supplier "$supplier" "$@"
fi
exec "${PYTHON:-python3}" "$cache/scripts/$script" "$@"
