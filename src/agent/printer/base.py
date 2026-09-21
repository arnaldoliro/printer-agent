"""The printer contract.

Only Moonraker is implemented. The interface exists so that adding OctoPrint or
PrusaLink later does not ripple through the recorder and the watcher — not as
speculative support for printers nobody has asked for yet.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum


class PrinterState(str, Enum):
    """States reported by Klipper's `print_stats.state`."""

    STANDBY = "standby"
    PRINTING = "printing"
    PAUSED = "paused"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    ERROR = "error"
    #: Reported by us, not by the printer: we have not reached it yet.
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: str | None) -> PrinterState:
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN

    @property
    def is_active(self) -> bool:
        """True while a job is on the bed, paused included."""
        return self in (PrinterState.PRINTING, PrinterState.PAUSED)

    @property
    def is_finished(self) -> bool:
        """True once a job has ended, however it ended."""
        return self in (PrinterState.COMPLETE, PrinterState.CANCELLED, PrinterState.ERROR)


@dataclass(frozen=True)
class PrintState:
    """A snapshot of what the printer is doing."""

    state: PrinterState = PrinterState.UNKNOWN
    filename: str | None = None
    #: Fraction of the file processed, 0.0 to 1.0.
    progress: float = 0.0
    print_duration: float = 0.0
    total_duration: float = 0.0
    message: str = ""


class PrinterError(RuntimeError):
    """Raised when the printer cannot be reached or rejects a command."""


class PrinterClient(ABC):
    """Reads printer status and, when allowed to, controls the print."""

    #: When True the client refuses every command that changes the print.
    read_only: bool = True

    @abstractmethod
    async def status(self) -> PrintState:
        """Return the current state in a single request."""

    @abstractmethod
    async def events(self) -> AsyncIterator[PrintState]:
        """Yield a new state every time the printer reports a change."""

    @abstractmethod
    async def pause(self) -> bool:
        """Pause the running print. Returns False when not allowed."""

    @abstractmethod
    async def cancel(self) -> bool:
        """Cancel the running print. Returns False when not allowed."""

    @abstractmethod
    async def resume(self) -> bool:
        """Resume a paused print. Returns False when not allowed."""

    @abstractmethod
    async def file_metadata(self, filename: str) -> dict:
        """Slicer metadata for a G-code file: estimated time, layers, thumbnails."""
