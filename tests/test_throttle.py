import asyncio
from typing import Callable

import pytest

from rodecaster_tidal_bridge.throttle import TrailingThrottle


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


@pytest.mark.asyncio
async def test_first_call_emits_immediately():
    sent: list[int] = []
    clock = FakeClock()
    throttle = TrailingThrottle(min_interval_s=0.033, time_fn=clock.time, sleep_fn=asyncio.sleep)
    await throttle.submit(50, lambda v: sent.append(v))
    assert sent == [50]


@pytest.mark.asyncio
async def test_burst_only_first_and_last_emit():
    """Rapid submits within the throttle window: first goes through immediately,
    intermediates are dropped, only the most-recent pending value emits at the
    end of the window."""
    sent: list[int] = []
    clock = FakeClock()
    throttle = TrailingThrottle(min_interval_s=0.033, time_fn=clock.time, sleep_fn=clock_sleep(clock))

    await throttle.submit(10, lambda v: sent.append(v))   # immediate
    clock.advance(0.005)
    await throttle.submit(20, lambda v: sent.append(v))   # pending
    clock.advance(0.005)
    await throttle.submit(30, lambda v: sent.append(v))   # overwrites pending
    # let any pending timer fire
    await asyncio.sleep(0)
    clock.advance(0.05)
    await asyncio.sleep(0)
    await throttle.flush()

    assert sent == [10, 30]


@pytest.mark.asyncio
async def test_after_window_next_call_is_immediate_again():
    sent: list[int] = []
    clock = FakeClock()
    throttle = TrailingThrottle(min_interval_s=0.033, time_fn=clock.time, sleep_fn=clock_sleep(clock))

    await throttle.submit(10, lambda v: sent.append(v))
    clock.advance(0.05)
    await throttle.submit(99, lambda v: sent.append(v))
    await throttle.flush()
    assert sent == [10, 99]


def clock_sleep(clock: FakeClock) -> Callable[[float], "asyncio.Future"]:
    async def _sleep(dt: float) -> None:
        clock.advance(dt)
    return _sleep
