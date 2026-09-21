"""A stand-in for Moonraker.

The printer belongs to someone else and is not on this network, so the whole
print lifecycle — start, progress, finish — is exercised against this instead.
It speaks the parts of the protocol the agent actually uses: JSON-RPC over a
websocket for events, plain HTTP for queries and commands.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import websockets

PRINTER_INFO = {"hostname": "fake-printer", "state": "ready"}

GCODE_METADATA = {
    "filename": "suporte.gcode",
    "estimated_time": 7200,
    "layer_count": 180,
    "filament_total": 4210.5,
    "thumbnails": [{"width": 300, "height": 300, "data": "ignored"}],
}


def idle_status(filename: str = "") -> dict[str, dict[str, Any]]:
    return {
        "print_stats": {"state": "standby", "filename": filename, "print_duration": 0.0},
        "virtual_sdcard": {"progress": 0.0},
    }


class FakeMoonraker:
    """Serves the websocket side and records the commands it receives."""

    def __init__(self, status: dict[str, dict[str, Any]] | None = None) -> None:
        self.status = status or idle_status()
        self.commands: list[str] = []
        self._server: Any = None
        self._clients: set[Any] = set()

    async def start(self) -> int:
        """Listen on a free port and return it."""
        self._server = await websockets.serve(self._handle, "127.0.0.1", 0)
        return self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, socket: Any) -> None:
        self._clients.add(socket)
        try:
            async for raw in socket:
                request = json.loads(raw)
                if request.get("method") == "printer.objects.subscribe":
                    await socket.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": request.get("id"),
                                "result": {"status": self.status, "eventtime": 1.0},
                            }
                        )
                    )
        except websockets.WebSocketException:  # pragma: no cover - client went away
            pass
        finally:
            self._clients.discard(socket)

    async def push(self, update: dict[str, dict[str, Any]]) -> None:
        """Send a partial status update, the way Moonraker reports changes."""
        for name, fields in update.items():
            self.status.setdefault(name, {}).update(fields)

        message = json.dumps(
            {"jsonrpc": "2.0", "method": "notify_status_update", "params": [update, 1.0]}
        )
        for socket in list(self._clients):
            await socket.send(message)

    async def wait_for_client(self) -> None:
        """Block until a subscriber is connected."""
        import asyncio

        while not self._clients:
            await asyncio.sleep(0.01)

    # -- HTTP --------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        """An httpx transport answering the endpoints the agent calls."""

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path

            if path == "/printer/info":
                return httpx.Response(200, json={"result": PRINTER_INFO})
            if path == "/printer/objects/query":
                return httpx.Response(200, json={"result": {"status": self.status}})
            if path == "/server/files/metadata":
                return httpx.Response(200, json={"result": dict(GCODE_METADATA)})
            if path.startswith("/printer/print/"):
                self.commands.append(path.rsplit("/", 1)[-1])
                return httpx.Response(200, json={"result": "ok"})

            return httpx.Response(404, json={"error": {"message": f"no route for {path}"}})

        return httpx.MockTransport(handler)
