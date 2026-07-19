"""v0.5.114: lastshare soft-grace, cancel notify honesty, session extract."""

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


class DeadWS(FakeWS):
    async def send_text(self, t):
        raise ConnectionError("gone")


def test_lastshare_and_soft_grace_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "share", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "lastshare"})
        ls = next(m for m in out if m.get("type") == "lastshare")
        peer = ls.get("peer") or {}
        assert peer.get("name") == "B", ls
        assert peer.get("nearby") is True, peer
        assert "near" in str(ls.get("message") or "").lower()

        # Soft grace survives disconnect
        await wm.manager.disconnect(1, a)
        c = FakeWS()
        await wm.manager.connect(1, c, name="A", x=2, y=2, map_id=0)
        lid, lname = wm.manager.last_share_to(1)
        assert lid == 2 and lname == "B", (lid, lname)

    asyncio.run(scenario())


def test_cancel_notified_false_on_dead_socket_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), DeadWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        # re-attach dead socket if invite disconnects B
        if 2 not in wm.manager.online_ids():
            await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
            # restore invite pointer on B
            wm.manager.note_invite_from(2, 1, "A")
            wm.manager.note_invite_to(1, 2, "B")
        for _ in range(2):
            wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "cancel"})
        cancel = next(m for m in out if m.get("type") == "invite_cancel")
        assert cancel.get("action") == "cancel"
        # Must not claim notified when send failed
        assert cancel.get("notified") is False, cancel
        assert "nearby" in cancel, cancel

    asyncio.run(scenario())


def test_cancel_notified_true_live_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        for _ in range(2):
            wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "cancel"})
        cancel = next(m for m in out if m.get("type") == "invite_cancel")
        assert cancel.get("notified") is True, cancel
        assert cancel.get("nearby") is True, cancel
        got = [m for m in b.sent if m.get("type") == "invite_cancel"]
        assert got, b.sent

    asyncio.run(scenario())


def test_session_ping_sync_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "ping", "t": 42})
        pong = next(m for m in out if m.get("type") == "pong")
        assert pong.get("t") == 42
        assert "online" in pong and "afk_count" in pong
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "sync"})
        ws = next(m for m in out2 if m.get("type") == "world_state")
        assert "players" in ws and "you" in ws

    asyncio.run(scenario())


def test_social_includes_share_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "share", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "social"})
        soc = next(m for m in out if m.get("type") == "social")
        share = soc.get("share") or {}
        assert share.get("name") == "B", soc
        assert "share" in str(soc.get("message") or "").lower()

    asyncio.run(scenario())
