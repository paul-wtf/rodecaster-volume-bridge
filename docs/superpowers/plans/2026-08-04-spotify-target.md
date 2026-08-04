# Spotify-Target für die RodeCaster-Volume-Bridge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die bestehende Tidal-Bridge um Spotify als zweites, per Config wählbares Steuerziel erweitern und das Repo dabei target-neutral machen.

**Architecture:** Die Pipeline `midi_source → scale → throttle → sink` bleibt unverändert; nur das letzte Glied wird austauschbar. Ein `VolumeSink`-Protocol beschreibt den Vertrag, den `TidalSink` bereits erfüllt, eine Factory wählt anhand `cfg.target` den Sink. Der neue `SpotifySink` setzt Spotifys eigene MPRIS-`Volume`-Property über den D-Bus-Session-Bus und spiegelt dabei die Queue-, Coalescing- und Recovery-Mechanik von `TidalSink`.

**Tech Stack:** Python ≥3.11, asyncio, `mido`/`python-rtmidi` (MIDI), `websockets` (Tidal), `dbus-fast` (Spotify/MPRIS), `pytest` + `pytest-asyncio`.

**Spec:** `docs/superpowers/specs/2026-08-04-spotify-target-design.md`

## Global Constraints

- Python-Floor: `requires-python = ">=3.11"` — nicht absenken.
- Neue Dependency: `dbus-fast>=2.0`. Keine weiteren neuen Runtime-Dependencies.
- Package heißt nach Task 2 `rodecaster_volume_bridge`, Projekt/Binary `rodecaster-volume-bridge`, Config-Pfad `~/.config/rodecaster-volume-bridge/config.toml`.
- Gültige Target-Namen sind exakt `"tidal"` und `"spotify"`.
- MPRIS-Konstanten, wörtlich: Bus-Name `org.mpris.MediaPlayer2.spotify`, Object-Path `/org/mpris/MediaPlayer2`, Interface `org.mpris.MediaPlayer2.Player`, Property `Volume`, Typ `double`, Wertebereich `0.0`–`1.0`.
- `set_volume(value: int)` ist synchron, nicht-blockierend und wirft nie — es läuft auf dem MIDI-Pfad.
- `midi_source.py`, `scale.py`, `throttle.py`, `learn.py` werden **nur** durch den Package-Rename berührt, inhaltlich nicht verändert.
- Alle D-Bus-Tests werden übersprungen, wenn kein Session-Bus verfügbar ist — sie dürfen nie failen, nur skippen.
- Kommentare und Docstrings auf Englisch (wie im Bestand), Nutzer-sichtbare CLI-Ausgaben auf Deutsch (wie im Bestand).

---

### Task 1: Hörbarkeit der MPRIS-Volume verifizieren

Das ist das Risiko, an dem das ganze Design hängt. Bestätigt ist bisher nur, dass Spotify den Wert *annimmt und zurückliefert* — nicht, dass die Wiedergabe leiser wird. Fällt das negativ aus, wird der Rest des Plans nicht umgesetzt, sondern auf den PipeWire-Ansatz aus der Spec umgeschwenkt.

**Files:**
- Modify: `pyproject.toml:10-15` (dependencies)

**Interfaces:**
- Consumes: nichts
- Produces: die Dependency `dbus-fast>=2.0`, auf die alle folgenden Tasks bauen

- [ ] **Step 1: Dependency eintragen**

In `pyproject.toml` die `dependencies`-Liste um `dbus-fast` ergänzen:

```toml
dependencies = [
    "mido>=1.3",
    "python-rtmidi>=1.5",
    "websockets>=12",
    "tomli-w>=1.0",
    "dbus-fast>=2.0",
]
```

- [ ] **Step 2: Dev-Umgebung aktualisieren**

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: `dbus-fast` wird installiert, kein Fehler.

Falls noch kein venv existiert:
`python -m venv .venv && .venv/bin/pip install -e ".[dev]"`

- [ ] **Step 3: Verify-Skript schreiben**

Erstelle `/tmp/verify_mpris.py` (Wegwerf-Skript, **nicht** committen):

```python
import asyncio
from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus

BUS_NAME = "org.mpris.MediaPlayer2.spotify"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"


async def set_volume(bus, value: float):
    reply = await bus.call(Message(
        destination=BUS_NAME,
        path=OBJECT_PATH,
        interface="org.freedesktop.DBus.Properties",
        member="Set",
        signature="ssv",
        body=[PLAYER_IFACE, "Volume", Variant("d", value)],
    ))
    if reply.message_type == MessageType.ERROR:
        raise RuntimeError(f"Set failed: {reply.body}")


async def main():
    bus = await MessageBus(bus_type=BusType.SESSION).connect()
    for value in (1.0, 0.5, 0.15, 0.5, 1.0):
        print(f"-> Volume = {value}")
        await set_volume(bus, value)
        await asyncio.sleep(2.5)
    print("fertig, zurück auf 1.0")


asyncio.run(main())
```

