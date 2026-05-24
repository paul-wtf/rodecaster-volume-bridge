from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .bridge import run_bridge
from .config import (
    Config,
    ConfigMissingError,
    DEFAULT_CURVE_EXPONENT,
    default_config_path,
    load_config,
    save_config,
)
from .learn import detect_fader_cc
from .midi_source import find_port, list_input_ports, stream_cc_events


# Note: ALSA exposes the port without the Ø ligature. `aconnect -i` reports
# "RODECaster Duo:RODECaster Duo MIDI 1 28:0". If a different RodeCaster model
# uses a different ALSA name, pass --port-hint to override.
DEFAULT_PORT_HINT = "RODECaster"
DEFAULT_WS_URL = "ws://localhost:24123"
DEFAULT_HZ = 30


def main() -> int:
    parser = argparse.ArgumentParser(prog="rodecaster-tidal-bridge")
    parser.add_argument("--learn", action="store_true",
                        help="Detect which MIDI CC the music fader sends and save it.")
    parser.add_argument("--config", type=Path, default=default_config_path(),
                        help="Path to config TOML.")
    parser.add_argument("--port-hint", default=DEFAULT_PORT_HINT,
                        help="Substring to match against ALSA MIDI port names (learn mode only).")
    parser.add_argument("--learn-seconds", type=float, default=10.0)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        if args.learn:
            return asyncio.run(_cmd_learn(args))
        return asyncio.run(_cmd_run(args))
    except KeyboardInterrupt:
        return 0


async def _cmd_learn(args: argparse.Namespace) -> int:
    if find_port(args.port_hint) is None:
        print(f"No MIDI input contains {args.port_hint!r}.", file=sys.stderr)
        print(f"Available: {list_input_ports()}", file=sys.stderr)
        return 2

    print(f"Learn-mode: bewege jetzt den Music-Fader für {args.learn_seconds:.0f}s …")
    result = await detect_fader_cc(
        stream_cc_events(args.port_hint),
        timeout_s=args.learn_seconds,
    )
    if result is None:
        print("Keine MIDI-CC-Messages empfangen. Ist der Fader auf MIDI-Function gesetzt?",
              file=sys.stderr)
        return 1
    channel, cc = result
    cfg = Config(
        midi_port_name_contains=args.port_hint,
        midi_channel=channel,
        midi_cc=cc,
        tidal_ws_url=DEFAULT_WS_URL,
        throttle_max_hz=DEFAULT_HZ,
        curve_exponent=DEFAULT_CURVE_EXPONENT,
    )
    save_config(cfg, args.config)
    print(f"Erkannt: channel={channel} cc={cc}")
    print(f"Gespeichert nach {args.config}")
    return 0


async def _cmd_run(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
    except ConfigMissingError:
        print(f"Keine Config unter {args.config}.", file=sys.stderr)
        print('Erst `rodecaster-tidal-bridge --learn` ausführen.', file=sys.stderr)
        return 1
    if find_port(cfg.midi_port_name_contains) is None:
        print(f"No MIDI input contains {cfg.midi_port_name_contains!r}.", file=sys.stderr)
        print(f"Available: {list_input_ports()}", file=sys.stderr)
        return 2
    await run_bridge(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
