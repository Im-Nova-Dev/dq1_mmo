"""Multiplayer reliability: nearby chat, emotes, ping under load, free-port only."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import MSG_RATE_MAX, ConnectionManager
from tests.ws_helpers import http_json, register_char, start_server, stop_server


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


def test_ping_exempt_from_msg_rate_limit():
    """Flooding non-ping messages must not block heartbeats (unit-level policy)."""
    assert MSG_RATE_MAX >= 10
    mgr = ConnectionManager()

    class WS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, WS(), name="A", x=2, y=2, map_id=1)
        blocked = False
        for _ in range(MSG_RATE_MAX + 5):
            if not mgr.allow_message(1):
                blocked = True
                break
        assert blocked
        mgr.touch(1)
        assert mgr.get_meta(1) is not None

    asyncio.run(scenario())


def test_nearby_chat_and_emote(tmp_path, monkeypatch):
    db_path = tmp_path / "mp2.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "na@ex.com", "NearA", "NearAlice")
        token_b, ch_b = register_char(base, "nb@ex.com", "NearB", "NearBob")
        token_c, ch_c = register_char(base, "nc@ex.com", "NearC", "NearCarol")

        async def flow():
            import websockets

            async with (
                websockets.connect(ws_url) as wa,
                websockets.connect(ws_url) as wb,
                websockets.connect(ws_url) as wc,
            ):
                for ws, tok, ch in (
                    (wa, token_a, ch_a),
                    (wb, token_b, ch_b),
                    (wc, token_c, ch_c),
                ):
                    await ws.send(
                        json.dumps(
                            {"type": "auth", "token": tok, "character_id": ch["id"]}
                        )
                    )
                    await recv_until(ws, "auth_ok")
                    await recv_until(ws, "world_state")

                await drain(wa, 0.2)
                await drain(wb, 0.2)
                await drain(wc, 0.2)

                await wa.send(json.dumps({"type": "say", "text": "hi neighbors"}))
                ca = await recv_until(wa, "chat")
                cb = await recv_until(wb, "chat")
                cc = await recv_until(wc, "chat")
                assert ca["channel"] == "nearby"
                assert cb["text"] == "hi neighbors"
                assert cc["name"] == "NearAlice"

                await asyncio.sleep(0.8)
                await drain(wa, 0.05)
                await drain(wb, 0.05)
                await drain(wc, 0.05)

                await wb.send(json.dumps({"type": "emote", "emote": "wave"}))
                ea = await recv_until(wa, "emote")
                eb = await recv_until(wb, "emote")
                assert ea["emote"] == "wave"
                assert ea["name"] == "NearBob"
                assert eb["player_id"] == ch_b["id"]

                await asyncio.sleep(0.8)
                await wc.send(
                    json.dumps(
                        {"type": "chat", "text": "server wide", "channel": "global"}
                    )
                )
                ga = await recv_until(wa, "chat")
                assert ga["channel"] == "global"
                assert ga["text"] == "server wide"

                await wa.send(json.dumps({"type": "sync"}))
                snap = await recv_until(wa, "world_state")
                assert snap.get("online") == 3

                st, health = http_json(base, "GET", "/health")
                assert st == 200
                assert health["online"] == 3

                meta_path = [
                    (3, 2),
                    (4, 2),
                    (5, 2),
                    (6, 2),
                    (7, 2),
                    (8, 2),
                    (9, 2),
                    (10, 2),
                    (11, 2),
                    (12, 2),
                    (13, 2),
                ]
                for i, (x, y) in enumerate(meta_path, start=1):
                    await wb.send(json.dumps({"type": "move", "x": x, "y": y, "seq": i}))
                    await recv_until(wb, "move_ok", "combat_start", "error")
                    await asyncio.sleep(0.11)

                await drain(wa, 0.3)
                await drain(wb, 0.3)
                await drain(wc, 0.3)
                await asyncio.sleep(0.9)
                await wa.send(json.dumps({"type": "say", "text": "secret local"}))

                async def wait_chat_text(ws, text, timeout=4.0):
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        m = await recv_until(
                            ws, "chat", timeout=max(0.2, deadline - time.monotonic())
                        )
                        if m.get("text") == text:
                            return m
                    raise TimeoutError(text)

                ca2 = await wait_chat_text(wa, "secret local")
                assert ca2["channel"] == "nearby"
                cc2 = await wait_chat_text(wc, "secret local")
                assert cc2["channel"] == "nearby"

                for _ in range(5):
                    await wa.send(json.dumps({"type": "move", "x": 2, "y": 2, "seq": 900}))
                await wa.send(json.dumps({"type": "ping", "t": 42.5}))
                pong = await recv_until(wa, "pong", "error", "move_ok")
                if pong.get("type") != "pong":
                    pong = await recv_until(wa, "pong")
                assert pong.get("t") == 42.5

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_empty_emote_rejected(tmp_path, monkeypatch):
    """Empty string must not silently become wave."""
    db_path = tmp_path / "mp_em.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())
    server, _port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "em2@ex.com", "EmU2", "EmHero2")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps({"type": "auth", "token": token, "character_id": ch["id"]})
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                await ws.send(json.dumps({"type": "emote", "emote": ""}))
                err = await recv_until(ws, "error")
                assert err["reason"] == "bad emote"
                await asyncio.sleep(0.8)
                await ws.send(json.dumps({"type": "emote", "emote": "   "}))
                err2 = await recv_until(ws, "error")
                assert err2["reason"] == "bad emote"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_unknown_emote_rejected(tmp_path, monkeypatch):
    db_path = tmp_path / "mp3.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())
    server, _port, base, ws_url = start_server()
    try:
        token, ch = register_char(base, "em@ex.com", "EmU", "EmHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(
                    json.dumps({"type": "auth", "token": token, "character_id": ch["id"]})
                )
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")
                await ws.send(json.dumps({"type": "emote", "emote": "floss"}))
                err = await recv_until(ws, "error")
                assert err["reason"] == "unknown emote"

        asyncio.run(flow())
    finally:
        stop_server(server)
