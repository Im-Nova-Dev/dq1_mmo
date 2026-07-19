"""v0.5.47: expanded reserved names; inventory bag capacity fields."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.ws_helpers import register_char, start_server, stop_server


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


def test_reserved_names_god_null_npc():
    from models.player import CharacterCreate
    from pydantic import ValidationError

    for bad in ("God", "GOD", "null", "NPC", "staff", "Dragonlord"):
        try:
            CharacterCreate(name=bad)
            raise AssertionError(f"should reject {bad!r}")
        except ValidationError:
            pass
    # Still allow normal fantasy names
    ok = CharacterCreate(name="Hero")
    assert ok.name == "Hero"


def test_inventory_includes_bag_caps(tmp_path, monkeypatch):
    db_path = tmp_path / "bagmeta.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())
    from game.item_manager import MAX_BAG_SLOTS, MAX_STACK_QTY

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "bg@ex.com", "BgU", "BagMeta")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": t, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await drain(ws, 0.12)
                await ws.send(json.dumps({"type": "inventory"}))
                inv = await recv_until(ws, "inventory_update")
                bag = inv.get("bag") or {}
                assert int(bag.get("max_slots") or 0) == MAX_BAG_SLOTS, bag
                assert int(bag.get("max_stack") or 0) == MAX_STACK_QTY, bag
                assert int(bag.get("used") or 0) >= 1, bag  # starter herbs
                assert int(bag.get("used") or 0) <= MAX_BAG_SLOTS

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_empty_chat_does_not_burn_rate(tmp_path, monkeypatch):
    """Whitespace-only chat rejects without consuming chat rate."""
    db_path = tmp_path / "empty.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        t, ch = register_char(base, "em@ex.com", "EmU", "EmptyChat")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": t, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await drain(ws, 0.12)
                await ws.send(json.dumps({"type": "chat", "text": "  \t  "}))
                err = await recv_until(ws, "error")
                assert err.get("type") == "error", err
                # Immediate global must work (empty did not burn rate)
                await ws.send(
                    json.dumps(
                        {"type": "chat", "channel": "global", "text": "real"}
                    )
                )
                m = await recv_until(ws, "chat", "error")
                assert m.get("type") == "chat" and m.get("text") == "real", m

        asyncio.run(flow())
    finally:
        stop_server(server)
