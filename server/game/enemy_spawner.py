"""Random encounter rolls by zone."""

from __future__ import annotations

from game.data_loader import get_enemy, load_data
from game.rng import Rng
from game.world_manager import zone_at

FIELD_ENCOUNTER_CHANCE = 9  # /100 per step
DUNGEON_ENCOUNTER_CHANCE = 16

FIELD_WEIGHTS = {
    "slime": 30,
    "red_slime": 20,
    "drakee": 15,
    "ghost": 12,
    "magician": 8,
    "magidrakee": 6,
    "scorpion": 5,
    "druin": 4,
    "poltergeist": 3,
    "droll": 3,
    "drakeema": 2,
    "skeleton": 2,
}

DUNGEON_WEIGHTS = {
    "skeleton": 22,
    "ghost": 14,
    "magician": 12,
    "scorpion": 12,
    "druin": 10,
    "poltergeist": 8,
    "droll": 8,
    "metal_scorpion": 6,
    "wolflord": 4,
    "wraith": 4,
}


def _table_ids(weights: dict[str, int]) -> list[str]:
    enemies = load_data()["enemies"]
    return [eid for eid in weights if eid in enemies]


def roll_encounter(x: int, y: int, rng: Rng | None = None) -> str | None:
    rng = rng or Rng()
    zone = zone_at(x, y)
    if zone == "town":
        return None
    if zone == "field":
        if not rng.chance(FIELD_ENCOUNTER_CHANCE, 100):
            return None
        return weighted_pick(rng, FIELD_WEIGHTS)
    if zone == "dungeon":
        if not rng.chance(DUNGEON_ENCOUNTER_CHANCE, 100):
            return None
        return weighted_pick(rng, DUNGEON_WEIGHTS)
    return None


def weighted_pick(rng: Rng, weights: dict[str, int]) -> str:
    pool = [(eid, w) for eid, w in weights.items() if get_enemy(eid)]
    if not pool:
        return "slime"
    total = sum(w for _, w in pool)
    roll = rng.int(1, total)
    acc = 0
    for eid, w in pool:
        acc += w
        if roll <= acc:
            return eid
    return pool[-1][0]


def field_enemies() -> list[str]:
    return _table_ids(FIELD_WEIGHTS)


def dungeon_enemies() -> list[str]:
    return _table_ids(DUNGEON_WEIGHTS)
