"""v0.5.95: cancel invite, share location, regressions."""

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


def test_cancel_invite(tmp_path, monkeypatch):
    db_path = tmp_path / "cancel.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "c1@ex.com", "C1", "CanA")
        tb, cb = register_char(base, "c2@ex.com", "C2", "CanB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "cancel"}))
                e0 = await recv_until(wa, "error", "invite_cancel")
                assert e0.get("type") == "error"
                assert "cancel" in str(e0.get("reason") or "").lower()

                await wa.send(json.dumps({"type": "invite", "to": "CanB"}))
                await recv_until(wa, "invite", "error")
                await recv_until(wb, "invite", "error")

                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "cancel"}))
                ok = await recv_until(wa, "invite_cancel", "error")
                assert ok.get("type") == "invite_cancel", ok
                assert "cancelled" in str(ok.get("message") or "").lower()

                peer = await recv_until(wb, "invite_cancel", "error")
                assert peer.get("type") == "invite_cancel"
                assert "cancelled" in str(peer.get("message") or "").lower()

                # Guest cannot accept after cancel
                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "accept"}))
                err = await recv_until(wb, "error", "invite_reply")
                assert err.get("type") == "error"
                assert "invite" in str(err.get("reason") or "").lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_share_location(tmp_path, monkeypatch):
    db_path = tmp_path / "share.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s1@ex.com", "S1", "ShareA")
        tb, cb = register_char(base, "s2@ex.com", "S2", "ShareB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "share"}))
                e0 = await recv_until(wa, "error", "share")
                assert e0.get("type") == "error"

                await wa.send(json.dumps({"type": "share", "to": "ShareA"}))
                e1 = await recv_until(wa, "error", "share")
                assert "yourself" in str(e1.get("reason") or "").lower()

                await wa.send(json.dumps({"type": "share", "to": "ShareB"}))
                ok = await recv_until(wa, "share", "error")
                assert ok.get("type") == "share", ok
                assert ok.get("to_id") == cb["id"]
                assert "x" in ok and "y" in ok
                assert ok.get("zone") in ("town", "field", "dungeon", None)

                peer = await recv_until(wb, "share", "error")
                assert peer.get("type") == "share"
                assert peer.get("from") == "ShareA"
                assert peer.get("x") is not None
                assert "location" in str(peer.get("message") or "").lower() or peer.get(
                    "zone"
                )

                # /r works after share
                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "reply", "text": "got it"}))
                r = await recv_until(wb, "chat", "error")
                assert r.get("channel") == "whisper"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_share_ignore_and_help(tmp_path, monkeypatch):
    db_path = tmp_path / "shareig.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "HelpShare")
        tb, cb = register_char(base, "i@ex.com", "Ii", "IgShare")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wb.send(json.dumps({"type": "ignore", "name": "HelpShare"}))
                await recv_until(wb, "ignore", "error")
                await wa.send(json.dumps({"type": "share", "to": "IgShare"}))
                err = await recv_until(wa, "error", "share")
                assert err.get("type") == "error"
                assert "unavailable" in str(err.get("reason") or "").lower()
                assert err.get("reason") != "chat_rate_limit"

                await wa.send(json.dumps({"type": "help"}))
                h = await recv_until(wa, "help", "error")
                cmds = " ".join(
                    str(c.get("cmd") if isinstance(c, dict) else c)
                    for c in (h.get("commands") or [])
                )
                assert "share" in cmds or "cancel" in cmds, cmds

                await wa.send(json.dumps({"type": "version"}))
                v = await recv_until(wa, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
