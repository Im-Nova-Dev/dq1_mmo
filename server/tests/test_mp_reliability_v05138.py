"""v0.5.138: askwhere handler extract · private delivery · near/far echo."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import askwhere
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
    import network.handlers.askwhere as aw

    old = (wm.manager, common.manager, aw.manager)
    wm.manager = mgr
    common.manager = mgr
    aw.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.askwhere as aw

    wm.manager, common.manager, aw.manager = old


def test_askwhere_module_extracted_unit():
    assert "askwhere" in askwhere.ASKWHERE_TYPES
    assert "locate" in askwhere.ASKWHERE_TYPES
    assert askwhere.ASKWHERE_TYPES == askwhere.ALL_TYPES


def test_askwhere_echo_near_far_unit():
    async def scenario():
        import network.handlers.askwhere as aw

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Other", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            res = await aw.handle(1, 1, {"type": "askwhere", "to": "Other"}, outbound)
            assert res is not None, outbound
            m = outbound[0]
            assert m.get("type") == "askwhere", m
            assert "You asked" in (m.get("message") or ""), m
            assert m.get("to_id") == 2
            assert m.get("nearby") is True, m
            assert "online" in m
            assert any(s.get("type") == "askwhere" for s in b.sent)
            peer_msg = next(s for s in b.sent if s.get("type") == "askwhere")
            assert "share @last" in (peer_msg.get("message") or "").lower() or "where" in (
                peer_msg.get("message") or ""
            ).lower()
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_askwhere_self_blocked_unit():
    async def scenario():
        import network.handlers.askwhere as aw

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await aw.handle(1, 1, {"type": "locate", "to": "Hero"}, outbound)
            assert outbound[0].get("reason") == "cannot ask yourself"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_askwhere_fail_restore_afk_unit():
    async def scenario():
        import network.handlers.askwhere as aw

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
            await aw.handle(1, 1, {"type": "askwhere", "to": "Other"}, outbound)
            assert any(o.get("reason") == "player not online" for o in outbound)
            assert mgr.get_meta(1).get("afk") is True
            assert mgr.get_meta(1).get("afk_message") == "lunch"
        finally:
            mgr.send = old_send  # type: ignore
            _restore(old)

    asyncio.run(scenario())
