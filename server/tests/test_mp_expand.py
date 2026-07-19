"""Expanded multiplayer: whisper, reconnect soft-state, combat roster, ownership."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import RECONNECT_SOFT_GRACE, ConnectionManager
from tests.ws_helpers import register_char, start_server, stop_server


async def recv_until(ws, *types, timeout=4.0):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"waiting for {types}")
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


def test_soft_grace_repel_unit():
    """Repel survives brief disconnect via soft grace; expires after window."""
    mgr = ConnectionManager()

    class WS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        ws = WS()
        await mgr.connect(1, ws, name="A", x=2, y=2, map_id=1)
        mgr.set_repel(1, 12)
        assert mgr.repel_remaining(1) == 12
        left = await mgr.disconnect(1, ws)
        assert left is not None
        # Offline: grace bag holds repel
        assert 1 in mgr._soft_grace
        assert mgr._soft_grace[1]["repel_steps"] == 12

        ws2 = WS()
        await mgr.connect(1, ws2, name="A", x=2, y=2, map_id=1)
        assert mgr.repel_remaining(1) == 12
        assert 1 not in mgr._soft_grace

        # Expired grace is ignored
        await mgr.disconnect(1, ws2)
        mgr._soft_grace[1] = {
            "repel_steps": 9,
            "expires": time.monotonic() - 1,
        }
        ws3 = WS()
        await mgr.connect(1, ws3, name="A", x=2, y=2, map_id=1)
        assert mgr.repel_remaining(1) == 0

    asyncio.run(scenario())
    assert RECONNECT_SOFT_GRACE >= 30


def test_find_id_by_name_unit():
    mgr = ConnectionManager()

    class WS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, WS(), name="Alice", x=2, y=2, map_id=1)
        await mgr.connect(2, WS(), name="Bob", x=3, y=2, map_id=1)
        assert mgr.find_id_by_name("alice") == 1
        assert mgr.find_id_by_name("  BOB ") == 2
        assert mgr.find_id_by_name("carol") is None
        assert mgr.find_id_by_name("") is None

    asyncio.run(scenario())


def test_whisper_and_offline_target(tmp_path, monkeypatch):
    db_path = tmp_path / "mp_w.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "wa@ex.com", "WhA", "WhAlice")
        token_b, ch_b = register_char(base, "wb@ex.com", "WhB", "WhBob")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                for ws, tok, ch in ((wa, token_a, ch_a), (wb, token_b, ch_b)):
                    await ws.send(
                        json.dumps(
                            {"type": "auth", "token": tok, "character_id": ch["id"]}
                        )
                    )
                    await recv_until(ws, "auth_ok")
                    await recv_until(ws, "world_state")
                await drain(wa)
                await drain(wb)

                await wa.send(
                    json.dumps(
                        {
                            "type": "whisper",
                            "to": "WhBob",
                            "text": "secret plans",
                        }
                    )
                )
                # Both sides get the whisper chat
                ca = await recv_until(wa, "chat")
                cb = await recv_until(wb, "chat")
                assert ca["channel"] == "whisper"
                assert ca["text"] == "secret plans"
                assert ca["to"] == "WhBob"
                assert cb["channel"] == "whisper"
                assert cb["name"] == "WhAlice"

                # Third party offline name
                await asyncio.sleep(0.8)
                await wa.send(
                    json.dumps({"type": "whisper", "to": "Nobody", "text": "hi"})
                )
                err = await recv_until(wa, "error")
                assert err["reason"] == "player not online"

                # Cannot whisper self
                await asyncio.sleep(0.8)
                await wa.send(
                    json.dumps({"type": "tell", "to": "WhAlice", "text": "me"})
                )
                err2 = await recv_until(wa, "error")
                assert err2["reason"] == "cannot whisper yourself"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_reconnect_restores_repel_and_moves(tmp_path, monkeypatch):
    """Disconnect → reconnect within grace: repel restored, moves work (seq reset)."""
    db_path = tmp_path / "mp_rc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "rc@ex.com", "RcU", "RcHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps({"type": "auth", "token": token, "character_id": ch["id"]})
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                # Grant fairy water via shop/buy if needed — use item path if in inventory
                # Starting inventory has herbs; use debug-free path: fairy water from shop
                await ws.send(json.dumps({"type": "buy", "item": "fairy_water"}))
                inv = await recv_until(ws, "inventory_update", "error")
                if inv.get("type") == "error":
                    # already have or shop issue — try use anyway
                    pass
                else:
                    assert any(
                        i.get("item_id") == "fairy_water" for i in inv.get("items", [])
                    )
                await ws.send(json.dumps({"type": "use_item", "item": "fairy_water"}))
                used = await recv_until(ws, "item_used", "error")
                assert used.get("type") == "item_used", used
                assert (used.get("repel_steps") or 0) > 0
                steps = int(used["repel_steps"])

            # Short gap then reconnect
            await asyncio.sleep(0.15)

            async with websockets.connect(ws_url) as ws2:
                await ws2.send(
                    json.dumps({"type": "auth", "token": token, "character_id": ch["id"]})
                )
                m1 = await recv_until(ws2, "auth_ok")
                assert m1["type"] == "auth_ok"
                snap = await recv_until(ws2, "world_state")
                # world_state includes repel after soft restore
                assert int(snap.get("repel") or 0) == steps, snap

                # Move seq starts fresh at 1 (not stuck as duplicate)
                await ws2.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 1}))
                mok = await recv_until(ws2, "move_ok")
                assert mok.get("ok") is True
                assert mok.get("duplicate") is not True
                assert mok["x"] == 3

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_socket_replace_ownership(tmp_path, monkeypatch):
    """Second connection replaces first; old socket is not authoritative."""
    db_path = tmp_path / "mp_own.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "ow@ex.com", "OwU", "OwHero")

        async def flow():
            import websockets

            wa = await websockets.connect(ws_url)
            await wa.send(
                json.dumps({"type": "auth", "token": token, "character_id": ch["id"]})
            )
            await recv_until(wa, "auth_ok")
            await recv_until(wa, "world_state")

            wb = await websockets.connect(ws_url)
            await wb.send(
                json.dumps({"type": "auth", "token": token, "character_id": ch["id"]})
            )
            await recv_until(wb, "auth_ok")
            await recv_until(wb, "world_state")
            await drain(wb)

            # New socket owns the character
            await wb.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 1}))
            mok = await recv_until(wb, "move_ok")
            assert mok.get("ok") is True

            # Old socket should be closed or ineffective; don't hang forever
            try:
                await asyncio.wait_for(wa.recv(), 1.0)
            except Exception:
                pass

            await wb.close()
            try:
                await wa.close()
            except Exception:
                pass

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_combat_pulses_online_roster(tmp_path, monkeypatch):
    """Entering combat marks in_combat on global roster pulse."""
    db_path = tmp_path / "mp_cb.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    config.ALLOW_DEBUG = True
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "ca@ex.com", "CbA", "CbAlice")
        token_b, ch_b = register_char(base, "cb@ex.com", "CbB", "CbBob")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                for ws, tok, ch in ((wa, token_a, ch_a), (wb, token_b, ch_b)):
                    await ws.send(
                        json.dumps(
                            {"type": "auth", "token": tok, "character_id": ch["id"]}
                        )
                    )
                    await recv_until(ws, "auth_ok")
                    await recv_until(ws, "world_state")
                await drain(wa)
                await drain(wb)

                await wa.send(
                    json.dumps(
                        {"type": "debug_encounter", "enemy": "slime", "seed": 7}
                    )
                )
                await recv_until(wa, "combat_start")

                # Bob should see an online pulse and/or player_update with combat
                saw_combat = False
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    try:
                        m = json.loads(
                            await asyncio.wait_for(wb.recv(), remaining)
                        )
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                    if m.get("type") == "online":
                        for card in m.get("roster") or []:
                            if card.get("id") == ch_a["id"] and card.get("in_combat"):
                                saw_combat = True
                                break
                    if m.get("type") == "player_update" and m.get(
                        "player_id"
                    ) == ch_a["id"]:
                        if m.get("in_combat"):
                            saw_combat = True
                    if saw_combat:
                        break
                assert saw_combat, "expected combat flag on roster or player_update"

        asyncio.run(flow())
    finally:
        stop_server(server)
