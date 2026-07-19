"""v0.5.71 adversarial lock-in: combat move gate, first-join restored, social edges, peeks under fire."""

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
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.12)
    return m


def test_move_blocked_in_combat(tmp_path, monkeypatch):
    db_path = tmp_path / "mvc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "m@ex.com", "Mm", "MoveC")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "debug_encounter", "enemy": "slime"}))
                st = await recv_until(ws, "combat_start", "error")
                assert st.get("type") == "combat_start", st
                await drain(ws, 0.15)
                await ws.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 7}))
                # Prefer move_ok (always present for client reconcile) or error
                msgs = []
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and len(msgs) < 4:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), 0.4)
                        m = json.loads(raw)
                        if m.get("type") in ("error", "move_ok"):
                            msgs.append(m)
                            if m.get("type") == "move_ok":
                                break
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                assert msgs, "no move response in combat"
                reasons = " ".join(str(m.get("reason") or "") for m in msgs).lower()
                assert "combat" in reasons, msgs
                move_oks = [m for m in msgs if m.get("type") == "move_ok"]
                if move_oks:
                    assert move_oks[-1].get("ok") is False, move_oks[-1]

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_first_join_restored_all_false(tmp_path, monkeypatch):
    db_path = tmp_path / "fj.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "f@ex.com", "Ff", "FirstJ")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": ta, "character_id": ca["id"]}
                    )
                )
                auth_ok = world = None
                deadline = time.monotonic() + 4.0
                while time.monotonic() < deadline and (
                    auth_ok is None or world is None
                ):
                    raw = await asyncio.wait_for(ws.recv(), 1.0)
                    m = json.loads(raw)
                    if m.get("type") == "auth_ok":
                        auth_ok = m
                    if m.get("type") == "world_state":
                        world = m
                assert auth_ok and world
                rest = world.get("restored") or auth_ok.get("restored") or {}
                assert rest.get("ignores") is False
                assert rest.get("last_whisper") is False
                assert rest.get("repel") is False
                assert rest.get("radiant") is False
                assert "Restored" not in str(auth_ok.get("welcome") or "")

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_ignore_both_directions(tmp_path, monkeypatch):
    db_path = tmp_path / "wig.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "wa@ex.com", "Wa", "WigA")
        tb, cb = register_char(base, "wb@ex.com", "Wb", "WigB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                # B ignores A
                await wb.send(json.dumps({"type": "ignore", "name": "WigA"}))
                await recv_until(wb, "ignore", "error")
                await asyncio.sleep(CHAT_MIN_INTERVAL + 0.05)
                await wa.send(
                    json.dumps({"type": "whisper", "to": "WigB", "text": "blocked"})
                )
                m = await recv_until(wa, "error", "chat")
                assert m.get("type") == "error"
                assert "unavailable" in str(m.get("reason") or "").lower(), m

                await wb.send(json.dumps({"type": "unignore", "name": "WigA"}))
                await recv_until(wb, "ignore", "error")
                # A ignores B
                await wa.send(json.dumps({"type": "ignore", "name": "WigB"}))
                await recv_until(wa, "ignore", "error")
                await asyncio.sleep(CHAT_MIN_INTERVAL + 0.05)
                await wa.send(
                    json.dumps({"type": "whisper", "to": "WigB", "text": "nope"})
                )
                m = await recv_until(wa, "error", "chat")
                assert m.get("type") == "error"
                assert "ignore" in str(m.get("reason") or "").lower(), m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_concurrent_peeks_and_counts_you(tmp_path, monkeypatch):
    db_path = tmp_path / "cp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "p@ex.com", "Pp", "PeekA")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                aa = await auth(ws, ta, ca["id"])
                await asyncio.gather(
                    ws.send(json.dumps({"type": "who"})),
                    ws.send(json.dumps({"type": "counts"})),
                    ws.send(json.dumps({"type": "buffs"})),
                    ws.send(json.dumps({"type": "keys"})),
                )
                got = set()
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline and len(got) < 4:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), 0.5)
                        m = json.loads(raw)
                        got.add(m.get("type"))
                        if m.get("type") == "counts":
                            you = m.get("you") or {}
                            assert you.get("session_id") == aa.get("session_id"), m
                            assert you.get("zone") == "town", m
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                assert {"who", "counts", "buffs", "controls"} <= got, got

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_find_filters_and_bare_shop_errors(tmp_path, monkeypatch):
    db_path = tmp_path / "ff.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "z@ex.com", "Zz", "FindZ")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "find", "q": "zone:town idle:no"}))
                f = await recv_until(ws, "find", "error")
                assert f.get("type") == "find" and f.get("idle") is False, f
                assert any(h.get("name") == "FindZ" for h in (f.get("players") or [])), f

                await ws.send(json.dumps({"type": "buy"}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error" and "item" in str(m.get("reason") or "").lower()
                await ws.send(json.dumps({"type": "sell"}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error" and "item" in str(m.get("reason") or "").lower()
                await ws.send(json.dumps({"type": "discard"}))
                m = await recv_until(ws, "error", "inventory_update")
                assert m.get("type") == "error" and "item" in str(m.get("reason") or "").lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_unignore_offline_and_flee_ooc(tmp_path, monkeypatch):
    db_path = tmp_path / "uo.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "u@ex.com", "Uu", "UnigA")
        tb, cb = register_char(base, "v@ex.com", "Vv", "UnigB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa:
                await auth(wa, ta, ca["id"])
                async with websockets.connect(ws_url) as wb:
                    await auth(wb, tb, cb["id"])
                    await wa.send(json.dumps({"type": "ignore", "name": "UnigB"}))
                    await recv_until(wa, "ignore", "error")
                    await wb.send(json.dumps({"type": "quit"}))
                    await recv_until(wb, "quit", "error")
                await asyncio.sleep(0.2)
                await wa.send(json.dumps({"type": "unignore", "name": "UnigB"}))
                m = await recv_until(wa, "ignore", "error")
                assert m.get("type") == "ignore" and m.get("action") == "unignore", m

                await wa.send(json.dumps({"type": "flee"}))
                m = await recv_until(wa, "error", "combat_update")
                assert m.get("type") == "error"
                assert "combat" in str(m.get("reason") or "").lower(), m

        asyncio.run(flow())
    finally:
        stop_server(server)
