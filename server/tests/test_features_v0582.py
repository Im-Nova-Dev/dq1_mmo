"""v0.5.82 features: /afk reason, afk_count, clear keywords, long message clamp."""

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


def test_afk_reason_fields_and_clamp(tmp_path, monkeypatch):
    db_path = tmp_path / "feat_afk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "f@ex.com", "Ff", "FeatHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])

                long_reason = "R" * 60
                await ws.send(
                    json.dumps({"type": "afk", "reason": long_reason})
                )
                ack = await recv_until(ws, "afk", "error")
                assert ack.get("type") == "afk" and ack.get("afk") is True, ack
                msg = ack.get("afk_message") or ""
                assert len(msg) <= 48, msg
                assert msg.startswith("R"), msg

                await ws.send(json.dumps({"type": "buffs"}))
                buffs = await recv_until(ws, "buffs", "error")
                assert buffs.get("afk") is True, buffs
                assert buffs.get("afk_message") == msg, buffs
                assert msg in str(buffs.get("message") or "")

                await ws.send(json.dumps({"type": "status"}))
                st = await recv_until(ws, "status", "error")
                you = st.get("you") or {}
                assert you.get("afk") is True
                assert you.get("afk_message") == msg
                assert int(st.get("afk_count") or 0) >= 1

                # Update reason via message field
                await ws.send(json.dumps({"type": "away", "message": "biobreak"}))
                ack2 = await recv_until(ws, "afk", "error")
                assert ack2.get("afk_message") == "biobreak", ack2

                # Clear keyword
                await ws.send(json.dumps({"type": "afk", "text": "off"}))
                off = await recv_until(ws, "afk", "error")
                assert off.get("afk") is False, off

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_afk_unauth_and_help_hint(tmp_path, monkeypatch):
    db_path = tmp_path / "feat_afk2.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"type": "afk", "text": "nope"}))
                err = await recv_until(ws, "error", "afk")
                assert err.get("type") == "error", err
                assert "auth" in str(err.get("reason") or "").lower()

                # help still lists afk (after auth)
                ta, ca = register_char(base, "h@ex.com", "Hh", "HelpHero")
                await auth(ws, ta, ca["id"])
                await ws.send(json.dumps({"type": "help"}))
                h = await recv_until(ws, "help", "error")
                cmds = h.get("commands") or []
                afk_hint = next(
                    (c for c in cmds if isinstance(c, dict) and c.get("cmd") == "afk"),
                    None,
                )
                assert afk_hint is not None, cmds
                assert "reason" in str(afk_hint.get("hint") or "").lower() or "afk" in str(
                    afk_hint.get("hint") or ""
                ).lower()

        asyncio.run(flow())
    finally:
        stop_server(server)
