"""v0.5.149: use_item extract · AFK clear · turn gate · item required."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import use_item
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
    import network.handlers._common as common
    import network.handlers.use_item as ui

    old = (wm.manager, common.manager, ui.manager)
    wm.manager = mgr
    common.manager = mgr
    ui.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.use_item as ui

    wm.manager, common.manager, ui.manager = old


def test_use_item_module_extracted_unit():
    assert "use" in use_item.USE_TYPES or "use_item" in use_item.ALL_TYPES
    assert "consume" in use_item.ALL_TYPES


def test_use_item_required_unit():
    async def scenario():
        import network.handlers.use_item as ui

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ui.handle(1, 1, {"type": "use"}, outbound)
            assert outbound[0].get("reason") in ("item required", "unknown item")
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_use_combat_wait_turn_unit():
    async def scenario():
        import network.handlers.use_item as ui
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            battle = MagicMock()
            battle.phase = "enemy"
            battle.outcome = "ongoing"

            async def fake_get(cid):
                return {"id": cid, "level": 1}

            with patch.object(combat_engine, "is_in_combat", return_value=True), patch.object(
                combat_engine, "get", return_value=battle
            ), patch(
                "network.handlers.use_item.get_character", side_effect=fake_get
            ):
                outbound: list[dict] = []
                await ui.handle(
                    1, 1, {"type": "use", "item": "herb"}, outbound
                )
                assert outbound[0].get("reason") == "wait for your turn"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_use_clears_afk_overworld_unit():
    async def scenario():
        import network.handlers.use_item as ui
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        mgr.set_afk(1, True, message="snack")
        old = _bind(mgr)
        try:

            async def fake_get(cid):
                return {
                    "id": cid,
                    "level": 1,
                    "current_hp": 5,
                    "max_hp": 10,
                }

            async def fake_use(db, char, item_id, in_combat=False, rng=None):
                return True, None, {
                    "effect": "heal",
                    "name": "Herb",
                    "healed": 10,
                }

            async def fake_inv(cid):
                return {"type": "inventory_update", "bag": []}

            with patch.object(combat_engine, "is_in_combat", return_value=False), patch(
                "network.handlers.use_item.get_character", side_effect=fake_get
            ), patch(
                "network.handlers.use_item.use_consumable", side_effect=fake_use
            ), patch(
                "network.handlers.use_item.battle_spells_at", return_value=[]
            ), patch(
                "network.handlers.use_item.equipment_bonuses", return_value={}
            ), patch(
                "network.handlers.use_item._inventory_msg", side_effect=fake_inv
            ), patch("network.handlers.use_item.db_write") as dbw:

                class CM:
                    async def __aenter__(self):
                        return object()

                    async def __aexit__(self, *a):
                        return False

                dbw.return_value = CM()
                outbound: list[dict] = []
                await ui.handle(
                    1, 1, {"type": "use", "item": "herb"}, outbound
                )
                used = [m for m in outbound if m.get("type") == "item_used"]
                assert used, outbound
                assert mgr.get_meta(1).get("afk") is not True
                assert "online" in used[0]
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_use_auth_required_unit():
    async def scenario():
        import network.handlers.use_item as ui

        mgr = ConnectionManager()
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ui.handle(None, None, {"type": "use", "item": "herb"}, outbound)
            assert outbound[0].get("reason") == "authenticate first"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_wings_teleport_move_ok_unit():
    async def scenario():
        import network.handlers.use_item as ui
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=10, y=10, map_id=0)
        old = _bind(mgr)
        try:

            async def fake_get(cid):
                return {"id": cid, "level": 1}

            async def fake_use(db, char, item_id, in_combat=False, rng=None):
                return True, None, {
                    "effect": "teleport",
                    "teleported": True,
                    "x": 2,
                    "y": 2,
                    "name": "Wings",
                }

            async def fake_inv(cid):
                return {"type": "inventory_update", "bag": []}

            with patch.object(combat_engine, "is_in_combat", return_value=False), patch(
                "network.handlers.use_item.get_character", side_effect=fake_get
            ), patch(
                "network.handlers.use_item.use_consumable", side_effect=fake_use
            ), patch(
                "network.handlers.use_item.battle_spells_at", return_value=[]
            ), patch(
                "network.handlers.use_item.equipment_bonuses", return_value={}
            ), patch(
                "network.handlers.use_item._inventory_msg", side_effect=fake_inv
            ), patch("network.handlers.use_item.db_write") as dbw:

                class CM:
                    async def __aenter__(self):
                        return object()

                    async def __aexit__(self, *a):
                        return False

                dbw.return_value = CM()
                outbound: list[dict] = []
                await ui.handle(
                    1, 1, {"type": "use", "item": "wings"}, outbound
                )
                moves = [m for m in outbound if m.get("type") == "move_ok"]
                assert moves and moves[0].get("reason") == "wings"
                assert moves[0].get("x") == 2
        finally:
            _restore(old)

    asyncio.run(scenario())
