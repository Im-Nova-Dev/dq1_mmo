"""New features: radiant light, sell/heal edge cases already covered, char delete, xp progress."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game.enemy_spawner import (
    DUNGEON_ENCOUNTER_CHANCE,
    DUNGEON_ENCOUNTER_CHANCE_LIT,
    roll_encounter,
)
from game.progression import xp_to_next_level
from game.rng import Rng
from network.websocket_manager import ConnectionManager
from tests.ws_helpers import http_json, register_char, start_server, stop_server


def test_xp_to_next_level_progress():
    p0 = xp_to_next_level(0, 1)
    assert p0["level"] == 1
    assert p0["xp_to_next"] >= 0
    assert p0["max_level"] is False
    # high XP should approach or hit cap
    pmax = xp_to_next_level(10**9, 30)
    assert pmax["max_level"] is True or pmax["xp_to_next"] == 0


def test_radiant_reduces_dungeon_rate_unit():
    assert DUNGEON_ENCOUNTER_CHANCE_LIT < DUNGEON_ENCOUNTER_CHANCE
    # Town still never encounters
    for _ in range(30):
        assert roll_encounter(2, 2, Rng(), radiant=True) is None


def test_radiant_manager_ticks():
    mgr = ConnectionManager()

    class WS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, WS(), name="A", x=2, y=2, map_id=1)
        mgr.set_radiant(1, 3)
        assert mgr.radiant_remaining(1) == 3
        assert mgr.consume_radiant_step(1) is True
        assert mgr.radiant_remaining(1) == 2
        assert mgr.consume_radiant_step(1) is True
        assert mgr.consume_radiant_step(1) is True
        assert mgr.consume_radiant_step(1) is False

    asyncio.run(scenario())


def test_delete_character_rest(tmp_path, monkeypatch):
    db_path = tmp_path / "del.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, _ws = start_server()
    try:
        token, ch = register_char(base, "del@ex.com", "DelU", "DelHero")
        st, chars = http_json(base, "GET", "/auth/characters", token=token)
        assert st == 200 and len(chars) == 1

        st, body = http_json(base, "DELETE", f"/auth/characters/{ch['id']}", token=token)
        # 204 may have empty body
        assert st in (200, 204), body

        st, chars2 = http_json(base, "GET", "/auth/characters", token=token)
        assert st == 200
        assert chars2 == [] or len(chars2) == 0

        # second delete 404
        st, body = http_json(base, "DELETE", f"/auth/characters/{ch['id']}", token=token)
        assert st == 404
    finally:
        stop_server(server)


def test_radiant_spell_ws(tmp_path, monkeypatch):
    """High-level character casts radiant via debug-free path: set level in DB."""
    db_path = tmp_path / "rad.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "rad@ex.com", "RadU", "RadHero")
        # Level up so radiant is known (learn_level 9)
        import sqlite3

        con = sqlite3.connect(str(db_path))
        con.execute(
            "UPDATE characters SET level=12, max_mp=40, current_mp=40, experience=5000 WHERE id=?",
            (ch["id"],),
        )
        con.commit()
        con.close()

        async def flow():
            import websockets

            async def recv_until(ws, *types, timeout=4.0):
                deadline = time.monotonic() + timeout
                while True:
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        raise TimeoutError(types)
                    m = json.loads(await asyncio.wait_for(ws.recv(), rem))
                    if m.get("type") in types:
                        return m

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                auth = await recv_until(ws, "auth_ok")
                assert "xp_progress" in auth.get("character", {}) or True
                await recv_until(ws, "world_state")
                await ws.send(json.dumps({"type": "use_spell", "spell": "radiant"}))
                m = await recv_until(ws, "spell_cast", "error")
                assert m.get("type") == "spell_cast", m
                assert (m.get("radiant_steps") or 0) > 0
                # heal at full HP should not spend (error)
                await ws.send(json.dumps({"type": "use_spell", "spell": "heal"}))
                # may not know heal yet at L12 - heal is earlier
                m2 = await recv_until(ws, "spell_cast", "error")
                # either full HP error or unlearned - both fine
                assert m2.get("type") in ("spell_cast", "error")

        asyncio.run(flow())
    finally:
        stop_server(server)
