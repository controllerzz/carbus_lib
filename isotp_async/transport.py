from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from carbus_async.messages import CanMessage
from .iface import CanTransport


def _st_min_to_seconds(st_min: int) -> float:

    if 0x00 <= st_min <= 0x7F:
        return st_min / 1000.0
    if 0xF1 <= st_min <= 0xF9:
        return (st_min - 0xF0) * 100e-6  # 0xF1 -> 1*100us, ...
    return 0.0


@dataclass
class IsoTpChannel:

    can: CanTransport
    tx_id: int
    rx_id: int

    block_size: int = 8
    st_min_ms: int = 0
    fc_timeout: float = 1.0
    cf_timeout: float = 1.0

    async def send_pdu(self, data: bytes) -> None:
        length = len(data)
        if length <= 7:
            # Single Frame
            pci = bytes([0x00 | (length & 0x0F)])

            if len(data) < 7:
                for _ in range(7-len(data)):
                    data = data + b"\xaa"

            msg = CanMessage(
                can_id=self.tx_id,
                data=pci + data,
            )
            await self.can.send(msg)
            return

        # --- Multi-frame: First Frame ---
        len_hi = (length >> 8) & 0x0F
        len_lo = length & 0xFF
        ff_pci0 = 0x10 | len_hi  # high nibble = 0x1 (FF), low=high bits len
        ff_pci1 = len_lo

        first_data = data[:6]
        ff_payload = bytes([ff_pci0, ff_pci1]) + first_data
        msg = CanMessage(
            can_id=self.tx_id,
            data=ff_payload,
        )
        await self.can.send(msg)

        offset = 6

        # ---  FlowControl от peer ---
        fc_msg = await self.can.recv(timeout=self.fc_timeout)
        if fc_msg is None:
            raise asyncio.TimeoutError("ISO-TP: FlowControl timeout (N_Bs)")

        if not fc_msg.data:
            raise RuntimeError("ISO-TP: empty FlowControl frame")

        fc_pci = fc_msg.data[0]
        fc_type = fc_pci >> 4  # 3 = FC

        if fc_type != 0x3:
            raise RuntimeError(f"ISO-TP: expected FlowControl, got PCI=0x{fc_pci:02X}")

        fs = fc_pci & 0x0F  # FS (0=CTS, 1=WT, 2=OVFLW)
        bs = fc_msg.data[1] if len(fc_msg.data) > 1 else 0
        st_min_raw = fc_msg.data[2] if len(fc_msg.data) > 2 else self.st_min_ms

        if fs == 0x2:
            raise RuntimeError("ISO-TP: FlowControl OVFLW from peer")

        # Для простоты: поддерживаем только FS=CTS (0x0)
        if fs != 0x0:
            raise RuntimeError(f"ISO-TP: unsupported FlowStatus=0x{fs:02X}")

        if bs == 0x00:
            # 0 => "unlimited"
            bs = 0

        st_min = _st_min_to_seconds(st_min_raw)

        # --- Consecutive Frames ---
        seq_num = 1
        frames_in_block = 0

        while offset < length:
            if bs != 0 and frames_in_block >= bs:
                # BS, FC
                fc_msg = await self.can.recv(timeout=self.fc_timeout)
                if fc_msg is None:
                    raise asyncio.TimeoutError("ISO-TP: second FlowControl timeout (N_Bs)")

                fc_pci = fc_msg.data[0]
                fc_type = fc_pci >> 4
                if fc_type != 0x3:
                    raise RuntimeError(f"ISO-TP: expected FlowControl, got PCI=0x{fc_pci:02X}")
                fs = fc_pci & 0x0F
                bs = fc_msg.data[1] if len(fc_msg.data) > 1 else 0
                st_min_raw = fc_msg.data[2] if len(fc_msg.data) > 2 else self.st_min_ms

                if fs == 0x2:
                    raise RuntimeError("ISO-TP: FlowControl OVFLW from peer")
                if fs != 0x0:
                    raise RuntimeError(f"ISO-TP: unsupported FlowStatus=0x{fs:02X}")

                if bs == 0x00:
                    bs = 0
                st_min = _st_min_to_seconds(st_min_raw)
                frames_in_block = 0

            chunk = data[offset:offset + 7]
            offset += len(chunk)

            cf_pci = 0x20 | (seq_num & 0x0F)  # high nibble = 0x2 (CF)
            cf_payload = bytes([cf_pci]) + chunk

            if len(cf_payload) < 8:
                for _ in range(8 - len(cf_payload)):
                    cf_payload = cf_payload + b"\xaa"

            msg = CanMessage(
                can_id=self.tx_id,
                data=cf_payload,
            )
            await self.can.send(msg)

            seq_num = (seq_num + 1) & 0x0F
            if seq_num == 0:
                seq_num = 0x1

            frames_in_block += 1

            if st_min > 0:
                await asyncio.sleep(st_min)

    async def recv_pdu(self, timeout: float = 1.0) -> Optional[bytes]:

        first = await self.can.recv(timeout=timeout)
        if first is None:
            return None

        data = first.data
        if not data:
            return None

        pci = data[0]
        frame_type = pci >> 4

        # --- Single Frame ---
        if frame_type == 0x0:
            length = pci & 0x0F
            return data[1:1 + length]

        # --- First Frame ---
        if frame_type != 0x1:
            return None

        # FF length
        length_hi = pci & 0x0F
        length_lo = data[1] if len(data) > 1 else 0
        total_length = (length_hi << 8) | length_lo

        payload = bytearray(data[2:])

        bs = self.block_size
        st_raw = self.st_min_ms
        fc_pci = 0x30  # type=3 (FC), FS=0 (CTS)
        fc_payload = bytes([fc_pci, bs & 0xFF, st_raw & 0xFF])

        if len(fc_payload) < 8:
            fc_payload = fc_payload + b"\x00" * (8 - len(fc_payload))

        fc_frame = CanMessage(
            can_id=self.tx_id,
            data=fc_payload,
        )
        await self.can.send(fc_frame)

        st_min = _st_min_to_seconds(st_raw)

        expected_sn = 1
        while len(payload) < total_length:
            cf = await self.can.recv(timeout=self.cf_timeout)
            if cf is None:
                raise asyncio.TimeoutError("ISO-TP: CF timeout (N_Cr)")

            if not cf.data:
                continue

            cf_pci = cf.data[0]
            cf_type = cf_pci >> 4
            if cf_type != 0x2:
                continue

            sn = cf_pci & 0x0F
            if sn != (expected_sn & 0x0F):
                raise RuntimeError(
                    f"ISO-TP: wrong sequence number: got {sn}, expected {expected_sn}"
                )

            payload.extend(cf.data[1:])
            expected_sn = (expected_sn + 1) & 0x0F
            if expected_sn == 0:
                expected_sn = 1

            if st_min > 0:
                await asyncio.sleep(st_min)

        return bytes(payload[:total_length])
