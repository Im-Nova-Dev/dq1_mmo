"""v0.5.104 multiplayer: @pending alias resolution + mute cancel message."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.message_handler import _resolve_social_peer, _social_alias


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


def test_social_alias_tokens_unit():
    assert _social_alias("@last") == "last"
    assert _social_alias("!") == "last"
    assert _social_alias("@pending") == "pending"
    assert _social_alias("@invite") == "pending"
    assert _social_alias("@meetup") == "pending"
    # bare "pending" is a valid hero name — not an alias without @
    assert _social_alias("pending") is None
    assert _social_alias("meetup") is None
    assert _social_alias("Hero") is None
    assert _social_alias(None, {"reply": True}) == "last"
    assert _social_alias(None, {"pending": True}) == "pending"


def test_resolve_pending_prefers_incoming_unit():
    from network import websocket_manager as wm

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        wm.manager.note_invite_from(2, 1, "A")
        wm.manager.note_invite_to(2, 99, "X")  # outgoing distractor
        lid, lname, err = _resolve_social_peer(wm.manager, 2, "pending")
        assert err is None
        assert lid == 1
        assert lname == "A"

    asyncio.run(scenario())


def test_poke_pending_after_invite_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "poke", "to": "@pending"})
        assert any(m.get("type") == "poke" for m in out), out
        assert any(m.get("type") == "poke" for m in b.sent)

    asyncio.run(scenario())


def test_cancel_muted_message_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        wm.manager.ignore_player(2, 1)
        b.sent.clear()
        wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "cancel"})
        echo = next(m for m in out if m.get("type") == "invite_cancel")
        assert echo.get("notified") is False
        assert echo.get("muted") is True
        assert "muted" in str(echo.get("message") or "").lower()
        assert not [m for m in b.sent if m.get("type") == "invite_cancel"]

    asyncio.run(scenario())


def test_share_askwhere_pending_and_thank_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        wm.manager.refund_chat(2)
        _c, _u, out, _ = await handle_message(2, 20, {"type": "share", "to": "@pending"})
        assert any(m.get("type") == "share" for m in out), out
        wm.manager.refund_chat(2)
        _c, _u, out2, _ = await handle_message(2, 20, {"type": "askwhere", "to": "@invite"})
        assert any(m.get("type") == "askwhere" for m in out2), out2
        wm.manager.refund_chat(1)
        _c, _u, out3, _ = await handle_message(1, 10, {"type": "thank", "to": "B"})
        assert any(m.get("type") == "thank" for m in out3), out3

    asyncio.run(scenario())


def test_pending_empty_alias_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="Solo", x=2, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "poke", "to": "@pending"})
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "no pending invite"

    asyncio.run(scenario())
