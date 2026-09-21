"""Configuration loading and validation.

The agent is configured through a YAML file. Only the sections the agent
currently uses are modelled here; unknown keys are ignored on purpose, so
`config.example.yaml` can document options that land in later commits.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_CONFIG_PATHS = (Path("config.yaml"), Path("config.local.yaml"))

SourceKind = Literal["webcam", "network", "file"]


class CameraConfig(BaseModel):
    """How the agent sees the print."""

    model_config = ConfigDict(extra="ignore")

    source: SourceKind = "webcam"

    #: index of the local video device, used when source is "webcam"
    device: int = 0
    #: RTSP/MJPEG address, used when source is "network"
    url: str | None = None
    #: recorded video file, used when source is "file"
    path: Path | None = None

    #: Seconds between captured frames. Print failures unfold over minutes, so
    #: a very low interval buys nothing and fills the disk.
    capture_interval_seconds: float = Field(default=10.0, gt=0)

    #: JPEG quality for stored frames. 85 keeps failures readable at roughly a
    #: third of the size of quality 95.
    jpeg_quality: int = Field(default=85, ge=1, le=100)

    @model_validator(mode="after")
    def _require_source_target(self) -> CameraConfig:
        if self.source == "network" and not self.url:
            raise ValueError('camera.url is required when camera.source is "network"')
        if self.source == "file" and not self.path:
            raise ValueError('camera.path is required when camera.source is "file"')
        return self

    def describe(self) -> str:
        """Human readable description, stored in the job metadata."""
        if self.source == "webcam":
            return f"webcam:{self.device}"
        if self.source == "network":
            return f"network:{self.url}"
        return f"file:{self.path}"


class StorageConfig(BaseModel):
    """Where recordings go."""

    model_config = ConfigDict(extra="ignore")

    path: Path = Path("./dados")


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    level: str = "INFO"


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    camera: CameraConfig = Field(default_factory=CameraConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def find_default_config() -> Path | None:
    """Return the first default config file that exists, if any."""
    return next((path for path in DEFAULT_CONFIG_PATHS if path.is_file()), None)


def load_config(path: Path | None = None) -> AgentConfig:
    """Load configuration from `path`, or fall back to defaults.

    Running without any config file is supported: every option has a default,
    which keeps `printer-agent record --source webcam` usable out of the box.
    """
    if path is None:
        path = find_default_config()
    if path is None:
        return AgentConfig()

    if not path.is_file():
        raise FileNotFoundError(f"configuration file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")

    return AgentConfig.model_validate(raw)
