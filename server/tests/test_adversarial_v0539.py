"""Adversarial findings from v0.5.39 hunt: find zone:moon, non-integer moves."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.ws_helpers import register_char, start_server, stop_server


async def recv_until(ws, *types, timeout=4.0):
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
    await recv_until(ws, "auth_ok")
    await drain(ws, 0.12)


def test_find_zone_moon_is_invalid_zone(tmp_path, monkeypatch):
    """Bare /find zone:moon must say invalid zone (not find query required)."""
    db_path = tmp_path / "moon.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "moon@ex.com", "MoonU", "MoonHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, token, ch["id"])
                for q in ("zone:moon", "zone:void", "  zone:SPACE", "Bob zone:nether"):
                    await ws.send(json.dumps({"type": "find", "q": q}))
                    err = await recv_until(ws, "error", "find")
                    assert err.get("type") == "error", (q, err)
                    assert err.get("reason") == "invalid zone", (q, err)

                # Valid zone-only still works
                await ws.send(json.dumps({"type": "find", "q": "zone:town"}))
                ok = await recv_until(ws, "find", "error")
                assert ok.get("type") == "find", ok
                assert ok.get("zone") == "town"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_non_integer_move_rejected(tmp_path, monkeypatch):
    """Fractional x/y must not truncate into a free step (3.7 → 3)."""
    db_path = tmp_path / "fmove.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "fm@ex.com", "FmU", "FloatMover")

        async def flow():
            import websockets
            import network.message_handler as mh

            orig = mh.roll_encounter
            mh.roll_encounter = lambda *a, **k: None  # type: ignore
            try:
                async with websockets.connect(ws_url) as ws:
                    await auth(ws, token, ch["id"])
                    # Fractional adjacent-looking step (server also emits error + move_ok)
                    await ws.send(
                        json.dumps({"type": "move", "x": 3.7, "y": 2.0, "seq": 1})
                    )
                    saw_reject = False
                    for _ in range(6):
                        m = await recv_until(ws, "move_ok", "error")
                        if m.get("type") == "error" and m.get("reason") == "invalid move":
                            saw_reject = True
                        if m.get("type") == "move_ok":
                            assert m.get("ok") is False, m
                            assert m.get("reason") == "invalid move", m
                            assert m.get("x") == 2 and m.get("y") == 2, m
                            saw_reject = True
                            break
                    assert saw_reject
                    await drain(ws, 0.1)

                    # Integer-valued float is OK (3.0, 2.0)
                    await ws.send(
                        json.dumps({"type": "move", "x": 3.0, "y": 2.0, "seq": 2})
                    )
                    m2 = await recv_until(ws, "move_ok", "error")
                    # skip stray errors if any
                    if m2.get("type") == "error":
                        m2 = await recv_until(ws, "move_ok")
                    assert m2.get("type") == "move_ok", m2
                    assert m2.get("ok") is True, m2
                    assert m2.get("x") == 3 and m2.get("y") == 2, m2
            finally:
                mh.roll_encounter = orig

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_self_blocked(tmp_path, monkeypatch):
    db_path = tmp_path / "wself.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "ws@ex.com", "WsU", "SelfTalk")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, token, ch["id"])
                await ws.send(
                    json.dumps(
                        {"type": "whisper", "to": "SelfTalk", "text": "hello me"}
                    )
                )
                err = await recv_until(ws, "error", "chat")
                assert err.get("type") == "error", err
                assert "yourself" in str(err.get("reason") or "").lower(), err

        asyncio.run(flow())
    finally:
        stop_server(server)
