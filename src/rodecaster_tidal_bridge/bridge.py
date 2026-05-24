from __future__ import annotations

import asyncio
import logging

from .config import Config
from .midi_source import stream_cc_events
from .scale import midi_to_volume
from .throttle import TrailingThrottle
from .tidal_sink import TidalSink

log = logging.getLogger(__name__)


async def run_bridge(cfg: Config) -> None:
    sink = TidalSink(url=cfg.tidal_ws_url)
    await sink.start()
    interval = 1.0 / cfg.throttle_max_hz
    throttle = TrailingThrottle(min_interval_s=interval)

    log.info(
        "bridge running: matching MIDI port %r, ch=%d cc=%d, throttle=%dHz",
        cfg.midi_port_name_contains, cfg.midi_channel, cfg.midi_cc, cfg.throttle_max_hz,
    )
    try:
        async for ev in stream_cc_events(cfg.midi_port_name_contains):
            if ev.channel != cfg.midi_channel or ev.cc != cfg.midi_cc:
                continue
            volume = midi_to_volume(ev.value)
            await throttle.submit(volume, sink.set_volume)
    finally:
        await throttle.flush()
        await sink.stop()
