from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import websockets

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
        # Holds a value that was dequeued but not yet successfully sent,
        # so it survives a reconnect without being lost.
        pending: Optional[int] = None
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self._url, close_timeout=0
                ) as ws:
                    log.info("connected to %s", self._url)
                    backoff = self._backoff_start
                    reader = asyncio.create_task(self._read_replies(ws))
                    try:
                        pending = await self._pump(ws, pending)
                    finally:
                        reader.cancel()
                        await asyncio.gather(reader, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("websocket error (%s); reconnecting in %.2fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._backoff_max)

    async def _read_replies(self, ws: Any) -> None:
        try:
            async for raw in ws:
                try:
                    reply = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(reply, dict) and reply.get("type") == "error":
                    log.warning("tidal api rejected an action: %s", reply.get("error"))
        except websockets.ConnectionClosed:
            pass

    async def _pump(self, ws: Any, pending: Optional[int] = None) -> Optional[int]:
        """Send queued volume values.

        ``pending`` is a value that was dequeued from a previous connection but
        not successfully sent (e.g. because the connection dropped mid-send).
        Returns any unsent value on connection error so the caller can pass it
        to the next connection attempt.
        """
        while not self._stop.is_set():
            if pending is None:
                # Wait for a new value OR for the connection to close,
                # whichever comes first.
                get_task = asyncio.ensure_future(self._queue.get())
                done, _ = await asyncio.wait(
                    [get_task, asyncio.ensure_future(ws.wait_closed())],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if get_task in done:
                    pending = get_task.result()
                else:
                    # Connection closed while waiting; cancel the get task
                    get_task.cancel()
                    try:
                        await get_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    # Exit pump so _run can reconnect
                    return pending

            # coalesce: if more values queued already, jump to the most recent
            latest = self._drain_to_latest()
            if latest is not None:
                pending = latest
            payload = json.dumps({"action": "volume", "volume": pending})
            await ws.send(payload)
            # send succeeded — clear the pending value
            pending = None
        return pending
