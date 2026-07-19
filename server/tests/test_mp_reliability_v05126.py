"""v0.5.126: look handler extract · near/far coords · social aliases."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import look as look_handlers
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_look_module_extracted_unit():
    assert "look" in look_handlers.LOOK_TYPES
    assert "examine" in look_handlers.LOOK_TYPES
    assert "whereis" in look_handlers.LOOK_TYPES


def test_look_near_has_coords_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "look", "name": "B"})
        lk = next(m for m in out if m.get("type") == "look")
        pl = lk.get("player") or {}
        assert pl.get("nearby") is True
        assert "x" in pl and "y" in pl
        assert lk.get("nearby") is True
        assert "nearby" in str(lk.get("message") or "").lower()

    asyncio.run(scenario())


def test_look_far_no_coords_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=18, y=2, map_id=0)
        assert 2 not in wm.manager.ids_nearby(1)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "look", "name": "B"})
        lk = next(m for m in out if m.get("type") == "look")
        pl = lk.get("player") or {}
        assert pl.get("nearby") is False
        assert "x" not in pl and "y" not in pl
        assert "far" in str(lk.get("message") or "").lower() or pl.get("zone")

    asyncio.run(scenario())


def test_look_at_emote_alias_unit():
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
        _c, _u, out, _ = await handle_message(1, 10, {"type": "look", "name": "@emote"})
        lk = next(m for m in out if m.get("type") == "look")
        assert (lk.get("player") or {}).get("name") == "B"

    asyncio.run(scenario())


def test_bare_look_self_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "look"})
        lk = next(m for m in out if m.get("type") == "look")
        pl = lk.get("player") or {}
        assert pl.get("id") == 1
        assert pl.get("nearby") is True
        assert "x" in pl

    asyncio.run(scenario())