- [ ] **Step 4: Mit laufender Wiedergabe ausführen und hinhören**

Spotify starten, einen Track abspielen, dann:

Run: `.venv/bin/python /tmp/verify_mpris.py`
Expected: Die Wiedergabe wird hörbar leiser (bei `0.15` deutlich), dann wieder lauter, und endet auf normaler Lautstärke.

**Gate:** Ist die Lautstärkeänderung *nicht* hörbar, hier stoppen und melden — der Rest des Plans ist dann hinfällig und die Spec muss auf den PipeWire-Ansatz umgeschrieben werden. Nicht weitermachen und hoffen.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build: add dbus-fast dependency for MPRIS volume control"
```

---

### Task 2: Package-Rename auf rodecaster-volume-bridge

Reine Umbenennung. Kein Verhalten ändert sich, alle bestehenden Tests müssen unverändert durchlaufen (bis auf Import-Pfade).

**Files:**
- Rename: `src/rodecaster_tidal_bridge/` → `src/rodecaster_volume_bridge/`
- Rename: `systemd/rodecaster-tidal-bridge.service` → `systemd/rodecaster-volume-bridge.service`
- Modify: `pyproject.toml:6` (name), `pyproject.toml:23` (scripts)
- Modify: `src/rodecaster_volume_bridge/config.py:30` (Config-Pfad)
- Modify: `src/rodecaster_volume_bridge/__main__.py:31,90` (prog, Hinweistext)
- Modify: `tests/test_config.py:6`, `tests/test_learn.py:6-7`, `tests/test_throttle.py:6`, `tests/test_tidal_sink.py:7`, `tests/test_scale.py:3`
- Modify: `README.md`

**Interfaces:**
- Consumes: nichts
- Produces: Package `rodecaster_volume_bridge` — alle folgenden Tasks importieren daraus

- [ ] **Step 1: Baseline sichern — Tests müssen jetzt grün sein**

Run: `.venv/bin/pytest`
Expected: PASS, alle Tests grün. Falls nicht, erst das melden, bevor umbenannt wird.

- [ ] **Step 2: Verzeichnis und Service-Datei umbenennen**

```bash
git mv src/rodecaster_tidal_bridge src/rodecaster_volume_bridge
git mv systemd/rodecaster-tidal-bridge.service systemd/rodecaster-volume-bridge.service
```

- [ ] **Step 3: Alle Referenzen auf den alten Namen ersetzen**

```bash
grep -rl "rodecaster_tidal_bridge\|rodecaster-tidal-bridge" \
    --exclude-dir=.git --exclude-dir=docs . \
  | xargs sed -i \
      -e 's/rodecaster_tidal_bridge/rodecaster_volume_bridge/g' \
      -e 's/rodecaster-tidal-bridge/rodecaster-volume-bridge/g'
```

`docs/` ist bewusst ausgenommen — die alte Spec und der alte Plan sind historische Dokumente und werden nicht umgeschrieben.

- [ ] **Step 4: Ergebnis prüfen**

Run: `grep -rn "rodecaster_tidal_bridge\|rodecaster-tidal-bridge" --exclude-dir=.git --exclude-dir=docs .`
Expected: keine Treffer.

Run: `grep -n "^name\|rodecaster" pyproject.toml`
Expected: `name = "rodecaster-volume-bridge"` und `rodecaster-volume-bridge = "rodecaster_volume_bridge.__main__:main"`.

- [ ] **Step 5: Service-Description anpassen**

In `systemd/rodecaster-volume-bridge.service` Zeile 2, weil `sed` nur die Programmnamen getroffen hat:

```ini
Description=RodeCaster MIDI Volume Bridge
```

- [ ] **Step 6: Neu installieren und Tests laufen lassen**

Run: `.venv/bin/pip install -e ".[dev]" && .venv/bin/pytest`
Expected: PASS, dieselbe Anzahl Tests wie in Step 1.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: rename package to rodecaster-volume-bridge"
```

---

### Task 3: Config um target und Spotify-Block erweitern

