import asyncio

from carbus_async import CarBusDevice, PeriodicCanSender


async def main(is_debug=False):
    dev = await CarBusDevice.open("COM6")

    await dev.open_can_channel(
        channel=1,
        nominal_bitrate=500_000,
    )

    await dev.set_terminator(channel=1, enabled=True)

    sender = PeriodicCanSender(dev)

    def mod(tick, data):
        b = bytearray(data)
        b[0] = tick & 0xFF
        return bytes(b)

    sender.add(
        "cnt",
        channel=1,
        can_id=0x100,
        data=b"\x00" * 8,
        period_s=0.5,
        modify=mod)

    sender.add(
        "heartbeat",
        channel=1,
        can_id=0x123,
        data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        period_s=0.1,
    )

    try:
        await asyncio.Event().wait()
    finally:
        await sender.stop_all()
        await dev.close()

    return


asyncio.run(main())
