import pytest

from rodecaster_volume_bridge.config import Config, InvalidConfigError
from rodecaster_volume_bridge.sink import make_sink
from rodecaster_volume_bridge.spotify_sink import SpotifySink
from rodecaster_volume_bridge.tidal_sink import TidalSink


def base_config(**overrides) -> Config:
    fields = dict(
        midi_port_name_contains="RODECaster",
        midi_channel=1,
        midi_cc=7,
        throttle_max_hz=100,
        target="spotify",
    )
    fields.update(overrides)
    return Config(**fields)


def test_builds_spotify_sink_with_configured_bus_name():
    sink = make_sink(base_config(
        target="spotify",
        spotify_bus_name="org.mpris.MediaPlayer2.spotifyd",
    ))
    assert isinstance(sink, SpotifySink)
    assert sink._bus_name == "org.mpris.MediaPlayer2.spotifyd"


def test_builds_tidal_sink_with_configured_url():
    sink = make_sink(base_config(
        target="tidal",
        tidal_ws_url="ws://localhost:24123",
    ))
    assert isinstance(sink, TidalSink)
    assert sink._url == "ws://localhost:24123"


def test_tidal_target_without_ws_url_raises_naming_the_block():
    with pytest.raises(InvalidConfigError) as excinfo:
        make_sink(base_config(target="tidal", tidal_ws_url=None))
    message = str(excinfo.value)
    assert "tidal" in message
    assert "ws_url" in message


def test_unknown_target_raises():
    with pytest.raises(InvalidConfigError) as excinfo:
        make_sink(base_config(target="deezer"))
    assert "deezer" in str(excinfo.value)
