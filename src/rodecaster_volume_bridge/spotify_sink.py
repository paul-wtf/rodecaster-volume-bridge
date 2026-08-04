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
