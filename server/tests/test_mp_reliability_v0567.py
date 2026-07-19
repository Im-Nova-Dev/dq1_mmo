"""v0.5.67 multiplayer reliability: force join pulse, find afk, roll/counts session_id."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager, CHAT_MIN_INTERVAL
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


def test_find_by_prefix_afk_unit():
    mgr = ConnectionManager()

    class FakeWS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Active", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="AfkBob", x=3, y=2, map_id=0)
        mgr.set_afk(2, True)
        all_t = mgr.find_by_prefix("", zone="town")
        assert len(all_t) >= 2, all_t
        only_afk = mgr.find_by_prefix("", afk=True)
        names = {c.get("name") for c in only_afk}
        assert "AfkBob" in names and "Active" not in names, only_afk
        only_live = mgr.find_by_prefix("", afk=False)
        names2 = {c.get("name") for c in only_live}
        assert "Active" in names2 and "AfkBob" not in names2, only_live
        comb = mgr.find_by_prefix("Afk", zone="town", afk=True)
        assert len(comb) == 1 and comb[0].get("name") == "AfkBob", comb

    asyncio.run(scenario())


def test_find_afk_and_zone_combo(tmp_path, monkeypatch):
    db_path = tmp_path / "findafk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "fa@ex.com", "Fa", "FindA")
        tb, cb = register_char(base, "fb@ex.com", "Fb", "FindB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wb.send(json.dumps({"type": "afk"}))
                await recv_until(wb, "afk", "error")

                await wa.send(json.dumps({"type": "find", "q": "afk:yes"}))
                f = await recv_until(wa, "find", "error")
                assert f.get("type") == "find", f
                hits = f.get("players") or []
                assert any(h.get("name") == "FindB" and h.get("afk") for h in hits), f
                assert not any(h.get("name") == "FindA" for h in hits), f
                assert f.get("afk") is True, f

                await wa.send(json.dumps({"type": "find", "q": "zone:town afk:yes"}))
                f2 = await recv_until(wa, "find", "error")
                assert f2.get("type") == "find" and f2.get("zone") == "town", f2
                hits2 = f2.get("players") or []
                assert any(h.get("name") == "FindB" for h in hits2), f2

                await wa.send(json.dumps({"type": "find", "q": "afk"}))
                f3 = await recv_until(wa, "find", "error")
                assert f3.get("type") == "find", f3
                assert any(h.get("name") == "FindB" for h in (f3.get("players") or [])), f3

                # Old path: zone only still works
                await wa.send(json.dumps({"type": "find", "q": "zone:town"}))
                f4 = await recv_until(wa, "find", "error")
                assert f4.get("type") == "find" and (f4.get("count") or 0) >= 2, f4

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_join_forces_online_roster_session(tmp_path, monkeypatch):
    """Reconnect must force online pulse so peers see new session_id promptly."""
    db_path = tmp_path / "joinforce.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ja@ex.com", "Ja", "JoinA")
        tb, cb = register_char(base, "jb@ex.com", "Jb", "JoinB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wb:
                await auth(wb, tb, cb["id"])
                await drain(wb, 0.15)
                async with websockets.connect(ws_url) as wa:
                    aa = await auth(wa, ta, ca["id"])
                    sid = aa.get("session_id")
                    assert sid is not None
                    # B should receive forced online pulse with A's session
                    deadline = time.monotonic() + 2.0
                    saw = False
                    while time.monotonic() < deadline:
                        try:
                            raw = await asyncio.wait_for(wb.recv(), 0.3)
                            m = json.loads(raw)
                            if m.get("type") == "online":
                                roster = m.get("roster") or []
                                card = next(
                                    (c for c in roster if c.get("name") == "JoinA"),
                                    None,
                                )
                                if card and card.get("session_id") == sid:
                                    saw = True
                                    break
                        except (asyncio.TimeoutError, TimeoutError):
                            continue
                    if not saw:
                        await wb.send(json.dumps({"type": "who"}))
                        who = await recv_until(wb, "who")
                        roster = who.get("roster") or []
                        card = next(
                            (c for c in roster if c.get("name") == "JoinA"), None
                        )
                        assert card is not None and card.get("session_id") == sid, who
                    else:
                        assert saw

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_roll_and_counts_include_session_id(tmp_path, monkeypatch):
    db_path = tmp_path / "rollsid.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ra@ex.com", "Ra", "RollA")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                aa = await auth(ws, ta, ca["id"])
                sid = aa.get("session_id")
                await ws.send(json.dumps({"type": "counts"}))
                c = await recv_until(ws, "counts", "error")
                assert c.get("type") == "counts", c
                assert c.get("session_id") == sid, c
                assert int(c.get("online") or 0) >= 1
                assert c.get("zones") is not None

                await asyncio.sleep(CHAT_MIN_INTERVAL + 0.05)
                await drain(ws)
                await ws.send(json.dumps({"type": "roll", "sides": 6}))
                r = await recv_until(ws, "chat", "error")
                assert r.get("type") == "chat" and r.get("system") is True, r
                assert r.get("session_id") == sid, r
                roll = r.get("roll") or {}
                assert roll.get("sides") == 6 and 1 <= int(roll.get("value") or 0) <= 6
                assert roll.get("session_id") == sid, roll

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_zone_ignore_and_near_afk_regression(tmp_path, monkeypatch):
    """Old paths: zone ignore + near AFK card (v0.5.65+)."""
    db_path = tmp_path / "zign.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "za@ex.com", "Za", "ZoneIgA")
        tb, cb = register_char(base, "zb@ex.com", "Zb", "ZoneIgB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wb.send(json.dumps({"type": "afk"}))
                await recv_until(wb, "afk", "error")
                await wa.send(json.dumps({"type": "near"}))
                n = await recv_until(wa, "near", "error")
                players = n.get("players") or []
                b = next((p for p in players if p.get("name") == "ZoneIgB"), None)
                assert b is not None and b.get("afk") is True, n

                await asyncio.sleep(CHAT_MIN_INTERVAL + 0.05)
                await wb.send(json.dumps({"type": "ignore", "name": "ZoneIgA"}))
                await recv_until(wb, "ignore", "error")
                await asyncio.sleep(CHAT_MIN_INTERVAL + 0.05)
                await drain(wb)
                await wa.send(
                    json.dumps({"type": "chat", "channel": "zone", "text": "secretz"})
                )
                ma = await recv_until(wa, "chat", "error")
                assert ma.get("type") == "chat" and ma.get("channel") == "zone", ma
                leaked = [
                    x for x in await drain(wb, 0.3) if x.get("text") == "secretz"
                ]
                assert len(leaked) == 0, leaked

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_session_replace_online_stable(tmp_path, monkeypatch):
    """Replace socket: online count stays flat (no ghost +1)."""
    db_path = tmp_path / "repl.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sa@ex.com", "Sa", "SidA")
        tb, cb = register_char(base, "sb@ex.com", "Sb", "SidB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wb:
                await auth(wb, tb, cb["id"])
                async with websockets.connect(ws_url) as wa1:
                    a1 = await auth(wa1, ta, ca["id"])
                    s1 = a1.get("session_id")
                    async with websockets.connect(ws_url) as wa2:
                        a2 = await auth(wa2, ta, ca["id"])
                        assert a2.get("session_id") != s1
                        await wa2.send(json.dumps({"type": "counts"}))
                        c = await recv_until(wa2, "counts")
                        assert int(c.get("online") or 0) == 2, c

        asyncio.run(flow())
    finally:
        stop_server(server)
