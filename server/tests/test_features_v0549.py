"""v0.5.49: discard bag items; free slot when full."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiosqlite

from database.migrations import run_migrations
from game.item_manager import (
    MAX_BAG_SLOTS,
    add_item,
    can_receive_item,
    discard_item,
)
from game.data_loader import load_data
from tests.ws_helpers import register_char, start_server, stop_server


def _run(coro):
    return asyncio.run(coro)


async def _db():
    path = Path(tempfile.mkdtemp()) / "disc.db"
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await run_migrations(db)
    await db.execute(
        "INSERT INTO users (email, password_hash, username) VALUES ('a@b.c', 'x', 'U')"
    )
    await db.execute(
        """
        INSERT INTO characters (user_id, name, max_hp, current_hp, gold, world_x, world_y)
        VALUES (1, 'Hero', 40, 40, '100', 2, 2)
        """
    )
    await db.commit()
    async with db.execute("SELECT * FROM characters WHERE id = 1") as c:
        row = await c.fetchone()
    return db, dict(row)


def test_discard_unit():
    async def flow():
        db, char = await _db()
        assert await add_item(db, 1, "herb", 3)
        await db.commit()
        ok, reason, info = await discard_item(db, char, "herb", 1)
        assert ok, reason
        assert info.get("quantity") == 1
        ok2, reason2, _ = await discard_item(db, char, "herb", 99)
        assert not ok2 and reason2 == "not in inventory"
        # discard rest
        await discard_item(db, char, "herb", 2)
        ok3, r3, _ = await discard_item(db, char, "herb", 1)
        assert not ok3
        await db.close()

    _run(flow())


def test_discard_frees_bag_slot():
    async def flow():
        load_data.cache_clear()
        db, char = await _db()
        eq = list((load_data().get("equipment") or {}).keys())
        assert len(eq) > MAX_BAG_SLOTS
        for iid in eq[:MAX_BAG_SLOTS]:
            assert await add_item(db, 1, iid, 1)
        await db.commit()
        extra = eq[MAX_BAG_SLOTS]
        ok, reason = await can_receive_item(db, 1, extra, 1)
        assert not ok and reason == "inventory full"
        # discard first stack
        okd, rd, _ = await discard_item(db, char, eq[0], 1)
        assert okd, rd
        ok2, reason2 = await can_receive_item(db, 1, extra, 1)
        assert ok2, reason2
        await db.close()

    _run(flow())


async def recv_until(ws, *types, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(types)
        raw = await asyncio.wait_for(ws.recv(), remaining)
        m = json.loads(raw)
        if m.get("type") in types:
            return m


async def drain(ws, seconds=0.12):
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
            out.append(json.loads(raw))
        except (asyncio.TimeoutError, TimeoutError):
            break
    return out


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    await recv_until(ws, "auth_ok")
    await drain(ws, 0.12)


def test_discard_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "discws.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())
    load_data.cache_clear()

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "d@ex.com", "Du", "DiscHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                await ws.send(json.dumps({"type": "inventory"}))
                inv0 = await recv_until(ws, "inventory_update")
                used0 = int((inv0.get("bag") or {}).get("used") or 0)
                # starter has herbs
                await ws.send(json.dumps({"type": "discard", "item": "herb", "quantity": 1}))
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv
                assert inv.get("discarded"), inv
                assert "Discarded" in str(inv.get("message") or ""), inv
                used1 = int((inv.get("bag") or {}).get("used") or 0)
                # used may stay same if herbs remain (qty>1) or drop if last
                assert used1 <= used0
                # discard missing
                await ws.send(json.dumps({"type": "discard", "item": "nope"}))
                err = await recv_until(ws, "error", "inventory_update")
                assert err.get("type") == "error", err

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_discard_blocked_in_combat(tmp_path, monkeypatch):
    db_path = tmp_path / "discc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "dc@ex.com", "DcU", "DiscCombat")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, ch["id"])
                await ws.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime"})
                )
                await recv_until(ws, "combat_start", "error")
                await ws.send(json.dumps({"type": "discard", "item": "herb"}))
                err = await recv_until(ws, "error", "inventory_update")
                assert err.get("type") == "error", err
                assert err.get("reason") == "in combat", err

        asyncio.run(flow())
    finally:
        stop_server(server)
