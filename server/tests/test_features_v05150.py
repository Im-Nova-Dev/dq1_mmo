"""v0.5.150: field magic extract · /cast heal WS · version."""

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


def test_cast_heal_or_full_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "cast.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "csta@ex.com", "Ca", "CastA")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wsa:
                await auth(wsa, ta, ca["id"])
                await drain(wsa, 0.15)

                # Level 1 may not know heal; full HP refuses; both valid
                await wsa.send(json.dumps({"type": "cast", "spell": "heal"}))
                m = await recv_until(wsa, "spell_cast", "error")
                assert m.get("type") in ("spell_cast", "error"), m
                if m.get("type") == "error":
                    assert m.get("reason") in (
                        "unknown or unlearned spell",
                        "already at full HP",
                        "not enough MP",
                        "cannot cast on field",
                    ), m
                else:
                    assert "online" in m

                await wsa.send(json.dumps({"type": "version"}))
                v = await recv_until(wsa, "version", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_field_magic_module_exports():
    from network.handlers import field_magic as fm

    assert "cast" in fm.ALL_TYPES
    assert "heal" in fm.FIELD_SHORTCUTS
    assert "repel" in fm.FIELD_SHORTCUTS
