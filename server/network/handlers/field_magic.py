"""Field (overworld) magic — extracted.

Multiplayer reliability: only when not in combat; cast / shortcuts; heal
refuses full HP; Return/Outside teleport via publish_move (AOI); successful
cast mark_active + publish_status (AFK clear); spell_cast echo includes
online/nearby census for room orientation. Combat battle spells stay in
message_handler combat path (this module returns None mid-fight for cast types).
"""

from __future__ import annotations

from typing import Any

from game.combat_engine import combat_engine
from game.data_loader import battle_spells_at, field_spells_at, get_spell
from game import formulas as F
from game.item_manager import REPEL_STEPS, equipment_bonuses
from game.player_manager import apply_character_patch, get_character
from game.rng import Rng
from game.world_manager import DUNGEON_ENTRANCE, SPAWN_X, SPAWN_Y, is_walkable, zone_at
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import manager

FIELD_SHORTCUTS = frozenset(
    {"heal", "healmore", "return", "repel", "outside", "radiant"}
)
CAST_TYPES = frozenset(
    {
        ClientMessageType.USE_SPELL,
        "use_spell",
        "cast",
        "cast_spell",
    }
)
ALL_TYPES = CAST_TYPES | FIELD_SHORTCUTS

_SPELL_ALIAS = {
    "healmore": "healmore",
    "heal_more": "healmore",
    "return": "return",
    "warp": "return",
    "town": "return",
    "repel": "repel",
    "holy_protection": "repel",
    "outside": "outside",
    "exit": "outside",
    "radiant": "radiant",
    "light": "radiant",
    "heal": "heal",
}


def _census(character_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    payload["online"] = len(manager.online_ids())
    payload["nearby_count"] = len(manager.ids_nearby(character_id))
    meta = manager.get_meta(character_id)
    if meta is not None:
        try:
            z = zone_at(int(meta["x"]), int(meta["y"]))
            if z in ("town", "field", "dungeon"):
                payload["zone"] = z
        except Exception:
            pass
    return payload


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch field magic. Returns None if not field magic (or combat cast)."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    # Mid-fight: cast/use_spell go to combat path; pure shortcuts fall through
    if combat_engine.is_in_combat(character_id if character_id is not None else -1):
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    if msg_type in FIELD_SHORTCUTS:
        spell_id = str(msg_type)
    else:
        spell_id = str(
            data.get("spell")
            or data.get("id")
            or data.get("name")
            or ""
        ).strip().lower().replace(" ", "")
    spell_id = _SPELL_ALIAS.get(spell_id, spell_id)

    char = await get_character(character_id)
    if not char:
        outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
        return character_id, user_id, outbound, None

    known = field_spells_at(int(char["level"]))
    if spell_id not in known:
        outbound.append(msg(ServerMessageType.ERROR, reason="unknown or unlearned spell"))
        return character_id, user_id, outbound, None

    sp = get_spell(spell_id)
    if not sp or not sp.get("field"):
        outbound.append(msg(ServerMessageType.ERROR, reason="cannot cast on field"))
        return character_id, user_id, outbound, None

    cost = int(sp.get("mp_cost") or 0)
    mp = int(char.get("current_mp") or 0)
    if mp < cost:
        outbound.append(msg(ServerMessageType.ERROR, reason="not enough MP"))
        return character_id, user_id, outbound, None

    rng = Rng()
    meta = manager.get_meta(character_id)
    patch: dict = {"current_mp": mp - cost}
    info: dict = {
        "spell": spell_id,
        "name": sp.get("name") or spell_id,
        "mp_cost": cost,
        "current_mp": mp - cost,
    }
    formula = sp.get("formula") or spell_id

    if formula in ("heal", "healmore"):
        max_hp = int(char.get("max_hp") or 1)
        cur_hp = int(char.get("current_hp") or 0)
        if cur_hp >= max_hp:
            outbound.append(msg(ServerMessageType.ERROR, reason="already at full HP"))
            return character_id, user_id, outbound, None
        amt = F.heal_amount(rng) if formula == "heal" else F.healmore_amount(rng)
        new_hp, actual = F.apply_heal(cur_hp, max_hp, amt)
        patch["current_hp"] = new_hp
        info.update(
            {
                "healed": actual,
                "current_hp": new_hp,
                "max_hp": max_hp,
                "message": f"You cast {sp.get('name')}! Recovered {actual} HP.",
            }
        )
    elif formula == "return" or spell_id == "return":
        patch["world_x"] = SPAWN_X
        patch["world_y"] = SPAWN_Y
        info.update(
            {
                "teleported": True,
                "x": SPAWN_X,
                "y": SPAWN_Y,
                "message": f"You cast {sp.get('name')}! Returned to town.",
            }
        )
    elif formula == "repel" or spell_id == "repel":
        manager.set_repel(character_id, REPEL_STEPS)
        info.update(
            {
                "repel_steps": REPEL_STEPS,
                "message": f"You cast {sp.get('name')}! Foes keep away for a while.",
            }
        )
    elif spell_id == "outside":
        zone = zone_at(int(meta["x"]), int(meta["y"])) if meta else "blocked"
        if zone != "dungeon":
            outbound.append(msg(ServerMessageType.ERROR, reason="only works in dungeon"))
            return character_id, user_id, outbound, None
        ox, oy = 14, 3
        if not is_walkable(ox, oy):
            ox, oy = DUNGEON_ENTRANCE[0] - 1, DUNGEON_ENTRANCE[1]
        patch["world_x"] = ox
        patch["world_y"] = oy
        info.update(
            {
                "teleported": True,
                "x": ox,
                "y": oy,
                "message": f"You cast {sp.get('name')}! You exit the dungeon.",
            }
        )
    elif spell_id == "radiant":
        steps = int(getattr(manager, "RADIANT_STEPS", 64) or 64)
        manager.set_radiant(character_id, steps)
        info.update(
            {
                "radiant_steps": steps,
                "message": (
                    f"You cast {sp.get('name')}! A soft light surrounds you "
                    f"({steps} steps — safer in dungeons)."
                ),
            }
        )
    else:
        outbound.append(msg(ServerMessageType.ERROR, reason="cannot cast on field"))
        return character_id, user_id, outbound, None

    char = await apply_character_patch(character_id, patch) or char
    if info.get("teleported"):
        aoi = await manager.publish_move(
            character_id, int(info["x"]), int(info["y"]), seq=None
        )
        outbound.extend(aoi)
        outbound.append(
            msg(
                ServerMessageType.MOVE_OK,
                ok=True,
                x=int(info["x"]),
                y=int(info["y"]),
                seq=None,
                reason="spell",
            )
        )

    # Casting is multiplayer activity — clear AFK for peers
    was_afk_cast = manager.mark_active(character_id)
    if was_afk_cast:
        await manager.publish_status(character_id, pulse_online=True)

    char["known_spells"] = battle_spells_at(int(char["level"]))
    char["field_spells"] = field_spells_at(int(char["level"]))
    char["bonuses"] = equipment_bonuses(char)
    outbound.append(
        _census(
            character_id,
            msg(ServerMessageType.SPELL_CAST, character=char, **info),
        )
    )
    return character_id, user_id, outbound, None
