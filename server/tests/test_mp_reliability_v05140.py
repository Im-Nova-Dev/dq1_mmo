"""v0.5.140: invite_cancel extract · soft-grace clear · near/far echo."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import invite_cancel
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def _bind(mgr):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.invite_cancel as ic

    old = (wm.manager, common.manager, ic.manager)
    wm.manager = mgr
    common.manager = mgr
    ic.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.invite_cancel as ic

    wm.manager, common.manager, ic.manager = old


def test_invite_cancel_module_extracted_unit():
    assert "cancel" in invite_cancel.CANCEL_TYPES
    assert "uninvite" in invite_cancel.CANCEL_TYPES


def test_cancel_notifies_pending_peer_unit():
    async def scenario():
        import network.handlers.invite_cancel as ic

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        # set pending invite 1 -> 2
        mgr.note_invite_to(1, 2, "Guest")
        mgr.note_invite_from(2, 1, "Hero")
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            res = await ic.handle(1, 1, {"type": "cancel"}, outbound)
            assert res is not None, outbound
            m = outbound[0]
            assert m.get("type") == "invite_cancel", m
            assert m.get("action") == "cancel"
            assert m.get("notified") is True, m
            assert "cancelled" in (m.get("message") or "").lower()
            assert m.get("nearby") is True
            assert "online" in m
            assert any(s.get("type") == "invite_cancel" for s in b.sent)
            # pointers cleared
            assert mgr.last_invite_to(1)[0] is None
            assert mgr.last_invite_from(2)[0] is None
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_cancel_no_invite_unit():
    async def scenario():
        import network.handlers.invite_cancel as ic

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ic.handle(1, 1, {"type": "uninvite"}, outbound)
            assert outbound[0].get("reason") == "no invite to cancel"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_cancel_muted_guest_unit():
    async def scenario():
        import network.handlers.invite_cancel as ic

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        mgr.note_invite_to(1, 2, "Guest")
        mgr.note_invite_from(2, 1, "Hero")
        mgr.ignore_player(2, 1)  # guest mutes inviter
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ic.handle(1, 1, {"type": "cancel"}, outbound)
            m = outbound[0]
            assert m.get("type") == "invite_cancel"
            assert m.get("notified") is False
            assert m.get("muted") is True
            assert "muted" in (m.get("message") or "").lower()
            assert not any(s.get("type") == "invite_cancel" for s in b.sent)
        finally:
            _restore(old)

    asyncio.run(scenario())
