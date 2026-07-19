"""v0.5.106: look/ignore @pending multiplayer social aliases."""

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


def test_look_and_ignore_pending(tmp_path, monkeypatch):
    db_path = tmp_path / "lookpend.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "LookA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "LookB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "look", "name": "@pending"}))
                e0 = await recv_until(wa, "error", "look")
                assert e0.get("type") == "error"

                await wa.send(json.dumps({"type": "invite", "to": "LookB"}))
                await recv_until(wa, "invite", "error")
                await recv_until(wb, "invite", "error")

                await wa.send(json.dumps({"type": "look", "name": "@pending"}))
                card = await recv_until(wa, "look", "error")
                assert card.get("type") == "look", card
                player = card.get("player") if isinstance(card.get("player"), dict) else card
                assert player.get("name") == "LookB", card

                await wa.send(json.dumps({"type": "ignore", "name": "@pending"}))
                ig = await recv_until(wa, "ignore", "error")
                assert ig.get("type") == "ignore", ig
                assert ig.get("action") == "ignore"

                # poke blocked by ignore
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "poke", "to": "LookB"}))
                err = await recv_until(wa, "error", "poke")
                assert err.get("type") == "error"
                assert "ignore" in str(err.get("reason") or "").lower()

                await wa.send(json.dumps({"type": "unignore", "name": "@last"}))
                # @last may be LookB from poke fail or invite whisper
                u = await recv_until(wa, "ignore", "error")
                # if @last fails, try @pending
                if u.get("type") == "error":
                    await wa.send(json.dumps({"type": "unignore", "name": "@pending"}))
                    u = await recv_until(wa, "ignore", "error")
                assert u.get("type") == "ignore", u

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_help_look_ignore_pending(tmp_path, monkeypatch):
    db_path = tmp_path / "lookhelp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "LookHelp")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                blob = json.dumps(h.get("commands") or []).lower()
                assert "look" in blob and ("@pending" in blob or "pending" in blob)

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_version_who_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "lookver.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "v@ex.com", "Vv", "LookVer")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")
                await ws.send(json.dumps({"type": "who"}))
                who = await recv_until(ws, "who", "error")
                assert "combat_count" in who

        asyncio.run(flow())
    finally:
        stop_server(server)
