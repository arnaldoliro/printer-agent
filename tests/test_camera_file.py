"""FileSource: the offline development path."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.camera import FileSource, VideoSourceError, create_source
from agent.config import CameraConfig


async def drain(source) -> list:
    """Read a source to exhaustion."""
    frames = []
    async with source:
        while (frame := await source.read()) is not None:
            frames.append(frame)
    return frames


async def test_reads_one_frame_per_interval(sample_video: Path) -> None:
    """A 3 second clip at a 1 second interval yields 3 frames."""
    assert len(await drain(FileSource(sample_video, interval_seconds=1.0))) == 3


async def test_a_shorter_interval_yields_more_frames(sample_video: Path) -> None:
    assert len(await drain(FileSource(sample_video, interval_seconds=0.5))) == 6


async def test_replay_does_not_wait_for_wall_clock_time(sample_video: Path) -> None:
    """The whole point: a long recording must replay in a moment, not in hours."""
    import time

    started = time.monotonic()
    await drain(FileSource(sample_video, interval_seconds=1.0))

    assert time.monotonic() - started < 1.0


async def test_timestamps_follow_the_recording_timeline(sample_video: Path) -> None:
    frames = await drain(FileSource(sample_video, interval_seconds=1.0))

    gap = (frames[1].captured_at - frames[0].captured_at).total_seconds()
    assert gap == pytest.approx(1.0, abs=0.05)


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(VideoSourceError, match="video file not found"):
        FileSource(tmp_path / "absent.avi", interval_seconds=1.0).open()


async def test_reading_before_open_is_an_error(sample_video: Path) -> None:
    with pytest.raises(VideoSourceError, match="not open"):
        await FileSource(sample_video, interval_seconds=1.0).read()


def test_factory_builds_each_kind(sample_video: Path) -> None:
    from agent.camera import NetworkSource, WebcamSource

    assert isinstance(create_source(CameraConfig(source="webcam")), WebcamSource)
    assert isinstance(create_source(CameraConfig(source="network", url="rtsp://x")), NetworkSource)
    assert isinstance(create_source(CameraConfig(source="file", path=sample_video)), FileSource)
