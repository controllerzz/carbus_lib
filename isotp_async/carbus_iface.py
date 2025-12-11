from __future__ import annotations

import asyncio
from typing import Optional

from carbus_async.device import CarBusDevice
from carbus_async.messages import CanMessage


from .iface import CanTransport


class CarBusCanTransport(CanTransport):
    def __init__(self, dev: CarBusDevice, channel: int, rx_id: int) -> None:
        self._dev = dev
        self._channel = channel
        self._rx_id = rx_id

    async def send(self, msg: CanMessage) -> None:
        await self._dev.send_can(
            msg,
            channel=self._channel,
            confirm=False,
            echo=False,
        )

    async def recv(self, timeout: Optional[float] = None) -> Optional[CanMessage]:
        while True:
            if timeout is None:
                ch, msg = await self._dev.receive_can()
            else:
                try:
                    ch, msg = await asyncio.wait_for(
                        self._dev.receive_can(),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    return None

            if ch != self._channel:
                continue
            if msg.can_id != self._rx_id:
                continue

            return msg
