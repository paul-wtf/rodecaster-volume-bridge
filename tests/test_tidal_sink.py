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