**Files:**
- Modify: `src/rodecaster_volume_bridge/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Package `rodecaster_volume_bridge` aus Task 2
- Produces:
  - `Config` mit den Feldern `midi_port_name_contains: str`, `midi_channel: int`, `midi_cc: int`, `throttle_max_hz: int`, `target: str`, `tidal_ws_url: str | None = None`, `spotify_bus_name: str = DEFAULT_SPOTIFY_BUS_NAME`, `curve_exponent: float = DEFAULT_CURVE_EXPONENT`
  - `DEFAULT_SPOTIFY_BUS_NAME = "org.mpris.MediaPlayer2.spotify"`
  - `VALID_TARGETS = ("tidal", "spotify")`
  - `InvalidConfigError(ValueError)`

Achtung: `tidal_ws_url` verliert seinen Pflicht-Status und rutscht hinter `target`. Alle `Config(...)`-Konstruktionen im Repo nutzen Keyword-Argumente, daher bricht die Umsortierung nichts — aber `target` muss ab jetzt überall mit angegeben werden.

- [ ] **Step 1: Die failing tests schreiben**

In `tests/test_config.py` den Import erweitern und die vier bestehenden Tests um `target` ergänzen, dann die neuen Tests anhängen.

Import-Zeile ersetzen durch:

```python
from rodecaster_volume_bridge.config import (
    Config,
    ConfigMissingError,
    InvalidConfigError,
    load_config,
    save_config,
)
```

In `test_load_returns_typed_config` und `test_load_legacy_config_without_scale_section_defaults_to_2` jeweils als erste Zeile des TOML-Strings einfügen (vor `[midi]`, mit Leerzeile dahinter):

```
target = "tidal"
```

und in `test_load_returns_typed_config` die Assertion ergänzen:

```python
    assert cfg.target == "tidal"
    assert cfg.spotify_bus_name == "org.mpris.MediaPlayer2.spotify"
```

In `test_save_then_load_roundtrip` und `test_save_creates_parent_dirs` je `target="tidal",` in den `Config(...)`-Aufruf ergänzen.

Neue Tests ans Dateiende anhängen:

```python
def test_load_spotify_target_without_tidal_block(tmp_path: Path):
    """A Spotify-only config needs no [tidal] section."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        target = "spotify"

        [midi]
        port_name_contains = "RODECaster"
        channel = 1
        cc = 7

        [throttle]
        max_hz = 100
    """).strip())

    cfg = load_config(cfg_file)

    assert cfg.target == "spotify"
    assert cfg.tidal_ws_url is None
    assert cfg.spotify_bus_name == "org.mpris.MediaPlayer2.spotify"


def test_load_custom_spotify_bus_name(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        target = "spotify"

        [midi]
        port_name_contains = "RODECaster"
        channel = 1
        cc = 7

        [spotify]
        bus_name = "org.mpris.MediaPlayer2.spotifyd"

        [throttle]
        max_hz = 100
    """).strip())

    assert load_config(cfg_file).spotify_bus_name == "org.mpris.MediaPlayer2.spotifyd"


def test_load_without_target_raises_with_valid_values_listed(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        [midi]
        port_name_contains = "RODECaster"
        channel = 1
        cc = 7

        [throttle]
        max_hz = 100
    """).strip())

    with pytest.raises(InvalidConfigError) as excinfo:
        load_config(cfg_file)
    assert "tidal" in str(excinfo.value)
    assert "spotify" in str(excinfo.value)


def test_load_unknown_target_raises(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        target = "deezer"

        [midi]
        port_name_contains = "RODECaster"
        channel = 1
        cc = 7

        [throttle]
        max_hz = 100
    """).strip())

    with pytest.raises(InvalidConfigError) as excinfo:
        load_config(cfg_file)
    assert "deezer" in str(excinfo.value)


def test_save_writes_both_target_blocks(tmp_path: Path):
    """Both blocks are written with defaults so switching targets is a
    one-line edit."""
    cfg_file = tmp_path / "config.toml"
    cfg = Config(
        midi_port_name_contains="RODECaster",
        midi_channel=1,
        midi_cc=7,
        throttle_max_hz=100,
        target="spotify",
    )
    save_config(cfg, cfg_file)

    text = cfg_file.read_text()
    assert "[tidal]" in text
    assert "[spotify]" in text
    assert 'target = "spotify"' in text


def test_save_then_load_roundtrip_spotify(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg = Config(
        midi_port_name_contains="RODECaster",
        midi_channel=2,
        midi_cc=11,
        throttle_max_hz=100,
        target="spotify",
        tidal_ws_url="ws://localhost:24123",
        spotify_bus_name="org.mpris.MediaPlayer2.spotify",
        curve_exponent=2.0,
    )
    save_config(cfg, cfg_file)
    assert load_config(cfg_file) == cfg
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'InvalidConfigError'`.

- [ ] **Step 3: config.py implementieren**

`src/rodecaster_volume_bridge/config.py` komplett ersetzen durch:

```python
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import tomli_w


class ConfigMissingError(FileNotFoundError):
    pass


class InvalidConfigError(ValueError):
    pass


DEFAULT_CURVE_EXPONENT = 2.0
DEFAULT_SPOTIFY_BUS_NAME = "org.mpris.MediaPlayer2.spotify"
DEFAULT_TIDAL_WS_URL = "ws://localhost:24123"
VALID_TARGETS = ("tidal", "spotify")


@dataclass(frozen=True)
class Config:
    midi_port_name_contains: str
    midi_channel: int
    midi_cc: int
    throttle_max_hz: int
    target: str
    tidal_ws_url: Optional[str] = None
    spotify_bus_name: str = DEFAULT_SPOTIFY_BUS_NAME
    curve_exponent: float = DEFAULT_CURVE_EXPONENT


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "rodecaster-volume-bridge" / "config.toml"


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigMissingError(f"Config file not found: {path}")
    with path.open("rb") as f:
        data = tomllib.load(f)

    target = data.get("target")
    if target not in VALID_TARGETS:
        valid = ", ".join(repr(t) for t in VALID_TARGETS)
        raise InvalidConfigError(
            f"Config {path}: 'target' is {target!r}, expected one of {valid}."
        )

    scale = data.get("scale", {})
    tidal = data.get("tidal", {})
    spotify = data.get("spotify", {})
    return Config(
        midi_port_name_contains=data["midi"]["port_name_contains"],
        midi_channel=int(data["midi"]["channel"]),
        midi_cc=int(data["midi"]["cc"]),
        throttle_max_hz=int(data["throttle"]["max_hz"]),
        target=target,
        tidal_ws_url=tidal.get("ws_url"),
        spotify_bus_name=spotify.get("bus_name", DEFAULT_SPOTIFY_BUS_NAME),
        curve_exponent=float(scale.get("curve_exponent", DEFAULT_CURVE_EXPONENT)),
    )


def save_config(cfg: Config, path: Path) -> None:
    """Write the config. Both target blocks are always written so switching
    targets later is a one-line edit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "target": cfg.target,
        "midi": {
            "port_name_contains": cfg.midi_port_name_contains,
            "channel": cfg.midi_channel,
            "cc": cfg.midi_cc,
        },
        "spotify": {"bus_name": cfg.spotify_bus_name},
        "tidal": {"ws_url": cfg.tidal_ws_url or DEFAULT_TIDAL_WS_URL},
        "throttle": {"max_hz": cfg.throttle_max_hz},
        "scale": {"curve_exponent": cfg.curve_exponent},
    }
    with path.open("wb") as f:
        tomli_w.dump(payload, f)
