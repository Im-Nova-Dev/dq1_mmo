"""v0.5.107: /social peers summary + /find @pending."""

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


def test_social_and_find_pending(tmp_path, monkeypatch):
    db_path = tmp_path / "social.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "SocA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "SocB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "social"}))
                empty = await recv_until(wa, "social", "error")
                assert empty.get("type") == "social"
                assert empty.get("has_any") is False

                await wa.send(json.dumps({"type": "invite", "to": "SocB"}))
                await recv_until(wa, "invite", "error")
                await recv_until(wb, "invite", "error")

                await wa.send(json.dumps({"type": "social"}))
                soc = await recv_until(wa, "social", "error")
                assert soc.get("has_any") is True, soc
                assert (soc.get("invite_to") or {}).get("name") == "SocB"
                assert (soc.get("whisper") or {}).get("name") == "SocB"

                await wa.send(json.dumps({"type": "find", "query": "@pending"}))
                f = await recv_until(wa, "find", "error")
                assert f.get("type") == "find", f
                assert int(f.get("count") or 0) == 1
                players = f.get("players") or []
                assert players and players[0].get("name") == "SocB"

                await wa.send(json.dumps({"type": "find", "query": "@last"}))
                f2 = await recv_until(wa, "find", "error")
                assert f2.get("type") == "find"
                assert int(f2.get("count") or 0) >= 1

                await wa.send(json.dumps({"type": "help"}))
                h = await recv_until(wa, "help", "error")
                blob = json.dumps(h.get("commands") or []).lower()
                assert "social" in blob or "peers" in blob

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_find_pending_empty(tmp_path, monkeypatch):
    db_path = tmp_path / "findpend.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "e@ex.com", "Ee", "FindEmpty")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "find", "query": "@pending"}))
                err = await recv_until(ws, "error", "find")
                assert err.get("type") == "error"
                assert "pending" in str(err.get("reason") or "").lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_version_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "socver.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "v@ex.com", "Vv", "SocVer")

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
