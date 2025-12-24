from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass, field
from typing import Dict, Optional

log = logging.getLogger("carbus_remote.server")


@dataclass
class AgentControl:
    serial: str
    password: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter


@dataclass
class PendingSession:
    serial: str
    client_reader: asyncio.StreamReader
    client_writer: asyncio.StreamWriter
    ready: asyncio.Event = field(default_factory=asyncio.Event)  # agent_data подключился
    done: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())  # pipe завершён


class RelayServer:
    def __init__(self) -> None:
        self._agents: Dict[str, AgentControl] = {}
        self._pending: Dict[str, PendingSession] = {}
        self._lock = asyncio.Lock()

    async def handle_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            if not line:
                return

            try:
                hello = json.loads(line.decode("utf-8", errors="ignore").strip())
            except Exception:
                await self._send_json(writer, {"ok": False, "error": "bad_handshake"})
                return

            role = hello.get("role")

            if role == "agent":
                await self._handle_agent_control(reader, writer, hello, peer)
                return

            if role == "client":
                await self._handle_client(reader, writer, hello, peer)
                return

            if role == "agent_data":
                await self._handle_agent_data(reader, writer, hello, peer)
                return

            await self._send_json(writer, {"ok": False, "error": "bad_role"})

        except asyncio.TimeoutError:
            await self._send_json(writer, {"ok": False, "error": "handshake_timeout"})
        except Exception:
            log.exception("Connection error from %s", peer)
        finally:
            if getattr(writer, "_carbus_piped", False):
                return
            if not writer.is_closing():
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    async def _handle_agent_control(self, reader, writer, hello, peer) -> None:
        serial = str(hello.get("serial", "")).strip()
        password = str(hello.get("password", "")).strip()
        if not serial or not password:
            await self._send_json(writer, {"ok": False, "error": "bad_handshake"})
            return

        async with self._lock:
            old = self._agents.get(serial)
            if old:
                try:
                    old.writer.close()
                except Exception:
                    pass
            self._agents[serial] = AgentControl(serial, password, reader, writer)

        await self._send_json(writer, {"ok": True})
        log.info("Agent online serial=%s from %s", serial, peer)

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
        finally:
            async with self._lock:
                cur = self._agents.get(serial)
                if cur and cur.writer is writer:
                    self._agents.pop(serial, None)
            log.info("Agent offline serial=%s", serial)

    async def _handle_client(self, reader, writer, hello, peer) -> None:
        serial = str(hello.get("serial", "")).strip()
        password = str(hello.get("password", "")).strip()
        if not serial or not password:
            await self._send_json(writer, {"ok": False, "error": "bad_handshake"})
            return

        async with self._lock:
            agent = self._agents.get(serial)
            if agent is None:
                await self._send_json(writer, {"ok": False, "error": "agent_offline"})
                return
            if agent.password != password:
                await self._send_json(writer, {"ok": False, "error": "unauthorized"})
                return

            session = secrets.token_hex(8)
            ps = PendingSession(serial=serial, client_reader=reader, client_writer=writer)
            self._pending[session] = ps

            try:
                agent.writer.write((json.dumps({"cmd": "open_session", "session": session}) + "\n").encode("utf-8"))
                await agent.writer.drain()
            except Exception:
                self._pending.pop(session, None)
                await self._send_json(writer, {"ok": False, "error": "agent_write_failed"})
                return

        await self._send_json(writer, {"ok": True, "session": session})
        log.info("Client accepted serial=%s session=%s from %s", serial, session, peer)

        try:
            await asyncio.wait_for(ps.ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            async with self._lock:
                self._pending.pop(session, None)
            await self._send_json(writer, {"ok": False, "error": "agent_data_timeout"})
            return

        try:
            await ps.done
        finally:
            async with self._lock:
                self._pending.pop(session, None)

    async def _handle_agent_data(self, reader, writer, hello, peer) -> None:
        session = str(hello.get("session", "")).strip()
        if not session:
            await self._send_json(writer, {"ok": False, "error": "bad_handshake"})
            return

        async with self._lock:
            ps = self._pending.get(session)

        if ps is None:
            await self._send_json(writer, {"ok": False, "error": "unknown_session"})
            return

        await self._send_json(writer, {"ok": True})
        log.info("Agent data connected session=%s from %s (pairing)", session, peer)

        setattr(ps.client_writer, "_carbus_piped", True)
        setattr(writer, "_carbus_piped", True)

        ps.ready.set()

        try:
            await self._pipe(ps.client_reader, ps.client_writer, reader, writer)
        finally:
            if not ps.done.done():
                ps.done.set_result(None)

    async def _pipe(self, a_reader, a_writer, b_reader, b_writer, bufsize: int = 4096) -> None:
        async def pump(src, dst):
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

        t1 = asyncio.create_task(pump(a_reader, b_writer))
        t2 = asyncio.create_task(pump(b_reader, a_writer))
        await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)

        for t in (t1, t2):
            t.cancel()
            try:
                await t
            except Exception:
                pass

        for w in (a_writer, b_writer):
            try:
                w.close()
            except Exception:
                pass
        for w in (a_writer, b_writer):
            try:
                await w.wait_closed()
            except Exception:
                pass

    @staticmethod
    async def _send_json(writer, obj: dict) -> None:
        writer.write((json.dumps(obj) + "\n").encode("utf-8"))
        await writer.drain()


async def main(host: str = "0.0.0.0", port: int = 9000) -> None:
    rs = RelayServer()
    srv = await asyncio.start_server(rs.handle_conn, host, port)
    log.info("Relay server listening on %s", ", ".join(str(s.getsockname()) for s in srv.sockets or []))
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(main())