```

Hinweis zu `test_save_writes_both_target_blocks`: dort ist `tidal_ws_url=None`, und `save_config` schreibt deshalb den Default-URL. Beim Roundtrip in `test_save_then_load_roundtrip_spotify` ist die URL explizit gesetzt, daher ist dort Gleichheit gegeben.

- [ ] **Step 4: Tests laufen lassen**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS, alle Config-Tests grün.

- [ ] **Step 5: Aufrufer reparieren**

`.venv/bin/pytest` schlägt jetzt an anderer Stelle fehl bzw. `__main__.py` ist kaputt, weil `Config(...)` dort ohne `target` gebaut wird. In `src/rodecaster_volume_bridge/__main__.py`:

Import-Block (Zeilen 10-17) ersetzen durch:

```python
from .config import (
    Config,
    ConfigMissingError,
    DEFAULT_CURVE_EXPONENT,
    DEFAULT_SPOTIFY_BUS_NAME,
    DEFAULT_TIDAL_WS_URL,
    InvalidConfigError,
    default_config_path,
    load_config,
    save_config,
)
```

Die Konstante `DEFAULT_WS_URL = "ws://localhost:24123"` (Zeile 26) löschen — sie ist jetzt `DEFAULT_TIDAL_WS_URL` in `config.py`. Danach den `Config(...)`-Aufruf in `_cmd_learn` ersetzen durch:

```python
    cfg = Config(
        midi_port_name_contains=args.port_hint,
        midi_channel=channel,
        midi_cc=cc,
        throttle_max_hz=DEFAULT_HZ,
        target=args.target,
        tidal_ws_url=DEFAULT_TIDAL_WS_URL,
        spotify_bus_name=DEFAULT_SPOTIFY_BUS_NAME,
        curve_exponent=DEFAULT_CURVE_EXPONENT,
    )
```

Und das `--target`-Argument im Parser ergänzen, direkt nach `--learn-seconds`:

```python
    parser.add_argument("--target", choices=("spotify", "tidal"), default="spotify",
                        help="Which player to control (learn mode only; "
                             "change later by editing the config).")
```

Zusätzlich in `_cmd_run` den neuen Config-Fehler abfangen — nach dem `except ConfigMissingError`-Block:

```python
    except InvalidConfigError as e:
        print(str(e), file=sys.stderr)
        return 1
```

- [ ] **Step 6: Gesamte Suite laufen lassen**

Run: `.venv/bin/pytest`
Expected: PASS.

Run: `.venv/bin/python -c "import rodecaster_volume_bridge.__main__"`
Expected: kein Fehler.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add target selection and spotify block to config"
```

---

### Task 4: SpotifySink

Der Kern. Eigenständig testbar, hängt nicht an Config oder Factory.

**Files:**
- Create: `src/rodecaster_volume_bridge/spotify_sink.py`
- Test: `tests/test_spotify_sink.py`

