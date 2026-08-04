# Spotify-Target für die RodeCaster-Volume-Bridge — Design

**Datum:** 2026-08-04
**Autor:** Paul (mit Claude)
**Status:** Draft, awaiting review

## Ziel

Die bestehende Tidal-Bridge um Spotify als zweites Steuerziel erweitern: Fader-Bewegungen am RodeCaster sollen wahlweise die Tidal- **oder** die Spotify-Lautstärke setzen. Das Repo wird dabei von einem Tidal-spezifischen zu einem target-neutralen Projekt.

Die Funktionalität soll aus Nutzersicht identisch sein — Fader bewegen, Lautstärke folgt in Echtzeit. Eine 1:1-Nachbildung des Tidal-Transports ist ausdrücklich nicht gefordert.

## Nicht-Ziele

- Bidirektionale Synchronisation (Spotify → Fader) — RodeCaster hat keine Motor-Fader.
- Mehrere Targets gleichzeitig oder Auto-Erkennung des spielenden Players. Genau ein Target ist aktiv, festgelegt per Config.
- Spotify im Browser oder über Spotify Connect auf Fremdgeräten. Nur der lokale Desktop-Client.
- Andere Transport-Kommandos (Play/Pause/Skip), obwohl MPRIS sie anbieten würde.
- Migration der alten Config-Datei.

## Umfeld / Annahmen

Auf dem Zielsystem verifiziert (2026-08-04):

- **OS:** NixOS, Kernel 7.1.x, `/home/paul`.
- **Spotify:** Desktop-Client installiert (`/etc/profiles/per-user/paul/bin/spotify`) und laufend.
- **MPRIS:** `org.mpris.MediaPlayer2.spotify` ist auf dem Session-Bus präsent.
- **Volume-Property schreibbar:** Ein `Set` auf `org.mpris.MediaPlayer2.Player.Volume` mit `0.42` wurde angenommen und lieferte beim Zurücklesen `0.420005`; anschließend sauber auf `1.0` restauriert. Ältere Spotify-Linux-Builds ignorierten Schreibzugriffe hier — dieser tut es nicht.
- **Audio-Stack:** PipeWire mit `pipewire-pulse` aktiv (für dieses Design irrelevant, siehe Alternativen).
- **Python-D-Bus-Lib:** weder `dbus-fast` noch `jeepney` vorinstalliert; beide sind pip-installierbar und pure Python.

**Offene Verifikation:** Der Test hat bewiesen, dass Spotify den Wert annimmt und zurückliefert. Ob die Wiedergabe dadurch auch *hörbar* leiser wird, ist noch nicht bestätigt. Das ist der erste Schritt der Implementierung (siehe Umsetzungsreihenfolge).

## Gewählter Ansatz und Alternativen

**Gewählt: MPRIS über D-Bus.** Setzt Spotifys eigene Volume-Property — semantisch dasselbe wie der Tidal-Sink, der ebenfalls die App-interne Lautstärke steuert. Persistente Verbindung, keine Authentifizierung, kein Ratelimit, latenzfrei bei 100 Hz.

Verworfen:

- **PipeWire per-App-Volume** (Mixer-Lautstärke des Spotify-Streams, wie in `pavucontrol`). Würde auch für Browser-Spotify und generisch für beliebige Apps funktionieren, ist aber nicht Spotifys eigener Regler und taucht in dessen UI nicht auf. Dazu praktische Hürden: `pactl` ist auf dem System gar nicht installiert (nur `wpctl`), und ein Prozess-Spawn pro Fader-Bewegung skaliert nicht auf 100 Hz. Eine saubere Python-Anbindung an PipeWire wäre deutlich mehr Aufwand als der D-Bus-Weg.
- **Spotify Web API** (`PUT /v1/me/player/volume`). Braucht OAuth-Flow, Premium und Internet, und ist ratelimited — bei einem kontinuierlichen Fader läuft man in 429er. Für diesen Anwendungsfall die schlechteste Option.

## Umbenennung

Das Repo wird target-neutral. Inhaltlich unveränderte Umbenennungen:

| alt | neu |
|---|---|
| `rodecaster-tidal-bridge` (Projekt, Binary) | `rodecaster-volume-bridge` |
| `src/rodecaster_tidal_bridge/` | `src/rodecaster_volume_bridge/` |
| `~/.config/rodecaster-tidal-bridge/config.toml` | `~/.config/rodecaster-volume-bridge/config.toml` |
| `systemd/rodecaster-tidal-bridge.service` | `systemd/rodecaster-volume-bridge.service` |

