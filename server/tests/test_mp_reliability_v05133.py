"""v0.5.133: safety handler extract · stuck/quit multiplayer census."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import safety
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_safety_module_extracted_unit():
    assert "quit" in safety.QUIT_TYPES
    assert "stuck" in safety.STUCK_TYPES
    assert "home" in safety.STUCK_TYPES
    assert safety.QUIT_TYPES | safety.STUCK_TYPES == safety.ALL_TYPES


def test_stuck_already_home_census_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.safety as safety_mod
        from game.world_manager import SPAWN_X, SPAWN_Y

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=SPAWN_X, y=SPAWN_Y, map_id=0)
        old = wm.manager
        wm.manager = mgr
        safety_mod.manager = mgr
        try:
            outbound: list[dict] = []
            res = await safety_mod.handle(1, 1, {"type": "stuck"}, outbound)
            assert res is not None
            m = outbound[0]
            assert m.get("type") == "stuck"
            assert m.get("teleported") is False
            assert m.get("zone") == "town"
            assert "You are already in town" in (m.get("message") or "")
            assert "online" in m
            assert "nearby_count" in m
            assert m.get("afk") is False
        finally:
            wm.manager = old
            safety_mod.manager = old

    asyncio.run(scenario())


def test_quit_ack_fields_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.safety as safety_mod

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Other", x=3, y=2, map_id=0)
        old = wm.manager
        wm.manager = mgr
        safety_mod.manager = mgr
        try:
            outbound: list[dict] = []
            res = await safety_mod.handle(1, 1, {"type": "quit"}, outbound)
            # quit returns character_id None
            assert res is not None
            cid, uid, out, _ = res
            assert cid is None
            m = out[0]
            assert m.get("type") == "quit"
            assert m.get("ok") is True
            assert "Farewell" in (m.get("message") or "")
            assert "online" in m
            assert m.get("online") == 1  # other remains
            # hero disconnected
            assert 1 not in mgr.online_ids()
            assert 2 in mgr.online_ids()
        finally:
            wm.manager = old
            safety_mod.manager = old

    asyncio.run(scenario())


def test_stuck_combat_blocked_unit():
    async def scenario():
        from network import websocket_manager as wm
        import network.handlers.safety as safety_mod
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=10, y=10, map_id=0)
        # force combat flag if API allows
        old_ce = combat_engine.is_in_combat
        combat_engine.is_in_combat = lambda cid: cid == 1  # type: ignore
        old = wm.manager
        wm.manager = mgr
        safety_mod.manager = mgr
        try:
            outbound: list[dict] = []
            res = await safety_mod.handle(1, 1, {"type": "home"}, outbound)
            assert res is not None
            m = outbound[0]
            assert m.get("type") == "error"
            assert m.get("reason") == "in combat"
        finally:
            combat_engine.is_in_combat = old_ce  # type: ignore
            wm.manager = old
            safety_mod.manager = old

    asyncio.run(scenario())
