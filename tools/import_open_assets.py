#!/usr/bin/env python3
"""
Import open-source (CC0) art + generate license-clean SVG enemy placeholders.

Sources:
  - Kenney.nl Tiny Dungeon / Tiny Town / Roguelike RPG / RPG Urban (CC0)
  - Clint Bellanger "Tiny Creatures" (CC0) — OpenGameArt / itch.io
  - Project SVG archetypes as last-resort placeholders

Usage (from repo root):
  python3 tools/import_open_assets.py [--kenney-dir /path/to/extracted]
  python3 tools/import_open_assets.py --svg-only   # no re-crop; regen enemies only
  python3 tools/import_open_assets.py --download   # fetch Kenney + Tiny Creatures

Outputs under client/assets/:
  src/kenney/*.png          16×16 Kenney masters
  src/tiny-creatures/*.png  16×16 TC masters used by game
  tiles/*.png               40×40 map tiles
  sprites/heroes/*          player sprites
  sprites/enemies/*         one PNG per enemy id in shared/dq1_data.json
  svg/enemies/*             SVG sources (only when no pixel art match)
  ui/icon_sword.png

Drop your own PNGs over anything; filenames are the contract.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "client" / "assets"
KENNEY_OUT = ASSETS / "src" / "kenney"
TC_OUT = ASSETS / "src" / "tiny-creatures"
DATA = ROOT / "shared" / "dq1_data.json"
OPEN_CACHE = ROOT / "tools" / "_open_cache"
KENNEY_CACHE = ROOT / "tools" / "_kenney_cache"

# Tiny Dungeon tile indices (16×16) — Kenney CC0
TD = {
    "dungeon_floor": 1,
    "hero_mage": 84,
    "hero_other": 86,
    "hero": 97,
    "icon_sword": 105,
    "enemy_slime": 108,
    "enemy_flesh": 109,
    "enemy_crab": 110,
    "enemy_spider_brown": 120,
    "enemy_skull": 121,
    "enemy_spider": 122,
    "enemy_snake": 123,
    "enemy_rat": 124,
    "knight_iron": 96,
    "knight_steel": 97,
    "knight_gold": 98,
    "chest_mimic": 93,
}

# Map each game enemy_id → (base_key, optional RGB multiply tint or None)
# base_key:
#   key in TD / kenney masters
#   "tc:NNNN"  → Tiny Creatures tile_NNNN.png
#   "svg:arch" → project SVG archetype
ENEMY_MAP: dict[str, tuple[str, tuple[float, float, float] | None]] = {
    # slimes — Kenney green blob + tints
    "slime": ("enemy_slime", None),
    "red_slime": ("enemy_slime", (1.35, 0.35, 0.35)),
    "metal_slime": ("enemy_slime", (0.75, 0.95, 1.15)),
    # scorpions / crustaceans — Kenney crab
    "scorpion": ("enemy_crab", None),
    "metal_scorpion": ("enemy_crab", (0.7, 0.85, 1.1)),
    "rogue_scorpion": ("enemy_crab", (0.55, 0.9, 0.55)),
    # undead / spectral — Kenney skull + Tiny Creatures ghosts
    "skeleton": ("enemy_skull", None),
    "wraith": ("enemy_skull", (0.65, 0.55, 0.95)),
    "wraith_knight": ("enemy_skull", (0.85, 0.75, 0.55)),
    "ghost": ("tc:0031", None),            # white ghost
    "specter": ("tc:0032", None),          # blue ghost
    "poltergeist": ("tc:0044", (1.1, 0.8, 1.15)),  # pale spirit
    # beasts — Tiny Creatures wolves / beasts
    "wolf": ("tc:0024", None),
    "wolflord": ("tc:0025", (0.95, 0.65, 0.5)),
    "werewolf": ("tc:0167", None),         # dark beast
    # constructs — Tiny Creatures golems
    "golem": ("tc:0128", None),
    "stoneman": ("tc:0129", None),
    "goldman": ("tc:0126", (1.35, 1.15, 0.4)),
    # knights / humanoids (Tiny Dungeon characters)
    "knight": ("knight_steel", None),
    "armored_knight": ("knight_iron", None),
    "axe_knight": ("knight_gold", (1.1, 0.85, 0.55)),
    "demon_knight": ("knight_iron", (0.85, 0.35, 0.45)),
    # casters
    "magician": ("hero_mage", None),
    "wizard": ("hero_mage", (0.55, 0.55, 1.15)),
    "warlock": ("hero_mage", (0.9, 0.35, 0.85)),
    "drollmagi": ("hero_mage", (0.45, 0.95, 0.55)),
    # dragons / drakes / wyverns — distinct Tiny Creatures tiles
    "drakee": ("tc:0009", (0.55, 0.95, 1.15)),   # small worm-drake
    "drakeema": ("tc:0077", (1.05, 0.55, 1.1)),  # green dragon + tint
    "magidrakee": ("tc:0027", (0.55, 1.15, 0.75)),  # green scaly
    "droll": ("tc:0015", (0.55, 0.95, 0.6)),     # brown blob
    "druin": ("tc:0042", (0.95, 0.7, 0.5)),      # fox-beast
    "druinlord": ("tc:0166", (0.75, 0.45, 0.55)),  # large beast
    "blue_dragon": ("tc:0041", (0.45, 0.75, 1.35)),  # dragon + blue
    "green_dragon": ("tc:0041", None),
    "red_dragon": ("tc:0079", None),
    "dragonlord": ("tc:0078", (0.85, 0.4, 0.95)),
    "dragonlord_true": ("tc:0080", (1.2, 0.45, 0.35)),
    "wyvern": ("tc:0039", (0.55, 0.95, 0.55)),   # bat-wyvern
    "magiwyvern": ("tc:0039", (0.75, 0.5, 1.15)),
    "starwyvern": ("tc:0040", (1.25, 1.1, 0.35)),  # red star-blob
}


def nn_resize(im: Image.Image, size: int) -> Image.Image:
    return im.convert("RGBA").resize((size, size), Image.NEAREST)


def punch_black_bg(im: Image.Image, threshold: int = 12) -> Image.Image:
    """Tiny Creatures ships opaque pure-black mats — make them transparent.

    TC sprites use color (not pure black) for body/outline; black is only the mat.
    """
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 0 and r <= threshold and g <= threshold and b <= threshold:
                px[x, y] = (0, 0, 0, 0)
    return im


def tint_rgba(im: Image.Image, rgb_mul: tuple[float, float, float] | None) -> Image.Image:
    if not rgb_mul:
        return im.convert("RGBA")
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    r_m, g_m, b_m = rgb_mul
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            # keep outline (very dark) mostly intact
            if r + g + b < 90:
                continue
            nr = min(255, int(r * r_m))
            ng = min(255, int(g * g_m))
            nb = min(255, int(b * b_m))
            px[x, y] = (nr, ng, nb, a)
    return im


def crop_tile(pack_dir: Path, index: int) -> Image.Image:
    path = pack_dir / "Tiles" / f"tile_{index:04d}.png"
    if not path.exists():
        path = pack_dir / "Tiles" / f"tile_{index}.png"
    if not path.exists():
        raise FileNotFoundError(path)
    return Image.open(path).convert("RGBA")


def crop_roguelike_grass(pack_dir: Path) -> Image.Image:
    """Roguelike RPG pack is a spritesheet; grab a grass 16×16."""
    sheet = pack_dir / "Spritesheet" / "roguelikeSheet_transparent.png"
    if not sheet.exists():
        raise FileNotFoundError(sheet)
    im = Image.open(sheet).convert("RGBA")
    tw, margin, spacing = 16, 1, 1

    def at(col: int, row: int) -> Image.Image:
        x = margin + col * (tw + spacing)
        y = margin + row * (tw + spacing)
        return im.crop((x, y, x + tw, y + tw))

    for col, row in [(5, 0), (0, 0), (1, 0), (6, 0)]:
        tile = at(col, row)
        alpha = sum(1 for p in tile.get_flattened_data() if p[3] > 10)
        if alpha > 40:
            return tile
    return at(0, 0)


def crop_urban_water(pack_dir: Path, index: int = 175) -> Image.Image:
    path = pack_dir / "Tiles" / f"tile_{index:04d}.png"
    if path.exists():
        return Image.open(path).convert("RGBA")
    tiles = sorted((pack_dir / "Tiles").glob("tile_*.png"))
    if tiles:
        return Image.open(tiles[min(len(tiles) - 1, index)]).convert("RGBA")
    raise FileNotFoundError("urban water tile")


def ensure_dirs() -> None:
    for p in (
        KENNEY_OUT,
        TC_OUT,
        ASSETS / "tiles",
        ASSETS / "sprites" / "heroes",
        ASSETS / "sprites" / "enemies",
        ASSETS / "svg" / "enemies",
        ASSETS / "ui",
    ):
        p.mkdir(parents=True, exist_ok=True)


def write_svg_enemy(path: Path, archetype: str, label: str, tint: tuple[float, float, float] | None) -> None:
    """Crisp SVG placeholders — project-owned, free to replace."""
    t = tint or (0.7, 0.7, 0.75)
    r = int(min(255, 80 + 150 * t[0]))
    g = int(min(255, 80 + 150 * t[1]))
    b = int(min(255, 80 + 150 * t[2]))
    fill = f"#{r:02x}{g:02x}{b:02x}"
    dark = f"#{max(0, r // 3):02x}{max(0, g // 3):02x}{max(0, b // 3):02x}"
    light = f"#{min(255, r + 40):02x}{min(255, g + 40):02x}{min(255, b + 40):02x}"
    eye = "#1a1010"
    short = (label.replace("_", " ")[:14]).title()

    if archetype in ("slime", "blob"):
        body = f'''
  <ellipse cx="64" cy="82" rx="40" ry="28" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <ellipse cx="50" cy="72" rx="5" ry="7" fill="{eye}"/>
  <ellipse cx="78" cy="72" rx="5" ry="7" fill="{eye}"/>
  <ellipse cx="48" cy="68" rx="2" ry="2" fill="#fff" opacity="0.7"/>
  <ellipse cx="76" cy="68" rx="2" ry="2" fill="#fff" opacity="0.7"/>
'''
    elif archetype == "drake":
        body = f'''
  <ellipse cx="64" cy="88" rx="22" ry="10" fill="{dark}" opacity="0.35"/>
  <ellipse cx="64" cy="70" rx="28" ry="22" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <ellipse cx="88" cy="58" rx="16" ry="12" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <polygon points="100,52 118,48 104,62" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <ellipse cx="94" cy="54" rx="3" ry="3" fill="{eye}"/>
  <rect x="40" y="78" width="8" height="14" fill="{dark}"/>
  <rect x="56" y="80" width="8" height="14" fill="{dark}"/>
  <rect x="72" y="78" width="8" height="14" fill="{dark}"/>
'''
    elif archetype == "dragon":
        body = f'''
  <ellipse cx="64" cy="100" rx="30" ry="10" fill="{dark}" opacity="0.3"/>
  <polygon points="20,70 8,40 28,55" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <polygon points="108,70 120,40 100,55" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <ellipse cx="64" cy="72" rx="34" ry="26" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <ellipse cx="64" cy="48" rx="18" ry="16" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <polygon points="50,38 44,18 58,32" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <polygon points="78,38 84,18 70,32" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <ellipse cx="56" cy="48" rx="3" ry="4" fill="{eye}"/>
  <ellipse cx="72" cy="48" rx="3" ry="4" fill="{eye}"/>
  <polygon points="60,56 64,62 68,56" fill="{dark}"/>
'''
    elif archetype == "wyvern":
        body = f'''
  <ellipse cx="64" cy="96" rx="24" ry="8" fill="{dark}" opacity="0.3"/>
  <polygon points="24,60 4,36 36,50" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <polygon points="104,60 124,36 92,50" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <ellipse cx="64" cy="68" rx="22" ry="28" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <ellipse cx="64" cy="42" rx="14" ry="12" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <ellipse cx="58" cy="40" rx="2.5" ry="3" fill="{eye}"/>
  <ellipse cx="70" cy="40" rx="2.5" ry="3" fill="{eye}"/>
  <polygon points="64,90 58,118 70,118" fill="{fill}" stroke="{dark}" stroke-width="2"/>
'''
    elif archetype == "beast":
        body = f'''
  <ellipse cx="64" cy="96" rx="28" ry="10" fill="{dark}" opacity="0.3"/>
  <ellipse cx="64" cy="72" rx="32" ry="24" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <ellipse cx="64" cy="48" rx="20" ry="16" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <polygon points="48,40 42,24 54,36" fill="{dark}"/>
  <polygon points="80,40 86,24 74,36" fill="{dark}"/>
  <ellipse cx="56" cy="48" rx="3" ry="3" fill="{eye}"/>
  <ellipse cx="72" cy="48" rx="3" ry="3" fill="{eye}"/>
  <rect x="40" y="84" width="10" height="16" fill="{dark}"/>
  <rect x="78" y="84" width="10" height="16" fill="{dark}"/>
'''
    elif archetype == "knight":
        body = f'''
  <ellipse cx="64" cy="100" rx="22" ry="8" fill="{dark}" opacity="0.3"/>
  <rect x="42" y="48" width="44" height="40" rx="6" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <circle cx="64" cy="36" r="16" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <rect x="52" y="30" width="20" height="10" fill="{dark}" opacity="0.5"/>
  <ellipse cx="58" cy="36" rx="2" ry="2" fill="{eye}"/>
  <ellipse cx="70" cy="36" rx="2" ry="2" fill="{eye}"/>
  <rect x="86" y="52" width="8" height="28" fill="{dark}"/>
  <polygon points="90,48 100,56 90,64" fill="{light}" stroke="{dark}" stroke-width="1"/>
'''
    elif archetype == "caster":
        body = f'''
  <ellipse cx="64" cy="100" rx="20" ry="8" fill="{dark}" opacity="0.3"/>
  <polygon points="40,90 64,40 88,90" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <circle cx="64" cy="34" r="12" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <ellipse cx="60" cy="34" rx="2" ry="2" fill="{eye}"/>
  <ellipse cx="68" cy="34" rx="2" ry="2" fill="{eye}"/>
  <line x1="88" y1="90" x2="104" y2="30" stroke="{dark}" stroke-width="3"/>
  <circle cx="104" cy="26" r="6" fill="{light}" stroke="{dark}" stroke-width="2"/>
'''
    elif archetype == "scorpion":
        body = f'''
  <ellipse cx="64" cy="78" rx="30" ry="18" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <ellipse cx="90" cy="70" rx="12" ry="10" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <path d="M40,70 Q20,40 36,30" fill="none" stroke="{dark}" stroke-width="4"/>
  <path d="M88,70 Q108,40 92,30" fill="none" stroke="{dark}" stroke-width="4"/>
  <circle cx="36" cy="28" r="5" fill="{light}"/>
  <circle cx="92" cy="28" r="5" fill="{light}"/>
  <ellipse cx="86" cy="68" rx="2" ry="2" fill="{eye}"/>
  <ellipse cx="94" cy="68" rx="2" ry="2" fill="{eye}"/>
'''
    elif archetype == "undead":
        body = f'''
  <ellipse cx="64" cy="100" rx="18" ry="7" fill="{dark}" opacity="0.3"/>
  <circle cx="64" cy="40" r="18" fill="{light}" stroke="{dark}" stroke-width="2"/>
  <ellipse cx="56" cy="38" rx="3" ry="4" fill="{eye}"/>
  <ellipse cx="72" cy="38" rx="3" ry="4" fill="{eye}"/>
  <rect x="50" y="58" width="28" height="32" rx="4" fill="{fill}" stroke="{dark}" stroke-width="2"/>
  <line x1="50" y1="70" x2="40" y2="90" stroke="{dark}" stroke-width="3"/>
  <line x1="78" y1="70" x2="88" y2="90" stroke="{dark}" stroke-width="3"/>
'''
    elif archetype == "ghost":
        body = f'''
  <path d="M40,90 Q40,40 64,28 Q88,40 88,90 Q80,80 72,90 Q64,80 56,90 Q48,80 40,90 Z"
        fill="{fill}" stroke="{dark}" stroke-width="2" opacity="0.9"/>
  <ellipse cx="54" cy="52" rx="4" ry="6" fill="{eye}"/>
  <ellipse cx="74" cy="52" rx="4" ry="6" fill="{eye}"/>
'''
    else:
        body = f'''
  <circle cx="64" cy="64" r="36" fill="{fill}" stroke="{dark}" stroke-width="3"/>
  <circle cx="52" cy="58" r="5" fill="{eye}"/>
  <circle cx="76" cy="58" r="5" fill="{eye}"/>
'''

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128"
     shape-rendering="geometricPrecision" role="img" aria-label="{label}">
  <!-- Project placeholder — replace client/assets/sprites/enemies/{label}.png anytime -->
  <rect width="128" height="128" fill="none"/>
  {body}
  <text x="64" y="122" text-anchor="middle" font-family="monospace" font-size="10" fill="#333">{short}</text>
</svg>
'''
    path.write_text(svg, encoding="utf-8")


def svg_to_png(svg_path: Path, png_path: Path, size: int = 96) -> bool:
    rsvg = shutil.which("rsvg-convert")
    if rsvg:
        subprocess.run(
            [rsvg, "-w", str(size), "-h", str(size), str(svg_path), "-o", str(png_path)],
            check=True,
        )
        return True
    magick = shutil.which("magick") or shutil.which("convert")
    if magick:
        subprocess.run(
            [magick, "-background", "none", str(svg_path), "-resize", f"{size}x{size}", str(png_path)],
            check=True,
        )
        return True
    print(f"warn: cannot rasterize {svg_path.name} (need rsvg-convert or ImageMagick)", file=sys.stderr)
    return False


def load_enemy_ids() -> list[str]:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    enemies = data.get("enemies") or {}
    if isinstance(enemies, dict):
        return sorted(enemies.keys())
    return sorted(e.get("id") or e.get("name") for e in enemies)


def find_kenney_dir(explicit: Path | None) -> Path | None:
    if explicit and explicit.is_dir():
        return explicit
    candidates = [
        Path("/tmp/kenney_dl/extracted"),
        KENNEY_CACHE,
        Path.home() / "Downloads" / "kenney",
    ]
    for c in candidates:
        if (c / "tiny-dungeon").is_dir() or (c / "Tiles").is_dir():
            return c
    return None


def find_tiny_creatures_dir() -> Path | None:
    candidates = [
        OPEN_CACHE / "tiny-creatures" / "tiny-creatures",
        OPEN_CACHE / "tiny-creatures",
        Path("/tmp/tiny-creatures"),
    ]
    for c in candidates:
        if (c / "Tiles").is_dir():
            return c
        nested = c / "tiny-creatures"
        if (nested / "Tiles").is_dir():
            return nested
    return None


def vendor_kenney_masters(kdir: Path) -> dict[str, Image.Image]:
    """Crop + save 16×16 masters into src/kenney; return name→Image."""
    masters: dict[str, Image.Image] = {}
    td = kdir / "tiny-dungeon"
    if not td.is_dir():
        if (kdir / "Tiles").is_dir():
            td = kdir
        else:
            print("warn: tiny-dungeon not found under", kdir)
            return masters

    for name, idx in TD.items():
        try:
            im = crop_tile(td, idx)
            masters[name] = im
            im.save(KENNEY_OUT / f"{name}.png")
        except FileNotFoundError as e:
            print("skip", name, e)

    try:
        if (kdir / "roguelike").is_dir():
            field = crop_roguelike_grass(kdir / "roguelike")
            masters["field"] = field
            field.save(KENNEY_OUT / "field.png")
        elif (KENNEY_OUT / "field.png").exists():
            masters["field"] = Image.open(KENNEY_OUT / "field.png")
    except Exception as e:
        print("field crop:", e)

    try:
        tt = kdir / "tiny-town"
        if tt.is_dir():
            for name, idx in (("wall", 49), ("town", 43)):
                im = crop_tile(tt, idx)
                masters[name] = im
                im.save(KENNEY_OUT / f"{name}.png")
    except Exception as e:
        print("town tiles:", e)

    try:
        urban = kdir / "urban"
        if urban.is_dir():
            water = crop_urban_water(urban, 175)
            masters["water"] = water
            water.save(KENNEY_OUT / "water.png")
    except Exception as e:
        print("water:", e)

    if "dungeon_floor" in masters:
        masters["dungeon"] = masters["dungeon_floor"]
        masters["dungeon"].save(KENNEY_OUT / "dungeon.png")

    for src, dst in (
        ("hero", "hero.png"),
        ("hero_other", "hero_other.png"),
        ("hero_mage", "hero_mage.png"),
        ("icon_sword", "icon_sword.png"),
        ("enemy_slime", "enemy_slime.png"),
        ("enemy_skull", "enemy_skull.png"),
        ("enemy_spider", "enemy_spider.png"),
    ):
        if src in masters:
            masters[src].save(KENNEY_OUT / dst)

    (KENNEY_OUT / "LICENSE.txt").write_text(
        """Kenney asset crops used by dq1_mmo

