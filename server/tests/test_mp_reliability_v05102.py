"""v0.5.102 multiplayer reliability: invite supersede, soft-grace purge, dual /r peer."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager, RECONNECT_SOFT_GRACE


class FakeWS:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.fail = fail
        self.closed = False

    async def send_text(self, t):
        if self.fail:
            raise RuntimeError("socket dead")
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_second_invite_notifies_previous_inviter_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b, c = FakeWS(), FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await wm.manager.connect(3, c, name="C", x=4, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        a.sent.clear()
        wm.manager.refund_chat(3)
        await handle_message(3, 30, {"type": "invite", "to": "B"})
        assert wm.manager.last_invite_to(1)[0] is None
        supers = [m for m in a.sent if m.get("type") == "invite_superseded"]
        assert supers, a.sent
        assert "another" in str(supers[0].get("message") or "").lower()
        assert supers[0].get("to_id") == 2

    asyncio.run(scenario())


def test_retarget_invite_notifies_previous_guest_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b, c = FakeWS(), FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await wm.manager.connect(3, c, name="C", x=4, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        b.sent.clear()
        wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "invite", "to": "C"})
        assert wm.manager.last_invite_from(2)[0] is None
        cancels = [m for m in b.sent if m.get("type") == "invite_cancel"]
        assert cancels, b.sent
        assert cancels[0].get("reason") == "retarget"

    asyncio.run(scenario())


def test_invite_sets_whisper_peer_both_ways_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        assert wm.manager.last_whisper_from(1)[0] == 2
        assert wm.manager.last_whisper_from(2)[0] == 1
        # Guest can /r immediately after invite
        wm.manager.refund_chat(2)
        _c, _u, out, _ = await handle_message(2, 20, {"type": "reply", "text": "on my way"})
        assert any(m.get("channel") == "whisper" for m in out), out

    asyncio.run(scenario())


def test_purge_soft_grace_clears_peer_invite_pointers_unit():
    """Expired soft-grace bags must not leave zombie invite pointers on peers."""
    mgr = ConnectionManager()

    async def scenario():
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="B", x=3, y=2, map_id=0)
        mgr.note_invite_from(2, 1, "A")
        mgr.note_invite_to(1, 2, "B")
        await mgr.disconnect(1, a)
        # Force grace bag expired for inviter
        bag = mgr._soft_grace.get(1)
        assert bag is not None
        bag["expires"] = time.monotonic() - 1.0
        # Guest still online with last_invite_from A
        assert mgr.last_invite_from(2)[0] == 1
        n = mgr.purge_expired_soft_grace()
        assert n >= 1
        assert mgr.last_invite_from(2)[0] is None, "guest invite cleared when inviter grace expired"
        assert 1 not in mgr._soft_grace

    asyncio.run(scenario())


def test_dual_reconnect_accept_still_works_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        await wm.manager.disconnect(1, a)
        await wm.manager.disconnect(2, b)
        a2, b2 = FakeWS(), FakeWS()
        await wm.manager.connect(1, a2, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b2, name="B", x=3, y=2, map_id=0)
        assert wm.manager.last_invite_from(2)[0] == 1
        wm.manager.refund_chat(2)
        _c, _u, out, _ = await handle_message(2, 20, {"type": "accept"})
        assert any(m.get("type") == "invite_reply" for m in out), out

    asyncio.run(scenario())


def test_pending_and_thank_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "pending"})
        pend = next(m for m in out if m.get("type") == "pending")
        assert pend.get("has_outgoing") is True
        wm.manager.refund_chat(1)
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "thank", "to": "B"})
        assert any(m.get("type") == "thank" for m in out2), out2

    asyncio.run(scenario())
