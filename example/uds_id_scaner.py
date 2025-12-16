import asyncio
from dataclasses import dataclass
from typing import List, Tuple, Optional

from tqdm import tqdm

from carbus_async.device import CarBusDevice
from carbus_async.messages import CanMessage


@dataclass(frozen=True)
class CanScanConfig:
    port: str = "COM6"
    baudrate: int = 115200
    channel: int = 1
    nominal_bitrate: int = 500_000

    base_id: int = 0x700
    count: int = 0x100
    timeout_s: float = 0.05

    tester_present_sf: bytes = bytes((0x02, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00))


async def setup_device(cfg: CanScanConfig) -> CarBusDevice:
    dev = await CarBusDevice.open(cfg.port, baudrate=cfg.baudrate)

    await dev.open_can_channel(channel=cfg.channel, nominal_bitrate=cfg.nominal_bitrate)
    await dev.set_terminator(channel=cfg.channel, enabled=True)

    await dev.clear_all_filters(cfg.channel)
    await dev.set_std_id_filter(
        channel=cfg.channel,
        index=0,
        can_id=0x700,
        mask=0x700,
    )

    return dev


def is_positive_tester_present_response(msg: CanMessage) -> bool:
    return len(msg.data) >= 2 and msg.data[1] == 0x7E


async def scan_tester_present_ids(
    dev: CarBusDevice,
    cfg: CanScanConfig,
) -> List[Tuple[int, int]]:
    msg_tx = CanMessage(can_id=0x00, data=cfg.tester_present_sf)
    found: List[Tuple[int, int]] = []

    for offset in tqdm(range(cfg.count), desc="Scan IDs"):
        msg_tx.can_id = cfg.base_id + offset

        await dev.send_can(channel=cfg.channel, msg=msg_tx)
        msg_rx: Optional[CanMessage] = await dev.receive_can_on_timeout(timeout=cfg.timeout_s)

        if msg_rx and is_positive_tester_present_response(msg_rx):
            found.append((msg_tx.can_id, msg_rx.can_id))

    return found


def print_found_pairs(pairs: List[Tuple[int, int]]) -> None:
    if not pairs:
        print("No responses found.")
        return

    for tester_id, ecu_id in pairs:
        print(f"TESTER ID: {tester_id:#05x} / ECU ID: {ecu_id:#05x}")


async def main() -> None:
    cfg = CanScanConfig()
    dev: CarBusDevice | None = None

    try:
        dev = await setup_device(cfg)
        pairs = await scan_tester_present_ids(dev, cfg)
        print_found_pairs(pairs)
    finally:
        if dev is not None:
            await dev.close()


if __name__ == "__main__":
    asyncio.run(main())
