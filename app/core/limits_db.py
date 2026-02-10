import aiosqlite
import os
from datetime import date

DB_PATH = "data/limits.sqlite"


def today_str() -> str:
    """Server-local calendar day as YYYY-MM-DD."""
    return date.today().isoformat()


async def init_limits_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH, timeout=2) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA busy_timeout=2000;")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_counters (
              user_id INTEGER NOT NULL,
              day TEXT NOT NULL,
              counter_name TEXT NOT NULL,
              value INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (user_id, day, counter_name)
            )
            """
        )
        await db.commit()


async def get_counter(user_id: int, day: str, name: str) -> int:
    try:
        async with aiosqlite.connect(DB_PATH, timeout=2) as db:
            await db.execute("PRAGMA busy_timeout=2000;")
            cur = await db.execute(
                "SELECT value FROM daily_counters WHERE user_id=? AND day=? AND counter_name=?",
                (user_id, day, name),
            )
            row = await cur.fetchone()
            await cur.close()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        # Fail open for MVP (do not block user if DB is locked)
        return 0


async def inc_counter(user_id: int, day: str, name: str, delta: int = 1) -> int:
    try:
        async with aiosqlite.connect(DB_PATH, timeout=2) as db:
            await db.execute("PRAGMA busy_timeout=2000;")
            await db.execute(
                """
                INSERT INTO daily_counters (user_id, day, counter_name, value)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, day, counter_name)
                DO UPDATE SET value = value + excluded.value
                """,
                (user_id, day, name, int(delta)),
            )
            await db.commit()

            cur = await db.execute(
                "SELECT value FROM daily_counters WHERE user_id=? AND day=? AND counter_name=?",
                (user_id, day, name),
            )
            row = await cur.fetchone()
            await cur.close()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        # Fail open: return a value that won't block the flow.
        return 0
