"""v0.5.133: safety WS · stuck already-home census · quit farewell."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.ws_helpers import register_char, start_server, stop_server


async def recv_until(ws, *types, timeout=5.0):
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
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
        except (asyncio.TimeoutError, TimeoutError):
            break


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.1)
    return m


def test_safety_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "safe.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "safe@ex.com", "Sf", "SafeHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                # spawn is town — already home
                await ws.send(json.dumps({"type": "stuck"}))
                m = await recv_until(ws, "stuck", "error")
                assert m.get("type") == "stuck", m
                assert m.get("teleported") is False
                assert m.get("zone") == "town"
                assert isinstance(m.get("message"), str)
                assert "online" in m
                assert "nearby_count" in m

                await ws.send(json.dumps({"type": "home"}))
                m2 = await recv_until(ws, "stuck", "error")
                assert m2.get("type") == "stuck"
                assert m2.get("teleported") is False

                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

                await ws.send(json.dumps({"type": "quit"}))
                q = await recv_until(ws, "quit", "error")
                assert q.get("type") == "quit"
                assert q.get("ok") is True
                assert "Farewell" in (q.get("message") or "")

        asyncio.run(flow())
    finally:
        stop_server(server)
