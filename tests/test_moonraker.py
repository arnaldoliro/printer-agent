"""MoonrakerClient against a fake printer."""

from __future__ import annotations

import asyncio

import pytest

from agent.printer import MoonrakerClient, PrinterError, PrinterState, websocket_url


def client_for(printer, **kwargs) -> MoonrakerClient:
    return MoonrakerClient(url=printer.url, transport=printer.transport(), **kwargs)


def test_websocket_url_is_derived_from_the_http_address() -> None:
    assert websocket_url("http://192.168.0.42:7125") == "ws://192.168.0.42:7125/websocket"
    assert websocket_url("https://printer.local") == "wss://printer.local/websocket"
    assert websocket_url("http://host:7125/") == "ws://host:7125/websocket"


async def test_info_reports_the_printer(fake_printer) -> None:
    async with client_for(fake_printer) as client:
        assert (await client.info())["hostname"] == "fake-printer"


async def test_status_reads_state_and_progress(fake_printer) -> None:
    fake_printer.status = {
        "print_stats": {"state": "printing", "filename": "suporte.gcode"},
        "virtual_sdcard": {"progress": 0.42},
    }
    async with client_for(fake_printer) as client:
        state = await client.status()

    assert state.state is PrinterState.PRINTING
    assert state.filename == "suporte.gcode"
    assert state.progress == pytest.approx(0.42)


async def test_unknown_states_do_not_crash(fake_printer) -> None:
    fake_printer.status = {"print_stats": {"state": "something-new"}}
    async with client_for(fake_printer) as client:
        assert (await client.status()).state is PrinterState.UNKNOWN


async def test_file_metadata_is_returned(fake_printer) -> None:
    async with client_for(fake_printer) as client:
        metadata = await client.file_metadata("suporte.gcode")

    assert metadata["layer_count"] == 180
    assert metadata["estimated_time"] == 7200


async def test_observer_mode_refuses_to_touch_the_print(fake_printer) -> None:
    """The safety property the whole design rests on."""
    async with client_for(fake_printer, read_only=True) as client:
        assert await client.pause() is False
        assert await client.cancel() is False
        assert await client.resume() is False

    assert fake_printer.commands == []


async def test_active_mode_sends_commands(fake_printer) -> None:
    async with client_for(fake_printer, read_only=False) as client:
        assert await client.pause() is True
        assert await client.cancel() is True

    assert fake_printer.commands == ["pause", "cancel"]


async def test_using_the_client_unopened_is_an_error(fake_printer) -> None:
    with pytest.raises(PrinterError, match="not open"):
        await MoonrakerClient(url=fake_printer.url).info()


async def test_events_yield_the_initial_state_then_changes(fake_printer) -> None:
    async with client_for(fake_printer) as client:
        events = client.events()

        first = await asyncio.wait_for(events.__anext__(), timeout=5)
        assert first.state is PrinterState.STANDBY

        await fake_printer.wait_for_client()
        await fake_printer.push({"print_stats": {"state": "printing", "filename": "peca.gcode"}})

        second = await asyncio.wait_for(events.__anext__(), timeout=5)
        assert second.state is PrinterState.PRINTING
        assert second.filename == "peca.gcode"

        await events.aclose()


async def test_partial_updates_are_merged_into_the_running_status(fake_printer) -> None:
    """Moonraker sends only what changed, so fields must not be lost."""
    fake_printer.status = {
        "print_stats": {"state": "printing", "filename": "peca.gcode"},
        "virtual_sdcard": {"progress": 0.1},
    }

    async with client_for(fake_printer) as client:
        events = client.events()
        await asyncio.wait_for(events.__anext__(), timeout=5)

        await fake_printer.wait_for_client()
        # Progress moves; the filename is not repeated.
        await fake_printer.push({"virtual_sdcard": {"progress": 0.5}})

        state = await asyncio.wait_for(events.__anext__(), timeout=5)
        await events.aclose()

    assert state.progress == pytest.approx(0.5)
    assert state.filename == "peca.gcode"
