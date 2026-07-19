"""Unit tests for ConnectionManager AOI, rate limits, and public meta."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import (  # noqa: E402
    CHAT_MIN_INTERVAL,
    ConnectionManager,
    MOVE_MIN_INTERVAL,
)


class FakeWS:
    def __init__(self, name: str = "ws") -> None:
        self.name = name
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code


def _run(coro):
    return asyncio.run(coro)


def test_connect_and_nearby_visibility():
    mgr = ConnectionManager()
    a, b = FakeWS("a"), FakeWS("b")

    async def scenario():
        peers_a = await mgr.connect(1, a, name="Alice", x=2, y=2, map_id=1, level=1)
        assert peers_a == []
        peers_b = await mgr.connect(2, b, name="Bob", x=3, y=2, map_id=1, level=2)
        # Bob should see Alice
        assert any(p["id"] == 1 for p in peers_b)
        nearby = mgr.nearby_players(1)
        assert any(p["id"] == 2 for p in nearby)
        assert nearby[0]["in_combat"] is False
        # disconnect B notifies A
        left = await mgr.disconnect(2, b)
        assert left is not None
        assert any(m.get("type") == "player_left" and m.get("player_id") == 2 for m in a.sent)

    _run(scenario())


def test_aoi_enter_leave_on_move():
    mgr = ConnectionManager()
    a, b = FakeWS("a"), FakeWS("b")

    async def scenario():
        await mgr.connect(1, a, name="Alice", x=2, y=2, map_id=1)
        # far away — outside VISIBILITY_RANGE (10)
        await mgr.connect(2, b, name="Bob", x=18, y=2, map_id=1)
        assert mgr.nearby_players(1) == []

        # Jump into range (one publish_move) — should fire join both ways
        to_self = await mgr.publish_move(2, 5, 2, seq=1)
        assert any(m.get("type") == "player_joined" and m.get("player_id") == 1 for m in to_self)
        assert any(m.get("type") == "player_joined" and m.get("player_id") == 2 for m in a.sent)
        assert any(p["id"] == 2 for p in mgr.nearby_players(1))

        # Stay nearby — movement, not re-join
        a.sent.clear()
        to_self2 = await mgr.publish_move(2, 4, 2, seq=2)
        assert not any(m.get("type") == "player_joined" for m in to_self2)
        assert any(m.get("type") == "player_moved" and m.get("player_id") == 2 for m in a.sent)

        # Walk out of range
        a.sent.clear()
        to_self3 = await mgr.publish_move(2, 18, 2, seq=3)
        assert any(m.get("type") == "player_left" and m.get("player_id") == 1 for m in to_self3)
        assert any(m.get("type") == "player_left" and m.get("player_id") == 2 for m in a.sent)
        assert mgr.nearby_players(1) == []

    _run(scenario())


def test_reconnect_replaces_socket():
    mgr = ConnectionManager()
    old, new = FakeWS("old"), FakeWS("new")

    async def scenario():
        await mgr.connect(1, old, name="Hero", x=2, y=2, map_id=1)
        await mgr.connect(1, new, name="Hero", x=2, y=2, map_id=1)
        assert old.closed is True
        assert mgr.owns(1, new)
        assert not mgr.owns(1, old)
        # stale disconnect must not wipe new session
        left = await mgr.disconnect(1, old)
        assert left is None
        assert mgr.is_online(1)

    _run(scenario())


def test_move_and_chat_rate_limits():
    mgr = ConnectionManager()
    ws = FakeWS()

    async def scenario():
        await mgr.connect(1, ws, name="Hero", x=2, y=2, map_id=1)
        ok1, _ = mgr.allow_move(1)
        assert ok1 is True
        ok2, retry = mgr.allow_move(1)
        assert ok2 is False
        assert retry > 0
        assert retry <= MOVE_MIN_INTERVAL

        cok1, _ = mgr.allow_chat(1)
        assert cok1 is True
        cok2, cretry = mgr.allow_chat(1)
        assert cok2 is False
        assert cretry > 0
        assert cretry <= CHAT_MIN_INTERVAL

    _run(scenario())


def test_public_meta_includes_combat():
    mgr = ConnectionManager()
    ws = FakeWS()

    async def scenario():
        await mgr.connect(1, ws, name="Hero", x=2, y=2, map_id=1, in_combat=True)
        meta = mgr.get_meta(1)
        assert meta["in_combat"] is True
        mgr.set_in_combat(1, False)
        await mgr.connect(2, FakeWS(), name="Other", x=3, y=2, map_id=1)
        peers = mgr.nearby_players(2)
        hero = next(p for p in peers if p["id"] == 1)
        assert hero["in_combat"] is False
        mgr.set_in_combat(1, True)
        await mgr.publish_status(1)
        other_ws = mgr._connections[2]
        assert any(
            m.get("type") == "player_update" and m.get("in_combat") is True
            for m in other_ws.sent
        )

    _run(scenario())


def test_stale_ids():
    mgr = ConnectionManager()

    async def scenario():
        await mgr.connect(1, FakeWS(), name="A", x=1, y=1, map_id=1)
        meta = mgr.get_meta(1)
        meta["last_seen"] = 0.0  # very old
        stale = mgr.stale_ids(now=1000.0)
        assert 1 in stale

    _run(scenario())
