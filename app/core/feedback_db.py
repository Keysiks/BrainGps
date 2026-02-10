"""SQLite feedback storage (MVP)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import aiosqlite

DB_PATH = "/var/lib/braingps/braingps.db"


async def init_db() -> None:
    """Create feedback table and indexes if they don't exist."""
    db_file = Path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  branch TEXT,
  node_id TEXT,
  strategy_id TEXT,

  rating INTEGER NOT NULL,
  reason_code TEXT,
  comment TEXT,

  model TEXT,
  latency_ms INTEGER,
  meta_json TEXT
);
"""
        )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_feedback_ts ON feedback(ts);")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_strategy ON feedback(strategy_id);"
        )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id);")
        await db.commit()


async def save_feedback(
    *,
    user_id: int,
    session_id: str,
    rating: int,
    reason_code: str | None = None,
    comment: str | None = None,
    branch: str | None = None,
    node_id: str | None = None,
    strategy_id: str | None = None,
    model: str | None = None,
    latency_ms: int | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Insert a feedback record."""
    ts = int(time.time())
    meta_json = json.dumps(meta or {}, ensure_ascii=False)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
INSERT INTO feedback (
  ts, user_id, session_id, branch, node_id, strategy_id,
  rating, reason_code, comment,
  model, latency_ms, meta_json
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
""",
            (
                ts,
                user_id,
                session_id,
                branch,
                node_id,
                strategy_id,
                rating,
                reason_code,
                comment,
                model,
                latency_ms,
                meta_json,
            ),
        )
        await db.commit()
