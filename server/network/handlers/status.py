"""Self status / sheet peeks (extracted from message_handler).

Rate-exempt multiplayer self card: HP/MP/gold/zone plus nearby census and
a plain message. Social snapshot summary when soft-reconnect peers exist.
"""

from __future__ import annotations

from typing import Any

from game.combat_engine import combat_engine
from game.data_loader import battle_spells_at, field_spells_at
from game.item_manager import equipment_bonuses
from game.player_manager import get_character
from game.progression import xp_to_next_level
from game.world_manager import SPAWN_X, SPAWN_Y, zone_at
from network.handlers._common import soft_reconnect_social_snapshot
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import _is_idle, manager

STATUS_TYPES = frozenset(
    {
        ClientMessageType.STATUS,
        ClientMessageType.ME,
        "status",
        "me",
        "whoami",
        "stats",
        "sheet",
    }
)


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch status/me. Returns None if msg_type is not a status peek."""
    msg_type = data.get("type")
    if msg_type not in STATUS_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None
    manager.touch(character_id)
    char = await get_character(character_id)
    meta = manager.get_meta(character_id)
    if not char:
        outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
        return character_id, user_id, outbound, None
    x = int(meta["x"]) if meta else int(char.get("world_x") or SPAWN_X)
    y = int(meta["y"]) if meta else int(char.get("world_y") or SPAWN_Y)
    try:
        z = zone_at(x, y)
    except Exception:
        z = None

    xp_prog = xp_to_next_level(
        int(char.get("experience") or 0),
        int(char.get("level") or 1),
    )
    bonuses = equipment_bonuses(char)

    you_afk = bool(meta.get("afk")) if meta else False
    you_idle = _is_idle(meta) if meta else False
    nearby_n = len(manager.ids_nearby(character_id))
    nearby_afk = manager.nearby_afk_count(character_id)
    nearby_combat = manager.nearby_combat_count(character_id)
    online_n = len(manager.online_ids())
    afk_n = manager.afk_count()
    in_combat = combat_engine.is_in_combat(character_id)
    repel_n = manager.repel_remaining(character_id)
    radiant_n = manager.radiant_remaining(character_id)
    social = soft_reconnect_social_snapshot(manager, character_id)

    you_status: dict[str, Any] = {
        "x": x,
        "y": y,
        "zone": z,
        "in_combat": in_combat,
        "repel": repel_n,
        "radiant": radiant_n,
        "session_id": manager.session_id(character_id),
        "afk": you_afk,
        "idle": you_idle,
        "nearby_count": nearby_n,
        "nearby_afk": nearby_afk,
        "nearby_combat": nearby_combat,
    }
    if you_afk and meta is not None:
        am = meta.get("afk_message")
        if isinstance(am, str) and am.strip():
            you_status["afk_message"] = am.strip()[:48]

    # Compact multiplayer social summary (no protocol dump — names only)
    social_bits: list[str] = []
    if social.get("has_whisper") and social.get("last_whisper"):
        social_bits.append(f"whisper {social['last_whisper'].get('name')}")
    if social.get("has_share"):
        st = social.get("last_share_to") or social.get("last_share_from") or {}
        if st.get("name"):
            social_bits.append(f"share {st['name']}")
    if social.get("has_emote"):
        et = social.get("last_emote_to") or social.get("last_emote_from") or {}
        if et.get("name"):
            social_bits.append(f"emote {et['name']}")
    if social.get("has_invite"):
        it = social.get("last_invite_from") or social.get("last_invite_to") or {}
        if it.get("name"):
            social_bits.append(f"meetup {it['name']}")

    name = char.get("name") or "Hero"
    lvl = char.get("level") or 1
    hp = char.get("current_hp")
    mhp = char.get("max_hp")
    zone_bit = f" · {z}" if z else ""
    near_bit = f" · {nearby_n} nearby" if nearby_n else ""
    afk_bit = " · AFK" if you_afk else ""
    fight_bit = " · fighting" if in_combat else ""
    status_msg = (
        f"{name} L{lvl} · HP {hp}/{mhp}{zone_bit} · "
        f"{online_n} online{near_bit}{afk_bit}{fight_bit}."
    )
    if social_bits:
        status_msg += " Social: " + ", ".join(social_bits[:3]) + "."

    outbound.append(
        msg(
            ServerMessageType.STATUS,
            character={
                "id": character_id,
                "name": char.get("name"),
                "level": char.get("level"),
                "current_hp": char.get("current_hp"),
                "max_hp": char.get("max_hp"),
                "current_mp": char.get("current_mp"),
                "max_mp": char.get("max_mp"),
                "gold": char.get("gold"),
                "strength": char.get("strength"),
                "agility": char.get("agility"),
                "experience": char.get("experience"),
                "xp_progress": xp_prog,
                "equipment_weapon": char.get("equipment_weapon"),
                "equipment_armor": char.get("equipment_armor"),
                "equipment_shield": char.get("equipment_shield"),
                "equipment_helmet": char.get("equipment_helmet"),
                "bonuses": bonuses,
                "known_spells": battle_spells_at(int(char.get("level") or 1)),
                "field_spells": field_spells_at(int(char.get("level") or 1)),
            },
            you=you_status,
            online=online_n,
            afk_count=afk_n,
            nearby_count=nearby_n,
            nearby_afk=nearby_afk,
            nearby_combat=nearby_combat,
            zones=manager.zone_counts(),
            has_social=bool(social_bits),
            message=status_msg,
        )
    )
    return character_id, user_id, outbound, None
