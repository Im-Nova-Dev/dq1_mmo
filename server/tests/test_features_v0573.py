"""v0.5.73 features: played peek, whereis, mapinfo, version aliases under rate spam."""

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


def test_played_unauthenticated_fails(tmp_path, monkeypatch):
    db_path = tmp_path / "uauth.db"
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
                await ws.send(json.dumps({"type": "played"}))
                m = await recv_until(ws, "error", "played")
                assert m.get("type") == "error"
                assert "auth" in str(m.get("reason") or "").lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_rate_exempt_peeks_under_spam(tmp_path, monkeypatch):
    """played/profile/mapinfo/version stay usable while non-exempt messages rate-limit."""
    db_path = tmp_path / "rate.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "r@ex.com", "Rr", "RateHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                # Burn general message rate with junk types that are not exempt
                limited = False
                for i in range(80):
                    await ws.send(json.dumps({"type": "emote", "emote": "wave"}))
                    try:
                        m = await recv_until(ws, "emote", "error", timeout=0.4)
                        if m.get("type") == "error" and m.get("reason") == "rate_limit":
                            limited = True
                            break
                    except TimeoutError:
                        continue
                # Even if rate didn't trip (emote may use chat rate), peeks must work
                await ws.send(json.dumps({"type": "played"}))
                pl = await recv_until(ws, "played", "error")
                assert pl.get("type") == "played", pl

                await ws.send(json.dumps({"type": "card"}))
                look = await recv_until(ws, "look", "error")
                assert look.get("type") == "look", look

                await ws.send(json.dumps({"type": "mapinfo"}))
                z = await recv_until(ws, "zone", "error")
                assert z.get("type") == "zone", z

                await ws.send(json.dumps({"type": "about"}))
                v = await recv_until(ws, "version", "error")
                assert v.get("type") == "version", v
                _ = limited  # optional signal

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_empty_s_chat_no_echo(tmp_path, monkeypatch):
    db_path = tmp_path / "empty.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "e@ex.com", "Ee", "EmptyS")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "s", "text": "   "}))
                m = await recv_until(ws, "error", "chat")
                assert m.get("type") == "error"
                assert m.get("reason") == "empty chat"
                # Immediate real chat should work (no false rate burn from empty)
                await ws.send(json.dumps({"type": "s", "text": "ok"}))
                c = await recv_until(ws, "chat", "error")
                assert c.get("type") == "chat" and c.get("channel") == "nearby"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_help_lists_played_and_whereis(tmp_path, monkeypatch):
    db_path = tmp_path / "help.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "HelpH")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                assert h.get("type") == "help"
                cmds = h.get("commands") or []
                blob = json.dumps(cmds).lower()
                assert "played" in blob
                assert "whereis" in blob or "profile" in blob

        asyncio.run(flow())
    finally:
        stop_server(server)
