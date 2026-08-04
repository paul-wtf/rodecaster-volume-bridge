from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import tomli_w


class ConfigMissingError(FileNotFoundError):
    pass


class InvalidConfigError(ValueError):
    pass


DEFAULT_CURVE_EXPONENT = 2.0
DEFAULT_SPOTIFY_BUS_NAME = "org.mpris.MediaPlayer2.spotify"
DEFAULT_TIDAL_WS_URL = "ws://localhost:24123"
VALID_TARGETS = ("tidal", "spotify")


@dataclass(frozen=True)
class Config:
    midi_port_name_contains: str
    midi_channel: int
    midi_cc: int
    throttle_max_hz: int
    target: str
    tidal_ws_url: Optional[str] = None
    spotify_bus_name: str = DEFAULT_SPOTIFY_BUS_NAME
    curve_exponent: float = DEFAULT_CURVE_EXPONENT


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "rodecaster-volume-bridge" / "config.toml"


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigMissingError(f"Config file not found: {path}")
    with path.open("rb") as f:
        data = tomllib.load(f)

    target = data.get("target")
    if target not in VALID_TARGETS:
        valid = ", ".join(repr(t) for t in VALID_TARGETS)
        raise InvalidConfigError(
            f"Config {path}: 'target' is {target!r}, expected one of {valid}."
        )

    scale = data.get("scale", {})
    tidal = data.get("tidal", {})
    spotify = data.get("spotify", {})
    return Config(
        midi_port_name_contains=data["midi"]["port_name_contains"],
        midi_channel=int(data["midi"]["channel"]),
        midi_cc=int(data["midi"]["cc"]),
        throttle_max_hz=int(data["throttle"]["max_hz"]),
        target=target,
        tidal_ws_url=tidal.get("ws_url"),
        spotify_bus_name=spotify.get("bus_name", DEFAULT_SPOTIFY_BUS_NAME),
        curve_exponent=float(scale.get("curve_exponent", DEFAULT_CURVE_EXPONENT)),
    )


def save_config(cfg: Config, path: Path) -> None:
    """Write the config. Both target blocks are always written so switching
    targets later is a one-line edit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "target": cfg.target,
        "midi": {
            "port_name_contains": cfg.midi_port_name_contains,
            "channel": cfg.midi_channel,
            "cc": cfg.midi_cc,
        },
        "spotify": {"bus_name": cfg.spotify_bus_name},
        "tidal": {"ws_url": cfg.tidal_ws_url or DEFAULT_TIDAL_WS_URL},
        "throttle": {"max_hz": cfg.throttle_max_hz},
        "scale": {"curve_exponent": cfg.curve_exponent},
    }
    with path.open("wb") as f:
        tomli_w.dump(payload, f)
