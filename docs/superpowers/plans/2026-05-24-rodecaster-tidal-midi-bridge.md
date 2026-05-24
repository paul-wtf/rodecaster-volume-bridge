# RodeCaster → Tidal MIDI Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lokaler Python-Daemon, der die "Music"-Fader-Position vom RodeCaster (USB-MIDI) liest und Tidal's Lautstärke über das `@vmohammad/api` TidaLuna-Plugin (`localhost:24123`) in Echtzeit anpasst.

**Architecture:** Drei kleine Module mit klaren Boundaries — `midi_source` (ALSA-Input), `tidal_sink` (WebSocket-Client mit Reconnect/Coalescing) und `bridge` (Glue + Throttle + Learn-Mode + CLI). Trailing-edge Throttle auf 30 Hz, Config in TOML, systemd-user Service zum Start.

**Tech Stack:** Python 3.11+, `mido` + `python-rtmidi` (ALSA), `websockets`, `pytest` + `pytest-asyncio`, `tomllib` (stdlib für Read, `tomli-w` für Write).

**Spec:** [`docs/superpowers/specs/2026-05-24-rodecaster-tidal-midi-bridge-design.md`](../specs/2026-05-24-rodecaster-tidal-midi-bridge-design.md)

---

## File Structure

```
rodecaster-tidal-bridge/
├── pyproject.toml                              # Task 1
├── .gitignore                                  # Task 1
├── README.md                                   # Task 11
├── src/rodecaster_tidal_bridge/
│   ├── __init__.py                             # Task 1
│   ├── config.py                               # Task 2 (load/save TOML)
│   ├── scale.py                                # Task 3 (pure 127→100 mapping)
│   ├── throttle.py                             # Task 4 (trailing-edge throttle)
│   ├── tidal_sink.py                           # Task 5 (WebSocket sink)
│   ├── midi_source.py                          # Task 6 (ALSA MIDI input)
│   ├── learn.py                                # Task 7 (Learn-Mode)
│   ├── bridge.py                               # Task 8 (run loop / glue)
│   └── __main__.py                             # Task 9 (CLI entrypoint)
├── tests/
│   ├── test_config.py                          # Task 2
│   ├── test_scale.py                           # Task 3
│   ├── test_throttle.py                        # Task 4
│   ├── test_tidal_sink.py                      # Task 5
│   └── test_learn.py                           # Task 7
└── systemd/
    └── rodecaster-tidal-bridge.service         # Task 10
```

**Boundaries:**
- `scale.py`, `throttle.py`, `config.py`, `learn.py` — pure / deterministic, fully unit-tested.
- `tidal_sink.py` — IO, tested against in-process mock WebSocket server.
- `midi_source.py` — Hardware boundary, **manually verified only** (no automated tests).
- `bridge.py` — composes everything; smoke-tested manually.

---

### Task 1: Repo-Skeleton & Packaging

**Files:**
- Create: `/home/paul/git/rodecaster-tidal-bridge/pyproject.toml`
- Create: `/home/paul/git/rodecaster-tidal-bridge/.gitignore`
- Create: `/home/paul/git/rodecaster-tidal-bridge/src/rodecaster_tidal_bridge/__init__.py`

- [ ] **Step 1: Schreibe `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "rodecaster-tidal-bridge"
version = "0.1.0"
description = "Bridge RodeCaster MIDI fader to Tidal volume via @vmohammad/api"
requires-python = ">=3.11"
dependencies = [
    "mido>=1.3",
    "python-rtmidi>=1.5",
    "websockets>=12",
    "tomli-w>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
]

[project.scripts]
rodecaster-tidal-bridge = "rodecaster_tidal_bridge.__main__:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Schreibe `.gitignore`**

```
__pycache__/
*.pyc
.venv/
build/
dist/
*.egg-info/
.pytest_cache/
```

- [ ] **Step 3: Schreibe `src/rodecaster_tidal_bridge/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Virtualenv anlegen und installieren**

Run:
```bash
cd /home/paul/git/rodecaster-tidal-bridge
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```
Expected: kein Fehler. `python-rtmidi` kompiliert ggf. — auf Arch ist `alsa-lib` in der Regel da.

