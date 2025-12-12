from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List

import serial_asyncio

from .exceptions import CarBusError, SyncError, CommandError
from .messages import CanMessage


NOMINAL_BITRATE_INDEX: Dict[int, int] = {
    10_000: 0,
    20_000: 1,
    33_300: 2,
    50_000: 3,
    62_500: 4,
    83_300: 5,
    95_200: 6,
    100_000: 7,
    125_000: 8,
    250_000: 9,
    400_000: 10,
    500_000: 11,
    800_000: 12,
    1_000_000: 13,
    # 0xFF = detect,
}


DATA_BITRATE_INDEX: Dict[int, int] = {
    500_000: 0,
    1_000_000: 1,
    2_000_000: 2,
    4_000_000: 3,
    5_000_000: 4,
}


@dataclass(frozen=True)
class CanTiming:
    prescaler: int
    tq_seg1: int
    tq_seg2: int
    sjw: int


@dataclass
class DeviceInfoParam:
    header: int
    data: List[int]

from .protocol import (
    Command,
    CommandHeader,
    MsgCommandHeader,
    HeaderFlags,
    BusMessageFlags,
    CC_MULTIWORD,
    DI_HARDWARE_ID,
    DI_FIRMWARE_VERSION,
    DI_DEVICE_SERIAL,
    DI_FEATURES,
    DI_CHANNEL_MAP,
    DI_CHANNEL_FEATURES,
    DI_FILTER,
    DI_GATEWAY,
    DI_CHANNEL_FREQUENCY,
    DI_ISOTP,
    DI_TX_BUFFER,
    DI_TX_TASK,
    is_ack,
    base_command_from_ack,
    need_extended_header,
)

HW_ID_NAMES: Dict[int, str] = {
    0xFF: "HW_CH30",
    0x02: "HW_ODB_OLD",
    0x01: "HW_CH32",
    0x04: "HW_ODB",
    0x03: "HW_CHP",
    0x11: "HW_CH33",
    0x13: "HW_CHPM03",
    0x14: "HW_ODB_FD",
    0x06: "HW_FDL2_M02",
    0x16: "HW_FDL2_M05",
}

# DI_FEATURES
DI_FEATURE_GATEWAY   = 0x00000001
DI_FEATURE_ISOTP     = 0x00000002
DI_FEATURE_TX_BUFFER = 0x00000004
DI_FEATURE_TX_TASK   = 0x00000008

FLAG_CONFIG_TERMINATOR = 0x05

# ChannelType (DI_CHANNEL_MAP)
CHANNEL_TYPE_MAP: Dict[int, str] = {
    0x00: "NONE",   # CTE_None
    0x01: "CAN",    # CTE_CAN
    0x02: "CANFD",  # CTE_CANFD
    0x10: "LIN",    # CTE_LIN
}

# DI_CHANNEL_FEATURES
DI_CHANNEL_CHANNEL_MASK   = 0x00FF0000
DI_CHANNEL_CHANNEL_SHIFT  = 16

DI_CHANNEL_FEATURE_ALC        = 0x00000001
DI_CHANNEL_FEATURE_TERMINATOR = 0x00000002
DI_CHANNEL_FEATURE_PULLUP     = 0x00000004
DI_CHANNEL_FEATURE_CSD        = 0x00000008
DI_CHANNEL_FEATURE_IDLE       = 0x00000010
DI_CHANNEL_FEATURE_DSD        = 0x00000020
DI_CHANNEL_FEATURE_NONISO     = 0x00000040

# DI_FILTER
DI_FILTER_CHANNEL_MASK  = 0x00FF0000
DI_FILTER_CHANNEL_SHIFT = 16

DI_FILTER_TYPE_MASK     = 0x0000FF00
DI_FILTER_TYPE_SHIFT    = 8
DI_FILTER_SIZE_MASK     = 0x000000FF
DI_FILTER_SIZE_SHIFT    = 0

DI_FILTER_TYPE_8BIT     = 0x01
DI_FILTER_TYPE_11BIT    = 0x02
DI_FILTER_TYPE_29BIT    = 0x04

# DI_GATEWAY
DI_GATEWAY_SRC_MASK    = 0x00FF0000
DI_GATEWAY_SRC_SHIFT   = 16
DI_GATEWAY_DST_MASK    = 0x0000FF00
DI_GATEWAY_DST_SHIFT   = 8
DI_GATEWAY_FILTER_MASK = 0x000000FF
DI_GATEWAY_FILTER_SHIFT = 0

