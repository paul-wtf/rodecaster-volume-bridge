from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncIterator, Optional

from .midi_source import CCEvent


async def detect_fader_cc(
    events: AsyncIterator[CCEvent],
    max_events: int = 2000,
    timeout_s: float = 10.0,
) -> Optional[tuple[int, int]]:
    """Listen for up to `timeout_s` seconds (or `max_events` events) and return
    the (channel, cc) pair with the most distinct values — i.e. the fader,
    not a button or toggle. Returns None if no CC events arrive."""
    distinct: dict[tuple[int, int], set[int]] = defaultdict(set)
    count = 0

    async def consume() -> None:
        nonlocal count
        async for e in events:
            distinct[(e.channel, e.cc)].add(e.value)
            count += 1
            if count >= max_events:
                return

    try:
        await asyncio.wait_for(consume(), timeout=timeout_s)
    except asyncio.TimeoutError:
        pass

    if not distinct:
        return None
    return max(distinct.items(), key=lambda kv: len(kv[1]))[0]
