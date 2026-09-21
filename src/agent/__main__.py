"""Command line entry point.

Nothing is wired up yet: this commit only prepares the project skeleton.
Recording, printer integration and failure detection land in later commits.
"""

from __future__ import annotations

import argparse
import sys

from agent import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="printer-agent",
        description="Local agent that watches a 3D print and reports failures.",
    )
    parser.add_argument("--version", action="version", version=f"printer-agent {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
