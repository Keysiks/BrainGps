from __future__ import annotations

import math
import time
from typing import Any

import aiosqlite

from app.core.analytics_db import DB_PATH


def _percentile_nearest_rank(values: list[int], p: float) -> int:
    """Nearest-rank percentile (p in [0.0..1.0])."""
    if not values:
        return 0
    if p <= 0:
        return min(values)
    if p >= 1:
        return max(values)

    values_sorted = sorted(values)
    # Nearest-rank: ceil(p * N)
    k = int(math.ceil(p * len(values_sorted)))
    idx = max(0, min(len(values_sorted) - 1, k - 1))
    return int(values_sorted[idx])


def _median(values: list[int]) -> int:
    return _percentile_nearest_rank(values, 0.5)


async def get_metrics(days: int = 7) -> dict[str, Any]:
    """Compute key product/tech metrics from analytics events."""
    since_ts = int(time.time()) - (days * 24 * 60 * 60)

    async with aiosqlite.connect(DB_PATH, timeout=2) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout=2000;")

        # --- Funnel ---
        unique_users = 0
        async with db.execute(
            "SELECT COUNT(DISTINCT user_id) AS c FROM events WHERE ts > ?",
            (since_ts,),
        ) as cur:
            row = await cur.fetchone()
            unique_users = int(row["c"] or 0) if row else 0

        sessions_started = 0
        async with db.execute(
            "SELECT COUNT(DISTINCT session_id) AS c FROM events WHERE event_name='start' AND ts > ?",
            (since_ts,),
        ) as cur:
            row = await cur.fetchone()
            sessions_started = int(row["c"] or 0) if row else 0

        activated_sessions = 0
        async with db.execute(
            """
            SELECT COUNT(DISTINCT e.session_id) AS c
            FROM events e
            WHERE e.event_name='final_generated'
              AND e.ts > ?
              AND e.session_id IN (
                SELECT session_id FROM events WHERE event_name='start' AND ts > ?
              )
            """,
            (since_ts, since_ts),
        ) as cur:
            row = await cur.fetchone()
            activated_sessions = int(row["c"] or 0) if row else 0

        activation_rate = (activated_sessions / sessions_started) if sessions_started else 0.0

        # Median TTFV per session: (first final_generated ts) - (start ts)
        ttfv_values: list[int] = []
        async with db.execute(
            """
            SELECT s.session_id, (MIN(f.ts) - s.ts) AS ttfv
            FROM events s
            JOIN events f
              ON f.session_id = s.session_id
             AND f.event_name = 'final_generated'
             AND f.ts > s.ts
            WHERE s.event_name = 'start'
              AND s.ts > ?
            GROUP BY s.session_id
            """,
            (since_ts,),
        ) as cur:
            for row in await cur.fetchall():
                ttfv = row["ttfv"]
                if isinstance(ttfv, int) and ttfv >= 0:
                    ttfv_values.append(ttfv)
        median_ttfv_s = _median(ttfv_values)

        # --- Quality proxies ---
        sessions_with_final = 0
        async with db.execute(
            "SELECT COUNT(DISTINCT session_id) AS c FROM events WHERE event_name='final_generated' AND ts > ?",
            (since_ts,),
        ) as cur:
            row = await cur.fetchone()
            sessions_with_final = int(row["c"] or 0) if row else 0

        sessions_with_regen = 0
        async with db.execute(
            """
            SELECT COUNT(DISTINCT session_id) AS c
            FROM events
            WHERE event_name='regenerate'
              AND ts > ?
              AND session_id IN (
                SELECT DISTINCT session_id FROM events WHERE event_name='final_generated' AND ts > ?
              )
            """,
            (since_ts, since_ts),
        ) as cur:
            row = await cur.fetchone()
            sessions_with_regen = int(row["c"] or 0) if row else 0

        regen_rate = (sessions_with_regen / sessions_with_final) if sessions_with_final else 0.0

        avg_response_chars = 0.0
        async with db.execute(
            """
            SELECT AVG(response_chars) AS avg
            FROM events
            WHERE event_name='final_generated'
              AND ts > ?
              AND response_chars IS NOT NULL
            """,
            (since_ts,),
        ) as cur:
            row = await cur.fetchone()
            avg_response_chars = float(row["avg"] or 0.0) if row else 0.0

        # --- Simulation ---
        sim_sessions = 0
        async with db.execute(
            "SELECT COUNT(DISTINCT session_id) AS c FROM events WHERE event_name='sim_start' AND ts > ?",
            (since_ts,),
        ) as cur:
            row = await cur.fetchone()
            sim_sessions = int(row["c"] or 0) if row else 0

        sim_start_rate = (sim_sessions / sessions_with_final) if sessions_with_final else 0.0

        # Avg sim turns per sim session (sessions that had sim_start in window)
        turns_per_sim_session: list[int] = []
        async with db.execute(
            """
            SELECT s.session_id, COALESCE(t.turns, 0) AS turns
            FROM (
              SELECT DISTINCT session_id
              FROM events
              WHERE event_name='sim_start' AND ts > ?
            ) s
            LEFT JOIN (
              SELECT session_id, COUNT(*) AS turns
              FROM events
              WHERE event_name='sim_turn' AND ts > ?
              GROUP BY session_id
            ) t ON t.session_id = s.session_id
            """,
            (since_ts, since_ts),
        ) as cur:
            for row in await cur.fetchall():
                turns = row["turns"]
                if isinstance(turns, int) and turns >= 0:
                    turns_per_sim_session.append(turns)

        avg_sim_turns = (sum(turns_per_sim_session) / len(turns_per_sim_session)) if turns_per_sim_session else 0.0

        hint_sessions = 0
        async with db.execute(
            """
            SELECT COUNT(DISTINCT session_id) AS c
            FROM events
            WHERE event_name='hint_click'
              AND ts > ?
              AND session_id IN (
                SELECT DISTINCT session_id FROM events WHERE event_name='sim_start' AND ts > ?
              )
            """,
            (since_ts, since_ts),
        ) as cur:
            row = await cur.fetchone()
            hint_sessions = int(row["c"] or 0) if row else 0

        draft_sessions = 0
        async with db.execute(
            """
            SELECT COUNT(DISTINCT session_id) AS c
            FROM events
            WHERE event_name='draft_click'
              AND ts > ?
              AND session_id IN (
                SELECT DISTINCT session_id FROM events WHERE event_name='sim_start' AND ts > ?
              )
            """,
            (since_ts, since_ts),
        ) as cur:
            row = await cur.fetchone()
            draft_sessions = int(row["c"] or 0) if row else 0

        hint_rate = (hint_sessions / sim_sessions) if sim_sessions else 0.0
        draft_rate = (draft_sessions / sim_sessions) if sim_sessions else 0.0

        # --- Technical ---
        latencies: list[int] = []
        async with db.execute(
            """
            SELECT latency_ms
            FROM events
            WHERE event_name='final_generated'
              AND ts > ?
              AND latency_ms IS NOT NULL
            """,
            (since_ts,),
        ) as cur:
            for row in await cur.fetchall():
                v = row["latency_ms"]
                if isinstance(v, int) and v >= 0:
                    latencies.append(v)

        p50_latency_ms = _percentile_nearest_rank(latencies, 0.50)
        p95_latency_ms = _percentile_nearest_rank(latencies, 0.95)

        llm_errors = 0
        async with db.execute(
            "SELECT COUNT(*) AS c FROM events WHERE event_name='llm_error' AND ts > ?",
            (since_ts,),
        ) as cur:
            row = await cur.fetchone()
            llm_errors = int(row["c"] or 0) if row else 0

        total_final = 0
        async with db.execute(
            "SELECT COUNT(*) AS c FROM events WHERE event_name='final_generated' AND ts > ?",
            (since_ts,),
        ) as cur:
            row = await cur.fetchone()
            total_final = int(row["c"] or 0) if row else 0

        denom = total_final + llm_errors
        llm_error_rate = (llm_errors / denom) if denom else 0.0

    return {
        "unique_users": unique_users,
        "sessions_started": sessions_started,
        "activation_rate": activation_rate,
        "median_ttfv_s": median_ttfv_s,
        "regen_rate": regen_rate,
        "avg_response_chars": avg_response_chars,
        "sim_start_rate": sim_start_rate,
        "avg_sim_turns": avg_sim_turns,
        "hint_rate": hint_rate,
        "draft_rate": draft_rate,
        "p50_latency_ms": p50_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "llm_error_rate": llm_error_rate,
    }


