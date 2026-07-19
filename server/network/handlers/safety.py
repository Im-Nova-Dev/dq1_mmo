"""Multiplayer safety: quit · stuck/home (extracted).

Free town recall with combat gate, soft rate limit, nearby notice, and richer
stuck acks (online/nearby census) for soft reconnect orientation.
"""

from __future__ import annotations

from typing import Any

from game.combat_engine import combat_engine
from game.player_manager import apply_character_patch
from game.world_manager import SPAWN_X, SPAWN_Y, zone_at
from network.protocol import ServerMessageType, msg
from network.websocket_manager import manager

QUIT_TYPES = frozenset({"quit", "logout", "exit", "leave_world"})
STUCK_TYPES = frozenset({"stuck", "unstuck", "home", "recall_home"})
ALL_TYPES = QUIT_TYPES | STUCK_TYPES


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch quit/stuck. Returns None if not a safety message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if msg_type in QUIT_TYPES:
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        online_n = len(manager.online_ids())
        zone = None
        if meta is not None:
            try:
                zone = zone_at(int(meta["x"]), int(meta["y"]))
                if zone not in ("town", "field", "dungeon"):
                    zone = None
            except Exception:
                zone = None
        zone_bit = f" · {zone}" if zone else ""
        outbound.append(
            msg(
                "quit",
                ok=True,
                message=f"Farewell, hero.{zone_bit}",
                reason="quit",
                online=max(0, online_n - 1),  # after leave, peers see N-1
                zone=zone,
                session_id=manager.session_id(character_id),
            )
        )
        try:
            await manager.disconnect(character_id, reason="quit")
        except Exception:
            pass
        return None, user_id, outbound, None

    # stuck / home
    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None
    if combat_engine.is_in_combat(character_id):
        outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
        return character_id, user_id, outbound, None
    meta = manager.get_meta(character_id)
    if not meta:
        outbound.append(msg(ServerMessageType.ERROR, reason="not online"))
        return character_id, user_id, outbound, None
    try:
        cx, cy = int(meta["x"]), int(meta["y"])
    except Exception:
        cx, cy = SPAWN_X, SPAWN_Y
    already = cx == SPAWN_X and cy == SPAWN_Y and zone_at(cx, cy) == "town"
    online_n = len(manager.online_ids())
    nearby_n = len(manager.ids_nearby(character_id))

    # Already home: no rate burn, no teleport — still activity (clear AFK badge)
    if already:
        was_afk_home = manager.mark_active(character_id)
        if was_afk_home:
            await manager.publish_status(character_id, pulse_online=True)
        outbound.append(
            msg(
                "stuck",
                ok=True,
                x=SPAWN_X,
                y=SPAWN_Y,
                zone="town",
                teleported=False,
                session_id=manager.session_id(character_id),
                message="You are already in town.",
                afk=False,
                online=online_n,
                nearby_count=nearby_n,
                afk_count=manager.afk_count(),
            )
        )
        return character_id, user_id, outbound, None

    # Soft rate limit so stuck cannot be spammed as free teleport
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
    # allow_chat cleared AFK; keep stamps clean (including optional reason)
    meta["afk"] = False
    meta["afk_since"] = None
    meta["afk_message"] = None
    name = meta.get("name") or "Hero"
    char = await apply_character_patch(
        character_id, {"world_x": SPAWN_X, "world_y": SPAWN_Y}
    )
    aoi = await manager.publish_move(character_id, SPAWN_X, SPAWN_Y, seq=None)
    outbound.extend(aoi)
    outbound.append(
        msg(
            ServerMessageType.MOVE_OK,
            ok=True,
            x=SPAWN_X,
            y=SPAWN_Y,
            seq=None,
            reason="stuck",
            zone="town",
        )
    )
    # Nearby system notice — multiplayer awareness of free home recall
    notice = msg(
        ServerMessageType.CHAT,
        player_id=character_id,
        name="System",
        text=f"{name} returned to town.",
        channel="system",
        system=True,
    )
    sid_s = manager.session_id(character_id)
    if sid_s is not None:
        notice["session_id"] = sid_s
    await manager.broadcast_nearby(
        character_id, notice, include_self=False, respect_ignore=False
    )
    await manager.publish_status(character_id, pulse_online=True)
    nearby_after = len(manager.ids_nearby(character_id))
    outbound.append(
        msg(
            "stuck",
            ok=True,
            x=SPAWN_X,
            y=SPAWN_Y,
            zone="town",
            teleported=True,
            session_id=manager.session_id(character_id),
            character=char,
            message="You find your way back to town.",
            online=len(manager.online_ids()),
            nearby_count=nearby_after,
            afk_count=manager.afk_count(),
            afk=False,
        )
    )
    return character_id, user_id, outbound, None
