#!/usr/bin/env bash
# Regenerate game-size PNGs from vendored sources + optional enemy SVGs.
# Prefer client/assets/src/kenney/*.png (Kenney CC0). Falls back to SVG placeholders.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)/client/assets"
KENNEY="$ROOT/src/kenney"
MON_SRC="${DQ1_COMBAT_MONSTERS:-$(cd "$(dirname "$0")/../.." && pwd)/dq1-combat/demos/assets/monsters}"
if [[ ! -d "$MON_SRC" ]]; then
  MON_SRC="/home/sleep/Projects/dq1-combat/demos/assets/monsters"
fi

mkdir -p "$ROOT/tiles" "$ROOT/sprites/heroes" "$ROOT/sprites/enemies" "$ROOT/ui" "$ROOT/svg"

scale_nn() {
  # scale_nn SRC DEST SIZE — nearest-neighbor, preserve RGBA
  local src="$1" dest="$2" size="$3"
  local py=""
  for cand in \
    "$(dirname "$0")/../server/.venv/bin/python3" \
    python3; do
    if [[ -x "$cand" ]] || command -v "$cand" >/dev/null 2>&1; then
      if "$cand" -c "from PIL import Image" 2>/dev/null; then
        py="$cand"
        break
      fi
    fi
  done
  if [[ -n "$py" ]]; then
    "$py" - "$src" "$dest" "$size" <<'PY'
import sys
from PIL import Image
src, dest, size = sys.argv[1], sys.argv[2], int(sys.argv[3])
Image.open(src).convert("RGBA").resize((size, size), Image.NEAREST).save(dest)
PY
  elif command -v magick >/dev/null 2>&1; then
    magick "$src" -filter point -resize "${size}x${size}" PNG32:"$dest"
  elif command -v convert >/dev/null 2>&1; then
    convert "$src" -filter point -resize "${size}x${size}" PNG32:"$dest"
  else
    echo "need Pillow or ImageMagick to scale $src" >&2
    return 1
  fi
}

# --- Kenney CC0 masters (preferred) ---
if [[ -f "$KENNEY/field.png" ]]; then
  for name in field wall town water dungeon; do
    if [[ -f "$KENNEY/${name}.png" ]]; then
      scale_nn "$KENNEY/${name}.png" "$ROOT/tiles/${name}.png" 40
      echo "tile $name (kenney)"
    fi
  done
  [[ -f "$KENNEY/hero.png" ]] && scale_nn "$KENNEY/hero.png" "$ROOT/sprites/heroes/hero.png" 40
  [[ -f "$KENNEY/hero.png" ]] && scale_nn "$KENNEY/hero.png" "$ROOT/sprites/heroes/hero_battle.png" 80
  [[ -f "$KENNEY/hero_other.png" ]] && scale_nn "$KENNEY/hero_other.png" "$ROOT/sprites/heroes/other.png" 40
  [[ -f "$KENNEY/icon_sword.png" ]] && scale_nn "$KENNEY/icon_sword.png" "$ROOT/ui/icon_sword.png" 32
  echo "heroes/ui from kenney"
else
  # --- SVG fallback ---
  if ! command -v rsvg-convert >/dev/null 2>&1; then
    echo "warn: no kenney sources and no rsvg-convert; skip tile/hero regen"
  else
    for name in field wall town water dungeon; do
      svg="$ROOT/svg/tile_${name}.svg"
      if [[ -f "$svg" ]]; then
        rsvg-convert -w 40 -h 40 "$svg" -o "$ROOT/tiles/${name}.png"
        echo "tile $name (svg)"
      fi
    done
    [[ -f "$ROOT/svg/hero.svg" ]] && rsvg-convert -w 40 -h 40 "$ROOT/svg/hero.svg" -o "$ROOT/sprites/heroes/hero.png"
    [[ -f "$ROOT/svg/hero.svg" ]] && rsvg-convert -w 80 -h 80 "$ROOT/svg/hero.svg" -o "$ROOT/sprites/heroes/hero_battle.png"
    [[ -f "$ROOT/svg/hero_other.svg" ]] && rsvg-convert -w 40 -h 40 "$ROOT/svg/hero_other.svg" -o "$ROOT/sprites/heroes/other.png"
    [[ -f "$ROOT/svg/icon_sword.svg" ]] && rsvg-convert -w 32 -h 32 "$ROOT/svg/icon_sword.svg" -o "$ROOT/ui/icon_sword.png"
    echo "heroes/ui from svg"
  fi
fi

# --- Enemy sprites from dq1-combat SVGs (optional) ---
if [[ -d "$MON_SRC" ]] && command -v rsvg-convert >/dev/null 2>&1; then
  n=0
  for f in "$MON_SRC"/*.svg; do
    [[ -f "$f" ]] || continue
    base=$(basename "$f" .svg)
    rsvg-convert -w 96 -h 96 "$f" -o "$ROOT/sprites/enemies/${base}.png" && n=$((n + 1)) || true
  done
  echo "enemies converted: $n from $MON_SRC"
else
  echo "note: enemy PNGs left as-is (no monster SVG dir or rsvg-convert)"
fi

echo "done → $ROOT"
