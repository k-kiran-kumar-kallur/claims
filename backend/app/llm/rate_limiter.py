"""Per-model token-bucket rate limiter and circuit breaker (spec §5.6, §14.1)."""
from __future__ import annotations

import threading
import time
from collections import deque

from app.core.errors import CircuitOpenError


class RateLimiter:
    """Sliding-window limiter for requests-per-minute and tokens-per-minute."""

    def __init__(self, rpm: int, tpm: int):
        self.rpm, self.tpm = max(rpm, 1), max(tpm, 1)
        self._req: deque[float] = deque()
        self._tok: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def acquire(self, est_tokens: int = 1000, max_wait: float = 120.0) -> None:
        deadline = time.monotonic() + max_wait
        while True:
            with self._lock:
                now = time.monotonic()
                while self._req and now - self._req[0] > 60:
                    self._req.popleft()
                while self._tok and now - self._tok[0][0] > 60:
                    self._tok.popleft()
                used = sum(t for _, t in self._tok)
                if len(self._req) < self.rpm and used + est_tokens <= self.tpm:
                    self._req.append(now)
                    self._tok.append((now, est_tokens))
                    return
                wait = 60 - (now - self._req[0]) if self._req else 1.0
            if time.monotonic() + min(wait, 1.0) > deadline:
                return  # degrade gracefully: let the provider's 429 handling take over
            time.sleep(min(max(wait, 0.05), 1.0))


class CircuitBreaker:
    def __init__(self, failure_threshold: int, cooldown_seconds: int):
        self.failure_threshold, self.cooldown = failure_threshold, cooldown_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            if time.monotonic() - self._opened_at >= self.cooldown:
                self._opened_at = None  # half-open: allow a trial call
                self._failures = self.failure_threshold - 1
                return
            remaining = self.cooldown - (time.monotonic() - self._opened_at)
        raise CircuitOpenError(f"LLM circuit open; retry in {remaining:.0f}s", retry_after=remaining)

    def success(self) -> None:
        with self._lock:
            self._failures, self._opened_at = 0, None

    def failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = time.monotonic()

    @property
    def state(self) -> str:
        return "open" if self._opened_at is not None else "closed"
