from __future__ import annotations

from dataclasses import dataclass


class UdsError(Exception):
    ...

@dataclass
class UdsNegativeResponse(UdsError):

    req_sid: int
    nrc: int

    def __str__(self) -> str:
        return f"UDS NRC 0x{self.nrc:02X} for SID 0x{self.req_sid:02X}"