**Interfaces:**
- Consumes: `dbus-fast` aus Task 1, Package-Name aus Task 2
- Produces: `SpotifySink(bus_name: str, object_path: str = MPRIS_OBJECT_PATH, retry_delay_s: float = 0.2)` mit `async start()`, `async stop()`, `set_volume(value: int)` — erfüllt damit das `VolumeSink`-Protocol aus Task 5. Außerdem `SessionBusUnavailableError(RuntimeError)`.

`bus_name` hat bewusst **keinen** Default: der Default gehört in `config.py` (Task 3, `DEFAULT_SPOTIFY_BUS_NAME`), damit derselbe String nicht an zwei Stellen steht.

- [ ] **Step 1: Die failing tests schreiben**

Erstelle `tests/test_spotify_sink.py`:

```python
import asyncio
import os

import pytest
from dbus_fast import BusType, PropertyAccess
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, dbus_property

from rodecaster_volume_bridge.spotify_sink import (
    SessionBusUnavailableError,
    SpotifySink,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DBUS_SESSION_BUS_ADDRESS"),
    reason="no D-Bus session bus available",
)

TEST_BUS_NAME = "org.mpris.MediaPlayer2.rcvbtest"
OBJECT_PATH = "/org/mpris/MediaPlayer2"


class FakePlayer(ServiceInterface):
    """Minimal stand-in for Spotify's MPRIS Player interface."""

    def __init__(self) -> None:
        super().__init__("org.mpris.MediaPlayer2.Player")
        self._volume = 1.0
        self.sets: list[float] = []

    @dbus_property(access=PropertyAccess.READWRITE)
    def Volume(self) -> "d":
        return self._volume

    @Volume.setter
    def Volume(self, value: "d") -> None:
        self._volume = value
        self.sets.append(value)


async def export_fake() -> tuple[MessageBus, FakePlayer]:
    bus = await MessageBus(bus_type=BusType.SESSION).connect()
    player = FakePlayer()
    bus.export(OBJECT_PATH, player)
    await bus.request_name(TEST_BUS_NAME)
    return bus, player


async def wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.mark.asyncio
async def test_sets_volume_as_fraction():
    fake_bus, player = await export_fake()
    sink = SpotifySink(bus_name=TEST_BUS_NAME)
    await sink.start()
    try:
        sink.set_volume(42)
        assert await wait_for(lambda: player.sets), "no Set arrived"
        assert player.sets[-1] == pytest.approx(0.42)
    finally:
        await sink.stop()
        fake_bus.disconnect()


@pytest.mark.asyncio
async def test_coalesces_burst_while_player_absent():
    """A burst of fader movements while Spotify is down collapses to the
    latest value, which is applied once Spotify appears."""
    sink = SpotifySink(bus_name=TEST_BUS_NAME)
    await sink.start()
    fake_bus = None
    try:
        # No awaits between these — the sink task cannot interleave.
        for value in range(1, 11):
            sink.set_volume(value)

        fake_bus, player = await export_fake()
        assert await wait_for(lambda: player.sets), "value was not applied"
        await asyncio.sleep(0.2)  # give any stragglers a chance to arrive
        assert player.sets == [pytest.approx(0.10)]
    finally:
        await sink.stop()
        if fake_bus is not None:
            fake_bus.disconnect()


@pytest.mark.asyncio
async def test_waits_for_player_that_appears_later():
    sink = SpotifySink(bus_name=TEST_BUS_NAME)
    await sink.start()
    fake_bus = None
    try:
        sink.set_volume(75)
        await asyncio.sleep(0.2)  # nothing to send to yet

        fake_bus, player = await export_fake()
        assert await wait_for(lambda: player.sets), "pending value was lost"
        assert player.sets[-1] == pytest.approx(0.75)
    finally:
        await sink.stop()
        if fake_bus is not None:
            fake_bus.disconnect()


@pytest.mark.asyncio
async def test_survives_player_disappearing_and_returning():
    fake_bus, player = await export_fake()
    sink = SpotifySink(bus_name=TEST_BUS_NAME)
    await sink.start()
    second_bus = None
    try:
        sink.set_volume(50)
        assert await wait_for(lambda: player.sets)

        fake_bus.disconnect()
        await asyncio.sleep(0.2)
        sink.set_volume(20)
        await asyncio.sleep(0.2)

        second_bus, player2 = await export_fake()
        assert await wait_for(lambda: player2.sets), "value did not survive"
        assert player2.sets[-1] == pytest.approx(0.20)
    finally:
        await sink.stop()
        if second_bus is not None:
            second_bus.disconnect()


@pytest.mark.asyncio
async def test_set_volume_never_raises_when_player_absent():
    sink = SpotifySink(bus_name=TEST_BUS_NAME)
    await sink.start()
    try:
        sink.set_volume(30)  # must not raise
        await asyncio.sleep(0.1)
    finally:
        await sink.stop()


@pytest.mark.asyncio
async def test_unreachable_session_bus_raises_clear_error(monkeypatch):
    """A missing session bus is a setup problem, not a transient state —
    it must fail at start with a message that says so."""
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/nonexistent/rcvb")
    sink = SpotifySink(bus_name=TEST_BUS_NAME)
    with pytest.raises(SessionBusUnavailableError) as excinfo:
        await sink.start()
    assert "session bus" in str(excinfo.value).lower()
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/pytest tests/test_spotify_sink.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rodecaster_volume_bridge.spotify_sink'`.

