"""Moonraker client: HTTP for commands, websocket for events.

Moonraker is the API server that sits in front of Klipper. Everything here goes
over the local network exactly as Fluidd and Mainsail do, so the agent never
needs root on the printer and never modifies its firmware.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets

from agent.printer.base import PrinterClient, PrinterError, PrinterState, PrintState

logger = logging.getLogger(__name__)

#: Printer objects we care about. `print_stats` carries the state and filename,
#: `virtual_sdcard` the progress through the file.
SUBSCRIBED_OBJECTS = {"print_stats": None, "virtual_sdcard": None}

#: Reconnection backoff. The agent runs unattended for days, so a dropped
#: websocket has to heal on its own rather than end the session.
_RECONNECT_MIN_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0


def websocket_url(base_url: str) -> str:
    """Turn `http://host:7125` into `ws://host:7125/websocket`."""
    parts = urlsplit(base_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, "/websocket", "", ""))


class MoonrakerClient(PrinterClient):
    def __init__(
        self,
        url: str,
        api_key: str | None = None,
        read_only: bool = True,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.read_only = read_only
        self.timeout = timeout
        #: Injected by the tests so the HTTP side can be exercised without a printer.
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        #: Merged view of the subscribed objects. Moonraker pushes only the
        #: fields that changed, so updates have to be folded into a running copy.
        self._status: dict[str, dict[str, Any]] = {}

    # -- lifecycle ---------------------------------------------------------

    async def __aenter__(self) -> MoonrakerClient:
        headers = {"X-Api-Key": self.api_key} if self.api_key else {}
        self._client = httpx.AsyncClient(
            base_url=self.url,
            timeout=self.timeout,
            headers=headers,
            transport=self._transport,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise PrinterError("client is not open; use `async with MoonrakerClient(...)`")
        return self._client

    # -- reads -------------------------------------------------------------

    async def info(self) -> dict:
        """Printer identification, and the cheapest way to check reachability."""
        return await self._get("/printer/info")

    async def status(self) -> PrintState:
        payload = await self._get(
            "/printer/objects/query",
            params={"print_stats": "", "virtual_sdcard": ""},
        )
        self._merge(payload.get("status", {}))
        return self._current_state()

    async def file_metadata(self, filename: str) -> dict:
        """Slicer metadata: estimated time, filament used, layers, thumbnails."""
        return await self._get("/server/files/metadata", params={"filename": filename})

    async def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            response = await self._http.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PrinterError(f"{path} failed: {exc}") from exc

        body = response.json()
        if "error" in body:
            raise PrinterError(f"{path} returned an error: {body['error']}")
        return body.get("result", {})

    # -- commands ----------------------------------------------------------

    async def pause(self) -> bool:
        return await self._command("/printer/print/pause", "pause")

    async def cancel(self) -> bool:
        return await self._command("/printer/print/cancel", "cancel")

    async def resume(self) -> bool:
        return await self._command("/printer/print/resume", "resume")

    async def _command(self, path: str, name: str) -> bool:
        if self.read_only:
            # Observer mode. Until a detector has earned its keep, the agent
            # says what it would have done and touches nothing.
            logger.warning("observer mode: would have sent %s, but the agent is read-only", name)
            return False

        try:
            response = await self._http.post(path)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PrinterError(f"{name} failed: {exc}") from exc

        logger.info("sent %s to the printer", name)
        return True

    # -- events ------------------------------------------------------------

    async def events(self) -> AsyncIterator[PrintState]:
        """Yield a state every time the printer reports a change.

        Reconnects on its own: an agent watching an overnight print cannot end
        its session because the network blinked.
        """
        backoff = _RECONNECT_MIN_SECONDS
        url = websocket_url(self.url)

        while True:
            try:
                async with websockets.connect(url) as socket:
                    backoff = _RECONNECT_MIN_SECONDS
                    logger.info("subscribed to %s", url)

                    initial = await self._subscribe(socket)
                    self._merge(initial)
                    yield self._current_state()

                    async for message in socket:
                        update = self._parse_notification(message)
                        if update is None:
                            continue
                        self._merge(update)
                        yield self._current_state()

            except (OSError, websockets.WebSocketException) as exc:
                logger.warning("websocket lost (%s); reconnecting in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)

    async def _subscribe(self, socket: Any) -> dict[str, dict[str, Any]]:
        """Subscribe and return the full status Moonraker replies with."""
        request = {
            "jsonrpc": "2.0",
            "method": "printer.objects.subscribe",
            "params": {"objects": SUBSCRIBED_OBJECTS},
            "id": 1,
        }
        await socket.send(json.dumps(request))

        # The reply may arrive behind unrelated notifications.
        while True:
            body = json.loads(await socket.recv())
            if body.get("id") == 1:
                if "error" in body:
                    raise PrinterError(f"subscription rejected: {body['error']}")
                return body.get("result", {}).get("status", {})

    @staticmethod
    def _parse_notification(message: str | bytes) -> dict[str, dict[str, Any]] | None:
        """Extract the payload of a `notify_status_update`, ignoring the rest."""
        try:
            body = json.loads(message)
        except json.JSONDecodeError:
            logger.debug("ignoring non-JSON websocket message")
            return None

        if body.get("method") != "notify_status_update":
            return None

        params = body.get("params") or []
        return params[0] if params and isinstance(params[0], dict) else None

    # -- state -------------------------------------------------------------

    def _merge(self, update: dict[str, dict[str, Any]]) -> None:
        """Fold a partial update into the running status."""
        for name, fields in update.items():
            if isinstance(fields, dict):
                self._status.setdefault(name, {}).update(fields)

    def _current_state(self) -> PrintState:
        stats = self._status.get("print_stats", {})
        sdcard = self._status.get("virtual_sdcard", {})

        return PrintState(
            state=PrinterState.parse(stats.get("state")),
            filename=stats.get("filename") or None,
            progress=float(sdcard.get("progress") or 0.0),
            print_duration=float(stats.get("print_duration") or 0.0),
            total_duration=float(stats.get("total_duration") or 0.0),
            message=stats.get("message") or "",
        )
