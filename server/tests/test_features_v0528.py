"""v0.5.28: move rate only on valid steps; reserved channel before chat rate."""

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
            raise TimeoutError(f"waiting for {types}")
        raw = await asyncio.wait_for(ws.recv(), remaining)
        m = json.loads(raw)
        if m.get("type") in types:
            return m


async def drain(ws, seconds=0.15):
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
            out.append(json.loads(raw))
        except (asyncio.TimeoutError, TimeoutError):
            break
    return out


def test_invalid_step_does_not_burn_move_rate(tmp_path, monkeypatch):
    """Wall/same-tile rejections must not rate-limit the next real step."""
    db_path = tmp_path / "move_rate.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "mr@ex.com", "Mr", "MoveRate")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await drain(ws, 0.1)

                # Same-tile step (invalid) — must not consume rate budget
                await ws.send(json.dumps({"type": "move", "x": 2, "y": 2, "seq": 1}))
                m = await recv_until(ws, "move_ok", "error")
                # Either error + move_ok or just move_ok with ok=False
                if m.get("type") == "error":
                    m = await recv_until(ws, "move_ok")
                assert m.get("ok") is False
                assert m.get("reason") == "invalid step", m

                # Immediately take a valid adjacent step — must succeed (not rate_limit)
                await ws.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 2}))
                m2 = await recv_until(ws, "move_ok", "error")
                if m2.get("type") == "error":
                    m2 = await recv_until(ws, "move_ok")
                assert m2.get("ok") is True, m2
                assert m2.get("reason") != "rate_limit", m2
                assert int(m2.get("x")) == 3 and int(m2.get("y")) == 2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_reserved_channel_before_rate_limit(tmp_path, monkeypatch):
    """Spoofing system/admin channel returns reserved channel, not rate_limit first."""
    db_path = tmp_path / "reschan.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "rc@ex.com", "Rc", "ResChan")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await drain(ws, 0.1)

                await ws.send(
                    json.dumps(
                        {
                            "type": "chat",
                            "channel": "system",
                            "text": "spoof attempt",
                        }
                    )
                )
                m = await recv_until(ws, "error")
                assert m.get("reason") == "reserved channel", m

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_who_zones_and_help_mentions_who(tmp_path, monkeypatch):
    db_path = tmp_path / "whoz.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "wz@ex.com", "Wz", "WhoZone")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps(
                        {"type": "auth", "token": token, "character_id": ch["id"]}
                    )
                )
                await recv_until(ws, "auth_ok")
                await drain(ws, 0.1)

                await ws.send(json.dumps({"type": "who"}))
                who = await recv_until(ws, "who")
                zones = who.get("zones") or {}
                assert "town" in zones and "field" in zones and "dungeon" in zones
                assert int(zones.get("town") or 0) >= 1

                await ws.send(json.dumps({"type": "help"}))
                help_m = await recv_until(ws, "help")
                cmds = " ".join(
                    str(c.get("cmd")) + " " + str(c.get("hint"))
                    for c in (help_m.get("commands") or [])
                )
                assert "who" in cmds.lower()
                assert "ignore" in cmds.lower()

        asyncio.run(flow())
    finally:
        stop_server(server)
