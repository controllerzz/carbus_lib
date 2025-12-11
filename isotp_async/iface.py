from __future__ import annotations

from typing import Protocol, Optional
from carbus_async.messages import CanMessage


class CanTransport(Protocol):

    async def send(self, msg: CanMessage) -> None:
        ...

    async def recv(self, timeout: Optional[float] = None) -> Optional[CanMessage]:
        ...
