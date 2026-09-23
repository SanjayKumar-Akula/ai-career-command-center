"""A tiny in-memory sliding-window rate limiter (no external dependencies).

Good enough for a single-process college project; swap for a Redis-backed
limiter if the app is ever scaled to multiple workers.
"""

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1, int(window_seconds))
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Return True if `key` is allowed to make a request right now."""
        now = time.monotonic()
        with self._lock:
            window = self._hits[key]
            cutoff = now - self.window_seconds
            while window and window[0] < cutoff:
                window.popleft()
            if len(window) >= self.max_requests:
                return False
            window.append(now)
            # opportunistic cleanup of other keys
            if len(self._hits) > 512:
                for stale_key in [k for k, q in self._hits.items() if not q]:
                    self._hits.pop(stale_key, None)
            return True
