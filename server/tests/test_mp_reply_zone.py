"""Multiplayer: server reply whisper, roster zone, move clears idle."""

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


def test_online_card_includes_zone_not_coords():
    mgr = ConnectionManager()

    async def scenario():
        await mgr.connect(1, FakeWS(), name="Townie", x=2, y=2, map_id=0)
        await mgr.connect(2, FakeWS(), name="Fielder", x=8, y=6, map_id=0)
        roster = mgr.online_roster()
        by_name = {r["name"]: r for r in roster}
        assert by_name["Townie"].get("zone") == "town"
        assert by_name["Fielder"].get("zone") == "field"
        # no radar
        assert "x" not in by_name["Townie"]
        assert "y" not in by_name["Townie"]
        hits = mgr.find_by_prefix("Town")
        assert hits and hits[0].get("zone") == "town"

    asyncio.run(scenario())


def test_allow_move_refreshes_last_seen_idle():
    mgr = ConnectionManager()

    async def scenario():
        await mgr.connect(1, FakeWS(), name="Walker", x=5, y=5, map_id=0)
        meta = mgr.get_meta(1)
        meta["last_seen"] = time.monotonic() - (IDLE_SOFT + 10)
        assert mgr.online_roster()[0]["idle"] is True
        ok, _ = mgr.allow_move(1)
        assert ok
        assert mgr.online_roster()[0]["idle"] is False

    asyncio.run(scenario())


def test_whisper_reply_server_side(tmp_path, monkeypatch):
    db_path = tmp_path / "reply.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ra@ex.com", "Ra", "ReplyAlice")
        tb, cb = register_char(base, "rb@ex.com", "Rb", "ReplyBob")

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
                    await drain(ws, 0.1)

                # Alice whispers Bob
                await wa.send(
                    json.dumps(
                        {
                            "type": "whisper",
                            "to": "ReplyBob",
                            "text": "hello bob",
                        }
                    )
                )
                # both get chat
                ca_msg = await recv_until(wa, "chat")
                assert ca_msg.get("channel") == "whisper"
                cb_msg = await recv_until(wb, "chat")
                assert "hello bob" in str(cb_msg.get("text"))

                await drain(wa, 0.05)
                await drain(wb, 0.05)

                # Bob replies via server type=reply (no name)
                await wb.send(json.dumps({"type": "reply", "text": "hi alice"}))
                # Alice should receive
                got = await recv_until(wa, "chat", "error")
                assert got.get("type") == "chat", got
                assert "hi alice" in str(got.get("text"))
                assert got.get("channel") == "whisper"

                # Empty reply with no history on fresh connection
                async with websockets.connect(ws_url) as wc:
                    tc, cc = register_char(base, "rc@ex.com", "Rc", "ReplyCarol")
                    await wc.send(
                        json.dumps(
                            {
                                "type": "auth",
                                "token": tc,
                                "character_id": cc["id"],
                            }
                        )
                    )
                    await recv_until(wc, "auth_ok")
                    await drain(wc, 0.05)
                    await wc.send(json.dumps({"type": "reply", "text": "nobody"}))
                    err = await recv_until(wc, "error")
                    assert err.get("reason") == "no one to reply to", err

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_reply_survives_soft_reconnect(tmp_path, monkeypatch):
    """last_whisper_from restored via soft grace after brief disconnect."""
    db_path = tmp_path / "reply2.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sa@ex.com", "Sa", "SoftAlice")
        tb, cb = register_char(base, "sb@ex.com", "Sb", "SoftBob")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wb:
                await wb.send(
                    json.dumps(
                        {"type": "auth", "token": tb, "character_id": cb["id"]}
                    )
                )
                await recv_until(wb, "auth_ok")
                await drain(wb, 0.1)

                async with websockets.connect(ws_url) as wa:
                    await wa.send(
                        json.dumps(
                            {
                                "type": "auth",
                                "token": ta,
                                "character_id": ca["id"],
                            }
                        )
                    )
                    await recv_until(wa, "auth_ok")
                    await drain(wa, 0.1)
                    await wa.send(
                        json.dumps(
                            {
                                "type": "whisper",
                                "to": "SoftBob",
                                "text": "ping",
                            }
                        )
                    )
                    await recv_until(wb, "chat")
                    await drain(wa, 0.05)
                # Alice disconnects; Bob still online
                await asyncio.sleep(0.05)

                # Alice reconnects and should still be able to reply if Bob whispered...
                # Bob replies first so Alice's last_whisper is Bob after reconnect
                # Actually after Alice disconnect, her soft grace has last_whisper_from=Bob
                async with websockets.connect(ws_url) as wa2:
                    await wa2.send(
                        json.dumps(
                            {
                                "type": "auth",
                                "token": ta,
                                "character_id": ca["id"],
                            }
                        )
                    )
                    await recv_until(wa2, "auth_ok")
                    await drain(wa2, 0.1)
                    await wa2.send(
                        json.dumps({"type": "reply", "text": "still there?"})
                    )
                    got = await recv_until(wb, "chat", "error")
                    assert got.get("type") == "chat", got
                    assert "still there" in str(got.get("text"))

        asyncio.run(flow())
    finally:
        stop_server(server)
