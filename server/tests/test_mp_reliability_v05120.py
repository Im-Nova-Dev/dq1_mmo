"""v0.5.120: soft-reconnect social snapshot (share · emote · invite) on auth/sync."""

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


def test_soft_reconnect_snapshot_unit():
    from network import websocket_manager as wm
    from network.handlers._common import soft_reconnect_social_snapshot
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for typ in ("wave", "share", "invite"):
            for _ in range(2):
                wm.manager.refund_chat(1)
            await handle_message(1, 10, {"type": typ, "to": "B"})
        snap = soft_reconnect_social_snapshot(wm.manager, 1)
        assert snap["has_emote"] and (snap["last_emote_to"] or {}).get("name") == "B"
        assert snap["has_share"] and (snap["last_share_to"] or {}).get("name") == "B"
        assert snap["has_invite"] and (snap["last_invite_to"] or {}).get("name") == "B"
        snap_b = soft_reconnect_social_snapshot(wm.manager, 2)
        assert snap_b["has_emote"] and (snap_b["last_emote_from"] or {}).get("name") == "A"
        assert snap_b["has_share"] and (snap_b["last_share_from"] or {}).get("name") == "A"
        assert snap_b["has_invite"] and (snap_b["last_invite_from"] or {}).get("name") == "A"

    asyncio.run(scenario())


def test_sync_includes_invite_peers_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "sync"})
        ws = next(m for m in out if m.get("type") == "world_state")
        assert (ws.get("last_invite_to") or {}).get("name") == "B", ws
        _c, _u, out2, _ = await handle_message(2, 20, {"type": "sync"})
        ws2 = next(m for m in out2 if m.get("type") == "world_state")
        assert (ws2.get("last_invite_from") or {}).get("name") == "A", ws2

    asyncio.run(scenario())


def test_emote_soft_grace_snapshot_unit():
    """After soft reconnect, snapshot still shows emote peers."""
    from network import websocket_manager as wm
    from network.handlers._common import soft_reconnect_social_snapshot
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "wave", "to": "B"})
        await wm.manager.disconnect(1, a)
        a2 = FakeWS()
        await wm.manager.connect(1, a2, name="A", x=2, y=2, map_id=0)
        snap = soft_reconnect_social_snapshot(wm.manager, 1)
        assert snap["has_emote"], snap
        assert (snap["last_emote_to"] or {}).get("name") == "B"
        snap_b = soft_reconnect_social_snapshot(wm.manager, 2)
        assert (snap_b["last_emote_from"] or {}).get("name") == "A"

    asyncio.run(scenario())


def test_sync_emote_share_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for typ in ("wave", "share"):
            for _ in range(2):
                wm.manager.refund_chat(1)
            await handle_message(1, 10, {"type": typ, "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "sync"})
        ws = next(m for m in out if m.get("type") == "world_state")
        assert (ws.get("last_emote_to") or {}).get("name") == "B"
        assert (ws.get("last_share_to") or {}).get("name") == "B"

    asyncio.run(scenario())


def test_empty_snapshot_unit():
    from network import websocket_manager as wm
    from network.handlers._common import soft_reconnect_social_snapshot

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        snap = soft_reconnect_social_snapshot(wm.manager, 1)
        assert snap["has_share"] is False
        assert snap["has_emote"] is False
        assert snap["has_invite"] is False
        assert snap["last_emote_to"] is None
        assert snap["last_invite_from"] is None

    asyncio.run(scenario())
