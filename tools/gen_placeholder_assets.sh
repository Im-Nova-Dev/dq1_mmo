#!/usr/bin/env bash
# Regenerate SVG→PNG placeholder tiles/heroes and reconvert enemy SVGs from dq1-combat.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)/client/assets"
MON_SRC="${DQ1_COMBAT_MONSTERS:-$(cd "$(dirname "$0")/../.." && pwd)/dq1-combat/demos/assets/monsters}"
# Fallback: sibling path from Projects
if [[ ! -d "$MON_SRC" ]]; then
  MON_SRC="/home/sleep/Projects/dq1-combat/demos/assets/monsters"
fi

command -v rsvg-convert >/dev/null || { echo "need rsvg-convert (librsvg)"; exit 1; }

mkdir -p "$ROOT/tiles" "$ROOT/sprites/heroes" "$ROOT/sprites/enemies" "$ROOT/ui" "$ROOT/svg"

for name in field wall town water dungeon; do
  svg="$ROOT/svg/tile_${name}.svg"
  if [[ -f "$svg" ]]; then
    rsvg-convert -w 40 -h 40 "$svg" -o "$ROOT/tiles/${name}.png"
    echo "tile $name"
  fi
done

for pair in "hero:hero.png" "hero:hero_battle.png:80" "hero_other:other.png"; do
  IFS=: read -r base out size <<<"${pair//:/ }"
done

[[ -f "$ROOT/svg/hero.svg" ]] && rsvg-convert -w 40 -h 40 "$ROOT/svg/hero.svg" -o "$ROOT/sprites/heroes/hero.png"
[[ -f "$ROOT/svg/hero.svg" ]] && rsvg-convert -w 80 -h 80 "$ROOT/svg/hero.svg" -o "$ROOT/sprites/heroes/hero_battle.png"
[[ -f "$ROOT/svg/hero_other.svg" ]] && rsvg-convert -w 40 -h 40 "$ROOT/svg/hero_other.svg" -o "$ROOT/sprites/heroes/other.png"

if [[ -d "$MON_SRC" ]]; then
  n=0
  for f in "$MON_SRC"/*.svg; do
    base=$(basename "$f" .svg)
    rsvg-convert -w 96 -h 96 "$f" -o "$ROOT/sprites/enemies/${base}.png" && n=$((n + 1)) || true
  done
  echo "enemies converted: $n from $MON_SRC"
else
  echo "warn: no monster SVG dir at $MON_SRC"
fi

echo "done → $ROOT"
