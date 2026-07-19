"""v0.5.94 adversarial hunt: invite double-reply, roll float sides, fighting edges."""

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
    out = []
    while time.monotonic() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
            out.append(json.loads(raw))
        except (asyncio.TimeoutError, TimeoutError):
            break
    return out


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.1)
    return m


def test_double_accept_cannot_spam(tmp_path, monkeypatch):
    """Successful accept/decline must consume the invite."""
    db_path = tmp_path / "dbl.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "HostDbl")
        tb, cb = register_char(base, "b@ex.com", "Bb", "GuestDbl")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "invite", "to": "GuestDbl"}))
                await recv_until(wa, "invite", "error")
                await recv_until(wb, "invite", "error")

                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "accept"}))
                ok = await recv_until(wb, "invite_reply", "error")
                assert ok.get("action") == "accept", ok
                await recv_until(wa, "invite_reply", "error")

                # Second accept must fail — invite consumed
                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "accept"}))
                err = await recv_until(wb, "error", "invite_reply")
                assert err.get("type") == "error", err
                assert "invite" in str(err.get("reason") or "").lower(), err

                # lastinvite empty
                await wb.send(json.dumps({"type": "lastinvite"}))
                li = await recv_until(wb, "lastinvite", "error")
                assert li.get("peer") is None, li

                # Decline path also consumes
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "invite", "to": "GuestDbl"}))
                await recv_until(wa, "invite", "error")
                await recv_until(wb, "invite", "error")
                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "later"}))
                d = await recv_until(wb, "invite_reply", "error")
                assert d.get("action") == "decline"
                await recv_until(wa, "invite_reply", "error")
                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "decline"}))
                err2 = await recv_until(wb, "error", "invite_reply")
                assert err2.get("type") == "error"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_accept_sets_reply_peer(tmp_path, monkeypatch):
    db_path = tmp_path / "rpeer.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "r1@ex.com", "R1", "ReplyA")
        tb, cb = register_char(base, "r2@ex.com", "R2", "ReplyB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "invite", "to": "ReplyB"}))
                await recv_until(wa, "invite", "error")
                await recv_until(wb, "invite", "error")
                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "accept"}))
                await recv_until(wb, "invite_reply", "error")
                await recv_until(wa, "invite_reply", "error")

                # Guest can /r to host after accept
                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "reply", "text": "on my way"}))
                r = await recv_until(wb, "chat", "error")
                assert r.get("type") == "chat", r
                assert r.get("channel") == "whisper", r
                assert r.get("to_id") == ca["id"] or r.get("to") == "ReplyA"
                await recv_until(wa, "chat", "error")

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_roll_float_sides_and_fighting_self(tmp_path, monkeypatch):
    db_path = tmp_path / "rollf.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "z@ex.com", "Zz", "RollF")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])

                await ws.send(json.dumps({"type": "afk", "text": "hold"}))
                await recv_until(ws, "afk")

                # float sides must not become d2 / clear AFK
                await ws.send(json.dumps({"type": "roll", "sides": 2.7}))
                err = await recv_until(ws, "error", "chat")
                assert err.get("type") == "error"
                assert "sides" in str(err.get("reason") or "").lower()
                await ws.send(json.dumps({"type": "status"}))
                st = await recv_until(ws, "status")
                assert (st.get("you") or {}).get("afk") is True

                await ws.send(json.dumps({"type": "roll", "sides": True}))
                err2 = await recv_until(ws, "error", "chat")
                assert err2.get("type") == "error"

                await ws.send(json.dumps({"type": "back"}))
                await recv_until(ws, "afk")

                # Self in combat not listed as nearby fighting
                await ws.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 4})
                )
                await recv_until(ws, "combat_start", "error")
                await ws.send(json.dumps({"type": "fighting"}))
                f = await recv_until(ws, "fighting", "error")
                assert int(f.get("nearby_combat") or 0) == 0, f
                names = [p.get("name") for p in (f.get("players") or [])]
                assert "RollF" not in names, names

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_invite_ignore_accept_matrix(tmp_path, monkeypatch):
    db_path = tmp_path / "igacc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "i1@ex.com", "I1", "IgHost")
        tb, cb = register_char(base, "i2@ex.com", "I2", "IgGuest")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "invite", "to": "IgGuest"}))
                await recv_until(wa, "invite", "error")
                await recv_until(wb, "invite", "error")

                # Host ignores guest — guest cannot accept
                await wa.send(json.dumps({"type": "ignore", "name": "IgGuest"}))
                await recv_until(wa, "ignore", "error")
                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "accept"}))
                err = await recv_until(wb, "error", "invite_reply")
                assert err.get("type") == "error"
                assert "unavailable" in str(err.get("reason") or "").lower() or "ignore" in str(
                    err.get("reason") or ""
                ).lower()
                # invite still pending (failed before rate? actually after ignore check before rate)
                await wb.send(json.dumps({"type": "lastinvite"}))
                li = await recv_until(wb, "lastinvite", "error")
                assert (li.get("peer") or {}).get("name") == "IgHost", li

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_unit_clear_invite():
    from network.websocket_manager import ConnectionManager

    m = ConnectionManager()

    class W:
        pass

    m._connections[1] = W()
    m._meta[1] = {
        "id": 1,
        "name": "A",
        "last_invite_from_id": 2,
        "last_invite_from_name": "B",
    }
    m.clear_last_invite(1)
    assert m.last_invite_from(1) == (None, None)
