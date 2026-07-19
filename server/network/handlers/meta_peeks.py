"""Ops / session meta peeks: version · played · time (extracted).

Rate-exempt multiplayer helpers used under peek spam. Share census fields with
ping/status so clients stay oriented after soft reconnect and during AFK.
"""

from __future__ import annotations

import time
from typing import Any

from config import PROCESS_STARTED_AT, VERSION as _VER
from game.combat_engine import combat_engine
from game.world_manager import zone_at
from network.handlers._common import _format_uptime
from network.protocol import ServerMessageType, msg
from network.websocket_manager import _is_idle, manager

VERSION_TYPES = frozenset({"version", "ver", "about", "server", "info"})
PLAYED_TYPES = frozenset({"played", "session", "session_time", "online_time"})
TIME_TYPES = frozenset({"time", "uptime", "servertime", "clock"})

ALL_TYPES = VERSION_TYPES | PLAYED_TYPES | TIME_TYPES


def _zone_of_meta(meta: dict[str, Any] | None) -> str | None:
    if not meta:
        return None
    try:
        z = zone_at(int(meta["x"]), int(meta["y"]))
        return z if z in ("town", "field", "dungeon") else None
    except Exception:
        return None


def _pretty_session_age(age: int) -> str:
    h, rem = divmod(max(0, int(age)), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch version/played/time. Returns None if not a meta peek."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if msg_type in VERSION_TYPES:
        if character_id is not None:
            manager.touch(character_id)
        online_n = len(manager.online_ids())
        afk_n = manager.afk_count()
        combat_n = manager.combat_count()
        zones = manager.zone_counts()
        up = max(0, int(time.time() - PROCESS_STARTED_AT))
        body: dict[str, Any] = {
            "type": "version",
            "version": _VER,
            "online": online_n,
            "afk_count": afk_n,
            "combat_count": combat_n,
            "zones": zones,
            "uptime": up,
            "service": "dq1-mmo",
            "message": f"dq1-mmo {_VER} · {online_n} online · up {_format_uptime(up)}",
        }
        if character_id is not None:
            body["nearby_count"] = len(manager.ids_nearby(character_id))
            body["nearby_afk"] = manager.nearby_afk_count(character_id)
            body["nearby_combat"] = manager.nearby_combat_count(character_id)
            body["session_id"] = manager.session_id(character_id)
            meta = manager.get_meta(character_id)
            body["zone"] = _zone_of_meta(meta)
            body["in_combat"] = combat_engine.is_in_combat(character_id)
        outbound.append(body)
        return character_id, user_id, outbound, None

    if msg_type in PLAYED_TYPES:
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        meta = manager.get_meta(character_id)
        if not meta:
            outbound.append(msg(ServerMessageType.ERROR, reason="not online"))
            return character_id, user_id, outbound, None
        started = float(meta.get("session_started") or 0.0)
        now = time.monotonic()
        age = max(0, int(now - started)) if started else 0
        pretty = _pretty_session_age(age)
        you_zone = _zone_of_meta(meta)
        you_afk = bool(meta.get("afk"))
        in_combat = combat_engine.is_in_combat(character_id)
        nearby_n = len(manager.ids_nearby(character_id))
        zone_bit = f" · {you_zone}" if you_zone else ""
        fight_bit = " · fighting" if in_combat else ""
        near_bit = f" · {nearby_n} nearby" if nearby_n else ""
        body = {
            "type": "played",
            "seconds": age,
            "session_id": manager.session_id(character_id),
            "name": meta.get("name"),
            "zone": you_zone,
            "online": len(manager.online_ids()),
            "afk_count": manager.afk_count(),
            "combat_count": manager.combat_count(),
            "nearby_count": nearby_n,
            "nearby_afk": manager.nearby_afk_count(character_id),
            "nearby_combat": manager.nearby_combat_count(character_id),
            "afk": you_afk,
            "idle": _is_idle(meta),
            "in_combat": in_combat,
            "message": f"This session: {pretty}.{zone_bit}{fight_bit}{near_bit}",
        }
        if you_afk:
            am = meta.get("afk_message")
            if isinstance(am, str) and am.strip():
                body["afk_message"] = am.strip()[:48]
        outbound.append(body)
        return character_id, user_id, outbound, None

    if msg_type in TIME_TYPES:
        if character_id is not None:
            manager.touch(character_id)
        now = time.time()
        up = max(0, int(now - PROCESS_STARTED_AT))
        online_n = len(manager.online_ids())
        body = {
            "type": "time",
            "server_t": now,
            "uptime": up,
            "uptime_hms": _format_uptime(up),
            "version": _VER,
            "online": online_n,
            "afk_count": manager.afk_count(),
            "combat_count": manager.combat_count(),
            "zones": manager.zone_counts(),
            "message": f"Server up {_format_uptime(up)} · {online_n} online",
        }
        if character_id is not None:
            body["nearby_count"] = len(manager.ids_nearby(character_id))
            body["session_id"] = manager.session_id(character_id)
            meta = manager.get_meta(character_id)
            body["zone"] = _zone_of_meta(meta)
        outbound.append(body)
        return character_id, user_id, outbound, None

    return None
