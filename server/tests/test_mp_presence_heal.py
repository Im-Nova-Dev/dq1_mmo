"""Multiplayer presence self-heal: AOI prune/reconcile, online zones, health."""

from __future__ import annotations

import asyncio
import json
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
        if self.closed:
            raise RuntimeError("closed")
        self.sent.append(json.loads(t))


async def recv_until(ws, *types, timeout=4.0):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"waiting for {types}")
        raw = await asyncio.wait_for(ws.recv(), remaining)
        m = json.loads(raw)
        if m.get("type") in types:
            return m


async def drain(ws, seconds=0.15):
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
            out.append(json.loads(raw))
        except (asyncio.TimeoutError, TimeoutError):
            break
    return out


def test_prune_stale_visible_removes_ghosts_and_far_peers():
    mgr = ConnectionManager()

    async def scenario():
        await mgr.connect(1, FakeWS(), name="A", x=5, y=5, map_id=0)
        await mgr.connect(2, FakeWS(), name="B", x=6, y=5, map_id=0)
        await mgr.connect(3, FakeWS(), name="C", x=50, y=50, map_id=0)
        # Corrupt AOI: ghost + far peer
        mgr.get_meta(1)["visible"] = {2, 3, 999}
        n = mgr.prune_stale_visible()
        assert n >= 2, n
        vis = mgr.get_meta(1)["visible"]
        assert 999 not in vis
        assert 3 not in vis  # out of range
        assert 2 in vis  # still nearby

    asyncio.run(scenario())


def test_reconcile_all_aoi_relinks_empty_visible():
    mgr = ConnectionManager()

    async def scenario():
        await mgr.connect(1, FakeWS(), name="A", x=5, y=5, map_id=0)
        await mgr.connect(2, FakeWS(), name="B", x=6, y=5, map_id=0)
        mgr.get_meta(1)["visible"] = set()
        mgr.get_meta(2)["visible"] = set()
        n = await mgr.reconcile_all_aoi()
        assert n == 2
        assert 2 in mgr.get_meta(1)["visible"]
        assert 1 in mgr.get_meta(2)["visible"]
        # B should have received a player_joined for A (or vice versa)
        joins_b = [
            m
            for m in mgr._connections[2].sent
            if isinstance(m, dict)
            and m.get("type") == "player_joined"
            and m.get("player_id") == 1
        ]
        assert joins_b, "peer must get player_joined after reconcile"

    asyncio.run(scenario())


def test_online_pulse_includes_zones():
    mgr = ConnectionManager()

    async def scenario():
        await mgr.connect(1, FakeWS(), name="Town", x=2, y=2, map_id=0)
        await mgr.connect(2, FakeWS(), name="Field", x=8, y=6, map_id=0)
        payload = mgr._online_payload()
        assert payload["online"] == 2
        assert "zones" in payload
        assert payload["zones"]["town"] == 1
        assert payload["zones"]["field"] == 1
        await mgr.broadcast_online_force()
        got = [
            m
            for m in mgr._connections[1].sent
            if isinstance(m, dict) and m.get("type") == "online"
        ]
        assert got
        assert "zones" in got[-1]
        assert got[-1]["zones"]["town"] == 1

    asyncio.run(scenario())


def test_health_includes_zones(tmp_path, monkeypatch):
    db_path = tmp_path / "hz.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        import urllib.request

        token, ch = register_char(base, "hz@ex.com", "Hz", "HealthZ")

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

                with urllib.request.urlopen(f"{base}/health", timeout=3) as r:
                    body = json.loads(r.read().decode())
                assert body.get("status") == "ok"
                assert "zones" in body
                assert int(body.get("online") or 0) >= 1
                assert int((body.get("zones") or {}).get("town") or 0) >= 1

                # online pulse after join should carry zones (debounced force)
                await ws.send(json.dumps({"type": "who"}))
                who = await recv_until(ws, "who")
                assert "zones" in who

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_four_player_global_chat_and_find(tmp_path, monkeypatch):
    """Regression: 4 concurrent sessions, chat delivery, find limit."""
    db_path = tmp_path / "four.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        chars = [
            register_char(base, f"f{i}@ex.com", f"F{i}", f"Four{i}") for i in range(4)
        ]

        async def flow():
            import websockets

            sockets = []
            for tok, ch in chars:
                ws = await websockets.connect(ws_url)
                await ws.send(
                    json.dumps({"type": "auth", "token": tok, "character_id": ch["id"]})
                )
                await recv_until(ws, "auth_ok")
                await drain(ws, 0.08)
                sockets.append(ws)

            await sockets[0].send(
                json.dumps({"type": "chat", "channel": "global", "text": "four-hi"})
            )
            await asyncio.sleep(0.15)
            for i, ws in enumerate(sockets[1:], 1):
                got = [
                    m
                    for m in await drain(ws, 0.2)
                    if m.get("type") == "chat" and "four-hi" in str(m.get("text"))
                ]
                assert got, f"peer {i} missed global chat"

            await sockets[0].send(json.dumps({"type": "find", "q": "Four", "limit": 2}))
            f = await recv_until(sockets[0], "find")
            assert len(f.get("players") or []) <= 2
            assert int(f.get("count") or 0) <= 2

            for ws in sockets:
                await ws.close()

        asyncio.run(flow())
    finally:
        stop_server(server)