def format_metrics_message(metrics: dict[str, Any], days: int) -> str:
    # Markdown (aiogram) friendly output
    return (
        f"*Metrics (last {days}d)*\n\n"
        f"*Funnel*\n"
        f"- Unique users: {metrics['unique_users']}\n"
        f"- Sessions started: {metrics['sessions_started']}\n"
        f"- Activation: {metrics['activation_rate']*100:.1f}%\n"
        f"- Median TTFV: {metrics['median_ttfv_s']}s\n\n"
        f"*Quality proxies*\n"
        f"- Regenerate rate: {metrics['regen_rate']*100:.1f}%\n"
        f"- Avg response chars (final): {int(metrics['avg_response_chars'])}\n\n"
        f"*Simulation*\n"
        f"- Sim start rate: {metrics['sim_start_rate']*100:.1f}%\n"
        f"- Avg sim turns / sim session: {metrics['avg_sim_turns']:.1f}\n"
        f"- Hint usage rate: {metrics['hint_rate']*100:.1f}%\n"
        f"- Draft usage rate: {metrics['draft_rate']*100:.1f}%\n\n"
        f"*Technical*\n"
        f"- LLM latency p50: {metrics['p50_latency_ms']}ms\n"
        f"- LLM latency p95: {metrics['p95_latency_ms']}ms\n"
        f"- LLM error rate: {metrics['llm_error_rate']*100:.1f}%"
    )
