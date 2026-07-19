"""Presence multiplayer peeks: who/near/counts/zone/fighting (extracted)."""

from __future__ import annotations

from typing import Any

from game.world_manager import zone_at
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import manager

WHO_TYPES = frozenset({ClientMessageType.WHO, "who", "players", "online_list"})
NEAR_TYPES = frozenset({"near", "nearby_list", "here"})
COUNTS_TYPES = frozenset({"counts", "census", "population"})
ZONE_TYPES = frozenset({
    "zone", "where", "area", "whereami", "coords", "pos", "position", "mapinfo",
})
FIGHTING_TYPES = frozenset({"fighting", "combats", "battles", "in_combat", "combat_near"})
ALL_TYPES = WHO_TYPES | NEAR_TYPES | COUNTS_TYPES | ZONE_TYPES | FIGHTING_TYPES


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if msg_type in (ClientMessageType.WHO, "who", "players", "online_list"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        meta = manager.get_meta(character_id)
        nearby = manager.nearby_players(character_id)
        you_zone = None
        if meta is not None:
            try:
                you_zone = zone_at(int(meta["x"]), int(meta["y"]))
            except Exception:
                you_zone = None
        from network.websocket_manager import _is_idle

        outbound.append(
            msg(
                ServerMessageType.WHO,
                players=nearby,
                nearby_count=len(nearby),
                online=len(manager.online_ids()),
                online_ids=manager.online_ids(),
                roster=manager.online_roster(),
                zones=manager.zone_counts(),
                afk_count=manager.afk_count(),
                combat_count=manager.combat_count(),
                nearby_afk=manager.nearby_afk_count(character_id),
                nearby_combat=manager.nearby_combat_count(character_id),
                you={
                    "id": character_id,
                    "name": (meta or {}).get("name"),
                    "level": (meta or {}).get("level"),
                    "x": meta["x"] if meta else None,
                    "y": meta["y"] if meta else None,
                    "in_combat": bool(meta.get("in_combat")) if meta else False,
                    "idle": _is_idle(meta) if meta else False,
                    "afk": bool((meta or {}).get("afk")),
                    "session_id": manager.session_id(character_id),
                    "repel": manager.repel_remaining(character_id),
                    "radiant": manager.radiant_remaining(character_id),
                    "zone": you_zone,
                },
            )
        )
        # Optional AFK reason on self card
        who_msg = outbound[-1]
        you_card = who_msg.get("you") if isinstance(who_msg, dict) else None
        if (
            isinstance(you_card, dict)
            and you_card.get("afk")
            and meta is not None
        ):
            am = meta.get("afk_message")
            if isinstance(am, str) and am.strip():
                you_card["afk_message"] = am.strip()[:48]
        return character_id, user_id, outbound, None

    # --- Nearby-only roster (lighter than full /who) ---
    if msg_type in ("near", "nearby_list", "here"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        nearby = manager.nearby_players(character_id)
        meta = manager.get_meta(character_id)
        you_zone = None
        if meta is not None:
            try:
                you_zone = zone_at(int(meta["x"]), int(meta["y"]))
            except Exception:
                you_zone = None
        nearby_afk = manager.nearby_afk_count(character_id)
        nearby_combat = manager.nearby_combat_count(character_id)
        afk_n = manager.afk_count()
        near_body = {
            "type": "near",
            "players": nearby,
            "nearby_count": len(nearby),
            "nearby_afk": nearby_afk,
            "nearby_combat": nearby_combat,
            "afk_count": afk_n,
            "online": len(manager.online_ids()),
            "zone": you_zone,
            "zones": manager.zone_counts(),
            "message": (
                f"{len(nearby)} nearby · combat {nearby_combat} · "
                f"AFK {nearby_afk} · {afk_n} AFK online"
            ),
        }
        you_afk = bool((meta or {}).get("afk"))
        near_body["you"] = {
            "id": character_id,
            "name": (meta or {}).get("name"),
            "afk": you_afk,
            "zone": you_zone,
            "session_id": manager.session_id(character_id),
        }
        if you_afk and meta is not None:
            am = meta.get("afk_message")
            if isinstance(am, str) and am.strip():
                near_body["you"]["afk_message"] = am.strip()[:48]
        outbound.append(near_body)
        return character_id, user_id, outbound, None

    # --- Lightweight census (online + zone counts, no full roster) ---
    if msg_type in ("counts", "census", "population"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        zones = manager.zone_counts()
        online_n = len(manager.online_ids())
        nearby_n = len(manager.ids_nearby(character_id))
        sid = manager.session_id(character_id)
        meta = manager.get_meta(character_id)
        from network.websocket_manager import _is_idle as _idle_chk
        from game.world_manager import zone_at as _z_at

        you_zone = None
        if meta is not None:
            try:
                you_zone = _z_at(int(meta["x"]), int(meta["y"]))
            except Exception:
                you_zone = None
        played_sec = 0
        if meta is not None:
            import time as _time

            try:
                started = float(meta.get("session_started") or 0.0)
                if started > 0:
                    played_sec = max(0, int(_time.monotonic() - started))
            except (TypeError, ValueError):
                played_sec = 0
        you_afk = bool((meta or {}).get("afk"))
        you = {
            "id": character_id,
            "name": (meta or {}).get("name"),
            "nearby_count": nearby_n,
            "afk": you_afk,
            "idle": _idle_chk(meta) if meta else False,
            "zone": you_zone,
            "in_combat": bool((meta or {}).get("in_combat")),
            "played": played_sec,
        }
        if you_afk and meta is not None:
            try:
                import time as _time

                since = float(meta.get("afk_since") or 0.0)
                if since > 0:
                    you["afk_for"] = max(0, int(_time.monotonic() - since))
            except (TypeError, ValueError):
                pass
            am = meta.get("afk_message")
            if isinstance(am, str) and am.strip():
                you["afk_message"] = am.strip()[:48]
        if sid is not None:
            you["session_id"] = sid
        afk_n = manager.afk_count()
        combat_n = manager.combat_count()
        nearby_combat = manager.nearby_combat_count(character_id)
        body = {
            "type": "counts",
            "online": online_n,
            "afk_count": afk_n,
            "combat_count": combat_n,
            "nearby_count": nearby_n,
            "nearby_combat": nearby_combat,
            "zones": zones,
            "you": you,
            "session_id": sid,
            "message": (
                f"{online_n} online · AFK {afk_n} · fighting {combat_n} · "
                f"nearby {nearby_n} · near combat {nearby_combat} · "
                f"town {zones.get('town', 0)} · field {zones.get('field', 0)} · "
                f"dungeon {zones.get('dungeon', 0)}"
            ),
        }
        outbound.append(body)
        return character_id, user_id, outbound, None

    # --- Where am I / zone population (multiplayer social) ---
    if msg_type in (
        "zone",
        "where",
        "area",
        "whereami",
        "coords",
        "pos",
        "position",
        "mapinfo",
    ):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        meta = manager.get_meta(character_id)
        you_zone = None
        x = y = None
        if meta is not None:
            try:
                x, y = int(meta["x"]), int(meta["y"])
                you_zone = zone_at(x, y)
            except Exception:
                you_zone = None
        zones = manager.zone_counts()
        # Same-zone roster (public cards, no x/y) for multiplayer social overview
        mates = manager.zone_roster(character_id, include_self=True)
        zone_pop = int(zones.get(you_zone, 0)) if you_zone else len(mates)
        zone_afk = manager.zone_afk_count(character_id, include_self=True)
        zone_combat = manager.zone_combat_count(character_id, include_self=True)
        afk_n = manager.afk_count()
        zone_body = {
            "type": "zone",
            "zone": you_zone,
            "x": x,
            "y": y,
            "zones": zones,
            "players": mates,
            "zone_count": len(mates),
            "zone_afk": zone_afk,
            "zone_combat": zone_combat,
            "afk_count": afk_n,
            "population": zone_pop,
            "online": len(manager.online_ids()),
            "message": (
                f"You are in the {you_zone} ({len(mates)} here · AFK {zone_afk}"
                f" · combat {zone_combat})."
                if you_zone in ("town", "field", "dungeon")
                else "You are somewhere on the map."
            ),
        }
        sid_z = manager.session_id(character_id)
        if sid_z is not None:
            zone_body["session_id"] = sid_z
        outbound.append(zone_body)
        return character_id, user_id, outbound, None

    # --- Look / examine / inspect / profile / whereis (public card; coords if nearby) ---
    if msg_type in ("fighting", "combats", "battles", "in_combat", "combat_near"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        fighters = manager.nearby_combat_roster(character_id)
        n = len(fighters)
        names = [str(p.get("name") or "?") for p in fighters[:8]]
        name_bit = (", ".join(names) + (f" +{n - 8}" if n > 8 else "")) if names else "none"
        outbound.append(
            msg(
                "fighting",
                players=fighters,
                nearby_combat=n,
                nearby_count=len(manager.ids_nearby(character_id)),
                online=len(manager.online_ids()),
                afk_count=manager.afk_count(),
                combat_count=manager.combat_count(),
                message=f"{n} nearby fighting · {name_bit}",
            )
        )
        return character_id, user_id, outbound, None

    return None
