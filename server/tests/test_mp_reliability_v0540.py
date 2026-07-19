"""v0.5.40 multiplayer reliability: zone on presence, live zone chat, roster sort, /players."""

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
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic()))
            out.append(json.loads(raw))
        except (asyncio.TimeoutError, TimeoutError):
            break
    return out


async def auth(ws, token, cid):
    await ws.send(json.dumps({"type": "auth", "token": token, "character_id": cid}))
    await recv_until(ws, "auth_ok")
    await drain(ws, 0.12)


def test_ids_in_zone_skips_orphan_meta():
    """Zone chat must not target disconnected meta ghosts."""
    from network.websocket_manager import ConnectionManager

    mgr = ConnectionManager()
    # Two town metas, only A has a live "socket" marker
    mgr._meta[1] = {
        "id": 1,
        "name": "A",
        "x": 2.0,
        "y": 2.0,
        "map_id": 0,
        "level": 1,
        "visible": set(),
        "last_seen": time.monotonic(),
    }
    mgr._meta[2] = {
        "id": 2,
        "name": "Ghost",
        "x": 3.0,
        "y": 2.0,
        "map_id": 0,
        "level": 1,
        "visible": set(),
        "last_seen": time.monotonic(),
    }
    mgr._connections[1] = object()  # type: ignore
    # 2 is orphan meta only
    ids = mgr.ids_in_zone(1)
    assert 2 not in ids


def test_online_roster_sorted_stable():
    from network.websocket_manager import ConnectionManager

    mgr = ConnectionManager()
    now = time.monotonic()
    for cid, name in ((3, "Cara"), (1, "alice"), (2, "Bob")):
        mgr._meta[cid] = {
            "id": cid,
            "name": name,
            "x": 2.0,
            "y": 2.0,
            "map_id": 0,
            "level": 1,
            "visible": set(),
            "last_seen": now,
            "in_combat": False,
        }
        mgr._connections[cid] = object()  # type: ignore
    roster = mgr.online_roster()
    names = [p["name"] for p in roster]
    assert names == ["alice", "Bob", "Cara"], names
    assert all("zone" in p for p in roster)


def test_public_meta_includes_zone():
    from network.websocket_manager import _public_meta

    pub = _public_meta(
        {
            "id": 1,
            "name": "T",
            "x": 2.0,
            "y": 2.0,
            "map_id": 0,
            "level": 5,
            "in_combat": False,
            "last_seen": time.monotonic(),
        }
    )
    assert pub.get("zone") == "town"
    assert pub["idle"] is False


