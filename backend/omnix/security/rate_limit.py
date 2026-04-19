"""
Rate limiting for auth endpoints (and optionally others).

Uses a simple token-bucket algorithm per IP address, stored in-memory.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Any

from omnix.logging_setup import get_logger

log = get_logger("omnix.security.rate_limit")


@dataclass
class _Bucket:
    tokens: float
    last_refill: float
    request_count: int = 0


class RateLimiter:
    """
    Token-bucket rate limiter.

    Default: 10 requests per minute on auth endpoints,
    1000 requests per minute on general API.
    """

    def __init__(
        self,
        auth_rate: int = 10,        # max requests per window
        auth_window: float = 60.0,  # window in seconds
        api_rate: int = 1000,
        api_window: float = 60.0,
    ):
        self.auth_rate = auth_rate
        self.auth_window = auth_window
        self.api_rate = api_rate
        self.api_window = api_window

        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def _get_client_ip(self, handler: Any) -> str:
        """Extract client IP from the request handler."""
        # Check X-Forwarded-For for reverse proxy setups
        forwarded = handler.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        # Check X-Real-IP
        real_ip = handler.headers.get("X-Real-IP", "")
        if real_ip:
            return real_ip.strip()
        return handler.client_address[0] if handler.client_address else "unknown"

    def _cleanup_old_buckets(self) -> None:
        """Remove buckets that haven't been used in 5 minutes."""
        now = time.time()
        if now - self._last_cleanup < 300:
            return
        self._last_cleanup = now
        cutoff = now - 300
        stale = [k for k, b in self._buckets.items() if b.last_refill < cutoff]
        for k in stale:
            del self._buckets[k]

    def check(self, handler: Any, is_auth: bool = False) -> bool:
        """
        Check if the request is within rate limits.
        Returns True if allowed, False if rate-limited.
        """
        ip = self._get_client_ip(handler)
        rate = self.auth_rate if is_auth else self.api_rate
        window = self.auth_window if is_auth else self.api_window

        key = f"{'auth' if is_auth else 'api'}:{ip}"
        now = time.time()

        with self._lock:
            self._cleanup_old_buckets()

            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=rate, last_refill=now)
                self._buckets[key] = bucket

            # Refill tokens based on elapsed time
            elapsed = now - bucket.last_refill
            refill = elapsed * (rate / window)
            bucket.tokens = min(rate, bucket.tokens + refill)
            bucket.last_refill = now

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                bucket.request_count += 1
                return True

            log.warning("rate limit exceeded: %s (key=%s)", ip, key)
            return False

    def send_rate_limit_response(self, handler: Any) -> None:
        """Send a 429 Too Many Requests response."""
        handler.send_response(429)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Retry-After", "60")
        handler.end_headers()
        import json
        body = json.dumps({
            "error": {
                "code": "rate_limited",
                "message": "Too many requests. Please try again later.",
            }
        }).encode()
        handler.wfile.write(body)

    def get_stats(self) -> dict:
        """Return rate limiter stats."""
        with self._lock:
            return {
                "active_buckets": len(self._buckets),
                "auth_rate": f"{self.auth_rate}/{self.auth_window}s",
                "api_rate": f"{self.api_rate}/{self.api_window}s",
            }