- [ ] **Step 5: Verifizieren**

Run: `.venv/bin/python -c "import mido, websockets, rodecaster_tidal_bridge; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore src/
git commit -m "chore: initial package skeleton"
```

---

### Task 2: Config Load/Save

**Files:**
- Create: `src/rodecaster_tidal_bridge/config.py`
- Create: `tests/test_config.py`

Konfiguriert in `~/.config/rodecaster-tidal-bridge/config.toml`. Wir machen den Pfad injizierbar für Tests.

- [ ] **Step 1: Schreibe failing test**

`tests/test_config.py`:
```python
from pathlib import Path
import textwrap

import pytest

from rodecaster_tidal_bridge.config import Config, load_config, save_config, ConfigMissingError


def test_load_returns_typed_config(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(textwrap.dedent("""
        [midi]
        port_name_contains = "RØDECaster"
        channel = 1
        cc = 7

        [tidal]
        ws_url = "ws://localhost:24123"

        [throttle]
        max_hz = 30
    """).strip())

    cfg = load_config(cfg_file)

    assert cfg.midi_port_name_contains == "RØDECaster"
    assert cfg.midi_channel == 1
    assert cfg.midi_cc == 7
    assert cfg.tidal_ws_url == "ws://localhost:24123"
    assert cfg.throttle_max_hz == 30


def test_load_missing_raises(tmp_path: Path):
    with pytest.raises(ConfigMissingError):
        load_config(tmp_path / "does-not-exist.toml")


def test_save_then_load_roundtrip(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg = Config(
        midi_port_name_contains="RØDECaster",
        midi_channel=2,
        midi_cc=11,
        tidal_ws_url="ws://localhost:24123",
        throttle_max_hz=30,
    )
    save_config(cfg, cfg_file)
    loaded = load_config(cfg_file)
    assert loaded == cfg


def test_save_creates_parent_dirs(tmp_path: Path):
    cfg_file = tmp_path / "nested" / "dir" / "config.toml"
    cfg = Config(
        midi_port_name_contains="X",
        midi_channel=1,
        midi_cc=7,
        tidal_ws_url="ws://localhost:24123",
        throttle_max_hz=30,
    )
    save_config(cfg, cfg_file)
    assert cfg_file.exists()
```

- [ ] **Step 2: Test failt verifizieren**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: ImportError / ModuleNotFoundError für `rodecaster_tidal_bridge.config`.

- [ ] **Step 3: Implementierung**

`src/rodecaster_tidal_bridge/config.py`:
```python
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w


class ConfigMissingError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class Config:
    midi_port_name_contains: str
    midi_channel: int
    midi_cc: int
    tidal_ws_url: str
    throttle_max_hz: int


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "rodecaster-tidal-bridge" / "config.toml"


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigMissingError(f"Config file not found: {path}")
    with path.open("rb") as f:
        data = tomllib.load(f)
    return Config(
        midi_port_name_contains=data["midi"]["port_name_contains"],
        midi_channel=int(data["midi"]["channel"]),
        midi_cc=int(data["midi"]["cc"]),
        tidal_ws_url=data["tidal"]["ws_url"],
        throttle_max_hz=int(data["throttle"]["max_hz"]),
    )


def save_config(cfg: Config, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "midi": {
            "port_name_contains": cfg.midi_port_name_contains,
            "channel": cfg.midi_channel,
            "cc": cfg.midi_cc,
        },
        "tidal": {"ws_url": cfg.tidal_ws_url},
        "throttle": {"max_hz": cfg.throttle_max_hz},
    }
    with path.open("wb") as f:
        tomli_w.dump(payload, f)
```

- [ ] **Step 4: Tests grün**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rodecaster_tidal_bridge/config.py tests/test_config.py
git commit -m "feat: typed config load/save with TOML"
```

---

### Task 3: Value Scaling (127 → 100)

**Files:**
- Create: `src/rodecaster_tidal_bridge/scale.py`
- Create: `tests/test_scale.py`

- [ ] **Step 1: Schreibe failing test**

`tests/test_scale.py`:
```python
import pytest

