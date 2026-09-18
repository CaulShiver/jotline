import subprocess
import sys

import pytest

from jotline.accessibility import COPY_NATIVE, COPY_REQUEST
from jotline.app import Jotline
from jotline.clipboard import clipboard_command, write_system_clipboard
from jotline.store import Vault


def notifications(app):
    return [item.message for item in app._notifications]


def test_macos_clipboard_command_is_pbcopy(monkeypatch):
    monkeypatch.setattr("jotline.clipboard.shutil.which", lambda name: "/usr/bin/pbcopy" if name == "pbcopy" else None)
    assert clipboard_command("darwin") == ["/usr/bin/pbcopy"]


def test_linux_prefers_wl_copy_on_wayland(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        "jotline.clipboard.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"wl-copy", "xclip"} else None,
    )
    assert clipboard_command("linux") == ["/usr/bin/wl-copy"]


def test_linux_uses_xclip_on_x11(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(
        "jotline.clipboard.shutil.which",
        lambda name: "/usr/bin/xclip" if name == "xclip" else None,
    )
    assert clipboard_command("linux") == ["/usr/bin/xclip", "-selection", "clipboard"]


def test_write_system_clipboard_returns_false_without_a_tool(monkeypatch):
    monkeypatch.setattr("jotline.clipboard.clipboard_command", lambda: None)
    assert write_system_clipboard("note") is False


def test_write_system_clipboard_runs_the_tool(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("jotline.clipboard.clipboard_command", lambda: ["/usr/bin/pbcopy"])
    monkeypatch.setattr("jotline.clipboard.subprocess.run", fake_run)
    assert write_system_clipboard("café") is True
    assert seen["command"] == ["/usr/bin/pbcopy"]
    assert seen["input"] == "café".encode("utf-8")


def test_write_system_clipboard_false_on_tool_error(monkeypatch):
    def fake_run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("jotline.clipboard.clipboard_command", lambda: ["/usr/bin/pbcopy"])
    monkeypatch.setattr("jotline.clipboard.subprocess.run", fake_run)
    assert write_system_clipboard("note") is False


@pytest.mark.skipif(sys.platform != "darwin", reason="pbcopy is the macOS clipboard")
def test_macos_pbcopy_round_trip():
    marker = "jotline-native-clipboard-aa91"
    previous = subprocess.run(["pbpaste"], capture_output=True, check=True).stdout
    try:
        assert write_system_clipboard(marker)
        assert subprocess.run(["pbpaste"], capture_output=True, check=True).stdout == marker.encode()
    finally:
        subprocess.run(["pbcopy"], input=previous, check=True)


async def test_copy_confirms_when_native_clipboard_works(tmp_path, monkeypatch):
    monkeypatch.setattr("jotline.clipboard.write_system_clipboard", lambda text: True)
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.editor().insert("synthetic note")
        app.command("copy")
        await pilot.pause()
        assert app.clipboard == "synthetic note"
        messages = notifications(app)
        assert COPY_NATIVE in messages
        assert COPY_REQUEST not in messages


async def test_copy_describes_osc52_when_native_clipboard_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("jotline.clipboard.write_system_clipboard", lambda text: False)
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.editor().insert("synthetic note")
        app.command("copy")
        await pilot.pause()
        assert app.clipboard == "synthetic note"
        messages = notifications(app)
        assert COPY_REQUEST in messages
        assert COPY_NATIVE not in messages
        assert all("successfully" not in message.casefold() for message in messages)
