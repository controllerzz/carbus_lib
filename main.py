import asyncio

from carbus_async import CanMessage
from carbus_async.device import CarBusDevice, CanTiming
from isotp_async.carbus_iface import CarBusCanTransport
from isotp_async import IsoTpChannel
from uds_async.client import UdsClient

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

    # await dev.open_can_channel_custom(
    #     channel=1,
    #     nominal_timing=CanTiming(
    #         prescaler=15,
    #         tq_seg1=12,
    #         tq_seg2=3,
    #         sjw=1
    #     ),
    #     data_timing=CanTiming(
    #         prescaler=6,
    #         tq_seg1=7,
    #         tq_seg2=2,
    #         sjw=1
    #     ),
    #     fd=True,
    #     brs=True,
    # )

    await dev.set_terminator(channel=1, enabled=True)

    await asyncio.sleep(0.5)

    msg = CanMessage(can_id=0x7E0, data=b"\x02\x3E\x00\x00\x00\x00\x00\x00",fd=True, brs=True)
    await dev.send_can(msg, channel=1)

    info = await dev.get_device_info()
    print("HW:", info.hardware_id, info.hardware_name)
    print("FW:", info.firmware_version)
    print("Serial #", info.serial_int)

    print("Features:",
          "gateway" if info.feature_gateway else "",
          "isotp" if info.feature_isotp else "",
          "txbuf" if info.feature_tx_buffer else "",
          "txtask" if info.feature_tx_task else "",
          )

    await dev.clear_all_filters(1)
    await dev.set_std_id_filter(1, index=0, can_id=0x7E8, mask=0x7FF)

    can_tr = CarBusCanTransport(dev, channel=1, rx_id=0x7E8)
    isotp = IsoTpChannel(can_tr, tx_id=0x7E0, rx_id=0x7E8)
    uds = UdsClient(isotp)

    vin = await uds.read_data_by_identifier(0xF190)
    print("VIN:", vin.decode(errors="ignore"))

    await dev.close()


asyncio.run(main())
