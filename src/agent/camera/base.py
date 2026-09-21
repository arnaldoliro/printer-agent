"""The video source contract.

Everything downstream — recording today, detection later — consumes frames
through this interface, so the same code runs against a USB webcam, a network
camera, or a recorded file.

Two rules shape this design:

* **Pacing belongs to the source.** A live source has to wait for wall clock
  time to pass between frames; a recorded file must NOT, or replaying a 40 hour
  print would take 40 hours. Both honour the same capture interval and the
  caller never has to know which kind it is holding.
* **Blocking work runs in a thread.** OpenCV is synchronous, and a blocking
  call inside the event loop would stall the Moonraker websocket. Subclasses
  implement plain blocking methods; this class moves them off the loop.
"""

from __future__ import annotations

import asyncio
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

    # -- to implement ------------------------------------------------------

    @abstractmethod
    def open(self) -> None:
        """Acquire the underlying device or file. May block."""

    @abstractmethod
    def close(self) -> None:
        """Release the underlying device or file."""

    @abstractmethod
    def describe(self) -> str:
        """Short description stored in the job metadata."""

    @abstractmethod
    def capture(self) -> Frame | None:
        """Grab one frame, or None once the source is exhausted. May block."""

    @abstractmethod
    def seconds_until_next(self) -> float:
        """How long to wait before the next capture is due.

        Live sources return the time left in the interval; file sources return
        zero, because their interval is applied by skipping frames instead.
        """

    # -- used by callers ---------------------------------------------------

    async def read(self) -> Frame | None:
        """Wait until the next frame is due, then capture it off the loop."""
        delay = self.seconds_until_next()
        if delay > 0:
            await asyncio.sleep(delay)
        return await asyncio.to_thread(self.capture)

    async def __aenter__(self) -> VideoSource:
        await asyncio.to_thread(self.open)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await asyncio.to_thread(self.close)
