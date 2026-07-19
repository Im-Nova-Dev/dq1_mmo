"""v0.5.87 multiplayer: directed emotes, who nearby_afk, auth afk_count, regressions."""

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


def test_directed_emote_and_validation(tmp_path, monkeypatch):
    db_path = tmp_path / "emote_dir.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "EmoteA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "EmoteB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                # Self target rejected before rate
                await wa.send(json.dumps({"type": "emote", "emote": "wave", "to": "EmoteA"}))
                err = await recv_until(wa, "error", "emote")
                assert err.get("type") == "error", err
                assert "yourself" in str(err.get("reason") or "").lower(), err

                # Offline
                await wa.send(json.dumps({"type": "emote", "emote": "wave", "to": "Ghost"}))
                err2 = await recv_until(wa, "error", "emote")
                assert err2.get("type") == "error"
                assert "online" in str(err2.get("reason") or "").lower()

                # Directed success
                await wa.send(json.dumps({"type": "emote", "emote": "wave", "to": "EmoteB"}))
                em = await recv_until(wa, "emote", "error")
                assert em.get("type") == "emote", em
                assert em.get("to") == "EmoteB", em
                assert em.get("to_id") == cb["id"], em
                assert "EmoteB" in str(em.get("message") or ""), em

                # Peer receives
                peer = await recv_until(wb, "emote", "error")
                assert peer.get("type") == "emote"
                assert peer.get("to") == "EmoteB"
                assert "waves" in str(peer.get("message") or "").lower() or peer.get("emote") == "wave"

                # Failed directed does not clear AFK
                await wa.send(json.dumps({"type": "afk", "text": "hold"}))
                await recv_until(wa, "afk")
                await wa.send(json.dumps({"type": "emote", "emote": "wave", "to": "Nobody"}))
                await recv_until(wa, "error")
                await wa.send(json.dumps({"type": "status"}))
                st = await recv_until(wa, "status")
                assert (st.get("you") or {}).get("afk") is True

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_who_nearby_afk_and_auth_afk_count(tmp_path, monkeypatch):
    db_path = tmp_path / "who_afk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "w@ex.com", "Ww", "WhoA")
        tb, cb = register_char(base, "x@ex.com", "Xx", "WhoB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wb:
                await auth(wb, tb, cb["id"])
                await wb.send(json.dumps({"type": "afk", "text": "zzz"}))
                await recv_until(wb, "afk")

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
                    ok = await recv_until(wa, "auth_ok", "auth_fail")
                    assert ok.get("type") == "auth_ok", ok
                    assert "afk_count" in ok, ok
                    assert int(ok.get("afk_count") or 0) >= 1, ok
                    assert "AFK" in str(ok.get("welcome") or "") or int(
                        ok.get("afk_count") or 0
                    ) >= 1

                    await drain(wa, 0.15)
                    await wa.send(json.dumps({"type": "who"}))
                    who = await recv_until(wa, "who", "error")
                    assert who.get("type") == "who"
                    assert "nearby_afk" in who, who
                    assert int(who.get("afk_count") or 0) >= 1
                    assert int(who.get("nearby_afk") or 0) >= 1

                    await wa.send(json.dumps({"type": "motd"}))
                    motd = await recv_until(wa, "motd", "error")
                    assert "afk_count" in motd

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_whisper_zone_counts_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "reg_mp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "r1@ex.com", "R1", "RegA")
        tb, cb = register_char(base, "r2@ex.com", "R2", "RegB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(
                    json.dumps({"type": "whisper", "to": "RegB", "text": "hi reg"})
                )
                e = await recv_until(wa, "chat", "error")
                assert e.get("channel") == "whisper"
                await recv_until(wb, "chat", "error")

                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "yell", "text": "zone reg"}))
                y = await recv_until(wa, "chat", "error")
                assert y.get("channel") == "zone"
                await recv_until(wb, "chat", "error")

                await wa.send(json.dumps({"type": "counts"}))
                c = await recv_until(wa, "counts", "error")
                assert c.get("type") == "counts" and "afk_count" in c

                # invalid roll keeps AFK
                await wa.send(json.dumps({"type": "afk", "text": "x"}))
                await recv_until(wa, "afk")
                await wa.send(json.dumps({"type": "roll", "sides": 0}))
                err = await recv_until(wa, "error")
                assert err.get("reason") != "chat_rate_limit"
                await wa.send(json.dumps({"type": "status"}))
                st = await recv_until(wa, "status")
                assert (st.get("you") or {}).get("afk") is True

        asyncio.run(flow())
    finally:
        stop_server(server)
