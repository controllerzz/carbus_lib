from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Optional

from carbus_async.device import CarBusDevice

# подстрой импорт под свой проект
from carbus_async.remote.client import open_remote_device

log = logging.getLogger("carbus.can_bridge.simple")


def _ensure_hooks(dev: CarBusDevice) -> None:
    # фикс для твоей ошибки: где-то в CarBusDevice используется _can_hooks,
    # но он не создаётся в open/open_stream
    if not hasattr(dev, "_can_hooks"):
        dev._can_hooks = []  # type: ignore[attr-defined]


async def _open_local(port: str, baudrate: int) -> CarBusDevice:
    dev = await CarBusDevice.open(port, baudrate=baudrate, use_can=True, use_lin=False)
    _ensure_hooks(dev)
    return dev


async def _open_remote(relay: str, serial: int, password: str) -> CarBusDevice:
    if ":" not in relay:
        raise ValueError("relay must be host:port")
    host, p = relay.rsplit(":", 1)
    dev = await open_remote_device(host, int(p), serial=serial, password=password)
    _ensure_hooks(dev)
    return dev


async def _setup_can_500k(dev: CarBusDevice, channel: int) -> None:
    await dev.open_can_channel(channel=channel, nominal_bitrate=500_000, fd=False)
    await dev.set_std_id_filter(
        channel=1,
        index=0,
        can_id=0x700,
        mask=0x700,
    )
    await dev.ensure_terminator(channel=1, enabled=True)


async def _pump(
    name: str,
    src: CarBusDevice,
    src_ch: int,
    dst: CarBusDevice,
    dst_ch: int,
    stop: asyncio.Event,
) -> None:
    try:
        while not stop.is_set():
            ch, msg = await src.receive_can()
            if ch != src_ch:
                continue
            await dst.send_can(msg, channel=dst_ch, confirm=False, echo=False)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("[%s] stopped by error: %r", name, e)
    finally:
        stop.set()


async def main_async() -> None:
    ap = argparse.ArgumentParser(description="Simple CAN bridge local<->remote via relay (no filters)")
    # defaults чтобы запускать из IDE
    ap.add_argument("--local-port", default="COM6")
    ap.add_argument("--local-baudrate", type=int, default=115200)
    ap.add_argument("--local-channel", type=int, default=1)

    ap.add_argument("--relay", default="185.42.26.80:9000")
    ap.add_argument("--serial", type=int, default=5957)
    ap.add_argument("--password", default="1234")
    ap.add_argument("--remote-channel", type=int, default=1)

    ap.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = ap.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    stop = asyncio.Event()
    local: Optional[CarBusDevice] = None
    remote: Optional[CarBusDevice] = None

    try:
        log.info("Open local device %s ...", args.local_port)
        local = await _open_local(args.local_port, args.local_baudrate)
        await _setup_can_500k(local, args.local_channel)
        log.info("Local CAN ready: ch=%d @ 500k", args.local_channel)

        log.info("Open remote device via relay %s (serial=%d) ...", args.relay, args.serial)
        remote = await _open_remote(args.relay, args.serial, args.password)
        await _setup_can_500k(remote, args.remote_channel)
        log.info("Remote CAN ready: ch=%d @ 500k", args.remote_channel)

        t1 = asyncio.create_task(
            _pump("local->remote", local, args.local_channel, remote, args.remote_channel, stop),
            name="pump_local_remote",
        )
        t2 = asyncio.create_task(
            _pump("remote->local", remote, args.remote_channel, local, args.local_channel, stop),
            name="pump_remote_local",
        )

        log.info("CAN bridge running. Ctrl+C to stop.")
        await asyncio.Event().wait()

    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

        # аккуратно гасим
        for dev in (remote, local):
            if dev is None:
                continue
            try:
                await dev.close()
            except Exception:
                pass

        log.info("CAN bridge stopped.")


if __name__ == "__main__":
    asyncio.run(main_async())