Wird stattdessen alles geskippt, fehlt der Session-Bus: `echo $DBUS_SESSION_BUS_ADDRESS` prüfen und die Tests in einer Desktop-Session ausführen.

- [ ] **Step 3: spotify_sink.py implementieren**

Erstelle `src/rodecaster_volume_bridge/spotify_sink.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus

log = logging.getLogger(__name__)

MPRIS_OBJECT_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"


class SessionBusUnavailableError(RuntimeError):
    pass


class SpotifySink:
    """Drives an MPRIS player's Volume property.

    Mirrors TidalSink: set_volume() is a non-blocking hand-off onto a queue,
    a background task does the talking, and queued values are coalesced to
    the most recent one so a fast fader sweep never trails behind.

    When the player is absent the latest value is held as pending and applied
    the moment the bus name reappears, so the volume matches the physical
    fader position instead of silently drifting apart. Presence is tracked via
    NameOwnerChanged rather than polling.
    """

    def __init__(
        self,
        bus_name: str,
        object_path: str = MPRIS_OBJECT_PATH,
        retry_delay_s: float = 0.2,
    ) -> None:
        self._bus_name = bus_name
        self._object_path = object_path
        self._retry_delay_s = retry_delay_s
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._bus: Optional[MessageBus] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._stop = asyncio.Event()
        self._owned = asyncio.Event()

    async def start(self) -> None:
        try:
            self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # A missing session bus is a setup problem, not something to
            # retry — fail loudly instead of silently never sending anything.
            raise SessionBusUnavailableError(
                f"Cannot reach the D-Bus session bus ({e}). "
                "Is DBUS_SESSION_BUS_ADDRESS set and a session bus running?"
            ) from e
        await self._watch_name()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None

    def set_volume(self, value: int) -> None:
        # fire-and-forget; queue is unbounded so put_nowait never blocks
        self._queue.put_nowait(value)

    async def _watch_name(self) -> None:
        """Subscribe to NameOwnerChanged for our bus name and seed the
        current ownership state."""
        assert self._bus is not None
        await self._bus.call(Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="AddMatch",
            signature="s",
            body=[
                "type='signal',sender='org.freedesktop.DBus',"
                "interface='org.freedesktop.DBus',member='NameOwnerChanged',"
                f"arg0='{self._bus_name}'"
            ],
        ))
        self._bus.add_message_handler(self._on_name_owner_changed)

        reply = await self._bus.call(Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="NameHasOwner",
            signature="s",
            body=[self._bus_name],
        ))
        if reply.message_type != MessageType.ERROR and reply.body[0]:
            self._owned.set()
        else:
            log.info("%s not on the bus yet; waiting", self._bus_name)

    def _on_name_owner_changed(self, msg: Message) -> None:
        # Returning None leaves the message unhandled so other handlers see it.
        if (
            msg.message_type is not MessageType.SIGNAL
            or msg.interface != "org.freedesktop.DBus"
            or msg.member != "NameOwnerChanged"
        ):
            return
        name, _old_owner, new_owner = msg.body
        if name != self._bus_name:
            return
        if new_owner:
            log.info("%s appeared on the bus", self._bus_name)
            self._owned.set()
        else:
            log.info("%s left the bus", self._bus_name)
            self._owned.clear()

    def _drain_to_latest(self) -> Optional[int]:
        latest: Optional[int] = None
        while True:
            try:
                latest = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return latest

    async def _run(self) -> None:
        # Holds a value that was dequeued but not yet successfully sent, so it
        # survives the player restarting without being lost.
        pending: Optional[int] = None
        while not self._stop.is_set():
            try:
                if pending is None:
                    pending = await self._queue.get()
                # coalesce: if more values queued already, jump to the newest
                latest = self._drain_to_latest()
                if latest is not None:
                    pending = latest

                await self._owned.wait()
                if await self._send(pending):
                    pending = None
                else:
                    # Either the player just vanished (the signal handler will
                    # have cleared _owned, so the wait above blocks next round)
                    # or the call failed for another reason — back off briefly
                    # so a persistent failure cannot spin.
                    await asyncio.sleep(self._retry_delay_s)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("unexpected error in spotify sink loop")
                await asyncio.sleep(self._retry_delay_s)

    async def _send(self, value: int) -> bool:
        assert self._bus is not None
        fraction = max(0.0, min(1.0, value / 100.0))
        try:
            reply = await self._bus.call(Message(
                destination=self._bus_name,
                path=self._object_path,
                interface=DBUS_PROPERTIES_IFACE,
                member="Set",
                signature="ssv",
                body=[MPRIS_PLAYER_IFACE, "Volume", Variant("d", fraction)],
            ))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("volume set failed (%s); will retry", e)
            return False
        if reply is not None and reply.message_type == MessageType.ERROR:
            log.warning("volume set rejected: %s", reply.body)
            return False
        return True
```

