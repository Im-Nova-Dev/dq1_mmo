"""v0.5.103 adversarial: ignore-respecting cancel/retarget; hunt regressions."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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


def test_cancel_does_not_notify_ignorer_unit():
    """Guest who ignores inviter must not receive invite_cancel toast."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        assert wm.manager.last_invite_from(2)[0] == 1
        wm.manager.ignore_player(2, 1)
        b.sent.clear()
        wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "cancel"})
        cancels = [m for m in out if m.get("type") == "invite_cancel"]
        assert cancels, out
        # Echo to inviter may say not notified (muted)
        assert cancels[0].get("notified") is False, cancels[0]
        peer_cancels = [m for m in b.sent if m.get("type") == "invite_cancel"]
        assert not peer_cancels, f"ignorer got cancel: {peer_cancels}"
        assert wm.manager.last_invite_from(2)[0] is None
        assert wm.manager.last_invite_to(1)[0] is None

    asyncio.run(scenario())


def test_retarget_does_not_notify_ignorer_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b, c = FakeWS(), FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await wm.manager.connect(3, c, name="C", x=4, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        wm.manager.ignore_player(2, 1)
        b.sent.clear()
        wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "invite", "to": "C"})
        peer_cancels = [m for m in b.sent if m.get("type") == "invite_cancel"]
        assert not peer_cancels, peer_cancels
        assert wm.manager.last_invite_from(2)[0] is None
        assert wm.manager.last_invite_to(1)[0] == 3

    asyncio.run(scenario())


def test_cancel_still_notifies_when_not_ignored_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        b.sent.clear()
        wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "cancel"})
        echo = next(m for m in out if m.get("type") == "invite_cancel")
        assert echo.get("notified") is True
        peer = [m for m in b.sent if m.get("type") == "invite_cancel"]
        assert peer, b.sent

    asyncio.run(scenario())


def test_supersede_offline_prev_clears_soft_grace_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b, c = FakeWS(), FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await wm.manager.connect(3, c, name="C", x=4, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        await wm.manager.disconnect(1, a)
        assert (wm.manager._soft_grace.get(1) or {}).get("last_invite_to_id") == 2
        wm.manager.refund_chat(3)
        await handle_message(3, 30, {"type": "invite", "to": "B"})
        bag = wm.manager._soft_grace.get(1) or {}
        assert bag.get("last_invite_to_id") is None
        assert wm.manager.last_invite_from(2)[0] == 3

    asyncio.run(scenario())


def test_purge_and_pending_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        await wm.manager.disconnect(1, a)
        bag = wm.manager._soft_grace.get(1)
        assert bag
        bag["expires"] = time.monotonic() - 1
        wm.manager.purge_expired_soft_grace()
        assert wm.manager.last_invite_from(2)[0] is None
        _c, _u, out, _ = await handle_message(2, 20, {"type": "pending"})
        pend = next(m for m in out if m.get("type") == "pending")
        assert pend.get("has_incoming") is False

    asyncio.run(scenario())


def test_triple_invite_only_last_outgoing_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        socks = [FakeWS() for _ in range(4)]
        for i, ws in enumerate(socks, 1):
            await wm.manager.connect(i, ws, name=f"P{i}", x=float(i), y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "P2"})
        for inv in (3, 4):
            wm.manager.refund_chat(inv)
            await handle_message(inv, inv * 10, {"type": "invite", "to": "P2"})
        assert wm.manager.last_invite_from(2)[0] == 4
        assert wm.manager.last_invite_to(1)[0] is None
        assert wm.manager.last_invite_to(3)[0] is None
        assert wm.manager.last_invite_to(4)[0] == 2

    asyncio.run(scenario())
