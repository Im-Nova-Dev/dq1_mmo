"""Accept / decline meetup invite (extracted). Not a party.

Private reply via private_social_delivery (refund chat + restore AFK on fail).
Offline inviter clears soft-grace pointers so /accept|/decline cannot loop.
Invite is consumed only after successful delivery so failed accept can retry.
Coords only when already nearby (same privacy model as invite/look).
"""

from __future__ import annotations

from typing import Any

from network.handlers._common import (
    _afk_snap,
    peer_status_suffix,
    private_social_delivery,
    social_peer_card,
)
from network.protocol import ServerMessageType, msg
from network.websocket_manager import _is_idle, _zone_of, manager

ACCEPT_TYPES = frozenset({"accept", "coming", "invite_accept"})
DECLINE_TYPES = frozenset(
    {"decline", "later", "invite_decline", "pass_invite"}
)
ALL_TYPES = ACCEPT_TYPES | DECLINE_TYPES


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch accept/decline. Returns None if not an invite-reply message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    accepting = msg_type in ACCEPT_TYPES
    lid, lname = manager.last_invite_from(character_id)
    if lid is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="no invite to answer"))
        return character_id, user_id, outbound, None
    if lid not in manager.online_ids():
        # Inviter left — clear stuck invite so /accept|/decline cannot loop forever.
        # Also clear inviter soft-grace last_invite_to so they do not rehydrate
        # a zombie outgoing invite after reconnect.
        manager.clear_last_invite(character_id)
        manager.clear_invite_to_peer(lid, character_id)
        live = lname or "Hero"
        outbound.append(
            msg(
                ServerMessageType.ERROR,
                reason="player not online",
                invite_cleared=True,
                message=f"Invite from {live} cleared (player offline).",
            )
        )
        return character_id, user_id, outbound, None
    if manager.is_ignored_by(lid, character_id):
        outbound.append(msg(ServerMessageType.ERROR, reason="player unavailable"))
        return character_id, user_id, outbound, None
    if manager.is_ignored_by(character_id, lid):
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
    tmeta = manager.get_meta(lid)
    name = (meta or {}).get("name") or "Hero"
    tname = (tmeta or {}).get("name") or lname or "Hero"
    # Zone of the person accepting/declining (no coords unless already nearby)
    reply_zone = _zone_of(meta) if meta else None
    zone_bit = (
        f" (from the {reply_zone})"
        if reply_zone in ("town", "field", "dungeon")
        else ""
    )
    if accepting:
        line = f"{name} is coming to meet you{zone_bit}."
        self_line = f"You told {tname} you are coming{zone_bit}."
        action = "accept"
    else:
        line = f"{name} cannot meet right now{zone_bit}."
        self_line = f"You declined {tname}'s invite."
        action = "decline"
    reply_msg: dict[str, Any] = {
        "type": "invite_reply",
        "action": action,
        "from": name,
        "from_id": character_id,
        "to": tname,
        "to_id": lid,
        "message": line,
    }
    if reply_zone in ("town", "field", "dungeon"):
        reply_msg["zone"] = reply_zone
    # Share coords only when already nearby (same privacy as invite/look)
    if lid in set(manager.ids_nearby(character_id)):
        try:
            reply_msg["x"] = int(meta["x"]) if meta else None
            reply_msg["y"] = int(meta["y"]) if meta else None
        except (TypeError, ValueError, KeyError):
            pass
        reply_msg["nearby"] = True
    else:
        reply_msg["nearby"] = False
    sid_r = manager.session_id(character_id)
    if sid_r is not None:
        reply_msg["session_id"] = sid_r
    if not await private_social_delivery(
        character_id,
        lid,
        reply_msg,
        was_afk=was_afk,
        afk_message=afk_msg_snap,
        outbound=outbound,
    ):
        return character_id, user_id, outbound, None

    # Consume invite so double-accept cannot spam the inviter
    manager.clear_last_invite(character_id)
    # Inviter's outgoing pointer no longer pending
    inv_to, _ = manager.last_invite_to(lid)
    if inv_to == character_id:
        manager.clear_last_invite_to(lid)
    # Accept also sets /r peer for easy follow-up whisper
    if accepting:
        manager.note_whisper_from(character_id, lid, tname)
        manager.note_whisper_from(lid, character_id, name)

    peer = social_peer_card(manager, lid, tname, viewer_id=character_id)
    suffix = peer_status_suffix(peer) if peer else ""
    echo = dict(reply_msg)
    echo["message"] = self_line.rstrip(".") + (suffix or "") + "."
    if peer and peer.get("zone") and "peer_zone" not in echo:
        # Do not overwrite accepter zone on invite_reply — peer zone is extra
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
