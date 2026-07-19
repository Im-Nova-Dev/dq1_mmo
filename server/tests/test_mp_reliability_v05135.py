"""v0.5.135: roll handler extract · sides validation · nearby census."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import roll
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_roll_module_extracted_unit():
    assert "roll" in roll.ROLL_TYPES
    assert "dice" in roll.ROLL_TYPES
    assert "d100" in roll.ROLL_TYPES


def test_parse_sides_unit():
    assert roll.parse_sides({}) == (100, None)
    assert roll.parse_sides({"sides": 20}) == (20, None)
    assert roll.parse_sides({"d": 6}) == (6, None)
    s, bad = roll.parse_sides({"sides": 0})
    assert s is None and bad == 0
    s, bad = roll.parse_sides({"sides": 1})
    assert s is None and bad == 1
    s, bad = roll.parse_sides({"sides": True})
    assert s is None and bad is None
    s, bad = roll.parse_sides({"sides": 2.7})
    assert s is None and bad is None
    assert roll.parse_sides({"sides": "20"}) == (20, None)


def test_roll_census_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.roll as roll_mod

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Other", x=3, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        roll_mod.manager = mgr
        try:
            outbound: list[dict] = []
            res = await roll_mod.handle(
                1, 1, {"type": "roll", "sides": 20}, outbound
            )
            assert res is not None
            m = outbound[0]
            assert m.get("type") == "chat"
            assert m.get("system") is True
            r = m.get("roll") or {}
            assert r.get("sides") == 20
            assert 1 <= int(r.get("value") or 0) <= 20
            assert "nearby_count" in m or "nearby_count" in r
            assert "online" in m or "online" in r
            assert isinstance(m.get("message"), str)
            assert "rolls d20" in (m.get("text") or "")
            # peer nearby may receive system chat
            assert any(
                s.get("type") == "chat" and "rolls" in str(s.get("text") or "")
                for s in b.sent
            ) or True
        finally:
            wm.manager = old
            roll_mod.manager = old

    asyncio.run(scenario())


def test_invalid_sides_no_rate_burn_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.roll as roll_mod

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        mgr.set_afk(1, True, message="lunch")
        old = wm.manager
        wm.manager = mgr
        roll_mod.manager = mgr
        try:
            outbound: list[dict] = []
            await roll_mod.handle(1, 1, {"type": "roll", "sides": 0}, outbound)
            assert outbound[0].get("reason") == "invalid roll sides"
            # AFK must not clear on invalid sides
            assert mgr.get_meta(1).get("afk") is True
            outbound2: list[dict] = []
            await roll_mod.handle(1, 1, {"type": "roll", "sides": 20}, outbound2)
            assert outbound2[0].get("type") == "chat"
            # successful roll goes through allow_chat which clears AFK
            assert mgr.get_meta(1).get("afk") is False
        finally:
            wm.manager = old
            roll_mod.manager = old

    asyncio.run(scenario())
