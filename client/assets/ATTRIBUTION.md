# Art assets

Drop replacement PNGs into the folders below any time. Names matter for auto-load.
Missing files fall back to procedural drawing in the client.

## Current set

| Path | Source | License |
|------|--------|---------|
| `tiles/*.png` | [Kenney](https://kenney.nl) **Tiny Town**, **Tiny Dungeon**, **RPG Urban Pack** (scaled 16→40) | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `sprites/heroes/*.png` | Kenney **Tiny Dungeon** characters (scaled 16→40/80) | CC0 |
| `ui/icon_sword.png` | Kenney **Tiny Dungeon** | CC0 |
| `src/kenney/*.png` | 16×16 source crops used to regenerate game-size PNGs | CC0 |
| `sprites/enemies/*.png` | Converted from [dq1-combat](https://github.com/Im-Nova-Dev/dq1-combat) demo SVGs | Project assets (replace freely) |
| `svg/` | Simple SVG placeholders (optional regen path) | Project |

**Credit (optional, appreciated):** [Kenney.nl](https://kenney.nl) — CC0 asset packs.

These are **not** official Dragon Quest art. Swap in your own sprites whenever you like.

## Replacing art yourself

1. Drop PNGs into the folders below (file names matter).
2. Prefer **nearest-neighbor** sizes (16/32/40/64 work well).
3. Restart Love2D (`love client`).

### Tiles (`tiles/`) — 40×40 recommended

| File | Map code |
|------|----------|
| `field.png` | 0 grass / field |
| `wall.png` | 1 wall |
| `town.png` | 2 town |
| `water.png` | 3 water |
| `dungeon.png` | 4 dungeon |

### Heroes (`sprites/heroes/`)

| File | Use |
|------|-----|
| `hero.png` | Local player (overworld, ~40×40) |
| `hero_battle.png` | Combat (optional, larger ~80×80) |
| `other.png` | Other players |

### Enemies (`sprites/enemies/`)

Name files after enemy **ids** from `shared/dq1_data.json`, e.g.:

- `slime.png`, `red_slime.png`, `drakee.png`, `ghost.png`, `skeleton.png`, …

Missing files fall back to a colored blob.

### UI (`ui/`)

Optional icons; safe to leave as-is.

## Regenerating from vendored Kenney sources

16×16 masters live in `src/kenney/`. Scale them up without re-downloading:

```bash
# from repo root
./tools/gen_placeholder_assets.sh
```

Or manually:

```bash
# example: 40×40 nearest-neighbor with ImageMagick
convert client/assets/src/kenney/field.png -filter point -resize 40x40 client/assets/tiles/field.png
```

## Optional: re-download Kenney packs (CC0)

```bash
# Tiny Town, Tiny Dungeon, RPG Urban (URLs from kenney.nl asset pages)
# Then re-run tools/import_open_assets.py if present, or copy tiles by hand.
```

Packs used (all CC0):

- https://kenney.nl/assets/tiny-town  
- https://kenney.nl/assets/tiny-dungeon  
- https://kenney.nl/assets/rpg-urban-pack  
- https://kenney.nl/assets/roguelike-rpg-pack  

## SVG placeholders

```bash
rsvg-convert -w 40 -h 40 client/assets/svg/tile_field.svg -o client/assets/tiles/field.png
```

Prefer the Kenney PNGs for gameplay; SVGs remain as a license-clean fallback if you delete PNGs and want to redraw simply.
