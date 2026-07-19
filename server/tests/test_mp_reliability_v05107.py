"""v0.5.107 multiplayer: social summary + find social aliases."""

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


def test_social_summary_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "social"})
        soc = next(m for m in out if m.get("type") == "social")
        assert soc.get("has_any") is True
        assert (soc.get("invite_to") or {}).get("name") == "B"
        assert (soc.get("whisper") or {}).get("name") == "B"
        _c, _u, out2, _ = await handle_message(2, 20, {"type": "peers"})
        soc2 = next(m for m in out2 if m.get("type") == "social")
        assert (soc2.get("invite_from") or {}).get("name") == "A"

    asyncio.run(scenario())


def test_find_pending_and_last_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "find", "query": "@pending"})
        f = next(m for m in out if m.get("type") == "find")
        assert int(f.get("count") or 0) == 1
        assert (f.get("players") or [{}])[0].get("name") == "B"
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "find", "q": "@last"})
        f2 = next(m for m in out2 if m.get("type") == "find")
        assert int(f2.get("count") or 0) >= 1

    asyncio.run(scenario())


def test_find_pending_offline_errors_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        await wm.manager.disconnect(2, b)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "find", "query": "@pending"})
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and "online" in str(errs[0].get("reason") or "").lower()

    asyncio.run(scenario())


def test_look_ignore_pending_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "look", "name": "@pending"})
        assert any(m.get("type") == "look" for m in out), out
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "whisper", "to": "@pending", "text": "x"})
        # may rate limit if invite burned chat - refund
        if any(m.get("reason") == "chat_rate_limit" for m in out2):
            wm.manager.refund_chat(1)
            _c, _u, out2, _ = await handle_message(
                1, 10, {"type": "whisper", "to": "@pending", "text": "x"}
            )
        assert any(m.get("channel") == "whisper" for m in out2), out2

    asyncio.run(scenario())


def test_social_unauth_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        _c, _u, out, _ = await handle_message(None, None, {"type": "social"})
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and "auth" in str(errs[0].get("reason") or "").lower()

    asyncio.run(scenario())
