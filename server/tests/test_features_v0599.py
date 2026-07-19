"""v0.5.99: /thank social ack + offline invite clear + regressions."""

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


def test_thank_and_validation(tmp_path, monkeypatch):
    db_path = tmp_path / "thank.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "t1@ex.com", "T1", "ThankA")
        tb, cb = register_char(base, "t2@ex.com", "T2", "ThankB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "thank", "to": "ThankA"}))
                e1 = await recv_until(wa, "error", "thank")
                assert e1.get("type") == "error"
                assert "yourself" in str(e1.get("reason") or "").lower()

                await wa.send(json.dumps({"type": "thank"}))
                e2 = await recv_until(wa, "error", "thank")
                assert e2.get("type") == "error"

                await wa.send(json.dumps({"type": "ty", "to": "ThankB"}))
                ok = await recv_until(wa, "thank", "error")
                assert ok.get("type") == "thank", ok
                assert "ThankB" in str(ok.get("message") or "")

                peer = await recv_until(wb, "thank", "error")
                assert peer.get("type") == "thank"
                assert peer.get("from") == "ThankA"
                assert "thanks" in str(peer.get("message") or "").lower()

                # /r after thank
                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "reply", "text": "np"}))
                r = await recv_until(wb, "chat", "error")
                assert r.get("channel") == "whisper"

                # ignore blocks without rate burn
                await wb.send(json.dumps({"type": "ignore", "name": "ThankA"}))
                await recv_until(wb, "ignore", "error")
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "thanks", "to": "ThankB"}))
                e3 = await recv_until(wa, "error", "thank")
                assert e3.get("type") == "error"
                assert "unavailable" in str(e3.get("reason") or "").lower()
                assert e3.get("reason") != "chat_rate_limit"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_thank_help_and_bool_id(tmp_path, monkeypatch):
    db_path = tmp_path / "thankhelp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "HelpThank")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "thank", "to_id": True}))
                err = await recv_until(ws, "error", "thank")
                assert err.get("type") == "error"
                assert "not found" in str(err.get("reason") or "").lower()

                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                cmds = " ".join(
                    str(c.get("cmd") if isinstance(c, dict) else c)
                    for c in (h.get("commands") or [])
                )
                assert "thank" in cmds or "ty" in cmds, cmds

                await ws.send(json.dumps({"type": "version"}))
                v = await recv_until(ws, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_share_then_thank_loop(tmp_path, monkeypatch):
    """Meetup hygiene: share → thank @last."""
    db_path = tmp_path / "sharethank.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s1@ex.com", "S1", "ShareThankA")
        tb, cb = register_char(base, "s2@ex.com", "S2", "ShareThankB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "share", "to": "ShareThankB"}))
                assert (await recv_until(wa, "share", "error")).get("type") == "share"
                assert (await recv_until(wb, "share", "error")).get("type") == "share"

                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "thank", "to": "@last"}))
                th = await recv_until(wb, "thank", "error")
                assert th.get("type") == "thank", th
                got = await recv_until(wa, "thank", "error")
                assert got.get("type") == "thank"
                assert got.get("from") == "ShareThankB"

        asyncio.run(flow())
    finally:
        stop_server(server)
