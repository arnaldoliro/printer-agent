"""Recorder: frames and metadata on disk."""

from __future__ import annotations

import json
from pathlib import Path

from agent.camera import FileSource
from agent.recorder import Recorder, slugify


def record(video: Path, output: Path, **kwargs):
    source = FileSource(video, interval_seconds=1.0)
    return Recorder(source=source, storage_path=output, name="teste de impressao").run(**kwargs)


def test_writes_frames_and_metadata(sample_video: Path, tmp_path: Path) -> None:
    output = tmp_path / "dados"
    job = record(sample_video, output)

    job_dir = Path(job.directory)
    frames = sorted((job_dir / "frames").glob("*.jpg"))

    assert job.frame_count == 3
    assert len(frames) == 3
    assert frames[0].name == "000001.jpg"
    assert frames[0].stat().st_size > 0


def test_metadata_describes_the_job(sample_video: Path, tmp_path: Path) -> None:
    job = record(sample_video, tmp_path / "dados")
    metadata = json.loads((Path(job.directory) / "job.json").read_text())

    assert metadata["status"] == "completed"
    assert metadata["result"] == "unknown"
    assert metadata["frame_count"] == 3
    assert metadata["source"] == f"file:{sample_video}"
    assert metadata["capture_interval_seconds"] == 1.0
    assert metadata["finished_at"]
    assert metadata["agent_version"]


def test_job_directory_is_named_after_the_job(sample_video: Path, tmp_path: Path) -> None:
    job = record(sample_video, tmp_path / "dados")
    assert Path(job.directory).name.endswith("_teste-de-impressao")


def test_max_frames_stops_early(sample_video: Path, tmp_path: Path) -> None:
    job = record(sample_video, tmp_path / "dados", max_frames=2)
    assert job.frame_count == 2


def test_metadata_exists_before_the_job_ends(sample_video: Path, tmp_path: Path) -> None:
    """A crash or a power cut must still leave a readable record."""
    output = tmp_path / "dados"
    source = FileSource(sample_video, interval_seconds=1.0)
    recorder = Recorder(source=source, storage_path=output, name="parcial")

    recorder.run(max_frames=1)
    job_dirs = list(output.iterdir())

    assert len(job_dirs) == 1
    assert (job_dirs[0] / "job.json").is_file()


def test_slugify_handles_accents_and_symbols() -> None:
    assert slugify("Impressão #1 — suporte") == "impressao-1-suporte"
    assert slugify("///") == "job"
