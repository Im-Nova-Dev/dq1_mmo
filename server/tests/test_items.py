"""Consumable use, shop herbs, repel."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiosqlite

from database.migrations import run_migrations
from game.combat_engine import Battle
from game.item_manager import REPEL_STEPS, add_item, shop_catalog, use_consumable
from game.rng import Rng
from network.websocket_manager import ConnectionManager


def _run(coro):
    return asyncio.run(coro)


async def _db():
    path = Path(tempfile.mkdtemp()) / "items.db"
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await run_migrations(db)
    await db.execute(
        "INSERT INTO users (email, password_hash, username) VALUES ('a@b.c', 'x', 'U')"
    )
    await db.execute(
        """
        INSERT INTO characters (user_id, name, max_hp, current_hp, gold, world_x, world_y)
        VALUES (1, 'Hero', 40, 10, '100', 8, 5)
        """
    )
    await db.commit()
    async with db.execute("SELECT * FROM characters WHERE id = 1") as c:
        row = await c.fetchone()
    char = dict(row)
    return db, char


def test_shop_has_consumables():
    ids = {i["id"] for i in shop_catalog()}
    assert "herb" in ids
    assert "fairy_water" in ids
    assert "wing" in ids


def test_use_herb_heals():
    async def scenario():
        db, char = await _db()
        await add_item(db, 1, "herb", 2)
        await db.commit()
        ok, reason, info = await use_consumable(db, char, "herb", rng=Rng(1))
        assert ok, reason
        assert info["effect"] == "heal"
        assert info["healed"] >= 0
        assert char["current_hp"] > 10 or info["healed"] == 0
        assert char["current_hp"] <= 40
        await db.close()

    _run(scenario())


def test_use_wing_returns_to_town():
    async def scenario():
        db, char = await _db()
        await add_item(db, 1, "wing", 1)
        await db.commit()
        ok, reason, info = await use_consumable(db, char, "wing", rng=Rng(1))
        assert ok, reason
        assert info.get("teleported")
        assert char["world_x"] == 2 and char["world_y"] == 2
        await db.close()

    _run(scenario())


def test_use_fairy_water_repel():
    async def scenario():
        db, char = await _db()
        await add_item(db, 1, "fairy_water", 1)
        await db.commit()
        ok, reason, info = await use_consumable(db, char, "fairy_water", rng=Rng(1))
        assert ok, reason
        assert info.get("repel_steps") == REPEL_STEPS
        await db.close()

    _run(scenario())


def test_wing_blocked_in_combat():
    async def scenario():
        db, char = await _db()
        await add_item(db, 1, "wing", 1)
        await db.commit()
        ok, reason, _ = await use_consumable(db, char, "wing", in_combat=True, rng=Rng(1))
        assert ok is False
        assert "combat" in reason
        await db.close()

    _run(scenario())


def test_combat_item_heal_action():
    b = Battle(
        {
            "name": "H",
            "level": 3,
            "strength": 10,
            "agility": 10,
            "max_hp": 40,
            "max_mp": 0,
            "current_hp": 5,
            "current_mp": 0,
            "experience": 10,
            "gold": "0",
        },
        "slime",
        seed=2,
    )
    before = b.hero["hp"]
    r = b.act({"type": "item", "id": "herb", "name": "Herb", "effect": "heal", "amount": 25})
    assert r["ok"]
    assert b.hero["hp"] >= before


def test_equip_consumable_rejected():
    async def scenario():
        db, char = await _db()
        await add_item(db, 1, "herb", 1)
        await db.commit()
        from game.item_manager import equip_item

        ok, reason = await equip_item(db, char, "weapon", "herb")
        assert ok is False
        assert reason == "use item instead"
        await db.close()

    _run(scenario())


def test_buy_not_enough_gold():
    async def scenario():
        db, char = await _db()
        char["gold"] = "0"
        from game.item_manager import buy_item

        ok, reason = await buy_item(db, char, "club")
        assert ok is False
        assert reason == "not enough gold"
        await db.close()

    _run(scenario())


def test_repel_consume_on_manager():
    mgr = ConnectionManager()

    async def scenario():
        class WS:
            async def send_text(self, t):
                pass

            async def close(self, *a, **k):
                pass

        await mgr.connect(1, WS(), name="A", x=2, y=2, map_id=1)
        assert mgr.consume_repel_step(1) is False
        mgr.set_repel(1, 2)
        assert mgr.consume_repel_step(1) is True
        assert mgr.repel_remaining(1) == 1
        assert mgr.consume_repel_step(1) is True
        assert mgr.consume_repel_step(1) is False

    _run(scenario())
