"""Multiplayer: find zone filter, chat clears idle, player_moved idle."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager, IDLE_SOFT
from tests.ws_helpers import register_char, start_server, stop_server


class FakeWS:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def close(self, *a, **k):
        self.closed = True

    async def send_text(self, t):
        self.sent.append(json.loads(t))


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


def test_find_by_prefix_zone_filter():
    mgr = ConnectionManager()

    async def scenario():
        # Prefix match is name.startswith — use names that share a true prefix
        await mgr.connect(1, FakeWS(), name="AliceTown", x=2, y=2, map_id=0)
        await mgr.connect(2, FakeWS(), name="AliceField", x=8, y=6, map_id=0)
        await mgr.connect(3, FakeWS(), name="BobTown", x=3, y=2, map_id=0)
        all_a = mgr.find_by_prefix("Alice")
        assert len(all_a) == 2, all_a
        town = mgr.find_by_prefix("Alice", zone="town")
        assert len(town) == 1 and town[0]["name"] == "AliceTown", town
        field = mgr.find_by_prefix("Alice", zone="field")
        assert len(field) == 1 and field[0]["name"] == "AliceField", field
        assert "x" not in town[0]
        dung = mgr.find_by_prefix("Alice", zone="dungeon")
        assert dung == []
        # Invalid zone → empty
        assert mgr.find_by_prefix("Alice", zone="moon") == []
        # Zone-only list (empty prefix)
        town_all = mgr.find_by_prefix("", zone="town")
        assert len(town_all) == 2
        assert {p["name"] for p in town_all} == {"AliceTown", "BobTown"}
        # Empty prefix without zone → empty
        assert mgr.find_by_prefix("") == []

    asyncio.run(scenario())


def test_allow_chat_clears_idle():
    mgr = ConnectionManager()

    async def scenario():
        await mgr.connect(1, FakeWS(), name="Chatty", x=2, y=2, map_id=0)
        meta = mgr.get_meta(1)
        meta["last_seen"] = time.monotonic() - (IDLE_SOFT + 10)
        assert mgr.online_roster()[0]["idle"] is True
        ok, _ = mgr.allow_chat(1)
        assert ok
        assert mgr.online_roster()[0]["idle"] is False

    asyncio.run(scenario())


def test_player_moved_includes_idle():
    mgr = ConnectionManager()

    async def scenario():
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="A", x=5, y=5, map_id=0)
        await mgr.connect(2, b, name="B", x=6, y=5, map_id=0)
        b.sent.clear()
        await mgr.publish_move(1, 5, 6, seq=1)
        moves = [m for m in b.sent if m.get("type") == "player_moved"]
        assert moves, b.sent
        assert "idle" in moves[0]
        assert moves[0]["idle"] is False

    asyncio.run(scenario())


def test_find_zone_only_and_invalid_zone_ws(tmp_path, monkeypatch):
    """ /find zone:town lists zone; invalid zone errors. """
    db_path = tmp_path / "fz2.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "za@ex.com", "Za", "ZoneA")
        tb, cb = register_char(base, "zb@ex.com", "Zb", "ZoneB")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                for ws, tok, ch in ((wa, ta, ca), (wb, tb, cb)):
                    await ws.send(
                        json.dumps(
                            {"type": "auth", "token": tok, "character_id": ch["id"]}
                        )
                    )
                    await recv_until(ws, "auth_ok")
                    await drain(ws, 0.08)

                await wa.send(json.dumps({"type": "find", "q": "zone:town"}))
                f = await recv_until(wa, "find", "error")
                assert f.get("type") == "find", f
                assert f.get("zone") == "town"
                assert int(f.get("count") or 0) >= 2
                names = {p.get("name") for p in (f.get("players") or [])}
                assert "ZoneA" in names and "ZoneB" in names

                await wa.send(json.dumps({"type": "find", "q": "Adv", "zone": "moon"}))
                err = await recv_until(wa, "error", "find")
                assert err.get("type") == "error", err
                assert err.get("reason") == "invalid zone"

                await wa.send(json.dumps({"type": "find", "q": "  zone:town"}))
                f2 = await recv_until(wa, "find", "error")
                assert f2.get("type") == "find", f2
                assert int(f2.get("count") or 0) >= 2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_find_zone_filter_ws(tmp_path, monkeypatch):
    db_path = tmp_path / "fz.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "fa@ex.com", "Fa", "FindTown")
        tb, cb = register_char(base, "fb@ex.com", "Fb", "FindField")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
            ):
                for ws, tok, ch in ((wa, ta, ca), (wb, tb, cb)):
                    await ws.send(
                        json.dumps(
                            {"type": "auth", "token": tok, "character_id": ch["id"]}
                        )
                    )
                    await recv_until(ws, "auth_ok")
                    await drain(ws, 0.08)

                # Move Bob to field
                path = [(2, 3), (3, 3), (4, 3), (5, 3), (6, 3)]
                seq = 0
                for x, y in path:
                    seq += 1
                    await asyncio.sleep(0.12)
                    await wb.send(json.dumps({"type": "move", "x": x, "y": y, "seq": seq}))
                    m = await recv_until(wb, "move_ok", "error", "combat_start")
                    if m.get("type") == "combat_start":
                        for _ in range(8):
                            await wb.send(json.dumps({"type": "flee"}))
                            try:
                                mf = await recv_until(
                                    wb, "combat_end", "combat_update", "error", timeout=0.6
                                )
                                if mf.get("type") == "combat_end":
                                    break
                            except TimeoutError:
                                pass
                        await drain(wb, 0.1)
                        seq += 1
                        await wb.send(
                            json.dumps({"type": "move", "x": x, "y": y, "seq": seq})
                        )
                        await recv_until(wb, "move_ok", "error")

                await wb.send(json.dumps({"type": "sync"}))
                snap = await recv_until(wb, "world_state")
                # may still be town if path blocked; zone filter still works unit-side
                await drain(wa, 0.05)
                await wa.send(
                    json.dumps({"type": "find", "q": "Find", "zone": "town"})
                )
                f = await recv_until(wa, "find")
                assert f.get("type") == "find"
                for p in f.get("players") or []:
                    assert p.get("zone") == "town" or p.get("zone") is None
                # query suffix form
                await wa.send(json.dumps({"type": "find", "q": "Find zone:town"}))
                f2 = await recv_until(wa, "find")
                assert f2.get("type") == "find"

        asyncio.run(flow())
    finally:
        stop_server(server)
