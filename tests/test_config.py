"""Configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agent.config import AgentConfig, CameraConfig, load_config

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.yaml"


def test_defaults_work_without_a_file() -> None:
    config = load_config(None)
    assert config.camera.source == "webcam"
    assert config.camera.capture_interval_seconds == 10.0


def test_example_config_is_valid() -> None:
    """The shipped example must always load, or new users start broken."""
    config = AgentConfig.model_validate(yaml.safe_load(EXAMPLE_CONFIG.read_text()))
    assert config.camera.source == "webcam"
    assert config.storage.path == Path("./dados")


def test_unknown_sections_are_ignored() -> None:
    """Options documented for later commits must not break loading today."""
    config = AgentConfig.model_validate({"printer": {"type": "moonraker"}, "mode": "observer"})
    assert config.camera.source == "webcam"


def test_load_config_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("camera:\n  source: webcam\n  device: 2\n", encoding="utf-8")
    assert load_config(path).camera.device == 2


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "absent.yaml")


def test_network_source_requires_a_url() -> None:
    with pytest.raises(ValidationError, match=r"camera\.url is required"):
        CameraConfig(source="network")


def test_file_source_requires_a_path() -> None:
    with pytest.raises(ValidationError, match=r"camera\.path is required"):
        CameraConfig(source="file")


def test_interval_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        CameraConfig(capture_interval_seconds=0)


def test_describe_identifies_the_source() -> None:
    assert CameraConfig(source="webcam", device=1).describe() == "webcam:1"
    assert CameraConfig(source="file", path=Path("a.mp4")).describe() == "file:a.mp4"
