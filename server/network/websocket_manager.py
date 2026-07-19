import asyncio
import json
from typing import Any

from fastapi import WebSocket

from game.world_manager import is_nearby


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, WebSocket] = {}
        self._meta: dict[int, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        character_id: int,
        websocket: WebSocket,
        *,
        name: str,
        x: float,
        y: float,
        map_id: int,
        level: int = 1,
    ) -> None:
        async with self._lock:
            old = self._connections.get(character_id)
            if old is not None and old is not websocket:
                try:
                    await old.close(code=4000, reason="Replaced by new connection")
                except Exception:
                    pass
            self._connections[character_id] = websocket
            self._meta[character_id] = {
                "id": character_id,
                "name": name,
                "x": float(x),
                "y": float(y),
                "map_id": map_id,
                "level": level,
            }

    async def disconnect(
        self,
        character_id: int,
        websocket: WebSocket | None = None,
    ) -> dict[str, Any] | None:
        """Remove connection. If websocket is given, only remove when it still owns the slot
        (prevents a replaced/stale socket from wiping the new session)."""
        async with self._lock:
            current = self._connections.get(character_id)
            if websocket is not None and current is not None and current is not websocket:
                return None
            self._connections.pop(character_id, None)
            return self._meta.pop(character_id, None)

    def is_online(self, character_id: int) -> bool:
        return character_id in self._connections

    def owns(self, character_id: int, websocket: WebSocket) -> bool:
        return self._connections.get(character_id) is websocket

    def online_ids(self) -> list[int]:
        return list(self._connections.keys())

    def get_meta(self, character_id: int) -> dict[str, Any] | None:
        return self._meta.get(character_id)

    def set_position(self, character_id: int, x: float, y: float) -> None:
        meta = self._meta.get(character_id)
        if meta is not None:
            meta["x"] = float(x)
            meta["y"] = float(y)

    def nearby_players(self, character_id: int) -> list[dict[str, Any]]:
        me = self._meta.get(character_id)
        if me is None:
            return []
        out: list[dict[str, Any]] = []
        for cid, meta in self._meta.items():
            if cid == character_id:
                continue
            if meta["map_id"] != me["map_id"]:
                continue
            if is_nearby(me["x"], me["y"], meta["x"], meta["y"]):
                out.append(
                    {
                        "id": meta["id"],
                        "name": meta["name"],
                        "world_x": meta["x"],
                        "world_y": meta["y"],
                        "map_id": meta["map_id"],
                        "level": meta["level"],
                    }
                )
        return out

    async def send(self, character_id: int, message: dict[str, Any]) -> bool:
        ws = self._connections.get(character_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(message, default=str))
            return True
        except Exception:
            await self.disconnect(character_id, ws)
            return False

    async def broadcast(self, message: dict[str, Any], exclude: int | None = None) -> None:
        dead: list[tuple[int, WebSocket]] = []
        payload = json.dumps(message, default=str)
        for cid, ws in list(self._connections.items()):
            if exclude is not None and cid == exclude:
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append((cid, ws))
        for cid, ws in dead:
            await self.disconnect(cid, ws)

    async def broadcast_nearby(
        self,
        source_id: int,
        message: dict[str, Any],
        *,
        include_self: bool = False,
    ) -> None:
        me = self._meta.get(source_id)
        if me is None:
            return
        dead: list[tuple[int, WebSocket]] = []
        payload = json.dumps(message, default=str)
        for cid, ws in list(self._connections.items()):
            if cid == source_id and not include_self:
                continue
            other = self._meta.get(cid)
            if other is None:
                continue
            if other["map_id"] != me["map_id"]:
                continue
            if not is_nearby(me["x"], me["y"], other["x"], other["y"]):
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append((cid, ws))
        for cid, ws in dead:
            await self.disconnect(cid, ws)


manager = ConnectionManager()
