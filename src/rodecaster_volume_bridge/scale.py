def midi_to_volume(midi_value: int, exponent: float = 1.0) -> int:
    """Map MIDI value 0..127 to volume 0..100 using y = (x/127)**exponent.

    exponent=1.0 is linear. exponent>1 stretches the low end of the fader
    (finer control over quiet volumes); exponent<1 does the opposite.
    Endpoints always map to 0 and 100.
    """
    if not 0 <= midi_value <= 127:
        raise ValueError(f"MIDI value out of range [0,127]: {midi_value}")
    if exponent <= 0:
        raise ValueError(f"exponent must be positive: {exponent}")
    return round((midi_value / 127) ** exponent * 100)
