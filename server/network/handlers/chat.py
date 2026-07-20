"""Public chat channels (extracted): global · nearby AOI · zone yell/shout.

channel=whisper delegates to whisper handler (private_social_delivery).
Reserved system channels rejected before rate limit. Zone chat only from
town/field/dungeon (validated before rate). Peers via broadcast; self always
via outbound once for reliable local echo.
"""

from __future__ import annotations

from typing import Any

from game.world_manager import zone_at
from network.handlers import whisper as whisper_handlers
from network.handlers._common import sanitize_chat
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import _is_idle, manager

CHAT_TYPES = frozenset(
    {
        ClientMessageType.CHAT,
        ClientMessageType.SAY,
        "chat",
        "say",
        "s",
        "g",
        "nearby_chat",
        "yell",
        "shout",
    }
)
ALL_TYPES = CHAT_TYPES


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch public chat / yell. Returns None if not a chat message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    text = sanitize_chat(data.get("text") or data.get("message") or data.get("msg"))
    if text is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="empty chat"))
        return character_id, user_id, outbound, None

    meta = manager.get_meta(character_id)
    name = (meta or {}).get("name") or "Hero"
    # Explicit channel wins; say/s/nearby_chat → nearby; g → global; yell/shout → zone
    channel = (data.get("channel") or "").lower().strip()
    # Reserved for server-originated traffic only (level-up fanfare, etc.)
    # Check before rate-limit so clients get a clear reason, not chat_rate_limit.
    if channel in ("system", "admin", "server", "gm"):
        outbound.append(msg(ServerMessageType.ERROR, reason="reserved channel"))
        return character_id, user_id, outbound, None
    if channel not in (
        "global",
        "nearby",
        "local",
        "whisper",
        "zone",
        "area",
        "shout",
        "yell",
    ):
        if msg_type in (ClientMessageType.SAY, "say", "s", "nearby_chat"):
            channel = "nearby"
        elif msg_type == "g":
            channel = "global"
        elif msg_type in ("yell", "shout"):
            channel = "zone"
        else:
            channel = "global"
    if channel == "local":
        channel = "nearby"
    if channel == "area":
        channel = "zone"
    # Shout/yell = same-zone broadcast (multiplayer area shout, not global spam)
    if channel in ("shout", "yell"):
        channel = "zone"

    # chat with channel=whisper → private path (shared with /w)
    if channel == "whisper":
        wdata = dict(data)
        wdata["type"] = "whisper"
        if "text" not in wdata:
            wdata["text"] = text
        return await whisper_handlers.handle(
            character_id, user_id, wdata, outbound
        )

    was_idle = _is_idle(meta) if meta else False
    zone_name = None
    if meta is not None:
        try:
            zone_name = zone_at(int(meta["x"]), int(meta["y"]))
        except Exception:
            zone_name = None
    # Zone chat only from walkable social zones (not water/wall)
    # Before rate burn — invalid zone must not lock out chat.
    if channel == "zone" and zone_name not in ("town", "field", "dungeon"):
        outbound.append(msg(ServerMessageType.ERROR, reason="not in a zone"))
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

    chat_msg: dict[str, Any] = msg(
        ServerMessageType.CHAT,
        player_id=character_id,
        name=name,
        text=text,
        channel=channel,
        zone=zone_name if channel == "zone" else None,
    )
    sid_c = manager.session_id(character_id)
    if sid_c is not None:
        chat_msg["session_id"] = sid_c

    # Peers via broadcast (exclude self); self always via outbound once
    # so local UI never loses the echo if a peer-send races/fails.
    if channel == "nearby":
        await manager.broadcast_nearby(
            character_id, chat_msg, include_self=False, respect_ignore=True
        )
    elif channel == "zone":
        await manager.broadcast_zone(
            character_id, chat_msg, include_self=False, respect_ignore=True
        )
    else:
        await manager.broadcast(
            chat_msg,
            exclude=character_id,
            from_id=character_id,
            respect_ignore=True,
        )

    # Self echo census (after broadcast — peers already got the core payload)
    echo = dict(chat_msg)
    echo["online"] = len(manager.online_ids())
    echo["nearby_count"] = len(manager.ids_nearby(character_id))
    if zone_name in ("town", "field", "dungeon") and channel != "zone":
        echo["speaker_zone"] = zone_name
    outbound.append(echo)
    if was_idle:
        await manager.publish_status(character_id)
    return character_id, user_id, outbound, None
