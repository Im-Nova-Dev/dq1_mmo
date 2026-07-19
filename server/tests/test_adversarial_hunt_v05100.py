"""v0.5.100 adversarial hunt: soft-grace invite zombies after cancel/offline clear."""

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


def test_cancel_while_guest_offline_clears_soft_grace_invite():
    """Inviter /cancel while guest offline must not leave zombie invite on reconnect."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="CanA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="CanB", x=3, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "invite", "to": "CanB"})
        assert any(m.get("type") == "invite" for m in out), out
        assert wm.manager.last_invite_from(2)[0] == 1
        assert wm.manager.last_invite_to(1)[0] == 2

        await wm.manager.disconnect(2, b)
        bag = wm.manager._soft_grace.get(2) or {}
        assert bag.get("last_invite_from_id") == 1
        # Inviter still online — outgoing pointer must survive guest disconnect
        assert wm.manager.last_invite_to(1)[0] == 2

        # Avoid chat-rate flake: refund stamp instead of sleeping
        wm.manager.refund_chat(1)
        _c, _u, out_c, _ = await handle_message(1, 10, {"type": "cancel"})
        assert any(m.get("type") == "invite_cancel" for m in out_c), out_c
        bag2 = wm.manager._soft_grace.get(2) or {}
        assert bag2.get("last_invite_from_id") is None, (
            f"soft-grace invite must be cleared, got {bag2.get('last_invite_from_id')}"
        )
        assert wm.manager.last_invite_to(1)[0] is None

        b2 = FakeWS()
        await wm.manager.connect(2, b2, name="CanB", x=3, y=2, map_id=0)
        assert wm.manager.last_invite_from(2)[0] is None, "zombie invite after reconnect"

        _c, _u, out_a, _ = await handle_message(2, 20, {"type": "accept"})
        errs = [m for m in out_a if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "no invite to answer"

    asyncio.run(scenario())


def test_offline_decline_clears_inviter_soft_grace_invite_to():
    """Guest offline-clear must drop inviter soft-grace last_invite_to."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="DecA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="DecB", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "DecB"})
        await wm.manager.disconnect(1, a)
        bag = wm.manager._soft_grace.get(1) or {}
        assert bag.get("last_invite_to_id") == 2

        _c, _u, out, _ = await handle_message(2, 20, {"type": "decline"})
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and errs[0].get("invite_cleared") is True
        bag2 = wm.manager._soft_grace.get(1) or {}
        assert bag2.get("last_invite_to_id") in (None,), bag2

        a2 = FakeWS()
        await wm.manager.connect(1, a2, name="DecA", x=2, y=2, map_id=0)
        assert wm.manager.last_invite_to(1)[0] is None

        _c, _u, out_c, _ = await handle_message(1, 10, {"type": "cancel"})
        errs_c = [m for m in out_c if m.get("type") == "error"]
        assert errs_c and errs_c[0].get("reason") == "no invite to cancel"

    asyncio.run(scenario())


def test_clear_invite_peer_helpers_unit():
    from network.websocket_manager import ConnectionManager

    async def scenario():
        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="B", x=3, y=2, map_id=0)
        mgr.note_invite_from(2, 1, "A")
        mgr.note_invite_to(1, 2, "B")
        assert mgr.clear_invite_from_peer(2, 1) is True
        assert mgr.last_invite_from(2)[0] is None
        assert mgr.clear_invite_to_peer(1, 2) is True
        assert mgr.last_invite_to(1)[0] is None
        # no-op when already clear
        assert mgr.clear_invite_from_peer(2, 1) is False

    asyncio.run(scenario())


def test_thank_and_who_still_work_after_invite_hygiene():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="RegA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="RegB", x=3, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 1, {"type": "thank", "to": "RegB"})
        assert any(m.get("type") == "thank" for m in out), out
        _c, _u, out2, _ = await handle_message(1, 1, {"type": "who"})
        who = next(m for m in out2 if m.get("type") == "who")
        assert "combat_count" in who and "afk_count" in who

    asyncio.run(scenario())
