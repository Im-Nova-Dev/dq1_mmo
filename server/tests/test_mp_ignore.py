"""Multiplayer ignore list + idle roster + dead-socket cleanup."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import IDLE_SOFT, ConnectionManager
from tests.ws_helpers import register_char, start_server, stop_server


async def recv_until(ws, *types, timeout=4.0):
    deadline = time.monotonic() + timeout
    while True:
        rem = deadline - time.monotonic()
        if rem <= 0:
            raise TimeoutError(types)
        m = json.loads(await asyncio.wait_for(ws.recv(), rem))
        if m.get("type") in types:
            return m


async def drain(ws, seconds=0.12):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
        except (asyncio.TimeoutError, TimeoutError):
            break


def test_ignore_blocks_nearby_chat_unit():
    mgr = ConnectionManager()

    class WS:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(json.loads(t))

        async def close(self, *a, **k):
            pass

    async def scenario():
        a, b = WS(), WS()
        await mgr.connect(1, a, name="Alice", x=2, y=2, map_id=1)
        await mgr.connect(2, b, name="Bob", x=3, y=2, map_id=1)
        ok, reason = mgr.ignore_player(2, 1)  # Bob ignores Alice
        assert ok, reason
        assert mgr.is_ignored_by(2, 1)
        a.sent.clear()
        b.sent.clear()
        await mgr.broadcast_nearby(
            1, {"type": "chat", "text": "hi bob", "channel": "nearby"}, include_self=True
        )
        # Alice hears herself
        assert any(m.get("text") == "hi bob" for m in a.sent)
        # Bob does not
        assert not any(m.get("text") == "hi bob" for m in b.sent), b.sent
        # unignore restores
        mgr.unignore_player(2, 1)
        b.sent.clear()
        await mgr.broadcast_nearby(
            1, {"type": "chat", "text": "again", "channel": "nearby"}, include_self=False
        )
        assert any(m.get("text") == "again" for m in b.sent)

    asyncio.run(scenario())


def test_ignore_survives_soft_reconnect():
    mgr = ConnectionManager()

    class WS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        w = WS()
        await mgr.connect(1, w, name="A", x=2, y=2, map_id=1)
        await mgr.connect(2, WS(), name="B", x=3, y=2, map_id=1)
        mgr.ignore_player(1, 2)
        await mgr.disconnect(1, w)
        assert 1 in mgr._soft_grace
        await mgr.connect(1, WS(), name="A", x=2, y=2, map_id=1)
        assert mgr.is_ignored_by(1, 2)

    asyncio.run(scenario())


def test_idle_flag_on_roster():
    mgr = ConnectionManager()

    class WS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, WS(), name="Fresh", x=2, y=2, map_id=1)
        card = mgr.online_roster()[0]
        assert card.get("idle") is False
        # age last_seen
        mgr.get_meta(1)["last_seen"] = time.monotonic() - (IDLE_SOFT + 5)
        card2 = mgr.online_roster()[0]
        assert card2.get("idle") is True
        mgr.touch(1)
        assert mgr.online_roster()[0].get("idle") is False

    asyncio.run(scenario())


def test_ignore_ws_and_whisper(tmp_path, monkeypatch):
    db_path = tmp_path / "ign.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ia@ex.com", "IgA", "IgAlice")
        tb, cb = register_char(base, "ib@ex.com", "IgB", "IgBob")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                for ws, tok, ch in ((wa, ta, ca), (wb, tb, cb)):
                    await ws.send(
                        json.dumps(
                            {"type": "auth", "token": tok, "character_id": ch["id"]}
                        )
                    )
                    await recv_until(ws, "auth_ok")
                    await recv_until(ws, "world_state")
                await drain(wa)
                await drain(wb)

                await wb.send(json.dumps({"type": "ignore", "name": "IgAlice"}))
                m = await recv_until(wb, "ignore", "error")
                assert m.get("type") == "ignore", m
                assert m.get("action") == "ignore"

                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "say", "text": "secret nearby"}))
                # Alice hears echo; Bob should not get it
                ca_msg = await recv_until(wa, "chat")
                assert ca_msg.get("text") == "secret nearby"
                got_b = False
                end = time.monotonic() + 0.5
                while time.monotonic() < end:
                    try:
                        raw = await asyncio.wait_for(wb.recv(), 0.15)
                        mm = json.loads(raw)
                        if mm.get("type") == "chat" and mm.get("text") == "secret nearby":
                            got_b = True
                            break
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                assert not got_b, "ignored player must not receive nearby chat"

                await asyncio.sleep(0.85)
                await wa.send(
                    json.dumps(
                        {"type": "whisper", "to": "IgBob", "text": "psst"}
                    )
                )
                err = await recv_until(wa, "error", "chat")
                assert err.get("type") == "error"
                assert "unavailable" in (err.get("reason") or "").lower()

                await wb.send(json.dumps({"type": "unignore", "name": "IgAlice"}))
                m2 = await recv_until(wb, "ignore", "error")
                assert m2.get("action") == "unignore"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_dead_socket_removed_from_online():
    """Failed send must disconnect dead peers (reliability)."""
    mgr = ConnectionManager()

    class OK:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(t)

        async def close(self, *a, **k):
            pass

    class Dead:
        async def send_text(self, t):
            raise RuntimeError("broken")

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, OK(), name="A", x=2, y=2, map_id=1)
        await mgr.connect(2, Dead(), name="B", x=3, y=2, map_id=1)
        await mgr.broadcast_nearby(1, {"type": "chat", "text": "ping"}, include_self=True)
        assert not mgr.is_online(2)
        assert 2 not in mgr.online_ids()

    asyncio.run(scenario())