- [ ] **Step 4: Tests laufen lassen**

Run: `.venv/bin/pytest tests/test_spotify_sink.py -v`
Expected: PASS, alle sechs Tests grün (nicht geskippt).

- [ ] **Step 5: Gegen das echte Spotify prüfen**

Spotify mit laufender Wiedergabe, dann:

```bash
.venv/bin/python -c "
import asyncio
from rodecaster_volume_bridge.spotify_sink import SpotifySink

async def main():
    sink = SpotifySink(bus_name='org.mpris.MediaPlayer2.spotify')
    await sink.start()
    for v in (100, 40, 15, 100):
        print(v); sink.set_volume(v); await asyncio.sleep(2)
    await sink.stop()

asyncio.run(main())
"
```

Expected: Lautstärke folgt hörbar, endet auf 100.

- [ ] **Step 6: Commit**

```bash
git add src/rodecaster_volume_bridge/spotify_sink.py tests/test_spotify_sink.py
git commit -m "feat: add SpotifySink driving MPRIS volume over D-Bus"
```

---

### Task 5: VolumeSink-Protocol, Factory und bridge.py

**Files:**
- Create: `src/rodecaster_volume_bridge/sink.py`
- Modify: `src/rodecaster_volume_bridge/bridge.py:1-25`
- Test: `tests/test_sink_factory.py`

**Interfaces:**
- Consumes: `Config`, `InvalidConfigError` aus Task 3; `SpotifySink` aus Task 4; `TidalSink` aus dem Bestand
- Produces: `VolumeSink` (Protocol) und `make_sink(cfg: Config) -> VolumeSink`

- [ ] **Step 1: Die failing tests schreiben**

Erstelle `tests/test_sink_factory.py`:

```python
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
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/pytest tests/test_sink_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rodecaster_volume_bridge.sink'`.

- [ ] **Step 3: sink.py implementieren**

Erstelle `src/rodecaster_volume_bridge/sink.py`:

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .config import Config, InvalidConfigError
from .spotify_sink import SpotifySink
from .tidal_sink import TidalSink


@runtime_checkable
class VolumeSink(Protocol):
    """A destination for volume values in the range 0..100.

    set_volume() runs on the MIDI path: it must never block and never raise.
    Delivery is the sink's own problem, handled by its background task.
    """

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def set_volume(self, value: int) -> None: ...


def make_sink(cfg: Config) -> VolumeSink:
    if cfg.target == "spotify":
        return SpotifySink(bus_name=cfg.spotify_bus_name)
    if cfg.target == "tidal":
        if not cfg.tidal_ws_url:
            raise InvalidConfigError(
                "target is 'tidal' but no ws_url is configured; "
                "add a [tidal] block with ws_url."
            )
        return TidalSink(url=cfg.tidal_ws_url)
    raise InvalidConfigError(
        f"Unknown target {cfg.target!r}; expected 'tidal' or 'spotify'."
    )
```

- [ ] **Step 4: Tests laufen lassen**

Run: `.venv/bin/pytest tests/test_sink_factory.py -v`
Expected: PASS.

- [ ] **Step 5: bridge.py auf die Factory umstellen**

In `src/rodecaster_volume_bridge/bridge.py` den Import von `TidalSink` durch die Factory ersetzen und die Instanziierung sowie die Log-Zeile anpassen. Die Zeilen 1-25 werden zu:

```python
from __future__ import annotations

import asyncio
import logging

from .config import Config
from .midi_source import stream_cc_events
from .scale import midi_to_volume
from .sink import make_sink
from .throttle import TrailingThrottle

log = logging.getLogger(__name__)


async def run_bridge(cfg: Config) -> None:
    sink = make_sink(cfg)
    await sink.start()
    interval = 1.0 / cfg.throttle_max_hz
    throttle = TrailingThrottle(min_interval_s=interval)

    log.info(
        "bridge running: target=%s, matching MIDI port %r, ch=%d cc=%d, "
        "throttle=%dHz, curve=%.2f",
        cfg.target, cfg.midi_port_name_contains, cfg.midi_channel, cfg.midi_cc,
        cfg.throttle_max_hz, cfg.curve_exponent,
    )
