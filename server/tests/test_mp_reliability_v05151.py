"""v0.5.151: combat extract · turn gate · AFK clear · field spell block · census."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import combat
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
    import network.handlers.combat as cb
    import network.handlers._common as common

    old = (wm.manager, cb.manager, common.manager)
    wm.manager = mgr
    cb.manager = mgr
    common.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers.combat as cb
    import network.handlers._common as common

    wm.manager, cb.manager, common.manager = old


def test_combat_module_extracted_unit():
    assert "attack" in combat.ATTACK_TYPES or "attack" in combat.ALL_TYPES
    assert "flee" in combat.ALL_TYPES
    assert "cast" in combat.SPELL_TYPES


def test_combat_auth_required_unit():
    async def scenario():
        import network.handlers.combat as cb
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        old = _bind(mgr)
        try:
            with patch.object(combat_engine, "is_in_combat", return_value=True):
                outbound: list[dict] = []
                await cb.handle(None, None, {"type": "attack"}, outbound)
                assert outbound[0].get("reason") == "authenticate first"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_combat_not_in_combat_unit():
    async def scenario():
        import network.handlers.combat as cb
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            with patch.object(combat_engine, "is_in_combat", return_value=False), patch.object(
                combat_engine, "get", return_value=None
            ):
                outbound: list[dict] = []
                await cb.handle(1, 1, {"type": "attack"}, outbound)
                assert outbound[0].get("reason") == "not in combat"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_cast_outside_combat_defers_unit():
    """Field cast must not be claimed by combat when not fighting."""
    async def scenario():
        import network.handlers.combat as cb
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        old = _bind(mgr)
        try:
            with patch.object(combat_engine, "is_in_combat", return_value=False):
                outbound: list[dict] = []
                result = await cb.handle(
                    1, 1, {"type": "cast", "spell": "heal"}, outbound
                )
                assert result is None
                assert outbound == []
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_combat_wait_turn_unit():
    async def scenario():
        import network.handlers.combat as cb
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            battle = MagicMock()
            battle.phase = "enemy"
            battle.outcome = "ongoing"
            battle.hero = {"hp": 10, "mp": 5}

            with patch.object(combat_engine, "is_in_combat", return_value=True), patch.object(
                combat_engine, "get", return_value=battle
            ), patch(
                "network.handlers.combat._combat_update",
                return_value={"type": "combat_update"},
            ):
                outbound: list[dict] = []
                await cb.handle(1, 1, {"type": "attack"}, outbound)
                assert outbound[0].get("reason") == "wait for your turn"
                assert any(m.get("type") == "combat_update" for m in outbound)
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_field_spell_blocked_in_combat_unit():
    async def scenario():
        import network.handlers.combat as cb
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            battle = MagicMock()
            battle.phase = "awaiting_hero"
            battle.outcome = "ongoing"

            with patch.object(combat_engine, "is_in_combat", return_value=True), patch.object(
                combat_engine, "get", return_value=battle
            ), patch(
                "network.handlers.combat.get_spell",
                return_value={"field": True, "battle": False, "name": "Return"},
            ):
                outbound: list[dict] = []
                await cb.handle(
                    1, 1, {"type": "cast", "spell": "return"}, outbound
                )
                assert outbound[0].get("reason") == "in combat"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_attack_clears_afk_and_census_unit():
    async def scenario():
        import network.handlers.combat as cb
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        mgr.set_afk(1, True, message="snack")
        old = _bind(mgr)
        try:
            battle = MagicMock()
            battle.phase = "awaiting_hero"
            battle.outcome = "ongoing"
            battle.hero = {"hp": 10, "mp": 5}
            battle.act = MagicMock(
                return_value={"ok": True, "events": [{"kind": "hit", "dmg": 1}]}
            )

            with patch.object(combat_engine, "is_in_combat", return_value=True), patch.object(
                combat_engine, "get", return_value=battle
            ), patch(
                "network.handlers.combat._combat_update",
                return_value={"type": "combat_update", "events": []},
            ):
                outbound: list[dict] = []
                await cb.handle(1, 1, {"type": "attack"}, outbound)
                updates = [m for m in outbound if m.get("type") == "combat_update"]
                assert updates, outbound
                assert "online" in updates[0]
                assert mgr.get_meta(1).get("afk") is not True
                battle.act.assert_called_once()
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_flee_action_alias_unit():
    async def scenario():
        import network.handlers.combat as cb
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            battle = MagicMock()
            battle.phase = "awaiting_hero"
            battle.outcome = "ongoing"
            battle.act = MagicMock(return_value={"ok": True, "events": []})

            with patch.object(combat_engine, "is_in_combat", return_value=True), patch.object(
                combat_engine, "get", return_value=battle
            ), patch(
                "network.handlers.combat._combat_update",
                return_value={"type": "combat_update"},
            ):
                outbound: list[dict] = []
                await cb.handle(
                    1, 1, {"type": "combat_action", "action": "flee"}, outbound
                )
                battle.act.assert_called_once_with({"type": "flee"})
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_combat_end_victory_census_unit():
    async def scenario():
        import network.handlers.combat as cb
        from game.combat_engine import combat_engine

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            battle = MagicMock()
            battle.phase = "awaiting_hero"
            battle.outcome = "ongoing"
            battle.rewards = {"xp": 5, "gold": 3}
            battle.act = MagicMock(return_value={"ok": True, "events": []})

            def _end_side(cid):
                battle.outcome = "victory"

            def _act(action):
                battle.outcome = "victory"
                return {"ok": True, "events": [{"kind": "enemy_down"}]}

            battle.act = MagicMock(side_effect=_act)

            async def fake_persist(cid, b):
                return {"id": cid, "level": 2, "name": "Hero"}

            with patch.object(combat_engine, "is_in_combat", return_value=True), patch.object(
                combat_engine, "get", return_value=battle
            ), patch.object(combat_engine, "end"), patch(
                "network.handlers.combat._combat_update",
                return_value={"type": "combat_update"},
            ), patch(
                "network.handlers.combat._persist_battle_end", side_effect=fake_persist
            ), patch(
                "network.handlers.combat._announce_combat_outcome",
                return_value=None,
            ) as ann:
                # make announce async-compatible
                async def fake_ann(cid, outcome):
                    return None

                ann.side_effect = fake_ann
                outbound: list[dict] = []
                await cb.handle(1, 1, {"type": "attack"}, outbound)
                ends = [m for m in outbound if m.get("type") == "combat_end"]
                assert ends, outbound
                assert ends[0].get("result") == "victory"
                assert "online" in ends[0]
                assert mgr.get_meta(1).get("in_combat") is not True
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_unrelated_type_unit():
    async def scenario():
        import network.handlers.combat as cb

        outbound: list[dict] = []
        result = await cb.handle(1, 1, {"type": "chat", "text": "hi"}, outbound)
        assert result is None

    asyncio.run(scenario())
