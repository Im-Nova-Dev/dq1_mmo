"""v0.5.110: multi-token find filters (WS) + version."""

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


def test_find_multi_zone_tokens_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "multiz.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "MultiA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "MultiB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                # Both in town at spawn — double zone must not zero out
                await wa.send(
                    json.dumps({"type": "find", "query": "zone:field zone:town"})
                )
                f = await recv_until(wa, "find", "error")
                assert f.get("type") == "find", f
                assert f.get("zone") == "town", f
                assert int(f.get("count") or 0) >= 1, f
                q = str(f.get("query") or "")
                assert q.count("zone:") == 1, q

                await wa.send(
                    json.dumps({"type": "find", "query": "zone:town afk:no"})
                )
                f2 = await recv_until(wa, "find", "error")
                assert f2.get("type") == "find"
                assert f2.get("zone") == "town"
                assert f2.get("afk") is False

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_version_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "v110.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "v@ex.com", "Vv", "Ver110")

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
