from pathlib import Path
import textwrap

import pytest

from rodecaster_volume_bridge.config import (
    Config,
    ConfigMissingError,
    InvalidConfigError,
    load_config,
    save_config,
)


def test_load_returns_typed_config(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        target = "tidal"

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
    assert cfg.target == "tidal"
    assert cfg.spotify_bus_name == "org.mpris.MediaPlayer2.spotify"


def test_load_legacy_config_without_scale_section_defaults_to_2(tmp_path: Path):
    """A config written before the curve_exponent setting existed should still
    load and pick up a sensible default (2.0)."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        target = "tidal"

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
        target="tidal",
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
        target="tidal",
        tidal_ws_url="ws://localhost:24123",
        throttle_max_hz=30,
        curve_exponent=2.0,
    )
    save_config(cfg, cfg_file)
    assert cfg_file.exists()


def test_load_spotify_target_without_tidal_block(tmp_path: Path):
    """A Spotify-only config needs no [tidal] section."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        target = "spotify"

        [midi]
        port_name_contains = "RODECaster"
        channel = 1
        cc = 7

        [throttle]
        max_hz = 100
    """).strip())

    cfg = load_config(cfg_file)

    assert cfg.target == "spotify"
    assert cfg.tidal_ws_url is None
    assert cfg.spotify_bus_name == "org.mpris.MediaPlayer2.spotify"


def test_load_custom_spotify_bus_name(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        target = "spotify"

        [midi]
        port_name_contains = "RODECaster"
        channel = 1
        cc = 7

        [spotify]
        bus_name = "org.mpris.MediaPlayer2.spotifyd"

        [throttle]
        max_hz = 100
    """).strip())

    assert load_config(cfg_file).spotify_bus_name == "org.mpris.MediaPlayer2.spotifyd"


def test_load_without_target_raises_with_valid_values_listed(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        [midi]
        port_name_contains = "RODECaster"
        channel = 1
        cc = 7

        [throttle]
        max_hz = 100
    """).strip())

    with pytest.raises(InvalidConfigError) as excinfo:
        load_config(cfg_file)
    assert "tidal" in str(excinfo.value)
    assert "spotify" in str(excinfo.value)


def test_load_unknown_target_raises(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        target = "deezer"

        [midi]
        port_name_contains = "RODECaster"
        channel = 1
        cc = 7

        [throttle]
        max_hz = 100
    """).strip())

    with pytest.raises(InvalidConfigError) as excinfo:
        load_config(cfg_file)
    assert "deezer" in str(excinfo.value)


def test_save_writes_both_target_blocks(tmp_path: Path):
    """Both blocks are written with defaults so switching targets is a
    one-line edit."""
    cfg_file = tmp_path / "config.toml"
    cfg = Config(
        midi_port_name_contains="RODECaster",
        midi_channel=1,
        midi_cc=7,
        throttle_max_hz=100,
        target="spotify",
    )
    save_config(cfg, cfg_file)

    text = cfg_file.read_text()
    assert "[tidal]" in text
    assert "[spotify]" in text
    assert 'target = "spotify"' in text


def test_save_then_load_roundtrip_spotify(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg = Config(
        midi_port_name_contains="RODECaster",
        midi_channel=2,
        midi_cc=11,
        throttle_max_hz=100,
        target="spotify",
        tidal_ws_url="ws://localhost:24123",
        spotify_bus_name="org.mpris.MediaPlayer2.spotify",
        curve_exponent=2.0,
    )
    save_config(cfg, cfg_file)
    assert load_config(cfg_file) == cfg
