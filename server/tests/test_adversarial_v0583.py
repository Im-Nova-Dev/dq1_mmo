"""v0.5.83 adversarial: item resolve edges + regressions (AFK, shop, qty)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game.item_manager import resolve_item_id
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


def test_resolve_edges_unit():
    assert resolve_item_id(None)[1] == "item required"
    assert resolve_item_id("   ")[1] == "item required"
    assert resolve_item_id("sword")[1] == "name ambiguous"
    assert resolve_item_id("plate")[1] == "name ambiguous"
    assert resolve_item_id("axe")[0] == "hand_axe"
    # Exact id still wins
    assert resolve_item_id("copper_sword")[0] == "copper_sword"
    # Weird punctuation
    assert resolve_item_id("  Copper---Sword  ")[0] == "copper_sword"


def test_bare_item_still_required_and_qty_edges(tmp_path, monkeypatch):
    db_path = tmp_path / "adv_item.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "AdvItem")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])

                await ws.send(json.dumps({"type": "buy"}))
                err = await recv_until(ws, "error")
                assert "item" in str(err.get("reason") or "").lower()

                await ws.send(json.dumps({"type": "buy", "item": "herb", "quantity": 0}))
                err0 = await recv_until(ws, "error", "inventory_update")
                assert err0.get("type") == "error"
                assert "quantity" in str(err0.get("reason") or "").lower() or "bad" in str(
                    err0.get("reason") or ""
                ).lower()

                # AFK reason still works (regression)
                await ws.send(json.dumps({"type": "afk", "text": "shopping"}))
                afk = await recv_until(ws, "afk", "error")
                assert afk.get("afk") is True
                assert afk.get("afk_message") == "shopping"

                # Buy while AFK clears AFK via mark_active
                await ws.send(json.dumps({"type": "buy", "item": "club"}))
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv

                await ws.send(json.dumps({"type": "status"}))
                st = await recv_until(ws, "status", "error")
                you = st.get("you") or {}
                assert you.get("afk") is False, you

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_equip_ambiguous_and_sell_equipped_name(tmp_path, monkeypatch):
    db_path = tmp_path / "adv_eq.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "e@ex.com", "Ee", "EqHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "equip", "item": "sword"}))
                err = await recv_until(ws, "error", "inventory_update")
                assert err.get("type") == "error"
                assert "ambiguous" in str(err.get("reason") or "").lower()

                await ws.send(json.dumps({"type": "buy", "item": "club"}))
                await recv_until(ws, "inventory_update", "error")
                await ws.send(json.dumps({"type": "equip", "item": "club"}))
                await recv_until(ws, "inventory_update", "error")
                # Sell equipped by display-ish id
                await ws.send(json.dumps({"type": "sell", "item": "club"}))
                sold = await recv_until(ws, "inventory_update", "error")
                assert sold.get("type") == "inventory_update", sold
                assert (sold.get("sold") or {}).get("item_id") == "club"

        asyncio.run(flow())
    finally:
        stop_server(server)
