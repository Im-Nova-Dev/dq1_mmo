"""v0.5.115: @share alias, best_effort_send, bare share name not alias."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.message_handler import _social_alias


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_share_alias_tokens_unit():
    assert _social_alias("@share") == "share"
    assert _social_alias("@lastshare") == "share"
    assert _social_alias("share") is None  # bare hero name stays addressable
    assert _social_alias("@pending") == "pending"
    assert _social_alias("@last") == "last"


def test_thank_and_whisper_at_share_unit():
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
            1, 10, {"type": "thank", "to": "@share"}
        )
        assert any(m.get("type") == "thank" for m in out), out
        assert any(m.get("type") == "thank" for m in b.sent)

        for _ in range(2):
            wm.manager.refund_chat(1)
        _c, _u, out2, _ = await handle_message(
            1, 10, {"type": "whisper", "to": "@share", "text": "here"}
        )
        assert any(m.get("channel") == "whisper" for m in out2), out2

        # empty share target
        wm.reset_manager()
        a2 = FakeWS()
        await wm.manager.connect(1, a2, name="A", x=2, y=2, map_id=0)
        _c, _u, out3, _ = await handle_message(
            1, 10, {"type": "thank", "to": "@share"}
        )
        errs = [m for m in out3 if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "no share target", out3

    asyncio.run(scenario())


def test_find_at_share_unit():
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
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "find", "query": "@share"}
        )
        f = next(m for m in out if m.get("type") == "find")
        assert int(f.get("count") or 0) >= 1, f
        names = [p.get("name") for p in (f.get("players") or [])]
        assert "B" in names, f

    asyncio.run(scenario())


def test_invite_at_share_unit():
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
            1, 10, {"type": "invite", "to": "@share"}
        )
        assert any(m.get("type") == "invite" for m in out), out
        assert any(m.get("type") == "invite" for m in b.sent)

    asyncio.run(scenario())


def test_best_effort_send_unit():
    from network import websocket_manager as wm
    from network.handlers._common import best_effort_send

    class DeadWS(FakeWS):
        async def send_text(self, t):
            raise ConnectionError("x")

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), DeadWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        ok = await best_effort_send(2, {"type": "invite_superseded", "message": "x"})
        assert ok is False
        ok2 = await best_effort_send(1, {"type": "ping_test"})
        assert ok2 is True

    asyncio.run(scenario())


def test_lastshare_regression_unit():
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
        _c, _u, out, _ = await handle_message(1, 10, {"type": "lastshare"})
        ls = next(m for m in out if m.get("type") == "lastshare")
        assert (ls.get("peer") or {}).get("name") == "B"

    asyncio.run(scenario())
