"""v0.5.96 multiplayer: combat census, find combat filter, cancel after accept."""

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


def test_combat_count_census(tmp_path, monkeypatch):
    db_path = tmp_path / "cc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "CenA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "CenB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "counts"}))
                c0 = await recv_until(wa, "counts", "error")
                assert "combat_count" in c0, c0
                assert int(c0.get("combat_count") or 0) == 0

                await wb.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 7})
                )
                await recv_until(wb, "combat_start", "error")

                await wa.send(json.dumps({"type": "who"}))
                who = await recv_until(wa, "who", "error")
                assert int(who.get("combat_count") or 0) >= 1, who

                await wa.send(json.dumps({"type": "counts"}))
                c1 = await recv_until(wa, "counts", "error")
                assert int(c1.get("combat_count") or 0) >= 1, c1
                assert "fighting" in str(c1.get("message") or "").lower() or int(
                    c1.get("combat_count") or 0
                ) >= 1

                await wa.send(json.dumps({"type": "ping", "t": 1}))
                pong = await recv_until(wa, "pong", "error")
                assert int(pong.get("combat_count") or 0) >= 1, pong

                st, health = http_json(base, "GET", "/health")
                assert st == 200, health
                assert int(health.get("combat_count") or 0) >= 1, health

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_find_combat_filter(tmp_path, monkeypatch):
    db_path = tmp_path / "fc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "f1@ex.com", "F1", "FindA")
        tb, cb = register_char(base, "f2@ex.com", "F2", "FindB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wb.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 8})
                )
                await recv_until(wb, "combat_start", "error")

                await wa.send(json.dumps({"type": "find", "q": "combat:yes"}))
                f = await recv_until(wa, "find", "error")
                assert f.get("type") == "find", f
                names = [p.get("name") for p in (f.get("players") or [])]
                assert "FindB" in names, names
                assert "combat:yes" in str(f.get("query") or "")
                assert int(f.get("combat_count") or 0) >= 1

                await wa.send(json.dumps({"type": "find", "q": "fighting"}))
                f2 = await recv_until(wa, "find", "error")
                names2 = [p.get("name") for p in (f2.get("players") or [])]
                assert "FindB" in names2, names2

                await wa.send(json.dumps({"type": "find", "q": "combat:maybe"}))
                err = await recv_until(wa, "error", "find")
                assert err.get("type") == "error"
                assert "combat" in str(err.get("reason") or "").lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_cancel_after_accept_no_spam(tmp_path, monkeypatch):
    db_path = tmp_path / "cxl.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "x@ex.com", "Xx", "HostX")
        tb, cb = register_char(base, "y@ex.com", "Yy", "GuestY")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "invite", "to": "GuestY"}))
                await recv_until(wa, "invite", "error")
                await recv_until(wb, "invite", "error")

                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "accept"}))
                await recv_until(wb, "invite_reply", "error")
                await recv_until(wa, "invite_reply", "error")

                # Host last_invite_to should already be cleared by accept —
                # if somehow still set, cancel must not spam guest
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "cancel"}))
                # either no invite to cancel, or cleared without peer notify
                m = await recv_until(wa, "error", "invite_cancel")
                if m.get("type") == "invite_cancel":
                    # guest must NOT receive another cancel after accept
                    leaked = []
                    end = time.monotonic() + 0.25
                    while time.monotonic() < end:
                        try:
                            raw = await asyncio.wait_for(
                                wb.recv(), max(0.01, end - time.monotonic())
                            )
                            leaked.append(json.loads(raw))
                        except (asyncio.TimeoutError, TimeoutError):
                            break
                    assert not any(x.get("type") == "invite_cancel" for x in leaked), leaked
                else:
                    assert "cancel" in str(m.get("reason") or "").lower() or m.get(
                        "type"
                    ) == "error"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_share_whisper_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "reg96.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "r1@ex.com", "R1", "Reg96A")
        tb, cb = register_char(base, "r2@ex.com", "R2", "Reg96B")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "share", "to": "Reg96B"}))
                s = await recv_until(wa, "share", "error")
                assert s.get("type") == "share"
                await recv_until(wb, "share", "error")

                await asyncio.sleep(0.85)
                await wa.send(
                    json.dumps({"type": "whisper", "to": "Reg96B", "text": "hi"})
                )
                w = await recv_until(wa, "chat", "error")
                assert w.get("channel") == "whisper"
                await recv_until(wb, "chat", "error")

        asyncio.run(flow())
    finally:
        stop_server(server)
