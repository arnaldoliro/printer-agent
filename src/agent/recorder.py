"""Records a print job: frames on disk plus the metadata that describes them.

A recorded failure is the one piece of training data that cannot be bought or
downloaded, so recording comes before any detection. Every print that happens
without this running is data lost for good.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import cv2

from agent import __version__
from agent.camera.base import VideoSource

logger = logging.getLogger(__name__)

JobStatus = Literal["recording", "completed", "interrupted", "failed"]
#: Outcome of the print itself, which the agent cannot know yet. It stays
#: "unknown" until a human labels it or, later, the printer reports it.
JobResult = Literal["unknown", "success", "failure"]

JOB_METADATA_FILENAME = "job.json"
FRAMES_DIRNAME = "frames"


def slugify(value: str) -> str:
    """Turn a job name into something safe for a directory name."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "job"


@dataclass
class Job:
    """Everything known about one recording."""

    name: str
    source: str
    capture_interval_seconds: float
    started_at: str
    directory: str
    agent_version: str = __version__
    finished_at: str | None = None
    duration_seconds: float | None = None
    frame_count: int = 0
    status: JobStatus = "recording"
    result: JobResult = "unknown"
    notes: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n"


class Recorder:
    """Drives a `VideoSource` and writes what it returns to a job directory."""

    def __init__(
        self,
        source: VideoSource,
        storage_path: Path,
        name: str,
        jpeg_quality: int = 85,
    ) -> None:
        self.source = source
        self.storage_path = Path(storage_path)
        self.name = name
        self.jpeg_quality = jpeg_quality

        self._job: Job | None = None
        self._job_dir: Path | None = None
        self._frames_dir: Path | None = None

    @property
    def job(self) -> Job | None:
        return self._job

    def run(self, max_frames: int | None = None, max_duration_seconds: float | None = None) -> Job:
        """Record until the source is exhausted, a limit is hit, or Ctrl+C.

        The job metadata is written before the first frame and rewritten at the
        end, so an interrupted or crashed run still leaves a readable record.
        """
        job = self._start()
        started = datetime.now().astimezone()

        try:
            with self.source:
                while True:
                    if max_frames is not None and job.frame_count >= max_frames:
                        logger.info("reached the frame limit of %d", max_frames)
                        break

                    elapsed = (datetime.now().astimezone() - started).total_seconds()
                    if max_duration_seconds is not None and elapsed >= max_duration_seconds:
                        logger.info("reached the duration limit of %.0fs", max_duration_seconds)
                        break

                    frame = self.source.read()
                    if frame is None:
                        logger.info("source exhausted after %d frames", job.frame_count)
                        break

                    self._write_frame(frame.image, job.frame_count + 1)
                    job.frame_count += 1
                    if job.frame_count % 10 == 0:
                        logger.info("captured %d frames", job.frame_count)

            job.status = "completed"
        except KeyboardInterrupt:
            logger.info("interrupted after %d frames", job.frame_count)
            job.status = "interrupted"
        except Exception:
            job.status = "failed"
            self._finish(job, started)
            raise

        self._finish(job, started)
        return job

    def _start(self) -> Job:
        started_at = datetime.now().astimezone()
        directory = self.storage_path / f"{started_at:%Y-%m-%d_%H%M%S}_{slugify(self.name)}"
        frames_dir = directory / FRAMES_DIRNAME
        frames_dir.mkdir(parents=True, exist_ok=True)

        job = Job(
            name=self.name,
            source=self.source.describe(),
            capture_interval_seconds=self.source.interval_seconds,
            started_at=started_at.isoformat(),
            directory=str(directory),
        )

        self._job = job
        self._job_dir = directory
        self._frames_dir = frames_dir
        self._write_metadata(job)

        logger.info("recording %s into %s", job.source, directory)
        return job

    def _write_frame(self, image, index: int) -> None:
        assert self._frames_dir is not None
        target = self._frames_dir / f"{index:06d}.jpg"
        ok = cv2.imwrite(str(target), image, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not ok:
            raise OSError(f"could not write frame to {target}")

    def _finish(self, job: Job, started: datetime) -> None:
        finished = datetime.now().astimezone()
        job.finished_at = finished.isoformat()
        job.duration_seconds = round((finished - started).total_seconds(), 3)
        self._write_metadata(job)
        logger.info(
            "job %s: %d frames in %.1fs -> %s",
            job.status,
            job.frame_count,
            job.duration_seconds,
            job.directory,
        )

    def _write_metadata(self, job: Job) -> None:
        assert self._job_dir is not None
        (self._job_dir / JOB_METADATA_FILENAME).write_text(job.to_json(), encoding="utf-8")
