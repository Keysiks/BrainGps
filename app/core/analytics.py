from app.core.analytics_db import track_event as db_track_event

def infer_branch(node_id: str | None) -> str:
    if not node_id:
        return "unknown"
    node_id_lower = node_id.lower()
    if node_id_lower.startswith("work_") or "work" in node_id_lower:
        return "work"
    if node_id_lower.startswith("fam_") or "family" in node_id_lower:
        return "family"
    if node_id_lower.startswith("sos_") or "sos" in node_id_lower:
        return "sos"
    if node_id_lower.startswith("ex_") or "ex" in node_id_lower:
        return "exes"
    return "unknown"

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
    if branch is None and node_id is not None:
        branch = infer_branch(node_id)
    
    await db_track_event(
        user_id=user_id,
        session_id=session_id,
        event_name=event_name,
        branch=branch,
        node_id=node_id,
        strategy_id=strategy_id,
        latency_ms=latency_ms,
        model=model,
        prompt_chars=prompt_chars,
        response_chars=response_chars,
        meta=meta
    )
