"""v0.5.130: mute handler extract · ignore_list zone/AFK · plain mute messages."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import mute
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_mute_module_extracted_unit():
    assert "ignore" in mute.IGNORE_TYPES or "mute" in mute.IGNORE_TYPES
    assert "unignore" in mute.UNIGNORE_TYPES
    assert "ignores" in mute.LIST_TYPES
    assert mute.IGNORE_TYPES <= mute.ALL_TYPES


def test_ignore_list_includes_zone_unit():
    async def scenario():
        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        # town-ish coords
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="B", x=3, y=2, map_id=0)
        ok, _ = mgr.ignore_player(1, 2)
        assert ok
        card = mgr.ignore_list(1)[0]
        assert card.get("online") is True
        assert card.get("nearby") is True
        # zone when peer is online (no coords leaked)
        assert card.get("zone") in ("town", "field", "dungeon"), card

    asyncio.run(scenario())


def test_ignore_ack_message_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.mute as mute_mod

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Other", x=3, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        mute_mod.manager = mgr
        try:
            outbound: list[dict] = []
            res = await mute_mod.handle(
                1, 1, {"type": "ignore", "name": "Other"}, outbound
            )
            assert res is not None
            m = outbound[0]
            assert m.get("type") == "ignore"
            assert m.get("action") == "ignore"
            assert m.get("ok") is True
            assert isinstance(m.get("message"), str)
            assert "Other" in m["message"] or "Muted" in m["message"]
            assert m.get("count") == 1
            player = m.get("player") or {}
            assert player.get("id") == 2
            assert "nearby" in player or player.get("name")
        finally:
            wm.manager = old
            mute_mod.manager = old

    asyncio.run(scenario())


def test_ignores_list_nearby_count_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.mute as mute_mod

        mgr = ConnectionManager()
        a, b, c = FakeWS(), FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Near", x=3, y=2, map_id=0)
        await mgr.connect(3, c, name="Far", x=18, y=2, map_id=0)
        mgr.ignore_player(1, 2)
        mgr.ignore_player(1, 3)
        old = wm.manager
        wm.manager = mgr
        mute_mod.manager = mgr
        try:
            outbound: list[dict] = []
            res = await mute_mod.handle(1, 1, {"type": "ignores"}, outbound)
            assert res is not None
            m = outbound[0]
            assert m.get("action") == "list"
            assert m.get("count") == 2
            assert m.get("online_count") == 2
            assert m.get("nearby_count") == 1, m
            assert isinstance(m.get("message"), str)
            assert "Near" in m["message"] or "Mute list" in m["message"]
            # zone may appear in message for online peers
            cards = m.get("ignores") or []
            zones = [c.get("zone") for c in cards if c.get("online")]
            assert any(z in ("town", "field", "dungeon") for z in zones), cards
        finally:
            wm.manager = old
            mute_mod.manager = old

    asyncio.run(scenario())


def test_unignore_message_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.mute as mute_mod

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Other", x=3, y=2, map_id=0)
        mgr.ignore_player(1, 2)
        old = wm.manager
        wm.manager = mgr
        mute_mod.manager = mgr
        try:
            outbound: list[dict] = []
            res = await mute_mod.handle(
                1, 1, {"type": "unignore", "name": "Other"}, outbound
            )
            assert res is not None
            m = outbound[0]
            assert m.get("action") == "unignore"
            assert m.get("ok") is True
            assert "Unmuted" in (m.get("message") or "")
            assert m.get("count") == 0
        finally:
            wm.manager = old
            mute_mod.manager = old

    asyncio.run(scenario())
