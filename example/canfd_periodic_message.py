import asyncio

from carbus_async import CarBusDevice, PeriodicCanSender
from carbus_async.device import CanTiming


async def main(is_debug=False):
    dev = await CarBusDevice.open("COM6")

    # await dev.open_can_channel_custom(
    #     channel=1,
    #
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

    await dev.open_can_channel(
        channel=1,
        nominal_bitrate=500_000,
        data_bitrate=2_000_000,
        fd=True,
        brs=True,
    )

    await dev.ensure_terminator(channel=1, enabled=True)

    sender = PeriodicCanSender(dev)

    def mod(tick, data):
        b = bytearray(data)
        b[0] = tick & 0xFF
        return bytes(b)

    sender.add(
        "cnt",
        channel=1,
        fd=True,
        brs=True,
        can_id=0x100,
        data=b"\x00" * 8,
        period_s=0.5,
        modify=mod
    )

    sender.add(
        "heartbeat",
        channel=1,
        can_id=0x123,
        data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        period_s=0.05,
    )

    try:
        await asyncio.Event().wait()
    finally:
        await sender.stop_all()
        await dev.close()

    return


asyncio.run(main())