from rodecaster_tidal_bridge.scale import midi_to_volume


@pytest.mark.parametrize("midi,volume", [
    (0, 0),
    (127, 100),
    (64, 50),     # round(64*100/127) = round(50.39) = 50
    (63, 50),     # round(63*100/127) = round(49.6)  = 50
    (1, 1),       # round(0.79) = 1
])
def test_midi_to_volume(midi: int, volume: int):
    assert midi_to_volume(midi) == volume


@pytest.mark.parametrize("bad", [-1, 128, 200])
def test_midi_to_volume_rejects_out_of_range(bad: int):
    with pytest.raises(ValueError):
        midi_to_volume(bad)
```

- [ ] **Step 2: Test failt verifizieren**

Run: `.venv/bin/pytest tests/test_scale.py -v`
Expected: ImportError.

- [ ] **Step 3: Implementierung**

`src/rodecaster_tidal_bridge/scale.py`:
```python
def midi_to_volume(midi_value: int) -> int:
    if not 0 <= midi_value <= 127:
        raise ValueError(f"MIDI value out of range [0,127]: {midi_value}")
    return round(midi_value * 100 / 127)
```

- [ ] **Step 4: Tests grün**

Run: `.venv/bin/pytest tests/test_scale.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rodecaster_tidal_bridge/scale.py tests/test_scale.py
git commit -m "feat: midi-to-volume scaling with input validation"
```

---

### Task 4: Trailing-Edge Throttle

**Files:**
- Create: `src/rodecaster_tidal_bridge/throttle.py`
- Create: `tests/test_throttle.py`

Async-Throttle mit injizierbarer Clock & Sleep für deterministische Tests.

- [ ] **Step 1: Schreibe failing test**

`tests/test_throttle.py`:
```python
import asyncio
from typing import Callable

import pytest

from rodecaster_tidal_bridge.throttle import TrailingThrottle


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


@pytest.mark.asyncio
async def test_first_call_emits_immediately():
    sent: list[int] = []
    clock = FakeClock()
    throttle = TrailingThrottle(min_interval_s=0.033, time_fn=clock.time, sleep_fn=asyncio.sleep)
    await throttle.submit(50, lambda v: sent.append(v))
    assert sent == [50]


@pytest.mark.asyncio
async def test_burst_only_first_and_last_emit():
    """Rapid submits within the throttle window: first goes through immediately,
    intermediates are dropped, only the most-recent pending value emits at the
    end of the window."""
    sent: list[int] = []
    clock = FakeClock()
    throttle = TrailingThrottle(min_interval_s=0.033, time_fn=clock.time, sleep_fn=clock_sleep(clock))

    await throttle.submit(10, lambda v: sent.append(v))   # immediate
    clock.advance(0.005)
    await throttle.submit(20, lambda v: sent.append(v))   # pending
    clock.advance(0.005)
    await throttle.submit(30, lambda v: sent.append(v))   # overwrites pending
    # let any pending timer fire
    await asyncio.sleep(0)
    clock.advance(0.05)
    await asyncio.sleep(0)
    await throttle.flush()

    assert sent == [10, 30]


@pytest.mark.asyncio
async def test_after_window_next_call_is_immediate_again():
    sent: list[int] = []
    clock = FakeClock()
    throttle = TrailingThrottle(min_interval_s=0.033, time_fn=clock.time, sleep_fn=clock_sleep(clock))

    await throttle.submit(10, lambda v: sent.append(v))
    clock.advance(0.05)
    await throttle.submit(99, lambda v: sent.append(v))
    await throttle.flush()
    assert sent == [10, 99]


def clock_sleep(clock: FakeClock) -> Callable[[float], "asyncio.Future"]:
    async def _sleep(dt: float) -> None:
        clock.advance(dt)
    return _sleep
```

- [ ] **Step 2: Test failt verifizieren**

Run: `.venv/bin/pytest tests/test_throttle.py -v`
Expected: ImportError.

- [ ] **Step 3: Implementierung**

`src/rodecaster_tidal_bridge/throttle.py`:
```python
from __future__ import annotations

