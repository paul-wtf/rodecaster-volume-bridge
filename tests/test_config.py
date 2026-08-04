from pathlib import Path
import textwrap

import pytest

from rodecaster_volume_bridge.config import Config, load_config, save_config, ConfigMissingError


def test_load_returns_typed_config(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        [midi]
        port_name_contains = "RODECaster"
        channel = 1
        cc = 7

        [tidal]
        ws_url = "ws://localhost:24123"

        [throttle]
        max_hz = 30

        [scale]
        curve_exponent = 2.5
    """).strip())

    cfg = load_config(cfg_file)

    assert cfg.midi_port_name_contains == "RODECaster"
    assert cfg.midi_channel == 1
    assert cfg.midi_cc == 7
    assert cfg.tidal_ws_url == "ws://localhost:24123"
    assert cfg.throttle_max_hz == 30
    assert cfg.curve_exponent == 2.5


def test_load_legacy_config_without_scale_section_defaults_to_2(tmp_path: Path):
    """A config written before the curve_exponent setting existed should still
    load and pick up a sensible default (2.0)."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        [midi]
        port_name_contains = "RODECaster"
        channel = 1
        cc = 7

        [tidal]
        ws_url = "ws://localhost:24123"

        [throttle]
        max_hz = 30
    """).strip())

    cfg = load_config(cfg_file)
    assert cfg.curve_exponent == 2.0


def test_load_missing_raises(tmp_path: Path):
    with pytest.raises(ConfigMissingError):
        load_config(tmp_path / "does-not-exist.toml")


def test_save_then_load_roundtrip(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg = Config(
        midi_port_name_contains="RODECaster",
        midi_channel=2,
        midi_cc=11,
        tidal_ws_url="ws://localhost:24123",
        throttle_max_hz=30,
        curve_exponent=2.0,
    )
    save_config(cfg, cfg_file)
    loaded = load_config(cfg_file)
    assert loaded == cfg


def test_save_creates_parent_dirs(tmp_path: Path):
    cfg_file = tmp_path / "nested" / "dir" / "config.toml"
    cfg = Config(
        midi_port_name_contains="X",
        midi_channel=1,
        midi_cc=7,
        tidal_ws_url="ws://localhost:24123",
        throttle_max_hz=30,
        curve_exponent=2.0,
    )
    save_config(cfg, cfg_file)
    assert cfg_file.exists()
