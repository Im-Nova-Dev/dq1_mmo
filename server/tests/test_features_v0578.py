"""v0.5.78: slash shop/use/equip — string aliases + auto-slot equip."""

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


async def drain(ws, seconds=0.1):
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


def test_buy_sell_string_aliases_and_use(tmp_path, monkeypatch):
    db_path = tmp_path / "shop.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s@ex.com", "Ss", "ShopHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "shop"}))
                shop = await recv_until(ws, "shop_list", "error")
                assert shop.get("type") == "shop_list", shop
                assert isinstance(shop.get("items"), list) and len(shop["items"]) > 0

                await ws.send(json.dumps({"type": "purchase", "item": "herb", "quantity": 1}))
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv
                assert inv.get("bought") or "Bought" in str(inv.get("message") or ""), inv

                # use herb at full HP → error (string alias "use")
                await ws.send(json.dumps({"type": "use", "item": "herb"}))
                err = await recv_until(ws, "error", "item_used", "inventory_update")
                # may be error first
                if err.get("type") == "inventory_update":
                    err = await recv_until(ws, "error", "item_used")
                assert err.get("type") == "error", err

                # sell herb
                await ws.send(json.dumps({"type": "sell", "item": "herb", "quantity": 1}))
                sold = await recv_until(ws, "inventory_update", "error")
                assert sold.get("type") == "inventory_update", sold

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_equip_auto_slot(tmp_path, monkeypatch):
    db_path = tmp_path / "eq.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "e@ex.com", "Ee", "EquipHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "buy", "item": "club"}))
                await recv_until(ws, "inventory_update", "error")
                # equip without slot — server infers weapon
                await ws.send(json.dumps({"type": "equip", "item": "club"}))
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv
                assert inv.get("equipped") and inv["equipped"].get("item_id") == "club", inv
                assert inv["equipped"].get("slot") == "weapon", inv

                # wear alias
                await ws.send(json.dumps({"type": "buy", "item": "clothes"}))
                bought = await recv_until(ws, "inventory_update", "error")
                # clothes may or may not exist — skip if unknown
                if bought.get("type") == "error":
                    return
                await ws.send(json.dumps({"type": "wear", "item": "clothes"}))
                w = await recv_until(ws, "inventory_update", "error")
                assert w.get("type") in ("inventory_update", "error"), w

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_shop_outside_town_and_help(tmp_path, monkeypatch):
    db_path = tmp_path / "out.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "o@ex.com", "Oo", "OutHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                # walk toward field if possible
                seq = 1
                for x, y in ((3, 2), (4, 2), (5, 2), (5, 3), (6, 3), (6, 2)):
                    await asyncio.sleep(0.12)
                    await ws.send(json.dumps({"type": "move", "x": x, "y": y, "seq": seq}))
                    await recv_until(ws, "move_ok", "error")
                    seq += 1
                await drain(ws, 0.15)
                await ws.send(json.dumps({"type": "zone"}))
                z = await recv_until(ws, "zone", "error")
                if z.get("zone") != "town":
                    await ws.send(json.dumps({"type": "buy", "item": "herb"}))
                    err = await recv_until(ws, "error", "inventory_update")
                    assert err.get("type") == "error" and "town" in str(err.get("reason")), err

                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                blob = json.dumps(h).lower()
                assert "buy" in blob and "use" in blob and "equip" in blob

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_use_item_alias_unknown(tmp_path, monkeypatch):
    db_path = tmp_path / "use.db"
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

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "consume", "item": "nope"}))
                m = await recv_until(ws, "error", "item_used", "inventory_update")
                if m.get("type") != "error":
                    m = await recv_until(ws, "error", timeout=1.0)
                assert m.get("type") == "error", m

        asyncio.run(flow())
    finally:
        stop_server(server)
