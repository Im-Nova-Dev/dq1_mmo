"""Ignore / mute list (extracted). Soft-grace multipplayer mute hygiene.

ignore · unignore · ignores list. Online mute cards carry near/far · zone · AFK
so soft reconnect and /ignores stay useful without leaking map coords.
"""

from __future__ import annotations

from typing import Any

from network.handlers._common import (
    _resolve_social_peer,
    _social_alias,
    peer_status_suffix,
    social_peer_card,
)
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import coerce_character_id, manager

IGNORE_TYPES = frozenset(
    {ClientMessageType.IGNORE, "ignore", "mute", "block"}
)
UNIGNORE_TYPES = frozenset(
    {ClientMessageType.UNIGNORE, "unignore", "unmute", "unblock"}
)
LIST_TYPES = frozenset(
    {
        ClientMessageType.IGNORES,
        "ignores",
        "ignore_list",
        "blocklist",
        "blocks",
    }
)
ALL_TYPES = IGNORE_TYPES | UNIGNORE_TYPES | LIST_TYPES


def _list_message(ignores: list[dict[str, Any]]) -> str:
    if not ignores:
        return "Mute list empty."
    bits: list[str] = []
    for c in ignores[:8]:
        nm = c.get("name") or "?"
        if c.get("online"):
            near = "near" if c.get("nearby") else "far"
            zone = c.get("zone")
            zbit = f"·{zone}" if isinstance(zone, str) and zone else ""
            fight = "·fight" if c.get("in_combat") else ""
            afk = "·afk" if c.get("afk") else ""
            bits.append(f"{nm}[{near}{zbit}{fight}{afk}]")
        else:
            bits.append(f"{nm}(offline)")
    more = f" +{len(ignores) - 8} more" if len(ignores) > 8 else ""
    return f"Mute list ({len(ignores)}): " + ", ".join(bits) + more


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch ignore / unignore / list. Returns None if not a mute message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if msg_type in IGNORE_TYPES:
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        target_name = data.get("name") or data.get("to") or data.get("player")
        target_id = manager.find_id_by_player_id(
            data.get("player_id") or data.get("id") or data.get("to_id")
        )
        social_mode = _social_alias(target_name, data)
        if target_id is None and social_mode:
            lid, lname, empty = _resolve_social_peer(
                manager, character_id, social_mode
            )
            if lid is None:
                outbound.append(
                    msg(
                        ServerMessageType.ERROR,
                        reason=(
                            empty
                            if social_mode
                            in (
                                "pending",
                                "share",
                                "share_from",
                                "emote",
                                "emote_from",
                            )
                            else "no one to ignore"
                        ),
                    )
                )
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and not social_mode:
            target_id, nerr = manager.resolve_live_name(target_name)
            if nerr == "name ambiguous":
                outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                return character_id, user_id, outbound, None
        if target_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        ok, reason = manager.ignore_player(character_id, target_id)
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
            return character_id, user_id, outbound, None
        tmeta = manager.get_meta(target_id)
        peer = social_peer_card(
            manager,
            target_id,
            (tmeta or {}).get("name"),
            viewer_id=character_id,
        )
        pname = (peer or {}).get("name") or (tmeta or {}).get("name") or "Hero"
        suffix = peer_status_suffix(peer) if peer else ""
        ignores = manager.ignore_list(character_id)
        outbound.append(
            msg(
                ServerMessageType.IGNORE,
                action="ignore",
                ok=True,
                reason=reason,
                player={
                    "id": target_id,
                    "name": pname,
                    **(
                        {
                            k: peer[k]
                            for k in (
                                "online",
                                "nearby",
                                "zone",
                                "afk",
                                "in_combat",
                            )
                            if peer and k in peer
                        }
                        if peer
                        else {}
                    ),
                },
                ignores=ignores,
                count=len(ignores),
                message=f"Muted {pname}{suffix}.",
            )
        )
        return character_id, user_id, outbound, None

    if msg_type in UNIGNORE_TYPES:
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        target_name = data.get("name") or data.get("to") or data.get("player")
        target_id = manager.find_id_by_player_id(
            data.get("player_id") or data.get("id") or data.get("to_id")
        )
        social_mode = _social_alias(target_name, data)
        if target_id is None and social_mode:
            lid, lname, empty = _resolve_social_peer(
                manager, character_id, social_mode
            )
            if lid is None:
                outbound.append(
                    msg(
                        ServerMessageType.ERROR,
                        reason=(
                            empty
                            if social_mode
                            in (
                                "pending",
                                "share",
                                "share_from",
                                "emote",
                                "emote_from",
                            )
                            else "no one to unignore"
                        ),
                    )
                )
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and not social_mode:
            target_id, nerr = manager.resolve_live_name(target_name)
            if nerr == "name ambiguous":
                outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                return character_id, user_id, outbound, None
            if target_id is None:
                meta = manager.get_meta(character_id) or {}
                names = meta.get("ignore_names") or {}
                key = target_name.strip().lower()
                for tid, n in names.items():
                    if str(n).strip().lower() == key:
                        try:
                            target_id = int(tid)
                        except (TypeError, ValueError):
                            target_id = None
                        break
        if target_id is None:
            target_id = coerce_character_id(
                data.get("player_id")
                if data.get("player_id") is not None
                else data.get("id")
            )
        if target_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
            return character_id, user_id, outbound, None
        # Capture name before unignore may drop ignore_names cache
        pre_meta = manager.get_meta(character_id) or {}
        pre_names = pre_meta.get("ignore_names") or {}
        cached_name = pre_names.get(target_id) or pre_names.get(str(target_id))
        tmeta = manager.get_meta(target_id)
        pname = (tmeta or {}).get("name") or cached_name or "Hero"
        ok, reason = manager.unignore_player(character_id, target_id)
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
            return character_id, user_id, outbound, None
        ignores = manager.ignore_list(character_id)
        outbound.append(
            msg(
                ServerMessageType.IGNORE,
                action="unignore",
                ok=True,
                reason=reason,
                player_id=target_id,
                player={"id": target_id, "name": str(pname)[:24]},
                ignores=ignores,
                count=len(ignores),
                message=f"Unmuted {str(pname)[:24]}.",
            )
        )
        return character_id, user_id, outbound, None

    if msg_type in LIST_TYPES:
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        ignores = manager.ignore_list(character_id)
        n_on = sum(1 for c in ignores if c.get("online"))
        n_off = len(ignores) - n_on
        n_near = sum(1 for c in ignores if c.get("online") and c.get("nearby"))
        outbound.append(
            msg(
                ServerMessageType.IGNORE,
                action="list",
                ignores=ignores,
                count=len(ignores),
                online_count=n_on,
                offline_count=n_off,
                nearby_count=n_near,
                online=len(manager.online_ids()),
                message=_list_message(ignores),
            )
        )
        return character_id, user_id, outbound, None

    return None