import asyncio
import time as _time
from typing import Awaitable, Callable, Optional


class TrailingThrottle:
    """Trailing-edge throttle: first submit emits immediately; subsequent
    submits within `min_interval_s` overwrite a single pending value that
    fires once the window elapses."""

    def __init__(
        self,
        min_interval_s: float,
        time_fn: Callable[[], float] = _time.monotonic,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = min_interval_s
        self._time = time_fn
        self._sleep = sleep_fn
        self._last_send: float = float("-inf")
        self._pending_value: Optional[int] = None
        self._pending_emit: Optional[Callable[[int], None]] = None
        self._task: Optional[asyncio.Task[None]] = None

    async def submit(self, value: int, emit: Callable[[int], None]) -> None:
        now = self._time()
        if now - self._last_send >= self._interval and self._task is None:
            emit(value)
            self._last_send = now
            return
        self._pending_value = value
        self._pending_emit = emit
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._fire_later())

    async def _fire_later(self) -> None:
        wait = self._interval - (self._time() - self._last_send)
        if wait > 0:
            await self._sleep(wait)
        if self._pending_emit is not None and self._pending_value is not None:
            self._pending_emit(self._pending_value)
            self._last_send = self._time()
            self._pending_value = None
            self._pending_emit = None

    async def flush(self) -> None:
        if self._task is not None and not self._task.done():
            await self._task
```

- [ ] **Step 4: Tests grün**

Run: `.venv/bin/pytest tests/test_throttle.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rodecaster_tidal_bridge/throttle.py tests/test_throttle.py
git commit -m "feat: async trailing-edge throttle with injectable clock"
```

---

### Task 5: Tidal WebSocket Sink

**Files:**
- Create: `src/rodecaster_tidal_bridge/tidal_sink.py`
- Create: `tests/test_tidal_sink.py`

WebSocket-Client, der `{"action":"volume","volume":N}` sendet. Wenn die Connection bricht: Reconnect mit exponential Backoff (0.5 s start, max 5 s). Queue coalesced auf jüngsten Wert vor Send.

- [ ] **Step 1: Schreibe failing test**

`tests/test_tidal_sink.py`:
```python
import asyncio
import json

import pytest
import websockets

from rodecaster_tidal_bridge.tidal_sink import TidalSink


@pytest.mark.asyncio
async def test_sends_volume_action_to_mock_server():
    received: list[dict] = []

    async def handler(ws):
        async for msg in ws:
            received.append(json.loads(msg))

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"

        sink = TidalSink(url=url, backoff_start=0.01, backoff_max=0.05)
        await sink.start()
        sink.set_volume(42)
        # give the sender task a chance to flush
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.02)
        await sink.stop()

    assert received == [{"action": "volume", "volume": 42}]


@pytest.mark.asyncio
async def test_coalesces_to_latest_on_reconnect():
    """When connection drops mid-batch, multiple queued updates are
    collapsed to just the latest before sending on the new connection."""
    received: list[dict] = []
    accept_event = asyncio.Event()

    async def handler(ws):
        accept_event.set()
        async for msg in ws:
            received.append(json.loads(msg))

    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    url = f"ws://127.0.0.1:{port}"

    sink = TidalSink(url=url, backoff_start=0.01, backoff_max=0.05)
    await sink.start()
    await accept_event.wait()

    # close server: sink will go into reconnect; queue updates while down
    server.close()
    await server.wait_closed()
    sink.set_volume(10)
    sink.set_volume(20)
    sink.set_volume(30)

    # bring server back on same port
    accept_event2 = asyncio.Event()
    received2: list[dict] = []

    async def handler2(ws):
        accept_event2.set()
        async for msg in ws:
            received2.append(json.loads(msg))

    server2 = await websockets.serve(handler2, "127.0.0.1", port)
    try:
        await asyncio.wait_for(accept_event2.wait(), timeout=2)
        for _ in range(100):
            if received2:
                break
            await asyncio.sleep(0.02)
    finally:
        await sink.stop()
        server2.close()
        await server2.wait_closed()

    # exactly one message, with the latest value
    assert received2 == [{"action": "volume", "volume": 30}]
