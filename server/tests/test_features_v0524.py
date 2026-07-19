"""v0.5.24: help command, pong server_t, defeat gold_lost."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.ws_helpers import register_char, start_server, stop_server


async def recv_until(ws, *types, timeout=4.0):
    deadline = time.monotonic() + timeout
    while True:
        rem = deadline - time.monotonic()
        if rem <= 0:
            raise TimeoutError(types)
        m = json.loads(await asyncio.wait_for(ws.recv(), rem))
        if m.get("type") in types:
            return m


def test_help_and_pong_server_t(tmp_path, monkeypatch):
    db_path = tmp_path / "help.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "hp@ex.com", "HpU", "HelpHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")

                await ws.send(json.dumps({"type": "help"}))
                m = await recv_until(ws, "help", "error")
                assert m["type"] == "help", m
                assert isinstance(m.get("commands"), list) and len(m["commands"]) >= 5
                assert m.get("version")
                assert "channels" in m

                await ws.send(json.dumps({"type": "ping", "t": 42}))
                pong = await recv_until(ws, "pong")
                assert pong.get("t") == 42
                assert isinstance(pong.get("server_t"), (int, float))
                assert pong.get("online") is not None

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_defeat_includes_gold_lost():
    import aiosqlite

    from database.db import close_db, init_db
    from game.combat_engine import combat_engine, reset_combat_engine
    from game.player_manager import get_character
    from network.message_handler import _persist_battle_end

    async def scenario():
        path = Path(tempfile.mkdtemp()) / "gl.db"
        import config

        os.environ["DATABASE_URL"] = str(path)
        config.DATABASE_URL = str(path)
        await close_db()
        gen = await init_db()
        try:
            db = await aiosqlite.connect(path)
            await db.execute(
                "INSERT INTO users (email, password_hash, username) VALUES ('g@e.com','x','GU')"
            )
            await db.execute(
                """
                INSERT INTO characters
                (user_id, name, max_hp, current_hp, max_mp, current_mp, gold, world_x, world_y, level)
                VALUES (1, 'G', 40, 1, 10, 10, '80', 2, 2, 1)
                """
            )
            await db.commit()
            await db.close()
            reset_combat_engine()
            char = await get_character(1)
            hero = dict(char)
            hero["known_spells"] = []
            b = combat_engine.start(1, hero, "dragonlord", seed=1)
            for _ in range(40):
                if b.outcome != "ongoing":
                    break
                b.act({"type": "attack"})
            assert b.outcome == "defeat"
            out = await _persist_battle_end(1, b)
            assert str(out.get("gold")) == "40"
            assert int(out.get("gold_lost") or 0) == 40
        finally:
            await close_db(gen)

    asyncio.run(scenario())