@dataclass
class DeviceInfo:
    params: List[DeviceInfoParam]
    raw_payload: bytes

    @classmethod
    def from_payload(cls, payload: bytes) -> "DeviceInfo":
        if len(payload) % 4 != 0:
            raise ValueError(
                f"DEVICE_INFO payload length {len(payload)} is not multiple of 4"
            )

        words = [
            int.from_bytes(payload[i: i + 4], "little")
            for i in range(0, len(payload), 4)
        ]

        params: List[DeviceInfoParam] = []
        i = 0
        n = len(words)

        while i < n:
            header = words[i]
            i += 1

            if header & CC_MULTIWORD:
                length = (header >> 16) & 0xFF
                data = words[i: i + length]
                i += length
            else:
                data = []

            params.append(DeviceInfoParam(header=header, data=data))

        return cls(params=params, raw_payload=payload)

    @staticmethod
    def _param_code(value: int) -> int:
        return value & 0x7F000000

    def _find_first(self, base: int) -> Optional[DeviceInfoParam]:
        base_code = self._param_code(base)
        for p in self.params:
            if self._param_code(p.header) == base_code:
                return p
        return None

    def _find_all(self, base: int) -> List[DeviceInfoParam]:
        base_code = self._param_code(base)
        return [
            p for p in self.params
            if self._param_code(p.header) == base_code
        ]

    def find_by_prefix(self, prefix: int) -> List[DeviceInfoParam]:
        base_code = self._param_code(prefix)
        return [
            p for p in self.params
            if self._param_code(p.header) == base_code
        ]

    @property
    def hardware_id(self) -> Optional[int]:
        p = self._find_first(DI_HARDWARE_ID)
        if not p:
            return None
        return p.header & 0xFF

    @property
    def hardware_name(self) -> Optional[str]:
        hw_id = self.hardware_id
        if hw_id is None:
            return None
        return HW_ID_NAMES.get(hw_id, f"0x{hw_id:02X}")

    @property
    def firmware_version(self) -> Optional[str]:
        p = self._find_first(DI_FIRMWARE_VERSION)
        if not p:
            return None
        if not p.data:
            return ""

        b = b"".join(w.to_bytes(4, "little") for w in p.data)
        # Обрезаем по 0x00
        if b"\x00" in b:
            b = b.split(b"\x00", 1)[0]
        try:
            return b.decode("ascii", errors="ignore")
        except Exception:
            return b.hex()

    @property
    def serial_bytes(self) -> Optional[bytes]:
        p = self._find_first(DI_DEVICE_SERIAL)
        if not p or not p.data:
            return None
        return b"".join(w.to_bytes(4, "little") for w in p.data)

    @property
    def serial_int(self) -> Optional[int]:
        b = self.serial_bytes
        if b is None:
            return None
        return int.from_bytes(b, "big")

    @property
    def features_mask(self) -> int:
        p = self._find_first(DI_FEATURES)
        if not p:
            return 0
        return p.header & 0x00FFFFFF

    @property
    def feature_gateway(self) -> bool:
        return bool(self.features_mask & DI_FEATURE_GATEWAY)

    @property
    def feature_isotp(self) -> bool:
        return bool(self.features_mask & DI_FEATURE_ISOTP)

    @property
    def feature_tx_buffer(self) -> bool:
        return bool(self.features_mask & DI_FEATURE_TX_BUFFER)

    @property
    def feature_tx_task(self) -> bool:
        return bool(self.features_mask & DI_FEATURE_TX_TASK)

    @property
    def channel_types(self) -> Dict[int, str]:
        p = self._find_first(DI_CHANNEL_MAP)
        if not p:
            return {}

        value = p.header
        b0 = (value >> 0) & 0xFF
        b1 = (value >> 8) & 0xFF
        b2 = (value >> 16) & 0xFF
        out: Dict[int, str] = {}

        for idx, v in enumerate((b0, b1, b2), start=1):
            out[idx] = CHANNEL_TYPE_MAP.get(v, f"0x{v:02X}")

        return out

    @property
    def channel_features(self) -> Dict[int, Dict[str, bool]]:
        res: Dict[int, Dict[str, bool]] = {}
        for p in self._find_all(DI_CHANNEL_FEATURES):
            ch = (p.header & DI_CHANNEL_CHANNEL_MASK) >> DI_CHANNEL_CHANNEL_SHIFT
            mask = p.header & 0x0000FFFF
            if ch == 0:
                continue
            res[ch] = {
                "raw_mask": mask,
                "alc": bool(mask & DI_CHANNEL_FEATURE_ALC),
                "terminator": bool(mask & DI_CHANNEL_FEATURE_TERMINATOR),
                "pullup": bool(mask & DI_CHANNEL_FEATURE_PULLUP),
                "csd": bool(mask & DI_CHANNEL_FEATURE_CSD),
                "idle": bool(mask & DI_CHANNEL_FEATURE_IDLE),
                "dsd": bool(mask & DI_CHANNEL_FEATURE_DSD),
                "noniso": bool(mask & DI_CHANNEL_FEATURE_NONISO),
            }
        return res

    @property
    def filters_info(self) -> List[Dict[str, int]]:
        out: List[Dict[str, int]] = []
        for p in self._find_all(DI_FILTER):
            h = p.header
            ch = (h & DI_FILTER_CHANNEL_MASK) >> DI_FILTER_CHANNEL_SHIFT
            type_mask = (h & DI_FILTER_TYPE_MASK) >> DI_FILTER_TYPE_SHIFT
            size = (h & DI_FILTER_SIZE_MASK) >> DI_FILTER_SIZE_SHIFT

            if ch == 0:
                continue

            info = {
                "channel": ch,
                "type_mask": type_mask,
                "size": size,
                "has_8bit": bool(type_mask & DI_FILTER_TYPE_8BIT),
                "has_11bit": bool(type_mask & DI_FILTER_TYPE_11BIT),
                "has_29bit": bool(type_mask & DI_FILTER_TYPE_29BIT),
            }
            out.append(info)
        return out

    @property
    def gateway_info(self) -> List[Dict[str, int]]:
        out: List[Dict[str, int]] = []
        for p in self._find_all(DI_GATEWAY):
            h = p.header
            src = (h & DI_GATEWAY_SRC_MASK) >> DI_GATEWAY_SRC_SHIFT
            dst = (h & DI_GATEWAY_DST_MASK) >> DI_GATEWAY_DST_SHIFT
            flt = (h & DI_GATEWAY_FILTER_MASK) >> DI_GATEWAY_FILTER_SHIFT
            if src == 0 or dst == 0:
                continue
            out.append({"src": src, "dst": dst, "filters": flt})
        return out

    @property
    def channel_frequencies(self) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for p in self._find_all(DI_CHANNEL_FREQUENCY):
            h = p.header
            ch = (h & DI_GATEWAY_SRC_MASK) >> DI_GATEWAY_SRC_SHIFT  # по доке тот же формат
            freq = h & 0x0000FFFF  # в примере 0x15010078 → 0x0078 → 120 (МГц)
            if ch == 0:
                continue
            # по доке пример: 0x78 (120МГц) — домножаем до Hz
            out[ch] = freq * 1_000_000
        return out

    @property
    def isotp_buffer_size(self) -> Optional[int]:
        p = self._find_first(DI_ISOTP)
        if not p:
            return None
        return p.header & 0x00FFFFFF

    @property
    def tx_buffer_size(self) -> Optional[int]:
        p = self._find_first(DI_TX_BUFFER)
        if not p:
            return None
        return p.header & 0x00FFFFFF

    @property
    def tx_task_count(self) -> Optional[int]:
        p = self._find_first(DI_TX_TASK)
        if not p:
            return None
        return p.header & 0x00FFFFFF

    def find_by_prefix(self, prefix: int) -> List[DeviceInfoParam]:
        return [
            p for p in self.params
            if (p.header & 0xFF000000) == (prefix & 0xFF000000)
        ]

    def find_by_prefix(self, prefix: int) -> List[DeviceInfoParam]:
        """
        Вернуть все параметры, у которых старший байт совпадает с prefix & 0xFF000000.
        Например, prefix=0x01000000 вернёт все DI_*, начинающиеся с 0x01.
        """
        return [
            p
            for p in self.params
            if (p.header & 0xFF000000) == (prefix & 0xFF000000)
        ]


