"""v0.5.148: inn extract · town gate · combat gate · AFK clear · census."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import inn
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def _bind(mgr):
    from network import websocket_manager as wm
    import network.handlers.inn as inn_mod

    old = (wm.manager, inn_mod.manager)
    wm.manager = mgr
    inn_mod.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers.inn as inn_mod

    wm.manager, inn_mod.manager = old


def test_inn_module_extracted_unit():
    assert "inn" in inn.INN_TYPES or "rest" in inn.ALL_TYPES
    assert "sleep" in inn.ALL_TYPES


def test_inn_quote_town_unit():
    async def scenario():
        import network.handlers.inn as inn_mod

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:

            async def fake_get(cid):
                return {
                    "id": cid,
                    "level": 1,
                    "gold": "100",
                    "current_hp": 5,
                    "max_hp": 10,
                    "current_mp": 0,
                    "max_mp": 5,
                }

            with patch(
                "network.handlers.inn.get_character", side_effect=fake_get
            ), patch("network.handlers.inn.inn_cost", return_value=4):
                outbound: list[dict] = []
                await inn_mod.handle(
                    1, 1, {"type": "inn", "preview": True}, outbound
                )
                m = outbound[0]
                assert m.get("preview") is True
                assert m.get("cost") == 4
                assert m.get("zone") == "town"
                assert "online" in m
                assert "Inn stay" in str(m.get("message") or "") or m.get("full")
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_inn_not_in_town_unit():
    async def scenario():
        import network.handlers.inn as inn_mod
        from game.world_manager import zone_at

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=12, y=12, map_id=0)
        old = _bind(mgr)
        try:
            if zone_at(12, 12) != "town":
                outbound: list[dict] = []
                await inn_mod.handle(1, 1, {"type": "rest"}, outbound)
                assert outbound[0].get("reason") == "inn only in town"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_inn_combat_blocked_unit():
    async def scenario():
        import network.handlers.inn as inn_mod
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            with patch.object(combat_engine, "is_in_combat", return_value=True):
                outbound: list[dict] = []
                await inn_mod.handle(1, 1, {"type": "inn"}, outbound)
                assert outbound[0].get("reason") == "in combat"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_rest_clears_afk_unit():
    async def scenario():
        import network.handlers.inn as inn_mod

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        mgr.set_afk(1, True, message="nap")
        old = _bind(mgr)
        try:

            async def fake_get(cid):
                return {
                    "id": cid,
                    "level": 1,
                    "gold": "100",
                    "current_hp": 5,
                    "max_hp": 10,
                    "current_mp": 0,
                    "max_mp": 5,
                }

            async def fake_rest(db, char):
                return True, None, {"cost": 4}

            with patch(
                "network.handlers.inn.get_character", side_effect=fake_get
            ), patch(
                "network.handlers.inn.rest_at_inn", side_effect=fake_rest
            ), patch(
                "network.handlers.inn.battle_spells_at", return_value=[]
            ), patch(
                "network.handlers.inn.equipment_bonuses", return_value={}
            ), patch("network.handlers.inn.db_write") as dbw:

                class CM:
                    async def __aenter__(self):
                        return object()

                    async def __aexit__(self, *a):
                        return False

                dbw.return_value = CM()
                outbound: list[dict] = []
                await inn_mod.handle(1, 1, {"type": "rest"}, outbound)
                m = outbound[0]
                assert m.get("preview") is False or m.get("type") == "rest_ok"
                assert mgr.get_meta(1).get("afk") is not True
                assert "online" in m
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_inn_auth_required_unit():
    async def scenario():
        import network.handlers.inn as inn_mod

        mgr = ConnectionManager()
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await inn_mod.handle(None, None, {"type": "inn"}, outbound)
            assert outbound[0].get("reason") == "authenticate first"
        finally:
            _restore(old)

    asyncio.run(scenario())
