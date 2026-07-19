"""v0.5.70 multiplayer reliability: counts.you, find idle, soft-reconnect restored flags."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import CHAT_MIN_INTERVAL, ConnectionManager
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


def test_find_idle_filter_unit():
    mgr = ConnectionManager()

    class FakeWS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Active", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="AfkOne", x=3, y=2, map_id=0)
        mgr.set_afk(2, True)
        idle_hits = mgr.find_by_prefix("", idle=True)
        names = {c.get("name") for c in idle_hits}
        assert "AfkOne" in names and "Active" not in names, idle_hits
        active = mgr.find_by_prefix("", idle=False)
        names2 = {c.get("name") for c in active}
        assert "Active" in names2 and "AfkOne" not in names2, active

    asyncio.run(scenario())


def test_counts_includes_you(tmp_path, monkeypatch):
    db_path = tmp_path / "cnt.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "c@ex.com", "Cc", "CntA")
        tb, cb = register_char(base, "d@ex.com", "Dd", "CntB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                aa = await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "afk"}))
                await recv_until(wa, "afk", "error")
                await wa.send(json.dumps({"type": "counts"}))
                c = await recv_until(wa, "counts", "error")
                assert c.get("type") == "counts", c
                assert int(c.get("online") or 0) == 2, c
                you = c.get("you") or {}
                assert you.get("id") == ca["id"], you
                assert you.get("session_id") == aa.get("session_id"), you
                assert you.get("afk") is True, you
                assert you.get("zone") == "town", you
                assert you.get("nearby_count") is not None, you
                assert c.get("session_id") == aa.get("session_id"), c

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_find_idle_and_invalid_filter(tmp_path, monkeypatch):
    db_path = tmp_path / "fid.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "f@ex.com", "Ff", "FidA")
        tb, cb = register_char(base, "g@ex.com", "Gg", "FidB")

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
                await wa.send(json.dumps({"type": "find", "q": "idle:yes"}))
                f = await recv_until(wa, "find", "error")
                assert f.get("type") == "find" and f.get("idle") is True, f
                hits = f.get("players") or []
                assert any(h.get("name") == "FidB" for h in hits), f
                assert not any(h.get("name") == "FidA" for h in hits), f

                await wa.send(json.dumps({"type": "find", "q": "idle:maybe"}))
                e = await recv_until(wa, "find", "error")
                assert e.get("type") == "error"
                assert "idle" in str(e.get("reason") or "").lower(), e

                # Old path still works
                await wa.send(json.dumps({"type": "find", "q": "zone:town"}))
                z = await recv_until(wa, "find", "error")
                assert z.get("type") == "find" and (z.get("count") or 0) >= 2, z

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_soft_reconnect_restored_flags(tmp_path, monkeypatch):
    """Ignore + last whisper survive disconnect and surface on restored."""
    db_path = tmp_path / "rest.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ra@ex.com", "Ra", "RestA")
        tb, cb = register_char(base, "rb@ex.com", "Rb", "RestB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await wa.send(json.dumps({"type": "ignore", "name": "RestB"}))
                await recv_until(wa, "ignore", "error")
                await asyncio.sleep(CHAT_MIN_INTERVAL + 0.05)
                await drain(wa)
                # Unignore so whisper works, note last peer, then re-ignore
                await wa.send(json.dumps({"type": "unignore", "name": "RestB"}))
                await recv_until(wa, "ignore", "error")
                await asyncio.sleep(CHAT_MIN_INTERVAL + 0.05)
                await wa.send(
                    json.dumps({"type": "whisper", "to": "RestB", "text": "hi"})
                )
                await recv_until(wa, "chat", "error")
                await recv_until(wb, "chat", "error")
                await wa.send(json.dumps({"type": "ignore", "name": "RestB"}))
                await recv_until(wa, "ignore", "error")

            # Soft reconnect A
            async with websockets.connect(ws_url) as wa2:
                await wa2.send(
                    json.dumps(
                        {"type": "auth", "token": ta, "character_id": ca["id"]}
                    )
                )
                auth_ok = None
                world = None
                deadline = time.monotonic() + 4.0
                while time.monotonic() < deadline and (
                    auth_ok is None or world is None
                ):
                    raw = await asyncio.wait_for(wa2.recv(), 1.0)
                    m = json.loads(raw)
                    if m.get("type") == "auth_ok":
                        auth_ok = m
                    if m.get("type") == "world_state":
                        world = m
                assert auth_ok is not None and world is not None, (auth_ok, world)
                restored = world.get("restored") or auth_ok.get("restored") or {}
                assert restored.get("ignores") is True, restored
                assert restored.get("last_whisper") is True, restored
                welcome = auth_ok.get("welcome") or ""
                assert "Restored" in welcome or restored.get("ignores"), welcome
                # Soft state usable
                await wa2.send(json.dumps({"type": "lastwhisper"}))
                lw = await recv_until(wa2, "lastwhisper", "error")
                peer = lw.get("peer") or {}
                assert peer.get("name") == "RestB", lw
                await wa2.send(json.dumps({"type": "ignores"}))
                ig = await recv_until(wa2, "ignore", "error")
                names = {
                    str(c.get("name") or "").lower()
                    for c in (ig.get("ignores") or [])
                }
                assert "restb" in names, ig

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_shout_ignore_and_three_player_zone(tmp_path, monkeypatch):
    """Regression: shout=zone, ignore blocks, 3-player delivery."""
    db_path = tmp_path / "sh.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sa@ex.com", "Sa", "ShA")
        tb, cb = register_char(base, "sb@ex.com", "Sb", "ShB")
        tc, cc = register_char(base, "sc@ex.com", "Sc", "ShC")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
                websockets.connect(ws_url) as wc,
            ):
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await auth(wc, tc, cc["id"])
                await asyncio.sleep(CHAT_MIN_INTERVAL + 0.05)
                await drain(wb)
                await drain(wc)
                await wa.send(
                    json.dumps({"type": "chat", "channel": "shout", "text": "hi3"})
                )
                ma = await recv_until(wa, "chat", "error")
                mb = await recv_until(wb, "chat", "error")
                mc = await recv_until(wc, "chat", "error")
                assert ma.get("channel") == "zone", ma
                assert mb.get("text") == "hi3" and mc.get("text") == "hi3"

                await asyncio.sleep(CHAT_MIN_INTERVAL + 0.05)
                await wb.send(json.dumps({"type": "ignore", "name": "ShA"}))
                await recv_until(wb, "ignore", "error")
                await asyncio.sleep(CHAT_MIN_INTERVAL + 0.05)
                await drain(wb)
                await wa.send(
                    json.dumps({"type": "chat", "channel": "shout", "text": "sec"})
                )
                await recv_until(wa, "chat", "error")
                leaked = [x for x in await drain(wb, 0.3) if x.get("text") == "sec"]
                assert len(leaked) == 0, leaked

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_session_replace_online_count(tmp_path, monkeypatch):
    """Replace keeps online flat (old reliability path)."""
    db_path = tmp_path / "rep.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "xa@ex.com", "Xa", "RepA")
        tb, cb = register_char(base, "xb@ex.com", "Xb", "RepB")

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
                        you = c.get("you") or {}
                        assert you.get("session_id") == a2.get("session_id"), you

        asyncio.run(flow())
    finally:
        stop_server(server)
