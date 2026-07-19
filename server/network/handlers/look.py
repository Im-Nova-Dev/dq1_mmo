"""Look / examine multiplayer peeks (extracted from message_handler).

Rate-exempt social inspection: coords only when AOI-near (or self).
Supports social aliases (@last, @share, @emote, @pending, …).
"""

from __future__ import annotations

import time
from typing import Any

from game.world_manager import zone_at
from network.handlers._common import _resolve_social_peer, _social_alias
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import coerce_character_id, manager
from network.websocket_manager import _is_idle

LOOK_TYPES = frozenset(
    {
        ClientMessageType.LOOK,
        ClientMessageType.EXAMINE,
        "look",
        "examine",
        "inspect",
        "profile",
        "card",
        "player_info",
        "whereis",
        "where_is",
    }
)


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch look/examine. Returns None if msg_type is not a look peek."""
    msg_type = data.get("type")
    if msg_type not in LOOK_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None
    manager.touch(character_id)
    target_name = data.get("name") or data.get("to") or data.get("target") or data.get(
        "player"
    )
    raw_pid = (
        data.get("player_id") if data.get("player_id") is not None else data.get("id")
    )
    tid: int | None = None
    had_raw_pid = raw_pid is not None
    if had_raw_pid:
        tid = coerce_character_id(raw_pid)
        # Explicit but invalid id (bool/float/garbage) → not found, not bare-self
        if tid is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
            return character_id, user_id, outbound, None
    social_mode = _social_alias(target_name, data)
    if tid is None and social_mode:
        lid, lname, empty = _resolve_social_peer(manager, character_id, social_mode)
        if lid is None:
            outbound.append(
                msg(
                    ServerMessageType.ERROR,
                    reason=empty
                    if social_mode
                    in ("pending", "share", "share_from", "emote", "emote_from")
                    else "no one to look at",
                )
            )
            return character_id, user_id, outbound, None
        tid = lid
        target_name = lname
    if tid is None and isinstance(target_name, str) and target_name.strip():
        if not social_mode:
            tid, nerr = manager.resolve_live_name(target_name)
            if nerr == "name ambiguous":
                outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                return character_id, user_id, outbound, None
            if tid is None and nerr == "player not online":
                # Named target resolved to nobody live — not "not found" (typo vs offline)
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
                return character_id, user_id, outbound, None
    # Bare look / empty name → examine self (MVP social convenience)
    if tid is None and not had_raw_pid and (
        target_name is None
        or (isinstance(target_name, str) and not target_name.strip())
    ):
        tid = character_id
    if tid is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
        return character_id, user_id, outbound, None
    tmeta = manager.get_meta(tid)
    if tmeta is None or tid not in manager.online_ids():
        outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
        return character_id, user_id, outbound, None
    nearby_ids = set(manager.ids_nearby(character_id))
    is_near = tid == character_id or tid in nearby_ids
    card: dict[str, Any] = {
        "id": tid,
        "name": tmeta.get("name"),
        "level": tmeta.get("level"),
        "in_combat": bool(tmeta.get("in_combat")),
        "nearby": is_near,
        "afk": bool(tmeta.get("afk")),
    }
    # Zone type is OK without coords (same privacy model as who/find)
    try:
        tz = zone_at(int(tmeta["x"]), int(tmeta["y"]))
        if tz in ("town", "field", "dungeon"):
            card["zone"] = tz
    except Exception:
        pass
    if is_near:
        card["x"] = tmeta.get("x")
        card["y"] = tmeta.get("y")
        card["map_id"] = tmeta.get("map_id")
    # Soft AFK flag (no coords when far)
    try:
        card["idle"] = _is_idle(tmeta)
        if card["afk"]:
            since = float(tmeta.get("afk_since") or 0.0)
            if since > 0:
                card["afk_for"] = max(0, int(time.monotonic() - since))
            am = tmeta.get("afk_message")
            if isinstance(am, str) and am.strip():
                card["afk_message"] = am.strip()[:48]
    except Exception:
        card["idle"] = False
    sid = tmeta.get("session_id")
    if sid is not None:
        card["session_id"] = sid
    # Plain multiplayer line for clients that only show message
    nm = card.get("name") or "Hero"
    if is_near:
        try:
            lx, ly = int(card.get("x") or 0), int(card.get("y") or 0)
            where = f" nearby @ ({lx},{ly})"
        except (TypeError, ValueError):
            where = " nearby"
    else:
        z = card.get("zone")
        where = f" in the {z}" if z else " (far)"
    afk_bit = " · AFK" if card.get("afk") else ""
    fight_bit = " · fighting" if card.get("in_combat") else ""
    look_msg = f"{nm}{where}{afk_bit}{fight_bit}."
    outbound.append(
        msg(
            ServerMessageType.LOOK,
            player=card,
            nearby=is_near,
            message=look_msg,
        )
    )
    return character_id, user_id, outbound, None
