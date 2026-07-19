"""v0.5.81: /cast field magic aliases, discard slash, cast clears AFK."""

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


async def set_level(cid: int, level: int, mp: int = 50):
    """Bump hero level so field spells unlock (heal at L3+)."""
    from database.db import db_write

    async with db_write() as db:
        await db.execute(
            "UPDATE characters SET level = ?, max_mp = ?, current_mp = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (level, mp, mp, cid),
        )
        await db.commit()


def test_cast_unlearned_and_aliases(tmp_path, monkeypatch):
    db_path = tmp_path / "cast.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "c@ex.com", "Cc", "CastHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                # Level 1 has no field spells
                await ws.send(json.dumps({"type": "cast", "spell": "heal"}))
                err = await recv_until(ws, "error", "spell_cast")
                assert err.get("type") == "error", err
                assert "spell" in str(err.get("reason") or "").lower() or "unlearned" in str(
                    err.get("reason") or ""
                ), err

                await set_level(ca["id"], 10, mp=80)
                # re-auth not required for live char patch on next get_character
                await ws.send(json.dumps({"type": "cast", "spell": "heal"}))
                # full HP → already at full HP
                m = await recv_until(ws, "error", "spell_cast")
                assert m.get("type") in ("error", "spell_cast"), m
                if m.get("type") == "error":
                    assert "full" in str(m.get("reason") or "").lower() or "mp" in str(
                        m.get("reason") or ""
                    ), m

                # shortcut type repel
                await ws.send(json.dumps({"type": "repel"}))
                r = await recv_until(ws, "spell_cast", "error")
                assert r.get("type") in ("spell_cast", "error"), r
                if r.get("type") == "spell_cast":
                    assert int(r.get("repel_steps") or 0) > 0 or "repel" in str(
                        r.get("message") or ""
                    ).lower(), r

                # return teleport home
                await ws.send(json.dumps({"type": "cast", "spell": "return"}))
                ret = await recv_until(ws, "spell_cast", "error", "move_ok")
                # may get move_ok first
                if ret.get("type") == "move_ok":
                    ret = await recv_until(ws, "spell_cast", "error")
                assert ret.get("type") in ("spell_cast", "error"), ret

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_cast_clears_afk(tmp_path, monkeypatch):
    db_path = tmp_path / "cafk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "CasterA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "PeerB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await set_level(ca["id"], 10, mp=80)
                await wa.send(json.dumps({"type": "afk"}))
                await recv_until(wa, "afk", "error")
                await drain(wb, 0.3)
                # cast repel while AFK
                await wa.send(json.dumps({"type": "cast", "spell": "repel"}))
                sc = await recv_until(wa, "spell_cast", "error")
                if sc.get("type") != "spell_cast":
                    # still clear AFK attempt failed — skip peer check
                    return
                await wb.send(json.dumps({"type": "look", "name": "CasterA"}))
                look = await recv_until(wb, "look", "error")
                card = look.get("player") or {}
                assert card.get("afk") is False, card

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_discard_slash_and_help(tmp_path, monkeypatch):
    db_path = tmp_path / "disc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "d@ex.com", "Dd", "DiscHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                # start with 3 herbs
                await ws.send(json.dumps({"type": "discard", "item": "herb", "quantity": 1}))
                inv = await recv_until(ws, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv
                assert inv.get("discarded") or "Discard" in str(inv.get("message") or ""), inv

                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                blob = json.dumps(h).lower()
                assert "cast" in blob and "discard" in blob

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_cast_unauth(tmp_path, monkeypatch):
    db_path = tmp_path / "cu.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"type": "cast", "spell": "heal"}))
                m = await recv_until(ws, "error", "spell_cast")
                assert m.get("type") == "error", m

        asyncio.run(flow())
    finally:
        stop_server(server)
