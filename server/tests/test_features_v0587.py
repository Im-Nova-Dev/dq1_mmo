"""v0.5.87 features: directed emote help, bare wave still works."""

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


def test_bare_emote_and_help(tmp_path, monkeypatch):
    db_path = tmp_path / "emote_feat.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "e@ex.com", "Ee", "WaveSolo")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "emote", "emote": "wave"}))
                em = await recv_until(ws, "emote", "error")
                assert em.get("type") == "emote"
                assert em.get("emote") == "wave"
                assert not em.get("to")

                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                blob = json.dumps(h)
                assert "wave" in blob.lower() or "emote" in blob.lower()

        asyncio.run(flow())
    finally:
        stop_server(server)
