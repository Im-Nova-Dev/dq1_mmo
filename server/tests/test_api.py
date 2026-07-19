"""Integration tests against running app (in-process, free port)."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_full_flow(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    from tests.ws_helpers import http_json, start_server, stop_server

    server, port, base, ws_url = start_server()
    try:
        st, health = http_json(base, "GET", "/health")
        assert st == 200 and health["status"] == "ok"

        st, reg = http_json(
            base,
            "POST",
            "/auth/register",
            {"email": "t@ex.com", "password": "password", "username": "Tester"},
        )
        assert st == 201, reg
        token = reg["access_token"]

        st, bad = http_json(
            base, "POST", "/auth/login", {"email": "t@ex.com", "password": "nope"}
        )
        assert st == 401

        st, ch = http_json(
            base, "POST", "/auth/characters", {"name": "HeroT"}, token=token
        )
        assert st == 201
        assert ch["gold"] == str(config.STARTING_GOLD)

        st, chars = http_json(base, "GET", "/auth/characters", token=token)
        assert st == 200 and len(chars) == 1

        async def ws_flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                m1 = json.loads(await asyncio.wait_for(ws.recv(), 3))
                m2 = json.loads(await asyncio.wait_for(ws.recv(), 3))
                assert m1["type"] == "auth_ok"
                assert m2["type"] == "world_state"
                assert "bonuses" in m1["character"]
                assert "repel" in m2 or m2.get("online") is not None

                async def recv_type(*types, timeout=3):
                    while True:
                        m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                        if m.get("type") in types:
                            return m

                await ws.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 1}))
                mok = await recv_type("move_ok")
                assert mok["ok"] is True and mok["seq"] == 1 and mok["x"] == 3

                await ws.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 1}))
                mok2 = await recv_type("move_ok")
                assert mok2.get("duplicate") is True

                await ws.send(json.dumps({"type": "buy", "item": "club"}))
                inv = await recv_type("inventory_update", "error")
                if inv["type"] == "error":
                    inv = await recv_type("inventory_update")
                assert inv["type"] == "inventory_update"
                assert any(i["item_id"] == "club" for i in inv["items"])

                await ws.send(
                    json.dumps({"type": "equip", "slot": "weapon", "item": "club"})
                )
                inv2 = await recv_type("inventory_update", "error")
                if inv2["type"] == "error":
                    inv2 = await recv_type("inventory_update")
                assert inv2["character"]["equipment_weapon"] == "club"
                assert inv2["character"]["bonuses"]["attack_power"] == 8
                assert "field_spells" in inv2["character"]

                await ws.send(json.dumps({"type": "ping", "t": 1.23}))
                pong = await recv_type("pong")
                assert pong.get("t") == 1.23

                await ws.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 11})
                )
                start = await recv_type("combat_start")
                assert start["type"] == "combat_start"
                await recv_type("combat_update")

                for _ in range(15):
                    await ws.send(json.dumps({"type": "attack"}))
                    m = await recv_type("combat_update", "combat_end", "level_up")
                    while m["type"] == "level_up":
                        m = await recv_type("combat_update", "combat_end", "level_up")
                    if m["type"] == "combat_end":
                        assert m["result"] == "victory"
                        assert m["character"]["equipment_weapon"] == "club"
                        return
                    if m.get("outcome") == "victory":
                        m = await recv_type("combat_end")
                        assert m["type"] == "combat_end"
                        return
                raise AssertionError("battle did not end")

        asyncio.run(ws_flow())
    finally:
        stop_server(server)
