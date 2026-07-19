import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

import config

_db: aiosqlite.Connection | None = None
# Monotonic generation so a lagging lifespan close cannot drop a newer connection.
_db_gen: int = 0
_db_owner_gen: int = 0
# Per-running-loop locks (module-level asyncio.Lock binds to the first loop — breaks tests).
_write_locks: dict[int, asyncio.Lock] = {}


def _write_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = id(loop)
    lock = _write_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _write_locks[key] = lock
    return lock


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialized")
    return _db


@asynccontextmanager
async def db_write():
    """Serialize SQLite writers (WAL still benefits from single-writer discipline)."""
    async with _write_lock():
        db = await get_db()
        yield db


async def init_db() -> int:
    """Open (or reopen) SQLite for the current event loop. Returns ownership generation."""
    global _db, _db_gen, _db_owner_gen
    _db_gen += 1
    my_gen = _db_gen

    old = _db
    _db = None
    if old is not None:
        try:
            await old.close()
        except Exception:
            pass

    # Read config.DATABASE_URL live (not a frozen import) so tests can rebind paths.
    db_url = config.DATABASE_URL
    Path(db_url).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_url)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")
    from database.migrations import run_migrations

    await run_migrations(conn)

    # If a newer init_db raced ahead, abandon this connection.
    if my_gen != _db_gen:
        try:
            await conn.close()
        except Exception:
            pass
        return my_gen

    _db = conn
    _db_owner_gen = my_gen
    return my_gen


async def close_db(owner_gen: int | None = None) -> None:
    """Close DB. If owner_gen is set, only close when this generation still owns _db."""
    global _db
    if owner_gen is not None and owner_gen != _db_owner_gen:
        return
    conn = _db
    if conn is None:
        return
    if owner_gen is not None and _db_owner_gen != owner_gen:
        return
    if _db is conn:
        _db = None
    try:
        await conn.close()
    except Exception:
        pass
    try:
        loop = asyncio.get_running_loop()
        _write_locks.pop(id(loop), None)
    except RuntimeError:
        pass
