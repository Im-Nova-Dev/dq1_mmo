"""v0.5.115: @share social alias WS · version."""

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


def test_share_alias_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "sh.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "p@ex.com", "Pp", "ShareA")
        tb, cb = register_char(base, "q@ex.com", "Qq", "ShareB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "share", "to": "ShareB"}))
                r = await recv_until(wa, "share", "error")
                if r.get("reason") == "chat_rate_limit":
                    await asyncio.sleep(float(r.get("retry_after") or 1.0) + 0.1)
                    await wa.send(json.dumps({"type": "share", "to": "ShareB"}))
                    r = await recv_until(wa, "share", "error")
                assert r.get("type") == "share", r
                await recv_until(wb, "share", "error")

                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "thank", "to": "@share"}))
                th = await recv_until(wa, "thank", "error")
                if th.get("reason") == "chat_rate_limit":
                    await asyncio.sleep(float(th.get("retry_after") or 1.0) + 0.1)
                    await wa.send(json.dumps({"type": "thank", "to": "@share"}))
                    th = await recv_until(wa, "thank", "error")
                assert th.get("type") == "thank", th
                await recv_until(wb, "thank", "error")

                await wa.send(json.dumps({"type": "version"}))
                v = await recv_until(wa, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