@dataclass
class _PendingRequest:
    future: asyncio.Future
    command: int


@dataclass
class CarBusDevice:
    port: str
    baudrate: int = 115200
    loop: Optional[asyncio.AbstractEventLoop] = None

    _reader: asyncio.StreamReader = field(init=False, repr=False)
    _writer: asyncio.StreamWriter = field(init=False, repr=False)
    _rx_queue: "asyncio.Queue[tuple[int, CanMessage]]" = field(init=False, repr=False)
    _rx_channel_queues: Dict[int, "asyncio.Queue[CanMessage]"] = field(init=False, repr=False)
    _pending: Dict[int, _PendingRequest] = field(init=False, repr=False)
    _seq_counter: int = field(init=False, default=0, repr=False)
    _reader_task: Optional[asyncio.Task] = field(init=False, default=None, repr=False)
    _closed: bool = field(init=False, default=False, repr=False)

    _log: logging.Logger = field(init=False, repr=False)
    _wire_log: logging.Logger = field(init=False, repr=False)

    def _ensure_channel_queue(self, channel: int) -> "asyncio.Queue[CanMessage]":
        q = self._rx_channel_queues.get(channel)
        if q is None:
            q = asyncio.Queue()
            self._rx_channel_queues[channel] = q
        return q

    @classmethod
    async def open(
        cls,
        port: str,
        baudrate: int = 115200,
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        use_can: bool = True,
        use_lin: bool = False,
    ) -> "CarBusDevice":
        self = cls(port=port, baudrate=baudrate, loop=loop)
        await self._connect()
        await self.sync()
        self._start_reader()
        await self.device_open(use_can=use_can, use_lin=use_lin)
        return self

    @classmethod
    async def open_tcp(cls, host: str, port: int, **kwargs) -> "CarBusDevice":
        return await cls.open(f"socket://{host}:{port}", **kwargs)

    async def _connect(self) -> None:
        loop = self.loop or asyncio.get_running_loop()

        self._log = logging.getLogger(f"carbus_async.device.{self.port}")
        self._wire_log = logging.getLogger(f"carbus_async.wire.{self.port}")

        if self.port.startswith("socket://"):
            addr = self.port[len("socket://") :]
            if ":" not in addr:
                raise ValueError(
                    f"Invalid socket URL '{self.port}'. Expected 'socket://host:port'"
                )

            host, port_str = addr.rsplit(":", 1)
            try:
                tcp_port = int(port_str)
            except ValueError as e:
                raise ValueError(
                    f"Invalid TCP port in '{self.port}': {port_str!r}"
                ) from e

            self._log.debug(
                "Connecting via TCP to %s:%d (tcp_bridge)", host, tcp_port
            )

            self._reader, self._writer = await asyncio.open_connection(
                host=host,
                port=tcp_port,
            )

            self._log.debug(
                "Connected to TCP %s:%d (logical port=%s)",
                host,
                tcp_port,
                self.port,
            )

        else:
            self._log.debug(
                "Connecting to serial port %s @ %d using serial_asyncio",
                self.port,
                self.baudrate,
            )
            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                loop=loop,
                url=self.port,
                baudrate=self.baudrate,
            )
            self._log.debug("Connected to %s @ %d", self.port, self.baudrate)

        self._rx_queue = asyncio.Queue()
        self._rx_channel_queues = {}
        self._pending = {}
        self._seq_counter = 0
        self._reader_task = None
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return

        try:
            try:
                await self.device_close()
            except Exception:
                self._log.debug("DEVICE_CLOSE failed, ignoring", exc_info=True)

            if self._reader_task:
                self._reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._reader_task

            self._writer.close()
            await self._writer.wait_closed()
        finally:
            self._closed = True

            for pending in list(self._pending.values()):
                if not pending.future.done():
                    pending.future.set_exception(
                        CarBusError("Device closed before response was received")
                    )
            self._pending.clear()

    def _start_reader(self) -> None:
        if self._reader_task is None or self._reader_task.done():
            self._reader_task = asyncio.create_task(
                self._read_loop(),
                name=f"carbus_read_loop_{self.port}",
            )

    def _next_seq(self) -> int:
        self._seq_counter = (self._seq_counter + 1) & 0xFF
        if self._seq_counter == 0:
            self._seq_counter = 1
        return self._seq_counter

    async def sync(self) -> None:
        frame = bytes((Command.SYNC, 0x00, Command.SYNC, 0x00))
        self._wire_log.debug("TX SYNC: %s", frame.hex(" "))

        self._writer.write(frame)
        await self._writer.drain()

        resp = await self._reader.readexactly(4)
        self._wire_log.debug("RX SYNC: %s", resp.hex(" "))

        if resp != bytes((0x5A, 0x00, 0x5A, 0x00)):
            raise SyncError(f"Unexpected SYNC response: {resp!r}")

    async def _send_raw(
        self,
        command: int,
        *,
        header_flags: int = 0,
        payload: bytes = b"",
        expect_response: bool = True,
    ) -> Tuple[int, int, bytes]:
        if self._closed:
            raise CarBusError("Device is closed")

        seq = self._next_seq()
        dsize = len(payload)

        if need_extended_header(command):
            header = MsgCommandHeader(
                command=command,
                sequence=seq,
                flags=header_flags,
                dsize=dsize,
            )
        else:
            if dsize > 0xFF:
                raise ValueError(
                    f"dsize={dsize} too big for CommandHeader (max 255)"
                )
            header = CommandHeader(
                command=command,
                sequence=seq,
                flags=header_flags,
                dsize=dsize,
            )

        header_bytes = header.to_bytes()
        frame = header_bytes + payload

        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        if expect_response:
            self._pending[seq] = _PendingRequest(future=fut, command=command)

        self._wire_log.debug(
            "TX cmd=0x%02X seq=%d flags=0x%04X dsize=%d :: %s",
            command,
            seq,
            header_flags,
            dsize,
            frame.hex(" "),
        )

        self._writer.write(frame)
        await self._writer.drain()

        if not expect_response:
            return 0, 0, b""

        cmd_resp, flags_resp, payload_resp = await fut
        return cmd_resp, flags_resp, payload_resp

    async def get_device_info(self) -> DeviceInfo:
        cmd, flags, payload = await self._send_raw(
            Command.DEVICE_INFO,
            header_flags=0,
            payload=b"",
            expect_response=True,
        )

        if cmd != Command.DEVICE_INFO:
            raise CommandError(
                f"Unexpected DEVICE_INFO response: cmd=0x{cmd:02X}, flags=0x{flags:04X}"
            )

        return DeviceInfo.from_payload(payload)

    async def device_open(self, *, use_can: bool = True, use_lin: bool = False) -> None:
        if use_can and use_lin:
            mode_val = 0x00  # FULL
        elif use_can and not use_lin:
            mode_val = 0x01  # CAN only
        elif not use_can and use_lin:
            mode_val = 0x02  # LIN only
        else:
            mode_val = 0x00  # FULL по умолчанию

        dc_mode = 0x01000000 | mode_val
        payload = dc_mode.to_bytes(4, "little")

        cmd, flags, resp_payload = await self._send_raw(
            Command.DEVICE_OPEN,
            header_flags=0,
            payload=payload,
            expect_response=True,
        )

        if not is_ack(cmd) or base_command_from_ack(cmd) != Command.DEVICE_OPEN:
            raise CommandError(
                f"Unexpected DEVICE_OPEN response: cmd=0x{cmd:02X}, flags=0x{flags:04X}"
            )

    async def device_close(self) -> None:
        cmd, flags, _ = await self._send_raw(
            Command.DEVICE_CLOSE,
            header_flags=0,
            payload=b"",
            expect_response=True,
        )

        if not is_ack(cmd) or base_command_from_ack(cmd) != Command.DEVICE_CLOSE:
            raise CommandError(
                f"Unexpected DEVICE_CLOSE response: cmd=0x{cmd:02X}, flags=0x{flags:04X}"
            )

    async def open_can_channel(
        self,
        channel: int = 1,
        *,
        nominal_bitrate: int = 500_000,
        fd: bool = False,
        data_bitrate: Optional[int] = None,
        brs: bool = False,
        listen_only: bool = False,
        loopback: bool = False,
        auto_detect: bool = False,
        retransmit: bool = False,
        non_iso: bool = False,
        nominal_index: Optional[int] = None,
        data_index: Optional[int] = None,
    ) -> None:

        if loopback:
            mode_val = 0x02
        elif listen_only:
            mode_val = 0x01
        else:
            mode_val = 0x00

        cc_can_mode = 0x11000000 | mode_val

        if not fd:
            frame_mode = 0x00
        else:
            frame_mode = 0x02 if brs else 0x01

        cc_can_frame = 0x12000000 | frame_mode

        if auto_detect:
            n_index = 0xFF
        elif nominal_index is not None:
            n_index = nominal_index & 0xFF
        else:
            try:
                n_index = NOMINAL_BITRATE_INDEX[nominal_bitrate]
            except KeyError:
                raise ValueError(
                    f"Unsupported nominal bitrate {nominal_bitrate}. "
                    f"Known: {sorted(NOMINAL_BITRATE_INDEX.keys())}"
                ) from None

        cc_bus_speed_n = 0x01000000 | (n_index & 0xFF)

        params: List[int] = [cc_can_mode, cc_can_frame, cc_bus_speed_n]

        if fd:
            if data_index is not None:
                d_index = data_index & 0xFF
            else:
                if data_bitrate is None:
                    raise ValueError("fd=True требует указать data_bitrate или data_index")
                try:
                    d_index = DATA_BITRATE_INDEX[data_bitrate]
                except KeyError:
                    raise ValueError(
                        f"Unsupported data bitrate {data_bitrate}. "
                        f"Known: {sorted(DATA_BITRATE_INDEX.keys())}"
                    ) from None

            cc_bus_speed_d = 0x02000000 | (d_index & 0xFF)
            params.append(cc_bus_speed_d)

        if retransmit:
            params.append(0x13000001)

        if fd and non_iso:
            params.append(0x14000001)

        payload = b"".join(p.to_bytes(4, "little") for p in params)

        header_flags = (channel & 0x0F) * 0x20

        cmd, flags, resp_payload = await self._send_raw(
            Command.CHANNEL_OPEN,
            header_flags=header_flags,
            payload=payload,
            expect_response=True,
        )

        if not is_ack(cmd) or base_command_from_ack(cmd) != Command.CHANNEL_OPEN:
            raise CommandError(
                f"Unexpected CHANNEL_OPEN response: cmd=0x{cmd:02X}, flags=0x{flags:04X}"
            )

    async def open_can_channel_custom(
            self,
            channel: int = 1,
            *,
            nominal_timing: CanTiming | None,
            data_timing: CanTiming | None = None,
            fd: bool = False,
            brs: bool = False,
            listen_only: bool = False,
            loopback: bool = False,
            retransmit: bool = False,
            non_iso: bool = False,
    ) -> None:

        def _build_bus_custom_baudrate_words(
            base_cc: int,
            prescaler: int,
            seg1: int,
            seg2: int,
            sjw: int,
        ) -> list[int]:

            packed = struct.pack("<HHHH", prescaler, seg1, seg2, sjw)
            word1 = int.from_bytes(packed[0:4], "little")
            word2 = int.from_bytes(packed[4:8], "little")

            length_words = 2
            header = base_cc | CC_MULTIWORD | ((length_words & 0xFF) << 16)
            return [header, word1, word2]

        # 1) CAN mode
        if loopback:
            mode_val = 0x02
        elif listen_only:
            mode_val = 0x01
        else:
            mode_val = 0x00
        cc_can_mode = 0x11000000 | mode_val

        # 2) CAN frame (classic/FD/BRS)
        if not fd:
            frame_mode = 0x00  # classic
        else:
            frame_mode = 0x02 if brs else 0x01
        cc_can_frame = 0x12000000 | frame_mode

        params: list[int] = [cc_can_mode, cc_can_frame]

        # 3) Nominal custom bitrate (CC_BUS_SPEED_N)
        if nominal_timing is not None:
            presc=nominal_timing.prescaler
            seg1=nominal_timing.tq_seg1
            seg2=nominal_timing.tq_seg2
            sjw=nominal_timing.sjw
            header_n = 0x01000000 | CC_MULTIWORD | (2 << 16)
            params.append(header_n)

            b = struct.pack("<HHHH", presc, seg1, seg2, sjw)  # BusCustomBaudRate
            params.append(int.from_bytes(b[0:4], "little"))
            params.append(int.from_bytes(b[4:8], "little"))

        # 4) Data custom bitrate (CC_BUS_SPEED_D)
        if fd and data_timing is not None:
            presc=data_timing.prescaler
            seg1=data_timing.tq_seg1
            seg2=data_timing.tq_seg2
            sjw=data_timing.sjw
            header_d = 0x02000000 | CC_MULTIWORD | (2 << 16)
            params.append(header_d)

            b = struct.pack("<HHHH", presc, seg1, seg2, sjw)
            params.append(int.from_bytes(b[0:4], "little"))
            params.append(int.from_bytes(b[4:8], "little"))

        # доп. опции
        if retransmit:
            params.append(0x13000001)
        if non_iso:
            params.append(0x14000001)

        payload = b"".join(p.to_bytes(4, "little") for p in params)

        header_flags = (channel & 0x0F) * 0x20
        cmd, flags, resp_payload = await self._send_raw(
            Command.CHANNEL_OPEN,
            header_flags=header_flags,
            payload=payload,
            expect_response=True,
        )

        if not is_ack(cmd) or base_command_from_ack(cmd) != Command.CHANNEL_OPEN:
            raise CommandError(
                f"Unexpected CHANNEL_OPEN response: cmd=0x{cmd:02X}, flags=0x{flags:04X}"
            )


    async def set_can_filter(
        self,
        channel: int,
        index: int,
        *,
        can_id: int,
        mask: int | None = None,
        extended: bool = False,
    ) -> None:

        if index < 0:
            raise ValueError("filter index must be >= 0")

        filter_type = 0x01 if extended else 0x00

        if mask is None:
            mask = 0x1FFFFFFF if extended else 0x7FF

        payload = struct.pack("<IIII", index, filter_type, can_id, mask)

        header_flags = (channel & 0x0F) * 0x20

        cmd, flags, resp_payload = await self._send_raw(
            Command.FILTER_SET,
            header_flags=header_flags,
            payload=payload,
            expect_response=True,
        )

        if not is_ack(cmd) or base_command_from_ack(cmd) != Command.FILTER_SET:
            raise CommandError(
                f"Unexpected FILTER_SET response: cmd=0x{cmd:02X}, flags=0x{flags:04X}"
            )

    async def set_std_id_filter(
        self,
        channel: int,
        index: int,
        can_id: int,
        mask: int = 0x7FF,
    ) -> None:

        if can_id < 0 or can_id > 0x7FF:
            raise ValueError("can_id for standard ID must be in 0x000..0x7FF")

        await self.set_can_filter(
            channel=channel,
            index=index,
            can_id=can_id,
            mask=mask,
            extended=False,
        )

    async def set_ext_id_filter(
        self,
        channel: int,
        index: int,
        can_id: int,
        mask: int = 0x1FFFFFFF,
    ) -> None:

        if can_id < 0 or can_id > 0x1FFFFFFF:
            raise ValueError("can_id for extended ID must be in 0x00000000..0x1FFFFFFF")

        await self.set_can_filter(
            channel=channel,
            index=index,
            can_id=can_id,
            mask=mask,
            extended=True,
        )

    async def clear_all_filters(
        self,
        channel: int,
        *,
        max_filters: int = 64,
        stop_on_error: bool = True,
    ) -> int:

        cleared = 0
        for idx in range(max_filters):
            try:
                await self.clear_can_filter(channel=channel, index=idx)
                cleared += 1
            except CommandError as e:
                if stop_on_error:
                    self._log.debug(
                        "Stop clearing filters on channel %d at index %d due to error: %s",
                        channel,
                        idx,
                        e,
                    )
                    break
                else:
                    self._log.warning(
                        "Error while clearing filter %d on channel %d: %s",
                        idx,
                        channel,
                        e,
                    )
                    continue

        return cleared

    async def clear_can_filter(
        self,
        channel: int,
        index: int,
    ) -> None:

        if index < 0:
            raise ValueError("filter index must be >= 0")

        payload = struct.pack("<I", index)
        header_flags = (channel & 0x0F) * 0x20

        cmd, flags, resp_payload = await self._send_raw(
            Command.FILTER_CLEAR,
            header_flags=header_flags,
            payload=payload,
            expect_response=True,
        )

        if not is_ack(cmd) or base_command_from_ack(cmd) != Command.FILTER_CLEAR:
            raise CommandError(
                f"Unexpected FILTER_CLEAR response: cmd=0x{cmd:02X}, flags=0x{flags:04X}"
            )

    async def set_terminator(self, channel: int, enabled: bool) -> None:

        state = 0x01 if enabled else 0x00
        channel_flag = (channel & 0x0F) * 0x20
        header_flags = channel_flag | FLAG_CONFIG_TERMINATOR

        payload = bytes((state,))

        cmd, flags, resp_payload = await self._send_raw(
            Command.CHANNEL_CONFIG,
            header_flags=header_flags,
            payload=payload,
            expect_response=True,
        )

        if not is_ack(cmd) or base_command_from_ack(cmd) != Command.CHANNEL_CONFIG:
            raise CommandError(
                f"Unexpected TERMINATOR response: cmd=0x{cmd:02X}, flags=0x{flags:04X}"
            )


    async def send_can(
        self,
        msg: CanMessage,
        *,
        channel: int,
        confirm: bool = False,
        echo: bool = False,
    ) -> None:

        if channel == 1:
            hflags = int(HeaderFlags.CHANNEL_1)
        elif channel == 2:
            hflags = int(HeaderFlags.CHANNEL_2)
        elif channel == 3:
            hflags = int(HeaderFlags.CHANNEL_3)
        elif channel == 4:
            hflags = int(HeaderFlags.CHANNEL_4)
        else:
            hflags = (channel & 0x0F) * 0x20

        if confirm:
            hflags |= int(HeaderFlags.CONFIRM_REQUIRED)

        mflags = BusMessageFlags.NONE
        if msg.extended:
            mflags |= BusMessageFlags.EXTID
        if msg.rtr:
            mflags |= BusMessageFlags.RTR
        if msg.fd:
            mflags |= BusMessageFlags.FDF
        if msg.brs:
            mflags |= BusMessageFlags.BRS
        if not echo:
            mflags |= BusMessageFlags.BLOCK_TX

        if msg.extended:
            raw_id = msg.can_id & 0x1FFFFFFF
        else:
            raw_id = (msg.can_id & 0x7FF) #<< 16

        timestamp = 0
        dlc = len(msg.data) & 0xFF

        header_struct = struct.pack(
            "<IIII",
            int(mflags),
            int(timestamp),
            int(raw_id),
            int(dlc),
        )
        payload = header_struct + msg.data

        await self._send_raw(
            Command.MESSAGE,
            header_flags=hflags,
            payload=payload,
            expect_response=confirm,
        )

    async def receive_can(self) -> tuple[int, CanMessage]:
        return await self._rx_queue.get()

    async def receive_can_on(self, channel: int = 1) -> CanMessage:
        q = self._ensure_channel_queue(channel)
        return await q.get()

    async def receive_can_on_timeout(
        self,
        channel: int = 1,
        timeout: float = 1.0,
    ) -> CanMessage | None:
        try:
            return await asyncio.wait_for(self.receive_can_on(channel), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def _read_loop(self) -> None:
        try:
            while not self._closed:
                cmd_bytes = await self._reader.readexactly(1)
                if not cmd_bytes:
                    break
                cmd = cmd_bytes[0]

                if need_extended_header(cmd):
                    header_rest = await self._reader.readexactly(5)
                    header = MsgCommandHeader.from_bytes(cmd_bytes + header_rest)
                    flags = header.flags
                    dsize = header.dsize
                    seq = header.sequence
                else:
                    header_rest = await self._reader.readexactly(3)
                    header = CommandHeader.from_bytes(cmd_bytes + header_rest)
                    flags = header.flags
                    dsize = header.dsize
                    seq = header.sequence

                payload = b""
                if dsize:
                    payload = await self._reader.readexactly(dsize)

                full_frame = cmd_bytes + header_rest + payload
                self._wire_log.debug(
                    "RX cmd=0x%02X seq=%d flags=0x%04X dsize=%d :: %s",
                    cmd,
                    seq,
                    flags,
                    dsize,
                    full_frame.hex(" "),
                )

                if cmd == Command.ERROR:
                    pending = self._pending.pop(seq, None)
                    if pending is not None and not pending.future.done():
                        pending.future.set_exception(
                            CommandError(
                                f"Device ERROR for seq={seq}, "
                                f"flags=0x{flags:04X}, payload={payload.hex()}"
                            )
                        )
                    continue

                if is_ack(cmd):
                    base_cmd = base_command_from_ack(cmd)
                    pending = self._pending.pop(seq, None)
                    if pending is not None and not pending.future.done():
                        pending.future.set_result((cmd, flags, payload))
                    continue

                if seq in self._pending:
                    pending = self._pending.pop(seq)
                    if not pending.future.done():
                        pending.future.set_result((cmd, flags, payload))
                    continue

                if cmd == Command.MESSAGE:
                    await self._handle_bus_message(flags, payload)
                elif cmd == Command.BUS_ERROR:
                    await self._handle_bus_error(flags, payload)
                else:
                    self._log.debug(
                        "Unhandled async command: cmd=0x%02X, flags=0x%04X, payload=%s",
                        cmd,
                        flags,
                        payload.hex(" "),
                    )
                    continue

        except asyncio.IncompleteReadError:
            self._closed = True
        except Exception as e:
            self._closed = True
            self._log.exception("Read loop exception: %s", e)
        finally:
            for pending in list(self._pending.values()):
                if not pending.future.done():
                    pending.future.set_exception(
                        CarBusError("Read loop terminated before response was received")
                    )
            self._pending.clear()

    async def _handle_bus_message(self, header_flags: int, payload: bytes) -> None:
        if len(payload) < 16:
            return

        flags_val, timestamp_us, _reserved, id_raw, dlc = struct.unpack_from("<IIIII", payload, 0)
        data = payload[20:20 + dlc]

        bus_flags = BusMessageFlags(flags_val)

        if bus_flags & BusMessageFlags.EXTID:
            can_id = id_raw & 0x1FFFFFFF
        else:
            can_id = (id_raw) & 0x7FF

        if header_flags & int(HeaderFlags.CHANNEL_1):
            channel = 1
        elif header_flags & int(HeaderFlags.CHANNEL_2):
            channel = 2
        elif header_flags & int(HeaderFlags.CHANNEL_3):
            channel = 3
        elif header_flags & int(HeaderFlags.CHANNEL_4):
            channel = 4
        else:
            channel = 0

        msg = CanMessage.from_bus_payload(
            flags=bus_flags,
            timestamp_us=timestamp_us,
            can_id=can_id,
            dlc=dlc,
            data=data,
        )

        await self._rx_queue.put((channel, msg))

        if channel != 0:
            q = self._rx_channel_queues.get(channel)
            if q is not None:
                await q.put(msg)


    async def _handle_bus_error(self, header_flags: int, payload: bytes) -> None:
        self._log.warning(
            "BUS_ERROR: flags=0x%04X, payload=%s", header_flags, payload.hex(" ")
        )


async def _example() -> None:
    dev = await CarBusDevice.open("COM6", baudrate=115200)

    info = await dev.get_device_info()
    print("DEVICE_INFO raw:", info.raw_payload.hex(" "))
    for p in info.params:
        print(f"DI header=0x{p.header:08X}, data={[f'0x{w:08X}' for w in p.data]}")

    await dev.open_can_channel(channel=1, nominal_bitrate=500_000, fd=False)

    msg = CanMessage(can_id=0x123, data=b"\x01\x02\x03\x04", dlc=4, channel=1)
    await dev.send_can(msg, confirm=False, echo=True)

    rx = await dev.receive_can()
    print("RX CAN:", rx)

    await dev.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_example())
