"""v0.5.69: buffs peek, controls/keys, inspect alias, blocklist, discard bare item."""

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


def test_buffs_empty_and_with_repel(tmp_path, monkeypatch):
    db_path = tmp_path / "buff.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "b@ex.com", "Bb", "BuffH")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "buffs"}))
                m = await recv_until(ws, "buffs", "error")
                assert m.get("type") == "buffs", m
                assert int(m.get("repel") or 0) == 0 and int(m.get("radiant") or 0) == 0
                assert m.get("afk") is False
                assert "No active" in str(m.get("message") or "")

                await ws.send(json.dumps({"type": "buy", "item": "fairy_water"}))
                await recv_until(ws, "inventory_update", "error")
                await ws.send(json.dumps({"type": "use_item", "item": "fairy_water"}))
                used = await recv_until(ws, "item_used", "error", "inventory_update")
                # may be item_used
                if used.get("type") != "item_used":
                    # drain for item_used
                    for _ in range(5):
                        try:
                            used = await recv_until(ws, "item_used", "error", timeout=0.5)
                            if used.get("type") == "item_used":
                                break
                        except TimeoutError:
                            break
                await ws.send(json.dumps({"type": "effects"}))
                b = await recv_until(ws, "buffs", "error")
                assert b.get("type") == "buffs", b
                assert int(b.get("repel") or 0) > 0, b
                assert "Repel" in str(b.get("message") or ""), b

                await ws.send(json.dumps({"type": "afk"}))
                await recv_until(ws, "afk", "error")
                await ws.send(json.dumps({"type": "buffs"}))
                b2 = await recv_until(ws, "buffs", "error")
                assert b2.get("afk") is True and "AFK" in str(b2.get("message") or ""), b2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_controls_and_keys(tmp_path, monkeypatch):
    db_path = tmp_path / "keys.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "k@ex.com", "Kk", "KeysH")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "keys"}))
                m = await recv_until(ws, "controls", "error")
                assert m.get("type") == "controls", m
                assert isinstance(m.get("overworld"), list) and len(m["overworld"]) >= 3
                assert isinstance(m.get("combat"), list)
                assert "WASD" in str(m.get("message") or "")

                await ws.send(json.dumps({"type": "controls"}))
                m2 = await recv_until(ws, "controls", "error")
                assert m2.get("type") == "controls"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_inspect_alias_and_blocklist(tmp_path, monkeypatch):
    db_path = tmp_path / "insp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ia@ex.com", "Ia", "InspA")
        tb, cb = register_char(base, "ib@ex.com", "Ib", "InspB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "inspect", "name": "InspB"}))
                m = await recv_until(wa, "look", "error")
                assert m.get("type") == "look", m
                p = m.get("player") or {}
                assert p.get("name") == "InspB", p

                await wa.send(json.dumps({"type": "ignore", "name": "InspB"}))
                await recv_until(wa, "ignore", "error")
                await wa.send(json.dumps({"type": "blocklist"}))
                bl = await recv_until(wa, "ignore", "error")
                assert bl.get("type") == "ignore" and bl.get("action") == "list", bl
                names = {
                    str(c.get("name") or "").lower()
                    for c in (bl.get("ignores") or [])
                }
                assert "inspb" in names, bl

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_discard_bare_item_required(tmp_path, monkeypatch):
    db_path = tmp_path / "disc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "d@ex.com", "Dd", "DiscH")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "discard"}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error"
                assert "item" in str(m.get("reason") or "").lower(), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_help_lists_buffs_and_keys(tmp_path, monkeypatch):
    db_path = tmp_path / "hlp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "HelpBuff")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                cmds = {c.get("cmd") for c in (h.get("commands") or [])}
                assert "buffs" in cmds and "keys" in cmds, cmds

        asyncio.run(flow())
    finally:
        stop_server(server)
