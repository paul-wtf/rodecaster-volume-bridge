from __future__ import annotations

from typing import Protocol, runtime_checkable

from .config import Config, InvalidConfigError
from .spotify_sink import SpotifySink
from .tidal_sink import TidalSink


@runtime_checkable
class VolumeSink(Protocol):
    """A destination for volume values in the range 0..100.

    set_volume() runs on the MIDI path: it must never block and never raise.
    Delivery is the sink's own problem, handled by its background task.
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
