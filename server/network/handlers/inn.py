"""Town inn rest (extracted).

Multiplayer reliability: combat-gated, town presence required, quote path
before pay, successful rest mark_active + publish_status so AFK peers clear.
Echo includes online/nearby census for room orientation.
"""

from __future__ import annotations

from typing import Any

from database.db import db_write
from game.combat_engine import combat_engine
from game.data_loader import battle_spells_at
from game.item_manager import _safe_gold, equipment_bonuses
from game.player_manager import get_character, inn_cost, rest_at_inn
from game.world_manager import zone_at
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import manager

INN_TYPES = frozenset({ClientMessageType.REST, "rest", "inn", "sleep"})
ALL_TYPES = INN_TYPES


def _census(character_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    payload["online"] = len(manager.online_ids())
    payload["nearby_count"] = len(manager.ids_nearby(character_id))
    payload["zone"] = "town"
    return payload


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch rest/inn. Returns None if not an inn message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    if combat_engine.is_in_combat(character_id):
        outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
        return character_id, user_id, outbound, None

    meta = manager.get_meta(character_id)
    if not meta or zone_at(int(meta["x"]), int(meta["y"])) != "town":
        outbound.append(msg(ServerMessageType.ERROR, reason="inn only in town"))
        return character_id, user_id, outbound, None

    char = await get_character(character_id)
    if not char:
        outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
        return character_id, user_id, outbound, None

    # Preview cost when asked (R once / /inn quote)
    if data.get("preview") or data.get("quote"):
        cost = inn_cost(char)
        full = (
            int(char.get("current_hp") or 0) >= int(char.get("max_hp") or 1)
            and int(char.get("current_mp") or 0) >= int(char.get("max_mp") or 0)
        )
        quote = msg(
            ServerMessageType.REST_OK,
            preview=True,
            cost=cost,
            can_afford=_safe_gold(char) >= cost,
            full=full,
            message=(
                "You are already well rested."
                if full
                else f"Inn stay costs {cost} G"
            ),
        )
        outbound.append(_census(character_id, quote))
        return character_id, user_id, outbound, None

    async with db_write() as db:
        ok, reason, info = await rest_at_inn(db, char)
    if not ok:
        err = msg(ServerMessageType.ERROR, reason=reason, **(info or {}))
        outbound.append(_census(character_id, err) if isinstance(err, dict) else err)
        return character_id, user_id, outbound, None

    was_afk = manager.mark_active(character_id)
    if was_afk:
        await manager.publish_status(character_id, pulse_online=True)

    char = await get_character(character_id) or char
    char["known_spells"] = battle_spells_at(int(char["level"]))
    char["bonuses"] = equipment_bonuses(char)
    ok_msg = msg(
        ServerMessageType.REST_OK, preview=False, character=char, **info
    )
    cost = info.get("cost") if isinstance(info, dict) else None
    if cost is not None:
        ok_msg["message"] = f"Rested at the inn for {cost} G."
    else:
        ok_msg["message"] = "You feel well rested."
    outbound.append(_census(character_id, ok_msg))
    return character_id, user_id, outbound, None
