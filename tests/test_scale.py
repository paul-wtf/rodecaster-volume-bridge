import pytest

from rodecaster_tidal_bridge.scale import midi_to_volume


@pytest.mark.parametrize("midi,volume", [
    (0, 0),
    (127, 100),
    (64, 50),
    (63, 50),
    (1, 1),
])
def test_midi_to_volume_linear_default(midi: int, volume: int):
    """exponent=1.0 (default) preserves the original linear mapping."""
    assert midi_to_volume(midi, exponent=1.0) == volume


@pytest.mark.parametrize("midi,volume", [
    (0, 0),
    (127, 100),
    (64, 25),       # (64/127)^2 = 0.254 → round → 25
    (32, 6),        # (32/127)^2 = 0.0635 → round → 6
    (95, 56),       # (95/127)^2 = 0.5594 → round → 56
])
def test_midi_to_volume_square_law(midi: int, volume: int):
    """exponent=2.0 (audio taper) compresses upper range, expands lower."""
    assert midi_to_volume(midi, exponent=2.0) == volume


def test_endpoints_invariant_under_exponent():
    """0 maps to 0 and 127 maps to 100 for any exponent."""
    for exp in [0.5, 1.0, 2.0, 2.5, 3.0]:
        assert midi_to_volume(0, exponent=exp) == 0
        assert midi_to_volume(127, exponent=exp) == 100


@pytest.mark.parametrize("bad", [-1, 128, 200])
def test_midi_to_volume_rejects_out_of_range(bad: int):
    with pytest.raises(ValueError):
        midi_to_volume(bad)


@pytest.mark.parametrize("bad_exp", [0.0, -0.5])
def test_midi_to_volume_rejects_nonpositive_exponent(bad_exp: float):
    with pytest.raises(ValueError):
        midi_to_volume(64, exponent=bad_exp)
