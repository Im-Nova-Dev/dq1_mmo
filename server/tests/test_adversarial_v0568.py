"""v0.5.68 adversarial: bare buy/sell item required; shout=zone; invalid afk filter; sell equipped."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import CHAT_MIN_INTERVAL
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
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.1)
    return m


def test_buy_sell_bare_item_required(tmp_path, monkeypatch):
    db_path = tmp_path / "bare.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "b@ex.com", "Bb", "BareH")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "sell"}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error" and "item" in str(m.get("reason") or "").lower(), m
                await ws.send(json.dumps({"type": "buy"}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error" and "item" in str(m.get("reason") or "").lower(), m
                await ws.send(json.dumps({"type": "sell", "item": ""}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error", m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_shout_is_zone_channel(tmp_path, monkeypatch):
    db_path = tmp_path / "sh.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sa@ex.com", "Sa", "ShA")
        tb, cb = register_char(base, "sb@ex.com", "Sb", "ShB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await asyncio.sleep(CHAT_MIN_INTERVAL + 0.05)
                await drain(wb)
                await wa.send(
                    json.dumps({"type": "chat", "channel": "shout", "text": "hey zone"})
                )
                ma = await recv_until(wa, "chat", "error")
                assert ma.get("type") == "chat" and ma.get("channel") == "zone", ma
                assert ma.get("zone") == "town", ma
                mb = await recv_until(wb, "chat", "error")
                assert mb.get("text") == "hey zone" and mb.get("channel") == "zone", mb

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_find_invalid_afk_filter(tmp_path, monkeypatch):
    db_path = tmp_path / "afkbad.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "f@ex.com", "Ff", "FindBad")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "find", "q": "afk:maybe"}))
                m = await recv_until(ws, "find", "error")
                assert m.get("type") == "error"
                assert "afk" in str(m.get("reason") or "").lower(), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_sell_equipped_clears_slot(tmp_path, monkeypatch):
    db_path = tmp_path / "eqsell.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "e@ex.com", "Ee", "EqSell")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "buy", "item": "club"}))
                await recv_until(ws, "inventory_update", "error")
                await ws.send(
                    json.dumps({"type": "equip", "slot": "weapon", "item": "club"})
                )
                eq = await recv_until(ws, "inventory_update", "error")
                assert (eq.get("character") or {}).get("equipment_weapon") == "club"
                await ws.send(json.dumps({"type": "sell", "item": "club"}))
                sold = await recv_until(ws, "inventory_update", "error")
                assert sold.get("type") == "inventory_update", sold
                assert sold.get("sold") is not None, sold
                assert not (sold.get("character") or {}).get("equipment_weapon"), sold

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_ignore_self_and_unignore_missing(tmp_path, monkeypatch):
    db_path = tmp_path / "ig.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "i@ex.com", "Ii", "IgSelf")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "ignore", "name": "IgSelf"}))
                m = await recv_until(ws, "error", "ignore")
                assert m.get("type") == "error"
                assert "yourself" in str(m.get("reason") or "").lower(), m
                await ws.send(json.dumps({"type": "unignore", "name": "Nobody"}))
                m = await recv_until(ws, "error", "ignore")
                assert m.get("type") == "error", m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_qty_edges_still_reject(tmp_path, monkeypatch):
    """Regression: bad quantities still fail closed."""
    db_path = tmp_path / "qty.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "q@ex.com", "Qq", "QtyH")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                for payload in (
                    {"type": "buy", "item": "herb", "quantity": 0},
                    {"type": "buy", "item": "herb", "quantity": 2.5},
                    {"type": "buy", "item": "herb", "quantity": True},
                ):
                    await ws.send(json.dumps(payload))
                    m = await recv_until(ws, "error", "inventory_update")
                    assert m.get("type") == "error", m
                    assert "quantity" in str(m.get("reason") or "").lower(), m

        asyncio.run(flow())
    finally:
        stop_server(server)
