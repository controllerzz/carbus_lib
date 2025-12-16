from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Union

from .messages import CanMessage
from .device import CarBusDevice

ModifyFn = Callable[[int, bytes], Union[bytes, Awaitable[bytes]]]


@dataclass
class PeriodicJob:
    name: str
    can_id: int
    data: bytes
    period_s: float
    channel: int = 1
    extended: bool = False
    fd: bool = False
    brs: bool = False
    rtr: bool = False
    echo: bool = False
    confirm: bool = False
    modify: Optional[ModifyFn] = None

    _task: Optional[asyncio.Task] = None
    _stop: asyncio.Event = asyncio.Event()

    def start(self, dev: CarBusDevice) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(dev), name=f"PeriodicJob:{self.name}")

        def _done(t: asyncio.Task):
            exc = t.exception()
            if exc:
                print(f"[PeriodicJob:{self.name}] crashed:", repr(exc))

        self._task.add_done_callback(_done)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with asyncio.CancelledError.__suppress_context__ if False else None:
                pass
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self, dev: CarBusDevice) -> None:
        tick = 0
        next_t = time.perf_counter()

        while not self._stop.is_set():
            now = time.perf_counter()
            if now < next_t:
                await asyncio.sleep(next_t - now)
            next_t += self.period_s

            out = self.data
            if self.modify is not None:
                res = self.modify(tick, out)
                out = await res if asyncio.iscoroutine(res) else res

            msg = CanMessage(
                can_id=self.can_id,
                data=out,
            )
            await dev.send_can(
                msg,
                channel=self.channel,
                confirm=self.confirm,
                echo=self.echo,
            )
            tick += 1


class PeriodicCanSender:
    def __init__(self, dev: CarBusDevice):
        self._dev = dev
        self._jobs: dict[str, PeriodicJob] = {}

    def add(
        self,
        name: str,
        *,
        channel: int,
        can_id: int,
        data: bytes,
        period_s: float,
        modify: Optional[ModifyFn] = None,
        extended: bool = False,
        fd: bool = False,
        brs: bool = False,
        rtr: bool = False,
        echo: bool = False,
        confirm: bool = False,
        autostart: bool = True,
    ) -> PeriodicJob:
        if name in self._jobs:
            raise ValueError(f"Periodic job '{name}' already exists")

        job = PeriodicJob(
            name=name,
            can_id=can_id,
            data=data,
            period_s=period_s,
            channel=channel,
            extended=extended,
            fd=fd,
            brs=brs,
            rtr=rtr,
            echo=echo,
            confirm=confirm,
            modify=modify,
        )
        self._jobs[name] = job
        if autostart:
            job.start(self._dev)
        return job

    def get(self, name: str) -> PeriodicJob:
        return self._jobs[name]

    async def remove(self, name: str) -> None:
        job = self._jobs.pop(name, None)
        if job is not None:
            await job.stop()

    async def stop_all(self) -> None:
        await asyncio.gather(*(job.stop() for job in self._jobs.values()), return_exceptions=True)
        self._jobs.clear()
