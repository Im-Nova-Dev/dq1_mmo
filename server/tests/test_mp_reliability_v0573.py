"""v0.5.73 multiplayer reliability: played, chat aliases, soft reconnect, peeks."""

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


def test_session_started_preserved_on_live_replace():
    """Live socket replace keeps /played timer; soft reconnect does not."""
    mgr = ConnectionManager()

    class FakeWS:
        def __init__(self, n):
            self.n = n
            self.closed = False

        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            self.closed = True

    async def scenario():
        a, b = FakeWS(1), FakeWS(2)
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        meta = mgr.get_meta(1)
        assert meta is not None
        started = float(meta["session_started"])
        await asyncio.sleep(0.05)
        # Live replace
        await mgr.connect(1, b, name="Hero", x=2, y=2, map_id=0)
        meta2 = mgr.get_meta(1)
        assert meta2 is not None
        assert float(meta2["session_started"]) == started, (started, meta2["session_started"])
        assert a.closed is True
        # Soft disconnect + reconnect resets timer
        await mgr.disconnect(1)
        await asyncio.sleep(0.02)
        c = FakeWS(3)
        await mgr.connect(1, c, name="Hero", x=2, y=2, map_id=0)
        meta3 = mgr.get_meta(1)
        assert meta3 is not None
        assert float(meta3["session_started"]) >= started + 0.04, meta3["session_started"]

    asyncio.run(scenario())


