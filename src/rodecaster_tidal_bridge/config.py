from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w


class ConfigMissingError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class Config:
    midi_port_name_contains: str
    midi_channel: int
    midi_cc: int
    tidal_ws_url: str
    throttle_max_hz: int


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "rodecaster-tidal-bridge" / "config.toml"


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigMissingError(f"Config file not found: {path}")
    with path.open("rb") as f:
        data = tomllib.load(f)
    return Config(
        midi_port_name_contains=data["midi"]["port_name_contains"],
        midi_channel=int(data["midi"]["channel"]),
        midi_cc=int(data["midi"]["cc"]),
        tidal_ws_url=data["tidal"]["ws_url"],
        throttle_max_hz=int(data["throttle"]["max_hz"]),
    )


def save_config(cfg: Config, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "midi": {
            "port_name_contains": cfg.midi_port_name_contains,
            "channel": cfg.midi_channel,
            "cc": cfg.midi_cc,
        },
        "tidal": {"ws_url": cfg.tidal_ws_url},
        "throttle": {"max_hz": cfg.throttle_max_hz},
    }
    with path.open("wb") as f:
        tomli_w.dump(payload, f)
