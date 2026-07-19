"""v0.5.101 multiplayer: double-invite clears previous inviter pointer."""

from __future__ import annotations

import asyncio
import json
import sys
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


def test_second_invite_clears_previous_inviter_outgoing_unit():
    """When C invites B while A still pending, A must lose last_invite_to."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b, c = FakeWS(), FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await wm.manager.connect(3, c, name="C", x=4, y=2, map_id=0)

        _c, _u, out, _ = await handle_message(1, 10, {"type": "invite", "to": "B"})
        assert any(m.get("type") == "invite" for m in out), out
        assert wm.manager.last_invite_to(1)[0] == 2
        assert wm.manager.last_invite_from(2)[0] == 1

        wm.manager.refund_chat(3)
        _c, _u, out2, _ = await handle_message(3, 30, {"type": "invite", "to": "B"})
        assert any(m.get("type") == "invite" for m in out2), out2
        assert wm.manager.last_invite_from(2)[0] == 3
        assert wm.manager.last_invite_to(3)[0] == 2
        # A no longer has a live pending invite to B
        assert wm.manager.last_invite_to(1)[0] is None, (
            "previous inviter must not keep zombie last_invite_to"
        )

        # A cancel → no invite
        wm.manager.refund_chat(1)
        _c, _u, out_c, _ = await handle_message(1, 10, {"type": "cancel"})
        errs = [m for m in out_c if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "no invite to cancel"

    asyncio.run(scenario())


def test_reinvite_different_guest_clears_old_guest_incoming_unit():
    """A invites B then A invites C without cancel → B must lose last_invite_from A."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b, c = FakeWS(), FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await wm.manager.connect(3, c, name="C", x=4, y=2, map_id=0)

        await handle_message(1, 10, {"type": "invite", "to": "B"})
        assert wm.manager.last_invite_from(2)[0] == 1

        wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "invite", "to": "C"})
        assert wm.manager.last_invite_to(1)[0] == 3
        assert wm.manager.last_invite_from(3)[0] == 1
        assert wm.manager.last_invite_from(2)[0] is None, (
            "old guest must not keep zombie last_invite_from"
        )

        # B accept → no invite
        _c, _u, out, _ = await handle_message(2, 20, {"type": "accept"})
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "no invite to answer"

    asyncio.run(scenario())


def test_pending_peek_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="PendA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="PendB", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "PendB"})

        _c, _u, out, _ = await handle_message(1, 10, {"type": "pending"})
        pend = next(m for m in out if m.get("type") == "pending")
        assert pend.get("has_outgoing") is True
        assert pend.get("outgoing", {}).get("name") == "PendB"

        _c, _u, out2, _ = await handle_message(2, 20, {"type": "pending"})
        pend2 = next(m for m in out2 if m.get("type") == "pending")
        assert pend2.get("has_incoming") is True
        assert pend2.get("incoming", {}).get("name") == "PendA"

    asyncio.run(scenario())


def test_thank_still_works_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="ThA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="ThB", x=3, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 1, {"type": "thank", "to": "ThB"})
        assert any(m.get("type") == "thank" for m in out), out

    asyncio.run(scenario())
