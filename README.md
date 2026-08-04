# rodecaster-volume-bridge

Brücke vom RodeCaster (Pro II/Duo) USB-MIDI-Fader zur Lautstärke eines
Musik-Players. Genau ein **Target** ist aktiv, umschaltbar über die Config:

- **spotify** (Default) — setzt Spotifys eigene `Volume`-Property direkt über
  MPRIS/D-Bus (Session-Bus). Kein Plugin nötig, funktioniert mit dem
  Spotify-Desktop-Client.
- **tidal** — der ursprüngliche Weg, über eine WebSocket-Verbindung zum
  [`@vmohammad/api`](https://github.com/vMohammad24/luna-plugins/tree/master/plugins/api)
  TidaLuna-Plugin auf Port `24123`.

## Voraussetzungen

- Linux mit ALSA
- Python ≥ 3.11
- RodeCaster: gewünschter Fader im Companion / Display auf **MIDI Function**
  umgestellt

Je nach Target zusätzlich:

- **Spotify**: der Desktop-Client mit aktivem MPRIS. Der Standard-Bus-Name ist
  `org.mpris.MediaPlayer2.spotify`; Flatpak-Builds und `spotifyd` melden sich
  unter einem anderen Namen auf dem Bus an (siehe `bus_name` in der
  Konfiguration unten).
- **Tidal**: TidaLuna mit aktivem `@vmohammad/api`-Plugin (Port `24123`).

## Installation

```bash
git clone <repo> ~/git/rodecaster-volume-bridge
cd ~/git/rodecaster-volume-bridge
pip install --user .
```

Auf NixOS fehlen die ALSA-Header, die `python-rtmidi` zum Bauen braucht:

```bash
nix-shell -p pkg-config alsa-lib --run 'pip install --user .'
```

## Setup (einmalig)

```bash
rodecaster-volume-bridge --learn
# bewege den Music-Fader, wenn aufgefordert
```

Das schreibt `~/.config/rodecaster-volume-bridge/config.toml` mit der
erkannten `channel`/`cc`-Kombination. Spotify ist dabei das Default-Target;
für Tidal:

```bash
rodecaster-volume-bridge --learn --target tidal
```

Ein späterer Wechsel des Targets erfordert kein erneutes `--learn` — es
genügt, die `target`-Zeile in der Config zu ändern und den Service neu zu
starten.

## Run

```bash
rodecaster-volume-bridge  # foreground
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
target = "spotify"

[midi]
port_name_contains = "RODECaster"
channel = 1
cc = 7

[spotify]
bus_name = "org.mpris.MediaPlayer2.spotify"

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

`target` bestimmt, welcher der beiden Blöcke `[spotify]` / `[tidal]`
tatsächlich verwendet wird — beide werden immer geschrieben, damit ein
späterer Wechsel nur das Ändern dieser einen Zeile ist. `bus_name` muss
angepasst werden, wenn Spotify nicht als Standard-Desktop-Client läuft, z. B.
`org.mpris.MediaPlayer2.spotifyd` für spotifyd oder der abweichende Name
eines Flatpak-Builds.

## Entwicklung

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Auf NixOS ebenfalls über `nix-shell` wrappen, sonst schlägt der Build von
`python-rtmidi` an den fehlenden ALSA-Headern fehl:

```bash
nix-shell -p pkg-config alsa-lib --run '.venv/bin/pip install -e ".[dev]"'
```
