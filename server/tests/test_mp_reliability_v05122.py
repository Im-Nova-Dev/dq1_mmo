"""v0.5.122: last_whisper social_peer_card on soft-reconnect snapshot + lastwhisper peek."""

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


def test_snapshot_includes_whisper_near_far_unit():
    from network import websocket_manager as wm
    from network.handlers._common import soft_reconnect_social_snapshot
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        # near pair
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(
            1, 10, {"type": "whisper", "to": "B", "text": "hi near"}
        )
        snap = soft_reconnect_social_snapshot(wm.manager, 1)
        assert snap["has_whisper"] is True, snap
        card = snap["last_whisper"] or {}
        assert card.get("name") == "B", card
        assert card.get("nearby") is True, card
        assert card.get("online") is True, card

        # far whisper partner card
        await wm.manager.disconnect(2, b)
        b2 = FakeWS()
        await wm.manager.connect(2, b2, name="B", x=18, y=2, map_id=0)
        assert 2 not in wm.manager.ids_nearby(1)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(
            1, 10, {"type": "whisper", "to": "B", "text": "hi far"}
        )
        snap2 = soft_reconnect_social_snapshot(wm.manager, 1)
        card2 = snap2["last_whisper"] or {}
        assert card2.get("name") == "B", card2
        assert card2.get("nearby") is False, card2

    asyncio.run(scenario())


def test_sync_whisper_peer_card_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "whisper", "to": "B", "text": "yo"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "sync"})
        ws = next(m for m in out if m.get("type") == "world_state")
        lw = ws.get("last_whisper") or {}
        assert lw.get("name") == "B", ws
        assert "online" in lw, lw
        assert lw.get("nearby") is True, lw

    asyncio.run(scenario())


def test_lastwhisper_has_peer_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=18, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "whisper", "to": "B", "text": "far"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "lastwhisper"})
        lw = next(m for m in out if m.get("type") == "lastwhisper")
        assert lw.get("has_peer") is True, lw
        peer = lw.get("peer") or {}
        assert peer.get("name") == "B", lw
        assert peer.get("nearby") is False, peer
        assert "far" in str(lw.get("message") or "").lower(), lw

    asyncio.run(scenario())


def test_whisper_soft_grace_snapshot_unit():
    from network import websocket_manager as wm
    from network.handlers._common import soft_reconnect_social_snapshot
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "whisper", "to": "B", "text": "x"})
        await wm.manager.disconnect(1, a)
        a2 = FakeWS()
        await wm.manager.connect(1, a2, name="A", x=2, y=2, map_id=0)
        snap = soft_reconnect_social_snapshot(wm.manager, 1)
        assert snap["has_whisper"] is True, snap
        assert (snap["last_whisper"] or {}).get("name") == "B"

    asyncio.run(scenario())


def test_invite_share_snapshot_regression_unit():
    from network import websocket_manager as wm
    from network.handlers._common import soft_reconnect_social_snapshot
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for typ in ("share", "invite"):
            for _ in range(2):
                wm.manager.refund_chat(1)
            await handle_message(1, 10, {"type": typ, "to": "B"})
        snap = soft_reconnect_social_snapshot(wm.manager, 1)
        assert snap["has_share"] and snap["has_invite"]
        assert (snap["last_share_to"] or {}).get("name") == "B"
        assert (snap["last_invite_to"] or {}).get("name") == "B"

    asyncio.run(scenario())
