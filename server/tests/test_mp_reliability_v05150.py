"""v0.5.150: field_magic extract · AFK clear · combat defer · census · teleport AOI."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import field_magic
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
    import network.handlers.field_magic as fm

    old = (wm.manager, fm.manager)
    wm.manager = mgr
    fm.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers.field_magic as fm

    wm.manager, fm.manager = old


def test_field_magic_module_extracted_unit():
    assert "cast" in field_magic.CAST_TYPES or "cast" in field_magic.ALL_TYPES
    assert "heal" in field_magic.FIELD_SHORTCUTS
    assert "outside" in field_magic.ALL_TYPES


def test_field_magic_auth_required_unit():
    async def scenario():
        import network.handlers.field_magic as fm

        mgr = ConnectionManager()
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await fm.handle(None, None, {"type": "cast", "spell": "heal"}, outbound)
            assert outbound[0].get("reason") == "authenticate first"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_field_magic_defers_when_in_combat_unit():
    """Mid-fight cast must return None so combat path can handle battle spells."""
    async def scenario():
        import network.handlers.field_magic as fm
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            with patch.object(combat_engine, "is_in_combat", return_value=True):
                outbound: list[dict] = []
                result = await fm.handle(
                    1, 1, {"type": "cast", "spell": "hurt"}, outbound
                )
                assert result is None
                assert outbound == []
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_field_magic_unrelated_type_unit():
    async def scenario():
        import network.handlers.field_magic as fm

        outbound: list[dict] = []
        result = await fm.handle(1, 1, {"type": "chat", "text": "hi"}, outbound)
        assert result is None

    asyncio.run(scenario())


def test_field_magic_unknown_spell_unit():
    async def scenario():
        import network.handlers.field_magic as fm
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:

            async def fake_get(cid):
                return {
                    "id": cid,
                    "level": 1,
                    "current_mp": 20,
                    "current_hp": 5,
                    "max_hp": 20,
                }

            with patch.object(combat_engine, "is_in_combat", return_value=False), patch(
                "network.handlers.field_magic.get_character", side_effect=fake_get
            ), patch(
                "network.handlers.field_magic.field_spells_at", return_value=["heal"]
            ):
                outbound: list[dict] = []
                await fm.handle(
                    1, 1, {"type": "cast", "spell": "nope"}, outbound
                )
                assert outbound[0].get("reason") == "unknown or unlearned spell"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_field_magic_full_hp_refuses_heal_unit():
    async def scenario():
        import network.handlers.field_magic as fm
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:

            async def fake_get(cid):
                return {
                    "id": cid,
                    "level": 5,
                    "current_mp": 20,
                    "current_hp": 30,
                    "max_hp": 30,
                }

            with patch.object(combat_engine, "is_in_combat", return_value=False), patch(
                "network.handlers.field_magic.get_character", side_effect=fake_get
            ), patch(
                "network.handlers.field_magic.field_spells_at", return_value=["heal"]
            ), patch(
                "network.handlers.field_magic.get_spell",
                return_value={
                    "name": "Heal",
                    "field": True,
                    "mp_cost": 4,
                    "formula": "heal",
                },
            ):
                outbound: list[dict] = []
                await fm.handle(1, 1, {"type": "heal"}, outbound)
                assert outbound[0].get("reason") == "already at full HP"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_field_magic_clears_afk_and_census_unit():
    async def scenario():
        import network.handlers.field_magic as fm
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        mgr.set_afk(1, True, message="nap")
        old = _bind(mgr)
        try:

            async def fake_get(cid):
                return {
                    "id": cid,
                    "level": 5,
                    "current_mp": 20,
                    "current_hp": 10,
                    "max_hp": 30,
                }

            async def fake_patch(cid, patch):
                return {
                    "id": cid,
                    "level": 5,
                    "current_mp": patch.get("current_mp", 16),
                    "current_hp": patch.get("current_hp", 20),
                    "max_hp": 30,
                }

            with patch.object(combat_engine, "is_in_combat", return_value=False), patch(
                "network.handlers.field_magic.get_character", side_effect=fake_get
            ), patch(
                "network.handlers.field_magic.field_spells_at", return_value=["heal"]
            ), patch(
                "network.handlers.field_magic.battle_spells_at", return_value=[]
            ), patch(
                "network.handlers.field_magic.equipment_bonuses", return_value={}
            ), patch(
                "network.handlers.field_magic.get_spell",
                return_value={
                    "name": "Heal",
                    "field": True,
                    "mp_cost": 4,
                    "formula": "heal",
                },
            ), patch(
                "network.handlers.field_magic.apply_character_patch",
                side_effect=fake_patch,
            ), patch(
                "network.handlers.field_magic.F.heal_amount", return_value=10
            ), patch(
                "network.handlers.field_magic.F.apply_heal",
                return_value=(20, 10),
            ):
                outbound: list[dict] = []
                await fm.handle(
                    1, 1, {"type": "cast", "spell": "heal"}, outbound
                )
                casts = [m for m in outbound if m.get("type") == "spell_cast"]
                assert casts, outbound
                assert mgr.get_meta(1).get("afk") is not True
                assert "online" in casts[0]
                assert "nearby_count" in casts[0]
                assert casts[0].get("healed") == 10
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_return_teleport_aoi_unit():
    async def scenario():
        import network.handlers.field_magic as fm
        from game.combat_engine import combat_engine
        from game.world_manager import SPAWN_X, SPAWN_Y

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=10, y=10, map_id=0)
        old = _bind(mgr)
        try:

            async def fake_get(cid):
                return {
                    "id": cid,
                    "level": 13,
                    "current_mp": 20,
                    "current_hp": 10,
                    "max_hp": 30,
                }

            async def fake_patch(cid, patch):
                return {
                    "id": cid,
                    "level": 13,
                    "current_mp": 12,
                    "current_hp": 10,
                    "max_hp": 30,
                    "world_x": patch.get("world_x", SPAWN_X),
                    "world_y": patch.get("world_y", SPAWN_Y),
                }

            with patch.object(combat_engine, "is_in_combat", return_value=False), patch(
                "network.handlers.field_magic.get_character", side_effect=fake_get
            ), patch(
                "network.handlers.field_magic.field_spells_at", return_value=["return"]
            ), patch(
                "network.handlers.field_magic.battle_spells_at", return_value=[]
            ), patch(
                "network.handlers.field_magic.equipment_bonuses", return_value={}
            ), patch(
                "network.handlers.field_magic.get_spell",
                return_value={
                    "name": "Return",
                    "field": True,
                    "mp_cost": 6,
                    "formula": "return",
                },
            ), patch(
                "network.handlers.field_magic.apply_character_patch",
                side_effect=fake_patch,
            ):
                outbound: list[dict] = []
                await fm.handle(1, 1, {"type": "return"}, outbound)
                moves = [
                    m
                    for m in outbound
                    if m.get("type") == "move_ok" and m.get("reason") == "spell"
                ]
                assert moves, outbound
                assert moves[0].get("x") == SPAWN_X
                assert moves[0].get("y") == SPAWN_Y
                meta = mgr.get_meta(1)
                assert int(meta["x"]) == SPAWN_X
                assert int(meta["y"]) == SPAWN_Y
                casts = [m for m in outbound if m.get("type") == "spell_cast"]
                assert casts and casts[0].get("teleported") is True
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_outside_requires_dungeon_unit():
    async def scenario():
        import network.handlers.field_magic as fm
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)  # town
        old = _bind(mgr)
        try:

            async def fake_get(cid):
                return {
                    "id": cid,
                    "level": 20,
                    "current_mp": 20,
                    "current_hp": 10,
                    "max_hp": 30,
                }

            with patch.object(combat_engine, "is_in_combat", return_value=False), patch(
                "network.handlers.field_magic.get_character", side_effect=fake_get
            ), patch(
                "network.handlers.field_magic.field_spells_at",
                return_value=["outside"],
            ), patch(
                "network.handlers.field_magic.get_spell",
                return_value={
                    "name": "Outside",
                    "field": True,
                    "mp_cost": 6,
                    "formula": "outside",
                },
            ):
                outbound: list[dict] = []
                await fm.handle(1, 1, {"type": "outside"}, outbound)
                assert outbound[0].get("reason") == "only works in dungeon"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_repel_sets_manager_unit():
    async def scenario():
        import network.handlers.field_magic as fm
        from game.combat_engine import combat_engine
        from game.item_manager import REPEL_STEPS

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:

            async def fake_get(cid):
                return {
                    "id": cid,
                    "level": 15,
                    "current_mp": 20,
                    "current_hp": 10,
                    "max_hp": 30,
                }

            async def fake_patch(cid, patch):
                return {
                    "id": cid,
                    "level": 15,
                    "current_mp": patch.get("current_mp", 14),
                    "current_hp": 10,
                    "max_hp": 30,
                }

            with patch.object(combat_engine, "is_in_combat", return_value=False), patch(
                "network.handlers.field_magic.get_character", side_effect=fake_get
            ), patch(
                "network.handlers.field_magic.field_spells_at", return_value=["repel"]
            ), patch(
                "network.handlers.field_magic.battle_spells_at", return_value=[]
            ), patch(
                "network.handlers.field_magic.equipment_bonuses", return_value={}
            ), patch(
                "network.handlers.field_magic.get_spell",
                return_value={
                    "name": "Repel",
                    "field": True,
                    "mp_cost": 4,
                    "formula": "repel",
                },
            ), patch(
                "network.handlers.field_magic.apply_character_patch",
                side_effect=fake_patch,
            ):
                outbound: list[dict] = []
                await fm.handle(1, 1, {"type": "repel"}, outbound)
                casts = [m for m in outbound if m.get("type") == "spell_cast"]
                assert casts, outbound
                assert casts[0].get("repel_steps") == REPEL_STEPS
                meta = mgr.get_meta(1)
                assert int(meta.get("repel_steps") or 0) >= REPEL_STEPS or meta.get(
                    "repel"
                )
        finally:
            _restore(old)

    asyncio.run(scenario())
