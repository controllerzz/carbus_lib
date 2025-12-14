# isotp_async/api.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from isotp_async import IsoTpChannel, CarBusCanTransport


@dataclass(frozen=True)
class IsoTpEndpoint:
    tx_id: int
    rx_id: int
    channel: int = 1


async def open_isotp(dev: Any, *, endpoint: IsoTpEndpoint | None = None,
                     channel: int = 1, tx_id: int | None = None, rx_id: int | None = None,
                     **channel_kwargs) -> IsoTpChannel:

    if endpoint is not None:
        channel = endpoint.channel
        tx_id = endpoint.tx_id
        rx_id = endpoint.rx_id

    if tx_id is None or rx_id is None:
        raise ValueError("tx_id and rx_id are required (or pass endpoint=...)")

    can_tr = CarBusCanTransport(dev, channel=channel, rx_id=rx_id)
    return IsoTpChannel(can_tr, tx_id=tx_id, rx_id=rx_id, **channel_kwargs)
