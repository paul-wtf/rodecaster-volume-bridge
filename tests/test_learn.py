import asyncio
from typing import AsyncIterator

import pytest

from rodecaster_volume_bridge.learn import detect_fader_cc
from rodecaster_volume_bridge.midi_source import CCEvent


async def stream(events: list[CCEvent]) -> AsyncIterator[CCEvent]:
    for e in events:
        yield e
        await asyncio.sleep(0)  # cooperative


@pytest.mark.asyncio
async def test_detects_most_varied_cc():
    events = [
        # noisy button on (5, 17): only 2 distinct values
        CCEvent(channel=5, cc=17, value=0),
        CCEvent(channel=5, cc=17, value=127),
        CCEvent(channel=5, cc=17, value=0),
        CCEvent(channel=5, cc=17, value=127),
        # the fader on (1, 7): many distinct values
        *[CCEvent(channel=1, cc=7, value=v) for v in range(0, 128, 8)],
    ]
    result = await detect_fader_cc(stream(events), max_events=999, timeout_s=0.1)
    assert result == (1, 7)


@pytest.mark.asyncio
async def test_returns_none_when_no_cc_events():
    async def empty() -> AsyncIterator[CCEvent]:
        if False:
            yield  # pragma: no cover
    result = await detect_fader_cc(empty(), max_events=999, timeout_s=0.05)
    assert result is None
