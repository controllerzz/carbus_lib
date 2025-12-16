import asyncio
import contextlib
from typing import Dict, Optional, Tuple

from carbus_async import CanMessage
from isotp_async.iface import CanTransport


class CanIdRouter:
    def __init__(self, dev, channel: int, queue_size: int = 256):
        self._dev = dev
        self._channel = channel
        self._queues: Dict[int, asyncio.Queue] = {}
        self._queue_size = queue_size
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    def get_queue(self, can_id: int) -> asyncio.Queue:
        q = self._queues.get(can_id)
        if q is None:
            q = asyncio.Queue(maxsize=self._queue_size)
            self._queues[can_id] = q
        return q

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._stop.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self):
        while not self._stop.is_set():
            ch, msg = await self._dev.receive_can()
            if ch != self._channel:
                continue

            q = self._queues.get(msg.can_id)
            if q is None:
                # никто не подписан на этот CAN-ID — просто игнор
                continue

            # если очередь забита — можно дропать самый старый или новый
            if q.full():
                _ = q.get_nowait()
            q.put_nowait(msg)


class RoutedCarBusCanTransport(CanTransport):
    def __init__(self, dev, channel: int, rx_id: int, router: CanIdRouter) -> None:
        self._dev = dev
        self._channel = channel
        self._rx_id = rx_id
        self._router = router
        self._queue = router.get_queue(rx_id)

    async def send(self, msg: CanMessage) -> None:
        await self._dev.send_can(msg, channel=self._channel, confirm=False, echo=False)

    async def recv(self, timeout: Optional[float] = None) -> Optional[CanMessage]:
        try:
            if timeout is None:
                return await self._queue.get()
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
