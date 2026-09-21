"""Command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
from pathlib import Path

from agent import __version__
from agent.camera import VideoSourceError, create_source
from agent.config import AgentConfig, CameraConfig, load_config
from agent.logging_setup import setup_logging
from agent.printer import MoonrakerClient, PrinterError
from agent.recorder import Recorder
from agent.watcher import PrintWatcher

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
        description="Capture frames from a camera or a video file into a job directory.",
    )
    _add_camera_arguments(record)
    record.add_argument("--name", default="print", help="job name, used in the directory name")
    record.add_argument("--output", type=Path, help="directory to store jobs in")
    record.add_argument("--max-frames", type=int, help="stop after this many frames")
    record.add_argument("--max-duration", type=float, help="stop after this many seconds")

    watch = subparsers.add_parser(
        "watch",
        help="follow the printer and record every print automatically",
        description=(
            "Connect to the printer and let it drive the recorder: a job starts when a print "
            "starts and is labelled with the outcome the printer reports. Runs until stopped."
        ),
    )
    _add_camera_arguments(watch)
    _add_printer_arguments(watch)
    watch.add_argument("--output", type=Path, help="directory to store jobs in")

    status = subparsers.add_parser(
        "status",
        help="check that the printer is reachable and show what it is doing",
    )
    _add_printer_arguments(status)

    return parser


def _add_camera_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", choices=("webcam", "network", "file"))
    parser.add_argument("--device", type=int, help="video device index for --source webcam")
    parser.add_argument("--url", help="stream address for --source network")
    parser.add_argument("--path", type=Path, help="video file for --source file")
    parser.add_argument("--interval", type=float, help="seconds between captured frames")
    parser.add_argument("--quality", type=int, help="JPEG quality, 1-100")


def _add_printer_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--printer-url", help="Moonraker address, e.g. http://192.168.0.42:7125")
    parser.add_argument("--api-key", help="Moonraker API key, when the printer requires one")


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
    if getattr(args, "source", None) is not None:
        if args.source != "network" and args.url is None:
            values["url"] = None
        if args.source != "file" and args.path is None:
            values["path"] = None

    return CameraConfig.model_validate(values)


def _printer_client(config: AgentConfig, args: argparse.Namespace) -> MoonrakerClient:
    return MoonrakerClient(
        url=getattr(args, "printer_url", None) or config.printer.url,
        api_key=getattr(args, "api_key", None) or config.printer.api_key,
        read_only=config.read_only,
        timeout=config.printer.timeout_seconds,
    )


async def command_record(config: AgentConfig, args: argparse.Namespace) -> int:
    camera = _camera_config(config, args)
    recorder = Recorder(
        source=create_source(camera),
        storage_path=args.output or config.storage.path,
        name=args.name,
        jpeg_quality=camera.jpeg_quality,
    )

    try:
        job = await recorder.run(
            max_frames=args.max_frames,
            max_duration_seconds=args.max_duration,
        )
    except VideoSourceError as exc:
        logger.error("%s", exc)
        return 1

    return 0 if job.frame_count else 1


async def command_watch(config: AgentConfig, args: argparse.Namespace) -> int:
    resolved = config.model_copy(
        update={
            "camera": _camera_config(config, args),
            "storage": config.storage.model_copy(
                update={"path": args.output or config.storage.path}
            ),
        }
    )

    if config.read_only:
        logger.info("observer mode: the agent will record and report, but never pause a print")

    try:
        async with _printer_client(config, args) as client:
            info = await client.info()
            logger.info("connected to %s", info.get("hostname", config.printer.url))

            watcher = PrintWatcher(client=client, config=resolved)
            with contextlib.suppress(asyncio.CancelledError, KeyboardInterrupt):
                await watcher.run()
    except PrinterError as exc:
        logger.error("%s", exc)
        return 1

    return 0


async def command_status(config: AgentConfig, args: argparse.Namespace) -> int:
    try:
        async with _printer_client(config, args) as client:
            info = await client.info()
            state = await client.status()
    except PrinterError as exc:
        logger.error("%s", exc)
        return 1

    print(f"printer:  {info.get('hostname', '?')} ({info.get('state', '?')})")
    print(f"state:    {state.state.value}")
    print(f"file:     {state.filename or '-'}")
    print(f"progress: {state.progress * 100:.1f}%")
    if state.message:
        print(f"message:  {state.message}")
    return 0


COMMANDS = {
    "record": command_record,
    "watch": command_watch,
    "status": command_status,
}


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

    try:
        return asyncio.run(COMMANDS[args.command](config, args))
    except ValueError as exc:
        logger.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
