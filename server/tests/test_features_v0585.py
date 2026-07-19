"""v0.5.85 features: near/zone AFK census fields, version afk_count."""

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


def test_near_unauth_and_zero_afk(tmp_path, monkeypatch):
    db_path = tmp_path / "near0.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"type": "near"}))
                err = await recv_until(ws, "error", "near")
                assert err.get("type") == "error"
                assert "auth" in str(err.get("reason") or "").lower()

                ta, ca = register_char(base, "z@ex.com", "Zz", "ZeroAfk")
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "near"}))
                near = await recv_until(ws, "near", "error")
                assert near.get("type") == "near"
                assert int(near.get("afk_count") or 0) == 0
                assert int(near.get("nearby_afk") or 0) == 0
                assert "message" in near

                await ws.send(json.dumps({"type": "zone"}))
                zone = await recv_until(ws, "zone", "error")
                assert zone.get("type") == "zone"
                assert int(zone.get("zone_afk") or 0) == 0
                assert int(zone.get("afk_count") or 0) == 0

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_played_afk_message_and_version(tmp_path, monkeypatch):
    db_path = tmp_path / "played_afk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "p@ex.com", "Pp", "PlayAfk")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "afk", "text": "bio"}))
                await recv_until(ws, "afk")
                await ws.send(json.dumps({"type": "played"}))
                pl = await recv_until(ws, "played", "error")
                assert pl.get("afk") is True
                assert pl.get("afk_message") == "bio"
                assert "afk_count" in pl and int(pl.get("afk_count") or 0) >= 1

                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "error")
                assert int(v.get("afk_count") or 0) >= 1

        asyncio.run(flow())
    finally:
        stop_server(server)
