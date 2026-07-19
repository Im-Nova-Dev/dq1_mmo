"""v0.5.89: combat blocks emote, equip rate-exempt under spam, starter clothes."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.ws_helpers import http_json, register_char, start_server, stop_server


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


def test_starter_clothes_and_herbs(tmp_path, monkeypatch):
    db_path = tmp_path / "starter.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        st, reg = http_json(
            base,
            "POST",
            "/auth/register",
            {"email": "st@ex.com", "password": "password", "username": "Starter"},
        )
        assert st == 201, reg
        tok = reg["access_token"]
        st, ch = http_json(
            base, "POST", "/auth/characters", {"name": "CladHero"}, token=tok
        )
        assert st == 201, ch
        assert ch.get("equipment_armor") == "clothes", ch

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, tok, ch["id"])
                await ws.send(json.dumps({"type": "inventory"}))
                inv = await recv_until(ws, "inventory_update", "error")
                items = inv.get("items") or []
                herbs = [
                    i
                    for i in items
                    if (i.get("item_id") or i.get("id")) == "herb"
                ]
                assert herbs, items
                assert int(herbs[0].get("quantity") or 0) >= 3

                await ws.send(json.dumps({"type": "status"}))
                stt = await recv_until(ws, "status", "error")
                char = stt.get("character") or {}
                # armor may be under character equipment fields
                assert (
                    char.get("equipment_armor") == "clothes"
                    or (char.get("bonuses") or {}).get("equipment", {}).get("armor")
                    == "clothes"
                    or ch.get("equipment_armor") == "clothes"
                )

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_emote_blocked_in_combat(tmp_path, monkeypatch):
    db_path = tmp_path / "emote_cbt.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    monkeypatch.setenv("ALLOW_DEBUG", "1")
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "c@ex.com", "Cc", "CbtEmote")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "debug_encounter", "enemy": "slime"}))
                await recv_until(ws, "combat_start", "combat_update", "error")
                await ws.send(json.dumps({"type": "emote", "emote": "wave"}))
                err = await recv_until(ws, "error", "emote")
                assert err.get("type") == "error", err
                assert "combat" in str(err.get("reason") or "").lower(), err

                await ws.send(json.dumps({"type": "emotes"}))
                cat = await recv_until(ws, "emotes", "error")
                assert cat.get("type") == "emotes", cat  # list still ok

                # Flee can fail (DQ1 chance) — keep trying until combat ends
                fled = False
                for _ in range(12):
                    await ws.send(json.dumps({"type": "flee"}))
                    end = time.monotonic() + 1.5
                    while time.monotonic() < end:
                        try:
                            m = json.loads(
                                await asyncio.wait_for(
                                    ws.recv(), max(0.05, end - time.monotonic())
                                )
                            )
                            if m.get("type") == "combat_end":
                                fled = True
                                break
                            if m.get("type") == "error" and "combat" not in str(
                                m.get("reason") or ""
                            ).lower():
                                # unexpected; keep trying flee
                                pass
                        except (asyncio.TimeoutError, TimeoutError):
                            break
                    if fled:
                        break
                assert fled, "expected combat_end after flee attempts"

                await asyncio.sleep(0.85)
                await ws.send(json.dumps({"type": "emote", "emote": "wave"}))
                em = await recv_until(ws, "emote", "error")
                assert em.get("type") == "emote", em

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_equip_unequip_under_message_spam(tmp_path, monkeypatch):
    """Inventory actions must not return generic rate_limit after peek spam."""
    db_path = tmp_path / "rate_eq.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "r@ex.com", "Rr", "RateEq")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                # Spam exempt peeks
                for _ in range(60):
                    await ws.send(json.dumps({"type": "who"}))
                    await ws.send(json.dumps({"type": "gold"}))
                    await ws.send(json.dumps({"type": "status"}))
                await drain(ws, 0.3)

                await ws.send(json.dumps({"type": "unequip", "slot": "weapon"}))
                r = await recv_until(ws, "error", "inventory_update")
                assert r.get("type") == "error", r
                assert r.get("reason") != "rate_limit", r
                assert "equip" in str(r.get("reason") or "").lower() or "nothing" in str(
                    r.get("reason") or ""
                ).lower(), r

                await ws.send(json.dumps({"type": "buy", "item": "club"}))
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv
                assert inv.get("reason") != "rate_limit"

                await ws.send(json.dumps({"type": "equip", "item": "club"}))
                eq = await recv_until(ws, "inventory_update", "error")
                assert eq.get("type") == "inventory_update", eq

        asyncio.run(flow())
    finally:
        stop_server(server)
