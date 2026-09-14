"""Refuse Windows at the process entry before POSIX-only storage is imported."""
from pathlib import Path
import sys

import pytest

from jotline.launch import UNSUPPORTED_WINDOWS, main


ROOT = Path(__file__).resolve().parents[1]


def test_launch_refuses_windows(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "win32")

    with pytest.raises(SystemExit) as exited:
        main()

    assert exited.value.code == 2
    assert capsys.readouterr().err.strip() == UNSUPPORTED_WINDOWS


def test_console_script_and_module_entry_use_launch():
    main_py = (ROOT / "src/jotline/__main__.py").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "from .launch import main" in main_py
    assert 'jotline = "jotline.launch:main"' in pyproject
