"""Multiplayer integration: two clients, presence, chat, combat flag."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from main import app

PORT = 8766
BASE = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}/ws"


def _start_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(80):
        try:
            urllib.request.urlopen(f"{BASE}/health", timeout=0.2)
            return server
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("server did not start")


def req(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if data is None else json.dumps(data).encode()
    r = urllib.request.Request(f"{BASE}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


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


def register_char(email: str, username: str, char_name: str):
    st, reg = req(
        "POST",
        "/auth/register",
        {"email": email, "password": "password", "username": username},
    )
    assert st == 201, reg
    token = reg["access_token"]
    st, ch = req("POST", "/auth/characters", {"name": char_name}, token=token)
    assert st == 201, ch
    return token, ch


def test_two_players_presence_and_chat(tmp_path, monkeypatch):
    db_path = tmp_path / "mp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server = _start_server()
    try:
        token_a, ch_a = register_char("a@ex.com", "UserA", "Alice")
        token_b, ch_b = register_char("b@ex.com", "UserB", "Bob")

        async def flow():
            import websockets

            async with websockets.connect(WS) as wa, websockets.connect(WS) as wb:
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
                # Bob should see Alice in town (same spawn area)
                ids = {p["id"] for p in ws_b.get("players") or []}
                assert ch_a["id"] in ids, f"Bob should see Alice, got {ws_b.get('players')}"

                # Alice may get player_joined for Bob
                joined = await drain(wa, 0.4)
                assert any(
                    m.get("type") == "player_joined" and m.get("player_id") == ch_b["id"]
                    for m in joined
                ), joined

                # Chat global
                await wa.send(json.dumps({"type": "chat", "text": "  hello   party  "}))
                chat_a = await recv_until(wa, "chat")
                chat_b = await recv_until(wb, "chat")
                assert chat_a["text"] == "hello party"
                assert chat_b["text"] == "hello party"
                assert chat_b["name"] == "Alice"
                assert chat_b["channel"] == "global"

                # Empty chat rejected
                await wa.send(json.dumps({"type": "chat", "text": "   "}))
                err = await recv_until(wa, "error")
                assert err["reason"] == "empty chat"

                # Chat rate limit
                await asyncio.sleep(0.05)
                await wa.send(json.dumps({"type": "chat", "text": "spam"}))
                # first after rate window may fail if too soon from previous
                m = await recv_until(wa, "chat", "error")
                if m["type"] == "chat":
                    await wa.send(json.dumps({"type": "chat", "text": "spam2"}))
                    m2 = await recv_until(wa, "error", "chat")
                    assert m2["type"] == "error" and m2["reason"] == "chat_rate_limit"
                else:
                    assert m["reason"] == "chat_rate_limit"

                # Debug combat on Alice — Bob should get player_update in_combat
                await asyncio.sleep(0.8)  # clear chat rate window noise
                await drain(wb, 0.1)
                await wa.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 1})
                )
                await recv_until(wa, "combat_start")
                # Bob should see status update
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

                # Disconnect Bob — Alice gets player_left
                await drain(wa, 0.05)
                await wb.close()
                left = await recv_until(wa, "player_left")
                assert left["player_id"] == ch_b["id"]

                # Sync still works for Alice
                await wa.send(json.dumps({"type": "sync"}))
                snap = await recv_until(wa, "world_state")
                assert all(p["id"] != ch_b["id"] for p in snap.get("players") or [])

        asyncio.run(flow())
    finally:
        server.should_exit = True
        time.sleep(0.25)


def test_sanitize_chat_helper():
    from network.message_handler import sanitize_chat

    assert sanitize_chat("  a  b  ") == "a b"
    assert sanitize_chat("") is None
    assert sanitize_chat("\x00evil") == "evil"
    assert len(sanitize_chat("z" * 500)) == 200
