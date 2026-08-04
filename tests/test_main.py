"""Unit tests for nikitai.__main__ entry point."""

from __future__ import annotations

import runpy
from unittest.mock import patch


@patch("nikitai.cli.main")
def test_dunder_main_invokes_main(mock_main):
    runpy.run_module("nikitai.__main__", run_name="__main__")

    mock_main.assert_called_once_with()
