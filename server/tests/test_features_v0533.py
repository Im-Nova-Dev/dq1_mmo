"""v0.5.33: sell reports gold_gained; inventory sold payload."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.ws_helpers import register_char, start_server, stop_server


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


def test_sell_includes_gold_gained(tmp_path, monkeypatch):
    db_path = tmp_path / "sold.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "so@ex.com", "SoU", "SoldHero")

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
                gold0 = int(str((inv.get("character") or {}).get("gold") or 0))
                await ws.send(json.dumps({"type": "sell", "item": "herb"}))
                m = await recv_until(ws, "inventory_update", "error")
                assert m.get("type") == "inventory_update", m
                sold = m.get("sold") or {}
                assert int(sold.get("gold_gained") or 0) == 12, sold
                assert sold.get("item_id") == "herb"
                gold1 = int(str((m.get("character") or {}).get("gold") or 0))
                assert gold1 == gold0 + 12
                assert "Sold" in str(m.get("message") or "")

        asyncio.run(flow())
    finally:
        stop_server(server)
