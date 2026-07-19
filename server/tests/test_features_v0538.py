"""v0.5.38: zone-enter system chat, move_ok.zone, who.you fields, new helmets."""

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


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    await recv_until(ws, "auth_ok")
    # Prefer world_state if present
    msgs = await drain(ws, 0.2)
    return msgs


def test_equipment_helmets_in_data():
    from game.data_loader import load_data

    load_data.cache_clear()
    data = load_data()
    eq = data["equipment"]
    assert "leather_helmet" in eq
    assert "iron_helmet" in eq
    assert eq["leather_helmet"]["slot"] == "helmet"
    assert eq["iron_helmet"]["defense"] == 4
    shop = data["shop"]
    assert "leather_helmet" in shop
    assert "iron_helmet" in shop


def test_buy_leather_helmet(tmp_path, monkeypatch):
    db_path = tmp_path / "helm.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())
    from game.data_loader import load_data

    load_data.cache_clear()

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "helm@ex.com", "HelmU", "HelmHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, token, ch["id"])
                await ws.send(json.dumps({"type": "buy", "item": "leather_helmet"}))
                m = await recv_until(ws, "inventory_update", "error")
                assert m.get("type") == "inventory_update", m
                bought = m.get("bought") or {}
                assert bought.get("item_id") == "leather_helmet"
                assert int(bought.get("gold_spent") or 0) == 80
                await ws.send(
                    json.dumps({"type": "equip", "slot": "helmet", "item": "leather_helmet"})
                )
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv
                char = inv.get("character") or {}
                assert char.get("equipment_helmet") in (
                    "leather_helmet",
                    "Leather Helmet",
                ) or "leather" in str(char.get("equipment_helmet") or "").lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_world_state_zone_and_who_you(tmp_path, monkeypatch):
    db_path = tmp_path / "whoz.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "whoz@ex.com", "WhoZU", "WhoZone")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                # Collect world_state
                found_ws = None
                for _ in range(20):
                    m = await recv_until(ws, "world_state", "online", "player_joined")
                    if m.get("type") == "world_state":
                        found_ws = m
                        break
                assert found_ws is not None
                assert found_ws.get("zone") == "town" or (
                    found_ws.get("you") or {}
                ).get("zone") == "town"

                await ws.send(json.dumps({"type": "who"}))
                who = await recv_until(ws, "who")
                you = who.get("you") or {}
                assert you.get("name") == "WhoZone"
                assert you.get("level") is not None
                assert "idle" in you
                assert you.get("zone") == "town"
                assert you.get("x") is not None and you.get("y") is not None

                await ws.send(json.dumps({"type": "status"}))
                st = await recv_until(ws, "status")
                you2 = st.get("you") or {}
                assert you2.get("zone") == "town"
                assert you2.get("x") is not None
                assert you2.get("y") is not None

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_move_ok_includes_zone_unit():
    """move_ok payload includes zone for town spawn step (unit via manager)."""
    from game.world_manager import zone_at, SPAWN_X, SPAWN_Y

    assert zone_at(SPAWN_X, SPAWN_Y) == "town"
    # Field tile on the classic exit path (5, 3)
    assert zone_at(5, 3) == "field"
    # Dungeon tile
    assert zone_at(16, 2) == "dungeon"


def test_move_ok_zone_and_enter_system_chat(tmp_path, monkeypatch):
    """Walk town → field; move_ok carries zone; system chat on enter."""
    db_path = tmp_path / "zenter.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    # Disable random encounters so pathing is deterministic
    monkeypatch.setenv("ALLOW_DEBUG", "0")
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "zent@ex.com", "ZentU", "ZoneWalker")

        async def flow():
            import websockets
            import network.message_handler as mh

            # Patch the name used by the move handler (not the source module)
            orig = mh.roll_encounter
            mh.roll_encounter = lambda *a, **k: None  # type: ignore

            try:
                async with websockets.connect(ws_url) as ws:
                    await auth(ws, token, ch["id"])
                    # Path from spawn (2,2): south to (2,3), east along y=3 to field at (5,3)
                    path = [
                        (2, 3),
                        (3, 3),
                        (4, 3),
                        (5, 3),  # field
                    ]
                    seq = 0
                    saw_field_zone = False
                    saw_enter = False
                    for x, y in path:
                        seq += 1
                        await asyncio.sleep(0.08)  # stay under move rate limit
                        await ws.send(
                            json.dumps({"type": "move", "x": x, "y": y, "seq": seq})
                        )
                        deadline = time.monotonic() + 4.0
                        got_ok = False
                        while time.monotonic() < deadline:
                            try:
                                raw = await asyncio.wait_for(ws.recv(), 0.5)
                            except (asyncio.TimeoutError, TimeoutError):
                                continue
                            m = json.loads(raw)
                            if m.get("type") == "move_ok" and m.get("seq") == seq:
                                got_ok = True
                                if m.get("ok") is False:
                                    # retry later path if blocked
                                    break
                                assert "zone" in m, m
                                if m.get("zone") == "field":
                                    saw_field_zone = True
                            if (
                                m.get("type") == "chat"
                                and m.get("channel") == "system"
                                and "entered the field"
                                in str(m.get("text") or "").lower()
                            ):
                                saw_enter = True
                            if saw_field_zone and saw_enter:
                                break
                        if not got_ok:
                            # drain and keep going
                            await drain(ws, 0.05)
                    assert saw_field_zone, "never saw move_ok zone=field"
                    assert saw_enter, "never saw system chat for zone enter"
            finally:
                mh.roll_encounter = orig

        asyncio.run(flow())
    finally:
        stop_server(server)
