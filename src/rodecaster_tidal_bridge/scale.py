def midi_to_volume(midi_value: int) -> int:
    if not 0 <= midi_value <= 127:
        raise ValueError(f"MIDI value out of range [0,127]: {midi_value}")
    return round(midi_value * 100 / 127)
