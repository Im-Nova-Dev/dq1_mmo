"""v0.5.123: soft reconnect preserves /played session_started."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, t):
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_soft_reconnect_preserves_session_started_unit():
    async def scenario():
        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        started = float(mgr.get_meta(1)["session_started"])
        await asyncio.sleep(0.05)
        await mgr.disconnect(1, a)
        bag = mgr._soft_grace.get(1) or {}
        assert bag.get("session_started") == started, bag
        a2 = FakeWS()
        await mgr.connect(1, a2, name="A", x=2, y=2, map_id=0)
        started2 = float(mgr.get_meta(1)["session_started"])
        assert started2 == started, (started, started2)

    asyncio.run(scenario())


def test_soft_grace_expired_resets_session_unit():
    async def scenario():
        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        started = float(mgr.get_meta(1)["session_started"])
        await mgr.disconnect(1, a)
        bag = mgr._soft_grace.get(1)
        assert bag is not None
        bag["expires"] = time.monotonic() - 1.0
        a2 = FakeWS()
        await mgr.connect(1, a2, name="A", x=2, y=2, map_id=0)
        started2 = float(mgr.get_meta(1)["session_started"])
        # Expired bag must not restore the old stamp
        assert started2 != started, (started, started2)

    asyncio.run(scenario())


def test_fresh_connect_no_false_session_restore_unit():
    async def scenario():
        mgr = ConnectionManager()
        a = FakeWS()
        t0 = time.monotonic()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        started = float(mgr.get_meta(1)["session_started"])
        assert started >= t0 - 0.01

    asyncio.run(scenario())


def test_live_replace_still_preserves_unit():
    async def scenario():
        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        started = float(mgr.get_meta(1)["session_started"])
        await asyncio.sleep(0.03)
        await mgr.connect(1, b, name="A", x=2, y=2, map_id=0)
        assert float(mgr.get_meta(1)["session_started"]) == started, (
            started,
            mgr.get_meta(1)["session_started"],
        )
        assert a.closed is True

    asyncio.run(scenario())


def test_whisper_soft_grace_regression_unit():
    """session_started stash must not drop whisper soft-grace fields."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "whisper", "to": "B", "text": "hi"})
        started = float(wm.manager.get_meta(1)["session_started"])
        await wm.manager.disconnect(1, a)
        a2 = FakeWS()
        await wm.manager.connect(1, a2, name="A", x=2, y=2, map_id=0)
        assert float(wm.manager.get_meta(1)["session_started"]) == started
        lid, lname = wm.manager.last_whisper_from(1)
        assert lid == 2 and lname == "B"

    asyncio.run(scenario())
