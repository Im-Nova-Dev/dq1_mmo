"""v0.5.82 multiplayer reliability: AFK status message, afk_count, whisper AFK tip.

Also regresses soft reconnect, look, who, counts, and mark_active clear paths.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import (
    ConnectionManager,
    _online_card,
    _public_meta,
    sanitize_afk_message,
)
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
    m = await recv_until(ws, "auth_ok")
    await drain(ws, 0.1)
    return m


def test_sanitize_afk_message_unit():
    assert sanitize_afk_message(None) is None
    assert sanitize_afk_message("") is None
    assert sanitize_afk_message("  ") is None
    assert sanitize_afk_message("lunch") == "lunch"
    assert sanitize_afk_message("  brb soon  ") == "brb soon"
    long = "x" * 80
    assert sanitize_afk_message(long) == "x" * 48
    assert sanitize_afk_message("line\nbreak") == "linebreak" or "line" in (
        sanitize_afk_message("line\nbreak") or ""
    )


def test_afk_message_on_cards_and_clear_paths():
    mgr = ConnectionManager()

    class FakeWS:
        async def send_text(self, t):
            pass

        async def close(self, *a, **k):
            pass

    async def scenario():
        await mgr.connect(1, FakeWS(), name="Hero", x=2, y=2, map_id=0)
        assert mgr.afk_count() == 0
        assert mgr.set_afk(1, True, message="hunting")
        meta = mgr.get_meta(1)
        assert meta is not None
        assert meta.get("afk") is True
        assert meta.get("afk_message") == "hunting"
        assert mgr.afk_count() == 1

        card = _online_card(meta)
        pub = _public_meta(meta)
        assert card.get("afk_message") == "hunting"
        assert pub.get("afk_message") == "hunting"
        assert card.get("afk") is True

        # Updating reason keeps afk_since
        since = meta.get("afk_since")
        await asyncio.sleep(0.03)
        assert mgr.set_afk(1, True, message="dinner")
        meta2 = mgr.get_meta(1)
        assert meta2 is not None
        assert meta2.get("afk_message") == "dinner"
        assert meta2.get("afk_since") == since

        # mark_active clears message
        was = mgr.mark_active(1)
        assert was is True
        meta3 = mgr.get_meta(1)
        assert meta3 is not None
        assert meta3.get("afk") is False
        assert meta3.get("afk_message") is None
        assert mgr.afk_count() == 0

        # allow_chat clears
        mgr.set_afk(1, True, message="zzz")
        ok, _ = mgr.allow_chat(1)
        assert ok
        assert mgr.get_meta(1).get("afk_message") is None

        # allow_move clears
        mgr.set_afk(1, True, message="zzz")
        ok, _ = mgr.allow_move(1)
        assert ok
        assert mgr.get_meta(1).get("afk_message") is None

        # set_afk False clears
        mgr.set_afk(1, True, message="brb")
        mgr.set_afk(1, False)
        assert mgr.get_meta(1).get("afk_message") is None

    asyncio.run(scenario())


def test_afk_message_look_who_counts_whisper(tmp_path, monkeypatch):
    db_path = tmp_path / "afk_msg.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "a@ex.com", "Aa", "AfkMsg")
        tb, cb = register_char(base, "b@ex.com", "Bb", "Whisperer")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                # Set AFK with reason
                await wa.send(json.dumps({"type": "afk", "text": "lunch"}))
                ack = await recv_until(wa, "afk", "error")
                assert ack.get("type") == "afk" and ack.get("afk") is True, ack
                assert ack.get("afk_message") == "lunch", ack
                assert "lunch" in str(ack.get("message") or "")

                # Peer system notice may include reason
                notice = None
                end = time.monotonic() + 2.5
                while time.monotonic() < end and notice is None:
                    try:
                        m = json.loads(await asyncio.wait_for(wb.recv(), 0.4))
                    except (asyncio.TimeoutError, TimeoutError):
                        continue
                    if m.get("type") == "chat" and m.get("channel") == "system":
                        if "AFK" in str(m.get("text") or ""):
                            notice = m
                assert notice is not None, "peer should see AFK system notice"
                assert "lunch" in str(notice.get("text") or ""), notice

                await drain(wb, 0.15)
                await drain(wa, 0.05)

                # Look shows reason
                await wb.send(json.dumps({"type": "look", "name": "AfkMsg"}))
                look = await recv_until(wb, "look", "error")
                assert look.get("type") == "look", look
                player = look.get("player") or {}
                assert player.get("afk") is True, player
                assert player.get("afk_message") == "lunch", player

                # Who / counts include afk_count
                await wb.send(json.dumps({"type": "who"}))
                who = await recv_until(wb, "who", "error")
                assert who.get("type") == "who", who
                assert int(who.get("afk_count") or 0) >= 1, who
                roster = who.get("roster") or []
                hit = next((p for p in roster if p.get("name") == "AfkMsg"), None)
                assert hit is not None and hit.get("afk_message") == "lunch", roster

                await wb.send(json.dumps({"type": "counts"}))
                counts = await recv_until(wb, "counts", "error")
                assert counts.get("type") == "counts", counts
                assert int(counts.get("afk_count") or 0) >= 1, counts
                assert "AFK" in str(counts.get("message") or ""), counts

                # Whisper echo notes AFK reason
                await wb.send(
                    json.dumps(
                        {
                            "type": "whisper",
                            "to": "AfkMsg",
                            "text": "hey are you there",
                        }
                    )
                )
                echo = await recv_until(wb, "chat", "error")
                assert echo.get("type") == "chat" and echo.get("channel") == "whisper", echo
                assert echo.get("target_afk") is True, echo
                assert echo.get("target_afk_message") == "lunch", echo

                # Target receives whisper
                inc = await recv_until(wa, "chat", "error")
                assert inc.get("channel") == "whisper", inc
                assert "hey" in str(inc.get("text") or "")

                # /back clears message
                await wa.send(json.dumps({"type": "back"}))
                back = await recv_until(wa, "afk", "error")
                assert back.get("afk") is False, back
                assert "afk_message" not in back or back.get("afk_message") in (None, "")

                await drain(wb, 0.1)
                await wb.send(json.dumps({"type": "look", "name": "AfkMsg"}))
                look2 = await recv_until(wb, "look", "error")
                p2 = look2.get("player") or {}
                assert p2.get("afk") is False, p2
                assert not p2.get("afk_message"), p2

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_soft_reconnect_clears_afk_keeps_ignore(tmp_path, monkeypatch):
    """Regression: soft reconnect starts not-AFK; ignore list survives."""
    db_path = tmp_path / "soft_afk.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "s@ex.com", "Ss", "SoftHero")
        tb, cb = register_char(base, "t@ex.com", "Tt", "Ignored")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "ignore", "name": "Ignored"}))
                ig = await recv_until(wa, "ignore", "ignores", "error")
                assert ig.get("type") in ("ignore", "ignores"), ig

                await wa.send(json.dumps({"type": "afk", "text": "brb"}))
                await recv_until(wa, "afk")

            # Soft reconnect within grace
            async with websockets.connect(ws_url) as wa2:
                await auth(wa2, ta, ca["id"])
                await wa2.send(json.dumps({"type": "status"}))
                st = await recv_until(wa2, "status", "error")
                you = st.get("you") or {}
                assert you.get("afk") is False, you
                assert not you.get("afk_message"), you

                await wa2.send(json.dumps({"type": "ignores"}))
                igl = await recv_until(wa2, "ignores", "ignore", "error")
                names = []
                entries = igl.get("ignores") or igl.get("players") or []
                if isinstance(entries, list):
                    for e in entries:
                        if isinstance(e, dict):
                            names.append(e.get("name"))
                        else:
                            names.append(e)
                if igl.get("name"):
                    names.append(igl.get("name"))
                assert any(n == "Ignored" for n in names), igl

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_zone_chat_and_yell_still_work(tmp_path, monkeypatch):
    """Regression: old multiplayer zone chat / yell path."""
    db_path = tmp_path / "zone_reg.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "z1@ex.com", "Z1", "Yeller")
        tb, cb = register_char(base, "z2@ex.com", "Z2", "Listener")

        async def flow():
            import websockets

            async with websockets.connect(ws_url) as wa, websockets.connect(ws_url) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await drain(wa)
                await drain(wb)

                await wa.send(json.dumps({"type": "yell", "text": "hello zone"}))
                echo = await recv_until(wa, "chat", "error")
                assert echo.get("type") == "chat", echo
                assert echo.get("channel") in ("zone", "yell", "shout") or echo.get(
                    "channel"
                ) == "zone", echo
                assert "hello zone" in str(echo.get("text") or "")

                got = await recv_until(wb, "chat", "error")
                assert got.get("channel") == "zone", got
                assert "hello zone" in str(got.get("text") or "")

        asyncio.run(flow())
    finally:
        stop_server(server)
