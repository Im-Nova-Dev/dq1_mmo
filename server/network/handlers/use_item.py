"""Use consumable (herb / wings / fairy water) — extracted.

Multiplayer reliability: combat herb is a full turn (awaiting_hero only),
successful use mark_active + publish_status (AFK clear), wings teleport via
publish_move (AOI), defeat respawn AOI. Inventory + item_used echoes include
online/nearby census.
"""

from __future__ import annotations

from typing import Any

from database.db import db_write
from game.combat_engine import combat_engine
from game.data_loader import battle_spells_at
from game.item_manager import equipment_bonuses, use_consumable
from game.player_manager import apply_character_patch, get_character
from game.rng import Rng
from game.world_manager import SPAWN_X, SPAWN_Y, zone_at
from network.handlers._common import (
    _announce_combat_outcome,
    _combat_update,
    _inventory_msg,
    _persist_battle_end,
    _resolve_item_arg,
)
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import manager

USE_TYPES = frozenset(
    {ClientMessageType.USE_ITEM, "use_item", "use", "consume"}
)
ALL_TYPES = USE_TYPES


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
    """Dispatch use_item. Returns None if not a use-item message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    item_raw = data.get("item") or data.get("item_id")
    item_id, item_err = _resolve_item_arg(item_raw)
    if item_err or not item_id:
        outbound.append(
            msg(ServerMessageType.ERROR, reason=item_err or "item required")
        )
        return character_id, user_id, outbound, None

    in_combat = combat_engine.is_in_combat(character_id)
    char = await get_character(character_id)
    if not char:
        outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
        return character_id, user_id, outbound, None

    # Combat item use is a full turn — only on hero phase
    battle = combat_engine.get(character_id) if in_combat else None
    if in_combat:
        if (
            battle is None
            or battle.phase != "awaiting_hero"
            or battle.outcome != "ongoing"
        ):
            outbound.append(msg(ServerMessageType.ERROR, reason="wait for your turn"))
            return character_id, user_id, outbound, None

    async with db_write() as db:
        ok, reason, info = await use_consumable(
            db, char, str(item_id), in_combat=in_combat, rng=Rng()
        )
    if not ok:
        outbound.append(msg(ServerMessageType.ERROR, reason=reason))
        inv_fail = await _inventory_msg(character_id)
        outbound.append(_census(character_id, inv_fail))
        return character_id, user_id, outbound, None

    # Successful use is multiplayer activity — clear AFK for peers
    was_afk_use = manager.mark_active(character_id)
    if was_afk_use:
        await manager.publish_status(character_id, pulse_online=True)

    # Refresh character after use
    char = await get_character(character_id) or char

    if info.get("effect") == "repel":
        manager.set_repel(character_id, int(info.get("repel_steps") or 0))

    if info.get("teleported"):
        tx, ty = int(info["x"]), int(info["y"])
        aoi_msgs = await manager.publish_move(character_id, tx, ty, seq=None)
        outbound.extend(aoi_msgs)
        try:
            tzone = zone_at(tx, ty)
        except Exception:
            tzone = None
        mok = msg(
            ServerMessageType.MOVE_OK,
            ok=True,
            x=tx,
            y=ty,
            seq=None,
            reason="wings",
        )
        if tzone:
            mok["zone"] = tzone
        outbound.append(_census(character_id, mok))

    if in_combat and battle is not None and info.get("effect") == "heal":
        # Spend turn: heal already applied to DB — sync battle HP then enemy acts
        amount = int(info.get("amount_rolled") or info.get("healed") or 0)
        result = battle.act(
            {
                "type": "item",
                "id": str(item_id),
                "name": info.get("name"),
                "effect": "heal",
                "amount": amount,
            }
        )
        if result.get("ok"):
            patch_hp = max(0, int(battle.hero["hp"]))
            patch_mp = max(0, int(battle.hero["mp"]))
            await apply_character_patch(
                character_id,
                {
                    "current_hp": max(1, patch_hp)
                    if battle.outcome == "defeat"
                    else patch_hp,
                    "current_mp": patch_mp,
                },
            )
        events = result.get("events") or []
        outbound.append(_combat_update(battle, events))
        if battle.outcome != "ongoing":
            char = await _persist_battle_end(character_id, battle)
            combat_engine.end(character_id)
            manager.set_in_combat(character_id, False)
            await manager.publish_status(character_id, pulse_online=True)
            end_payload: dict[str, Any] = {
                "result": battle.outcome,
                "xp": (battle.rewards or {}).get("xp", 0),
                "gold": (battle.rewards or {}).get("gold", 0),
                "character": char,
                "events": events,
            }
            if battle.outcome == "defeat":
                end_payload["gold_lost"] = int(char.pop("gold_lost", 0) or 0)
                end_payload["respawn"] = {"x": SPAWN_X, "y": SPAWN_Y}
            outbound.append(msg(ServerMessageType.COMBAT_END, **end_payload))
            await _announce_combat_outcome(character_id, str(battle.outcome))
            if battle.outcome == "defeat":
                aoi_msgs = await manager.publish_move(
                    character_id, SPAWN_X, SPAWN_Y, seq=None
                )
                outbound.extend(aoi_msgs)
                try:
                    rzone = zone_at(SPAWN_X, SPAWN_Y)
                except Exception:
                    rzone = "town"
                outbound.append(
                    msg(
                        ServerMessageType.MOVE_OK,
                        ok=True,
                        x=SPAWN_X,
                        y=SPAWN_Y,
                        seq=None,
                        reason="respawn",
                        zone=rzone,
                    )
                )
        used = msg(ServerMessageType.ITEM_USED, **info, in_combat=True)
        outbound.append(_census(character_id, used))
        inv = await _inventory_msg(character_id)
        outbound.append(_census(character_id, inv))
        return character_id, user_id, outbound, None

    # Overworld use
    char["known_spells"] = battle_spells_at(int(char["level"]))
    char["bonuses"] = equipment_bonuses(char)
    used = msg(ServerMessageType.ITEM_USED, **info, in_combat=False)
    if info.get("effect") == "heal":
        used["message"] = f"Used {info.get('name') or item_id}."
    elif info.get("effect") == "repel":
        used["message"] = "Fairy water — fewer random fights for a while."
    elif info.get("teleported"):
        used["message"] = "Wings! Returned to town."
    outbound.append(_census(character_id, used))
    inv = await _inventory_msg(character_id)
    outbound.append(_census(character_id, inv))
    return character_id, user_id, outbound, None