`midi_source.py`, `scale.py`, `throttle.py` und `learn.py` sind bereits target-agnostisch und werden **nur** durch den Package-Rename berührt — keine inhaltlichen Änderungen.

Der Config-Pfad wandert ohne Migration mit. Wer die alte Datei hat, führt `--learn` neu aus (Sekundenaufwand). Der alte Pfad wird nicht gelesen.

## Architektur

```
┌─────────────┐  USB-MIDI (ALSA)  ┌──────────────────┐
│  RodeCaster │ ─────────────────►│  Bridge          │
│  (Music-Fdr)│   CC# value 0-127 │  (Python daemon) │
└─────────────┘                   └────────┬─────────┘
                                           │ VolumeSink.set_volume(0..100)
                        ┌──────────────────┴──────────────────┐
                        ▼                                     ▼
              ┌──────────────────┐                  ┌──────────────────┐
              │  TidalSink       │                  │  SpotifySink     │
              │  ws://:24123     │                  │  D-Bus session   │
              │  {"action":...}  │                  │  MPRIS Volume    │
              └──────────────────┘                  └──────────────────┘
```

Die Pipeline `midi_source → scale → throttle → sink` bleibt unverändert. Nur das letzte Glied ist austauschbar.

### `sink.py` (neu)

Definiert das `VolumeSink`-Protocol — exakt der Vertrag, den `TidalSink` heute schon erfüllt:

```python
class VolumeSink(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def set_volume(self, value: int) -> None: ...   # 0..100, fire-and-forget
```

`set_volume` ist bewusst synchron und nicht-blockierend: der Aufrufer ist der MIDI-Pfad und darf nie auf Netzwerk oder IPC warten.

Enthält außerdem die Factory `make_sink(cfg) -> VolumeSink`, die anhand `cfg.target` den passenden Sink baut und bei unbekanntem Target-Namen mit einer klaren Fehlermeldung abbricht.

### `spotify_sink.py` (neu)

Spiegelt `TidalSink` strukturell — gleiche Queue-, Coalescing- und Recovery-Mechanik, nur anderer Transport.

- **Verbindung:** Session-Bus über `dbus-fast` (asyncio-nativ). Persistente Verbindung, ein Proxy auf `org.mpris.MediaPlayer2.spotify` → `/org/mpris/MediaPlayer2`.
- **Senden:** Property-Set auf `org.mpris.MediaPlayer2.Player.Volume` als `double`, Wert `value / 100.0`. MPRIS definiert 1.0 als Normal-Lautstärke; 0..100 → 0.0..1.0.
- **Coalescing:** identisch zur bestehenden Implementierung — steht mehr als ein Wert in der Queue, wird direkt auf den neuesten gesprungen. Ein schneller Fader-Wisch darf nicht als Queue nachlaufen.
- **Spotify läuft nicht:** kein Fehler, kein Busy-Loop, kein Polling. Der Sink beobachtet `NameOwnerChanged` auf dem Bus-Namen und hält den letzten Fader-Wert als `pending`. Sobald Spotify erscheint, wird dieser Wert angewendet — die Lautstärke entspricht dann sofort der physischen Fader-Position, statt still auseinanderzulaufen.
- **Spotify verschwindet mitten im Senden:** der fehlgeschlagene Wert bleibt `pending`, der Sink geht zurück in den Warte-auf-Name-Zustand. Kein Wertverlust. Ein Backoff ist hier nicht nötig, weil D-Bus das Erscheinen signalisiert statt es pollen zu lassen.

Die Volume-Kurve (`curve_exponent`) und der Throttle greifen unverändert davor. Der Sink sieht nur fertige 0..100-Werte und kennt weder MIDI noch Kurve.

### `bridge.py` (Änderung)

Eine Stelle: statt `TidalSink(...)` hart zu instanziieren, wird `make_sink(cfg)` aufgerufen. Die Event-Schleife, der Throttle-Aufruf und das Shutdown-Handling bleiben identisch. Die Log-Zeile beim Start nennt zusätzlich das aktive Target.

### `config.py` (Änderung)

Neues Pflichtfeld `target` auf oberster Ebene. Neuer optionaler `[spotify]`-Block. Fehlt `target`, bricht das Laden mit einer verständlichen Meldung ab statt still auf Tidal zu fallen.

