"""The video source contract.

Everything downstream — recording today, detection later — consumes frames
through this interface, so the same code runs against a USB webcam, a network
camera, or a recorded file.

Pacing lives inside the source on purpose. A live source has to wait for wall
clock time to pass between frames; a recorded file must NOT, or replaying a
40 hour print would take 40 hours. Both honour the same capture interval, and
the caller never has to know which kind it is holding.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType

import numpy as np


@dataclass(frozen=True)
class Frame:
    """A single captured image.

    `captured_at` is wall clock time for live sources and the frame's position
    in the original recording for file sources, so job timings stay meaningful
    in both cases.
    """

    image: np.ndarray
    captured_at: datetime


class VideoSourceError(RuntimeError):
    """Raised when a source cannot be opened or fails while reading."""


class VideoSource(ABC):
    """Yields frames at the configured interval until the source is exhausted."""

    def __init__(self, interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        self.interval_seconds = interval_seconds

    @abstractmethod
    def open(self) -> None:
        """Acquire the underlying device or file."""

    @abstractmethod
    def read(self) -> Frame | None:
        """Return the next frame, or None once the source is exhausted.

        Live sources block until the next frame is due. File sources return
        immediately, skipping ahead within the recording.
        """

    @abstractmethod
    def close(self) -> None:
        """Release the underlying device or file."""

    @abstractmethod
    def describe(self) -> str:
        """Short description stored in the job metadata."""

    def __enter__(self) -> VideoSource:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