```

Der Rest der Funktion ab `try:` bleibt unverändert. (`import asyncio` war schon vorher ungenutzt — unverändert lassen, das ist nicht Teil dieser Änderung.)

- [ ] **Step 6: Setup-Fehler in der CLI sauber melden**

Damit ein fehlender Session-Bus als verständliche Meldung statt als Traceback erscheint, in `src/rodecaster_volume_bridge/__main__.py` den Import ergänzen:

```python
from .spotify_sink import SessionBusUnavailableError
```

und in `_cmd_run` den Aufruf am Ende ersetzen durch:

```python
    try:
        await run_bridge(cfg)
    except (InvalidConfigError, SessionBusUnavailableError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0
```

- [ ] **Step 7: Gesamte Suite laufen lassen**

Run: `.venv/bin/pytest -v`
Expected: PASS, keine Skips außer ggf. den D-Bus-Tests ohne Session-Bus.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: select volume sink by config target"
```

---

### Task 6: End-to-End mit dem RodeCaster und Dokumentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: alles aus Tasks 1-5
- Produces: nichts, was Code konsumiert

- [ ] **Step 1: Frische Config lernen**

RodeCaster anschließen, gewünschten Fader auf MIDI-Function stellen, dann:

Run: `.venv/bin/rodecaster-volume-bridge --learn`
Expected: Aufforderung, den Fader zu bewegen; danach `Erkannt: channel=… cc=…` und `Gespeichert nach ~/.config/rodecaster-volume-bridge/config.toml`.

- [ ] **Step 2: Geschriebene Config prüfen**

Run: `cat ~/.config/rodecaster-volume-bridge/config.toml`
Expected: enthält `target = "spotify"`, einen `[spotify]`- und einen `[tidal]`-Block.

- [ ] **Step 3: Bridge gegen laufendes Spotify testen**

Spotify starten, Musik abspielen, dann:

Run: `.venv/bin/rodecaster-volume-bridge -v`
Expected: Log-Zeile `bridge running: target=spotify, …`. Fader bewegen → Lautstärke folgt ohne spürbare Verzögerung, und Spotifys eigener Lautstärkeregler in der UI bewegt sich mit.

- [ ] **Step 4: Recovery testen**

Bei laufender Bridge Spotify komplett beenden. Fader bewegen (Bridge darf nicht crashen, Log zeigt `left the bus`). Spotify wieder starten und etwas abspielen.
Expected: Log zeigt `appeared on the bus`, und die Lautstärke springt auf die aktuelle Fader-Position.

- [ ] **Step 5: README aktualisieren**

`README.md` überarbeiten. Der Titel wird `# rodecaster-volume-bridge`, die Einleitung beschreibt beide Targets. Konkret:

- Einleitung: Brücke vom RodeCaster (Pro II/Duo) USB-MIDI zur Lautstärke von **Spotify** (über MPRIS/D-Bus) oder **Tidal** (über das `@vmohammad/api` TidaLuna-Plugin).
- Voraussetzungen: Linux mit ALSA, Python ≥3.11, RodeCaster-Fader auf MIDI-Function. Je nach Target zusätzlich: für Spotify der Desktop-Client mit aktivem MPRIS (bei Flatpak/`spotifyd` ggf. abweichender `bus_name`); für Tidal TidaLuna mit `@vmohammad/api` auf Port 24123.
- Setup: `rodecaster-volume-bridge --learn` (Spotify ist der Default), bzw. `rodecaster-volume-bridge --learn --target tidal`. Dazu der Hinweis, dass ein Target-Wechsel danach nur das Ändern der `target`-Zeile in der Config plus Service-Neustart ist.
- Der Config-Block wird durch das vollständige Beispiel aus der Spec ersetzt (`target`, `[midi]`, `[spotify]`, `[tidal]`, `[throttle]`, `[scale]`), mit einem Satz zu `bus_name` für abweichende Spotify-Builds.
- Alle `rodecaster-tidal-bridge`-Vorkommen inkl. der systemd-Zeilen auf `rodecaster-volume-bridge` ziehen.

- [ ] **Step 6: Behauptungen im README gegenprüfen**

Run: `grep -rn "rodecaster-tidal-bridge" README.md`
Expected: keine Treffer.

Jeden im README genannten Befehl einmal ausführen (`--learn`, den Run-Befehl, die systemd-Zeilen) und bestätigen, dass er so funktioniert wie beschrieben.

- [ ] **Step 7: Volle Suite ein letztes Mal**

Run: `.venv/bin/pytest -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "docs: README for spotify and tidal targets"
```

---

## Verifikation am Ende

Bevor das als fertig gemeldet wird, muss Folgendes tatsächlich gelaufen sein — nicht angenommen:

- `.venv/bin/pytest -v` grün, D-Bus-Tests **nicht** geskippt (mit Session-Bus ausgeführt)
- Fader bewegt → Spotify-Lautstärke folgt hörbar (Task 6, Step 3)
- Spotify beendet und neu gestartet → Bridge überlebt und holt die Fader-Position nach (Task 6, Step 4)
- `grep -rn "rodecaster_tidal_bridge\|rodecaster-tidal-bridge" --exclude-dir=.git --exclude-dir=docs .` ohne Treffer

Wird etwas davon nicht ausgeführt, gehört das explizit in die Abschlussmeldung.
