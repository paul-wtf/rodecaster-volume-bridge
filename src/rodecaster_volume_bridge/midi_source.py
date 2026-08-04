from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import mido

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CCEvent:
    channel: int   # 1-16 (mido reports 0-15; we add 1)
    cc: int        # 0-127
    value: int     # 0-127


def list_input_ports() -> list[str]:
    return mido.get_input_names()


def find_port(name_contains: str) -> Optional[str]:
    for name in mido.get_input_names():
        if name_contains.lower() in name.lower():
            return name
    return None


async def stream_cc_events(
    name_contains: str,
    reconnect_poll_s: float = 1.0,
) -> AsyncIterator[CCEvent]:
    """Yield CC events from the first matching ALSA input. Reconnects forever
    if the port disappears."""
    loop = asyncio.get_running_loop()
    while True:
        port_name = find_port(name_contains)
        if port_name is None:
            log.warning(
                "no MIDI port containing %r; available: %s",
                name_contains, list_input_ports(),
            )
            await asyncio.sleep(reconnect_poll_s)
            continue
        log.info("opening MIDI port %r", port_name)
        queue: asyncio.Queue[CCEvent] = asyncio.Queue()

        def callback(msg: mido.Message) -> None:
            if msg.type != "control_change":
                return
            loop.call_soon_threadsafe(
                queue.put_nowait,
                CCEvent(channel=msg.channel + 1, cc=msg.control, value=msg.value),
            )

        try:
            with mido.open_input(port_name, callback=callback):
                while True:
                    yield await queue.get()
        except (OSError, IOError) as e:
            log.warning("MIDI port closed (%s); will reconnect", e)
            await asyncio.sleep(reconnect_poll_s)