Source packs (all Creative Commons Zero / CC0):
  https://kenney.nl/assets/tiny-town
  https://kenney.nl/assets/tiny-dungeon
  https://kenney.nl/assets/rpg-urban-pack
  https://kenney.nl/assets/roguelike-rpg-pack

Author: Kenney Vleugels (www.kenney.nl)
License: https://creativecommons.org/publicdomain/zero/1.0/

You may use these graphics in personal and commercial projects.
Credit (Kenney or www.kenney.nl) would be nice but is not mandatory.
""",
        encoding="utf-8",
    )
    return masters


def vendor_tiny_creatures(tc_dir: Path) -> dict[str, Image.Image]:
    """Copy needed Tiny Creatures tiles into src/tiny-creatures and masters dict."""
    masters: dict[str, Image.Image] = {}
    needed: set[str] = set()
    for base, _ in ENEMY_MAP.values():
        if base.startswith("tc:"):
            needed.add(base.split(":", 1)[1])

    for num in sorted(needed):
        src = tc_dir / "Tiles" / f"tile_{num}.png"
        if not src.exists():
            # try unpadded
            src = tc_dir / "Tiles" / f"tile_{int(num)}.png"
        if not src.exists():
            print("warn: missing Tiny Creatures tile", num)
            continue
        im = punch_black_bg(Image.open(src).convert("RGBA"))
        key = f"tc:{num}"
        masters[key] = im
        im.save(TC_OUT / f"tile_{num}.png")

    lic_src = tc_dir / "License.txt"
    if lic_src.exists():
        shutil.copy2(lic_src, TC_OUT / "LICENSE.txt")
    else:
        (TC_OUT / "LICENSE.txt").write_text(
            """Tiny Creatures (CC0)
