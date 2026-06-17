from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from isotp_async.transport import IsoTpChannel
from .exceptions import UdsError, UdsNegativeResponse


@dataclass
class UdsClient:

    isotp: IsoTpChannel
    p2_timeout: float = 1.0

    async def _request(self, payload: bytes) -> bytes:
        await self.isotp.send_pdu(payload)

        while True:
            resp = await self.isotp.recv_pdu(timeout=self.p2_timeout)

            if resp is None:
                raise TimeoutError("UDS response timeout")

            if resp[0] == 0x7F and resp[2] == 0x78:
                continue

            break

        if resp[0] == 0x7F:
            if len(resp) < 3:
                raise UdsError("Malformed UDS negative response")

            sid = resp[1]
            nrc = resp[2]
            raise UdsNegativeResponse(req_sid=sid, nrc=nrc)

        return resp

    async def tester_present(self, suppress_response: bool = False) -> Optional[bytes]:
        sub = 0x80 if suppress_response else 0x00
        req = bytes([0x3E, sub])

        if suppress_response:
            try:
                resp = await self._request(req)
            except TimeoutError:
                return None

            return resp

        resp = await self._request(req)

        if resp[0] != 0x7E:
            raise UdsError(f"Unexpected SID 0x{resp[0]:02X} for TesterPresent")

        return resp

    async def diagnostic_session_control(self, session: int) -> bytes:
        req = bytes([0x10, session & 0xFF])
        resp = await self._request(req)

        if resp[0] != 0x50:
            raise UdsError(f"Unexpected SID 0x{resp[0]:02X} for DSC")

        return resp

    async def read_data_by_identifier(self, did: int) -> bytes:
        req = bytes([0x22, (did >> 8) & 0xFF, did & 0xFF])
        resp = await self._request(req)

        if resp[0] != 0x62:
            raise UdsError(f"Unexpected SID 0x{resp[0]:02X} for RDBI")

        if len(resp) < 3:
            raise UdsError("Malformed RDBI response")

        return resp[3:]

    async def write_data_by_identifier(self, did: int, data: bytes) -> bytes:
        req = bytes([0x2E, (did >> 8) & 0xFF, did & 0xFF, *data])
        resp = await self._request(req)

        if resp[0] != 0x6E:
            raise UdsError(f"Unexpected SID 0x{resp[0]:02X} for WDBI")

        return resp

    async def security_access_get_seed(self, level: int, data: bytes | None = None) -> bytes:
        req = bytes([0x27, level & 0xFF]) + (data or b"")
        resp = await self._request(req)

        if resp[0] != 0x67:
            raise UdsError(f"Unexpected SID 0x{resp[0]:02X} for SAGS")

        return resp[2:]

    async def security_access_send_key(self, level: int, key: bytes) -> bytes:
        req = bytes([0x27, level & 0xFF]) + key
        resp = await self._request(req)

        if resp[0] != 0x67:
            raise UdsError(f"Unexpected SID 0x{resp[0]:02X} for SASK")

        return resp
