import asyncio

from carbus_async import CarBusDevice, PeriodicCanSender, open_remote_device


async def main(is_debug=False):
    dev = await open_remote_device("185.42.26.80", 9000, serial=5957, password="1234")

    await dev.open_can_channel(
        channel=1,
        nominal_bitrate=500_000,
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
        can_id=0x100,
        data=b"\x00" * 8,
        period_s=0.001,
        modify=mod)

    sender.add(
        "heartbeat",
        channel=1,
        can_id=0x123,
        data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        period_s=0.03,
    )

    try:
        await asyncio.Event().wait()
    finally:
        await sender.stop_all()
        await dev.close()

    return


asyncio.run(main())
