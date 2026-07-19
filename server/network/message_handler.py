from typing import Any

from auth.jwt_handler import decode_access_token
from database.db import get_db
from game.world_manager import is_adjacent_step, is_walkable, map_payload
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import manager


async def handle_message(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
) -> tuple[int | None, int | None, list[dict], dict | None]:
    """
    Process one client message.
    Returns (character_id, user_id, outbound_to_sender, connect_meta|None).
    connect_meta is set on successful auth for ConnectionManager.connect.
    """
    msg_type = data.get("type")
    outbound: list[dict] = []
    connect_meta: dict | None = None

    if msg_type == ClientMessageType.PING:
        outbound.append(msg(ServerMessageType.PONG))
        return character_id, user_id, outbound, None

    if msg_type == ClientMessageType.AUTH:
        token = data.get("token")
        char_id = data.get("character_id")
        if not token or not char_id:
            outbound.append(msg(ServerMessageType.AUTH_FAIL, reason="token and character_id required"))
            return character_id, user_id, outbound, None

        payload = decode_access_token(token)
        if payload is None:
            outbound.append(msg(ServerMessageType.AUTH_FAIL, reason="invalid token"))
            return character_id, user_id, outbound, None

        db = await get_db()
        async with db.execute(
            "SELECT * FROM characters WHERE id = ? AND user_id = ?",
            (int(char_id), payload["user_id"]),
        ) as c:
            row = await c.fetchone()
        if row is None:
            outbound.append(msg(ServerMessageType.AUTH_FAIL, reason="character not found"))
            return character_id, user_id, outbound, None

        character = {k: row[k] for k in row.keys()}
        # Clamp saved position onto walkable tiles
        x = int(character["world_x"])
        y = int(character["world_y"])
        if not is_walkable(x, y):
            from game.world_manager import SPAWN_X, SPAWN_Y

            x, y = SPAWN_X, SPAWN_Y
            await db.execute(
                "UPDATE characters SET world_x = ?, world_y = ? WHERE id = ?",
                (x, y, character["id"]),
            )
            await db.commit()
            character["world_x"] = x
            character["world_y"] = y

        connect_meta = {
            "character_id": character["id"],
            "name": character["name"],
            "x": character["world_x"],
            "y": character["world_y"],
            "map_id": character["map_id"],
            "level": character["level"],
        }

        outbound.append(
            msg(
                ServerMessageType.AUTH_OK,
                player_id=character["id"],
                character=character,
                map=map_payload(),
            )
        )
        # Nearby snapshot filled after connect in main.py
        outbound.append(msg(ServerMessageType.WORLD_STATE, players=[], enemies=[], map=map_payload()))
        return character["id"], payload["user_id"], outbound, connect_meta

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    if msg_type == ClientMessageType.MOVE:
        x = data.get("x")
        y = data.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            outbound.append(msg(ServerMessageType.ERROR, reason="invalid move"))
            return character_id, user_id, outbound, None

        tx, ty = int(x), int(y)
        meta = manager.get_meta(character_id)
        if meta is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="not connected"))
            return character_id, user_id, outbound, None

        fx, fy = int(meta["x"]), int(meta["y"])
        if not is_adjacent_step(fx, fy, tx, ty):
            outbound.append(
                msg(
                    ServerMessageType.ERROR,
                    reason="invalid step",
                    x=fx,
                    y=fy,
                )
            )
            return character_id, user_id, outbound, None

        if not is_walkable(tx, ty):
            outbound.append(
                msg(
                    ServerMessageType.ERROR,
                    reason="blocked",
                    x=fx,
                    y=fy,
                )
            )
            return character_id, user_id, outbound, None

        db = await get_db()
        await db.execute(
            "UPDATE characters SET world_x = ?, world_y = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (tx, ty, character_id),
        )
        await db.commit()
        manager.set_position(character_id, tx, ty)

        move_msg = msg(ServerMessageType.PLAYER_MOVED, player_id=character_id, x=tx, y=ty)
        await manager.broadcast_nearby(character_id, move_msg, include_self=False)
        outbound.append(move_msg)
        return character_id, user_id, outbound, None

    outbound.append(msg(ServerMessageType.ERROR, reason=f"unknown or unsupported type: {msg_type}"))
    return character_id, user_id, outbound, None
