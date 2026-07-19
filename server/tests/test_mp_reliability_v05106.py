"""v0.5.106 multiplayer: look/ignore @pending reliability."""

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


def test_look_pending_after_invite_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "look", "name": "@pending"})
        looks = [m for m in out if m.get("type") == "look"]
        assert looks, out
        # name on card
        m = looks[0]
        nm = m.get("name") or (m.get("player") or {}).get("name")
        assert nm == "B", m

    asyncio.run(scenario())


def test_ignore_pending_blocks_social_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "ignore", "name": "@pending"})
        assert any(m.get("action") == "ignore" for m in out), out
        wm.manager.refund_chat(1)
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "poke", "to": "B"})
        errs = [m for m in out2 if m.get("type") == "error"]
        assert errs and "ignore" in str(errs[0].get("reason") or "").lower()
        _c, _u, out3, _ = await handle_message(1, 10, {"type": "unignore", "name": "@pending"})
        assert any(m.get("action") == "unignore" for m in out3), out3

    asyncio.run(scenario())


def test_look_pending_empty_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="Solo", x=2, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "look", "to": "@pending"})
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "no pending invite"

    asyncio.run(scenario())


def test_whisper_wave_pending_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "whisper", "to": "@pending", "text": "hi"}
        )
        assert any(m.get("channel") == "whisper" for m in out), out
        wm.manager.refund_chat(1)
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "wave", "to": "@pending"})
        assert any(m.get("type") == "emote" for m in out2), out2

    asyncio.run(scenario())


def test_directed_emote_offline_name_still_errors_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "bow", "to": "Ghost"})
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and "online" in str(errs[0].get("reason") or "").lower()

    asyncio.run(scenario())
