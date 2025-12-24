from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Optional

import serial_asyncio

log = logging.getLogger("carbus_remote.agent")


def parse_hostport(s: str) -> tuple[str, int]:
    if ":" not in s:
        raise ValueError("server must be host:port")
    host, p = s.rsplit(":", 1)
    return host, int(p)


async def pipe_bidirectional_streams(
    a_reader: asyncio.StreamReader,
    a_writer: asyncio.StreamWriter,
    b_reader: asyncio.StreamReader,
    b_writer: asyncio.StreamWriter,
    *,
    bufsize: int = 4096,
) -> None:

    async def pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await src.read(bufsize)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except Exception:
            pass
        finally:
            try:
                dst.close()
            except Exception:
                pass

    t1 = asyncio.create_task(pump(a_reader, b_writer), name="pipe_a_to_b")
    t2 = asyncio.create_task(pump(b_reader, a_writer), name="pipe_b_to_a")

    await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)

    for w in (a_writer, b_writer):
        try:
            w.close()
        except Exception:
            pass

    await asyncio.gather(t1, t2, return_exceptions=True)
    for w in (a_writer, b_writer):
        try:
            await w.wait_closed()
        except Exception:
            pass


async def open_serial_with_retry(port: str, baudrate: int, *, attempts: int = 3) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    last: Optional[BaseException] = None
    for i in range(attempts):
        try:
            return await serial_asyncio.open_serial_connection(url=port, baudrate=baudrate)
        except Exception as e:
            last = e
            await asyncio.sleep(0.25 + 0.25 * i)
    assert last is not None
    raise last


async def agent_run(
    *,
    port: str,
    baudrate: int,
    server: str,
    serial: str,
    password: str,
) -> None:
    server_host, server_port = parse_hostport(server)

    session_lock = asyncio.Lock()

    async def open_data_session(session: str) -> None:
        async with session_lock:
            net_r: Optional[asyncio.StreamReader] = None
            net_w: Optional[asyncio.StreamWriter] = None
            dev_r: Optional[asyncio.StreamReader] = None
            dev_w: Optional[asyncio.StreamWriter] = None

            try:
                log.info("Opening data session %s", session)

                net_r, net_w = await asyncio.wait_for(
                    asyncio.open_connection(server_host, server_port),
                    timeout=5.0,
                )

                net_w.write((json.dumps({"role": "agent_data", "session": session}) + "\n").encode("utf-8"))
                await net_w.drain()

                line = await asyncio.wait_for(net_r.readline(), timeout=5.0)
                resp = json.loads(line.decode("utf-8", errors="ignore") or "{}")
                if not resp.get("ok"):
                    log.error("Data session refused %s: %s", session, resp)
                    return

                log.info("Opening COM %s @ %d for session %s", port, baudrate, session)
                dev_r, dev_w = await open_serial_with_retry(port, baudrate, attempts=3)

                log.info("Session %s accepted. Piping bytes (COM <-> relay).", session)
                await pipe_bidirectional_streams(dev_r, dev_w, net_r, net_w)

                log.info("Session %s finished.", session)

            except Exception:
                log.exception("Data session %s crashed", session)

            finally:
                if net_w is not None:
                    try:
                        net_w.close()
                        await net_w.wait_closed()
                    except Exception:
                        pass

                if dev_w is not None:
                    try:
                        dev_w.close()
                        await dev_w.wait_closed()
                    except Exception:
                        pass

    log.info("Connecting to relay %s:%d (control)", server_host, server_port)
    ctrl_reader, ctrl_writer = await asyncio.open_connection(server_host, server_port)

    ctrl_writer.write((json.dumps({"role": "agent", "serial": serial, "password": password}) + "\n").encode("utf-8"))
    await ctrl_writer.drain()

    line = await asyncio.wait_for(ctrl_reader.readline(), timeout=10.0)
    resp = json.loads(line.decode("utf-8", errors="ignore") or "{}")
    if not resp.get("ok"):
        ctrl_writer.close()
        try:
            await ctrl_writer.wait_closed()
        except Exception:
            pass
        raise RuntimeError(f"relay refused agent: {resp}")

    log.info("Agent registered OK. Waiting for sessions... (serial=%s)", serial)

    try:
        while True:
            line = await ctrl_reader.readline()
            if not line:
                log.warning("Control connection closed by relay.")
                break

            try:
                msg = json.loads(line.decode("utf-8", errors="ignore") or "{}")
            except Exception:
                continue

            if msg.get("cmd") == "open_session":
                session = str(msg.get("session", "")).strip()
                if session:
                    asyncio.create_task(open_data_session(session), name=f"agent_data_session_{session}")

    finally:
        try:
            ctrl_writer.close()
            await ctrl_writer.wait_closed()
        except Exception:
            pass

        log.info("Agent stopped.")


async def main_async(
    port: str,
    baudrate: int,
    server: str,
    serial: str,
    password: str,
) -> None:
    await agent_run(
        port=port,
        baudrate=baudrate,
        server=server,
        serial=serial,
        password=password,
    )


def cli() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="COM port, e.g. COM6")
    ap.add_argument("--baudrate", type=int, default=115200)
    ap.add_argument("--server", required=True, help="relay host:port, e.g. 1.2.3.4:9000")
    ap.add_argument("--serial", required=True, help="device serial number (string/int)")
    ap.add_argument("--password", required=True, help="shared password for this serial")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(
        main_async(
            port=args.port,
            baudrate=args.baudrate,
            server=args.server,
            serial=str(args.serial),
            password=str(args.password),
        )
    )


if __name__ == "__main__":
    cli()

