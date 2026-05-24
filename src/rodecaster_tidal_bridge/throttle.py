from __future__ import annotations

import asyncio
import time as _time
from typing import Awaitable, Callable, Optional


class TrailingThrottle:
    """Trailing-edge throttle: first submit emits immediately; subsequent
    submits within `min_interval_s` overwrite a single pending value that
    fires once the window elapses."""

    def __init__(
        self,
        min_interval_s: float,
        time_fn: Callable[[], float] = _time.monotonic,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = min_interval_s
        self._time = time_fn
        self._sleep = sleep_fn
        self._last_send: float = float("-inf")
        self._pending_value: Optional[int] = None
        self._pending_emit: Optional[Callable[[int], None]] = None
        self._task: Optional[asyncio.Task[None]] = None

    async def submit(self, value: int, emit: Callable[[int], None]) -> None:
        now = self._time()
        task_idle = self._task is None or self._task.done()
        if now - self._last_send >= self._interval and task_idle:
            emit(value)
            self._last_send = now
            return
        self._pending_value = value
        self._pending_emit = emit
        if task_idle:
            self._task = asyncio.create_task(self._fire_later())

    async def _fire_later(self) -> None:
        wait = self._interval - (self._time() - self._last_send)
        if wait > 0:
            await self._sleep(wait)
        if self._pending_emit is not None and self._pending_value is not None:
            self._pending_emit(self._pending_value)
            self._last_send = self._time()
            self._pending_value = None
            self._pending_emit = None

    async def flush(self) -> None:
        if self._task is not None and not self._task.done():
            await self._task
