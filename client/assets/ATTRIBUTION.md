# Art assets

Drop replacement PNGs into the folders below any time. **File names are the contract** for auto-load.
Missing files fall back to procedural drawing in the Love2D client.

These are **not** official Dragon Quest art. Swap freely.

## Current set

| Path | Source | License |
|------|--------|---------|
| `tiles/*.png` | [Kenney](https://kenney.nl) **Tiny Town**, **Tiny Dungeon**, **RPG Urban Pack**, **Roguelike RPG Pack** (16→40 nearest) | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `sprites/heroes/*.png` | Kenney **Tiny Dungeon** characters (16→40/80) | CC0 |
| `ui/icon_sword.png` | Kenney **Tiny Dungeon** | CC0 |
| `src/kenney/*.png` | 16×16 Kenney masters used to regenerate game-size PNGs | CC0 |
| `sprites/enemies/*.png` (17) | Kenney **Tiny Dungeon** monsters/characters, tinted per enemy id | CC0 |
| `sprites/enemies/*.png` (23) | [Tiny Creatures](https://opengameart.org/content/tiny-creatures) by Clint Bellanger (Kenney-compatible 16×16) | CC0 |
| `src/tiny-creatures/*.png` | Vendored Tiny Creatures tiles used above | CC0 |
| `svg/` + `svg/enemies/*.svg` | Editable SVG companions for every enemy + tile/hero outlines (PNG is what the game loads) | Project |

**Credit (optional, appreciated):**
- [Kenney.nl](https://kenney.nl) — Kenney Vleugels, CC0
- [Clint Bellanger](https://clintbellanger.net) — Tiny Creatures, CC0

### Enemy id → art strategy

| Family | Examples | Art |
|--------|----------|-----|
| Slimes | `slime`, `red_slime`, `metal_slime` | Kenney slime + color tint |
| Scorpions | `scorpion`, `metal_scorpion`, `rogue_scorpion` | Kenney crab |
| Undead (bones) | `skeleton`, `wraith`, `wraith_knight` | Kenney skull + tint |
| Ghosts | `ghost`, `specter`, `poltergeist` | Tiny Creatures ghosts (distinct tiles) |
| Beasts | `wolf`, `wolflord`, `werewolf` | Tiny Creatures wolves / dark beast |
| Constructs | `golem`, `stoneman`, `goldman` | Tiny Creatures golems |
| Knights | `knight`, `armored_knight`, … | Kenney knight characters |
| Casters | `magician`, `wizard`, `warlock` | Kenney mage |
| Dragons / drakes / wyverns | `blue_dragon`, `drakee`, `wyvern`, … | Distinct Tiny Creatures dragons / bats / worm-drake |
| Misc beasts | `droll`, `druin`, `druinlord` | Tiny Creatures blobs / fox / large beast |

Each enemy also has `svg/enemies/<id>.svg` — silhouette templates you can edit and rasterize if you prefer vectors over the CC0 pixel art.

## Replacing art yourself

1. Drop PNGs into the folders below (names must match).
2. Prefer **nearest-neighbor** pixel art (16/32/40/64/96).
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

Name files after enemy **ids** from `shared/dq1_data.json` (40 enemies), e.g.:

- `slime.png`, `red_slime.png`, `drakee.png`, `ghost.png`, `skeleton.png`, …

Missing files fall back to a colored blob in combat UI.

### UI (`ui/`)

Optional icons; safe to leave as-is.

## Regenerating assets

```bash
# from repo root — uses vendored masters + Tiny Creatures mapping
./tools/gen_placeholder_assets.sh

# full re-import (re-download Kenney + Tiny Creatures CC0 packs)
python3 tools/import_open_assets.py --download

# packs already extracted
python3 tools/import_open_assets.py --kenney-dir /tmp/kenney_dl/extracted

# only refresh enemy sprites (keep current tiles/heroes)
python3 tools/import_open_assets.py --svg-only
```

Manual scale example:

```bash
convert client/assets/src/kenney/field.png -filter point -resize 40x40 client/assets/tiles/field.png
```

## Packs used (all CC0)

- https://kenney.nl/assets/tiny-town  
- https://kenney.nl/assets/tiny-dungeon  
- https://kenney.nl/assets/rpg-urban-pack  
- https://kenney.nl/assets/roguelike-rpg-pack  
- https://opengameart.org/content/tiny-creatures (Clint Bellanger; also on [itch.io](https://clintbellanger.itch.io/tiny-creatures))

## SVG-only path

If you want pure vector placeholders instead of pixel art:

```bash
# force SVG for a single enemy (edit ENEMY_MAP or overwrite PNG after)
rsvg-convert -w 96 -h 96 client/assets/svg/enemies/blue_dragon.svg -o client/assets/sprites/enemies/blue_dragon.png
```

Or set an enemy to `"svg:dragon"` in `tools/import_open_assets.py` and re-run.
