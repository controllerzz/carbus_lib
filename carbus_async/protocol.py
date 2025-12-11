from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, IntFlag


class Command(IntEnum):
    SYNC = 0xA5
    DEVICE_INFO = 0x06
    DEVICE_OPEN = 0x08
    DEVICE_CLOSE = 0x09
    CHANNEL_CONFIG = 0x11
    CHANNEL_OPEN = 0x18

    FILTER_SET = 0x21      # COMMAND_FILTER_SET
    FILTER_CLEAR = 0x22    # COMMAND_FILTER_CLEAR

    MESSAGE = 0x40
    BUS_ERROR = 0x48

    ERROR = 0xFF


class FilterType(IntEnum):
    STD_11BIT = 0x00
    EXT_29BIT = 0x01


EXTENDED_HEADER_COMMANDS = {Command.MESSAGE, Command.BUS_ERROR}


class HeaderFlags(IntFlag):
    NONE = 0x0000

    CHANNEL_1 = 0x2000
    CHANNEL_2 = 0x4000
    CHANNEL_3 = 0x6000
    CHANNEL_4 = 0x8000

    CONFIRM_REQUIRED = 0x0001


class BusMessageFlags(IntFlag):
    NONE = 0x00000000

    EXTID = 0x00000001
    RTR = 0x00000002
    FDF = 0x00000004
    BRS = 0x00000008
    ESI = 0x00000010

    ERROR_FRAME = 0x01000000
    RX = 0x10000000
    TX = 0x20000000
    BLOCK_TX = 0x30000000


CC_MULTIWORD = 0x80000000

DI_MULTIWORD = CC_MULTIWORD

DI_HARDWARE_ID       = 0x01000000  # тип устройства (HWIdentifiers)
DI_FIRMWARE_VERSION  = 0x02000000  # строка версии прошивки (ASCII, MULTIWORD)
DI_DEVICE_SERIAL     = 0x03000000  # серийный номер (бинарно, MULTIWORD)
DI_FEATURES          = 0x11000000  # битовая маска общих фич
DI_CHANNEL_MAP       = 0x12000000  # карта каналов (тип канала)
DI_CHANNEL_FEATURES  = 0x13000000  # опции по каналам (ALC, TERMINATOR, ...)
DI_FILTER            = 0x14000000  # настройки фильтров по каналам
DI_GATEWAY           = 0x15000000  # возможные пробросы между каналами
DI_CHANNEL_FREQUENCY = 0x16000000  # частота работы CAN/CAN-FD модуля
DI_ISOTP             = 0x21000000  # размер ISO-TP буфера
DI_TX_BUFFER         = 0x22000000  # размер буфера трейсера (в сообщениях)
DI_TX_TASK           = 0x23000000  # количество задач периодической отправки


@dataclass
class CommandHeader:
    command: int
    sequence: int
    flags: int
    dsize: int

    @classmethod
    def from_bytes(cls, data: bytes) -> "CommandHeader":
        if len(data) != 4:
            raise ValueError("CommandHeader требует ровно 4 байта")
        cmd, seq, flg, size = data
        return cls(cmd, seq, flg, size)

    def to_bytes(self) -> bytes:
        return bytes(
            (
                self.command & 0xFF,
                self.sequence & 0xFF,
                self.flags & 0xFF,
                self.dsize & 0xFF,
            )
        )


@dataclass
class MsgCommandHeader:
    command: int
    sequence: int
    flags: int
    dsize: int

    @classmethod
    def from_bytes(cls, data: bytes) -> "MsgCommandHeader":
        if len(data) != 6:
            raise ValueError("MsgCommandHeader требует ровно 6 байт")
        cmd = data[0]
        seq = data[1]
        flags = int.from_bytes(data[2:4], "little")
        dsize = int.from_bytes(data[4:6], "little")
        return cls(cmd, seq, flags, dsize)

    def to_bytes(self) -> bytes:
        return (
            bytes(
                (
                    self.command & 0xFF,
                    self.sequence & 0xFF,
                )
            )
            + self.flags.to_bytes(2, "little")
            + self.dsize.to_bytes(2, "little")
        )


def is_ack(cmd: int) -> bool:
    return 0x80 <= cmd < 0xFF


def base_command_from_ack(cmd: int) -> int:
    return cmd & 0x7F


def need_extended_header(command: int) -> bool:
    try:
        c = Command(command)
    except ValueError:
        return False
    return c in EXTENDED_HEADER_COMMANDS
