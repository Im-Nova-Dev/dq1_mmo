"""Meetup invite (extracted). Lightweight multiplayer social — not a party.

Uses private_social_delivery so failed sends refund chat and restore AFK.
Tracks invite_to / invite_from for soft reconnect; supersede/retarget hygiene.
Coords only when already nearby (same privacy model as look).
"""

from __future__ import annotations

from typing import Any

from game.world_manager import zone_at
from network.handlers._common import (
    _afk_snap,
    _resolve_social_peer,
    _social_alias,
    best_effort_send,
    peer_status_suffix,
    private_social_delivery,
    social_peer_card,
)
from network.protocol import ServerMessageType, msg
from network.websocket_manager import _is_idle, coerce_character_id, manager

INVITE_TYPES = frozenset({"invite", "meet", "beckon", "come"})
ALL_TYPES = INVITE_TYPES


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch invite/meet. Returns None if not an invite message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    target_name = data.get("to") or data.get("name") or data.get("target") or data.get(
        "player"
    )
    social_mode = _social_alias(target_name, data)
    raw_pid = None
    if data.get("to_id") is not None:
        raw_pid = data.get("to_id")
    elif data.get("player_id") is not None:
        raw_pid = data.get("player_id")
    target_id = (
        manager.find_id_by_player_id(raw_pid) if raw_pid is not None else None
    )
    if raw_pid is not None and target_id is None:
        if coerce_character_id(raw_pid) is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
        else:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
        return character_id, user_id, outbound, None
    if social_mode and target_id is None:
        # @last: whisper/emote; @pending: meetup peer (invite back / re-send)
        chain = (
            ("whisper", "emote")
            if social_mode == "last"
            else ("invite_from", "invite_to")
        )
        lid, lname, empty = _resolve_social_peer(
            manager, character_id, social_mode, chain=chain
        )
        if lid is None:
            outbound.append(
                msg(
                    ServerMessageType.ERROR,
                    reason=empty or "no one to invite",
                )
            )
            return character_id, user_id, outbound, None
        target_id = lid
        target_name = lname
    if target_id is None and isinstance(target_name, str) and target_name.strip():
        if not social_mode:
            tid, nerr = manager.resolve_live_name(target_name)
            if nerr == "name ambiguous":
                outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                return character_id, user_id, outbound, None
            target_id = tid
    if target_id is None:
        if (
            not (isinstance(target_name, str) and target_name.strip())
            and raw_pid is None
            and not social_mode
        ):
            outbound.append(msg(ServerMessageType.ERROR, reason="invite target required"))
        else:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
        return character_id, user_id, outbound, None
    if target_id == character_id:
        outbound.append(msg(ServerMessageType.ERROR, reason="cannot invite yourself"))
        return character_id, user_id, outbound, None
    if target_id not in manager.online_ids():
        outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
        return character_id, user_id, outbound, None
    if manager.is_ignored_by(target_id, character_id):
        outbound.append(msg(ServerMessageType.ERROR, reason="player unavailable"))
        return character_id, user_id, outbound, None
    if manager.is_ignored_by(character_id, target_id):
        outbound.append(msg(ServerMessageType.ERROR, reason="you ignore that player"))
        return character_id, user_id, outbound, None

    meta_pre = manager.get_meta(character_id)
    was_idle = _is_idle(meta_pre) if meta_pre else False
    was_afk, afk_msg_snap = _afk_snap(meta_pre)
    ok_chat, retry = manager.allow_chat(character_id)
    if not ok_chat:
        outbound.append(
            msg(
                ServerMessageType.ERROR,
                reason="chat_rate_limit",
                retry_after=round(retry, 3),
            )
        )
        return character_id, user_id, outbound, None

    meta = manager.get_meta(character_id)
    tmeta = manager.get_meta(target_id)
    name = (meta or {}).get("name") or "Hero"
    tname = (tmeta or {}).get("name") or (
        target_name.strip() if isinstance(target_name, str) else "Hero"
    )
    you_zone = None
    you_x = you_y = None
    if meta is not None:
        try:
            you_x, you_y = int(meta["x"]), int(meta["y"])
            you_zone = zone_at(you_x, you_y)
        except Exception:
            you_zone = None
    zone_bit = (
        f" in the {you_zone}"
        if you_zone in ("town", "field", "dungeon")
        else " on the map"
    )
    invite_line = f"{name} invites you to meet them{zone_bit}."
    invite_msg: dict[str, Any] = {
        "type": "invite",
        "from": name,
        "from_id": character_id,
        "to": tname,
        "to_id": target_id,
        "message": invite_line,
        "zone": you_zone,
    }
    # Share coords only when already nearby (same privacy model as look)
    if target_id in set(manager.ids_nearby(character_id)):
        invite_msg["x"] = you_x
        invite_msg["y"] = you_y
        invite_msg["nearby"] = True
    else:
        invite_msg["nearby"] = False
    sid_i = manager.session_id(character_id)
    if sid_i is not None:
        invite_msg["session_id"] = sid_i
    if not await private_social_delivery(
        character_id,
        target_id,
        invite_msg,
        was_afk=was_afk,
        afk_message=afk_msg_snap,
        outbound=outbound,
    ):
        return character_id, user_id, outbound, None

    # Both sides track social peer for /r · /thank @last after invite
    manager.note_whisper_from(character_id, target_id, tname)
    manager.note_whisper_from(target_id, character_id, name)
    # Target remembers inviter for /accept · /lastinvite (soft-grace)
    prev_inviter = manager.note_invite_from(target_id, character_id, name)
    # Inviter remembers target for /cancel
    prev_guest = manager.note_invite_to(character_id, target_id, tname)
    # Multiplayer hygiene: notify peers whose pending invite was replaced
    if prev_inviter is not None and prev_inviter in manager.online_ids():
        if not manager.is_ignored_by(prev_inviter, character_id):
            sup: dict[str, Any] = {
                "type": "invite_superseded",
                "to": tname,
                "to_id": target_id,
                "message": f"{tname} received another meetup invite.",
            }
            sid_sup = manager.session_id(character_id)
            if sid_sup is not None:
                sup["session_id"] = sid_sup
            await best_effort_send(prev_inviter, sup)
    if prev_guest is not None and prev_guest in manager.online_ids():
        if not manager.is_ignored_by(prev_guest, character_id):
            prev_meta = manager.get_meta(prev_guest)
            prev_name = (prev_meta or {}).get("name") or "Hero"
            retarget_msg: dict[str, Any] = {
                "type": "invite_cancel",
                "from": name,
                "from_id": character_id,
                "to": prev_name,
                "to_id": prev_guest,
                "message": f"{name} cancelled their meetup invite.",
                "reason": "retarget",
            }
            sid_rt = manager.session_id(character_id)
            if sid_rt is not None:
                retarget_msg["session_id"] = sid_rt
            await best_effort_send(prev_guest, retarget_msg)

    peer = social_peer_card(manager, target_id, tname, viewer_id=character_id)
    suffix = peer_status_suffix(peer) if peer else ""
    echo = dict(invite_msg)
    echo["message"] = f"Invite sent to {tname}{suffix}."
    if peer and peer.get("zone") and "zone" not in echo:
        echo["peer_zone"] = peer["zone"]
    target_afk = bool((tmeta or {}).get("afk"))
    if target_afk:
        echo["target_afk"] = True
        am = (tmeta or {}).get("afk_message")
        if isinstance(am, str) and am.strip():
            echo["target_afk_message"] = am.strip()[:48]
    echo["online"] = len(manager.online_ids())
    echo["nearby_count"] = len(manager.ids_nearby(character_id))
    outbound.append(echo)
    if was_idle:
        await manager.publish_status(character_id)
    return character_id, user_id, outbound, None
