"""v0.5.93 multiplayer: fighting peek, invite accept/decline, lastinvite, regressions."""

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


def test_fighting_peek_and_zone_combat(tmp_path, monkeypatch):
    db_path = tmp_path / "fight.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "f1@ex.com", "F1", "FightLook")
        tb, cb = register_char(base, "f2@ex.com", "F2", "Fighter")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "fighting"}))
                f0 = await recv_until(wa, "fighting", "error")
                assert f0.get("type") == "fighting", f0
                assert int(f0.get("nearby_combat") or 0) == 0
                assert f0.get("players") == [] or len(f0.get("players") or []) == 0

                await wb.send(
                    json.dumps({"type": "debug_encounter", "enemy": "slime", "seed": 11})
                )
                await recv_until(wb, "combat_start", "error")

                await wa.send(json.dumps({"type": "fighting"}))
                f1 = await recv_until(wa, "fighting", "error")
                assert int(f1.get("nearby_combat") or 0) >= 1, f1
                names = [p.get("name") for p in (f1.get("players") or [])]
                assert "Fighter" in names, names

                await wa.send(json.dumps({"type": "zone"}))
                z = await recv_until(wa, "zone", "error")
                assert "zone_combat" in z, z
                assert int(z.get("zone_combat") or 0) >= 1, z

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_invite_accept_decline_lastinvite(tmp_path, monkeypatch):
    db_path = tmp_path / "invacc.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "HostA")
        tb, cb = register_char(base, "b@ex.com", "Bb", "GuestB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                # No invite yet
                await wb.send(json.dumps({"type": "accept"}))
                e0 = await recv_until(wb, "error", "invite_reply")
                assert e0.get("type") == "error"
                assert "invite" in str(e0.get("reason") or "").lower()

                await wa.send(json.dumps({"type": "invite", "to": "GuestB"}))
                await recv_until(wa, "invite", "error")
                inv = await recv_until(wb, "invite", "error")
                assert inv.get("from") == "HostA"

                await wb.send(json.dumps({"type": "lastinvite"}))
                li = await recv_until(wb, "lastinvite", "error")
                assert li.get("type") == "lastinvite"
                assert (li.get("peer") or {}).get("name") == "HostA"
                assert (li.get("peer") or {}).get("online") is True

                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "accept"}))
                ok = await recv_until(wb, "invite_reply", "error")
                assert ok.get("type") == "invite_reply", ok
                assert ok.get("action") == "accept"
                peer = await recv_until(wa, "invite_reply", "error")
                assert peer.get("action") == "accept"
                assert "coming" in str(peer.get("message") or "").lower()

                # New invite then decline
                await asyncio.sleep(0.85)
                await wa.send(json.dumps({"type": "invite", "to": "GuestB"}))
                await recv_until(wa, "invite", "error")
                await recv_until(wb, "invite", "error")
                await asyncio.sleep(0.85)
                await wb.send(json.dumps({"type": "decline"}))
                d = await recv_until(wb, "invite_reply", "error")
                assert d.get("action") == "decline"
                dpeer = await recv_until(wa, "invite_reply", "error")
                assert dpeer.get("action") == "decline"

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_soft_lastinvite_and_whisper_regression(tmp_path, monkeypatch):
    db_path = tmp_path / "softinv.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s1@ex.com", "S1", "SoftA")
        tb, cb = register_char(base, "s2@ex.com", "S2", "SoftB")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "invite", "to": "SoftB"}))
                await recv_until(wa, "invite", "error")
                await recv_until(wb, "invite", "error")

                await wb.close()
                await asyncio.sleep(0.25)

                async with websockets.connect(ws_url) as wb2:
                    await auth(wb2, tb, cb["id"])
                    await drain(wb2, 0.15)
                    await wb2.send(json.dumps({"type": "lastinvite"}))
                    li = await recv_until(wb2, "lastinvite", "error")
                    assert (li.get("peer") or {}).get("name") == "SoftA", li

                    await asyncio.sleep(0.85)
                    await wb2.send(json.dumps({"type": "coming"}))
                    rep = await recv_until(wb2, "invite_reply", "error")
                    assert rep.get("type") == "invite_reply", rep
                    await recv_until(wa, "invite_reply", "error")

                    # Whisper still works after soft reconnect accept
                    await asyncio.sleep(0.85)
                    await wa.send(
                        json.dumps(
                            {"type": "whisper", "to": "SoftB", "text": "hi again"}
                        )
                    )
                    w = await recv_until(wa, "chat", "error")
                    assert w.get("type") == "chat", w
                    assert w.get("channel") == "whisper", w
                    await recv_until(wb2, "chat", "error")

        asyncio.run(flow())
    finally:
        stop_server(server)
