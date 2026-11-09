"""进程内滑动窗口限速。

只做两件事：登录尝试、webhook 调用。单进程部署，用不着 Redis；
每个键存最近一分钟的时间戳列表即可。
"""

from __future__ import annotations

import threading
import time
from collections import deque

WINDOW_SECONDS = 60.0


class SlidingWindow:
    def __init__(self, window: float = WINDOW_SECONDS) -> None:
        self.window = window
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, limit: int) -> bool:
        """记录一次调用。返回 False = 超限（本次也计数，防止绕过刷）。"""
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            cutoff = now - self.window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            bucket.append(now)
            return len(bucket) <= limit

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
