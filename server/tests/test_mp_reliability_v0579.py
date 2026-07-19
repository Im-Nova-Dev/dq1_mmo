"""v0.5.79 multiplayer reliability: AFK system notices, shop clears AFK, counts.afk_for."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager
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


def test_mark_active_unit():
    mgr = ConnectionManager()

    class FakeWS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, FakeWS(), name="Hero", x=2, y=2, map_id=0)
        assert mgr.set_afk(1, True)
        assert mgr.get_meta(1).get("afk") is True
        was = mgr.mark_active(1)
        assert was is True
        meta = mgr.get_meta(1)
        assert meta.get("afk") is False and meta.get("afk_since") is None
        assert mgr.mark_active(1) is False  # already active

    asyncio.run(scenario())


def test_afk_system_notice_to_peer(tmp_path, monkeypatch):
    db_path = tmp_path / "afk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "AfkHero")
        tb, cb = register_char(base, "b@ex.com", "Bb", "PeerHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "afk"}))
                ack = await recv_until(wa, "afk", "error")
                assert ack.get("type") == "afk" and ack.get("afk") is True, ack

                # Peer should get system chat (may be interleaved with player_update)
                notice = None
                end = time.monotonic() + 2.5
                while time.monotonic() < end and notice is None:
                    try:
                        m = json.loads(await asyncio.wait_for(wb.recv(), 0.4))
                        if m.get("type") == "chat" and m.get("channel") == "system":
                            if "AFK" in str(m.get("text") or ""):
                                notice = m
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                assert notice is not None, "peer missed AFK system notice"
                assert "AfkHero" in str(notice.get("text") or "")

                await drain(wa)
                await drain(wb)
                await wa.send(json.dumps({"type": "back"}))
                await recv_until(wa, "afk", "error")
                back = None
                end = time.monotonic() + 2.5
                while time.monotonic() < end and back is None:
                    try:
                        m = json.loads(await asyncio.wait_for(wb.recv(), 0.4))
                        if m.get("type") == "chat" and m.get("channel") == "system":
                            if "back" in str(m.get("text") or "").lower():
                                back = m
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                assert back is not None, "peer missed back system notice"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_buy_clears_afk_for_peers(tmp_path, monkeypatch):
    db_path = tmp_path / "buy.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "b1@ex.com", "B1", "BuyerA")
        tb, cb = register_char(base, "b2@ex.com", "B2", "PeerB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "afk"}))
                await recv_until(wa, "afk", "error")
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "buy", "item": "herb", "quantity": 1}))
                inv = await recv_until(wa, "inventory_update", "error")
                assert inv.get("type") == "inventory_update", inv

                # Peer should see AFK cleared via player_update / status
                cleared = False
                end = time.monotonic() + 2.5
                while time.monotonic() < end and not cleared:
                    try:
                        m = json.loads(await asyncio.wait_for(wb.recv(), 0.4))
                        if m.get("type") in ("player_update", "player_moved"):
                            if m.get("afk") is False or (
                                m.get("player") or {}
                            ).get("afk") is False:
                                cleared = True
                        # also accept who/look refresh paths
                        if m.get("type") == "player_update" and m.get("id") == ca["id"]:
                            if m.get("afk") is False:
                                cleared = True
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                # Verify via look if peer pulse was noisy
                await wb.send(json.dumps({"type": "look", "name": "BuyerA"}))
                look = await recv_until(wb, "look", "error")
                card = (look.get("player") or {})
                assert card.get("afk") is False, card

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_counts_you_afk_for(tmp_path, monkeypatch):
    db_path = tmp_path / "cnt.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "c@ex.com", "Cc", "CountAfk")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "afk"}))
                await recv_until(ws, "afk", "error")
                await asyncio.sleep(0.05)
                await ws.send(json.dumps({"type": "counts"}))
                cnt = await recv_until(ws, "counts", "error")
                you = cnt.get("you") or {}
                assert you.get("afk") is True, you
                assert "afk_for" in you, you
                assert int(you.get("afk_for") or 0) >= 0
                assert "played" in you

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_shop_unauth_and_stuck_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "reg.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "r@ex.com", "Rr", "RegShop")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as bare:
                await bare.send(json.dumps({"type": "buy", "item": "herb"}))
                m = await recv_until(bare, "error", "inventory_update")
                assert m.get("type") == "error" and "auth" in str(m.get("reason")), m

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "stuck"}))
                st = await recv_until(ws, "stuck", "error")
                assert st.get("type") == "stuck"
                await ws.send(json.dumps({"type": "played"}))
                pl = await recv_until(ws, "played", "error")
                assert pl.get("type") == "played" and pl.get("session_id") is not None

        asyncio.run(flow())
    finally:
        stop_server(server)
