import asyncio
import logging
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
async def test_redrains_to_latest_after_waiting_for_player():
    """The player is absent when set_volume(10) queues, and the sink task
    blocks waiting for it to appear. While it's blocked, the fader moves
    again to 80. Only 0.80 must ever reach the player once it appears --
    the coalescing guarantee must hold across that wait, not just before
    it."""
    sink = SpotifySink(bus_name=TEST_BUS_NAME)
    await sink.start()
    fake_bus = None
    try:
        sink.set_volume(10)
        # Give the sink task time to dequeue 10 and block on _owned.wait();
        # the player isn't exported yet, so there's nothing else it could be
        # doing. This mirrors the sleep-based synchronization already used
        # by test_waits_for_player_that_appears_later above.
        await asyncio.sleep(0.3)

        sink.set_volume(80)

        fake_bus, player = await export_fake()
        assert await wait_for(lambda: player.sets), "value was not applied"
        await asyncio.sleep(0.2)  # give any stragglers a chance to arrive
        assert player.sets == [pytest.approx(0.80)]
    finally:
        await sink.stop()
        if fake_bus is not None:
            fake_bus.disconnect()


@pytest.mark.asyncio
async def test_reconnects_after_own_bus_connection_lost(caplog):
    """Simulates the D-Bus daemon dying out from under the sink (e.g.
    `systemctl --user restart dbus`): the sink's own connection -- not the
    player's -- is severed. dbus-fast clears all user message handlers on
    disconnect, so NameOwnerChanged can never fire again on that connection;
    the sink must notice its own connection died, reconnect, and keep
    delivering values instead of getting stuck retrying against a dead
    connection forever.

    Critically, the *player's* bus connection is severed in the same breath
    as the sink's, so the name genuinely has no owner by the time the sink's
    reconnect calls NameHasOwner -- the seed check alone cannot set _owned.
    Only a NameOwnerChanged signal reaching the *new* connection's re-armed
    watch (AddMatch + add_message_handler redone in _watch_name()) can
    deliver the value that's queued afterwards. If reconnect merely swapped
    in a new bus without re-arming that watch, the assertion below would
    time out instead of passing.
    """
    caplog.set_level(logging.INFO, logger="rodecaster_volume_bridge.spotify_sink")
    fake_bus, player = await export_fake()
    sink = SpotifySink(
        bus_name=TEST_BUS_NAME, backoff_start=0.02, backoff_max=0.05
    )
    await sink.start()
    second_bus = None
    try:
        sink.set_volume(33)
        assert await wait_for(lambda: player.sets), "initial send failed"

        # Sever the sink's own connection -- not the player's -- to simulate
        # the D-Bus daemon (or just our link to it) dying. Also take the
        # player off the bus at the same time, so the name has genuinely no
        # owner once the sink reconnects.
        sink._bus.disconnect()
        fake_bus.disconnect()

        sink.set_volume(66)  # queued while the player is absent

        # Wait for the reconnect to actually finish -- new connection up and
        # NameOwnerChanged watch re-armed -- before bringing the player
        # back, so "player reappears only after the new watch is live" is
        # guaranteed by ordering, not a timing accident.
        assert await wait_for(
            lambda: "reconnected to the D-Bus session bus" in caplog.text,
            timeout=5.0,
        ), "sink never reconnected"

        second_bus, player2 = await export_fake()
        assert await wait_for(lambda: player2.sets, timeout=5.0), (
            "value was not delivered after the player reappeared on the "
            "new connection -- NameOwnerChanged was not re-subscribed"
        )
        assert player2.sets[-1] == pytest.approx(0.66)
    finally:
        await sink.stop()
        if second_bus is not None:
            second_bus.disconnect()


@pytest.mark.asyncio
async def test_unreachable_session_bus_raises_clear_error(monkeypatch):
    """A missing session bus is a setup problem, not a transient state —
    it must fail at start with a message that says so."""
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/nonexistent/rcvb")
    sink = SpotifySink(bus_name=TEST_BUS_NAME)
    with pytest.raises(SessionBusUnavailableError) as excinfo:
        await sink.start()
    assert "session bus" in str(excinfo.value).lower()
