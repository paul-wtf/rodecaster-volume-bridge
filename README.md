# rodecaster-volume-bridge

Brücke vom RodeCaster (Pro II/Duo) USB-MIDI zur Tidal-Lautstärke über das
[`@vmohammad/api`](https://github.com/vMohammad24/luna-plugins/tree/master/plugins/api)
TidaLuna-Plugin.

## Voraussetzungen

- Linux mit ALSA
- Python ≥ 3.11
- TidaLuna mit aktivem `@vmohammad/api` Plugin (Port `24123`)
- RodeCaster: gewünschter Fader im Companion / Display auf **MIDI Function** umgestellt

## Installation

```bash
git clone <repo> ~/git/rodecaster-volume-bridge
cd ~/git/rodecaster-volume-bridge
pip install --user .
```

## Setup (einmalig)

```bash
rodecaster-volume-bridge --learn
# bewege den Music-Fader, wenn aufgefordert
```

Das schreibt `~/.config/rodecaster-volume-bridge/config.toml` mit der erkannten
`channel`/`cc`-Kombination.

## Run

```bash
rodecaster-volume-bridge          # foreground
```

Oder als Service:

```bash
install -Dm644 systemd/rodecaster-volume-bridge.service \
  ~/.config/systemd/user/rodecaster-volume-bridge.service
systemctl --user daemon-reload
systemctl --user enable --now rodecaster-volume-bridge
journalctl --user -u rodecaster-volume-bridge -f
```

## Konfiguration

`~/.config/rodecaster-volume-bridge/config.toml`:

```toml
[midi]
port_name_contains = "RODECaster"
channel = 1
cc = 7

[tidal]
ws_url = "ws://localhost:24123"

[throttle]
max_hz = 100

[scale]
# Volume curve: volume = (midi/127)^curve_exponent * 100
# 1.0 = linear, 2.0 = square law (audio-taper default — finer at low end),
# 2.5–3.0 = even more low-end resolution at the cost of upper-end sensitivity.
curve_exponent = 2.0
```

## Entwicklung

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```
