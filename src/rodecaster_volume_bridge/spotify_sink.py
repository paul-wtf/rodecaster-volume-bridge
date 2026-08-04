from __future__ import annotations

import asyncio
import contextlib
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

    Separately, if the sink's own D-Bus session bus connection is lost (e.g.
    the D-Bus daemon restarts, which severs every connection including ours
    and silently clears our NameOwnerChanged handler), the background task
    reconnects with exponential backoff -- mirroring TidalSink's websocket
    reconnect -- and carries the pending value across the reconnect. This is
    orthogonal to the player being present or absent on an otherwise-healthy
    connection.
    """

    def __init__(
        self,
        bus_name: str,
        object_path: str = MPRIS_OBJECT_PATH,
        retry_delay_s: float = 0.2,
        backoff_start: float = 0.5,
        backoff_max: float = 5.0,
    ) -> None:
        self._bus_name = bus_name
        self._object_path = object_path
        self._retry_delay_s = retry_delay_s
        self._backoff_start = backoff_start
        self._backoff_max = backoff_max
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._bus: Optional[MessageBus] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._stop = asyncio.Event()
        self._owned = asyncio.Event()

    async def start(self) -> None:
        try:
            self._bus = await self._connect()
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

    async def _connect(self) -> MessageBus:
        return await MessageBus(bus_type=BusType.SESSION).connect()

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

    async def _get_or_disconnected(
        self, disconnect_fut: asyncio.Future
    ) -> tuple[Optional[int], bool]:
        """Wait for the next queued value, but return early if the bus
        connection dies first.

        ``asyncio.Queue.get()`` is destructive: once the get-task has
        actually completed with a value, that value is gone from the queue
        whether we use it or not. So if the get-task finished -- even if
        ``disconnect_fut`` also fired in the same ``asyncio.wait`` call --
        its value always wins; only an un-finished get-task is cancelled in
        favor of the disconnect. This is the opposite priority from
        ``_wait_owned_or_disconnected`` below, and deliberately so: losing
        this race would silently drop a queued volume value forever.
        """
        get_task = asyncio.ensure_future(self._queue.get())
        try:
            await asyncio.wait(
                [get_task, disconnect_fut], return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            get_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await get_task
            raise
        if get_task.done() and not get_task.cancelled():
            return get_task.result(), False
        get_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await get_task
        return None, True

    async def _wait_owned_or_disconnected(self, disconnect_fut: asyncio.Future) -> bool:
        """Wait for the player to appear, but return early (True) if the bus
        connection dies first.

        Unlike the queue-get case, ``disconnect_fut`` always takes priority
        here, even when both complete in the same ``asyncio.wait`` call:
        ``_owned.wait()`` on an Event that's already set resolves instantly,
        and an already-set ``_owned`` left over from before a connection died
        is exactly the stale state a dead connection leaves behind (its
        NameOwnerChanged handler can never fire again to clear it). Without
        this priority, the already-set Event would "win" every single time
        and the disconnection would never be noticed.
        """
        owned_task = asyncio.ensure_future(self._owned.wait())
        try:
            done, _ = await asyncio.wait(
                [owned_task, disconnect_fut], return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            owned_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await owned_task
            raise
        if disconnect_fut in done:
            owned_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await owned_task
            return True
        return False

    async def _run(self) -> None:
        # Holds a value that was dequeued but not yet successfully sent, so it
        # survives the player restarting -- or the bus connection itself
        # being lost and reconnected -- without being lost.
        pending: Optional[int] = None
        backoff = self._backoff_start
        while not self._stop.is_set():
            try:
                pending = await self._pump(pending)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("unexpected error in spotify sink loop")
                await asyncio.sleep(self._retry_delay_s)
                continue

            if self._stop.is_set():
                break

            # _pump only returns (without raising) when the bus connection
            # itself was lost, not merely when the player is absent -- get a
            # fresh connection and re-arm the name watch before resuming.
            self._owned.clear()
            try:
                self._bus = await self._connect()
                await self._watch_name()
                backoff = self._backoff_start
                log.info("reconnected to the D-Bus session bus")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning(
                    "failed to reconnect to the D-Bus session bus (%s); "
                    "retrying in %.2fs",
                    e,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._backoff_max)

    async def _pump(self, pending: Optional[int]) -> Optional[int]:
        """Send queued volume values on the current bus connection.

        Returns the still-unsent value (or None) once ``_stop`` is set, or as
        soon as the bus connection itself is lost -- detected via
        ``wait_for_disconnect()`` rather than waiting for a send to fail, so a
        dead connection cannot spin retries against it forever. ``_run``
        reconnects and calls this again with the returned value so nothing
        queued is lost.
        """
        assert self._bus is not None
        disconnect_fut = asyncio.ensure_future(self._bus.wait_for_disconnect())
        try:
            while not self._stop.is_set():
                if pending is None:
                    value, disconnected = await self._get_or_disconnected(disconnect_fut)
                    if disconnected:
                        return pending
                    pending = value

                # coalesce: if more values queued already, jump to the newest
                latest = self._drain_to_latest()
                if latest is not None:
                    pending = latest

                if await self._wait_owned_or_disconnected(disconnect_fut):
                    return pending

                # Re-drain: time passed while waiting for the player to
                # appear, so send only the freshest value -- the coalescing
                # guarantee must hold across this wait too, not just before it.
                latest = self._drain_to_latest()
                if latest is not None:
                    pending = latest

                if await self._send(pending):
                    pending = None
                else:
                    # Either the player just vanished (the signal handler will
                    # have cleared _owned, so the wait above blocks next round)
                    # or the call failed for another reason — back off briefly
                    # so a persistent failure cannot spin.
                    await asyncio.sleep(self._retry_delay_s)
            return pending
        finally:
            if not disconnect_fut.done():
                disconnect_fut.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await disconnect_fut

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
