"""v0.5.141: invite handler extract · private delivery · near/far echo."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import invite
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
    import network.handlers.invite as inv

    old = (wm.manager, common.manager, inv.manager)
    wm.manager = mgr
    common.manager = mgr
    inv.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.invite as inv

    wm.manager, common.manager, inv.manager = old


def test_invite_module_extracted_unit():
    assert "invite" in invite.INVITE_TYPES
    assert "meet" in invite.INVITE_TYPES


def test_invite_echo_near_far_unit():
    async def scenario():
        import network.handlers.invite as inv

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            res = await inv.handle(1, 1, {"type": "invite", "to": "Guest"}, outbound)
            assert res is not None, outbound
            m = outbound[0]
            assert m.get("type") == "invite", m
            assert "Invite sent" in (m.get("message") or ""), m
            assert m.get("to_id") == 2
            assert m.get("nearby") is True
            assert m.get("x") == 2  # near peer gets coords on guest payload
            assert "online" in m
            peer = next(s for s in b.sent if s.get("type") == "invite")
            assert peer.get("nearby") is True
            assert peer.get("x") == 2
            assert mgr.last_invite_to(1)[0] == 2
            assert mgr.last_invite_from(2)[0] == 1
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_invite_far_no_coords_unit():
    async def scenario():
        import network.handlers.invite as inv

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Far", x=18, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await inv.handle(1, 1, {"type": "meet", "to": "Far"}, outbound)
            m = outbound[0]
            assert m.get("type") == "invite"
            assert m.get("nearby") is False
            assert "x" not in m or m.get("x") is None
            peer = next(s for s in b.sent if s.get("type") == "invite")
            assert peer.get("nearby") is False
            assert "x" not in peer
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_invite_fail_restore_afk_unit():
    async def scenario():
        import network.handlers.invite as inv

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        mgr.set_afk(1, True, message="lunch")

        async def fail_send(cid, payload):
            return False

        old_send = mgr.send
        mgr.send = fail_send  # type: ignore
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await inv.handle(1, 1, {"type": "invite", "to": "Guest"}, outbound)
            assert any(o.get("reason") == "player not online" for o in outbound)
            assert mgr.get_meta(1).get("afk") is True
            assert mgr.get_meta(1).get("afk_message") == "lunch"
        finally:
            mgr.send = old_send  # type: ignore
            _restore(old)

    asyncio.run(scenario())


def test_invite_self_blocked_unit():
    async def scenario():
        import network.handlers.invite as inv

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await inv.handle(1, 1, {"type": "invite", "to": "Hero"}, outbound)
            assert outbound[0].get("reason") == "cannot invite yourself"
        finally:
            _restore(old)

    asyncio.run(scenario())