```

- [ ] **Step 2: Test failt verifizieren**

Run: `.venv/bin/pytest tests/test_tidal_sink.py -v`
Expected: ImportError.

- [ ] **Step 3: Implementierung**

`src/rodecaster_tidal_bridge/tidal_sink.py`:
```python
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import websockets
from websockets.client import WebSocketClientProtocol

log = logging.getLogger(__name__)


class TidalSink:
    def __init__(
        self,
        url: str,
        backoff_start: float = 0.5,
        backoff_max: float = 5.0,
    ) -> None:
        self._url = url
        self._backoff_start = backoff_start
        self._backoff_max = backoff_max
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._task: Optional[asyncio.Task[None]] = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def set_volume(self, value: int) -> None:
        # fire-and-forget; queue is unbounded so put_nowait never blocks
        self._queue.put_nowait(value)

    def _drain_to_latest(self) -> Optional[int]:
        latest: Optional[int] = None
        while True:
            try:
                latest = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return latest

    async def _run(self) -> None:
        backoff = self._backoff_start
        while not self._stop.is_set():
            try:
                async with websockets.connect(self._url) as ws:
                    log.info("connected to %s", self._url)
                    backoff = self._backoff_start
                    await self._pump(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("websocket error (%s); reconnecting in %.2fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._backoff_max)

    async def _pump(self, ws: WebSocketClientProtocol) -> None:
        while not self._stop.is_set():
            value = await self._queue.get()
            # coalesce: if more queued already, jump to the most recent
            latest = self._drain_to_latest()
            if latest is not None:
                value = latest
            payload = json.dumps({"action": "volume", "volume": value})
            await ws.send(payload)
```

- [ ] **Step 4: Tests grün**

Run: `.venv/bin/pytest tests/test_tidal_sink.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rodecaster_tidal_bridge/tidal_sink.py tests/test_tidal_sink.py
git commit -m "feat: tidal websocket sink with reconnect and coalescing"
```

---

### Task 6: MIDI Source (Hardware Boundary)

**Files:**
- Create: `src/rodecaster_tidal_bridge/midi_source.py`

Hier gibt es **keine automatischen Tests** — das ist die ALSA-Hardware-Boundary. Wir machen die Klasse so dünn wie möglich, damit es wenig zu testen gibt, und verifizieren manuell mit dem echten Gerät.

- [ ] **Step 1: Implementierung**

`src/rodecaster_tidal_bridge/midi_source.py`:
```python
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import mido

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CCEvent:
    channel: int   # 1-16 (mido reports 0-15; we add 1)
    cc: int        # 0-127
    value: int     # 0-127


def list_input_ports() -> list[str]:
    return mido.get_input_names()


def find_port(name_contains: str) -> Optional[str]:
    for name in mido.get_input_names():
        if name_contains.lower() in name.lower():
            return name
    return None


async def stream_cc_events(
    name_contains: str,
    reconnect_poll_s: float = 1.0,
) -> AsyncIterator[CCEvent]:
    """Yield CC events from the first matching ALSA input. Reconnects forever
    if the port disappears."""
    loop = asyncio.get_running_loop()
    while True:
        port_name = find_port(name_contains)
        if port_name is None:
            log.warning(
                "no MIDI port containing %r; available: %s",
                name_contains, list_input_ports(),
            )
            await asyncio.sleep(reconnect_poll_s)
            continue
        log.info("opening MIDI port %r", port_name)
        queue: asyncio.Queue[CCEvent] = asyncio.Queue()

        def callback(msg: mido.Message) -> None:
            if msg.type != "control_change":
                return
            loop.call_soon_threadsafe(
                queue.put_nowait,
                CCEvent(channel=msg.channel + 1, cc=msg.control, value=msg.value),
            )

        try:
            with mido.open_input(port_name, callback=callback):
                while True:
                    yield await queue.get()
        except (OSError, IOError) as e:
            log.warning("MIDI port closed (%s); will reconnect", e)
            await asyncio.sleep(reconnect_poll_s)
```

- [ ] **Step 2: Smoke-Check (Linting/Import)**

Run: `.venv/bin/python -c "from rodecaster_tidal_bridge.midi_source import list_input_ports, stream_cc_events; print(list_input_ports())"`
Expected: Liste mit verfügbaren ALSA-MIDI-Inputs auf diesem System. Wenn RodeCaster angeschlossen ist, sollte er drin sein.

- [ ] **Step 3: Commit**

```bash
git add src/rodecaster_tidal_bridge/midi_source.py
git commit -m "feat: ALSA midi input source with reconnect"
```

---

### Task 7: Learn-Mode

**Files:**
- Create: `src/rodecaster_tidal_bridge/learn.py`
- Create: `tests/test_learn.py`

Sammelt CC-Events für N Sekunden und gibt das `(channel, cc)`-Pair zurück, das am häufigsten vorkommt **und** wo die Werte am meisten variieren (nicht nur am häufigsten — denn ein still stehender Encoder feuert ggf. nichts; ein bewegter Fader produziert viele unterschiedliche Werte).

Wir testen mit einem injizierten async-iterator, nicht mit echter Hardware.

- [ ] **Step 1: Schreibe failing test**

`tests/test_learn.py`:
```python
import asyncio
from typing import AsyncIterator

import pytest

from rodecaster_tidal_bridge.learn import detect_fader_cc
from rodecaster_tidal_bridge.midi_source import CCEvent


async def stream(events: list[CCEvent]) -> AsyncIterator[CCEvent]:
    for e in events:
        yield e
        await asyncio.sleep(0)  # cooperative


@pytest.mark.asyncio
async def test_detects_most_varied_cc():
    events = [
        # noisy button on (5, 17): only 2 distinct values
        CCEvent(channel=5, cc=17, value=0),
        CCEvent(channel=5, cc=17, value=127),
        CCEvent(channel=5, cc=17, value=0),
        CCEvent(channel=5, cc=17, value=127),
        # the fader on (1, 7): many distinct values
        *[CCEvent(channel=1, cc=7, value=v) for v in range(0, 128, 8)],
    ]
    result = await detect_fader_cc(stream(events), max_events=999, timeout_s=0.1)
    assert result == (1, 7)


@pytest.mark.asyncio
async def test_returns_none_when_no_cc_events():
    async def empty() -> AsyncIterator[CCEvent]:
        if False:
            yield  # pragma: no cover
    result = await detect_fader_cc(empty(), max_events=999, timeout_s=0.05)
    assert result is None
```

- [ ] **Step 2: Test failt verifizieren**

Run: `.venv/bin/pytest tests/test_learn.py -v`
Expected: ImportError.

- [ ] **Step 3: Implementierung**

`src/rodecaster_tidal_bridge/learn.py`:
```python
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncIterator, Optional

from .midi_source import CCEvent


async def detect_fader_cc(
    events: AsyncIterator[CCEvent],
    max_events: int = 2000,
    timeout_s: float = 10.0,
) -> Optional[tuple[int, int]]:
    """Listen for up to `timeout_s` seconds (or `max_events` events) and return
    the (channel, cc) pair with the most distinct values — i.e. the fader,
    not a button or toggle. Returns None if no CC events arrive."""
    distinct: dict[tuple[int, int], set[int]] = defaultdict(set)
    count = 0

    async def consume() -> None:
        nonlocal count
        async for e in events:
            distinct[(e.channel, e.cc)].add(e.value)
            count += 1
            if count >= max_events:
                return

    try:
        await asyncio.wait_for(consume(), timeout=timeout_s)
    except asyncio.TimeoutError:
        pass

    if not distinct:
        return None
    return max(distinct.items(), key=lambda kv: len(kv[1]))[0]
```

- [ ] **Step 4: Tests grün**

Run: `.venv/bin/pytest tests/test_learn.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rodecaster_tidal_bridge/learn.py tests/test_learn.py
git commit -m "feat: learn-mode picks most-varied CC as fader"
```

---

### Task 8: Bridge Run Loop

**Files:**
- Create: `src/rodecaster_tidal_bridge/bridge.py`

Komposition: MIDI-Stream → Filter auf `(channel, cc)` → Scale → Throttle → Sink. Hier keine separaten Tests; manuell verifizierbar.

- [ ] **Step 1: Implementierung**

`src/rodecaster_tidal_bridge/bridge.py`:
```python
from __future__ import annotations

import asyncio
import logging

from .config import Config
from .midi_source import stream_cc_events
from .scale import midi_to_volume
from .throttle import TrailingThrottle
from .tidal_sink import TidalSink

log = logging.getLogger(__name__)


async def run_bridge(cfg: Config) -> None:
    sink = TidalSink(url=cfg.tidal_ws_url)
    await sink.start()
    interval = 1.0 / cfg.throttle_max_hz
    throttle = TrailingThrottle(min_interval_s=interval)

    log.info(
        "bridge running: matching MIDI port %r, ch=%d cc=%d, throttle=%dHz",
        cfg.midi_port_name_contains, cfg.midi_channel, cfg.midi_cc, cfg.throttle_max_hz,
    )
    try:
        async for ev in stream_cc_events(cfg.midi_port_name_contains):
            if ev.channel != cfg.midi_channel or ev.cc != cfg.midi_cc:
                continue
            volume = midi_to_volume(ev.value)
            await throttle.submit(volume, sink.set_volume)
    finally:
        await throttle.flush()
        await sink.stop()
```

- [ ] **Step 2: Smoke-Check (Import)**

Run: `.venv/bin/python -c "from rodecaster_tidal_bridge.bridge import run_bridge; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/rodecaster_tidal_bridge/bridge.py
git commit -m "feat: bridge run loop composing midi → throttle → sink"
```

---

### Task 9: CLI Entrypoint

**Files:**
- Create: `src/rodecaster_tidal_bridge/__main__.py`

- [ ] **Step 1: Implementierung**

`src/rodecaster_tidal_bridge/__main__.py`:
```python
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
    default_config_path,
    load_config,
    save_config,
)
from .learn import detect_fader_cc
from .midi_source import find_port, list_input_ports, stream_cc_events


DEFAULT_PORT_HINT = "RØDECaster"
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

    if args.learn:
        return asyncio.run(_cmd_learn(args))
    return asyncio.run(_cmd_run(args))


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
    await run_bridge(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Console-Script verifizieren**

Run: `.venv/bin/rodecaster-tidal-bridge --help`
Expected: argparse-Help-Output mit `--learn`, `--config`, `--port-hint`, `--learn-seconds`, `-v`.

- [ ] **Step 3: Commit**

```bash
git add src/rodecaster_tidal_bridge/__main__.py
git commit -m "feat: CLI with --learn and run modes"
```

---

### Task 10: Systemd-User Service

**Files:**
- Create: `systemd/rodecaster-tidal-bridge.service`

- [ ] **Step 1: Schreibe Unit-File**

`systemd/rodecaster-tidal-bridge.service`:
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

- [ ] **Step 2: Commit**

```bash
git add systemd/rodecaster-tidal-bridge.service
git commit -m "feat: systemd user unit for autostart"
```

---

### Task 11: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Schreibe README**

`README.md`:
```markdown
# rodecaster-tidal-bridge

Brücke vom RodeCaster (Pro II/Duo) USB-MIDI zur Tidal-Lautstärke über das
[`@vmohammad/api`](https://github.com/vMohammad24/luna-plugins/tree/master/plugins/api)
TidaLuna-Plugin.

## Voraussetzungen

- Linux mit ALSA
- Python ≥ 3.11
- TidaLuna mit aktivem `@vmohammad/api` Plugin (Port `24123`)
- RodeCaster: gewünschter Fader im Companion / Display auf **MIDI Function** umgestellt

## Installation

\`\`\`bash
git clone <repo> ~/git/rodecaster-tidal-bridge
cd ~/git/rodecaster-tidal-bridge
pip install --user .
\`\`\`

## Setup (einmalig)

\`\`\`bash
rodecaster-tidal-bridge --learn
# bewege den Music-Fader, wenn aufgefordert
\`\`\`

Das schreibt `~/.config/rodecaster-tidal-bridge/config.toml` mit der erkannten
`channel`/`cc`-Kombination.

## Run

\`\`\`bash
rodecaster-tidal-bridge          # foreground
\`\`\`

Oder als Service:
\`\`\`bash
install -Dm644 systemd/rodecaster-tidal-bridge.service \\
  ~/.config/systemd/user/rodecaster-tidal-bridge.service
systemctl --user daemon-reload
systemctl --user enable --now rodecaster-tidal-bridge
journalctl --user -u rodecaster-tidal-bridge -f
\`\`\`

## Konfiguration

`~/.config/rodecaster-tidal-bridge/config.toml`:

\`\`\`toml
[midi]
port_name_contains = "RØDECaster"
channel = 1
cc = 7

[tidal]
ws_url = "ws://localhost:24123"

[throttle]
max_hz = 30
\`\`\`

## Entwicklung

\`\`\`bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
\`\`\`
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with install, learn, run"
```

---

### Task 12: End-to-End Smoke Test (manuell)

Keine Code-Änderungen — Verifikation auf echter Hardware.

- [ ] **Step 1: API-Plugin verifizieren**

Run: `curl -s http://localhost:24123/ | head -c 200`
Expected: JSON mit aktueller Playback-State.

- [ ] **Step 2: RodeCaster sichtbar?**

Run: `.venv/bin/python -c "from rodecaster_tidal_bridge.midi_source import list_input_ports; print(list_input_ports())"`
Expected: Liste enthält etwas mit "RØDECaster" oder ähnlich.

- [ ] **Step 3: Fader auf MIDI Function umstellen**

Im RodeCaster-Companion-App oder am Gerät: gewünschter Fader-Channel → MIDI Function. Falls schon erledigt, überspringen.

- [ ] **Step 4: Learn-Mode**

Run: `.venv/bin/rodecaster-tidal-bridge --learn -v`
Während des Countdowns: Fader voll auf und voll ab bewegen.
Expected: `Erkannt: channel=… cc=…` und Config gespeichert.

- [ ] **Step 5: Run**

Run: `.venv/bin/rodecaster-tidal-bridge -v`
Spiele etwas in Tidal ab; bewege den Fader; beobachte Tidal-Volume-Slider:
- Geht hoch wenn Fader hoch, runter wenn Fader runter.
- Keine sichtbaren Sprünge / Bursts.
- Logs zeigen keine kontinuierlichen WebSocket-Fehler.

- [ ] **Step 6: Systemd-Install (optional)**

```bash
install -Dm644 systemd/rodecaster-tidal-bridge.service \
  ~/.config/systemd/user/rodecaster-tidal-bridge.service
systemctl --user daemon-reload
systemctl --user enable --now rodecaster-tidal-bridge
systemctl --user status rodecaster-tidal-bridge
```
Expected: `active (running)`.

---

## Self-Review-Notiz

Nach dem ersten Schreiben dieses Plans habe ich folgendes verifiziert:

1. **Spec-Coverage:** Jeder Punkt aus der Spec (3-Modul-Architektur, Learn-Mode, Throttle 30 Hz mit trailing-edge, WebSocket mit Coalescing-Reconnect, systemd-User-Unit, Config-TOML, manueller MIDI-Test) hat einen zugeordneten Task.
2. **Type-Konsistenz:** `Config`-Felder durchgängig `midi_port_name_contains` / `midi_channel` / `midi_cc` / `tidal_ws_url` / `throttle_max_hz`. `CCEvent`-Felder `channel/cc/value`. `TrailingThrottle.submit(value, emit)` / `flush()`. `TidalSink.set_volume(value)` / `start()` / `stop()`. Konsistent zwischen Definition (Task 2/4/5/6) und Verwendung (Task 7/8/9).
3. **Keine Placeholder:** Code in jedem Step ist konkret, keine TODOs.
