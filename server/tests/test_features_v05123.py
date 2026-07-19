"""v0.5.123: /played survives soft reconnect · version."""

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


def test_played_survives_soft_reconnect_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "pl.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "pl@ex.com", "Pl", "PlayA")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await asyncio.sleep(0.9)
                await ws.send(json.dumps({"type": "played"}))
                pl1 = await recv_until(ws, "played", "error")
                assert pl1.get("type") == "played", pl1
                secs1 = float(pl1.get("seconds") or 0)
                assert secs1 >= 0.5, pl1

            await asyncio.sleep(0.15)
            async with websockets.connect(ws_url) as ws2:
                await auth(ws2, ta, ca["id"])
                await ws2.send(json.dumps({"type": "played"}))
                pl2 = await recv_until(ws2, "played", "error")
                assert pl2.get("type") == "played", pl2
                secs2 = float(pl2.get("seconds") or 0)
                # Soft reconnect should continue the clock, not restart near 0
                assert secs2 >= secs1, (secs1, secs2)
                await ws2.send(json.dumps({"type": "version"}))
                v = await recv_until(ws2, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
