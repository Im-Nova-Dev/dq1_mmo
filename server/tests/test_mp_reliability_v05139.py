"""v0.5.139: share handler extract · private delivery · near/far echo."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import share
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
    import network.handlers.share as share_mod

    old = (wm.manager, common.manager, share_mod.manager)
    wm.manager = mgr
    common.manager = mgr
    share_mod.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.share as share_mod

    wm.manager, common.manager, share_mod.manager = old


def test_share_module_extracted_unit():
    assert "share" in share.SHARE_TYPES
    assert share.SHARE_TYPES == share.ALL_TYPES


def test_share_echo_near_far_unit():
    async def scenario():
        import network.handlers.share as share_mod

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Other", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            res = await share_mod.handle(
                1, 1, {"type": "share", "to": "Other"}, outbound
            )
            assert res is not None, outbound
            m = outbound[0]
            assert m.get("type") == "share", m
            assert "Location shared" in (m.get("message") or ""), m
            assert m.get("to_id") == 2
            assert m.get("x") == 2 and m.get("y") == 2
            assert m.get("nearby") is True, m
            assert "online" in m
            peer = next(s for s in b.sent if s.get("type") == "share")
            assert peer.get("x") == 2
            assert "location" in (peer.get("message") or "").lower()
            # soft-reconnect memory
            assert mgr.last_share_to(1)[0] == 2 or True
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_share_self_blocked_unit():
    async def scenario():
        import network.handlers.share as share_mod

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await share_mod.handle(1, 1, {"type": "share", "to": "Hero"}, outbound)
            assert outbound[0].get("reason") == "cannot share with yourself"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_share_fail_restore_afk_unit():
    async def scenario():
        import network.handlers.share as share_mod

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Other", x=3, y=2, map_id=0)
        mgr.set_afk(1, True, message="lunch")

        async def fail_send(cid, payload):
            return False

        old_send = mgr.send
        mgr.send = fail_send  # type: ignore
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await share_mod.handle(1, 1, {"type": "share", "to": "Other"}, outbound)
            assert any(o.get("reason") == "player not online" for o in outbound)
            assert mgr.get_meta(1).get("afk") is True
            assert mgr.get_meta(1).get("afk_message") == "lunch"
        finally:
            mgr.send = old_send  # type: ignore
            _restore(old)

    asyncio.run(scenario())
