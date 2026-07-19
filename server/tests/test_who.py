"""Lightweight who/online multiplayer query + free-port integration."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_who_two_players(tmp_path, monkeypatch):
    import os

    db_path = tmp_path / "who.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    os.environ["DATABASE_URL"] = str(db_path)
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    from tests.ws_helpers import register_char, start_server, stop_server

    server, port, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "wa@ex.com", "WhoA", "WhoAlice")
        token_b, ch_b = register_char(base, "wb@ex.com", "WhoB", "WhoBob")

        async def flow():
            import websockets

            async def auth(ws, token, cid):
                await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
                # auth_ok then world_state
                types = set()
                for _ in range(4):
                    m = json.loads(await asyncio.wait_for(ws.recv(), 3))
                    types.add(m.get("type"))
                    if "auth_ok" in types and "world_state" in types:
                        break
                assert "auth_ok" in types

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, token_a, ch_a["id"])
                await auth(wb, token_b, ch_b["id"])
                await asyncio.sleep(0.15)
                # drain
                for ws in (wa, wb):
                    try:
                        while True:
                            await asyncio.wait_for(ws.recv(), 0.05)
                    except (asyncio.TimeoutError, TimeoutError):
                        pass

                await wa.send(json.dumps({"type": "who"}))
                who = json.loads(await asyncio.wait_for(wa.recv(), 3))
                while who.get("type") != "who":
                    who = json.loads(await asyncio.wait_for(wa.recv(), 3))
                assert who["type"] == "who"
                assert who["online"] == 2
                assert ch_b["id"] in {p["id"] for p in who.get("players") or []}
                assert who["you"]["id"] == ch_a["id"]

        asyncio.run(flow())
    finally:
        stop_server(server)
