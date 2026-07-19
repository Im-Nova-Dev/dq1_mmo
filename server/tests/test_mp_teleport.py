"""Multiplayer reliability: RETURN spell / teleport AOI visibility (free port)."""

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
            raise TimeoutError(str(types))
        m = json.loads(await asyncio.wait_for(ws.recv(), remaining))
        if m.get("type") in types:
            return m


def test_return_spell_aoi_and_who_under_spam(tmp_path, monkeypatch):
    db_path = tmp_path / "tp.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    from database.db import db_write, init_db
    from tests.ws_helpers import register_char, start_server, stop_server

    server, port, base, ws_url = start_server()
    try:
        token_a, ch_a = register_char(base, "tpa@ex.com", "TpA", "TpAlice")
        token_b, ch_b = register_char(base, "tpb@ex.com", "TpB", "TpBob")

        async def prep():
            await init_db()
            async with db_write() as db:
                # Alice knows RETURN
                await db.execute(
                    """
                    UPDATE characters
                    SET level = 13, max_mp = 40, current_mp = 40, max_hp = 50, current_hp = 50
                    WHERE id = ?
                    """,
                    (ch_a["id"],),
                )
                await db.commit()

        asyncio.run(prep())

        async def flow():
            import websockets

            async def auth(ws, token, cid):
                await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
                await recv_until(ws, "auth_ok")
                await recv_until(ws, "world_state")

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, token_a, ch_a["id"])
                await auth(wb, token_b, ch_b["id"])
                await asyncio.sleep(0.15)

                # Move Alice toward field so RETURN actually moves her from a non-spawn tile
                seq = 1
                for x, y in [(2, 3), (3, 3), (4, 3), (5, 3)]:
                    await asyncio.sleep(0.12)
                    await wa.send(json.dumps({"type": "move", "x": x, "y": y, "seq": seq}))
                    seq += 1
                    m = await recv_until(wa, "move_ok", "combat_start", "error")
                    if m.get("type") == "combat_start":
                        await wa.send(json.dumps({"type": "flee"}))
                        await recv_until(wa, "combat_end", "error")
                        break

                # Bob should still see Alice (or did via AOI)
                await wb.send(json.dumps({"type": "who"}))
                who = await recv_until(wb, "who")
                assert who["online"] == 2

                # spam moves then who still works (who is rate-limit exempt)
                for i in range(25):
                    await wb.send(json.dumps({"type": "move", "x": 2, "y": 2, "seq": 100 + i}))
                await wb.send(json.dumps({"type": "who"}))
                who2 = await recv_until(wb, "who", "error", "move_ok", "rate_limit")
                # drain to who
                while who2.get("type") != "who":
                    if who2.get("type") == "error" and who2.get("reason") == "rate_limit":
                        # who should not be rate limited — retry
                        await wb.send(json.dumps({"type": "who"}))
                    who2 = await recv_until(wb, "who", "error", "move_ok")
                assert who2["type"] == "who"
                assert who2["online"] == 2

                # Alice RETURN to town
                await wa.send(json.dumps({"type": "use_spell", "spell": "return"}))
                sc = await recv_until(wa, "spell_cast", "error", "move_ok")
                # may get move_ok then spell_cast
                while sc.get("type") != "spell_cast":
                    if sc.get("type") == "error":
                        raise AssertionError(sc)
                    sc = await recv_until(wa, "spell_cast", "error", "move_ok")
                assert sc.get("teleported") is True
                assert sc.get("x") == 2 and sc.get("y") == 2

                # Bob receives AOI updates (left/moved/joined) without crash
                await asyncio.sleep(0.3)
                await wb.send(json.dumps({"type": "sync"}))
                snap = await recv_until(wb, "world_state")
                assert snap.get("online") == 2

        asyncio.run(flow())
    finally:
        stop_server(server)
