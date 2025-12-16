import asyncio

from carbus_async import CarBusDevice
from isotp_async import open_isotp
from uds_async import UdsClient

import logging

async def main(is_debug=False):

    if is_debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        logging.getLogger("carbus_async.wire").setLevel(logging.DEBUG)

    dev = await CarBusDevice.open("COM6")

    await dev.open_can_channel(
        channel=1,
        nominal_bitrate=500_000,
    )

    await dev.set_terminator(channel=1, enabled=True)

    isotp = await open_isotp(dev, channel=1, tx_id=0x7E0, rx_id=0x7E8)
    uds = UdsClient(isotp)

    vin = await uds.read_data_by_identifier(0xF190)
    print("VIN:", vin.decode(errors="ignore"))

    await dev.close()


asyncio.run(main())
