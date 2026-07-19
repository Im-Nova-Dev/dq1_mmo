"""v0.5.127: status handler extract · multiplayer census on sheet."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.handlers import status as status_handlers


def test_status_module_extracted_unit():
    assert "status" in status_handlers.STATUS_TYPES
    assert "me" in status_handlers.STATUS_TYPES
    assert "whoami" in status_handlers.STATUS_TYPES
    assert "stats" in status_handlers.STATUS_TYPES


def test_status_nearby_census_unit(tmp_path, monkeypatch):
    import asyncio
    import json

    from network import websocket_manager as wm
    from network.message_handler import handle_message
    from tests.ws_helpers import register_char, start_server, stop_server

    db_path = tmp_path / "st.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "sta@ex.com", "Sa", "StatA")
        tb, cb = register_char(base, "stb@ex.com", "Sb", "StatB")

        async def flow():
            import websockets
            import time

            async def auth(ws, token, cid):
                await ws.send(
                    json.dumps({"type": "auth", "token": token, "character_id": cid})
                )
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 1))
                    if m.get("type") == "auth_ok":
                        return m

            async with websockets.connect(ws_url) as wa, websockets.connect(
                ws_url
            ) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await asyncio.sleep(0.2)
                await wa.send(json.dumps({"type": "status"}))
                deadline = time.monotonic() + 5
                st = None
                while time.monotonic() < deadline:
                    m = json.loads(await asyncio.wait_for(wa.recv(), 1))
                    if m.get("type") == "status":
                        st = m
                        break
                assert st and st.get("type") == "status", st
                you = st.get("you") or {}
                assert "nearby_count" in you, you
                assert st.get("nearby_count") is not None
                assert "online" in st
                assert isinstance(st.get("message"), str) and st.get("message")
                assert "HP" in st["message"] or "online" in st["message"].lower()

        asyncio.run(flow())
    finally:
        stop_server(server)


def test_status_social_summary_unit(tmp_path, monkeypatch):
    import asyncio
    import json
    import time

    from tests.ws_helpers import register_char, start_server, stop_server

    db_path = tmp_path / "sts.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import config
    import database.db as dbmod

    config.DATABASE_URL = str(db_path)
    asyncio.run(dbmod.close_db())

    server, _p, base, ws_url = start_server()
    try:
        ta, ca = register_char(base, "ss@ex.com", "Ss", "SocA")
        tb, cb = register_char(base, "ss2@ex.com", "Tt", "SocB")

        async def flow():
            import websockets

            async def auth(ws, token, cid):
                await ws.send(
                    json.dumps({"type": "auth", "token": token, "character_id": cid})
                )
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 1))
                    if m.get("type") == "auth_ok":
                        return

            async def recv_status(ws):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 1))
                    if m.get("type") == "status":
                        return m

            async with websockets.connect(ws_url) as wa, websockets.connect(
                ws_url
            ) as wb:
                await auth(wa, ta, ca["id"])
                await auth(wb, tb, cb["id"])
                await asyncio.sleep(0.85)
                await wa.send(
                    json.dumps({"type": "whisper", "to": "SocB", "text": "hi"})
                )
                # drain chat/errors
                end = time.monotonic() + 1.0
                while time.monotonic() < end:
                    try:
                        await asyncio.wait_for(wa.recv(), 0.2)
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                await wa.send(json.dumps({"type": "status"}))
                st = await recv_status(wa)
                assert st.get("has_social") is True or "Social" in str(
                    st.get("message") or ""
                ), st

        asyncio.run(flow())
    finally:
        stop_server(server)
