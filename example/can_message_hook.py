import asyncio

from carbus_async import CarBusDevice, CanMessage
from isotp_async import open_isotp
from uds_async import UdsClient
import signal
import logging


async def wait_forever() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        await stop.wait()
    finally:
        return


async def main(is_debug=False):
    dev = await CarBusDevice.open("COM6")

    await dev.open_can_channel(
        channel=1,
        nominal_bitrate=500_000,
    )

    await dev.set_terminator(channel=1, enabled=True)

    @dev.on_can_id(0x7E0)
    async def hook(ch: int, msg: CanMessage):
        print("RX", ch, hex(msg.can_id), bytes(msg.data).hex())

    @dev.on_can_match(can_id=0x7E0, value=b"\x02\x3E\x00")
    async def tp(ch: int, msg: CanMessage):
        print("TesterPresent!")

    print("Running. Press Ctrl+C to stop.")
    try:
        await wait_forever()
    finally:
        await dev.close()


asyncio.run(main())
