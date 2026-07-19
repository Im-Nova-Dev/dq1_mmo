"""v0.5.84 adversarial: invalid roll must not clear AFK; multiplayer/shop regressions."""

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


def test_invalid_roll_sides_preserves_afk(tmp_path, monkeypatch):
    """Bad dice sizes must not burn chat rate or clear manual AFK."""
    db_path = tmp_path / "roll_afk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "r@ex.com", "Rr", "RollAfk")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "afk", "text": "coffee"}))
                ack = await recv_until(ws, "afk", "error")
                assert ack.get("afk") is True and ack.get("afk_message") == "coffee", ack

                for sides in (0, 1, -3, 1001, True, "nope"):
                    await ws.send(json.dumps({"type": "roll", "sides": sides}))
                    err = await recv_until(ws, "error", "chat")
                    assert err.get("type") == "error", err
                    assert "sides" in str(err.get("reason") or "").lower() or "invalid" in str(
                        err.get("reason") or ""
                    ).lower(), err
                    # Must not report chat_rate_limit for validation failures
                    assert err.get("reason") != "chat_rate_limit", err

                await ws.send(json.dumps({"type": "status"}))
                st = await recv_until(ws, "status", "error")
                you = st.get("you") or {}
                assert you.get("afk") is True, you
                assert you.get("afk_message") == "coffee", you

                # Immediate valid roll still works (rate never burned)
                await ws.send(json.dumps({"type": "roll"}))
                ok = await recv_until(ws, "chat", "error")
                assert ok.get("type") == "chat", ok
                assert "rolls" in str(ok.get("text") or "").lower()

                await ws.send(json.dumps({"type": "status"}))
                st2 = await recv_until(ws, "status", "error")
                you2 = st2.get("you") or {}
                assert you2.get("afk") is False, you2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_failed_social_preserves_afk_matrix(tmp_path, monkeypatch):
    """Empty chat, bad emote, offline whisper, unknown buy keep AFK."""
    db_path = tmp_path / "afk_matrix.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "m@ex.com", "Mm", "AfkKeep")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])

                async def assert_afk(reason: str):
                    await ws.send(json.dumps({"type": "status"}))
                    st = await recv_until(ws, "status", "error")
                    you = st.get("you") or {}
                    assert you.get("afk") is True, f"{reason}: {you}"

                async def set_afk():
                    await ws.send(json.dumps({"type": "afk", "text": "hold"}))
                    await recv_until(ws, "afk", "error")

                await set_afk()
                await ws.send(json.dumps({"type": "chat", "text": ""}))
                await recv_until(ws, "error")
                await assert_afk("empty chat")

                await set_afk()
                await ws.send(json.dumps({"type": "emote", "emote": "floss"}))
                await recv_until(ws, "error")
                await assert_afk("bad emote")

                await set_afk()
                await ws.send(json.dumps({"type": "whisper", "to": "Ghost", "text": "hi"}))
                await recv_until(ws, "error")
                await assert_afk("offline whisper")

                await set_afk()
                await ws.send(json.dumps({"type": "buy", "item": "banana_peel"}))
                await recv_until(ws, "error")
                await assert_afk("unknown buy")

                await set_afk()
                await ws.send(json.dumps({"type": "yell", "text": "   "}))
                await recv_until(ws, "error")
                await assert_afk("empty yell")

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_shop_and_combat_gates_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "shop_combat.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    monkeypatch.setenv("ALLOW_DEBUG", "1")
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s@ex.com", "Ss", "ShopGate")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])

                # Equip consumable rejected
                await ws.send(json.dumps({"type": "equip", "item": "herbs"}))
                err = await recv_until(ws, "error", "inventory_update")
                assert err.get("type") == "error", err

                # Buy club, equip as armor → wrong slot
                await ws.send(json.dumps({"type": "buy", "item": "club"}))
                await recv_until(ws, "inventory_update", "error")
                await ws.send(json.dumps({"type": "equip", "slot": "armor", "item": "club"}))
                err2 = await recv_until(ws, "error", "inventory_update")
                assert err2.get("type") == "error", err2
                assert "slot" in str(err2.get("reason") or "").lower(), err2

                # Sell equipped by display name
                await ws.send(json.dumps({"type": "buy", "item": "dragon scale"}))
                await recv_until(ws, "inventory_update", "error")
                await ws.send(json.dumps({"type": "equip", "item": "dragon scale"}))
                await recv_until(ws, "inventory_update", "error")
                await ws.send(json.dumps({"type": "discard", "item": "dragon scale"}))
                disc = await recv_until(ws, "error", "inventory_update")
                assert disc.get("type") == "error", disc  # equipped not in bag
                await ws.send(json.dumps({"type": "sell", "item": "Dragon's Scale"}))
                sold = await recv_until(ws, "inventory_update", "error")
                assert sold.get("type") == "inventory_update", sold
                assert (sold.get("sold") or {}).get("item_id") == "dragons_scale"

                # Combat gates
                await ws.send(json.dumps({"type": "debug_encounter", "enemy": "slime"}))
                await recv_until(ws, "combat_start", "combat_update", "error")
                await ws.send(json.dumps({"type": "buy", "item": "herb"}))
                buy_c = await recv_until(ws, "error", "inventory_update")
                assert buy_c.get("type") == "error" and "combat" in str(
                    buy_c.get("reason") or ""
                ).lower(), buy_c
                await ws.send(json.dumps({"type": "stuck"}))
                stuck = await recv_until(ws, "error", "stuck")
                assert stuck.get("type") == "error", stuck
                await ws.send(json.dumps({"type": "flee"}))
                # drain combat end
                end = time.monotonic() + 3
                while time.monotonic() < end:
                    try:
                        m = json.loads(
                            await asyncio.wait_for(ws.recv(), max(0.05, end - time.monotonic()))
                        )
                        if m.get("type") == "combat_end":
                            break
                    except (asyncio.TimeoutError, TimeoutError):
                        break

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_soft_reconnect_and_peeks_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "soft_peek.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "p@ex.com", "Pp", "PeekHero")
        tb, cb = register_char(base, "q@ex.com", "Qq", "PeerHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "ignore", "name": "PeerHero"}))
                await recv_until(wa, "ignore", "ignores", "error")
                await wa.send(json.dumps({"type": "afk", "text": "brb"}))
                await recv_until(wa, "afk")

            async with websockets.connect(ws_url) as wa2:
                await auth(wa2, ta, ca["id"])
                await wa2.send(json.dumps({"type": "status"}))
                st = await recv_until(wa2, "status", "error")
                you = st.get("you") or {}
                assert you.get("afk") is False, you

                await wa2.send(json.dumps({"type": "who"}))
                await wa2.send(json.dumps({"type": "counts"}))
                await wa2.send(json.dumps({"type": "played"}))
                who = await recv_until(wa2, "who", "error")
                counts = await recv_until(wa2, "counts", "error")
                played = await recv_until(wa2, "played", "error")
                assert who.get("type") == "who" and "afk_count" in who, who
                assert counts.get("type") == "counts" and "afk_count" in counts, counts
                assert played.get("type") == "played", played

                await wa2.send(json.dumps({"type": "ignores"}))
                ig = await recv_until(wa2, "ignores", "ignore", "error")
                blob = json.dumps(ig)
                assert "PeerHero" in blob, ig

                # Full heal does not burn MP
                from database.db import db_write

                async with db_write() as db:
                    await db.execute(
                        "UPDATE characters SET level=5, max_mp=40, current_mp=40, "
                        "current_hp=max_hp WHERE id=?",
                        (ca["id"],),
                    )
                    await db.commit()
                await wa2.send(json.dumps({"type": "cast", "spell": "heal"}))
                err = await recv_until(wa2, "error", "spell_cast")
                assert err.get("type") == "error", err
                await wa2.send(json.dumps({"type": "status"}))
                st2 = await recv_until(wa2, "status", "error")
                mp = (st2.get("character") or {}).get("current_mp")
                assert int(mp or 0) == 40, st2

        asyncio.run(flow())
    finally:
        stop_server(server)
