# isotp_async/api.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

# from carbus_async import CanIdRouter, RoutedCarBusCanTransport
from isotp_async import IsoTpChannel, CarBusCanTransport, IsoTpConnection


@dataclass(frozen=True)
class IsoTpEndpoint:
    tx_id: int
    rx_id: int
    channel: int = 1


async def open_isotp(
    dev: Any,
    *,
    endpoint: IsoTpEndpoint | None = None,
    channel: int = 1,
    tx_id: int | None = None,
    rx_id: int | None = None,
    router: Any | None = None,
    **channel_kwargs,
) -> IsoTpChannel:

    if endpoint is not None:
        channel = endpoint.channel
        tx_id = endpoint.tx_id
        rx_id = endpoint.rx_id

    if tx_id is None or rx_id is None:
        raise ValueError("tx_id and rx_id are required (or pass endpoint=...)")

    # ЛЕНИВЫЕ ИМПОРТЫ, чтобы не было circular import:
    if router is None:
        from isotp_async.carbus_iface import CarBusCanTransport  # <-- подстрой путь под твой проект
        can_tr = CarBusCanTransport(dev, channel=channel, rx_id=rx_id)
    else:
        from carbus_async.can_router import RoutedCarBusCanTransport  # <-- подстрой путь
        can_tr = RoutedCarBusCanTransport(dev, channel=channel, rx_id=rx_id, router=router)

    return IsoTpChannel(can_tr, tx_id=tx_id, rx_id=rx_id, **channel_kwargs)


@dataclass(frozen=True)
class IsoTpCanEndpoint:
    rx_id: int   # что слушаем (request -> ECU)
    tx_id: int   # куда отвечаем (ECU -> tester)


class IsoTpNetwork:
    def __init__(self, base_send, router: CanIdRouter):
        self._send = base_send
        self._router = router

    def endpoint(self, ep: IsoTpCanEndpoint) -> IsoTpConnection:
        transport = RoutedCarBusCanTransport(
            dev=..., channel=..., rx_id=ep.rx_id, router=self._router
        )
        return IsoTpConnection(transport=transport, tx_id=ep.tx_id)
