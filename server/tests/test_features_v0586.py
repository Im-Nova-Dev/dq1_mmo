"""v0.5.86: health/pong afk_count, stuck-home clears AFK, password change, sync census."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.ws_helpers import http_json, register_char, start_server, stop_server


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


def test_health_and_pong_include_afk_count(tmp_path, monkeypatch):
    db_path = tmp_path / "health_afk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "h@ex.com", "Hh", "HealthAfk")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wx:
                await wx.send(json.dumps({"type": "ping", "t": 9}))
                pong = await recv_until(wx, "pong", "error")
                assert pong.get("type") == "pong"
                assert "afk_count" in pong
                assert int(pong.get("afk_count") or 0) == 0

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "afk", "text": "ops"}))
                await recv_until(ws, "afk")

                st, h = http_json(base, "GET", "/health")
                assert st == 200, h
                assert h.get("status") == "ok"
                assert "afk_count" in h, h
                assert int(h.get("afk_count") or 0) >= 1, h
                assert "zones" in h and "online" in h

                await ws.send(json.dumps({"type": "ping", "t": 1}))
                pong2 = await recv_until(ws, "pong")
                assert int(pong2.get("afk_count") or 0) >= 1
                assert "nearby_afk" in pong2

                await ws.send(json.dumps({"type": "sync"}))
                ws_state = await recv_until(ws, "world_state", "error")
                assert ws_state.get("type") == "world_state"
                assert "afk_count" in ws_state and "nearby_afk" in ws_state
                you = ws_state.get("you") or {}
                assert you.get("afk") is True
                assert you.get("afk_message") == "ops"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_stuck_already_home_clears_afk(tmp_path, monkeypatch):
    db_path = tmp_path / "stuck_home.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s@ex.com", "Ss", "StuckHome")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "afk", "text": "afk-home"}))
                await recv_until(ws, "afk")
                await ws.send(json.dumps({"type": "stuck"}))
                stuck = await recv_until(ws, "stuck", "error")
                assert stuck.get("type") == "stuck", stuck
                assert stuck.get("teleported") is False, stuck
                assert stuck.get("afk") is False, stuck

                await ws.send(json.dumps({"type": "status"}))
                st = await recv_until(ws, "status")
                you = st.get("you") or {}
                assert you.get("afk") is False, you
                assert not you.get("afk_message"), you

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_password_change(tmp_path, monkeypatch):
    db_path = tmp_path / "pw.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, _ws = start_server()
    try:
        st, reg = http_json(
            base,
            "POST",
            "/auth/register",
            {"email": "pw@ex.com", "password": "oldpass1", "username": "PwUser"},
        )
        assert st == 201, reg
        token = reg["access_token"]

        st, body = http_json(
            base,
            "POST",
            "/auth/password",
            {"current_password": "wrong", "new_password": "newpass1"},
            token=token,
        )
        assert st == 401, body

        st, body = http_json(
            base,
            "POST",
            "/auth/password",
            {"current_password": "oldpass1", "new_password": "oldpass1"},
            token=token,
        )
        assert st == 400, body

        st, body = http_json(
            base,
            "POST",
            "/auth/password",
            {"current_password": "oldpass1", "new_password": "newpass9"},
            token=token,
        )
        assert st == 200, body
        assert body.get("ok") is True

        st, login = http_json(
            base,
            "POST",
            "/auth/login",
            {"email": "pw@ex.com", "password": "newpass9"},
        )
        assert st == 200, login
        assert "access_token" in login

        st, fail = http_json(
            base,
            "POST",
            "/auth/login",
            {"email": "pw@ex.com", "password": "oldpass1"},
        )
        assert st == 401, fail

        # unauth password change
        st, _ = http_json(
            base,
            "POST",
            "/auth/password",
            {"current_password": "x", "new_password": "yyyyyy"},
        )
        assert st == 401

    finally:
        stop_server(server)
