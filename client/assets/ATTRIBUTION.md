# Art assets

## Current set (placeholder)

| Path | Source | License |
|------|--------|---------|
| `sprites/enemies/*.png` | Converted from [dq1-combat](https://github.com/Im-Nova-Dev/dq1-combat) demo SVGs | Project assets |
| `sprites/heroes/*.png` | Generated SVG placeholders | Project (replace freely) |
| `tiles/*.png` | Generated SVG placeholders | Project (replace freely) |
| `ui/*.png` | Generated SVG placeholders | Project (replace freely) |
| `svg/` | Source SVGs for regenerating PNGs | Project |

## Replacing art yourself

1. Drop PNGs into the folders below (names matter for auto-load).
2. Keep **nearest-neighbor** friendly sizes (multiples of 16/32 work best).
3. Restart Love2D (or it reloads on next `love client`).

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
| `hero_battle.png` | Combat (optional, larger) |
| `other.png` | Other players |

### Enemies (`sprites/enemies/`)

Name files after enemy **ids** from `shared/dq1_data.json`, e.g.:

- `slime.png`, `red_slime.png`, `drakee.png`, `ghost.png`, `skeleton.png`, …

Missing files fall back to a colored blob.

### UI (`ui/`)

Optional icons; safe to leave as-is.

## Regenerating placeholders

```bash
# from repo after editing client/assets/svg/*
rsvg-convert -w 40 -h 40 client/assets/svg/tile_field.svg -o client/assets/tiles/field.png
```

Or re-run the generation portion of the asset setup script if present.
