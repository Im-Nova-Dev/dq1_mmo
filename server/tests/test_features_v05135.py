"""v0.5.135: roll WS · default d100 · sides census message."""

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


def test_roll_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "roll.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "roll@ex.com", "Ro", "RollHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])

                # Invalid first — must not burn chat rate
                await ws.send(json.dumps({"type": "roll", "sides": 0}))
                err = await recv_until(ws, "error", "chat")
                assert err.get("type") == "error"
                assert err.get("reason") == "invalid roll sides"

                await ws.send(json.dumps({"type": "roll"}))
                m = await recv_until(ws, "chat", "error")
                assert m.get("type") == "chat", m
                r = m.get("roll") or {}
                assert int(r.get("sides") or 0) == 100
                assert 1 <= int(r.get("value") or 0) <= 100
                assert isinstance(m.get("message"), str)
                assert "nearby_count" in m or "nearby_count" in r

                # Wait past chat rate so second roll works
                await asyncio.sleep(1.1)
                await ws.send(json.dumps({"type": "dice", "sides": 6}))
                m2 = await recv_until(ws, "chat", "error")
                assert m2.get("type") == "chat", m2
                assert (m2.get("roll") or {}).get("sides") == 6

                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
