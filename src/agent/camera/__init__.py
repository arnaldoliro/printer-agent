"""Video sources: where the agent gets its frames from."""

from __future__ import annotations

from agent.camera.base import Frame, VideoSource, VideoSourceError
from agent.camera.factory import create_source
from agent.camera.file import FileSource
from agent.camera.live import NetworkSource, WebcamSource

__all__ = [
    "FileSource",
    "Frame",
    "NetworkSource",
    "VideoSource",
    "VideoSourceError",
    "WebcamSource",
    "create_source",
]
