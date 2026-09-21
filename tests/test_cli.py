"""CLI behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent import __version__
from agent.__main__ import main


def test_version_is_set() -> None:
    assert __version__


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "printer-agent" in capsys.readouterr().out


def test_record_from_a_video_file(sample_video: Path, tmp_path: Path) -> None:
    output = tmp_path / "dados"
    exit_code = main(
        [
            "record",
            "--source",
            "file",
            "--path",
            str(sample_video),
            "--interval",
            "1",
            "--output",
            str(output),
            "--name",
            "cli",
        ]
    )

    assert exit_code == 0
    job_dir = next(output.iterdir())
    assert len(list((job_dir / "frames").glob("*.jpg"))) == 3


def test_network_source_without_url_is_rejected(tmp_path: Path) -> None:
    assert main(["record", "--source", "network", "--output", str(tmp_path)]) == 2


def test_missing_config_file_is_rejected(tmp_path: Path) -> None:
    assert main(["--config", str(tmp_path / "absent.yaml"), "record"]) == 2
