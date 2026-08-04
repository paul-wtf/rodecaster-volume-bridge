from __future__ import annotations

from typing import Protocol

from .config import Config, InvalidConfigError
from .spotify_sink import SpotifySink
from .tidal_sink import TidalSink


class VolumeSink(Protocol):
    """A destination for volume values in the range 0..100.

    set_volume() runs on the MIDI path: it must never block and never raise.
    Delivery is the sink's own problem, handled by its background task.

    start() may perform I/O and raise a fatal setup error (e.g. SpotifySink
    raises SessionBusUnavailableError when it cannot reach the D-Bus session
    bus); TidalSink's start() by contrast returns immediately and never
    raises. Callers must be prepared for start() to fail.
    """

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def set_volume(self, value: int) -> None: ...


def make_sink(cfg: Config) -> VolumeSink:
    if cfg.target == "spotify":
        return SpotifySink(bus_name=cfg.spotify_bus_name)
    if cfg.target == "tidal":
        if not cfg.tidal_ws_url:
            raise InvalidConfigError(
                "target is 'tidal' but no ws_url is configured; "
                "add a [tidal] block with ws_url."
            )
        return TidalSink(url=cfg.tidal_ws_url)
    raise InvalidConfigError(
        f"Unknown target {cfg.target!r}; expected 'tidal' or 'spotify'."
    )
