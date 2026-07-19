"""Social roll / dice (extracted). Nearby 1dN multiplayer icebreaker.

Validate sides before allow_chat so bad rolls never burn rate or clear AFK.
Broadcast system chat to nearby (ignore-bypass) and echo to roller with census.
"""

from __future__ import annotations

import math
import random
from typing import Any

from game.world_manager import zone_at
from network.protocol import ServerMessageType, msg
from network.websocket_manager import manager

ROLL_TYPES = frozenset({"roll", "dice", "d100"})
ALL_TYPES = ROLL_TYPES


def _zone_of_meta(meta: dict[str, Any] | None) -> str | None:
    if not meta:
        return None
    try:
        z = zone_at(int(meta["x"]), int(meta["y"]))
        return z if z in ("town", "field", "dungeon") else None
    except Exception:
        return None


def parse_sides(data: dict[str, Any]) -> tuple[int | None, int | None]:
    """Return (sides, None) or (None, invalid_sides_value_for_error).

    invalid_sides_value is set when range is wrong so callers can echo min/max.
    """
    if "sides" in data:
        raw_sides = data.get("sides")
    elif "d" in data:
        raw_sides = data.get("d")
    else:
        raw_sides = 100
    try:
        if isinstance(raw_sides, bool):
            raise ValueError("bool sides")
        if isinstance(raw_sides, float):
            if not math.isfinite(raw_sides) or not raw_sides.is_integer():
                raise ValueError("float sides")
            sides_i = int(raw_sides)
        elif isinstance(raw_sides, int):
            sides_i = raw_sides
        elif isinstance(raw_sides, str):
            s = raw_sides.strip()
            if not s or not s.lstrip("-").isdigit():
                raise ValueError("str sides")
            sides_i = int(s)
        else:
            sides_i = int(raw_sides)
    except (TypeError, ValueError):
        return None, None
    if sides_i < 2 or sides_i > 1000:
        return None, sides_i
    return sides_i, None


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch roll/dice/d100. Returns None if not a roll message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    # Validate sides BEFORE allow_chat so bad rolls never burn rate or clear AFK.
    sides_i, bad_range = parse_sides(data)
    if sides_i is None and bad_range is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="invalid roll sides"))
        return character_id, user_id, outbound, None
    if sides_i is None:
        outbound.append(
            msg(
                ServerMessageType.ERROR,
                reason="invalid roll sides",
                sides=bad_range,
                min=2,
                max=1000,
            )
        )
        return character_id, user_id, outbound, None

    allowed, retry = manager.allow_chat(character_id)
    if not allowed:
        outbound.append(
            msg(
                ServerMessageType.ERROR,
                reason="chat_rate_limit",
                retry_after=round(retry, 3),
            )
        )
        return character_id, user_id, outbound, None

    meta = manager.get_meta(character_id)
    name = (meta or {}).get("name") or "Hero"
    value = random.randint(1, sides_i)
    zone = _zone_of_meta(meta)
    online_n = len(manager.online_ids())
    nearby_n = len(manager.ids_nearby(character_id))
    zone_bit = f" · {zone}" if zone else ""
    roll_text = f"{name} rolls d{sides_i}: {value}"
    roll_body: dict[str, Any] = {
        "sides": sides_i,
        "value": value,
        "name": name,
        "zone": zone,
        "online": online_n,
        "nearby_count": nearby_n,
    }
    roll_msg = msg(
        ServerMessageType.CHAT,
        player_id=character_id,
        name="System",
        text=roll_text,
        channel="system",
        system=True,
        roll=roll_body,
        zone=zone,
        online=online_n,
        nearby_count=nearby_n,
        message=f"{roll_text}{zone_bit} · {nearby_n} nearby",
    )
    sid_r = manager.session_id(character_id)
    if sid_r is not None:
        roll_msg["session_id"] = sid_r
        roll_msg["roll"]["session_id"] = sid_r
    await manager.broadcast_nearby(
        character_id, roll_msg, include_self=False, respect_ignore=False
    )
    outbound.append(roll_msg)
    return character_id, user_id, outbound, None
