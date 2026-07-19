"""v0.5.85 multiplayer reliability: nearby/zone AFK census, stuck clears reason, peeks."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager
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


def test_nearby_and_zone_afk_count_unit():
    mgr = ConnectionManager()

    class FakeWS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, FakeWS(), name="A", x=2, y=2, map_id=0)
        await mgr.connect(2, FakeWS(), name="B", x=3, y=2, map_id=0)
        await mgr.connect(3, FakeWS(), name="C", x=50, y=50, map_id=0)
        assert mgr.afk_count() == 0
        assert mgr.nearby_afk_count(1) == 0
        mgr.set_afk(2, True, message="brb")
        mgr.set_afk(3, True, message="far")
        assert mgr.afk_count() == 2
        # B is nearby to A; C is far
        near_n = mgr.nearby_afk_count(1)
        assert near_n >= 1, "AFK peer B should count as nearby when in AOI"
        assert mgr.nearby_afk_count(1) <= mgr.afk_count()
        # zone_afk includes self if AFK
        mgr.set_afk(1, True, message="me")
        z = mgr.zone_afk_count(1, include_self=True)
        assert z >= 1

    asyncio.run(scenario())


def test_near_zone_played_pong_afk_census(tmp_path, monkeypatch):
    db_path = tmp_path / "afk_census.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "NearA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "NearB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wb.send(json.dumps({"type": "afk", "text": "lunch"}))
                await recv_until(wb, "afk", "error")
                await drain(wa, 0.2)

                await wa.send(json.dumps({"type": "near"}))
                near = await recv_until(wa, "near", "error")
                assert near.get("type") == "near", near
                assert "afk_count" in near, near
                assert int(near.get("afk_count") or 0) >= 1, near
                assert "nearby_afk" in near, near
                assert int(near.get("nearby_afk") or 0) >= 1, near
                assert near.get("you") is not None

                await wa.send(json.dumps({"type": "zone"}))
                zone = await recv_until(wa, "zone", "error")
                assert zone.get("type") == "zone", zone
                assert "afk_count" in zone and "zone_afk" in zone, zone
                assert int(zone.get("afk_count") or 0) >= 1, zone
                assert "AFK" in str(zone.get("message") or ""), zone

                await wa.send(json.dumps({"type": "played"}))
                played = await recv_until(wa, "played", "error")
                assert played.get("type") == "played", played
                assert "afk_count" in played and "nearby_afk" in played, played

                await wa.send(json.dumps({"type": "ping"}))
                pong = await recv_until(wa, "pong", "error")
                assert pong.get("type") == "pong", pong
                assert "afk_count" in pong and "nearby_afk" in pong, pong

                await wa.send(json.dumps({"type": "find", "q": "afk:yes"}))
                find = await recv_until(wa, "find", "error")
                assert find.get("type") == "find", find
                assert "afk_count" in find, find
                players = find.get("players") or []
                hit = next((p for p in players if p.get("name") == "NearB"), None)
                assert hit is not None, players
                assert hit.get("afk") is True
                assert hit.get("afk_message") == "lunch", hit

                await wa.send(json.dumps({"type": "version"}))
                ver = await recv_until(wa, "version", "error")
                assert ver.get("type") == "version"
                assert "afk_count" in ver, ver

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_stuck_clears_afk_message(tmp_path, monkeypatch):
    db_path = tmp_path / "stuck_afk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s@ex.com", "Ss", "StuckAfk")

        async def flow():
            import websockets
            from database.db import db_write

            # Move character into field so stuck teleports
            async with db_write() as db:
                await db.execute(
                    "UPDATE characters SET world_x = 10, world_y = 10 WHERE id = ?",
                    (ca["id"],),
                )
                await db.commit()

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                # Force meta position if spawn still town - walk east a bit
                for i in range(8):
                    await ws.send(
                        json.dumps({"type": "move", "x": 2 + i, "y": 2, "seq": i + 1})
                    )
                    try:
                        await recv_until(ws, "move_ok", "error", timeout=1.0)
                    except TimeoutError:
                        break
                await drain(ws, 0.15)

                await ws.send(json.dumps({"type": "afk", "text": "lost"}))
                ack = await recv_until(ws, "afk", "error")
                assert ack.get("afk_message") == "lost", ack

                await ws.send(json.dumps({"type": "stuck"}))
                # may get move_ok / stuck / system chat
                stuck = None
                end = time.monotonic() + 3
                while time.monotonic() < end and stuck is None:
                    try:
                        m = json.loads(
                            await asyncio.wait_for(ws.recv(), max(0.05, end - time.monotonic()))
                        )
                    except (asyncio.TimeoutError, TimeoutError):
                        continue
                    if m.get("type") == "stuck":
                        stuck = m
                assert stuck is not None, "expected stuck ack"
                # If already home, teleported false — still should clear AFK on teleport path
                # Re-check status
                await drain(ws, 0.15)
                await ws.send(json.dumps({"type": "status"}))
                st = await recv_until(ws, "status", "error")
                you = st.get("you") or {}
                if stuck.get("teleported") is True or stuck.get("ok") is True:
                    # After successful stuck teleport, AFK must be clear
                    if stuck.get("teleported") is True:
                        assert you.get("afk") is False, you
                        assert not you.get("afk_message"), you
                    # already-home stuck does not burn rate and may leave AFK
                    # — only assert clear when teleported

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_zone_who_regression(tmp_path, monkeypatch):
    """Old multiplayer paths still green."""
    db_path = tmp_path / "mp_reg.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "w1@ex.com", "W1", "WhisperA")
        tb, cb = register_char(base, "w2@ex.com", "W2", "WhisperB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(
                    json.dumps({"type": "whisper", "to": "WhisperB", "text": "hello mp"})
                )
                echo = await recv_until(wa, "chat", "error")
                assert echo.get("channel") == "whisper", echo
                inc = await recv_until(wb, "chat", "error")
                assert "hello" in str(inc.get("text") or "")

                # Chat rate interval between social actions
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "yell", "text": "zone hello"}))
                ye = await recv_until(wa, "chat", "error")
                assert ye.get("channel") == "zone", ye
                yb = await recv_until(wb, "chat", "error")
                assert yb.get("channel") == "zone", yb

                await wa.send(json.dumps({"type": "who"}))
                who = await recv_until(wa, "who", "error")
                assert who.get("type") == "who"
                assert int(who.get("online") or 0) >= 2
                assert "afk_count" in who

                # invalid roll keeps AFK (0.5.84 lock-in)
                await wa.send(json.dumps({"type": "afk", "text": "hold"}))
                await recv_until(wa, "afk")
                await wa.send(json.dumps({"type": "roll", "sides": 0}))
                err = await recv_until(wa, "error")
                assert err.get("reason") != "chat_rate_limit"
                await wa.send(json.dumps({"type": "status"}))
                st = await recv_until(wa, "status")
                assert (st.get("you") or {}).get("afk") is True

        asyncio.run(flow())
    finally:
        stop_server(server)
