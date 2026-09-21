"""Recorded video file as a frame source.

This is the source that makes the project workable. Detection tuning against a
real printer means one experiment per print; against recorded video it means
one experiment per second, repeatable and identical every run.

Unlike live sources, this one never sleeps: the capture interval is applied by
skipping ahead inside the recording, so a night-long timelapse replays in
seconds.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import cv2

from agent.camera.base import Frame, VideoSource, VideoSourceError

logger = logging.getLogger(__name__)

#: Used when the container does not report a usable frame rate.
_FALLBACK_FPS = 30.0


class FileSource(VideoSource):
    """Replays a video file, yielding one frame per capture interval."""

    def __init__(self, path: Path, interval_seconds: float) -> None:
        super().__init__(interval_seconds)
        self.path = Path(path)
        self._capture: cv2.VideoCapture | None = None
        self._step = 1
        self._position = 0
        self._fps = _FALLBACK_FPS
        #: Timestamps are anchored here and advance with the video's own
        #: timeline, so a replayed job keeps the pacing of the original.
        self._anchor = datetime.now().astimezone()

    def open(self) -> None:
        if not self.path.is_file():
            raise VideoSourceError(f"video file not found: {self.path}")

        capture = cv2.VideoCapture(str(self.path))
        if not capture.isOpened():
            capture.release()
            raise VideoSourceError(f"could not open video file: {self.path}")

        fps = capture.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0 or fps != fps:  # also rejects NaN
            logger.warning("%s reports no usable frame rate, assuming %s", self.path, _FALLBACK_FPS)
            fps = _FALLBACK_FPS

        self._capture = capture
        self._fps = fps
        self._step = max(1, round(fps * self.interval_seconds))
        self._position = 0
        self._anchor = datetime.now().astimezone()
        logger.info(
            "opened %s (%.2f fps, keeping 1 in %d frames)", self.describe(), fps, self._step
        )

    def read(self) -> Frame | None:
        if self._capture is None:
            raise VideoSourceError("source is not open")

        # The first call returns frame 0; later calls skip a whole interval.
        if self._position:
            for _ in range(self._step - 1):
                if not self._capture.grab():
                    return None
                self._position += 1

        ok, image = self._capture.read()
        if not ok or image is None:
            return None

        captured_at = self._anchor + timedelta(seconds=self._position / self._fps)
        self._position += 1
        return Frame(image=image, captured_at=captured_at)

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def describe(self) -> str:
        return f"file:{self.path}"