Nur der Block des aktiven Targets muss vorhanden sein — ein reines Spotify-Setup braucht keinen `[tidal]`-Block und umgekehrt. Diese Prüfung passiert in der Factory, nicht beim TOML-Parsen.

`save_config` (von `--learn` genutzt) schreibt beide Blöcke mit Defaults, damit ein Target-Wechsel nur eine Zeile Handarbeit ist.

## Config-Format

```toml
target = "spotify"          # "spotify" | "tidal"

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
# volume = (midi/127)^curve_exponent * 100
curve_exponent = 2.0
```

`bus_name` ist konfigurierbar, weil MPRIS-Clients ihre Namen mit Instanz-Suffix registrieren können und andere Spotify-Builds (Flatpak, `spotifyd`) abweichende Namen nutzen.

## Fehlerbehandlung

| Situation | Verhalten |
|---|---|
| Spotify läuft beim Start nicht | Warnung loggen, auf `NameOwnerChanged` warten, letzten Wert vormerken |
| Spotify startet später | Vorgemerkten Wert sofort anwenden |
| Spotify beendet sich | Wert als `pending` behalten, zurück in den Warte-Zustand, keine Exception nach oben |
| Session-Bus nicht erreichbar | Harter Fehler beim Start mit klarer Meldung — das ist ein Setup-Problem, kein transienter Zustand |
| `target` unbekannt oder fehlt | Abbruch beim Config-Laden mit Auflistung der gültigen Werte |
| Block des aktiven Targets fehlt | Abbruch in der Factory mit Angabe des fehlenden Blocks |

## Tests

`test_tidal_sink.py` bleibt unverändert (bis auf den Import-Pfad). Neu:

- **`test_spotify_sink.py`** — gegen einen **echten D-Bus-Service**, den der Test selbst auf dem Session-Bus exportiert, analog zum Mock-WebSocket-Server im Tidal-Test. Kein Mocking der Bibliothek, echte Property-Sets. Abgedeckt:
  - Ein gesetzter Wert kommt als korrekter Double an (42 → 0.42)
  - Coalescing: mehrere schnelle Updates landen als jüngster Wert
  - Der Service erscheint erst *nach* dem Sink-Start → vorgemerkter Wert wird angewendet
  - Der Service verschwindet → kein Crash, Wert überlebt bis zur Rückkehr
- **`test_sink_factory.py`** — richtiges Sink-Objekt pro Target, verständliche Fehler bei unbekanntem Target und bei fehlendem Config-Block.
- **`test_config.py`** — erweitert um `target`, `[spotify]` und den Fehlerfall ohne `target`.

`test_scale.py`, `test_throttle.py`, `test_learn.py` laufen unverändert weiter.

Ist in der Umgebung kein Session-Bus verfügbar (CI, Sandbox), werden die D-Bus-Tests übersprungen statt zu failen.

## Dependencies

Neu: `dbus-fast>=2.0`. Asyncio-nativ, pure Python mit optionaler C-Beschleunigung, aktiv gepflegt. Bewusst gegen `dbus-next` (praktisch unmaintained, `dbus-fast` ist dessen Nachfolger) und gegen `jeepney` (low-level, mehr Eigenbau für Property-Zugriff und Name-Watching).

## Umsetzungsreihenfolge

1. **Hörbarkeit verifizieren** — bei laufender Wiedergabe die MPRIS-Volume setzen und bestätigen, dass es tatsächlich leiser wird. Schlägt das fehl, ist das ganze Design hinfällig und wir gehen auf den PipeWire-Ansatz. Dieser Schritt kommt vor allem anderen.
2. Package-Rename inkl. Tests, pyproject, systemd-Unit, README.
3. `VolumeSink`-Protocol und Factory einziehen, `bridge.py` umstellen, `TidalSink` dagegen laufen lassen (Verhalten muss unverändert sein).
4. Config um `target` und `[spotify]` erweitern.
5. `SpotifySink` mit Tests.
6. README um Spotify-Setup und Target-Wechsel ergänzen.

## Offene Punkte

Ein einziger, und er ist als Schritt 1 der Umsetzung eingeplant: ob das Setzen der MPRIS-Volume die Wiedergabe hörbar leiser macht. Bestätigt ist bisher nur, dass Spotify den Wert annimmt und zurückliefert. Fällt die Prüfung negativ aus, ist der PipeWire-Ansatz der Rückfallweg.
