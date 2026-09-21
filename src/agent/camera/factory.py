"""Builds the right video source from configuration."""

from __future__ import annotations

from agent.camera.base import VideoSource
from agent.camera.file import FileSource
from agent.camera.live import NetworkSource, WebcamSource
from agent.config import CameraConfig


def create_source(config: CameraConfig) -> VideoSource:
    """Return the video source described by `config`."""
    interval = config.capture_interval_seconds

    if config.source == "webcam":
        return WebcamSource(device=config.device, interval_seconds=interval)
    if config.source == "network":
        assert config.url is not None  # guaranteed by CameraConfig validation
        return NetworkSource(url=config.url, interval_seconds=interval)
    if config.source == "file":
        assert config.path is not None  # guaranteed by CameraConfig validation
        return FileSource(path=config.path, interval_seconds=interval)

    raise ValueError(f"unknown camera source: {config.source}")
