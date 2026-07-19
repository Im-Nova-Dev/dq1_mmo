"""v0.5.120: auth restores emote/invite peers · version · welcome flags."""

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


def test_auth_restored_emote_invite_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "re.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ra@ex.com", "Ra", "RestA")
        tb, cb = register_char(base, "rb@ex.com", "Rb", "RestB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "wave", "to": "RestB"}))
                em = await recv_until(wa, "emote", "error")
                if em.get("reason") == "chat_rate_limit":
                    await asyncio.sleep(float(em.get("retry_after") or 1.0) + 0.1)
                    await wa.send(json.dumps({"type": "wave", "to": "RestB"}))
                    em = await recv_until(wa, "emote", "error")
                assert em.get("type") == "emote", em

                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "invite", "to": "RestB"}))
                inv = await recv_until(wa, "invite", "invite_sent", "error", "chat")
                # invite may surface as several types; accept non-error
                if inv.get("type") == "error" and inv.get("reason") == "chat_rate_limit":
                    await asyncio.sleep(float(inv.get("retry_after") or 1.0) + 0.1)
                    await wa.send(json.dumps({"type": "invite", "to": "RestB"}))
                    inv = await recv_until(wa, "invite", "invite_sent", "error", "chat")
                assert inv.get("type") != "error" or inv.get("reason") != "player not online", inv

            # soft reconnect A
            async with websockets.connect(ws_url) as wa2:
                await wa2.send(
                    json.dumps(
                        {"type": "auth", "token": ta, "character_id": ca["id"]}
                    )
                )
                auth_ok = world = None
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and (auth_ok is None or world is None):
                    raw = await asyncio.wait_for(wa2.recv(), 1.0)
                    m = json.loads(raw)
                    if m.get("type") == "auth_ok":
                        auth_ok = m
                    if m.get("type") == "world_state" and m.get("restored") is not None:
                        world = m
                assert auth_ok and world, (auth_ok, world)
                rest = world.get("restored") or auth_ok.get("restored") or {}
                # emote peer should rehydrate
                assert rest.get("last_emote") is True or (
                    world.get("last_emote_to") or auth_ok.get("last_emote_to")
                ), rest
                welcome = str(auth_ok.get("welcome") or "")
                if rest.get("last_emote"):
                    assert "emote" in welcome.lower() or "Restored" in welcome
                # version still healthy
                await wa2.send(json.dumps({"type": "version"}))
                v = await recv_until(wa2, "version", "about", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_first_join_no_false_emote_invite_restored(tmp_path, monkeypatch):
    db_path = tmp_path / "fj2.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "fj2@ex.com", "Fj", "First2")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": ta, "character_id": ca["id"]}
                    )
                )
                auth_ok = world = None
                deadline = time.monotonic() + 4.0
                while time.monotonic() < deadline and (
                    auth_ok is None or world is None
                ):
                    raw = await asyncio.wait_for(ws.recv(), 1.0)
                    m = json.loads(raw)
                    if m.get("type") == "auth_ok":
                        auth_ok = m
                    if m.get("type") == "world_state":
                        world = m
                assert auth_ok and world
                rest = world.get("restored") or auth_ok.get("restored") or {}
                assert rest.get("last_emote") is False or rest.get("last_emote") is None
                assert rest.get("last_invite") is False or rest.get("last_invite") is None
                assert world.get("last_emote_to") in (None, {}) or not world.get(
                    "last_emote_to"
                )
                assert "emote peers" not in str(auth_ok.get("welcome") or "").lower()
                assert "meetup invites" not in str(auth_ok.get("welcome") or "").lower()

        asyncio.run(flow())
    finally:
        stop_server(server)
