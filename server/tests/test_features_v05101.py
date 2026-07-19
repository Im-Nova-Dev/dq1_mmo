"""v0.5.101: /pending meetup peek + double-invite pointer hygiene."""

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


def test_pending_empty_and_with_invite(tmp_path, monkeypatch):
    db_path = tmp_path / "pend.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "p1@ex.com", "P1", "PendA")
        tb, cb = register_char(base, "p2@ex.com", "P2", "PendB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "pending"}))
                empty = await recv_until(wa, "pending", "error")
                assert empty.get("type") == "pending", empty
                assert empty.get("has_incoming") is False
                assert empty.get("has_outgoing") is False
                assert "no pending" in str(empty.get("message") or "").lower()

                await wa.send(json.dumps({"type": "invite", "to": "PendB"}))
                assert (await recv_until(wa, "invite", "error")).get("type") == "invite"
                await recv_until(wb, "invite", "error")

                await wa.send(json.dumps({"type": "invites"}))
                pa = await recv_until(wa, "pending", "error")
                assert pa.get("has_outgoing") is True, pa
                assert pa.get("outgoing") and pa["outgoing"].get("name") == "PendB"

                await wb.send(json.dumps({"type": "meetup"}))
                pb = await recv_until(wb, "pending", "error")
                assert pb.get("has_incoming") is True, pb
                assert pb.get("incoming") and pb["incoming"].get("name") == "PendA"

                await wb.send(json.dumps({"type": "help"}))
                h = await recv_until(wb, "help", "error")
                cmds = " ".join(
                    str(c.get("cmd") if isinstance(c, dict) else c)
                    for c in (h.get("commands") or [])
                )
                assert "pending" in cmds or "invites" in cmds, cmds

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_pending_unauth(tmp_path, monkeypatch):
    db_path = tmp_path / "pendu.db"
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
                await ws.send(json.dumps({"type": "pending"}))
                err = await recv_until(ws, "error", "pending")
                assert err.get("type") == "error"
                assert "auth" in str(err.get("reason") or "").lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_version_and_who_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "pendreg.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "v@ex.com", "Vv", "PendVer")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")
                await ws.send(json.dumps({"type": "who"}))
                who = await recv_until(ws, "who", "error")
                assert "combat_count" in who and "afk_count" in who

        asyncio.run(flow())
    finally:
        stop_server(server)
