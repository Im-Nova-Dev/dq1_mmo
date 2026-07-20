"""Cancel last outgoing meetup invite (extracted). Not a party.

Clears soft-grace peer pointers; notifies guest only if invite still pending
and not muted. Echo includes nearby + peer zone for multiplayer orientation.
"""

from __future__ import annotations

from typing import Any

from network.handlers._common import best_effort_send, social_peer_card
from network.protocol import ServerMessageType, msg
from network.websocket_manager import _is_idle, manager

CANCEL_TYPES = frozenset(
    {"cancel", "uninvite", "invite_cancel", "revoke_invite"}
)
ALL_TYPES = CANCEL_TYPES


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch cancel/uninvite. Returns None if not a cancel message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    tid, tname = manager.last_invite_to(character_id)
    if tid is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="no invite to cancel"))
        return character_id, user_id, outbound, None

    meta_pre = manager.get_meta(character_id)
    was_idle = _is_idle(meta_pre) if meta_pre else False
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
    name = (meta or {}).get("name") or "Hero"
    live_name = tname
    notified = False
    muted_skip = False
    peer_near: bool | None = None
    peer_zone: str | None = None
    if tid in manager.online_ids():
        tmeta = manager.get_meta(tid)
        live_name = (tmeta or {}).get("name") or tname or "Hero"
        peer_near = tid in set(manager.ids_nearby(character_id))
        peer = social_peer_card(manager, tid, live_name, viewer_id=character_id)
        if peer and peer.get("zone"):
            peer_zone = str(peer["zone"])
        # Only notify if invite is still pending from us
        from_id, _ = manager.last_invite_from(tid)
        if from_id == character_id:
            # Do not push cancel to someone who ignores us (mute hygiene)
            if not manager.is_ignored_by(tid, character_id):
                cancel_msg: dict[str, Any] = {
                    "type": "invite_cancel",
                    "from": name,
                    "from_id": character_id,
                    "to": live_name,
                    "to_id": tid,
                    "message": f"{name} cancelled their meetup invite.",
                }
                sid_c = manager.session_id(character_id)
                if sid_c is not None:
                    cancel_msg["session_id"] = sid_c
                # Honest notified flag — dead sockets must not claim success
                notified = await best_effort_send(tid, cancel_msg)
            else:
                muted_skip = True
            # still clear their pending pointer even if muted / send failed
    # Always drop peer pointer (live + soft-grace) so offline guests
    # do not rehydrate a zombie invite after reconnect.
    manager.clear_invite_from_peer(tid, character_id)
    manager.clear_last_invite_to(character_id)

    if notified:
        clear_msg = f"Invite to {live_name} cancelled."
    elif muted_skip:
        clear_msg = f"Cleared invite to {live_name} (they muted you)."
    else:
        clear_msg = f"Cleared invite to {live_name} (already answered or offline)."
    if peer_zone:
        clear_msg = clear_msg.rstrip(".") + f" · {peer_zone}."
    elif peer_near is True:
        clear_msg = clear_msg.rstrip(".") + " · near."
    elif peer_near is False:
        clear_msg = clear_msg.rstrip(".") + " · far."

    cancel_echo: dict[str, Any] = {
        "type": "invite_cancel",
        "action": "cancel",
        "to": live_name,
        "to_id": tid,
        "notified": notified,
        "muted": muted_skip,
        "message": clear_msg,
        "online": len(manager.online_ids()),
        "nearby_count": len(manager.ids_nearby(character_id)),
    }
    if peer_near is not None:
        cancel_echo["nearby"] = peer_near
    if peer_zone:
        cancel_echo["zone"] = peer_zone
    outbound.append(cancel_echo)
    if was_idle:
        await manager.publish_status(character_id)
    return character_id, user_id, outbound, None
