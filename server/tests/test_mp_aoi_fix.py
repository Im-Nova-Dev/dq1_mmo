"""Multiplayer AOI reliability: disconnect leave, status geometry, zone counts."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager
from tests.ws_helpers import http_json, register_char, start_server, stop_server


class FakeWS:
    def __init__(self, name: str = "ws"):
        self.name = name
        self.closed = False
        self.sent: list = []

    async def close(self, code=1000, reason=""):
        self.closed = True

    async def send_text(self, t: str):
        if self.closed:
            raise RuntimeError("closed")
        self.sent.append(json.loads(t))


async def recv_until(ws, *types, timeout=4.0):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"waiting for {types}")
        raw = await asyncio.wait_for(ws.recv(), remaining)
        m = json.loads(raw)
        if m.get("type") in types:
            return m


async def drain(ws, seconds=0.2):
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
            out.append(json.loads(raw))
        except (asyncio.TimeoutError, TimeoutError):
            break
    return out


def test_disconnect_notifies_geometric_aoi_when_visible_empty():
    """Regression: empty/corrupt visible must not leave ghost avatars nearby."""
    mgr = ConnectionManager()

    async def scenario():
        a, b = FakeWS("a"), FakeWS("b")
        await mgr.connect(1, a, name="Alice", x=5, y=5, map_id=0)
        await mgr.connect(2, b, name="Bob", x=6, y=5, map_id=0)
        # Simulate AOI desync
        mgr.get_meta(1)["visible"] = set()
        mgr.get_meta(2)["visible"] = set()
        await mgr.disconnect(1, a)
        left = [
            m
            for m in b.sent
            if isinstance(m, dict)
            and m.get("type") == "player_left"
            and m.get("player_id") == 1
        ]
        assert left, "Bob must receive player_left via geometric AOI"
        assert left[0].get("reason") == "disconnect"
        assert not mgr.is_online(1)
        assert 1 not in (mgr.get_meta(2) or {}).get("visible", set())

    asyncio.run(scenario())


def test_publish_status_uses_geometry_not_only_visible():
    """Combat/level flags reach peers even if cached visible is stale/empty."""
    mgr = ConnectionManager()

    async def scenario():
        a, b = FakeWS("a"), FakeWS("b")
        await mgr.connect(1, a, name="Alice", x=5, y=5, map_id=0, level=3)
        await mgr.connect(2, b, name="Bob", x=6, y=5, map_id=0)
        mgr.get_meta(1)["visible"] = set()
        mgr.get_meta(2)["visible"] = set()
        mgr.set_in_combat(1, True)
        await mgr.publish_status(1, pulse_online=False)
        updates = [
            m
            for m in b.sent
            if isinstance(m, dict)
            and m.get("type") == "player_update"
            and m.get("player_id") == 1
            and m.get("in_combat") is True
        ]
        assert updates, "Bob must get player_update via geometric AOI"

    asyncio.run(scenario())


def test_ids_nearby_skips_orphan_meta():
    """Orphan meta without a live socket is never 'nearby'."""
    mgr = ConnectionManager()

    async def scenario():
        await mgr.connect(1, FakeWS("a"), name="A", x=5, y=5, map_id=0)
        mgr._meta[99] = {
            "id": 99,
            "name": "Ghost",
            "x": 5.0,
            "y": 5.0,
            "map_id": 0,
            "level": 1,
            "in_combat": False,
            "last_seen": time.monotonic(),
            "visible": set(),
        }
        near = mgr.ids_nearby(1)
        assert 99 not in near
        roster_names = [r["name"] for r in mgr.online_roster()]
        assert "Ghost" not in roster_names
        assert mgr.find_by_prefix("Gho") == []

    asyncio.run(scenario())


def test_zone_counts_town_field():
    mgr = ConnectionManager()

    async def scenario():
        # Town tiles around (2,2); field around (8,6)
        await mgr.connect(1, FakeWS("t"), name="Townie", x=2, y=2, map_id=0)
        await mgr.connect(2, FakeWS("t2"), name="Townie2", x=3, y=2, map_id=0)
        await mgr.connect(3, FakeWS("f"), name="Fielder", x=8, y=6, map_id=0)
        zc = mgr.zone_counts()
        assert zc["town"] == 2, zc
        assert zc["field"] == 1, zc
        assert zc["dungeon"] == 0, zc

    asyncio.run(scenario())


def test_who_includes_zones(tmp_path, monkeypatch):
    db_path = tmp_path / "who_zones.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "za@ex.com", "Za", "ZoneAlice")
        token_b, ch_b = register_char(base, "zb@ex.com", "Zb", "ZoneBob")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                for ws, tok, ch in (
                    (wa, token_a, ch_a),
                    (wb, token_b, ch_b),
                ):
                    await ws.send(
                        json.dumps(
                            {"type": "auth", "token": tok, "character_id": ch["id"]}
                        )
                    )
                    await recv_until(ws, "auth_ok")
                    await drain(ws, 0.1)

                await wa.send(json.dumps({"type": "who"}))
                m = await recv_until(wa, "who", "error")
                assert m.get("type") == "who", m
                zones = m.get("zones") or {}
                assert isinstance(zones, dict), m
                assert "town" in zones and "field" in zones and "dungeon" in zones
                assert int(m.get("online") or 0) >= 2
                # Both spawn in town by default
                assert int(zones.get("town") or 0) >= 1

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_global_chat_respects_ignore(tmp_path, monkeypatch):
    """Global channel still honors ignore lists (reliability + social)."""
    db_path = tmp_path / "gignore.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "ga@ex.com", "Ga", "GlobAlice")
        token_b, ch_b = register_char(base, "gb@ex.com", "Gb", "GlobBob")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                for ws, tok, ch in (
                    (wa, token_a, ch_a),
                    (wb, token_b, ch_b),
                ):
                    await ws.send(
                        json.dumps(
                            {"type": "auth", "token": tok, "character_id": ch["id"]}
                        )
                    )
                    await recv_until(ws, "auth_ok")
                    await drain(ws, 0.1)

                # Bob ignores Alice
                await wb.send(json.dumps({"type": "ignore", "name": "GlobAlice"}))
                m = await recv_until(wb, "ignore", "error")
                assert m.get("type") == "ignore", m

                await drain(wa, 0.05)
                await drain(wb, 0.05)

                await wa.send(
                    json.dumps(
                        {
                            "type": "chat",
                            "channel": "global",
                            "text": "hello everyone",
                        }
                    )
                )
                # Alice may get echo via broadcast including self... broadcast doesn't
                # include a special self path — global broadcast sends to all except
                # ignore. Alice is sender and is not excluded by ignore of self.
                await asyncio.sleep(0.15)
                bob_chat = [
                    x
                    for x in await drain(wb, 0.2)
                    if x.get("type") == "chat" and "hello everyone" in str(x.get("text"))
                ]
                assert not bob_chat, f"ignored global chat leaked to Bob: {bob_chat}"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_reconnect_storm_session_and_aoi(tmp_path, monkeypatch):
    """Rapid socket replace keeps one live session and repairs AOI for peers."""
    db_path = tmp_path / "storm.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "sa@ex.com", "Sa", "StormAlice")
        token_b, ch_b = register_char(base, "sb@ex.com", "Sb", "StormBob")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wb:
                await wb.send(
                    json.dumps(
                        {
                            "type": "auth",
                            "token": token_b,
                            "character_id": ch_b["id"],
                        }
                    )
                )
                await recv_until(wb, "auth_ok")
                await drain(wb, 0.1)

                last_sid = None
                for i in range(4):
                    async with websockets.connect(ws_url) as wa:
                        await wa.send(
                            json.dumps(
                                {
                                    "type": "auth",
                                    "token": token_a,
                                    "character_id": ch_a["id"],
                                }
                            )
                        )
                        m = await recv_until(wa, "auth_ok")
                        sid = m.get("session_id")
                        assert sid is not None
                        if last_sid is not None:
                            assert int(sid) > int(last_sid)
                        last_sid = sid
                        await wa.send(json.dumps({"type": "sync"}))
                        ws_msg = await recv_until(wa, "world_state", "player_joined")
                        # drain rest
                        await drain(wa, 0.08)
                    await asyncio.sleep(0.05)

                # Bob still online; final who should list both after Alice reconnects
                async with websockets.connect(ws_url) as wa:
                    await wa.send(
                        json.dumps(
                            {
                                "type": "auth",
                                "token": token_a,
                                "character_id": ch_a["id"],
                            }
                        )
                    )
                    await recv_until(wa, "auth_ok")
                    await drain(wa, 0.1)
                    await wa.send(json.dumps({"type": "who"}))
                    who = await recv_until(wa, "who")
                    assert int(who.get("online") or 0) >= 2
                    await wa.send(json.dumps({"type": "ping", "t": 1}))
                    pong = await recv_until(wa, "pong")
                    assert pong.get("t") == 1
                    assert "server_t" in pong

        asyncio.run(flow())
    finally:
        stop_server(server)
