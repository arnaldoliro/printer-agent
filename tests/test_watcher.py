"""PrintWatcher: the printer drives the recorder, and labels the result."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

import pytest

from agent.config import AgentConfig, CameraConfig, StorageConfig
from agent.printer import MoonrakerClient
from agent.watcher import PrintWatcher, job_name_for


def config_for(sample_video: Path, tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        camera=CameraConfig(source="file", path=sample_video, capture_interval_seconds=1.0),
        storage=StorageConfig(path=tmp_path / "dados"),
    )


async def wait_until(predicate, timeout: float = 5.0) -> None:
    """Poll until `predicate` holds, instead of guessing at a sleep."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition was never met")
        await asyncio.sleep(0.01)


async def run_through(fake_printer, config: AgentConfig, transitions: list[dict]) -> list[Path]:
    """Drive the watcher through a sequence of printer updates."""
    jobs_dir = config.storage.path

    async with MoonrakerClient(url=fake_printer.url, transport=fake_printer.transport()) as client:
        watcher = PrintWatcher(client=client, config=config)
        task = asyncio.create_task(watcher.run())
        await fake_printer.wait_for_client()

        for update in transitions:
            seen = watcher._previous
            await fake_printer.push(update)
            await wait_until(lambda seen=seen: watcher._previous != seen)

        # Give the closing work a chance to finish before tearing down.
        await wait_until(lambda: watcher._task is None)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    return sorted(jobs_dir.iterdir()) if jobs_dir.exists() else []


def read_job(job_dir: Path) -> dict:
    return json.loads((job_dir / "job.json").read_text())


def test_job_name_comes_from_the_printed_file() -> None:
    assert job_name_for("suporte-monitor.gcode") == "suporte-monitor"
    assert job_name_for("pasta/peca.gcode") == "peca"
    assert job_name_for(None) == "print"
    assert job_name_for("") == "print"


async def test_a_print_starting_starts_a_recording(fake_printer, sample_video, tmp_path) -> None:
    config = config_for(sample_video, tmp_path)
    jobs = await run_through(
        fake_printer,
        config,
        [
            {"print_stats": {"state": "printing", "filename": "suporte.gcode"}},
            {"print_stats": {"state": "complete"}},
        ],
    )

    assert len(jobs) == 1
    assert jobs[0].name.endswith("_suporte")
    assert list((jobs[0] / "frames").glob("*.jpg"))


@pytest.mark.parametrize(
    ("final_state", "expected"),
    [
        ("complete", "success"),
        ("error", "failure"),
        # A human pressing cancel may have seen a failure or simply changed
        # their mind. Guessing would poison the dataset.
        ("cancelled", "unknown"),
    ],
)
async def test_the_printer_labels_the_recording(
    fake_printer, sample_video, tmp_path, final_state: str, expected: str
) -> None:
    config = config_for(sample_video, tmp_path)
    jobs = await run_through(
        fake_printer,
        config,
        [
            {"print_stats": {"state": "printing", "filename": "peca.gcode"}},
            {"print_stats": {"state": final_state}},
        ],
    )

    job = read_job(jobs[0])
    assert job["result"] == expected
    assert job["notes"]["printer_outcome"] == final_state


async def test_gcode_metadata_is_stored_with_the_frames(
    fake_printer, sample_video, tmp_path
) -> None:
    config = config_for(sample_video, tmp_path)
    jobs = await run_through(
        fake_printer,
        config,
        [
            {"print_stats": {"state": "printing", "filename": "suporte.gcode"}},
            {"print_stats": {"state": "complete"}},
        ],
    )

    gcode = read_job(jobs[0])["gcode"]
    assert gcode["layer_count"] == 180
    assert gcode["estimated_time"] == 7200
    # Thumbnails are large and already on the printer.
    assert "thumbnails" not in gcode


async def test_idle_transitions_do_not_record(fake_printer, sample_video, tmp_path) -> None:
    config = config_for(sample_video, tmp_path)
    jobs = await run_through(
        fake_printer,
        config,
        [{"print_stats": {"state": "paused"}}, {"print_stats": {"state": "standby"}}],
    )

    assert jobs == []


async def test_pausing_mid_print_keeps_the_same_recording(
    fake_printer, sample_video, tmp_path
) -> None:
    """A pause is part of the print, not the end of it."""
    config = config_for(sample_video, tmp_path)
    jobs = await run_through(
        fake_printer,
        config,
        [
            {"print_stats": {"state": "printing", "filename": "peca.gcode"}},
            {"print_stats": {"state": "paused"}},
            {"print_stats": {"state": "printing"}},
            {"print_stats": {"state": "complete"}},
        ],
    )

    assert len(jobs) == 1
