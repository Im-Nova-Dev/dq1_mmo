from database.db import db_write, get_db
from game.serialize import character_dict


async def get_character(character_id: int) -> dict | None:
    db = await get_db()
    async with db.execute("SELECT * FROM characters WHERE id = ?", (character_id,)) as c:
        row = await c.fetchone()
    if row is None:
        return None
    return character_dict(row)


async def save_position(character_id: int, x: float, y: float) -> None:
    async with db_write() as db:
        await db.execute(
            "UPDATE characters SET world_x = ?, world_y = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (x, y, character_id),
        )
        await db.commit()


async def apply_character_patch(character_id: int, patch: dict) -> dict | None:
    fields = []
    values = []
    allowed = {
        "level",
        "experience",
        "strength",
        "agility",
        "max_hp",
        "max_mp",
        "current_hp",
        "current_mp",
        "gold",
        "total_kills",
        "world_x",
        "world_y",
        "map_id",
    }
    for k, v in patch.items():
        if k in allowed:
            fields.append(f"{k} = ?")
            values.append(v)
    if not fields:
        return await get_character(character_id)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(character_id)
    async with db_write() as db:
        await db.execute(
            f"UPDATE characters SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )
        await db.commit()
    return await get_character(character_id)


def inn_cost(character: dict) -> int:
    """DQ1-ish inn fee: scales with level; 0 if already full HP/MP."""
    max_hp = int(character.get("max_hp") or 1)
    max_mp = int(character.get("max_mp") or 0)
    cur_hp = int(character.get("current_hp") or 0)
    cur_mp = int(character.get("current_mp") or 0)
    if cur_hp >= max_hp and cur_mp >= max_mp:
        return 0
    level = max(1, int(character.get("level") or 1))
    return max(4, level * 4)


async def rest_at_inn(db, character: dict) -> tuple[bool, str, dict]:
    """Full HP/MP restore for gold. Caller must ensure town + not in combat."""
    from game.item_manager import _safe_gold

    max_hp = int(character.get("max_hp") or 1)
    max_mp = int(character.get("max_mp") or 0)
    cur_hp = int(character.get("current_hp") or 0)
    cur_mp = int(character.get("current_mp") or 0)
    if cur_hp >= max_hp and cur_mp >= max_mp:
        return False, "already at full HP/MP", {}

    cost = inn_cost(character)
    gold = _safe_gold(character)
    if gold < cost:
        return False, "not enough gold", {"cost": cost, "gold": gold}

    gold_after = gold - cost
    cid = int(character["id"])
    await db.execute(
        """
        UPDATE characters
        SET current_hp = ?, current_mp = ?, gold = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (max_hp, max_mp, str(gold_after), cid),
    )
    await db.commit()

    character["current_hp"] = max_hp
    character["current_mp"] = max_mp
    character["gold"] = str(gold_after)
    return (
        True,
        "ok",
        {
            "cost": cost,
            "gold": str(gold_after),
            "current_hp": max_hp,
            "current_mp": max_mp,
            "max_hp": max_hp,
            "max_mp": max_mp,
            "message": f"You rest at the inn and recover fully! (−{cost} G)",
        },
    )
