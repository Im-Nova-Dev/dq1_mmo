"""v0.5.142: accept/decline invite_reply WS · near/far · version."""

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


def test_accept_decline_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "reply.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "repa@ex.com", "Ra", "ReplyA")
        tb, cb = register_char(base, "repb@ex.com", "Rb", "ReplyB")
        tc, cc = register_char(base, "repc@ex.com", "Rc", "ReplyC")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wsa, websockets.connect(
                ws_url
            ) as wsb, websockets.connect(ws_url) as wsc:
                await auth(wsa, ta, ca["id"])
                await auth(wsb, tb, cb["id"])
                await auth(wsc, tc, cc["id"])
                await drain(wsa, 0.15)
                await drain(wsb, 0.15)
                await drain(wsc, 0.15)

                # Invite B → accept
                await wsa.send(json.dumps({"type": "invite", "to": "ReplyB"}))
                ok = await recv_until(wsa, "invite", "error")
                assert ok.get("type") == "invite", ok
                peer_inv = await recv_until(wsb, "invite", "error")
                assert peer_inv.get("type") == "invite"

                await asyncio.sleep(1.1)  # avoid chat rate between invite/accept
                await wsb.send(json.dumps({"type": "accept"}))
                echo = await recv_until(wsb, "invite_reply", "error")
                assert echo.get("type") == "invite_reply", echo
                assert echo.get("action") == "accept"
                assert "online" in echo or "nearby" in echo
                peer = await recv_until(wsa, "invite_reply", "error")
                assert peer.get("type") == "invite_reply"
                assert peer.get("action") == "accept"
                assert "coming" in str(peer.get("message") or "").lower()

                # Invite C → decline (rate gap)
                await asyncio.sleep(1.1)
                await wsa.send(json.dumps({"type": "invite", "to": "ReplyC"}))
                ok2 = await recv_until(wsa, "invite", "error")
                assert ok2.get("type") == "invite", ok2
                await recv_until(wsc, "invite", "error")

                await asyncio.sleep(1.1)
                await wsc.send(json.dumps({"type": "decline"}))
                d_echo = await recv_until(wsc, "invite_reply", "error")
                assert d_echo.get("type") == "invite_reply", d_echo
                assert d_echo.get("action") == "decline"
                d_peer = await recv_until(wsa, "invite_reply", "error")
                assert d_peer.get("type") == "invite_reply"
                assert d_peer.get("action") == "decline"

                await wsa.send(json.dumps({"type": "version"}))
                v = await recv_until(wsa, "version", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
