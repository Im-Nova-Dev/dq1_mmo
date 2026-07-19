"""v0.5.105 adversarial: whisper/wave @pending; bare name not alias."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.message_handler import _social_alias


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


def test_whisper_and_wave_pending_unit():
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
            1, 10, {"type": "whisper", "to": "@pending", "text": "meet me"}
        )
        assert any(m.get("channel") == "whisper" for m in out), out
        assert any(m.get("channel") == "whisper" for m in b.sent)

        wm.manager.refund_chat(1)
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "wave", "to": "@pending"})
        assert any(m.get("type") == "emote" for m in out2), out2

        # channel=whisper path
        wm.manager.refund_chat(1)
        _c, _u, out3, _ = await handle_message(
            1,
            10,
            {"type": "chat", "channel": "whisper", "to": "@pending", "text": "yo"},
        )
        assert any(m.get("channel") == "whisper" for m in out3), out3

    asyncio.run(scenario())


def test_bare_pending_not_alias_unit():
    assert _social_alias("pending") is None
    assert _social_alias("@pending") == "pending"


def test_whisper_pending_empty_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="Solo", x=2, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "whisper", "to": "@pending", "text": "hi"}
        )
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "no pending invite"

    asyncio.run(scenario())


def test_poke_thank_pending_still_work_unit():
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
        wm.manager.refund_chat(2)
        _c, _u, out2, _ = await handle_message(2, 20, {"type": "thank", "to": "@invite"})
        assert any(m.get("type") == "thank" for m in out2), out2

    asyncio.run(scenario())


def test_cancel_muted_and_who_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        wm.manager.ignore_player(2, 1)
        wm.manager.refund_chat(1)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "cancel"})
        echo = next(m for m in out if m.get("type") == "invite_cancel")
        assert echo.get("muted") is True
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "who"})
        who = next(m for m in out2 if m.get("type") == "who")
        assert "combat_count" in who

    asyncio.run(scenario())


def test_directed_emote_unknown_name_not_undirected_unit():
    """Named offline target must error — never fall through to undirected wave."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        wm.manager.set_afk(1, True, message="wait")
        _c, _u, out, _ = await handle_message(1, 10, {"type": "wave", "to": "NobodyHere"})
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and "online" in str(errs[0].get("reason") or "").lower()
        assert not any(m.get("type") == "emote" for m in out)
        assert wm.manager.get_meta(1).get("afk") is True
        # bare undirected still works
        wm.manager.get_meta(1)["last_chat_at"] = 0
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "wave"})
        assert any(m.get("type") == "emote" for m in out2)

    asyncio.run(scenario())
