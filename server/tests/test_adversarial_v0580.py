"""v0.5.80 adversarial lock-in: AFK notices, shop/AFK activity, combat shop gates."""

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


async def recv_system_chat(ws, needle: str, timeout=3.0):
    end = time.monotonic() + timeout
    needle_l = needle.lower()
    while time.monotonic() < end:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), 0.4))
            if (
                m.get("type") == "chat"
                and m.get("channel") == "system"
                and needle_l in str(m.get("text") or "").lower()
            ):
                return m
        except (asyncio.TimeoutError, TimeoutError):
            break
    return None


async def drain(ws, seconds=0.15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
        except (asyncio.TimeoutError, TimeoutError):
            break


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.12)
    return m


def test_afk_back_notices_and_buy_clears(tmp_path, monkeypatch):
    db_path = tmp_path / "adv.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "AdvA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "AdvB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "afk"}))
                await recv_until(wa, "afk", "error")
                n = await recv_system_chat(wb, "AFK")
                assert n is not None and "AdvA" in str(n.get("text") or ""), n

                await drain(wb)
                await wa.send(json.dumps({"type": "buy", "item": "herb"}))
                inv = await recv_until(wa, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv
                await wb.send(json.dumps({"type": "look", "name": "AdvA"}))
                look = await recv_until(wb, "look", "error")
                assert (look.get("player") or {}).get("afk") is False, look

                await wa.send(json.dumps({"type": "afk"}))
                await recv_until(wa, "afk", "error")
                await asyncio.sleep(0.05)
                await wa.send(json.dumps({"type": "counts"}))
                cnt = await recv_until(wa, "counts", "error")
                you = cnt.get("you") or {}
                assert you.get("afk") is True and "afk_for" in you, you

                await drain(wb)
                await wa.send(json.dumps({"type": "back"}))
                await recv_until(wa, "afk", "error")
                n2 = await recv_system_chat(wb, "back")
                assert n2 is not None, "missing back notice"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_combat_blocks_shop_and_stuck(tmp_path, monkeypatch):
    db_path = tmp_path / "cbt.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    monkeypatch.setenv("ALLOW_DEBUG", "1")
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "c@ex.com", "Cc", "CbtHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "debug_encounter", "enemy": "slime"}))
                st = await recv_until(ws, "combat_start", "error")
                assert st.get("type") == "combat_start", st
                for typ, extra in (
                    ("stuck", {}),
                    ("shop", {}),
                    ("buy", {"item": "herb"}),
                    ("sell", {"item": "herb"}),
                    ("equip", {"item": "club"}),
                ):
                    await ws.send(json.dumps({"type": typ, **extra}))
                    m = await recv_until(
                        ws, "error", "stuck", "shop_list", "inventory_update"
                    )
                    assert m.get("type") == "error" and m.get("reason") == "in combat", (
                        typ,
                        m,
                    )
                await ws.send(json.dumps({"type": "flee"}))
                await drain(ws, 0.35)

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_unauth_shop_buy_sell_use(tmp_path, monkeypatch):
    db_path = tmp_path / "ua.db"
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
                for typ, extra in (
                    ("shop", {}),
                    ("buy", {"item": "herb"}),
                    ("sell", {"item": "herb"}),
                    ("use", {"item": "herb"}),
                    ("equip", {"item": "club"}),
                ):
                    await ws.send(json.dumps({"type": typ, **extra}))
                    m = await recv_until(
                        ws, "error", "shop_list", "inventory_update", "item_used"
                    )
                    assert m.get("type") == "error" and "auth" in str(m.get("reason")), (
                        typ,
                        m,
                    )

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_qty_and_peek_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "qty.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "q@ex.com", "Qq", "QtyHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                for payload in (
                    {"type": "buy", "item": "herb", "quantity": 0},
                    {"type": "buy"},
                    {"type": "discard"},
                    {"type": "yell", "text": "  "},
                ):
                    await ws.send(json.dumps(payload))
                    m = await recv_until(ws, "error", "inventory_update", "chat")
                    assert m.get("type") == "error", m
                    if payload.get("type") == "yell":
                        await asyncio.sleep(0.0)

                for t in ("played", "buffs", "counts", "version", "emotes"):
                    await ws.send(json.dumps({"type": t}))
                got = set()
                end = time.monotonic() + 3.0
                while time.monotonic() < end and len(got) < 4:
                    try:
                        m = json.loads(await asyncio.wait_for(ws.recv(), 0.4))
                        got.add(m.get("type"))
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                assert len(got) >= 4 and "played" in got, got

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_after_afk_cycle(tmp_path, monkeypatch):
    """Whisper still works after AFK/back system notices (no queue pollution)."""
    db_path = tmp_path / "wh.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "w1@ex.com", "W1", "WhA")
        tb, cb = register_char(base, "w2@ex.com", "W2", "WhB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "afk"}))
                await recv_until(wa, "afk", "error")
                await drain(wb, 0.35)
                await wa.send(json.dumps({"type": "back"}))
                await recv_until(wa, "afk", "error")
                await drain(wb, 0.35)
                await drain(wa, 0.2)
                await asyncio.sleep(0.85)
                await wb.send(
                    json.dumps({"type": "whisper", "to": "WhA", "text": "hello"})
                )
                # skip system if any
                end = time.monotonic() + 3.0
                echo = recv = None
                while time.monotonic() < end and (echo is None or recv is None):
                    for ws, slot in ((wb, "echo"), (wa, "recv")):
                        try:
                            m = json.loads(await asyncio.wait_for(ws.recv(), 0.3))
                        except (asyncio.TimeoutError, TimeoutError):
                            continue
                        if m.get("type") != "chat" or m.get("channel") == "system":
                            continue
                        if slot == "echo" and echo is None:
                            echo = m
                        if slot == "recv" and recv is None:
                            recv = m
                assert echo and echo.get("channel") == "whisper" and echo.get("text") == "hello", echo
                assert recv and recv.get("text") == "hello", recv

        asyncio.run(flow())
    finally:
        stop_server(server)
