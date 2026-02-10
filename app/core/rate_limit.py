import time
from dataclasses import dataclass


@dataclass
class RateLimitResult:
    allowed: bool
    wait_sec: int


# (user_id, key) -> last_ts (monotonic seconds)
_LAST_CALL: dict[tuple[int, str], float] = {}


def allow(user_id: int, key: str, interval_sec: int) -> bool:
    """Return True if call is allowed right now (min interval)."""
    return check(user_id, key, interval_sec).allowed


def check(user_id: int, key: str, interval_sec: int) -> RateLimitResult:
    now = time.monotonic()
    k = (int(user_id), str(key))
    last = _LAST_CALL.get(k)
    if last is None:
        _LAST_CALL[k] = now
        return RateLimitResult(allowed=True, wait_sec=0)

    elapsed = now - last
    if elapsed >= float(interval_sec):
        _LAST_CALL[k] = now
        return RateLimitResult(allowed=True, wait_sec=0)

    wait = int(float(interval_sec) - elapsed)
    if wait < 1:
        wait = 1
    return RateLimitResult(allowed=False, wait_sec=wait)
