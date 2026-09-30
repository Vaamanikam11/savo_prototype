"""Basic abuse protection so a shared link cannot run up the model bill."""
import os
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


def access_code() -> str:
    return os.getenv("ACCESS_CODE", "")


def admin_token() -> str:
    return os.getenv("ADMIN_TOKEN", "")


def max_sessions_per_day() -> int:
    return int(os.getenv("MAX_SESSIONS_PER_DAY", "40"))


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """In-memory sliding window. Fine for a single-instance demo; use Redis for more."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, limit: int, window_s: int) -> None:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "Too many requests. Please wait a bit and try again.")
        q.append(now)

    def reset(self) -> None:
        self.hits.clear()


limiter = RateLimiter()


def require_access_code(request: Request) -> None:
    code = access_code()
    if not code:
        return
    given = request.headers.get("x-access-code", "")
    if not secrets.compare_digest(given.encode(), code.encode()):
        raise HTTPException(401, "Access code is incorrect.")


def require_admin(request: Request) -> None:
    token = admin_token()
    if not token:
        raise HTTPException(404, "Not found")
    given = request.headers.get("x-admin-token", "")
    if not secrets.compare_digest(given.encode(), token.encode()):
        raise HTTPException(401, "Invalid admin token.")