def test_player_moved_includes_zone(tmp_path, monkeypatch):
    db_path = tmp_path / "pmz.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "pm1@ex.com", "Pm1", "MoverA")
        tb, cb = register_char(base, "pm2@ex.com", "Pm2", "WatcherB")

        async def flow():
            import websockets
            import network.message_handler as mh

            orig = mh.roll_encounter
            mh.roll_encounter = lambda *a, **k: None  # type: ignore
            try:
                async with (
                    websockets.connect(ws_url) as wa,
                    websockets.connect(ws_url) as wb,
                ):
                    await auth(wa, ta, ca["id"])
                    await auth(wb, tb, cb["id"])
                    # Both spawn town; A steps east still town (3,2)
                    await asyncio.sleep(0.1)
                    await wa.send(json.dumps({"type": "move", "x": 3, "y": 2, "seq": 1}))
                    # Watcher should get player_moved with zone
                    deadline = time.monotonic() + 4.0
                    saw = None
                    while time.monotonic() < deadline:
                        try:
                            raw = await asyncio.wait_for(wb.recv(), 0.5)
                        except (asyncio.TimeoutError, TimeoutError):
                            continue
                        m = json.loads(raw)
                        if (
                            m.get("type") == "player_moved"
                            and m.get("player_id") == ca["id"]
                        ):
                            saw = m
                            break
                        if m.get("type") == "player_joined" and m.get("player_id") == ca["id"]:
                            # first join may fire instead if AOI was empty
                            assert m.get("zone") in (None, "town") or m.get("zone") == "town"
                    assert saw is not None, "watcher never got player_moved"
                    assert saw.get("zone") == "town", saw
                    assert "idle" in saw
            finally:
                mh.roll_encounter = orig

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_players_alias_and_who_you(tmp_path, monkeypatch):
    db_path = tmp_path / "pl.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        t, c = register_char(base, "pl@ex.com", "PlU", "PlayersHero")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as ws:
                await auth(ws, t, c["id"])
                for typ in ("players", "online_list", "who"):
                    await ws.send(json.dumps({"type": typ}))
                    who = await recv_until(ws, "who")
                    assert who.get("type") == "who"
                    assert "zones" in who
                    you = who.get("you") or {}
                    assert you.get("name") == "PlayersHero"
                    assert you.get("zone") == "town"
                    roster = who.get("roster") or []
                    assert any(p.get("name") == "PlayersHero" for p in roster)

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_three_player_zone_chat_and_ignore(tmp_path, monkeypatch):
    """Town zone chat reaches co-zoners; ignore blocks; field player does not hear."""
    db_path = tmp_path / "z3.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, port, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "z3a@ex.com", "Z3a", "TownA")
        tb, cb = register_char(base, "z3b@ex.com", "Z3b", "TownB")
        tc, cc = register_char(base, "z3c@ex.com", "Z3c", "FieldC")

        async def flow():
            import websockets
            import network.message_handler as mh

            orig = mh.roll_encounter
            mh.roll_encounter = lambda *a, **k: None  # type: ignore
            try:
                async with (
                    websockets.connect(ws_url) as wa,
                    websockets.connect(ws_url) as wb,
                    websockets.connect(ws_url) as wc,
                ):
                    await auth(wa, ta, ca["id"])
                    await auth(wb, tb, cb["id"])
                    await auth(wc, tc, cc["id"])

                    # Walk C to field (5,3)
                    seq = 0
                    for x, y in ((2, 3), (3, 3), (4, 3), (5, 3)):
                        seq += 1
                        await asyncio.sleep(0.09)
                        await wc.send(
                            json.dumps({"type": "move", "x": x, "y": y, "seq": seq})
                        )
                        await drain(wc, 0.08)

                    await wb.send(json.dumps({"type": "ignore", "name": "TownA"}))
                    await recv_until(wb, "ignore", "error")

                    await wa.send(
                        json.dumps(
                            {
                                "type": "chat",
                                "text": "town-hello-xyz",
                                "channel": "zone",
                            }
                        )
                    )
                    # A should get own echo
                    a_msgs = []
                    deadline = time.monotonic() + 2.0
                    while time.monotonic() < deadline:
                        try:
                            raw = await asyncio.wait_for(wa.recv(), 0.3)
                            a_msgs.append(json.loads(raw))
                            if any(
                                m.get("type") == "chat"
                                and "town-hello-xyz" in str(m.get("text"))
                                for m in a_msgs
                            ):
                                break
                        except (asyncio.TimeoutError, TimeoutError):
                            break
                    assert any(
                        m.get("type") == "chat" and "town-hello-xyz" in str(m.get("text"))
                        for m in a_msgs
                    ), a_msgs

                    # B ignored A — should NOT get zone chat
                    b_msgs = await drain(wb, 0.4)
                    assert not any(
                        m.get("type") == "chat" and "town-hello-xyz" in str(m.get("text"))
                        for m in b_msgs
                    ), b_msgs

                    # C in field — should NOT get town zone chat
                    c_msgs = await drain(wc, 0.4)
                    assert not any(
                        m.get("type") == "chat" and "town-hello-xyz" in str(m.get("text"))
                        for m in c_msgs
                    ), c_msgs
            finally:
                mh.roll_encounter = orig

        asyncio.run(flow())
    finally:
        stop_server(server)
