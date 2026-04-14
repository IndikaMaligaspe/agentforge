"""
memory_settings.py — Environment-driven settings for LangGraph checkpoint storage.

The checkpointer (``backend/graph/checkpointer.py``) imports :data:`DATABASE_URL`
from this module so that the connection string is read from a single,
well-known location.

Required environment variable
------------------------------
DATABASE_URL
    Full async-capable PostgreSQL DSN, e.g.
    ``postgresql://user:pass@localhost:5432/mydb``
    Set this in ``.env`` (development) or via your deployment secrets manager.
"""
from __future__ import annotations

import os

# Connection string consumed by AsyncPostgresSaver via AsyncConnectionPool.
# Must use the plain postgresql:// scheme — psycopg does not accept the
# SQLAlchemy +psycopg suffix.
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/full_stack_agent",
)