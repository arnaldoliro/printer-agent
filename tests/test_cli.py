"""Smoke tests for the CLI skeleton."""

from __future__ import annotations

import pytest

from agent import __version__
from agent.__main__ import main


def test_version_is_set() -> None:
    assert __version__


def test_main_prints_help_and_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "printer-agent" in capsys.readouterr().out
