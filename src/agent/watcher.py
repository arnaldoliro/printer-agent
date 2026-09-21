"""Lets the printer drive the recorder.

Manual recording only captures the prints someone remembered to record. The
watcher removes that dependency: it follows the printer's own state and starts
and stops recording on its own.

It also labels the data. The printer reports how each job ended, so the
recordings arrive already sorted into successes and failures without anyone
having to remember what happened overnight.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from agent.camera import create_source
from agent.config import AgentConfig
from agent.printer.base import PrinterClient, PrinterError, PrinterState, PrintState
from agent.recorder import JobResult, Recorder

logger = logging.getLogger(__name__)

#: How the printer's final state maps to a label on the recording.
#:
#: "cancelled" deliberately stays unknown. A human pressing cancel may have
#: spotted a failure, or may simply have changed their mind — guessing would
#: poison the dataset that every later model is trained on. The raw printer
#: outcome is kept in the notes so it can be labelled by hand.
_RESULT_BY_STATE: dict[PrinterState, JobResult] = {
    PrinterState.COMPLETE: "success",
    PrinterState.ERROR: "failure",
    PrinterState.CANCELLED: "unknown",
}


def job_name_for(filename: str | None) -> str:
    """Name a recording after the file being printed."""
    if not filename:
        return "print"
    return Path(filename).stem or "print"


class PrintWatcher:
    """Starts a recording when a print starts and closes it when it ends."""

    def __init__(self, client: PrinterClient, config: AgentConfig) -> None:
        self.client = client
        self.config = config

        self._recorder: Recorder | None = None
        self._task: asyncio.Task[object] | None = None
        self._previous = PrinterState.UNKNOWN

    async def run(self) -> None:
        """Follow the printer until cancelled."""
        try:
            async for state in self.client.events():
                await self._handle(state)
        finally:
            await self._stop_recording(PrinterState.UNKNOWN)

    async def _handle(self, state: PrintState) -> None:
        if state.state == self._previous:
            return

        logger.info(
            "printer went from %s to %s%s",
            self._previous.value,
            state.state.value,
            f" ({state.filename})" if state.filename else "",
        )
        previous, self._previous = self._previous, state.state

        if state.state == PrinterState.PRINTING and not previous.is_active:
            await self._start_recording(state)
        elif state.state.is_finished and previous.is_active:
            await self._stop_recording(state.state)

    async def _start_recording(self, state: PrintState) -> None:
        if self._task is not None and not self._task.done():
            logger.debug("a recording is already running")
            return

        source = create_source(self.config.camera)
        recorder = Recorder(
            source=source,
            storage_path=self.config.storage.path,
            name=job_name_for(state.filename),
            jpeg_quality=self.config.camera.jpeg_quality,
        )

        # Create the job before scheduling the task: `create_task` does not
        # run anything until the next loop tick, and the metadata below needs a
        # job to attach itself to.
        recorder.start()

        self._recorder = recorder
        self._task = asyncio.create_task(recorder.run())
        logger.info("recording started for %s", state.filename or "an unnamed print")

        await self._attach_gcode_metadata(recorder, state.filename)

    async def _attach_gcode_metadata(self, recorder: Recorder, filename: str | None) -> None:
        """Store the slicer metadata alongside the frames, if it is available."""
        if not filename:
            return
        try:
            metadata = await self.client.file_metadata(filename)
        except PrinterError as exc:
            logger.warning("could not read metadata for %s: %s", filename, exc)
            return

        # The embedded thumbnails are large and already on the printer; the
        # frames are what we are here to collect.
        metadata.pop("thumbnails", None)
        recorder.set_gcode_metadata(metadata)

    async def _stop_recording(self, final_state: PrinterState) -> None:
        task, recorder = self._task, self._recorder
        self._task = self._recorder = None

        if task is None or recorder is None:
            return

        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        result = _RESULT_BY_STATE.get(final_state, "unknown")
        if recorder.job is not None:
            recorder.set_outcome(result, printer_outcome=final_state.value)
            logger.info(
                "recording closed: %d frames, printer said %s -> result %s",
                recorder.job.frame_count,
                final_state.value,
                result,
            )
