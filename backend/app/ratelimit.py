"""Fixed-window rate limiting. Uses Redis when REDIS_URL is set (shared across instances), else in-process."""

from __future__ import annotations

import threading
import time

from fastapi import HTTPException, Request

from .config import get_settings

_lock = threading.Lock()
_buckets: dict[str, tuple[int, int]] = {}
_redis = None


def _redis_client():
    global _redis
    url = get_settings().redis_url
    if not url:
        return None
    if _redis is None:
        try:
            import redis  # type: ignore
            _redis = redis.Redis.from_url(url, socket_timeout=0.5)
        except Exception:  # noqa: BLE001 - redis optional
            return None
    return _redis


def hit(key: str, limit: int, window_s: int = 60) -> bool:
    """Record a hit; return True if within limit."""
    window = int(time.time() // window_s)
    r = _redis_client()
    if r is not None:
        try:
            k = f"x:rl:{key}:{window}"
            n = r.incr(k)
            if n == 1:
                r.expire(k, window_s + 1)
            return n <= limit
        except Exception:  # noqa: BLE001 - fall back to local
            pass
    with _lock:
        w, n = _buckets.get(key, (window, 0))
        if w != window:
            w, n = window, 0
        n += 1
        _buckets[key] = (w, n)
        if len(_buckets) > 50_000:
            _buckets.clear()
        return n <= limit


def client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown"))


def limit(request: Request, scope: str, per_min: int | None = None) -> None:
    n = per_min or get_settings().rate_limit_per_min
    if get_settings().environment == "test":
        return
    if not hit(f"{scope}:{client_key(request)}", n):
        raise HTTPException(status_code=429, detail="Too many requests; slow down and retry shortly.")
