"""v0.5.145: chat extract · AOI nearby · zone · global · channel whisper."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import chat
from network.websocket_manager import ConnectionManager


class FakeWS:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.closed = False
        self.fail = fail

    async def send_text(self, t):
        if self.fail:
            raise ConnectionError("socket dead")
        self.sent.append(json.loads(t) if isinstance(t, str) else t)

    async def close(self, *a, **k):
        self.closed = True


def _bind(mgr):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.chat as ch
    import network.handlers.whisper as wh

    old = (wm.manager, common.manager, ch.manager, wh.manager)
    wm.manager = mgr
    common.manager = mgr
    ch.manager = mgr
    wh.manager = mgr
    return old


def _restore(old):
    from network import websocket_manager as wm
    import network.handlers._common as common
    import network.handlers.chat as ch
    import network.handlers.whisper as wh

    wm.manager, common.manager, ch.manager, wh.manager = old


def test_chat_module_extracted_unit():
    assert "chat" in chat.CHAT_TYPES or "chat" in chat.ALL_TYPES
    assert "yell" in chat.ALL_TYPES
    assert "s" in chat.ALL_TYPES
    assert "g" in chat.ALL_TYPES


def test_nearby_chat_aoi_unit():
    async def scenario():
        import network.handlers.chat as ch

        mgr = ConnectionManager()
        a, b, c = FakeWS(), FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Near", x=3, y=2, map_id=0)
        await mgr.connect(3, c, name="Far", x=18, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ch.handle(1, 1, {"type": "s", "text": "hi near"}, outbound)
            m = outbound[0]
            assert m.get("channel") == "nearby"
            assert m.get("text") == "hi near"
            assert "online" in m and "nearby_count" in m
            peer_near = [s for s in b.sent if s.get("text") == "hi near"]
            peer_far = [s for s in c.sent if s.get("text") == "hi near"]
            assert peer_near, b.sent
            assert not peer_far, c.sent
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_global_chat_unit():
    async def scenario():
        import network.handlers.chat as ch

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Far", x=18, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ch.handle(1, 1, {"type": "g", "text": "all hear"}, outbound)
            m = outbound[0]
            assert m.get("channel") == "global"
            peer = next(s for s in b.sent if s.get("text") == "all hear")
            assert peer.get("channel") == "global"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_yell_zone_unit():
    async def scenario():
        import network.handlers.chat as ch

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        # both in town-ish coords
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Townie", x=4, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ch.handle(1, 1, {"type": "yell", "text": "zone yo"}, outbound)
            m = outbound[0]
            assert m.get("channel") == "zone"
            assert m.get("zone") in ("town", "field", "dungeon")
            peer = next(s for s in b.sent if s.get("text") == "zone yo")
            assert peer.get("channel") == "zone"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_reserved_channel_no_rate_unit():
    async def scenario():
        import network.handlers.chat as ch

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ch.handle(
                1,
                1,
                {"type": "chat", "channel": "system", "text": "hack"},
                outbound,
            )
            assert outbound[0].get("reason") == "reserved channel"
            # Immediate real chat must still work (no rate burn)
            out2: list[dict] = []
            await ch.handle(1, 1, {"type": "g", "text": "ok"}, out2)
            assert out2[0].get("channel") == "global"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_channel_whisper_delegates_unit():
    async def scenario():
        import network.handlers.chat as ch

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ch.handle(
                1,
                1,
                {
                    "type": "chat",
                    "channel": "whisper",
                    "to": "Guest",
                    "text": "psst",
                },
                outbound,
            )
            m = outbound[0]
            assert m.get("channel") == "whisper"
            assert m.get("text") == "psst"
            peer = next(s for s in b.sent if s.get("text") == "psst")
            assert peer.get("channel") == "whisper"
            assert mgr.last_whisper_from(2)[0] == 1
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_channel_whisper_fail_restore_afk_unit():
    async def scenario():
        import network.handlers.chat as ch

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Guest", x=3, y=2, map_id=0)
        mgr.set_afk(1, True, message="lunch")

        async def fail_send(cid, payload):
            return False

        old_send = mgr.send
        mgr.send = fail_send  # type: ignore
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ch.handle(
                1,
                1,
                {
                    "type": "chat",
                    "channel": "whisper",
                    "to": "Guest",
                    "text": "psst",
                },
                outbound,
            )
            assert any(o.get("reason") == "player not online" for o in outbound)
            assert mgr.get_meta(1).get("afk") is True
            assert mgr.get_meta(1).get("afk_message") == "lunch"
        finally:
            mgr.send = old_send  # type: ignore
            _restore(old)

    asyncio.run(scenario())


def test_empty_chat_blocked_unit():
    async def scenario():
        import network.handlers.chat as ch

        mgr = ConnectionManager()
        a = FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ch.handle(1, 1, {"type": "g", "text": ""}, outbound)
            assert outbound[0].get("reason") == "empty chat"
        finally:
            _restore(old)

    asyncio.run(scenario())


def test_ignore_blocks_nearby_peer_unit():
    async def scenario():
        import network.handlers.chat as ch

        mgr = ConnectionManager()
        a, b = FakeWS(), FakeWS()
        await mgr.connect(1, a, name="Hero", x=2, y=2, map_id=0)
        await mgr.connect(2, b, name="Mutee", x=3, y=2, map_id=0)
        mgr.ignore_player(2, 1)  # Mutee ignores Hero
        old = _bind(mgr)
        try:
            outbound: list[dict] = []
            await ch.handle(1, 1, {"type": "s", "text": "muted?"}, outbound)
            assert outbound[0].get("channel") == "nearby"
            assert not any(s.get("text") == "muted?" for s in b.sent)
        finally:
            _restore(old)

    asyncio.run(scenario())
