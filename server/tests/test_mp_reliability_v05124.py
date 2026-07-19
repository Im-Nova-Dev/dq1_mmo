"""v0.5.124: restored.played + welcome session timer on soft reconnect."""

from __future__ import annotations

import asyncio
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
        import json

        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def test_soft_restored_session_flag_unit():
    async def scenario():
        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        assert mgr.get_meta(1).get("soft_restored_session") is False
        started = float(mgr.get_meta(1)["session_started"])
        await mgr.disconnect(1, a)
        a2 = FakeWS()
        await mgr.connect(1, a2, name="A", x=2, y=2, map_id=0)
        meta = mgr.get_meta(1)
        assert meta.get("soft_restored_session") is True, meta
        assert float(meta["session_started"]) == started

    asyncio.run(scenario())


def test_live_replace_not_soft_restored_unit():
    async def scenario():
        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.connect(1, b, name="A", x=2, y=2, map_id=0)
        assert mgr.get_meta(1).get("soft_restored_session") is False

    asyncio.run(scenario())


def test_build_restored_includes_played_unit():
    from network.handlers._common import (
        build_soft_reconnect_restored,
        format_restored_welcome_bits,
        soft_reconnect_social_snapshot,
    )

    async def scenario():
        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.disconnect(1, a)
        a2 = FakeWS()
        await mgr.connect(1, a2, name="A", x=2, y=2, map_id=0)
        social = soft_reconnect_social_snapshot(mgr, 1)
        restored = build_soft_reconnect_restored(
            mgr,
            1,
            ignores_snap=[],
            social=social,
            repel_n=0,
            radiant_n=0,
        )
        assert restored.get("played") is True, restored
        bits = format_restored_welcome_bits(restored)
        assert "session timer" in bits, bits
        # first join style
        mgr2 = ConnectionManager()
        c = FakeWS()
        await mgr2.connect(2, c, name="B", x=2, y=2, map_id=0)
        social2 = soft_reconnect_social_snapshot(mgr2, 2)
        rest2 = build_soft_reconnect_restored(
            mgr2, 2, ignores_snap=[], social=social2, repel_n=0, radiant_n=0
        )
        assert rest2.get("played") is False, rest2

    asyncio.run(scenario())


def test_expired_grace_no_played_restore_unit():
    async def scenario():
        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="A", x=2, y=2, map_id=0)
        await mgr.disconnect(1, a)
        bag = mgr._soft_grace.get(1)
        assert bag is not None
        bag["expires"] = time.monotonic() - 1.0
        a2 = FakeWS()
        await mgr.connect(1, a2, name="A", x=2, y=2, map_id=0)
        assert mgr.get_meta(1).get("soft_restored_session") is False

    asyncio.run(scenario())


def test_format_welcome_bits_order_unit():
    from network.handlers._common import format_restored_welcome_bits

    bits = format_restored_welcome_bits(
        {
            "ignores": True,
            "last_whisper": True,
            "played": True,
            "repel": True,
            "radiant": False,
        }
    )
    assert bits[0] == "mute list"
    assert "session timer" in bits
    assert "buffs" in bits
