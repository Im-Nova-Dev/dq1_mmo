"""v0.5.109 multiplayer reliability: pending/lastinvite zone badges + find you flag."""

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


def test_pending_includes_zone_and_combat_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        wm.manager.set_in_combat(2, True)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "pending"})
        p = next(m for m in out if m.get("type") == "pending")
        outg = p.get("outgoing") or {}
        assert outg.get("name") == "B", p
        assert outg.get("zone") == "field", outg
        assert outg.get("in_combat") is True, outg
        msg = str(p.get("message") or "")
        assert "field" in msg and "fight" in msg, msg

        _c, _u, out2, _ = await handle_message(2, 20, {"type": "pending"})
        p2 = next(m for m in out2 if m.get("type") == "pending")
        inc = p2.get("incoming") or {}
        assert inc.get("name") == "A" and inc.get("zone") == "town", p2

    asyncio.run(scenario())


def test_lastinvite_zone_badge_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        wm.manager.set_afk(1, True)
        _c, _u, out, _ = await handle_message(2, 20, {"type": "lastinvite"})
        li = next(m for m in out if m.get("type") == "lastinvite")
        peer = li.get("peer") or {}
        assert peer.get("name") == "A", li
        assert peer.get("zone") == "town", peer
        assert peer.get("afk") is True, peer
        assert "town" in str(li.get("message") or "")
        assert "afk" in str(li.get("message") or "").lower()

    asyncio.run(scenario())


def test_find_marks_you_on_self_hit_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="Alpha", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="Alpine", x=5, y=5, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "find", "query": "Alp"})
        f = next(m for m in out if m.get("type") == "find")
        assert int(f.get("count") or 0) == 2, f
        by_name = {p.get("name"): p for p in (f.get("players") or [])}
        assert by_name["Alpha"].get("you") is True, by_name
        assert not by_name["Alpine"].get("you"), by_name

    asyncio.run(scenario())


def test_find_pending_multi_filter_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        wm.manager.set_afk(2, True)
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "find", "query": "@pending zone:field afk:yes"}
        )
        f = next(m for m in out if m.get("type") == "find")
        assert int(f.get("count") or 0) == 1 and not f.get("filtered"), f
        _c, _u, out2, _ = await handle_message(
            1, 10, {"type": "find", "query": "@pending zone:field afk:no"}
        )
        f2 = next(m for m in out2 if m.get("type") == "find")
        assert f2.get("filtered") is True and f2.get("filter") == "afk:no", f2
        assert f2.get("peer_zone") == "field", f2

    asyncio.run(scenario())


def test_pending_offline_peer_no_zone_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        await wm.manager.disconnect(2, b)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "pending"})
        p = next(m for m in out if m.get("type") == "pending")
        outg = p.get("outgoing") or {}
        assert outg.get("online") is False, outg
        assert outg.get("zone") is None, outg
        assert "offline" in str(p.get("message") or "").lower(), p

    asyncio.run(scenario())


def test_social_and_find_pending_regression_unit():
    """v0.5.108 filter extras still work alongside pending zones."""
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
        assert (soc.get("invite_to") or {}).get("zone") == "field", soc
        _c, _u, out2, _ = await handle_message(
            1, 10, {"type": "find", "query": "@pending zone:town"}
        )
        f = next(m for m in out2 if m.get("type") == "find")
        assert f.get("filtered") is True and f.get("peer_zone") == "field", f

    asyncio.run(scenario())
