"""v0.5.99 multiplayer reliability: offline invite clear + thank fail AFK restore."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager


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


def test_offline_invite_accept_clears_stuck_invite_unit():
    """Accept/decline when inviter offline must clear last_invite (no infinite stuck)."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="InvA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="InvB", x=3, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "invite", "to": "InvB"})
        assert any(m.get("type") == "invite" for m in out), out
        assert wm.manager.last_invite_from(2)[0] == 1

        await wm.manager.disconnect(1, a)
        assert 1 not in wm.manager.online_ids()

        # Guest was AFK — offline accept must not burn AFK, must clear invite
        assert wm.manager.set_afk(2, True, message="waiting")
        _c, _u, out2, _ = await handle_message(2, 20, {"type": "accept"})
        errs = [m for m in out2 if m.get("type") == "error"]
        assert errs, out2
        assert errs[0].get("reason") == "player not online"
        assert errs[0].get("invite_cleared") is True
        assert "cleared" in str(errs[0].get("message") or "").lower()

        lid, _ = wm.manager.last_invite_from(2)
        assert lid is None, "stuck invite must be cleared"

        meta = wm.manager.get_meta(2)
        assert meta and meta.get("afk") is True, "AFK must survive offline accept clear"
        assert meta.get("afk_message") == "waiting"

        # Second accept → no invite
        _c, _u, out3, _ = await handle_message(2, 20, {"type": "accept"})
        errs3 = [m for m in out3 if m.get("type") == "error"]
        assert errs3 and errs3[0].get("reason") == "no invite to answer"

    asyncio.run(scenario())


def test_offline_invite_decline_clears_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="DecA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="DecB", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "DecB"})
        await wm.manager.disconnect(1, a)

        _c, _u, out, _ = await handle_message(2, 20, {"type": "decline"})
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and errs[0].get("invite_cleared") is True
        assert wm.manager.last_invite_from(2)[0] is None

    asyncio.run(scenario())


def test_thank_fail_restores_afk_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS(fail=True)
        await wm.manager.connect(1, a, name="ThA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="ThB", x=3, y=2, map_id=0)
        assert wm.manager.set_afk(1, True, message="afk thank")

        _c, _u, out, _ = await handle_message(1, 99, {"type": "thank", "to": "ThB"})
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and errs[0].get("reason") == "player not online"

        meta = wm.manager.get_meta(1)
        assert meta and meta.get("afk") is True
        assert meta.get("afk_message") == "afk thank"
        assert wm.manager.afk_count() == 1

    asyncio.run(scenario())


def test_invite_soft_reconnect_still_answerable_unit():
    """Brief inviter disconnect+reconnect keeps invite answerable (soft grace)."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="SoftA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="SoftB", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "SoftB"})
        assert wm.manager.last_invite_from(2)[0] == 1

        await wm.manager.disconnect(1, a)
        # Reconnect inviter within soft grace
        a2 = FakeWS()
        await wm.manager.connect(1, a2, name="SoftA", x=2, y=2, map_id=0)
        assert 1 in wm.manager.online_ids()
        assert wm.manager.last_invite_from(2)[0] == 1

        _c, _u, out, _ = await handle_message(2, 20, {"type": "accept"})
        assert any(m.get("type") == "invite_reply" for m in out), out
        assert wm.manager.last_invite_from(2)[0] is None

    asyncio.run(scenario())


def test_who_and_whisper_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="RegA", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="RegB", x=3, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 1, {"type": "who"})
        who = next(m for m in out if m.get("type") == "who")
        assert "combat_count" in who
        assert "afk_count" in who

        _c, _u, out2, _ = await handle_message(
            1, 1, {"type": "whisper", "to": "RegB", "text": "hi"}
        )
        assert any(m.get("channel") == "whisper" for m in out2), out2

    asyncio.run(scenario())
