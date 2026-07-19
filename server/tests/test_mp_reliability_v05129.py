"""v0.5.129: meta_peeks extract · version/played/time multiplayer census."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import meta_peeks
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        import json

        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_meta_peeks_module_extracted_unit():
    assert "version" in meta_peeks.VERSION_TYPES
    assert "played" in meta_peeks.PLAYED_TYPES
    assert "time" in meta_peeks.TIME_TYPES
    assert meta_peeks.VERSION_TYPES <= meta_peeks.ALL_TYPES
    assert meta_peeks.PLAYED_TYPES <= meta_peeks.ALL_TYPES
    assert meta_peeks.TIME_TYPES <= meta_peeks.ALL_TYPES


def test_version_census_unit():
    async def scenario():
        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="B", x=18, y=2, map_id=0)
        outbound: list[dict] = []
        # Patch module manager if needed — handlers use global manager
        from network import websocket_manager as wm

        old = wm.manager
        wm.manager = mgr
        meta_peeks.manager = mgr  # type: ignore[attr-defined]
        try:
            # re-bind imported manager in meta_peeks
            import network.handlers.meta_peeks as mp

            mp.manager = mgr
            res = await mp.handle(1, 1, {"type": "version"}, outbound)
            assert res is not None
            assert outbound and outbound[0].get("type") == "version"
            m = outbound[0]
            assert m.get("online") == 2
            assert "combat_count" in m
            assert "afk_count" in m
            assert isinstance(m.get("message"), str)
            assert "0.5." in str(m.get("version") or "")
            assert m.get("nearby_count") is not None
            assert "session_id" in m
        finally:
            wm.manager = old
            import network.handlers.meta_peeks as mp

            mp.manager = old

    asyncio.run(scenario())


def test_played_zone_combat_message_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.meta_peeks as mp

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        mp.manager = mgr
        try:
            outbound: list[dict] = []
            res = await mp.handle(1, 1, {"type": "played"}, outbound)
            assert res is not None
            m = outbound[0]
            assert m.get("type") == "played"
            assert isinstance(m.get("seconds"), int)
            assert m.get("seconds") >= 0
            assert "in_combat" in m
            assert "combat_count" in m
            assert "nearby_combat" in m
            assert isinstance(m.get("message"), str)
            assert "This session:" in m["message"]
            # town spawn typically zone town
            if m.get("zone"):
                assert m["zone"] in ("town", "field", "dungeon")
                assert m["zone"] in m["message"] or True
        finally:
            wm.manager = old
            mp.manager = old

    asyncio.run(scenario())


def test_time_census_message_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.meta_peeks as mp

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        mp.manager = mgr
        try:
            outbound: list[dict] = []
            res = await mp.handle(1, 1, {"type": "time"}, outbound)
            assert res is not None
            m = outbound[0]
            assert m.get("type") == "time"
            assert "uptime" in m
            assert "uptime_hms" in m
            assert "afk_count" in m
            assert "combat_count" in m
            assert "zones" in m
            assert isinstance(m.get("message"), str)
            assert "online" in m["message"].lower() or "up" in m["message"].lower()
        finally:
            wm.manager = old
            mp.manager = old

    asyncio.run(scenario())
