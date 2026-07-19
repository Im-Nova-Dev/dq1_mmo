"""v0.5.108 multiplayer reliability: social find filter mismatch + zone peers."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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


def test_find_pending_zone_filter_mismatch_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        # A town, B field — social find with zone:town must filter B out
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "find", "query": "@pending zone:town"}
        )
        f = next(m for m in out if m.get("type") == "find")
        assert int(f.get("count") or 0) == 0, f
        assert f.get("filtered") is True, f
        assert f.get("filtered_peer") == "B", f
        assert f.get("filter") == "zone:town", f
        assert f.get("peer_zone") == "field", f
        assert "filtered" in str(f.get("message") or "").lower() or "online" in str(
            f.get("message") or ""
        ).lower(), f
        # Matching zone still returns the peer
        _c, _u, out2, _ = await handle_message(
            1, 10, {"type": "find", "query": "@pending zone:field"}
        )
        f2 = next(m for m in out2 if m.get("type") == "find")
        assert int(f2.get("count") or 0) == 1, f2
        assert not f2.get("filtered"), f2
        assert (f2.get("players") or [{}])[0].get("name") == "B"

    asyncio.run(scenario())


def test_find_pending_afk_and_combat_filter_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})

        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "find", "query": "@pending afk:yes"}
        )
        f = next(m for m in out if m.get("type") == "find")
        assert f.get("filtered") is True and f.get("filter") == "afk:yes", f

        wm.manager.set_afk(2, True)
        _c, _u, out2, _ = await handle_message(
            1, 10, {"type": "find", "query": "@pending afk:yes"}
        )
        f2 = next(m for m in out2 if m.get("type") == "find")
        assert int(f2.get("count") or 0) == 1 and not f2.get("filtered"), f2

        _c, _u, out3, _ = await handle_message(
            1, 10, {"type": "find", "query": "@pending combat:yes"}
        )
        f3 = next(m for m in out3 if m.get("type") == "find")
        assert f3.get("filtered") is True and f3.get("filter") == "combat:yes", f3

        wm.manager.set_in_combat(2, True)
        _c, _u, out4, _ = await handle_message(
            1, 10, {"type": "find", "query": "@pending combat:yes"}
        )
        f4 = next(m for m in out4 if m.get("type") == "find")
        assert int(f4.get("count") or 0) == 1 and not f4.get("filtered"), f4

    asyncio.run(scenario())


def test_find_last_zone_filter_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        for _ in range(2):
            wm.manager.refund_chat(1)
        await handle_message(1, 10, {"type": "whisper", "to": "B", "text": "hey"})
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "find", "query": "@last zone:town"}
        )
        f = next(m for m in out if m.get("type") == "find")
        assert f.get("filtered") is True, f
        assert f.get("filtered_peer") == "B", f
        assert f.get("peer_zone") == "field", f

    asyncio.run(scenario())


def test_social_peer_includes_zone_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out, _ = await handle_message(1, 10, {"type": "social"})
        soc = next(m for m in out if m.get("type") == "social")
        inv = soc.get("invite_to") or {}
        assert inv.get("name") == "B", soc
        assert inv.get("zone") == "field", inv
        assert "field" in str(soc.get("message") or ""), soc
        wm.manager.set_in_combat(2, True)
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "peers"})
        soc2 = next(m for m in out2 if m.get("type") == "social")
        inv2 = soc2.get("invite_to") or {}
        assert inv2.get("in_combat") is True, inv2
        assert "fight" in str(soc2.get("message") or ""), soc2

    asyncio.run(scenario())


def test_find_pending_empty_and_online_regression_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "find", "query": "@pending"})
        errs = [m for m in out if m.get("type") == "error"]
        assert errs and "pending" in str(errs[0].get("reason") or "").lower(), out

        b = FakeWS()
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        await wm.manager.disconnect(2, b)
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "find", "query": "@pending"})
        errs2 = [m for m in out2 if m.get("type") == "error"]
        assert errs2 and "online" in str(errs2[0].get("reason") or "").lower(), out2

    asyncio.run(scenario())
