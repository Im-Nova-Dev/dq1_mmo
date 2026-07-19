"""v0.5.117: @from share-from alias · social_peeks extract · regressions."""

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


def test_from_alias_tokens_unit():
    assert _social_alias("@from") == "share_from"
    assert _social_alias("@sharefrom") == "share_from"
    assert _social_alias("@sharedby") == "share_from"
    assert _social_alias("from") is None  # bare name ok
    assert _social_alias("@share") == "share"


def test_recipient_thank_at_from_unit():
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
        for _ in range(2):
            wm.manager.refund_chat(2)
        _c, _u, out, _ = await handle_message(
            2, 20, {"type": "thank", "to": "@from"}
        )
        assert any(m.get("type") == "thank" for m in out), out
        assert any(m.get("type") == "thank" for m in a.sent)

        # empty @from
        wm.reset_manager()
        c = FakeWS()
        await wm.manager.connect(3, c, name="C", x=2, y=2, map_id=0)
        _c, _u, out2, _ = await handle_message(
            3, 30, {"type": "thank", "to": "@from"}
        )
        errs = [m for m in out2 if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "no share from anyone", out2

    asyncio.run(scenario())


def test_share_prefers_to_over_from_unit():
    """If you both shared to someone and received a share, @share prefers to."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b, c = FakeWS(), FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await wm.manager.connect(3, c, name="C", x=4, y=2, map_id=0)
        for _ in range(4):
            wm.manager.refund_chat(1)
            wm.manager.refund_chat(2)
        # C shares to A (A has from=C), A shares to B (A has to=B)
        await handle_message(3, 30, {"type": "share", "to": "A"})
        await handle_message(1, 10, {"type": "share", "to": "B"})
        for _ in range(2):
            wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "whisper", "to": "@share", "text": "hi"}
        )
        assert any(m.get("channel") == "whisper" for m in out), out
        # delivered to B not C
        assert any(
            m.get("channel") == "whisper" and m.get("text") == "hi" for m in b.sent
        ), b.sent
        # @from still hits C
        for _ in range(2):
            wm.manager.refund_chat(1)
        _c, _u, out2, _ = await handle_message(
            1, 10, {"type": "whisper", "to": "@from", "text": "thanks"}
        )
        assert any(m.get("channel") == "whisper" for m in out2), out2
        assert any(
            m.get("channel") == "whisper" and m.get("text") == "thanks" for m in c.sent
        ), c.sent

    asyncio.run(scenario())


def test_social_peeks_extracted_unit():
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
        for typ in ("social", "lastshare", "pending", "lastemote", "lastwhisper"):
            _c, _u, out, _ = await handle_message(1, 10, {"type": typ})
            assert out and out[0].get("type") in (
                typ,
                "lastshare",
                "social",
                "pending",
                "lastemote",
                "lastwhisper",
            ), (typ, out)

    asyncio.run(scenario())


def test_lastshare_bidirectional_regression_unit():
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
        _c, _u, out, _ = await handle_message(2, 20, {"type": "lastshare"})
        ls = next(m for m in out if m.get("type") == "lastshare")
        assert ls.get("has_from") is True
        assert (ls.get("from") or {}).get("name") == "A"

    asyncio.run(scenario())
