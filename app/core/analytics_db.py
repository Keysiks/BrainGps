import aiosqlite
import json
import time
import os

DB_PATH = "data/analytics.sqlite"

async def init_analytics_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH, timeout=2) as db:
        # Better concurrency for many short inserts
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA busy_timeout=2000;")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,

                event_name TEXT NOT NULL,
                branch TEXT,
                node_id TEXT,
                strategy_id TEXT,

                latency_ms INTEGER,
                model TEXT,
                prompt_chars INTEGER,
                response_chars INTEGER,

                meta_json TEXT
            )
            """
        )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_event ON events(event_name)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_strategy ON events(strategy_id)")
        await db.commit()

async def track_event(
    user_id: int,
    session_id: str,
    event_name: str,
    branch: str | None = None,
    node_id: str | None = None,
    strategy_id: str | None = None,
    latency_ms: int | None = None,
    model: str | None = None,
    prompt_chars: int | None = None,
    response_chars: int | None = None,
    meta: dict | None = None
) -> None:
    try:
        meta_json = None
        if isinstance(meta, dict) and meta:
            meta_json = json.dumps(meta, ensure_ascii=False)

        async with aiosqlite.connect(DB_PATH, timeout=2) as db:
            await db.execute("PRAGMA busy_timeout=2000;")
            await db.execute(
                """
                INSERT INTO events (
                    ts, user_id, session_id, event_name, branch, node_id, strategy_id,
                    latency_ms, model, prompt_chars, response_chars, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(time.time()),
                    user_id,
                    session_id,
                    event_name,
                    branch,
                    node_id,
                    strategy_id,
                    latency_ms,
                    model,
                    prompt_chars,
                    response_chars,
                    meta_json,
                ),
            )
            await db.commit()
    except Exception:
        # Fail silently (incl. DB locked)
        pass
