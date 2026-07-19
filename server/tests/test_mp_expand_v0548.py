"""v0.5.48 multiplayer: whisper delivery fail-closed, sync zones, /roll, combat engage chat."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

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
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
            out.append(json.loads(raw))
        except (asyncio.TimeoutError, TimeoutError):
            break
    return out


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    await recv_until(ws, "auth_ok")
    await drain(ws, 0.12)


def test_whisper_send_fail_does_not_echo(tmp_path, monkeypatch):
    """If target socket send fails, sender gets error and no self-echo."""
    db_path = tmp_path / "wfail.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "wa@ex.com", "WaU", "WhA")
        tb, cb = register_char(base, "wb@ex.com", "WbU", "WhB")

        async def flow():
            import websockets
            from network.websocket_manager import manager

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                orig = manager.send
                manager.send = AsyncMock(return_value=False)  # type: ignore[method-assign]
                try:
                    await wa.send(
                        json.dumps(
                            {"type": "whisper", "to": "WhB", "text": "secret"}
                        )
                    )
                    err = await recv_until(wa, "error", "chat")
                    assert err.get("type") == "error", err
                    assert err.get("reason") == "player not online", err
                finally:
                    manager.send = orig  # type: ignore[method-assign]

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_sync_includes_zones_and_roster(tmp_path, monkeypatch):
    db_path = tmp_path / "sync.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sa@ex.com", "SaU", "SyncA")
        tb, cb = register_char(base, "sb@ex.com", "SbU", "SyncB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "sync"}))
                ws_msg = await recv_until(wa, "world_state", "error")
                assert ws_msg.get("type") == "world_state", ws_msg
                assert isinstance(ws_msg.get("zones"), dict), ws_msg
                assert "town" in (ws_msg.get("zones") or {}), ws_msg
                assert isinstance(ws_msg.get("roster"), list), ws_msg
                assert int(ws_msg.get("online") or 0) >= 2, ws_msg
                assert ws_msg.get("nearby_count") is not None, ws_msg
                assert ws_msg.get("session_id") is not None, ws_msg

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_roll_nearby(tmp_path, monkeypatch):
    db_path = tmp_path / "roll.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ra@ex.com", "RaU", "RollA")
        tb, cb = register_char(base, "rb@ex.com", "RbU", "RollB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "roll", "sides": 20}))
                ma = await recv_until(wa, "chat", "error")
                assert ma.get("type") == "chat", ma
                assert ma.get("channel") == "system", ma
                assert "d20" in str(ma.get("text") or ""), ma
                roll = ma.get("roll") or {}
                assert int(roll.get("sides") or 0) == 20, roll
                assert 1 <= int(roll.get("value") or 0) <= 20, roll
                # Peer nearby receives too
                mb = await recv_until(wb, "chat", "error")
                assert mb.get("type") == "chat", mb
                assert "RollA" in str(mb.get("text") or ""), mb

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_combat_engage_system_chat(tmp_path, monkeypatch):
    db_path = tmp_path / "eng.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ea@ex.com", "EaU", "FightA")
        tb, cb = register_char(base, "eb@ex.com", "EbU", "WatchB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime"})
                )
                cs = await recv_until(wa, "combat_start", "error")
                assert cs.get("type") == "combat_start", cs
                # Bob should see system "FightA is fighting!"
                saw = None
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(wb.recv(), 0.35)
                        m = json.loads(raw)
                        if (
                            m.get("type") == "chat"
                            and m.get("channel") == "system"
                            and "fighting" in str(m.get("text") or "").lower()
                        ):
                            saw = m
                            break
                    except Exception:
                        break
                assert saw is not None, "peer never saw combat engage system chat"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_near_includes_zones(tmp_path, monkeypatch):
    db_path = tmp_path / "near.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "na@ex.com", "NaU", "NearZones")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                await ws.send(json.dumps({"type": "near"}))
                m = await recv_until(ws, "near", "error")
                assert m.get("type") == "near", m
                assert isinstance(m.get("zones"), dict), m
                assert m.get("zones").get("town", 0) >= 1, m

        asyncio.run(flow())
    finally:
        stop_server(server)
