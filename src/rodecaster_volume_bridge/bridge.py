from __future__ import annotations

import asyncio
import logging

from .config import Config
from .midi_source import stream_cc_events
from .scale import midi_to_volume
from .sink import make_sink
from .throttle import TrailingThrottle

log = logging.getLogger(__name__)


async def run_bridge(cfg: Config) -> None:
    sink = make_sink(cfg)
    try:
        await sink.start()
    except BaseException:
        # A sink that connected and then failed partway through its own
        # setup (e.g. SpotifySink after the D-Bus connect succeeds but
        # NameOwnerChanged subscription fails) must not leak that
        # connection. The throttle doesn't exist yet, so this can't just
        # be folded into the try/finally below.
        await sink.stop()
        raise
    interval = 1.0 / cfg.throttle_max_hz
    throttle = TrailingThrottle(min_interval_s=interval)

    log.info(
        "bridge running: target=%s, matching MIDI port %r, ch=%d cc=%d, "
        "throttle=%dHz, curve=%.2f",
        cfg.target, cfg.midi_port_name_contains, cfg.midi_channel, cfg.midi_cc,
        cfg.throttle_max_hz, cfg.curve_exponent,
    )
    try:
        async for ev in stream_cc_events(cfg.midi_port_name_contains):
            if ev.channel != cfg.midi_channel or ev.cc != cfg.midi_cc:
                continue
            volume = midi_to_volume(ev.value, cfg.curve_exponent)
            await throttle.submit(volume, sink.set_volume)
    finally:
        await throttle.flush()
        await sink.stop()
