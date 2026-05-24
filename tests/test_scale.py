import pytest

from rodecaster_tidal_bridge.scale import midi_to_volume


@pytest.mark.parametrize("midi,volume", [
    (0, 0),
    (127, 100),
    (64, 50),
    (63, 50),
    (1, 1),
])
def test_midi_to_volume(midi: int, volume: int):
    assert midi_to_volume(midi) == volume


@pytest.mark.parametrize("bad", [-1, 128, 200])
def test_midi_to_volume_rejects_out_of_range(bad: int):
    with pytest.raises(ValueError):
        midi_to_volume(bad)
