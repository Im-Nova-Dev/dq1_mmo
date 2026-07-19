"""v0.5.118: presence peeks extract · soft-reconnect share restore."""

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


def test_presence_peeks_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for typ, key in (
            ("who", "players"),
            ("near", "players"),
            ("counts", "online"),
            ("zone", "zone"),
            ("fighting", "players"),
        ):
            _c, _u, out, _ = await handle_message(1, 10, {"type": typ})
            assert out and out[0].get("type") == typ, (typ, out)
            assert key in out[0], out[0]

    asyncio.run(scenario())


def test_share_soft_grace_restored_flag_unit():
    """After soft reconnect, last_share_* still resolve; restored flag path unit."""
    from network import websocket_manager as wm
    from network.handlers._common import social_peer_card
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "share", "to": "B"})
        await wm.manager.disconnect(1, a)
        a2 = FakeWS()
        await wm.manager.connect(1, a2, name="A", x=2, y=2, map_id=0)
        st_id, st_name = wm.manager.last_share_to(1)
        assert st_id == 2 and st_name == "B"
        card = social_peer_card(wm.manager, st_id, st_name, viewer_id=1)
        assert card and card.get("name") == "B"
        # B still has from after A reconnects
        sf_id, sf_name = wm.manager.last_share_from(2)
        assert sf_id == 1

    asyncio.run(scenario())


def test_sync_includes_share_peers_unit():
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
        _c, _u, out, _ = await handle_message(1, 10, {"type": "sync"})
        ws = next(m for m in out if m.get("type") == "world_state")
        assert (ws.get("last_share_to") or {}).get("name") == "B", ws
        _c, _u, out2, _ = await handle_message(2, 20, {"type": "sync"})
        ws2 = next(m for m in out2 if m.get("type") == "world_state")
        assert (ws2.get("last_share_from") or {}).get("name") == "A", ws2

    asyncio.run(scenario())


def test_from_alias_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message, _social_alias

    assert _social_alias("@from") == "share_from"

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

    asyncio.run(scenario())


def test_who_still_works_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "who"})
        who = next(m for m in out if m.get("type") == "who")
        assert "you" in who and who["you"].get("name") == "A"

    asyncio.run(scenario())
