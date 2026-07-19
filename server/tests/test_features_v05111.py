"""v0.5.111: accept zone on invite_reply + r alias (WS)."""

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


def test_accept_zone_and_r_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "acczone.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "AccA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "AccB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "invite", "to": "AccB"}))
                await recv_until(wa, "invite", "error")
                inv = await recv_until(wb, "invite", "error")
                assert inv.get("type") == "invite"
                assert inv.get("zone") in ("town", "field", "dungeon"), inv

                await wb.send(json.dumps({"type": "accept"}))
                echo = await recv_until(wb, "invite_reply", "error")
                assert echo.get("type") == "invite_reply", echo
                assert echo.get("action") == "accept"
                assert echo.get("zone") in ("town", "field", "dungeon"), echo
                peer = await recv_until(wa, "invite_reply", "error")
                assert peer.get("type") == "invite_reply"
                assert peer.get("zone") in ("town", "field", "dungeon"), peer
                assert "coming" in str(peer.get("message") or "").lower()

                # r alias after invite sets whisper peer (chat rate may need a beat)
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "r", "text": "meet at inn"}))
                r = await recv_until(wa, "chat", "error")
                if r.get("reason") == "chat_rate_limit":
                    await asyncio.sleep(float(r.get("retry_after") or 1.0) + 0.1)
                    await wa.send(json.dumps({"type": "r", "text": "meet at inn"}))
                    r = await recv_until(wa, "chat", "error")
                assert r.get("type") == "chat" and r.get("channel") == "whisper", r
                got = await recv_until(wb, "chat", "error")
                assert got.get("channel") == "whisper"

                # lastemote is rate-exempt; wave may rate-limit
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "wave", "to": "AccB"}))
                em = await recv_until(wa, "emote", "error")
                if em.get("reason") == "chat_rate_limit":
                    await asyncio.sleep(float(em.get("retry_after") or 1.0) + 0.1)
                    await wa.send(json.dumps({"type": "wave", "to": "AccB"}))
                    await recv_until(wa, "emote", "error")
                await wa.send(json.dumps({"type": "lastemote"}))
                le = await recv_until(wa, "lastemote", "error")
                assert le.get("type") == "lastemote"
                peer_le = le.get("peer") or {}
                assert peer_le.get("name") == "AccB"
                assert peer_le.get("zone") in ("town", "field", "dungeon"), peer_le

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_version_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "v111.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "v@ex.com", "Vv", "Ver111")

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
