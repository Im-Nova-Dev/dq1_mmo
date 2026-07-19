"""v0.5.110 adversarial: multi filter tokens, mute matrix, find residual tokens."""

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


def test_find_strips_all_filter_tokens_unit():
    """Regression: second zone:/afk: token must not become a name prefix."""
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)  # town
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)  # field

        # Last zone wins; residual must not zero results
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "find", "query": "zone:town zone:field"}
        )
        f = next(m for m in out if m.get("type") == "find")
        assert f.get("zone") == "field", f
        assert int(f.get("count") or 0) >= 1, f
        assert "zone:" not in str(f.get("query") or "").replace("zone:field", ""), f
        # query should only list one zone filter
        q = str(f.get("query") or "")
        assert q.count("zone:") == 1, q
        names = [p.get("name") for p in (f.get("players") or [])]
        assert "B" in names, names

        _c, _u, out2, _ = await handle_message(
            1, 10, {"type": "find", "query": "zone:field zone:town"}
        )
        f2 = next(m for m in out2 if m.get("type") == "find")
        assert f2.get("zone") == "town", f2
        assert "A" in [p.get("name") for p in (f2.get("players") or [])], f2

        # Conflicting afk: last wins; no residual token as name
        wm.manager.set_afk(2, True)
        _c, _u, out3, _ = await handle_message(
            1, 10, {"type": "find", "query": "afk:yes afk:no"}
        )
        f3 = next(m for m in out3 if m.get("type") == "find")
        assert f3.get("afk") is False, f3
        assert "afk:yes" not in str(f3.get("query") or ""), f3
        assert int(f3.get("count") or 0) >= 1, f3  # A not AFK matches afk:no

        # Name + double zone
        _c, _u, out4, _ = await handle_message(
            1, 10, {"type": "find", "query": "B zone:town zone:field"}
        )
        f4 = next(m for m in out4 if m.get("type") == "find")
        assert f4.get("zone") == "field", f4
        assert int(f4.get("count") or 0) == 1, f4
        assert (f4.get("players") or [{}])[0].get("name") == "B"

    asyncio.run(scenario())


def test_ignore_blocks_private_social_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=3, y=2, map_id=0)
        await handle_message(1, 10, {"type": "ignore", "name": "B"})
        for _ in range(4):
            wm.manager.refund_chat(2)
        a.sent.clear()
        for kind, payload in (
            ("whisper", {"type": "whisper", "to": "A", "text": "hi"}),
            ("invite", {"type": "invite", "to": "A"}),
            ("poke", {"type": "poke", "to": "A"}),
            ("share", {"type": "share", "to": "A"}),
            ("wave", {"type": "wave", "to": "A"}),
        ):
            a.sent.clear()
            _c, _u, out, _ = await handle_message(2, 20, payload)
            errs = [m for m in out if m.get("type") == "error"]
            assert errs and "unavailable" in str(errs[0].get("reason") or "").lower(), (
                kind,
                out,
            )
            leaked = [
                m
                for m in a.sent
                if m.get("type") in ("invite", "share", "poke", "emote")
                or m.get("channel") == "whisper"
            ]
            assert not leaked, (kind, leaked)

    asyncio.run(scenario())


def test_afk_preserved_on_failed_private_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a = FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        wm.manager.set_afk(1, True, message="brb")
        for kind, payload in (
            ("whisper", {"type": "whisper", "to": "Ghost", "text": "x"}),
            ("thank", {"type": "thank", "to": "Ghost"}),
            ("poke", {"type": "poke", "to": "Ghost"}),
            ("share", {"type": "share", "to": "Ghost"}),
            ("wave", {"type": "wave", "to": "Ghost"}),
        ):
            for _ in range(2):
                wm.manager.refund_chat(1)
            wm.manager.set_afk(1, True, message="brb")
            await handle_message(1, 10, payload)
            meta = wm.manager.get_meta(1)
            assert meta and meta.get("afk") is True, (kind, meta)

    asyncio.run(scenario())


def test_find_no_coord_leak_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        _c, _u, out, _ = await handle_message(1, 10, {"type": "find", "query": "B"})
        f = next(m for m in out if m.get("type") == "find")
        for p in f.get("players") or []:
            assert "x" not in p and "y" not in p and "world_x" not in p, p
        await handle_message(1, 10, {"type": "invite", "to": "B"})
        _c, _u, out2, _ = await handle_message(1, 10, {"type": "social"})
        soc = next(m for m in out2 if m.get("type") == "social")
        for key in ("whisper", "invite_to", "invite_from", "emote"):
            blob = soc.get(key)
            if isinstance(blob, dict):
                assert "x" not in blob and "y" not in blob, (key, blob)

    asyncio.run(scenario())


def test_single_zone_still_works_unit():
    from network import websocket_manager as wm
    from network.message_handler import handle_message

    async def scenario():
        wm.reset_manager()
        a, b = FakeWS(), FakeWS()
        await wm.manager.connect(1, a, name="A", x=2, y=2, map_id=0)
        await wm.manager.connect(2, b, name="B", x=5, y=5, map_id=0)
        _c, _u, out, _ = await handle_message(
            1, 10, {"type": "find", "query": "zone:town"}
        )
        f = next(m for m in out if m.get("type") == "find")
        assert f.get("zone") == "town"
        assert int(f.get("count") or 0) >= 1
        names = [p.get("name") for p in (f.get("players") or [])]
        assert "A" in names

    asyncio.run(scenario())
