"""v0.5.104: @pending social aliases + mute-safe cancel message."""

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


def test_poke_and_thank_pending_alias(tmp_path, monkeypatch):
    db_path = tmp_path / "pendalias.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "AliasA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "AliasB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "poke", "to": "@pending"}))
                e0 = await recv_until(wa, "error", "poke")
                assert e0.get("type") == "error"
                assert "pending" in str(e0.get("reason") or "").lower() or "no" in str(
                    e0.get("reason") or ""
                ).lower()

                await wa.send(json.dumps({"type": "invite", "to": "AliasB"}))
                assert (await recv_until(wa, "invite", "error")).get("type") == "invite"
                await recv_until(wb, "invite", "error")

                await asyncio.sleep(0.85)
                # Inviter pokes pending outgoing
                await wa.send(json.dumps({"type": "poke", "to": "@pending"}))
                ok = await recv_until(wa, "poke", "error")
                assert ok.get("type") == "poke", ok
                peer = await recv_until(wb, "poke", "error")
                assert peer.get("type") == "poke"

                await asyncio.sleep(0.85)
                # Guest thanks pending incoming
                await wb.send(json.dumps({"type": "thank", "to": "@invite"}))
                th = await recv_until(wb, "thank", "error")
                assert th.get("type") == "thank", th
                got = await recv_until(wa, "thank", "error")
                assert got.get("type") == "thank"

                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "share", "to": "@pending"}))
                sh = await recv_until(wb, "share", "error")
                assert sh.get("type") == "share", sh

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_help_mentions_pending_alias(tmp_path, monkeypatch):
    db_path = tmp_path / "pendhelp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "HelpPend")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                blob = json.dumps(h.get("commands") or [])
                assert "@pending" in blob or "pending" in blob.lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_version_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "pendver.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "v@ex.com", "Vv", "VerPend2")

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
