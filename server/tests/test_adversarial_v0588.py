"""v0.5.88 adversarial: directed emote ignore privacy, failed paths, regressions."""

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
    out = []
    while time.monotonic() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
            out.append(json.loads(raw))
        except (asyncio.TimeoutError, TimeoutError):
            break
    return out


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.1)
    return m


def test_directed_emote_respects_ignore_both_ways(tmp_path, monkeypatch):
    db_path = tmp_path / "emote_ig.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "WaveA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "WaveB")

        async def flow():
            import websockets
            from database.db import db_write
            from game.world_manager import SPAWN_X, SPAWN_Y

            # Place B far so delivery would use direct send (not only AOI)
            async with db_write() as db:
                await db.execute(
                    "UPDATE characters SET world_x = ?, world_y = ? WHERE id = ?",
                    (40, 40, cb["id"]),
                )
                await db.commit()

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                # Confirm B is not nearby (if still nearby, force meta via moves)
                await wa.send(json.dumps({"type": "near"}))
                near = await recv_until(wa, "near", "error")
                near_names = [
                    p.get("name") for p in (near.get("players") or []) if isinstance(p, dict)
                ]

                # B ignores A → directed fails privacy (like whisper)
                await wb.send(json.dumps({"type": "ignore", "name": "WaveA"}))
                await recv_until(wb, "ignore", "ignores", "error")
                await drain(wb, 0.1)

                await wa.send(json.dumps({"type": "emote", "emote": "wave", "to": "WaveB"}))
                err = await recv_until(wa, "error", "emote")
                assert err.get("type") == "error", err
                assert "unavailable" in str(err.get("reason") or "").lower(), err

                # A should not get a successful emote; B should not get emote
                msgs = await drain(wb, 0.4)
                assert not any(m.get("type") == "emote" for m in msgs), msgs

                # Unignore, then A ignores B
                await wb.send(json.dumps({"type": "unignore", "name": "WaveA"}))
                await recv_until(wb, "ignore", "ignores", "unignore", "error")
                await wa.send(json.dumps({"type": "ignore", "name": "WaveB"}))
                await recv_until(wa, "ignore", "ignores", "error")

                await wa.send(json.dumps({"type": "emote", "emote": "wave", "to": "WaveB"}))
                err2 = await recv_until(wa, "error", "emote")
                assert err2.get("type") == "error", err2
                assert "ignore" in str(err2.get("reason") or "").lower(), err2

                # Failed directed does not clear AFK
                await wa.send(json.dumps({"type": "unignore", "name": "WaveB"}))
                await recv_until(wa, "ignore", "ignores", "unignore", "error")
                await wa.send(json.dumps({"type": "afk", "text": "wait"}))
                await recv_until(wa, "afk")
                await wa.send(json.dumps({"type": "emote", "emote": "wave", "to": "Nobody"}))
                await recv_until(wa, "error")
                await wa.send(json.dumps({"type": "status"}))
                st = await recv_until(wa, "status")
                assert (st.get("you") or {}).get("afk") is True

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_directed_far_delivers_when_not_ignored(tmp_path, monkeypatch):
    db_path = tmp_path / "emote_far.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "f@ex.com", "Ff", "FarFrom")
        tb, cb = register_char(base, "g@ex.com", "Gg", "FarTo")

        async def flow():
            import websockets
            from database.db import db_write

            async with db_write() as db:
                await db.execute(
                    "UPDATE characters SET world_x = 40, world_y = 40 WHERE id = ?",
                    (cb["id"],),
                )
                await db.commit()

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "emote", "emote": "bow", "to": "FarTo"}))
                em = await recv_until(wa, "emote", "error")
                assert em.get("type") == "emote", em
                assert em.get("to") == "FarTo", em

                peer = await recv_until(wb, "emote", "error")
                assert peer.get("type") == "emote", peer
                assert "bow" in str(peer.get("message") or "").lower() or peer.get("emote") == "bow"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_adversarial_matrix_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "adv_mat.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "m@ex.com", "Mm", "Matrix")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, ta, ca["id"])

                await ws.send(json.dumps({"type": "roll", "sides": True}))
                r = await recv_until(ws, "error", "chat")
                assert r.get("type") == "error" and "sides" in str(r.get("reason") or "")

                await ws.send(json.dumps({"type": "chat", "text": "   "}))
                r = await recv_until(ws, "error", "chat")
                assert r.get("type") == "error"

                await ws.send(json.dumps({"type": "move", "x": 99, "y": 99, "seq": 1}))
                r = await recv_until(ws, "error", "move_ok")
                assert r.get("type") == "error" or r.get("ok") is False

                st, h = http_json(base, "GET", "/health")
                assert st == 200 and "afk_count" in h

                # invalid directed does not burn then block real emote
                await ws.send(json.dumps({"type": "emote", "emote": "wave", "to": "Ghost"}))
                await recv_until(ws, "error")
                await ws.send(json.dumps({"type": "emote", "emote": "wave"}))
                em = await recv_until(ws, "emote", "error")
                assert em.get("type") == "emote", em

        asyncio.run(flow())
    finally:
        stop_server(server)
