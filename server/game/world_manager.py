"""World map — town, field, water, dungeon."""

# Tile codes:
# 0 grass / field (encounters)
# 1 wall
# 2 town floor (safe)
# 3 water (blocked)
# 4 dungeon floor (harder encounters)

MVP_MAP = [
    #  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 2, 2, 2, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 4, 4, 4, 1],
    [1, 2, 2, 2, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 4, 4, 4, 1],
    [1, 2, 2, 2, 2, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 4, 4, 4, 1],
    [1, 2, 2, 2, 2, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 1, 1, 4, 1, 1],
    [1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 4, 4, 4, 1],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 4, 4, 4, 1],
    [1, 0, 0, 0, 0, 0, 0, 3, 3, 0, 0, 0, 0, 0, 0, 1, 1, 0, 1, 1],
    [1, 0, 0, 0, 0, 0, 0, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
]

MAP_WIDTH = len(MVP_MAP[0])
MAP_HEIGHT = len(MVP_MAP)
VISIBILITY_RANGE = 10
SPAWN_X = 2
SPAWN_Y = 2
WALKABLE = {0, 2, 4}

# Dungeon entrance from field
DUNGEON_ENTRANCE = (15, 3)  # walkable path into dungeon corridor


def in_bounds(x: int, y: int) -> bool:
    return 0 <= x < MAP_WIDTH and 0 <= y < MAP_HEIGHT


def tile_at(x: int, y: int) -> int:
    if not in_bounds(x, y):
        return 1
    return MVP_MAP[y][x]


def is_walkable(x: int, y: int) -> bool:
    return tile_at(x, y) in WALKABLE


def zone_at(x: int, y: int) -> str:
    t = tile_at(x, y)
    if t == 2:
        return "town"
    if t == 0:
        return "field"
    if t == 4:
        return "dungeon"
    return "blocked"


def is_nearby(ax: float, ay: float, bx: float, by: float, rang: int = VISIBILITY_RANGE) -> bool:
    return abs(ax - bx) <= rang and abs(ay - by) <= rang


def is_adjacent_step(fx: int, fy: int, tx: int, ty: int) -> bool:
    dx = abs(tx - fx)
    dy = abs(ty - fy)
    return (dx + dy) == 1


def map_payload() -> dict:
    return {
        "width": MAP_WIDTH,
        "height": MAP_HEIGHT,
        "tiles": MVP_MAP,
        "spawn": {"x": SPAWN_X, "y": SPAWN_Y},
        "legend": {
            "0": "field",
            "1": "wall",
            "2": "town",
            "3": "water",
            "4": "dungeon",
        },
    }
