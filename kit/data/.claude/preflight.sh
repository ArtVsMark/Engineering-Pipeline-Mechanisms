# Предполётная проверка у потребителя механизмов (#1553): прогнать проверки
# дерева так, как их прогонит площадка, — до толчка.
#
#   bash .claude/preflight.sh            # проверить
#   bash .claude/preflight.sh --push     # проверить и толкнуть ветку, если зелено
#   bash .claude/preflight.sh --list     # только показать, что будет запущено
#
# КОД — ТОТ ЖЕ, ЧТО У ПЛОЩАДКИ. Поставщик и тег берутся из `uses:` ваших
# прогонов (`<владелец>/<репо>/.github/workflows/step-*.yml@vX.Y.Z`), механизмы
# этого тега выкачиваются один раз в кеш окна, и оттуда зовётся их
# `scripts/preflight.py` против вашего дерева. Копий скриптов в вашем дереве нет:
# реализация на семью одна (090).
#
# Исходы, как у предполётной: 0 — зелено, 3 — есть красное, 2 — не отработала
# (в том числе здесь: вызовов нет, вызовы расходятся, ссылка не тег, выкачка
# не удалась). Интерпретатор — `PYTHON` (по умолчанию `python3`): ему нужны
# планка механизмов и `pyyaml`.
set -euo pipefail

refuse() {
  echo "предполётная не отработала: $1" >&2
  exit 2
}

root=$(git rev-parse --show-toplevel) || refuse "не дерево git"
cd "$root"

# Запись вызова — с кавычками или без: `uses: o/m/…@v1` и `uses: "o/m/…@v1"`.
calls=$(grep -rhoE "uses:[[:space:]]*[\"']?[^[:space:]/\"']+/[^[:space:]/]+/\.github/workflows/[^@[:space:]]+@[^[:space:]\"']+" \
  .github/workflows 2>/dev/null \
  | sed -E "s/^uses:[[:space:]]*[\"']?([^/]+\/[^/]+)\/.*@(.*)$/\1 \2/" | sort -u || true)
[ -n "$calls" ] || refuse "в .github/workflows нет вызова общих шагов механизмов — тег взять неоткуда"
[ "$(printf '%s\n' "$calls" | wc -l)" -eq 1 ] \
  || refuse "прогоны зовут механизмы по разным ссылкам — сведите их к одному тегу: $(printf '%s; ' $calls)"
supplier=${calls% *}
tag=${calls#* }
[[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] \
  || refuse "механизмы зовутся по «$tag», а не по закреплённому тегу vX.Y.Z — выкачка не повторила бы площадку"

cache="${XDG_CACHE_HOME:-$HOME/.cache}/mechanisms/${supplier//\//_}@$tag"
if [ ! -f "$cache/scripts/preflight.py" ]; then
  origin="${MECHANISMS_ORIGIN:-https://github.com}/$supplier.git"
  rm -rf "$cache.part"
  timeout 300 git clone -q --depth 1 --branch "$tag" "$origin" "$cache.part" \
    || refuse "механизмы $supplier@$tag не выкачаны из $origin"
  rm -rf "$cache"
  mv "$cache.part" "$cache"
fi

export PYTHONPATH="$cache/packages/transport${PYTHONPATH:+:$PYTHONPATH}"
exec "${PYTHON:-python3}" "$cache/scripts/preflight.py" --root "$root" --mechanisms "$cache" "$@"
