# RodeCaster → Tidal MIDI Bridge — Design

**Datum:** 2026-05-24
**Autor:** Paul (mit Claude)
**Status:** Draft, awaiting review

## Ziel

Ein lokaler Python-Daemon, der Fader-Bewegungen am RodeCaster (Pro II/Duo) per USB-MIDI liest und die Tidal-Lautstärke über das [`@vmohammad/api`](https://github.com/vMohammad24/luna-plugins/tree/master/plugins/api) TidaLuna-Plugin (Port `24123`) in Echtzeit anpasst.

## Nicht-Ziele

- Bidirektionale Synchronisation (Tidal → Fader-LED/Motor) — RodeCaster hat keine Motor-Fader.
- Andere MIDI-Controls (Pan, Mute, Smart-Pads) — kann später ergänzt werden.
- GUI — CLI reicht.
- Steuerung anderer Apps (Spotify etc.).
- Cross-Host-Setup — wir nehmen an, dass MIDI-Quelle und Tidal auf demselben Linux-Rechner laufen.

## Umfeld / Annahmen

- **OS:** Arch Linux (Kernel 7.0.x), `/home/paul`.
- **MIDI-Stack:** ALSA via `python-rtmidi` (mido-Backend `rtmidi`).
- **Tidal:** TidaLuna-fähiger Client (`tidal-hifi-tidaluna`) läuft lokal.
- **API-Plugin:** `@vmohammad/api` ist in TidaLuna installiert, Server auf `localhost:24123` aktiv und vom User bestätigt.
- **RodeCaster-Konfig:** Der "Music"-Fader muss vom User vorher im RodeCaster-Companion / Display auf MIDI-Function umgeschaltet werden — sonst sendet er kein MIDI. Genaues CC# und MIDI-Channel sind initial unbekannt → Learn-Mode löst das.

## Architektur

```
┌─────────────┐  USB-MIDI (ALSA)  ┌──────────────────┐  ws://localhost:24123  ┌─────────────────┐
│  RodeCaster │ ─────────────────►│  Bridge          │ ──────────────────────►│  TidaLuna +     │
│  (Music-Fdr)│   CC# value 0-127 │  (Python daemon) │  {"action":"volume",   │  @vmohammad/api │
└─────────────┘                   └──────────────────┘   "volume": 0-100}     └─────────────────┘
```

Drei Module, jedes mit einer klaren Aufgabe:

### `midi_source.py`
- Öffnet das ALSA-MIDI-Input-Port des RodeCaster (Name-Matching auf `RØDECaster*` / konfigurierbar).
- Stellt Generator/AsyncIterator über CC-Messages: liefert Tupel `(channel: int, cc: int, value: int)`.
- Reagiert auf Device-Verschwinden mit Reconnect (Poll im 1 s-Intervall).
- Logged Open/Close-Events; **keine** Throttle/Mapping-Logik hier.

### `tidal_sink.py`
- Hält persistente WebSocket-Verbindung zu `ws://localhost:24123`.
- Stellt `set_volume(value: int)` bereit, der nicht-blockierend in eine Queue schreibt.
- Hintergrund-Coroutine sendet Queue-Inhalte; bei Verbindungsverlust exponentielles Backoff (start 0.5 s, max 5 s).
- Coalesces: wenn mehrere Volume-Updates in der Queue stehen, wird nur das jüngste gesendet.
- Verwendet `websockets`-Lib (Standard auf Arch via `python-websockets`).

### `bridge.py`
- CLI-Einstiegspunkt mit zwei Modi:
  - `bridge.py --learn` — sniffed MIDI-Messages für 10 s (oder bis User Enter drückt), schreibt das **am häufigsten** vorkommende `(channel, cc)`-Paar in die Config. Robust gegen versehentliche andere Bewegungen.
  - `bridge.py` (kein Arg) — Run-Mode, lädt Config, läuft als Service.
- Mapping: `value_127 → value_100` linear (`round(value * 100 / 127)`).
- Throttle: max **30 Updates/Sek** (33 ms Mindestabstand). Bei Bursts wird der letzte Wert nach Ablauf des Intervalls gesendet (trailing-edge).
- Config: TOML in `~/.config/rodecaster-tidal-bridge/config.toml`.

### Config-Format

```toml
[midi]
port_name_contains = "RØDECaster"   # Substring-Match gegen ALSA-Port-Namen
channel = 1                          # 1-16, vom learn-mode gefüllt
cc = 7                               # 0-127, vom learn-mode gefüllt

[tidal]
ws_url = "ws://localhost:24123"

[throttle]
max_hz = 30
```

## Daten-Fluss

1. `midi_source` empfängt MIDI-CC-Message.
2. `bridge.on_midi(ch, cc, value)` (trailing-edge throttle):
   - Wenn `(ch, cc)` ≠ konfiguriertes Pair → ignorieren.
   - Wenn letzter Send ≥ 33 ms her und kein Timer läuft → sofort senden, Zeitstempel merken.
   - Sonst: `pending_value` auf den jüngsten Wert setzen (überschreibt evtl. vorherigen pending). Falls noch kein Timer läuft, einen schedulen, der nach Ablauf des Intervalls den dann aktuellen `pending_value` sendet und sich selbst löscht.
3. `tidal_sink.set_volume()` legt in Queue ab. Hintergrund-Coroutine zieht das Element raus; falls die WebSocket-Verbindung gerade getrennt ist, kommen weitere Updates dahinter — vor dem Send wird die Queue auf das letzte Element reduziert (Coalescing als zweite Verteidigungslinie gegen Reconnect-Backlog).
4. `@vmohammad/api` setzt Tidal-Volume und antwortet mit `{type:"ok"}` — wir ignorieren die Response.

## Fehlerbehandlung

Validierung nur an Boundaries — Tooling/Library-Garantien werden vertraut.

| Fall | Verhalten |
|---|---|
| MIDI-Port nicht gefunden bei Start | Fehler-Log mit verfügbaren Ports auflisten, exit code 2. |
| MIDI-Port verschwindet zur Laufzeit | Warn-Log, Reconnect-Loop (1 s Poll) bis er wiederkommt. Bridge bleibt am Leben. |
| WebSocket Connect-Fail | Backoff-Reconnect; Bridge nimmt MIDI weiter entgegen, droppt Updates bis verbunden. |
| Config fehlt | Hinweis: `Run "bridge.py --learn" first.`, exit code 1. |
| Unerwartete API-Response | Ignorieren — wir feuern volume und vergessen. |

## Testing

| Was | Wie |
|---|---|
| `bridge.scale()` (127→100 Mapping) | Pure-function unit test, inkl. Grenzen 0, 127, 64. |
| Throttle | Inject Fake-Clock, MIDI-Stream simulieren, assert Anzahl Sends. |
| `tidal_sink` Coalescing & Reconnect | In-Memory WebSocket-Mock-Server, Verbindung droppen. |
| Learn-Mode CC-Detection | Stream mit dominantem CC + Noise, assert das richtige Pair gefunden wird. |
| **MIDI selbst** | **Nicht automatisiert** — manueller Smoke-Test mit echtem RodeCaster. |

Test-Stack: `pytest` + `pytest-asyncio`.

## Deployment / Lifecycle

- **Repo:** `/home/paul/git/rodecaster-tidal-bridge`
- **Install:** `pip install --user .` legt Konsolen-Skript `rodecaster-tidal-bridge` an.
- **Autostart:** `systemd --user` Unit `rodecaster-tidal-bridge.service`:
  ```ini
  [Unit]
  Description=RodeCaster → Tidal MIDI Bridge
  After=sound.target

  [Service]
  ExecStart=%h/.local/bin/rodecaster-tidal-bridge
  Restart=on-failure
  RestartSec=2

  [Install]
  WantedBy=default.target
  ```
- **Logs:** stdout/stderr → journalctl `--user -u rodecaster-tidal-bridge`.

## Projekt-Struktur

```
rodecaster-tidal-bridge/
├── pyproject.toml
├── README.md
├── src/
│   └── rodecaster_tidal_bridge/
│       ├── __init__.py
│       ├── bridge.py
│       ├── midi_source.py
│       └── tidal_sink.py
├── tests/
│   ├── test_bridge.py
│   ├── test_tidal_sink.py
│   └── test_learn_mode.py
├── systemd/
│   └── rodecaster-tidal-bridge.service
└── docs/
    └── superpowers/specs/
        └── 2026-05-24-rodecaster-tidal-midi-bridge-design.md
```

## Offene Punkte für Implementierung

- Exakter ALSA-Port-Name auf diesem System (per `aconnect -i` zur Laufzeit ermitteln, falls Match scheitert).
- Ob TidaLuna's WebSocket-Server CORS / Origin-Header verlangt — unwahrscheinlich, da localhost, aber zur Laufzeit prüfen.
