"""Adversarial: non-finite coordinates must not corrupt multiplayer state."""

from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager
from tests.ws_helpers import register_char, start_server, stop_server


class FakeWS:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def close(self, *a, **k):
        self.closed = True

    async def send_text(self, t):
        self.sent.append(json.loads(t))


async def recv_until(ws, *types, timeout=4.0):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(types)
        raw = await asyncio.wait_for(ws.recv(), remaining)
        m = json.loads(raw)
        if m.get("type") in types:
            return m


async def drain(ws, seconds=0.12):
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
            out.append(json.loads(raw))
        except (asyncio.TimeoutError, TimeoutError):
            break
    return out


def test_publish_move_rejects_nan_and_inf():
    mgr = ConnectionManager()

    async def scenario():
        await mgr.connect(1, FakeWS(), name="A", x=5, y=5, map_id=0)
        await mgr.publish_move(1, float("nan"), 5, seq=1)
        m = mgr.get_meta(1)
        assert math.isfinite(m["x"]) and math.isfinite(m["y"])
        assert m["x"] == 5.0 and m["y"] == 5.0

        await mgr.publish_move(1, float("inf"), 5, seq=2)
        m = mgr.get_meta(1)
        assert math.isfinite(m["x"]) and m["x"] == 5.0

        await mgr.publish_move(1, 6, float("-inf"), seq=3)
        m = mgr.get_meta(1)
        assert math.isfinite(m["y"]) and m["y"] == 5.0

        # Valid move still works
        await mgr.publish_move(1, 6, 5, seq=4)
        m = mgr.get_meta(1)
        assert m["x"] == 6.0 and m["y"] == 5.0

        # set_position also rejects
        mgr.set_position(1, float("nan"), 9)
        m = mgr.get_meta(1)
        assert m["x"] == 6.0

    asyncio.run(scenario())


def test_ws_rejects_non_finite_move(tmp_path, monkeypatch):
    """Client cannot crash the server or store NaN via move payload."""
    db_path = tmp_path / "nan.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "nan@ex.com", "NanU", "NanHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await drain(ws, 0.1)

                # Send bool / null (non-finite / non-numeric) — must reject cleanly
                await ws.send(json.dumps({"type": "move", "x": True, "y": 2, "seq": 1}))
                m = await recv_until(ws, "move_ok", "error")
                assert m.get("ok") is False or m.get("type") == "error", m
                await drain(ws, 0.08)

                await ws.send(json.dumps({"type": "move", "x": None, "y": 2, "seq": 2}))
                m2 = await recv_until(ws, "move_ok", "error")
                assert m2.get("ok") is False or m2.get("type") == "error", m2
                await drain(ws, 0.08)

                # Valid adjacent step still works (invalid moves must not burn rate budget)
                await ws.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 10}))
                m3 = await recv_until(ws, "move_ok", "error")
                # skip any stray error leftovers
                for _ in range(4):
                    if m3.get("type") == "move_ok" and m3.get("ok") is True:
                        break
                    if m3.get("type") == "error" or (
                        m3.get("type") == "move_ok" and m3.get("ok") is False
                    ):
                        m3 = await recv_until(ws, "move_ok", "error")
                        continue
                    break
                assert m3.get("type") == "move_ok", m3
                assert m3.get("ok") is True, m3
                assert int(m3.get("x")) == 3 and int(m3.get("y")) == 2

                # Server still healthy
                await ws.send(json.dumps({"type": "ping", "t": 1}))
                pong = await recv_until(ws, "pong")
                assert pong.get("t") == 1

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_meta_nan_recovery_on_next_move(tmp_path, monkeypatch):
    """If meta somehow has NaN, next valid move recovers instead of crashing."""
    db_path = tmp_path / "nanrec.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod
    from network.websocket_manager import manager

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "nr@ex.com", "NrU", "NrHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await drain(ws, 0.1)

                # Inject corruption into live manager meta
                meta = manager.get_meta(ch["id"])
                assert meta is not None
                meta["x"] = float("nan")
                meta["y"] = float("nan")

                await ws.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 1}))
                m = await recv_until(ws, "move_ok", "error")
                # Should not be server crash; either recover to spawn/adjacent or reject cleanly
                assert m.get("type") in ("move_ok", "error"), m
                meta2 = manager.get_meta(ch["id"])
                assert meta2 is not None
                assert math.isfinite(float(meta2["x"]))
                assert math.isfinite(float(meta2["y"]))

        asyncio.run(flow())
    finally:
        stop_server(server)
