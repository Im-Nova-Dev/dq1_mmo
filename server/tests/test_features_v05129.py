"""v0.5.129: meta peeks WS · version/played/time census messages."""

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


def test_meta_peeks_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "meta.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "meta@ex.com", "Meta", "MetaHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "error")
                assert v.get("type") == "version", v
                assert str(v.get("version") or config.VERSION).startswith("0.5.")
                assert isinstance(v.get("message"), str) and v["message"]
                assert "combat_count" in v
                assert v.get("online") >= 1

                await ws.send(json.dumps({"type": "played"}))
                pl = await recv_until(ws, "played", "error")
                assert pl.get("type") == "played", pl
                assert isinstance(pl.get("seconds"), int)
                assert "in_combat" in pl
                assert "This session:" in (pl.get("message") or "")

                await ws.send(json.dumps({"type": "time"}))
                t = await recv_until(ws, "time", "error")
                assert t.get("type") == "time", t
                assert "uptime" in t
                assert isinstance(t.get("message"), str) and t["message"]
                assert "zones" in t

                await ws.send(json.dumps({"type": "session"}))
                pl2 = await recv_until(ws, "played", "error")
                assert pl2.get("type") == "played", pl2

                await ws.send(json.dumps({"type": "about"}))
                v2 = await recv_until(ws, "version", "error")
                assert v2.get("type") == "version", v2

        asyncio.run(flow())
    finally:
        stop_server(server)
