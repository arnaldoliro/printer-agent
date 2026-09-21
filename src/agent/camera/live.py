"""Live sources: local USB webcams and network (RTSP/MJPEG) cameras.

Both wrap an OpenCV capture and differ only in what they open, so the pacing
and buffer-flushing logic is shared here.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import cv2

from agent.camera.base import Frame, VideoSource, VideoSourceError

logger = logging.getLogger(__name__)

#: Frames discarded before each capture. Cameras keep a few frames buffered,
#: and with a ten second interval whatever sits in that buffer is stale by the
#: time we ask for it. Draining first is what keeps the stored frame current.
_FLUSH_FRAMES = 4


class LiveSource(VideoSource):
    """Base for sources backed by a live OpenCV capture."""

    def __init__(self, interval_seconds: float) -> None:
        super().__init__(interval_seconds)
        self._capture: cv2.VideoCapture | None = None
        self._next_capture_at: float | None = None

    def _open_capture(self) -> cv2.VideoCapture:
        raise NotImplementedError

    def open(self) -> None:
        capture = self._open_capture()
        if not capture.isOpened():
            capture.release()
            raise VideoSourceError(f"could not open {self.describe()}")

        # Ask the driver to keep the shallowest buffer it supports. Not every
        # backend honours this, which is why we also flush before capturing.
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._capture = capture
        self._next_capture_at = None
        logger.info("opened %s", self.describe())

    def seconds_until_next(self) -> float:
        """Time left in the current interval; the first frame is immediate."""
        now = time.monotonic()
        if self._next_capture_at is None:
            self._next_capture_at = now
            return 0.0

        remaining = self._next_capture_at - now
        if remaining <= 0:
            # Capturing fell behind (slow disk, busy CPU). Resync to now rather
            # than trying to catch up with a burst of frames.
            self._next_capture_at = now
            return 0.0
        return remaining

    def capture(self) -> Frame | None:
        if self._capture is None:
            raise VideoSourceError("source is not open")

        if self._next_capture_at is not None:
            self._next_capture_at += self.interval_seconds

        for _ in range(_FLUSH_FRAMES):
            self._capture.grab()

        ok, image = self._capture.read()
        if not ok or image is None:
            logger.warning("failed to read a frame from %s", self.describe())
            return None

        return Frame(image=image, captured_at=datetime.now().astimezone())

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class WebcamSource(LiveSource):
    """A USB camera attached to the machine running the agent."""

    def __init__(self, device: int, interval_seconds: float) -> None:
        super().__init__(interval_seconds)
        self.device = device

    def _open_capture(self) -> cv2.VideoCapture:
        return cv2.VideoCapture(self.device)

    def describe(self) -> str:
        return f"webcam:{self.device}"


class NetworkSource(LiveSource):
    """An IP camera, or a phone running an IP-camera app, over RTSP or MJPEG."""

    def __init__(self, url: str, interval_seconds: float) -> None:
        super().__init__(interval_seconds)
        self.url = url

    def _open_capture(self) -> cv2.VideoCapture:
        return cv2.VideoCapture(self.url)

    def describe(self) -> str:
        return f"network:{self.url}"