Created by Clint Bellanger (clintbellanger.net)
https://opengameart.org/content/tiny-creatures
https://creativecommons.org/publicdomain/zero/1.0/
Compatible with Kenney Tiny Dungeon / Tiny Town (made with Kenney's permission).
""",
            encoding="utf-8",
        )
    print(f"tiny-creatures: vendored {len(masters)} tiles → {TC_OUT}")
    return masters


def load_existing_masters() -> dict[str, Image.Image]:
    masters: dict[str, Image.Image] = {}
    if KENNEY_OUT.is_dir():
        for p in KENNEY_OUT.glob("*.png"):
            masters[p.stem] = Image.open(p).convert("RGBA")
    if TC_OUT.is_dir():
        for p in TC_OUT.glob("tile_*.png"):
            num = p.stem.replace("tile_", "")
            # Re-punch in case older vendored masters still have black mats
            masters[f"tc:{num}"] = punch_black_bg(Image.open(p).convert("RGBA"))
    return masters


def export_game_assets(masters: dict[str, Image.Image]) -> None:
    for name in ("field", "wall", "town", "water", "dungeon"):
        src = masters.get(name) or masters.get("dungeon_floor")
        if src is None and (KENNEY_OUT / f"{name}.png").exists():
            src = Image.open(KENNEY_OUT / f"{name}.png")
        if src is not None:
            nn_resize(src, 40).save(ASSETS / "tiles" / f"{name}.png")
            print("tile", name)

    if "hero" in masters:
        nn_resize(masters["hero"], 40).save(ASSETS / "sprites" / "heroes" / "hero.png")
        nn_resize(masters["hero"], 80).save(ASSETS / "sprites" / "heroes" / "hero_battle.png")
    if "hero_other" in masters:
        nn_resize(masters["hero_other"], 40).save(ASSETS / "sprites" / "heroes" / "other.png")
    if "icon_sword" in masters:
        nn_resize(masters["icon_sword"], 32).save(ASSETS / "ui" / "icon_sword.png")
    print("heroes/ui ok")


def _svg_archetype_for(eid: str, base: str) -> str:
    """Pick an SVG silhouette for companion sources / fallbacks."""
    if base.startswith("svg:"):
        return base.split(":", 1)[1]
    if "slime" in eid or base == "enemy_slime":
        return "slime"
    if "scorpion" in eid or "crab" in base:
        return "scorpion"
    if any(k in eid for k in ("dragon", "drake", "wyvern")):
        return "dragon" if "dragon" in eid else ("wyvern" if "wyvern" in eid else "drake")
    if any(k in eid for k in ("wolf", "were", "druin")):
        return "beast"
    if any(k in eid for k in ("ghost", "specter", "polter")):
        return "ghost"
    if any(k in eid for k in ("skeleton", "wraith")):
        return "undead"
    if any(k in eid for k in ("knight", "golem", "stoneman", "goldman")):
        return "knight"
    if any(k in eid for k in ("magic", "wizard", "warlock", "magi", "drollmagi")):
        return "caster"
    if "droll" in eid:
        return "blob"
    return "blob"


def export_enemies(masters: dict[str, Image.Image], enemy_ids: list[str]) -> None:
    svg_dir = ASSETS / "svg" / "enemies"
    out_dir = ASSETS / "sprites" / "enemies"
    n_kenney = n_tc = n_svg = 0

    for eid in enemy_ids:
        base, tint = ENEMY_MAP.get(eid, ("svg:blob", None))
        dest = out_dir / f"{eid}.png"
        arch = _svg_archetype_for(eid, base)
        # Always keep an editable SVG companion (user can replace PNGs later)
        svg_path = svg_dir / f"{eid}.svg"
        write_svg_enemy(svg_path, arch, eid, tint)

        if base.startswith("svg:"):
            if svg_to_png(svg_path, dest, 96):
                n_svg += 1
            continue

        im = masters.get(base)
        if im is None:
            if svg_to_png(svg_path, dest, 96):
                n_svg += 1
            continue

        im = tint_rgba(im, tint)
        nn_resize(im, 96).save(dest)
        if base.startswith("tc:"):
            n_tc += 1
        else:
            n_kenney += 1

    print(
        f"enemies: {n_kenney} Kenney CC0, {n_tc} Tiny Creatures CC0, "
        f"{n_svg} SVG placeholders (total {len(enemy_ids)}; "
        f"SVG companions in svg/enemies/)"
    )


def download_packs() -> Path | None:
    """Download Kenney packs + Tiny Creatures into tools caches. Returns kenney dir."""
    KENNEY_CACHE.mkdir(parents=True, exist_ok=True)
    OPEN_CACHE.mkdir(parents=True, exist_ok=True)

    packs = {
        "tiny-dungeon": "https://kenney.nl/media/pages/assets/tiny-dungeon/f8422efb44-1674742415/kenney_tiny-dungeon.zip",
        "tiny-town": "https://kenney.nl/media/pages/assets/tiny-town/a415fbeb49-1735736916/kenney_tiny-town.zip",
        "roguelike": "https://kenney.nl/media/pages/assets/roguelike-rpg-pack/12c03cd78b-1677697420/kenney_roguelike-rpg-pack.zip",
        "urban": "https://kenney.nl/media/pages/assets/rpg-urban-pack/0a097d1dc7-1677578575/kenney_rpg-urban-pack.zip",
    }
    for name, url in packs.items():
        zpath = KENNEY_CACHE / f"{name}.zip"
        dest = KENNEY_CACHE / name
        if dest.is_dir() and any(dest.rglob("*.png")):
            print("have Kenney", name)
            continue
        print("download Kenney", name)
        urllib.request.urlretrieve(url, zpath)
        dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(dest)

    # Tiny Creatures (OpenGameArt mirror)
    tc_url = "https://opengameart.org/sites/default/files/tiny-creatures.zip"
    tc_zip = OPEN_CACHE / "tiny-creatures.zip"
    tc_dest = OPEN_CACHE / "tiny-creatures"
    if not find_tiny_creatures_dir():
        print("download Tiny Creatures (CC0, Clint Bellanger)")
        urllib.request.urlretrieve(tc_url, tc_zip)
        tc_dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(tc_zip) as zf:
            zf.extractall(tc_dest)
    else:
        print("have Tiny Creatures")

    return KENNEY_CACHE


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kenney-dir", type=Path, default=None, help="Extracted Kenney packs root")
    ap.add_argument("--svg-only", action="store_true", help="Only regenerate enemies; keep tiles/heroes")
    ap.add_argument("--download", action="store_true", help="Download Kenney + Tiny Creatures packs")
    args = ap.parse_args()

    ensure_dirs()
    enemy_ids = load_enemy_ids()
    print(f"game enemies: {len(enemy_ids)}")

    if args.download:
        args.kenney_dir = download_packs()

    masters: dict[str, Image.Image] = {}
    if not args.svg_only:
        kdir = find_kenney_dir(args.kenney_dir)
        if kdir:
            print("using Kenney packs at", kdir)
            masters.update(vendor_kenney_masters(kdir))
        else:
            print("no Kenney extract found; using existing src/kenney masters if present")
            masters.update(load_existing_masters())

        tc_dir = find_tiny_creatures_dir()
        if tc_dir:
            print("using Tiny Creatures at", tc_dir)
            masters.update(vendor_tiny_creatures(tc_dir))
        else:
            print("warn: Tiny Creatures not found — run with --download or place under tools/_open_cache/")
            # still load any previously vendored TC tiles
            for k, v in load_existing_masters().items():
                if k.startswith("tc:"):
                    masters[k] = v

        if masters:
            export_game_assets(masters)
        else:
            print("warn: no masters — tiles/heroes left unchanged")
    else:
        masters = load_existing_masters()
        tc_dir = find_tiny_creatures_dir()
        if tc_dir:
            masters.update(vendor_tiny_creatures(tc_dir))

    if not masters:
        masters = load_existing_masters()
    # Prefer freshly vendored TC if present
    tc_dir = find_tiny_creatures_dir()
    if tc_dir and not any(k.startswith("tc:") for k in masters):
        masters.update(vendor_tiny_creatures(tc_dir))

    export_enemies(masters, enemy_ids)

    print("done →", ASSETS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
