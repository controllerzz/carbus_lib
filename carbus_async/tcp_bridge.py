from __future__ import annotations

import asyncio
import logging

import serial_asyncio

log = logging.getLogger("carbus_async.tcp_bridge")


async def _pump(
    src: asyncio.StreamReader,
    dst: asyncio.StreamWriter,
    direction: str,
    chunk_size: int = 4096,
) -> None:
    try:
        while True:
            data = await src.read(chunk_size)
            if not data:
                log.debug("%s: EOF", direction)
                break
            dst.write(data)
            await dst.drain()
    except asyncio.CancelledError:
        log.debug("%s: cancelled", direction)
        raise
    except Exception as e:
        log.exception("%s: exception: %s", direction, e)
    finally:
        try:
            dst.close()
        except Exception:
            pass


async def handle_client(
    tcp_reader: asyncio.StreamReader,
    tcp_writer: asyncio.StreamWriter,
    *,
    serial_port: str,
    baudrate: int = 115200,
) -> None:
    peer = tcp_writer.get_extra_info("peername")
    log.info("Client connected: %s", peer)

    try:
        serial_reader, serial_writer = await serial_asyncio.open_serial_connection(
            url=serial_port,
            baudrate=baudrate,
        )
        log.info("Opened local serial %s @ %d for %s", serial_port, baudrate, peer)

        pump_tcp_to_serial = asyncio.create_task(
            _pump(tcp_reader, serial_writer, f"{peer} tcp->serial")
        )
        pump_serial_to_tcp = asyncio.create_task(
            _pump(serial_reader, tcp_writer, f"{peer} serial->tcp")
        )

        done, pending = await asyncio.wait(
            [pump_tcp_to_serial, pump_serial_to_tcp],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            with asyncio.SuppressCancelledError if hasattr(asyncio, "SuppressCancelledError") else nullcontext():
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    except Exception as e:
        log.exception("Error in handle_client %s: %s", peer, e)
    finally:
        try:
            tcp_writer.close()
        except Exception:
            pass
        log.info("Client disconnected: %s", peer)


async def run_tcp_bridge(
    *,
    listen_host: str = "0.0.0.0",
    listen_port: int = 7000,
    serial_port: str = "COM6",
    baudrate: int = 115200,
) -> None:
    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, serial_port=serial_port, baudrate=baudrate),
        listen_host,
        listen_port,
    )

    addr = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    log.info(
        "TCP bridge listening on %s -> serial %s @ %d",
        addr,
        serial_port,
        baudrate,
    )

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="TCP bridge for CarBus device (raw byte forwarder)."
    )
    parser.add_argument("--host", default="0.0.0.0", help="Listen host (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=7000, help="Listen TCP port (default 7000)")
    parser.add_argument("--serial", required=True, help="Local serial port (e.g. COM6, /dev/ttyACM0)")
    parser.add_argument("--baudrate", type=int, default=115200, help="Serial baudrate (default 115200)")

    args = parser.parse_args()

    async def _main() -> None:
        await run_tcp_bridge(
            listen_host=args.host,
            listen_port=args.port,
            serial_port=args.serial,
            baudrate=args.baudrate,
        )

    asyncio.run(_main())
