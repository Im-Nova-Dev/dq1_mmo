"""v0.5.142: invite_reply extract · private delivery · near/far · soft-grace clear."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import invite_reply
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.closed = False
        self.fail = fail

    async def send_text(self, t):
        if self.fail:
            raise ConnectionError("socket dead")
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def _bind(mgr):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.invite_reply as ir
    import network.handlers.invite as inv

    old = (wm.manager, common.manager, ir.manager, inv.manager)
    wm.manager = mgr
    common.manager = mgr
    ir.manager = mgr
    inv.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.invite_reply as ir
    import network.handlers.invite as inv

    wm.manager, common.manager, ir.manager, inv.manager = old


def test_invite_reply_module_extracted_unit():
    assert "accept" in invite_reply.ACCEPT_TYPES
    assert "coming" in invite_reply.ACCEPT_TYPES
    assert "decline" in invite_reply.DECLINE_TYPES
    assert "later" in invite_reply.DECLINE_TYPES
    assert invite_reply.ALL_TYPES == (
        invite_reply.ACCEPT_TYPES | invite_reply.DECLINE_TYPES
    )


def test_accept_echo_near_coords_unit():
    async def scenario():
        import network.handlers.invite as inv
        import network.handlers.invite_reply as ir

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await inv.handle(1, 1, {"type": "invite", "to": "Guest"}, outbound)
            mgr.refund_chat(2)
            out2: list[dict] = []
            res = await ir.handle(2, 2, {"type": "accept"}, out2)
            assert res is not None, out2
            m = next(x for x in out2 if x.get("type") == "invite_reply")
            assert m.get("action") == "accept", m
            assert m.get("nearby") is True
            assert m.get("x") == 3 and m.get("y") == 2
            assert "online" in m and "nearby_count" in m
            assert "coming" in (m.get("message") or "").lower() or "told" in (
                m.get("message") or ""
            ).lower()
            peer = next(s for s in a.sent if s.get("type") == "invite_reply")
            assert peer.get("action") == "accept"
            assert peer.get("nearby") is True
            assert peer.get("x") == 3
            # Invite consumed
            assert mgr.last_invite_from(2)[0] is None
            assert mgr.last_invite_to(1)[0] is None
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_accept_far_no_coords_unit():
    async def scenario():
        import network.handlers.invite as inv
        import network.handlers.invite_reply as ir

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Far", x=18, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await inv.handle(1, 1, {"type": "invite", "to": "Far"}, outbound)
            mgr.refund_chat(2)
            out2: list[dict] = []
            await ir.handle(2, 2, {"type": "accept"}, out2)
            m = next(x for x in out2 if x.get("type") == "invite_reply")
            assert m.get("nearby") is False
            assert "x" not in m or m.get("x") is None
            peer = next(s for s in a.sent if s.get("type") == "invite_reply")
            assert peer.get("nearby") is False
            assert "x" not in peer
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_decline_clears_pending_unit():
    async def scenario():
        import network.handlers.invite as inv
        import network.handlers.invite_reply as ir

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            await inv.handle(1, 1, {"type": "invite", "to": "Guest"}, [])
            mgr.refund_chat(2)
            out2: list[dict] = []
            await ir.handle(2, 2, {"type": "decline"}, out2)
            m = next(x for x in out2 if x.get("type") == "invite_reply")
            assert m.get("action") == "decline"
            assert "declined" in (m.get("message") or "").lower()
            peer = next(s for s in a.sent if s.get("type") == "invite_reply")
            assert peer.get("action") == "decline"
            assert mgr.last_invite_from(2)[0] is None
            assert mgr.last_invite_to(1)[0] is None
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_accept_fail_restore_afk_keeps_invite_unit():
    async def scenario():
        import network.handlers.invite as inv
        import network.handlers.invite_reply as ir

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            await inv.handle(1, 1, {"type": "invite", "to": "Guest"}, [])
            assert mgr.last_invite_from(2)[0] == 1
            mgr.set_afk(2, True, message="lunch")

            async def fail_send(cid, payload):
                return False

            old_send = mgr.send
            mgr.send = fail_send  # type: ignore
            try:
                out2: list[dict] = []
                await ir.handle(2, 2, {"type": "accept"}, out2)
                assert any(o.get("reason") == "player not online" for o in out2)
                assert mgr.get_meta(2).get("afk") is True
                assert mgr.get_meta(2).get("afk_message") == "lunch"
                # Invite still pending for retry
                assert mgr.last_invite_from(2)[0] == 1
            finally:
                mgr.send = old_send  # type: ignore
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_offline_inviter_clears_soft_grace_unit():
    async def scenario():
        import network.handlers.invite as inv
        import network.handlers.invite_reply as ir

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            await inv.handle(1, 1, {"type": "invite", "to": "Guest"}, [])
            assert mgr.last_invite_from(2)[0] == 1
            assert mgr.last_invite_to(1)[0] == 2
            # Soft disconnect inviter into grace (not online)
            await mgr.disconnect(1)
            assert 1 not in mgr.online_ids()
            # Soft-grace bag may still hold last_invite_to
            out2: list[dict] = []
            await ir.handle(2, 2, {"type": "accept"}, out2)
            err = next(x for x in out2 if x.get("type") == "error")
            assert err.get("reason") == "player not online"
            assert err.get("invite_cleared") is True
            assert mgr.last_invite_from(2)[0] is None
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_no_invite_to_answer_unit():
    async def scenario():
        import network.handlers.invite_reply as ir

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ir.handle(1, 1, {"type": "accept"}, outbound)
            assert outbound[0].get("reason") == "no invite to answer"
        finally:
            _restore(old)

    asyncio.run(scenario())
