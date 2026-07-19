"""v0.5.102: invite supersede + dual whisper after invite (integration)."""

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


def test_invite_superseded_notice(tmp_path, monkeypatch):
    db_path = tmp_path / "sup.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "SupA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "SupB")
        tc, cc = register_char(base, "c@ex.com", "Cc", "SupC")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
                websockets.connect(ws_url) as wc,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await auth(wc, tc, cc["id"])
                await drain(wa)
                await drain(wb)
                await drain(wc)

                await wa.send(json.dumps({"type": "invite", "to": "SupB"}))
                assert (await recv_until(wa, "invite", "error")).get("type") == "invite"
                await recv_until(wb, "invite", "error")

                await asyncio.sleep(0.85)
                await wc.send(json.dumps({"type": "invite", "to": "SupB"}))
                assert (await recv_until(wc, "invite", "error")).get("type") == "invite"
                # A should learn their invite was superseded
                sup = await recv_until(wa, "invite_superseded", "error", "invite")
                assert sup.get("type") == "invite_superseded", sup
                assert "SupB" in str(sup.get("message") or "")

                await wa.send(json.dumps({"type": "pending"}))
                pa = await recv_until(wa, "pending", "error")
                assert pa.get("has_outgoing") is False, pa

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_invite_enables_guest_reply(tmp_path, monkeypatch):
    """Guest can /r after invite without accepting first."""
    db_path = tmp_path / "invr.db"
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
                await wb.send(json.dumps({"type": "reply", "text": "coming!"}))
                r = await recv_until(wb, "chat", "error")
                assert r.get("channel") == "whisper", r
                got = await recv_until(wa, "chat", "error")
                assert got.get("channel") == "whisper"
                assert "coming" in str(got.get("text") or "")

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_pending_and_version_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "pv.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "v@ex.com", "Vv", "VerPend")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "pending"}))
                p = await recv_until(ws, "pending", "error")
                assert p.get("type") == "pending"
                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
