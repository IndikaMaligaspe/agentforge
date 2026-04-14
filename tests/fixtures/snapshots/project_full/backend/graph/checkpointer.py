"""PostgreSQL-backed LangGraph checkpointer.

Uses a shared AsyncConnectionPool + AsyncPostgresSaver owned by this module.
Initialize from your ASGI framework's lifespan handler (FastAPI, Starlette)
BEFORE the graph is first invoked. Module-level graph compile MUST NOT call
`get_checkpointer()` directly — the saver is async-initialized.
"""
from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.config.memory_settings import DATABASE_URL

_pool: AsyncConnectionPool | None = None
_saver: AsyncPostgresSaver | None = None


async def init_checkpointer() -> AsyncPostgresSaver:
    """Open the pool, set up tables, and return the shared saver. Idempotent."""
    global _pool, _saver
    if _saver is not None:
        return _saver
    _pool = AsyncConnectionPool(
        DATABASE_URL,
        open=False,
        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
    )
    await _pool.open()
    _saver = AsyncPostgresSaver(_pool)
    await _saver.setup()
    return _saver


async def aclose_checkpointer() -> None:
    """Close the pool. Call from lifespan shutdown."""
    global _pool, _saver
    if _pool is not None:
        await _pool.close()
    _pool = None
    _saver = None


def get_checkpointer() -> AsyncPostgresSaver:
    """Return the already-initialized saver. Raises if init_checkpointer was not awaited."""
    if _saver is None:
        raise RuntimeError(
            "PostgresSaver not initialized. Await init_checkpointer() from your "
            "ASGI lifespan before invoking the graph."
        )
    return _saver