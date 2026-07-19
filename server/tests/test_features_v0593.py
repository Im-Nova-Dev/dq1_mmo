"""v0.5.93 features: fighting unauth, accept empty, help, version."""

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


def test_unauth_fighting_and_accept(tmp_path, monkeypatch):
    db_path = tmp_path / "unauth93.db"
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
                for t in ("fighting", "accept", "decline", "lastinvite"):
                    await ws.send(json.dumps({"type": t}))
                    err = await recv_until(ws, "error")
                    assert "authenticate" in str(err.get("reason") or "").lower(), err

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_help_and_accept_preserves_afk(tmp_path, monkeypatch):
    db_path = tmp_path / "help93.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "Help93")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                cmds = " ".join(
                    str(c.get("cmd") if isinstance(c, dict) else c)
                    for c in (h.get("commands") or [])
                )
                assert "fighting" in cmds or "accept" in cmds or "lastinvite" in cmds, cmds

                await ws.send(json.dumps({"type": "busy", "text": "hold"}))
                await recv_until(ws, "afk")
                # Failed accept must not clear AFK (no invite)
                await ws.send(json.dumps({"type": "accept"}))
                await recv_until(ws, "error")
                await ws.send(json.dumps({"type": "status"}))
                st = await recv_until(ws, "status")
                assert (st.get("you") or {}).get("afk") is True

                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "about", "error")
                ver = str(v.get("version") or config.VERSION)
                assert ver.startswith("0.5."), ver

        asyncio.run(flow())
    finally:
        stop_server(server)
