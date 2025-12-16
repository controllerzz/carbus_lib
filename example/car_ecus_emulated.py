import asyncio
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from carbus_async import CanIdRouter, RoutedCarBusCanTransport
from carbus_async.device import CarBusDevice
from isotp_async import open_isotp, IsoTpConnection
from uds_async import UdsServer
from uds_async.exceptions import UdsNegativeResponse, UdsError

# import logging
#
# logging.basicConfig(
#     level=logging.DEBUG,
#     format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
# )

TESTER_ID = 0x740
ECU_ID = 0x760

DEFAULT_PORT = "COM6"
DEFAULT_BAUD = 115200
DEFAULT_CAN_CH = 1
DEFAULT_CAN_BITRATE = 500_000

CHANNEL = 1

IN_FILE_ECU = Path("ecu_uds22_params.pkl")
IN_FILE_ABS = Path("uds22_params.pkl")


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


async def setup_uds(dev: CarBusDevice, can_channel: int = DEFAULT_CAN_CH) -> UdsServer:
    ecu_isotp = await open_isotp(dev, channel=can_channel, tx_id=ECU_ID, rx_id=TESTER_ID)
    ecu_uds = UdsServer(ecu_isotp)
    return ecu_uds


NRC_INCORRECT_LENGTH = 0x13
NRC_REQUEST_OUT_OF_RANGE = 0x31


@dataclass
class UdsServiceState:
    did_store: Dict[int, bytes]


def _require_len(req: bytes, n: int, sid: int) -> None:
    if len(req) < n:
        raise UdsNegativeResponse(sid, NRC_INCORRECT_LENGTH)


def _did_from_req(req: bytes, sid: int) -> int:
    _require_len(req, 3, sid)
    return (req[1] << 8) | req[2]


def _rdbi_positive(req: bytes, payload: bytes) -> bytes:
    return bytes((0x62, req[1], req[2])) + payload


def _wdbi_positive(req: bytes) -> bytes:
    return bytes((0x6E, req[1], req[2]))


async def services_init(uds, *, in_file: str | Path) -> UdsServiceState:
    did_store: Dict[int, bytes] = load_dict_pickle(path=in_file)
    state = UdsServiceState(did_store=did_store)

    @uds.service(0x10)
    async def handle_session_control(req: bytes) -> bytes:
        print(f"UDS OpenSession {hex(req[1])}")
        _require_len(req, 2, 0x10)
        session = req[1]
        return bytes((0x50, session, 0x00, 0x32, 0x01, 0xF4))

    @uds.service(0x11)
    async def handle_session_control(req: bytes) -> bytes:
        print(f"UDS ECU Reset {hex(req[1])}")
        return bytes((0x51, req[1]))

    @uds.service(0x14)
    async def handle_session_control(req: bytes) -> bytes:
        return bytes((0x54, 0xFF, 0xFF, 0xFF, 0xFF))

    @uds.service(0x19)
    async def handle_session_control(req: bytes) -> bytes:
        return bytes((0x59, 0x00))

    @uds.service(0x22)
    async def handle_rdbi(req: bytes) -> bytes:
        did = _did_from_req(req, 0x22)

        payload = state.did_store.get(did)

        if payload is None:
            raise UdsNegativeResponse(0x22, NRC_REQUEST_OUT_OF_RANGE)

        print(f"UDS Read Param {hex(did)}: {payload.hex()}")
        return _rdbi_positive(req, payload)

    @uds.service(0x27)
    async def handle_security_access(req: bytes) -> bytes:
        _require_len(req, 2, 0x27)
        sub = req[1]

        is_seed_request = bool(sub & 0x01)
        if is_seed_request:
            return bytes((0x67, sub, 0x11, 0x22, 0x33, 0x44))

        _require_len(req, 6, 0x27)
        return bytes((0x67, sub))

    @uds.service(0x2E)
    async def handle_wdbi(req: bytes) -> bytes:
        _require_len(req, 4, 0x2E)
        did = (req[1] << 8) | req[2]
        state.did_store[did] = bytes(req[3:])

        print(f"UDS Write Param {hex(did)}: {bytes(req[3:]).hex()}")

        return _wdbi_positive(req)

    @uds.service(0x31)
    async def handle_routine_control(req: bytes) -> bytes:
        _require_len(req, 4, 0x31)
        print(f"UDS Routine Control {hex(req[1])} {hex(req[2])} {hex(req[3])}")
        return bytes((0x71, req[1], req[2], req[3]))

    @uds.service(0x3E)
    async def handle_tester_present(req: bytes) -> bytes:
        sub = req[1] if len(req) > 1 else 0x00
        return bytes((0x7E, sub))

    return state


async def main() -> None:
    dev: CarBusDevice | None = None
    try:
        dev = await setup_device()

        router = CanIdRouter(dev, channel=CHANNEL)
        await router.start()

        # ECU #1
        tr_engine = RoutedCarBusCanTransport(dev, CHANNEL, rx_id=0x7E0, router=router)
        isotp_engine = IsoTpConnection(can=tr_engine, tx_id=0x7E8, rx_id=0x7E0)
        uds_engine = UdsServer(isotp_engine)
        await services_init(uds_engine, in_file=IN_FILE_ECU)

        # ECU #2
        tr_abs = RoutedCarBusCanTransport(dev, CHANNEL, rx_id=0x740, router=router)
        isotp_abs = IsoTpConnection(can=tr_abs, tx_id=0x760, rx_id=0x740)
        uds_abs = UdsServer(isotp_abs)
        await services_init(uds_abs, in_file=IN_FILE_ABS)

        print("UDS servers running")

        await asyncio.gather(
            uds_engine.serve_forever(),
            uds_abs.serve_forever(),
        )

    finally:
        if dev is not None:
            await dev.close()


if __name__ == "__main__":
    asyncio.run(main())
