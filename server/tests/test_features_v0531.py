"""v0.5.31: bag sell_price, finite-pos zone_counts repair."""

from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager
from tests.ws_helpers import register_char, start_server, stop_server


class FakeWS:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def close(self, *a, **k):
        self.closed = True

    async def send_text(self, t):
        self.sent.append(json.loads(t))


async def recv_until(ws, *types, timeout=4.0):
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


def test_inventory_includes_sell_price(tmp_path, monkeypatch):
    db_path = tmp_path / "sell.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "sp@ex.com", "SpU", "SellHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await drain(ws, 0.1)
                await ws.send(json.dumps({"type": "inventory"}))
                inv = await recv_until(ws, "inventory_update")
                items = inv.get("items") or []
                assert items, "expected starter herbs"
                herb = next(
                    (i for i in items if (i.get("item_id") or i.get("id")) == "herb"),
                    items[0],
                )
                assert "sell_price" in herb, herb
                # herb price 24 → sell 12
                assert int(herb["sell_price"]) == 12, herb
                d = herb.get("def") or {}
                assert int(d.get("sell_price") or 0) == 12

                await ws.send(json.dumps({"type": "shop"}))
                shop = await recv_until(ws, "shop_list")
                catalog = shop.get("items") or []
                assert catalog
                assert "sell_price" in catalog[0]
                assert int(catalog[0]["sell_price"]) == max(
                    1, int(catalog[0]["price"]) // 2
                )

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_zone_counts_repairs_nan_meta():
    mgr = ConnectionManager()

    async def scenario():
        await mgr.connect(1, FakeWS(), name="A", x=2, y=2, map_id=0)
        meta = mgr.get_meta(1)
        meta["x"] = float("nan")
        meta["y"] = float("nan")
        zc = mgr.zone_counts()
        # after repair, player should count as town (spawn)
        assert math.isfinite(float(mgr.get_meta(1)["x"]))
        assert math.isfinite(float(mgr.get_meta(1)["y"]))
        assert zc["town"] >= 1, zc
        # nearby should also not crash
        near = mgr.ids_nearby(1)
        assert isinstance(near, list)

    asyncio.run(scenario())
