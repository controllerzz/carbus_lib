import asyncio

from carbus_async import CarBusDevice, open_remote_device
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

    dev = await open_remote_device("84.54.37.149", 9000, serial=5957, password="1234")

    print(f"Devise SN: {await dev.get_serial()}")

    await dev.open_can_channel(
        channel=1,
        nominal_bitrate=500_000,
    )

    await dev.ensure_terminator(channel=1, enabled=True)

    isotp = await open_isotp(dev, channel=1, tx_id=0x7E0, rx_id=0x7E8)
    uds = UdsClient(isotp)

    vin = await uds.read_data_by_identifier(0xF190)
    print("VIN:", vin.decode(errors="ignore"))

    await dev.close()


asyncio.run(main())
