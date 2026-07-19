"""Shared helpers for in-process WebSocket integration tests."""

from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request
import json
from typing import Any

import uvicorn
from main import app


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_server(port: int | None = None) -> tuple[uvicorn.Server, int, str, str]:
    """Start uvicorn in a daemon thread. Returns (server, port, http_base, ws_base)."""
    port = port or free_port()
    base = f"http://127.0.0.1:{port}"
    ws = f"ws://127.0.0.1:{port}/ws"
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{base}/health", timeout=0.2)
            return server, port, base, ws
        except Exception:
            time.sleep(0.05)
    raise RuntimeError(f"server did not start on {port}")


def stop_server(server: uvicorn.Server) -> None:
    """Request shutdown and wait for the lifespan cleanup to finish."""
    port = getattr(getattr(server, "config", None), "port", None)
    server.should_exit = True
    # Wait until health stops responding (lifespan close_db has run).
    for _ in range(80):
        if port is None:
            if not getattr(server, "started", True):
                break
            time.sleep(0.05)
            continue
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.1)
            time.sleep(0.05)
        except Exception:
            time.sleep(0.05)
            break
    else:
        time.sleep(0.2)


def http_json(
    base: str,
    method: str,
    path: str,
    data: dict | None = None,
    token: str | None = None,
) -> tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if data is None else json.dumps(data).encode()
    r = urllib.request.Request(f"{base}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return resp.status, {"raw": raw}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, {"raw": raw, "error": "non-json response"}


def register_char(
    base: str, email: str, username: str, char_name: str
) -> tuple[str, dict]:
    st, reg = http_json(
        base,
        "POST",
        "/auth/register",
        {"email": email, "password": "password", "username": username},
    )
    assert st == 201, reg
    token = reg["access_token"]
    st, ch = http_json(base, "POST", "/auth/characters", {"name": char_name}, token=token)
    assert st == 201, ch
    return token, ch
