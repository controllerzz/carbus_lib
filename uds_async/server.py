from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Optional

from isotp_async.transport import IsoTpChannel
from .exceptions import UdsNegativeResponse

UdsHandler = Callable[[bytes], Awaitable[Optional[bytes]]]


@dataclass
class UdsServer:

    isotp: IsoTpChannel
    p2_timeout: float = 1.0
    handlers: Dict[int, UdsHandler] = field(default_factory=dict)

    async def serve_forever(self) -> None:
        while True:
            try:
                req = await self.isotp.recv_pdu(timeout=self.p2_timeout)
            except asyncio.CancelledError:
                break

            if not req:
                continue

            sid = req[0]
            handler = self.handlers.get(sid)
            if handler is None:
                # ServiceNotSupported
                await self._send_negative_response(sid, 0x11)
                continue

            try:
                resp = await handler(req)
                if resp is None:
                    continue

                await self.isotp.send_pdu(resp)

            except UdsNegativeResponse as e:
                await self._send_negative_response(e.req_sid, e.nrc)

            except Exception:
                # General programming failure (0x72)
                await self._send_negative_response(sid, 0x72)

    async def _send_negative_response(self, sid: int, nrc: int) -> None:
        payload = bytes([0x7F, sid & 0xFF, nrc & 0xFF])
        await self.isotp.send_pdu(payload)

    def add_handler(self, sid: int, handler: UdsHandler) -> None:
        self.handlers[sid & 0xFF] = handler

    def service(self, sid: int):
        def decorator(func: UdsHandler) -> UdsHandler:
            self.add_handler(sid, func)
            return func
        return decorator
