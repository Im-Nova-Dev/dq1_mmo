"""v0.5.83: friendly item name resolve for buy/sell/use/equip/discard."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game.item_manager import normalize_item_key, resolve_item_id
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
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
        except (asyncio.TimeoutError, TimeoutError):
            break


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.1)
    return m


def test_resolve_item_id_unit():
    assert normalize_item_key("Copper Sword") == "copper_sword"
    assert normalize_item_key("dragon's scale") == "dragons_scale"

    assert resolve_item_id("herb") == ("herb", None)
    assert resolve_item_id("herbs") == ("herb", None)
    assert resolve_item_id("Copper Sword") == ("copper_sword", None)
    assert resolve_item_id("copper sword") == ("copper_sword", None)
    assert resolve_item_id("copper") == ("copper_sword", None)
    assert resolve_item_id("dragon scale") == ("dragons_scale", None)
    assert resolve_item_id("wings") == ("wing", None)
    assert resolve_item_id("fairy water") == ("fairy_water", None)
    assert resolve_item_id("leather helmet") == ("leather_helmet", None)

    # Ambiguous token
    rid, err = resolve_item_id("sword")
    assert rid is None and err == "name ambiguous"

    rid, err = resolve_item_id("no_such_item_xyz")
    assert rid is None and err == "unknown item"

    rid, err = resolve_item_id("")
    assert rid is None and err == "item required"


def test_buy_by_display_name_and_alias(tmp_path, monkeypatch):
    db_path = tmp_path / "item_names.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "n@ex.com", "Nn", "NameShop")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])

                # Display name with space
                await ws.send(
                    json.dumps({"type": "buy", "item": "copper sword", "quantity": 1})
                )
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv
                bought = inv.get("bought") or {}
                assert bought.get("item_id") == "copper_sword", bought

                # Alias + qty
                await ws.send(json.dumps({"type": "buy", "item": "herbs", "quantity": 2}))
                inv2 = await recv_until(ws, "inventory_update", "error")
                assert inv2.get("type") == "inventory_update", inv2
                b2 = inv2.get("bought") or {}
                assert b2.get("item_id") == "herb", b2
                assert int(b2.get("quantity") or 0) == 2

                # Dragon's Scale via friendly name
                await ws.send(
                    json.dumps({"type": "buy", "item": "dragon's scale"})
                )
                inv3 = await recv_until(ws, "inventory_update", "error")
                assert inv3.get("type") == "inventory_update", inv3
                assert (inv3.get("bought") or {}).get("item_id") == "dragons_scale"

                # Equip by display name (auto-slot)
                await ws.send(
                    json.dumps({"type": "equip", "item": "Copper Sword"})
                )
                eq = await recv_until(ws, "inventory_update", "error")
                assert eq.get("type") == "inventory_update", eq
                assert (eq.get("equipped") or {}).get("item_id") == "copper_sword" or (
                    eq.get("equipped") or {}
                ).get("slot") == "weapon", eq

                # Ambiguous
                await ws.send(json.dumps({"type": "buy", "item": "sword"}))
                err = await recv_until(ws, "error", "inventory_update")
                assert err.get("type") == "error", err
                assert "ambiguous" in str(err.get("reason") or "").lower()

                # Unknown
                await ws.send(json.dumps({"type": "buy", "item": "banana_peel"}))
                err2 = await recv_until(ws, "error", "inventory_update")
                assert err2.get("type") == "error"
                assert "unknown" in str(err2.get("reason") or "").lower()

                # Sell by alias still works (starter herbs remain)
                await ws.send(json.dumps({"type": "sell", "item": "herbs", "quantity": 1}))
                sold = await recv_until(ws, "inventory_update", "error")
                assert sold.get("type") == "inventory_update", sold
                assert (sold.get("sold") or {}).get("item_id") == "herb"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_use_and_discard_resolve(tmp_path, monkeypatch):
    db_path = tmp_path / "use_disc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "u@ex.com", "Uu", "UseHero")

        async def flow():
            import websockets
            from database.db import db_write
            from game.item_manager import add_item

            # Wound hero so herb use succeeds
            async with db_write() as db:
                await db.execute(
                    "UPDATE characters SET current_hp = 5, max_hp = 20 WHERE id = ?",
                    (ca["id"],),
                )
                await db.commit()

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await drain(ws, 0.15)

                await ws.send(json.dumps({"type": "use", "item": "herbs"}))
                # may get item_used then inventory_update
                m = await recv_until(ws, "item_used", "inventory_update", "error")
                if m.get("type") == "error":
                    assert "full" in str(m.get("reason") or "").lower() or "hp" in str(
                        m.get("reason") or ""
                    ).lower(), m
                await drain(ws, 0.15)

                await ws.send(json.dumps({"type": "buy", "item": "fairy water"}))
                bought = await recv_until(ws, "inventory_update", "error")
                assert bought.get("type") == "inventory_update", bought
                assert (bought.get("bought") or {}).get("item_id") == "fairy_water", bought
                await drain(ws, 0.1)

                await ws.send(json.dumps({"type": "discard", "item": "fairy water"}))
                disc = await recv_until(ws, "inventory_update", "error")
                assert disc.get("type") == "inventory_update", disc
                dinfo = disc.get("discarded") or {}
                assert dinfo.get("item_id") == "fairy_water", disc

        asyncio.run(flow())
    finally:
        stop_server(server)
