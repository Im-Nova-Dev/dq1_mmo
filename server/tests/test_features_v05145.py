"""v0.5.145: chat/say/yell WS · channels · version."""

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


def test_chat_channels_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "chat.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "cha@ex.com", "Ca", "ChatA")
        tb, cb = register_char(base, "chb@ex.com", "Cb", "ChatB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wsa, websockets.connect(
                ws_url
            ) as wsb:
                await auth(wsa, ta, ca["id"])
                await auth(wsb, tb, cb["id"])
                await drain(wsa, 0.15)
                await drain(wsb, 0.15)

                await wsa.send(json.dumps({"type": "g", "text": "hello global"}))
                ge = await recv_until(wsa, "chat", "error")
                assert ge.get("channel") == "global", ge
                assert ge.get("text") == "hello global"
                assert "online" in ge
                gp = await recv_until(wsb, "chat", "error")
                assert gp.get("channel") == "global" and gp.get("text") == "hello global"

                await asyncio.sleep(1.1)
                await wsa.send(json.dumps({"type": "s", "text": "hello near"}))
                ne = await recv_until(wsa, "chat", "error")
                assert ne.get("channel") == "nearby", ne
                np = await recv_until(wsb, "chat", "error")
                assert np.get("channel") == "nearby"

                await asyncio.sleep(1.1)
                await wsa.send(json.dumps({"type": "yell", "text": "hello zone"}))
                ye = await recv_until(wsa, "chat", "error")
                assert ye.get("channel") == "zone", ye
                assert ye.get("zone") in ("town", "field", "dungeon")

                await asyncio.sleep(1.1)
                await wsa.send(json.dumps({"type": "version"}))
                v = await recv_until(wsa, "version", "error")
                assert str(v.get("version") or config.VERSION).startswith("0.5.")

        asyncio.run(flow())
    finally:
        stop_server(server)
