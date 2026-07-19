"""v0.5.116: bidirectional share memory, soft grace, @share for recipient."""

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


def test_share_from_and_lastshare_both_ways_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "share", "to": "B"})

        # Sharer: outgoing
        _c, _u, out_a, _ = await handle_message(1, 10, {"type": "lastshare"})
        ls_a = next(m for m in out_a if m.get("type") == "lastshare")
        assert ls_a.get("has_to") is True
        assert (ls_a.get("to") or {}).get("name") == "B"
        assert "to B" in str(ls_a.get("message") or "")

        # Recipient: incoming
        _c, _u, out_b, _ = await handle_message(2, 20, {"type": "lastshare"})
        ls_b = next(m for m in out_b if m.get("type") == "lastshare")
        assert ls_b.get("has_from") is True
        assert (ls_b.get("from") or ls_b.get("from_peer") or {}).get("name") == "A"
        assert "from A" in str(ls_b.get("message") or "")

        # Recipient can @share (thank A)
        for _ in range(2):
            wm.manager.refund_chat(2)
        _c, _u, out_t, _ = await handle_message(
            2, 20, {"type": "thank", "to": "@share"}
        )
        assert any(m.get("type") == "thank" for m in out_t), out_t
        assert any(m.get("type") == "thank" for m in a.sent)

    asyncio.run(scenario())


def test_share_from_soft_grace_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "share", "to": "B"})
        await wm.manager.disconnect(2, b)
        b2 = FakeWS()
        await wm.manager.connect(2, b2, name="B", x=5, y=5, map_id=0)
        lid, lname = wm.manager.last_share_from(2)
        assert lid == 1 and lname == "A", (lid, lname)

    asyncio.run(scenario())


def test_social_share_from_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "share", "to": "B"})
        _c, _u, out, _ = await handle_message(2, 20, {"type": "social"})
        soc = next(m for m in out if m.get("type") == "social")
        sf = soc.get("share_from") or {}
        assert sf.get("name") == "A", soc
        assert "share from" in str(soc.get("message") or "").lower()

    asyncio.run(scenario())


def test_outgoing_share_alias_still_works_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(3):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "share", "to": "B"})
        for _ in range(2):
            wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "whisper", "to": "@share", "text": "here"}
        )
        assert any(m.get("channel") == "whisper" for m in out), out

    asyncio.run(scenario())


def test_lastshare_empty_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "lastshare"})
        ls = next(m for m in out if m.get("type") == "lastshare")
        assert ls.get("has_to") is False and ls.get("has_from") is False
        assert "No location share" in str(ls.get("message") or "")

    asyncio.run(scenario())
