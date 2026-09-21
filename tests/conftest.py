"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

VIDEO_FPS = 30.0
VIDEO_SECONDS = 3
VIDEO_SIZE = (64, 48)  # width, height


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """A short synthetic video, each frame tinted by its index."""
    path = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        VIDEO_FPS,
        VIDEO_SIZE,
    )
    if not writer.isOpened():  # pragma: no cover - depends on local codecs
        pytest.skip("no MJPG encoder available in this OpenCV build")

    total = int(VIDEO_FPS * VIDEO_SECONDS)
    for index in range(total):
        frame = np.full((VIDEO_SIZE[1], VIDEO_SIZE[0], 3), index % 256, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    return path
