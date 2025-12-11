from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .protocol import BusMessageFlags


class MessageDirection(str, Enum):
    RX = "rx"
    TX = "tx"
    UNKNOWN = "unknown"


@dataclass
class CanMessage:
    can_id: int
    data: bytes = b""
    extended: bool = False
    rtr: bool = False
    fd: bool = False
    brs: bool = False
    timestamp_us: int = 0

    @property
    def dlc(self) -> int:
        return len(self.data)

    @classmethod
    def from_bus_payload(
        cls,
        *,
        flags: BusMessageFlags,
        timestamp_us: int,
        can_id: int,
        dlc: int,
        data: bytes,
    ) -> "CanMessage":
        extended = bool(flags & BusMessageFlags.EXTID)
        rtr = bool(flags & BusMessageFlags.RTR)
        fd = bool(flags & BusMessageFlags.FDF)
        brs = bool(flags & BusMessageFlags.BRS)

        payload = data[:dlc]

        return cls(
            can_id=can_id,
            data=payload,
            extended=extended,
            rtr=rtr,
            fd=fd,
            brs=brs,
            timestamp_us=timestamp_us,
        )
