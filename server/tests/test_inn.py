"""Town inn rest feature."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiosqlite

from database.migrations import run_migrations
from game.player_manager import inn_cost, rest_at_inn


def _run(coro):
    return asyncio.run(coro)


async def _char(hp=5, mp=0, max_hp=40, max_mp=10, gold="100", level=3):
    path = Path(tempfile.mkdtemp()) / "inn.db"
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await run_migrations(db)
    await db.execute(
        "INSERT INTO users (email, password_hash, username) VALUES ('i@b.c', 'x', 'InnU')"
    )
    await db.execute(
        """
        INSERT INTO characters
        (user_id, name, level, max_hp, max_mp, current_hp, current_mp, gold, world_x, world_y)
        VALUES (1, 'Resty', ?, ?, ?, ?, ?, ?, 2, 2)
        """,
        (level, max_hp, max_mp, hp, mp, gold),
    )
    await db.commit()
    async with db.execute("SELECT * FROM characters WHERE id = 1") as c:
        row = await c.fetchone()
    return db, dict(row)


def test_inn_cost_zero_when_full():
    c = {"level": 5, "max_hp": 50, "current_hp": 50, "max_mp": 20, "current_mp": 20}
    assert inn_cost(c) == 0


def test_inn_cost_scales():
    c = {"level": 5, "max_hp": 50, "current_hp": 10, "max_mp": 20, "current_mp": 0}
    assert inn_cost(c) == 20


def test_rest_heals_and_charges():
    async def scenario():
        db, char = await _char(hp=5, mp=0, max_hp=40, max_mp=10, gold="100", level=3)
        ok, reason, info = await rest_at_inn(db, char)
        assert ok, reason
        assert char["current_hp"] == 40
        assert char["current_mp"] == 10
        assert int(char["gold"]) == 100 - info["cost"]
        assert info["cost"] == 12
        # already full
        ok2, reason2, _ = await rest_at_inn(db, char)
        assert ok2 is False
        assert reason2 == "already rested"
        await db.close()

    _run(scenario())


def test_rest_not_enough_gold():
    async def scenario():
        db, char = await _char(hp=1, gold="1", level=10)
        ok, reason, info = await rest_at_inn(db, char)
        assert ok is False
        assert reason == "not enough gold"
        assert info["cost"] == 40
        await db.close()

    _run(scenario())


def test_rest_rejects_outside_town_handler_logic():
    """Zone gate is in message_handler; document expected reason string."""
    from game.world_manager import zone_at

    assert zone_at(5, 3) == "field"
    assert zone_at(2, 2) == "town"
