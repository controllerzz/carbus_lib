import asyncio
import pickle
from pathlib import Path

from tqdm import tqdm

from carbus_async.device import CarBusDevice
from isotp_async import open_isotp
from uds_async import UdsClient
from uds_async.exceptions import UdsNegativeResponse, UdsError


TESTER_ID = 0x740
ECU_ID = 0x760

DEFAULT_PORT = "COM6"
DEFAULT_BAUD = 115200
DEFAULT_CAN_CH = 1
DEFAULT_CAN_BITRATE = 500_000

DID_RANGE = range(0x10000)
OUT_FILE = Path("uds22_params.pkl")


def save_dict_pickle(path: str | Path, data: dict[int, bytes]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)


def load_dict_pickle(path: str | Path) -> dict[int, bytes]:
    path = Path(path)
    with path.open("rb") as f:
        obj = pickle.load(f)
    if not isinstance(obj, dict):
        raise TypeError(f"Expected dict in pickle file, got {type(obj).__name__}")
    return obj


async def setup_device(
    port: str = DEFAULT_PORT,
    baudrate: int = DEFAULT_BAUD,
    can_channel: int = DEFAULT_CAN_CH,
    nominal_bitrate: int = DEFAULT_CAN_BITRATE,
) -> CarBusDevice:
    dev = await CarBusDevice.open(port, baudrate=baudrate)

    await dev.open_can_channel(channel=can_channel, nominal_bitrate=nominal_bitrate)
    await dev.set_terminator(channel=can_channel, enabled=True)

    await dev.clear_all_filters(can_channel)
    await dev.set_std_id_filter(channel=can_channel, index=0, can_id=0x700, mask=0x700)

    return dev


async def setup_uds(dev: CarBusDevice, can_channel: int = DEFAULT_CAN_CH) -> UdsClient:
    isotp = await open_isotp(dev, channel=can_channel, tx_id=TESTER_ID, rx_id=ECU_ID)
    uds = UdsClient(isotp)

    await uds.diagnostic_session_control(session=0x03)
    uds.p2_timeout = 0.05

    return uds


async def read_did_safe(
    uds,
    did: int,
    *,
    retries: int = 5,
    retry_delay: float = 0.05,
) -> bytes | None:

    for attempt in range(retries + 1):
        try:
            return await uds.read_data_by_identifier(did)

        except (UdsNegativeResponse, UdsError):
            return None

        except TimeoutError:
            if attempt >= retries:
                return None
            await asyncio.sleep(retry_delay * (2 ** attempt))

        except asyncio.CancelledError:
            raise


async def dump_dids(uds, dids, *, retries: int = 10) -> dict[int, bytes]:
    results: dict[int, bytes] = {}

    for did in tqdm(dids, desc="UDS 0x22 scan"):
        value = await read_did_safe(uds, did, retries=retries)
        if value is not None:
            results[did] = value

    return results


def bytes_to_ascii_preview(data: bytes, max_len: int = 64) -> str:
    chunk = data[:max_len]
    s = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
    if len(data) > max_len:
        s += "..."
    return s


def print_results(results: dict[int, bytes]) -> None:
    for did in sorted(results.keys()):
        data = results[did]
        print(
            f"{did:#06x} | size={len(data):3d} | hex={data.hex()} | ascii='{bytes_to_ascii_preview(data)}'"
        )


async def main() -> None:
    dev: CarBusDevice | None = None
    try:
        dev = await setup_device()
        uds = await setup_uds(dev)

        results = await dump_dids(uds, DID_RANGE)

        save_dict_pickle(OUT_FILE, results)
        print(f"\nSaved {len(results)} DIDs to: {OUT_FILE.resolve()}\n")

        print_results(results)

    finally:
        if dev is not None:
            await dev.close()


if __name__ == "__main__":
    asyncio.run(main())
