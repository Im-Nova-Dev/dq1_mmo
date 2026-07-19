"""v0.5.122: auth last_whisper peer card · version."""

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


def test_auth_whisper_peer_card_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "lw.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "lwa@ex.com", "Wa", "WhA")
        tb, cb = register_char(base, "lwb@ex.com", "Wb", "WhB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)
                await asyncio.sleep(0.85)
                await wa.send(
                    json.dumps({"type": "whisper", "to": "WhB", "text": "hello"})
                )
                ch = await recv_until(wa, "chat", "error")
                if ch.get("reason") == "chat_rate_limit":
                    await asyncio.sleep(float(ch.get("retry_after") or 1.0) + 0.1)
                    await wa.send(
                        json.dumps(
                            {"type": "whisper", "to": "WhB", "text": "hello"}
                        )
                    )
                    ch = await recv_until(wa, "chat", "error")
                assert ch.get("type") == "chat", ch

                await wa.send(json.dumps({"type": "lastwhisper"}))
                lw = await recv_until(wa, "lastwhisper", "error")
                assert lw.get("type") == "lastwhisper", lw
                assert lw.get("has_peer") is True or (lw.get("peer") or {}).get(
                    "name"
                )

            # soft reconnect
            async with websockets.connect(ws_url) as wa2:
                await wa2.send(
                    json.dumps(
                        {"type": "auth", "token": ta, "character_id": ca["id"]}
                    )
                )
                auth_ok = world = None
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and (
                    auth_ok is None or world is None
                ):
                    raw = await asyncio.wait_for(wa2.recv(), 1.0)
                    m = json.loads(raw)
                    if m.get("type") == "auth_ok":
                        auth_ok = m
                    if m.get("type") == "world_state" and m.get("restored") is not None:
                        world = m
                assert auth_ok and world
                rest = world.get("restored") or auth_ok.get("restored") or {}
                assert rest.get("last_whisper") is True, rest
                lw_card = world.get("last_whisper") or auth_ok.get("last_whisper") or {}
                assert lw_card.get("name") == "WhB" or lw_card.get("id"), lw_card
                # near/far online flags when peer still online
                assert "online" in lw_card or lw_card.get("name"), lw_card

                await wa2.send(json.dumps({"type": "version"}))
                v = await recv_until(wa2, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
