"""Multiplayer find + level-up system chat + AOI move lock regression."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager
from tests.ws_helpers import register_char, start_server, stop_server


async def recv_until(ws, *types, timeout=4.0):
    deadline = time.monotonic() + timeout
    while True:
        rem = deadline - time.monotonic()
        if rem <= 0:
            raise TimeoutError(types)
        m = json.loads(await asyncio.wait_for(ws.recv(), rem))
        if m.get("type") in types:
            return m


async def drain(ws, seconds=0.12):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
        except (asyncio.TimeoutError, TimeoutError):
            break


def test_find_by_prefix_unit():
    mgr = ConnectionManager()

    class WS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, WS(), name="Alice", x=2, y=2, map_id=1, level=3)
        await mgr.connect(2, WS(), name="Alicia", x=3, y=2, map_id=1, level=5)
        await mgr.connect(3, WS(), name="Bob", x=4, y=2, map_id=1, level=2)
        hits = mgr.find_by_prefix("ali")
        names = {h["name"] for h in hits}
        assert names == {"Alice", "Alicia"}
        assert all("x" not in h and "world_x" not in h for h in hits)
        assert mgr.find_by_prefix("bo")[0]["name"] == "Bob"
        assert mgr.find_by_prefix("") == []
        assert mgr.find_by_prefix("zzz") == []
        # limit
        assert len(mgr.find_by_prefix("a", limit=1)) == 1

    asyncio.run(scenario())


def test_find_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "find.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "fa@ex.com", "FaU", "FindAlice")
        tb, cb = register_char(base, "fb@ex.com", "FbU", "FindBob")
        tc, cc = register_char(base, "fc@ex.com", "FcU", "FindAlicia")

        async def flow():
            import websockets

            sockets = []
            for tok, ch in ((ta, ca), (tb, cb), (tc, cc)):
                ws = await websockets.connect(ws_url)
                await ws.send(
                    json.dumps({"type": "auth", "token": tok, "character_id": ch["id"]})
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                sockets.append(ws)
            for ws in sockets:
                await drain(ws)

            await sockets[0].send(json.dumps({"type": "find", "q": "FindA"}))
            m = await recv_until(sockets[0], "find", "error")
            assert m["type"] == "find", m
            names = {p["name"] for p in m.get("players") or []}
            assert "FindAlice" in names
            assert "FindAlicia" in names
            assert "FindBob" not in names
            assert m.get("count") == 2

            await sockets[0].send(json.dumps({"type": "find", "query": "FindB"}))
            m2 = await recv_until(sockets[0], "find")
            assert m2["count"] == 1
            assert m2["players"][0]["name"] == "FindBob"

            await sockets[0].send(json.dumps({"type": "find"}))
            err = await recv_until(sockets[0], "error")
            assert "query" in (err.get("reason") or "")

            for ws in sockets:
                await ws.close()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_level_up_system_chat_nearby(tmp_path, monkeypatch):
    """publish_level emits system chat to nearby peers."""
    mgr = ConnectionManager()

    class WS:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(json.loads(t))

        async def close(self, *a, **k):
            pass

    async def scenario():
        a, b, far = WS(), WS(), WS()
        await mgr.connect(1, a, name="HeroA", x=2, y=2, map_id=1, level=1)
        await mgr.connect(2, b, name="HeroB", x=3, y=2, map_id=1, level=1)
        await mgr.connect(3, far, name="Far", x=50, y=50, map_id=1, level=1)
        a.sent.clear()
        b.sent.clear()
        far.sent.clear()
        await mgr.publish_level(1, 4)
        assert mgr.get_meta(1)["level"] == 4
        # nearby peer B gets system chat
        sys_b = [
            m
            for m in b.sent
            if m.get("type") == "chat" and m.get("channel") == "system"
        ]
        assert sys_b, b.sent
        assert "level 4" in sys_b[0].get("text", "").lower()
        # self also receives
        sys_a = [
            m
            for m in a.sent
            if m.get("type") == "chat" and m.get("channel") == "system"
        ]
        assert sys_a
        # far player should not get nearby system chat
        sys_f = [
            m
            for m in far.sent
            if m.get("type") == "chat" and m.get("channel") == "system"
        ]
        assert not sys_f, far.sent

    asyncio.run(scenario())


def test_publish_move_under_lock_still_aoi():
    """Regression: locked publish_move still emits joins/leaves."""
    mgr = ConnectionManager()

    class WS:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(json.loads(t))

        async def close(self, *a, **k):
            pass

    async def scenario():
        a, b = WS(), WS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=1)
        await mgr.connect(2, b, name="B", x=3, y=2, map_id=1)
        a.sent.clear()
        b.sent.clear()
        # walk A far away
        to_self = await mgr.publish_move(1, 40, 40, seq=1)
        assert any(m.get("type") == "player_left" for m in to_self)
        assert any(m.get("type") == "player_left" for m in b.sent)
        # walk back near B
        to_self2 = await mgr.publish_move(1, 3, 2, seq=2)
        assert any(m.get("type") == "player_joined" for m in to_self2)
        assert 2 in mgr.get_meta(1)["visible"]

    asyncio.run(scenario())
