"""v0.5.108: find @pending filter messaging + social zone peers (WS)."""

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


def test_find_pending_filter_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "findfilt.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "FiltA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "FiltB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "invite", "to": "FiltB"}))
                await recv_until(wa, "invite", "error")
                await recv_until(wb, "invite", "error")

                # Both start in town — filter zone:field should miss
                await wa.send(
                    json.dumps({"type": "find", "query": "@pending zone:field"})
                )
                f = await recv_until(wa, "find", "error")
                assert f.get("type") == "find", f
                assert int(f.get("count") or 0) == 0
                assert f.get("filtered") is True, f
                assert f.get("filtered_peer") == "FiltB", f
                assert f.get("filter") == "zone:field", f
                assert f.get("message"), f

                await wa.send(
                    json.dumps({"type": "find", "query": "@pending zone:town"})
                )
                f2 = await recv_until(wa, "find", "error")
                assert f2.get("type") == "find"
                assert int(f2.get("count") or 0) == 1
                assert not f2.get("filtered")

                await wa.send(json.dumps({"type": "social"}))
                soc = await recv_until(wa, "social", "error")
                inv = soc.get("invite_to") or {}
                assert inv.get("name") == "FiltB"
                assert inv.get("zone") in ("town", "field", "dungeon"), inv

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_version_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "v108.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "v@ex.com", "Vv", "Ver108")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
