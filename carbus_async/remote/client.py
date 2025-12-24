from __future__ import annotations

import asyncio
import json
from typing import Optional

from carbus_async.device import CarBusDevice


async def open_remote_device(
    host: str,
    port: int,
    *,
    serial: str,
    password: str,
    use_can: bool = True,
    use_lin: bool = False,
) -> CarBusDevice:
    reader, writer = await asyncio.open_connection(host, port)

    hello = {"role": "client", "serial": str(serial), "password": str(password)}
    writer.write((json.dumps(hello) + "\n").encode("utf-8"))
    await writer.drain()

    line = await asyncio.wait_for(reader.readline(), timeout=10.0)
    resp = json.loads(line.decode("utf-8", errors="ignore") or "{}")
    if not resp.get("ok"):
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        raise RuntimeError(f"relay refused client: {resp}")

    dev = await CarBusDevice.open_stream(
        reader,
        writer,
        logical_port=f"remote://{host}:{port}/{serial}",
        use_can=use_can,
        use_lin=use_lin,
    )
    return dev
