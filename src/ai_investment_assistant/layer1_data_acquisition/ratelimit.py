"""共通レートリミッタ（layer1_data_acquisition_design.md 6-2確定仕様）。

config/api_sources.yamlのrate_limit_per_minute等を守るため、Repository呼び出し
間隔を制御する。全Repository共通のユーティリティとして提供する。
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class RateLimiter:
    """簡易トークンバケット式のレートリミッタ（1分あたりの呼び出し数を制限する）。"""

    def __init__(
        self,
        rate_limit_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_limit_per_minute <= 0:
            raise ValueError("rate_limit_per_minute must be positive")
        self._min_interval = 60.0 / rate_limit_per_minute
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_call: Optional[float] = None

    def acquire(self) -> None:
        """次の呼び出しまで、必要な分だけブロックする。"""
        with self._lock:
            now = self._clock()
            if self._last_call is not None:
                elapsed = now - self._last_call
                wait = self._min_interval - elapsed
                if wait > 0:
                    self._sleep(wait)
                    now = self._clock()
            self._last_call = now