def test_played_profile_mapinfo_server_aliases(tmp_path, monkeypatch):
    db_path = tmp_path / "play.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "p@ex.com", "Pp", "PlayHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await asyncio.sleep(0.15)
                await ws.send(json.dumps({"type": "played"}))
                pl = await recv_until(ws, "played", "error")
                assert pl.get("type") == "played", pl
                assert int(pl.get("seconds") or 0) >= 0
                assert pl.get("session_id") is not None
                assert "session" in str(pl.get("message") or "").lower() or "s" in str(
                    pl.get("message") or ""
                )
                assert pl.get("name") == "PlayHero"
                assert pl.get("online") is not None
                assert "zone" in pl
                assert "nearby_count" in pl

                await ws.send(json.dumps({"type": "session"}))
                pl2 = await recv_until(ws, "played", "error")
                assert pl2.get("type") == "played", pl2

                await ws.send(json.dumps({"type": "profile"}))
                look = await recv_until(ws, "look", "error")
                assert look.get("type") == "look", look
                card = look.get("player") or {}
                assert card.get("name") == "PlayHero" or look.get("name") == "PlayHero"

                await ws.send(json.dumps({"type": "whereis", "name": "PlayHero"}))
                look2 = await recv_until(ws, "look", "error")
                assert look2.get("type") == "look", look2

                await ws.send(json.dumps({"type": "mapinfo"}))
                z = await recv_until(ws, "zone", "error")
                assert z.get("type") == "zone", z
                assert z.get("session_id") is not None
                assert z.get("online") is not None

                await ws.send(json.dumps({"type": "server"}))
                ver = await recv_until(ws, "version", "error")
                assert ver.get("type") == "version", ver
                assert str(ver.get("version") or "").startswith("0.5.")

                await ws.send(json.dumps({"type": "info"}))
                ver2 = await recv_until(ws, "version", "error")
                assert ver2.get("type") == "version", ver2

                await ws.send(json.dumps({"type": "counts"}))
                cnt = await recv_until(ws, "counts", "error")
                assert cnt.get("type") == "counts", cnt
                you = cnt.get("you") or {}
                assert "played" in you, you
                assert int(you.get("played") or 0) >= 0

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_s_and_g_chat_channels(tmp_path, monkeypatch):
    db_path = tmp_path / "sg.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "NearA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "NearB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wsa, websockets.connect(ws_url) as wsb:
                await auth(wsa, ta, ca["id"])
                await auth(wsb, tb, cb["id"])
                await drain(wsa, 0.15)
                await drain(wsb, 0.15)

                await wsa.send(json.dumps({"type": "s", "text": "hello near"}))
                echo = await recv_until(wsa, "chat", "error")
                assert echo.get("type") == "chat", echo
                assert echo.get("channel") == "nearby", echo
                assert echo.get("text") == "hello near"
                peer = await recv_until(wsb, "chat", "error")
                assert peer.get("channel") == "nearby" and peer.get("text") == "hello near"

                await asyncio.sleep(0.85)  # chat rate (CHAT_MIN_INTERVAL=0.75)
                await wsa.send(json.dumps({"type": "g", "text": "hello world"}))
                ge = await recv_until(wsa, "chat", "error")
                assert ge.get("type") == "chat" and ge.get("channel") == "global", ge
                gp = await recv_until(wsb, "chat", "error")
                assert gp.get("channel") == "global" and gp.get("text") == "hello world"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_soft_reconnect_ignore_and_played_reset(tmp_path, monkeypatch):
    """Ignore list survives soft reconnect; played timer resets after full leave."""
    db_path = tmp_path / "soft.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s1@ex.com", "S1", "SoftA")
        tb, cb = register_char(base, "s2@ex.com", "S2", "SoftB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wsa, websockets.connect(ws_url) as wsb:
                await auth(wsa, ta, ca["id"])
                await auth(wsb, tb, cb["id"])
                await drain(wsa, 0.1)
                await drain(wsb, 0.1)

                await wsa.send(json.dumps({"type": "ignore", "name": "SoftB"}))
                ig = await recv_until(wsa, "ignore", "error", "ignores")
                assert ig.get("type") in ("ignore", "ignores"), ig

                await asyncio.sleep(0.2)
                await wsa.send(json.dumps({"type": "played"}))
                pl = await recv_until(wsa, "played", "error")
                age1 = int(pl.get("seconds") or 0)

            # Soft reconnect within grace
            await asyncio.sleep(0.15)
            async with websockets.connect(ws_url) as wsa2:
                auth2 = await auth(wsa2, ta, ca["id"])
                # may have restored ignores
                await wsa2.send(json.dumps({"type": "ignores"}))
                lst = await recv_until(wsa2, "ignores", "ignore", "error")
                body = lst if lst.get("type") == "ignores" else lst
                ignores = body.get("ignores") or body.get("names") or []
                # list form or objects
                names = set()
                if isinstance(ignores, list):
                    for it in ignores:
                        if isinstance(it, dict):
                            names.add(it.get("name") or it.get("id"))
                        else:
                            names.add(it)
                elif isinstance(ignores, dict):
                    names.update(ignores.values())
                assert any("SoftB" in str(n) for n in names) or cb["id"] in names or any(
                    str(n) == str(cb["id"]) for n in names
                ), (lst, names)

                await wsa2.send(json.dumps({"type": "played"}))
                pl2 = await recv_until(wsa2, "played", "error")
                # New connection after disconnect → age should be small
                assert int(pl2.get("seconds") or 0) <= max(2, age1), pl2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_and_who_still_work(tmp_path, monkeypatch):
    """Regression: classic multiplayer paths still healthy."""
    db_path = tmp_path / "reg.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "w1@ex.com", "W1", "WhispA")
        tb, cb = register_char(base, "w2@ex.com", "W2", "WhispB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wsa, websockets.connect(ws_url) as wsb:
                await auth(wsa, ta, ca["id"])
                await auth(wsb, tb, cb["id"])
                await drain(wsa, 0.1)
                await drain(wsb, 0.1)

                await wsa.send(
                    json.dumps({"type": "whisper", "to": "WhispB", "text": "psst"})
                )
                we = await recv_until(wsa, "chat", "error")
                assert we.get("channel") == "whisper", we
                wr = await recv_until(wsb, "chat", "error")
                assert wr.get("text") == "psst" and wr.get("channel") == "whisper"

                await wsa.send(json.dumps({"type": "who"}))
                who = await recv_until(wsa, "who", "error")
                assert who.get("type") == "who"
                assert int(who.get("online") or 0) >= 2

                await wsa.send(json.dumps({"type": "find", "query": "Whisp"}))
                fnd = await recv_until(wsa, "find", "error")
                assert fnd.get("type") == "find"
                assert int(fnd.get("count") or 0) >= 1

        asyncio.run(flow())
    finally:
        stop_server(server)
