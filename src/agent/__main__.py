"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from agent import __version__
from agent.camera import VideoSourceError, create_source
from agent.config import AgentConfig, CameraConfig, load_config
from agent.logging_setup import setup_logging
from agent.recorder import Recorder

logger = logging.getLogger("agent")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="printer-agent",
        description="Local agent that watches a 3D print and reports failures.",
    )
    parser.add_argument("--version", action="version", version=f"printer-agent {__version__}")
    parser.add_argument("--config", type=Path, help="path to config.yaml")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING, ERROR")

    subparsers = parser.add_subparsers(dest="command")

    record = subparsers.add_parser(
        "record",
        help="record a print to disk",
        description=(
            "Capture frames from a camera or a video file into a job directory. "
            "Start and stop are manual for now; the printer drives them in a later commit."
        ),
    )
    record.add_argument("--source", choices=("webcam", "network", "file"))
    record.add_argument("--device", type=int, help="video device index for --source webcam")
    record.add_argument("--url", help="stream address for --source network")
    record.add_argument("--path", type=Path, help="video file for --source file")
    record.add_argument("--interval", type=float, help="seconds between captured frames")
    record.add_argument("--quality", type=int, help="JPEG quality, 1-100")
    record.add_argument("--name", default="print", help="job name, used in the directory name")
    record.add_argument("--output", type=Path, help="directory to store jobs in")
    record.add_argument("--max-frames", type=int, help="stop after this many frames")
    record.add_argument("--max-duration", type=float, help="stop after this many seconds")

    return parser


def _camera_config(config: AgentConfig, args: argparse.Namespace) -> CameraConfig:
    """Apply command line overrides on top of the configuration file."""
    values = config.camera.model_dump()

    for arg_name, key in (
        ("source", "source"),
        ("device", "device"),
        ("url", "url"),
        ("path", "path"),
        ("interval", "capture_interval_seconds"),
        ("quality", "jpeg_quality"),
    ):
        value = getattr(args, arg_name, None)
        if value is not None:
            values[key] = value

    # A source given on the command line replaces the configured one, so drop
    # the targets that belong to the other kinds and would confuse validation.
    if args.source is not None:
        if args.source != "network" and args.url is None:
            values["url"] = None
        if args.source != "file" and args.path is None:
            values["path"] = None

    return CameraConfig.model_validate(values)


def command_record(config: AgentConfig, args: argparse.Namespace) -> int:
    camera = _camera_config(config, args)
    output = args.output or config.storage.path

    try:
        source = create_source(camera)
    except ValueError as exc:
        logger.error("%s", exc)
        return 2

    recorder = Recorder(
        source=source,
        storage_path=output,
        name=args.name,
        jpeg_quality=camera.jpeg_quality,
    )

    try:
        job = recorder.run(max_frames=args.max_frames, max_duration_seconds=args.max_duration)
    except VideoSourceError as exc:
        logger.error("%s", exc)
        return 1

    return 0 if job.frame_count else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    setup_logging(args.log_level or config.logging.level)

    if args.command == "record":
        try:
            return command_record(config, args)
        except ValueError as exc:
            logger.error("%s", exc)
            return 2

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
