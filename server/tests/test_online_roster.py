"""Global online count pulses + roster (free port)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def recv_until(ws, *types, timeout=4.0):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(str(types))
        m = json.loads(await asyncio.wait_for(ws.recv(), remaining))
        if m.get("type") in types:
            return m


async def drain(ws, seconds=0.2):
    end = time.monotonic() + seconds
    out = []
    while time.monotonic() < end:
        try:
            out.append(json.loads(await asyncio.wait_for(ws.recv(), 0.05)))
        except (asyncio.TimeoutError, TimeoutError):
            break
    return out


def test_online_pulse_and_roster(tmp_path, monkeypatch):
    db_path = tmp_path / "on.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    from tests.ws_helpers import register_char, start_server, stop_server

    server, port, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "oa@ex.com", "OnA", "OnAlice")
        token_b, ch_b = register_char(base, "ob@ex.com", "OnB", "OnBob")

        async def flow():
            import websockets

            async def auth(ws, token, cid):
                await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
                types = set()
                online_seen = None
                for _ in range(8):
                    m = json.loads(await asyncio.wait_for(ws.recv(), 3))
                    types.add(m.get("type"))
                    if m.get("type") == "online":
                        online_seen = m
                    if "auth_ok" in types and "world_state" in types:
                        break
                assert "auth_ok" in types
                return online_seen

            async with websockets.connect(ws_url) as wa:
                await auth(wa, token_a, ch_a["id"])
                await drain(wa, 0.15)

                async with websockets.connect(ws_url) as wb:
                    await auth(wb, token_b, ch_b["id"])
                    # Alice should get online pulse when Bob joins
                    online_a = None
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        try:
                            m = json.loads(await asyncio.wait_for(wa.recv(), 0.4))
                            if m.get("type") == "online" and m.get("online") == 2:
                                online_a = m
                                break
                        except (asyncio.TimeoutError, TimeoutError):
                            continue
                    assert online_a is not None, "Alice should see online=2"
                    assert any(p.get("id") == ch_b["id"] for p in online_a.get("roster") or [])

                    await wb.send(json.dumps({"type": "who"}))
                    who = await recv_until(wb, "who")
                    assert who["online"] == 2
                    assert len(who.get("roster") or []) == 2
                    names = {p["name"] for p in who["roster"]}
                    assert "OnAlice" in names and "OnBob" in names

                # Bob disconnected — Alice gets online=1
                online_left = None
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    try:
                        m = json.loads(await asyncio.wait_for(wa.recv(), 0.4))
                        if m.get("type") == "online" and m.get("online") == 1:
                            online_left = m
                            break
                    except (asyncio.TimeoutError, TimeoutError):
                        continue
                assert online_left is not None, "Alice should see online=1 after Bob leaves"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_online_roster_unit():
    from network.websocket_manager import ConnectionManager

    mgr = ConnectionManager()

    class WS:
        def __init__(self):
            self.sent = []

        async def send_text(self, t):
            self.sent.append(t)

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, WS(), name="Zed", x=2, y=2, map_id=1, level=3)
        await mgr.connect(2, WS(), name="Amy", x=3, y=2, map_id=1, level=1, in_combat=True)
        roster = mgr.online_roster()
        assert len(roster) == 2
        # sorted by name
        assert roster[0]["name"] == "Amy"
        assert roster[1]["name"] == "Zed"
        assert roster[0]["in_combat"] is True
        # no coordinates leaked
        assert "x" not in roster[0]

    asyncio.run(scenario())
