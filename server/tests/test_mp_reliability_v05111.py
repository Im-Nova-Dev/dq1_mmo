"""v0.5.111 multiplayer: accept zone on invite_reply, r alias, lastemote badges."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_accept_includes_zone_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        for _ in range(2):
            wm.manager.refund_chat(2)
        _c, _u, out, _ = await handle_message(2, 20, {"type": "accept"})
        rep = next(m for m in out if m.get("type") == "invite_reply")
        assert rep.get("action") == "accept", rep
        assert rep.get("zone") == "field", rep
        assert "field" in str(rep.get("message") or ""), rep
        got = [m for m in a.sent if m.get("type") == "invite_reply"]
        assert got and got[-1].get("zone") == "field", got
        assert "field" in str(got[-1].get("message") or "")
        # nearby flag always set
        assert "nearby" in rep, rep
        # (2,2)/(5,5) is AOI-near (range 10) — coords allowed
        assert rep.get("nearby") is True, rep
        assert "x" in rep and "y" in rep, rep

    asyncio.run(scenario())


def test_accept_far_omits_coords_unit():
    """Privacy: zone always; x/y only when AOI-near (Chebyshev > VISIBILITY_RANGE)."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        # town (1,1) vs field (12,1) — chebyshev 11 > range 10
        await wm.manager.connect(1, a, name="A", x=1, y=1, map_id=0)
        await wm.manager.connect(2, b, name="B", x=12, y=1, map_id=0)
        assert 2 not in wm.manager.ids_nearby(1)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        for _ in range(2):
            wm.manager.refund_chat(2)
        _c, _u, out, _ = await handle_message(2, 20, {"type": "accept"})
        rep = next(m for m in out if m.get("type") == "invite_reply")
        assert rep.get("action") == "accept", rep
        assert rep.get("zone") in ("town", "field", "dungeon"), rep
        assert rep.get("nearby") is False, rep
        assert "x" not in rep and "y" not in rep, rep
        got = [m for m in a.sent if m.get("type") == "invite_reply"]
        assert got and got[-1].get("nearby") is False, got
        assert "x" not in got[-1] and "y" not in got[-1], got[-1]

    asyncio.run(scenario())


def test_decline_includes_zone_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        for _ in range(2):
            wm.manager.refund_chat(2)
        _c, _u, out, _ = await handle_message(2, 20, {"type": "decline"})
        rep = next(m for m in out if m.get("type") == "invite_reply")
        assert rep.get("action") == "decline", rep
        assert rep.get("zone") == "field", rep
        got = [m for m in a.sent if m.get("type") == "invite_reply"]
        assert got and got[-1].get("zone") == "field"

    asyncio.run(scenario())


def test_r_alias_replies_last_whisper_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(3):
            wm.manager.refund_chat(1)
            wm.manager.refund_chat(2)
        await handle_message(1, 10, {"type": "whisper", "to": "B", "text": "hi"})
        for _ in range(2):
            wm.manager.refund_chat(2)
        _c, _u, out, _ = await handle_message(2, 20, {"type": "r", "text": "yo"})
        assert any(m.get("channel") == "whisper" for m in out), out
        # empty r should fail cleanly
        for _ in range(2):
            wm.manager.refund_chat(2)
        _c, _u, out2, _ = await handle_message(2, 20, {"type": "r", "text": ""})
        errs = [m for m in out2 if m.get("type") == "error"]
        assert errs, out2

    asyncio.run(scenario())


def test_lastemote_zone_badges_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "wave", "to": "B"})
        wm.manager.set_afk(2, True)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "lastemote"})
        le = next(m for m in out if m.get("type") == "lastemote")
        peer = le.get("peer") or {}
        assert peer.get("name") == "B", le
        assert peer.get("zone") == "field", peer
        assert peer.get("afk") is True, peer
        msg = str(le.get("message") or "")
        assert "field" in msg and "afk" in msg.lower(), msg

    asyncio.run(scenario())


def test_invite_still_has_zone_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "invite", "to": "B"})
        inv = next(m for m in out if m.get("type") == "invite")
        assert inv.get("zone") == "town", inv
        peer = [m for m in b.sent if m.get("type") == "invite"]
        assert peer and peer[-1].get("zone") == "town"

    asyncio.run(scenario())


def test_multi_token_find_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "find", "query": "zone:town zone:field"}
        )
        f = next(m for m in out if m.get("type") == "find")
        assert f.get("zone") == "field" and int(f.get("count") or 0) >= 1, f

    asyncio.run(scenario())
