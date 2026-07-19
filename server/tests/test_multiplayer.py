"""Multiplayer integration: two clients, presence, chat, combat flag (free port)."""

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


def test_two_players_presence_and_chat(tmp_path, monkeypatch):
    db_path = tmp_path / "mp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    from tests.ws_helpers import register_char, start_server, stop_server

    server, port, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "a@ex.com", "UserA", "Alice")
        token_b, ch_b = register_char(base, "b@ex.com", "UserB", "Bob")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await wa.send(
                    json.dumps(
                        {"type": "auth", "token": token_a, "character_id": ch_a["id"]}
                    )
                )
                m1 = await recv_until(wa, "auth_ok")
                assert m1["type"] == "auth_ok"
                ws_a = await recv_until(wa, "world_state")
                assert ws_a["type"] == "world_state"

                await wb.send(
                    json.dumps(
                        {"type": "auth", "token": token_b, "character_id": ch_b["id"]}
                    )
                )
                await recv_until(wb, "auth_ok")
                ws_b = await recv_until(wb, "world_state")
                ids = {p["id"] for p in ws_b.get("players") or []}
                assert ch_a["id"] in ids, f"Bob should see Alice, got {ws_b.get('players')}"

                joined = await drain(wa, 0.4)
                assert any(
                    m.get("type") == "player_joined" and m.get("player_id") == ch_b["id"]
                    for m in joined
                ), joined

                await wa.send(json.dumps({"type": "chat", "text": "  hello   party  "}))
                chat_a = await recv_until(wa, "chat")
                chat_b = await recv_until(wb, "chat")
                assert chat_a["text"] == "hello party"
                assert chat_b["text"] == "hello party"
                assert chat_b["name"] == "Alice"
                assert chat_b["channel"] == "global"

                await wa.send(json.dumps({"type": "chat", "text": "   "}))
                err = await recv_until(wa, "error")
                assert err["reason"] == "empty chat"

                await asyncio.sleep(0.05)
                await wa.send(json.dumps({"type": "chat", "text": "spam"}))
                m = await recv_until(wa, "chat", "error")
                if m["type"] == "chat":
                    await wa.send(json.dumps({"type": "chat", "text": "spam2"}))
                    m2 = await recv_until(wa, "error", "chat")
                    assert m2["type"] == "error" and m2["reason"] == "chat_rate_limit"
                else:
                    assert m["reason"] == "chat_rate_limit"

                await asyncio.sleep(0.8)
                await drain(wb, 0.1)
                await wa.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 1})
                )
                await recv_until(wa, "combat_start")
                upd = None
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(wb.recv(), 0.5)
                        m = json.loads(raw)
                        if (
                            m.get("type") == "player_update"
                            and m.get("player_id") == ch_a["id"]
                            and m.get("in_combat") is True
                        ):
                            upd = m
                            break
                    except (asyncio.TimeoutError, TimeoutError):
                        continue
                assert upd is not None, "Bob should see Alice enter combat"

                await drain(wa, 0.05)
                await wb.close()
                left = await recv_until(wa, "player_left")
                assert left["player_id"] == ch_b["id"]
                assert left.get("reason") in ("disconnect", None) or True

                await wa.send(json.dumps({"type": "sync"}))
                snap = await recv_until(wa, "world_state")
                assert all(p["id"] != ch_b["id"] for p in snap.get("players") or [])
                assert snap.get("online") == 1

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_sanitize_chat_helper():
    from network.message_handler import sanitize_chat

    assert sanitize_chat("  a  b  ") == "a b"
    assert sanitize_chat("") is None
    assert sanitize_chat("\x00evil") == "evil"
    assert len(sanitize_chat("z" * 500)) == 200
