"""v0.5.121: lastinvite bidirectional to+from · soft reconnect invite peek."""

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


def test_lastinvite_both_ways_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "invite", "to": "B"})

        # Inviter lastinvite: to B
        _c, _u, out_a, _ = await handle_message(1, 10, {"type": "lastinvite"})
        li_a = next(m for m in out_a if m.get("type") == "lastinvite")
        assert li_a.get("has_to") is True, li_a
        assert (li_a.get("to") or {}).get("name") == "B", li_a
        assert "to B" in str(li_a.get("message") or ""), li_a

        # Guest lastinvite: from A
        _c, _u, out_b, _ = await handle_message(2, 20, {"type": "lastinvite"})
        li_b = next(m for m in out_b if m.get("type") == "lastinvite")
        assert li_b.get("has_from") is True, li_b
        assert (li_b.get("from") or {}).get("name") == "A", li_b
        assert "from A" in str(li_b.get("message") or ""), li_b
        # back-compat peer prefers from
        assert (li_b.get("peer") or {}).get("name") == "A", li_b

    asyncio.run(scenario())


def test_lastinvite_soft_grace_unit():
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
        await wm.manager.disconnect(1, a)
        a2 = FakeWS()
        await wm.manager.connect(1, a2, name="A", x=2, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "lastinvite"})
        li = next(m for m in out if m.get("type") == "lastinvite")
        assert li.get("has_to") is True, li
        assert (li.get("to") or {}).get("name") == "B", li

    asyncio.run(scenario())


def test_lastinvite_empty_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "lastinvite"})
        li = next(m for m in out if m.get("type") == "lastinvite")
        assert li.get("has_to") is False and li.get("has_from") is False
        assert "No meetup invite" in str(li.get("message") or "")

    asyncio.run(scenario())


def test_pending_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "pending"})
        p = next(m for m in out if m.get("type") == "pending")
        assert p.get("has_outgoing") is True
        assert (p.get("outgoing") or {}).get("name") == "B"

    asyncio.run(scenario())


def test_lastemote_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "wave", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "lastemote"})
        le = next(m for m in out if m.get("type") == "lastemote")
        assert le.get("has_to") is True
        assert (le.get("to") or {}).get("name") == "B"

    asyncio.run(scenario())
