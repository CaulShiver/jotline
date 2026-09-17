"""Packaged desktop capture: snippets, XDG entry, and terminal launch."""
from argparse import Namespace
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import pytest

from jotline import cli
from jotline import desktop
from jotline.desktop import APP_ID, CAPTURE_MARKER, RECIPE_NAMES, TERMINAL_ORDER


def parse(*argv: str):
    return cli.build_parser().parse_args(["desktop", *argv])


def run_cli(*argv: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "jotline", *argv],
        capture_output=True, text=True, env=env, timeout=30,
    )


@pytest.fixture
def desktop_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("JOTLINE_VAULT", raising=False)
    monkeypatch.delenv("JOTLINE_TERMINAL", raising=False)
    monkeypatch.setattr(desktop, "linux_desktop_available", lambda: True)
    monkeypatch.setattr(desktop, "jotline_command", lambda: ["/opt/jotline/bin/jotline"])
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    return tmp_path


def test_package_ships_every_recipe_and_desktop_template():
    root = files("jotline.desktop_data")
    assert (root / "org.jotline.capture.desktop").is_file()
    for name in RECIPE_NAMES:
        assert (root / desktop.RECIPE_FILES[name]).is_file()


def test_recipes_cover_documented_desktops_and_stay_local(desktop_home):
    omarchy = desktop.render_recipe("omarchy")
    hyprland = desktop.render_recipe("hyprland")
    gnome = desktop.render_recipe("gnome")
    kde = desktop.render_recipe("kde")
    pipe = desktop.render_recipe("pipe")
    bundled = omarchy + hyprland + gnome + kde + pipe
    assert "o.bind" in omarchy and "uwsm-app" in omarchy and APP_ID in omarchy
    assert "windowrulev2" in hyprland and "desktop launch" in hyprland
    assert "Custom Shortcuts" in gnome and "gtk-launch" in gnome
    assert "konsole" in kde and "Meta+Shift+J" in kde
    assert "wl-paste" in pipe and "pbpaste" in pipe
    assert "Get-Clipboard" not in pipe
    assert "/opt/jotline/bin/jotline" in bundled
    for forbidden in ("http://", "https://", "openai", "cloud sync", "share sheet"):
        assert forbidden not in bundled.casefold()


def test_unknown_recipe_is_rejected():
    with pytest.raises(ValueError, match="Unknown recipe"):
        desktop.render_recipe("obsidian")


def test_desktop_entry_is_a_capture_launcher():
    body = desktop.render_desktop_entry(["/opt/jotline/bin/jotline"])
    assert "Type=Application" in body
    assert "Terminal=false" in body
    assert CAPTURE_MARKER in body
    assert "Name=Jotline Capture" in body
    assert "StartupWMClass=org.jotline.capture" in body
    assert "%f" not in body and "%F" not in body and "%u" not in body
    assert "Exec=/opt/jotline/bin/jotline desktop launch" in body
    assert "TryExec=/opt/jotline/bin/jotline" in body


def test_desktop_exec_quotes_spaces_and_reserved_characters():
    quoted = desktop.quote_desktop_arg("/home/user/My Notes/jotline")
    assert quoted == '"/home/user/My Notes/jotline"'
    dollar = desktop.quote_desktop_arg("cmd$oops")
    assert dollar == '"cmd\\$oops"'
    body = desktop.render_desktop_entry(["/home/user/My Notes/jotline"])
    assert 'Exec="/home/user/My Notes/jotline" desktop launch' in body


def test_install_is_idempotent_and_status_sees_it(desktop_home):
    path = desktop.install_desktop_entry()
    assert path == desktop_home / "xdg/applications/org.jotline.capture.desktop"
    assert CAPTURE_MARKER in path.read_text(encoding="utf-8")
    again = desktop.install_desktop_entry()
    assert again == path
    report = desktop.status_report()
    assert report["installed"] is True
    assert report["path"] == str(path)
    assert report["recipes"] == list(RECIPE_NAMES)
    assert report["supported"] is True


def test_install_refuses_a_foreign_file_without_force(desktop_home):
    path = desktop.desktop_entry_path()
    path.parent.mkdir(parents=True)
    path.write_text("[Desktop Entry]\nName=Other\n")
    with pytest.raises(ValueError, match="already exists"):
        desktop.install_desktop_entry()
    desktop.install_desktop_entry(force=True)
    assert CAPTURE_MARKER in path.read_text(encoding="utf-8")


def test_install_refuses_a_symlink(desktop_home):
    path = desktop.desktop_entry_path()
    path.parent.mkdir(parents=True)
    target = desktop_home / "other.desktop"
    target.write_text("nope")
    path.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        desktop.install_desktop_entry(force=True)


def test_uninstall_removes_only_our_entry(desktop_home):
    path = desktop.install_desktop_entry()
    removed = desktop.uninstall_desktop_entry()
    assert removed == path
    assert not path.exists()
    with pytest.raises(ValueError, match="not installed"):
        desktop.uninstall_desktop_entry()


def test_uninstall_refuses_a_foreign_file(desktop_home):
    path = desktop.desktop_entry_path()
    path.parent.mkdir(parents=True)
    path.write_text("[Desktop Entry]\nName=Other\n")
    with pytest.raises(ValueError, match="not a Jotline capture"):
        desktop.uninstall_desktop_entry()
    assert path.exists()


def test_relative_xdg_data_home_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", "rel")
    assert desktop.xdg_data_home() == tmp_path / ".local/share"
    assert desktop.applications_dir() == tmp_path / ".local/share/applications"


def test_recipe_output_writes_and_refuses_overwrite(desktop_home, tmp_path):
    destination = tmp_path / "bindings" / "hyprland.conf"
    written = desktop.write_recipe("hyprland", destination)
    assert written == destination
    assert "desktop launch" in destination.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        desktop.write_recipe("hyprland", destination)
    desktop.write_recipe("hyprland", destination, force=True)


def test_cli_desktop_does_not_create_a_vault(desktop_home):
    env = {**os.environ, "XDG_DATA_HOME": str(desktop_home / "xdg")}
    result = run_cli("desktop", "status", "--json", env=env)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["recipes"] == list(RECIPE_NAMES)
    assert not (desktop_home / "xdg/jotline").exists()
    assert not list(desktop_home.glob("**/.jotline.lock"))


def test_cli_prints_recipe_and_lists_names(desktop_home):
    listed = run_cli("desktop", "recipe")
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.splitlines() == list(RECIPE_NAMES)
    printed = run_cli("desktop", "recipe", "omarchy")
    assert printed.returncode == 0, printed.stderr
    assert "o.bind" in printed.stdout
    assert "SUPER + SHIFT + J" in printed.stdout


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="XDG desktop install is Linux-only")
def test_cli_install_uninstall_round_trip(desktop_home, monkeypatch):
    env = {**os.environ, "XDG_DATA_HOME": str(desktop_home / "xdg"), "HOME": str(desktop_home)}
    monkeypatch.setattr(Path, "home", lambda: desktop_home)
    installed = run_cli("desktop", "install", env=env)
    assert installed.returncode == 0, installed.stderr
    path = Path(installed.stdout.strip())
    assert path.is_file()
    assert CAPTURE_MARKER in path.read_text(encoding="utf-8")
    status = run_cli("desktop", "--json", env=env)
    assert json.loads(status.stdout)["installed"] is True
    removed = run_cli("desktop", "uninstall", env=env)
    assert removed.returncode == 0, removed.stderr
    assert not path.exists()


def test_cli_rejects_mismatched_flags(desktop_home):
    result = run_cli("desktop", "install", "hyprland")
    assert result.returncode == 1
    assert "recipe name is only used" in result.stderr
    daily = run_cli("desktop", "status", "--daily")
    assert daily.returncode == 1
    assert "--daily is only used" in daily.stderr
    json_flag = run_cli("desktop", "recipe", "--json")
    assert json_flag.returncode == 1
    output = run_cli("desktop", "install", "--output", str(desktop_home / "out.txt"))
    assert output.returncode == 1


def test_linux_only_actions_explain_macos_and_refuse_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ValueError, match="Windows is out of scope"):
        desktop.run_desktop_command(parse("install"))
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(ValueError, match="pbpaste"):
        desktop.run_desktop_command(parse("launch"))
    monkeypatch.setattr(sys, "platform", "linux")
    recipe = desktop.render_recipe("pipe")
    assert "wl-paste" in recipe
    assert "Get-Clipboard" not in recipe


def test_status_on_windows_says_out_of_scope(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(desktop, "linux_desktop_available", lambda: False)
    monkeypatch.setattr(desktop, "jotline_command", lambda: ["jotline"])
    report = desktop.status_report()
    assert report["supported"] is False
    text = desktop.format_status(report)
    assert "Windows is out of scope" in text
    assert "Get-Clipboard" not in text


def test_terminal_argv_sets_capture_class():
    capture = ["jotline", "capture"]
    assert desktop.terminal_argv("kitty", "/usr/bin/kitty", capture) == [
        "/usr/bin/kitty", "--class", APP_ID, "-e", "jotline", "capture"]
    assert desktop.terminal_argv("foot", "/usr/bin/foot", capture) == [
        "/usr/bin/foot", f"--app-id={APP_ID}", "jotline", "capture"]
    assert desktop.terminal_argv("alacritty", "/usr/bin/alacritty", capture) == [
        "/usr/bin/alacritty", "--class", APP_ID, "-e", "jotline", "capture"]
    assert desktop.terminal_argv("ghostty", "/usr/bin/ghostty", capture) == [
        "/usr/bin/ghostty", f"--class={APP_ID}", "-e", "jotline", "capture"]
    assert desktop.terminal_argv("wezterm", "/usr/bin/wezterm", capture) == [
        "/usr/bin/wezterm", "start", "--class", APP_ID, "--", "jotline", "capture"]
    assert desktop.terminal_argv("konsole", "/usr/bin/konsole", capture) == [
        "/usr/bin/konsole", "--name", APP_ID, "-e", "jotline", "capture"]
    assert desktop.terminal_argv("gnome-terminal", "/usr/bin/gnome-terminal", capture) == [
        "/usr/bin/gnome-terminal", "--title=Jotline", "--", "jotline", "capture"]
    assert desktop.terminal_argv("xdg-terminal-exec", "/usr/bin/xdg-terminal-exec", capture) == [
        "/usr/bin/xdg-terminal-exec", "--", "jotline", "capture"]
    xfce = desktop.terminal_argv("xfce4-terminal", "/usr/bin/xfce4-terminal", capture)
    assert xfce[0] == "/usr/bin/xfce4-terminal"
    assert xfce[-2] == "-e"
    with pytest.raises(ValueError, match="Unknown terminal"):
        desktop.terminal_argv("notepad", "notepad", capture)


def test_launch_prefers_hyprland_and_gnome_terminals(monkeypatch):
    capture = ["jotline", "capture"]
    monkeypatch.delenv("JOTLINE_TERMINAL", raising=False)

    def which(name: str, wanted: str):
        return f"/usr/bin/{name}" if name == wanted else None

    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "Hyprland")
    monkeypatch.setattr(desktop.shutil, "which", lambda name: which(name, "kitty"))
    plan = desktop.launch_plan(capture, in_terminal=False)
    assert plan.mode == "spawn" and plan.argv[0].endswith("kitty")

    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.setattr(desktop.shutil, "which", lambda name: which(name, "ptyxis"))
    plan = desktop.launch_plan(capture, in_terminal=False)
    assert plan.argv[0].endswith("ptyxis")

    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setattr(desktop.shutil, "which", lambda name: which(name, "konsole"))
    plan = desktop.launch_plan(capture, in_terminal=False)
    assert plan.argv[0].endswith("konsole")


def test_launch_honors_known_terminal_override(monkeypatch):
    monkeypatch.setenv("JOTLINE_TERMINAL", "foot")
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/foot" if name == "foot" else None)
    plan = desktop.launch_plan(["jotline", "capture"], in_terminal=False)
    assert plan.argv[:2] == ["/usr/bin/foot", f"--app-id={APP_ID}"]
    monkeypatch.setenv("JOTLINE_TERMINAL", "not-a-terminal")
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/tmp/not-a-terminal")
    with pytest.raises(ValueError, match="JOTLINE_TERMINAL"):
        desktop.launch_plan(["jotline", "capture"], in_terminal=False)


def test_launch_falls_back_to_current_tty_or_explains_pipe(monkeypatch):
    monkeypatch.delenv("JOTLINE_TERMINAL", raising=False)
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    plan = desktop.launch_plan(["/opt/jotline/bin/jotline", "capture"], in_terminal=True)
    assert plan == desktop.LaunchPlan("exec", ["/opt/jotline/bin/jotline", "capture"])
    with pytest.raises(ValueError, match="pipe text: " + re.escape(desktop.clipboard_pipe())):
        desktop.launch_plan(["jotline", "capture"], in_terminal=False)


def test_execute_launch_spawns_detached_and_execs(monkeypatch):
    spawned = []
    monkeypatch.setattr(
        desktop.subprocess, "Popen",
        lambda argv, **kwargs: spawned.append((argv, kwargs)) or type("Proc", (), {"pid": 7})(),
    )
    desktop.execute_launch(desktop.LaunchPlan("spawn", ["kitty", "-e", "jotline", "capture"]))
    argv, kwargs = spawned[0]
    assert argv[0] == "kitty"
    assert kwargs["start_new_session"] is True
    assert kwargs["close_fds"] is True
    executed = []
    monkeypatch.setattr(desktop.os, "execvp", lambda file, args: executed.append((file, list(args))))
    desktop.execute_launch(desktop.LaunchPlan("exec", ["jotline", "capture"]))
    assert executed == [("jotline", ["jotline", "capture"])]


def test_capture_command_uses_injected_jotline(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop, "jotline_command", lambda: ["/opt/jotline/bin/jotline"])
    vault = tmp_path / "notes"
    args = Namespace(vault=str(vault), workspace="work", daily=True)
    assert desktop.capture_command(args) == [
        "/opt/jotline/bin/jotline", "--vault", str(vault.expanduser()),
        "--workspace", "work", "capture", "--daily",
    ]
    args = Namespace(vault=str(vault), workspace=None, daily=False)
    assert desktop.capture_command(args) == [
        "/opt/jotline/bin/jotline", "--vault", str(vault.expanduser()), "capture",
    ]


def test_preferred_terminal_order_covers_known_emulators():
    for name in TERMINAL_ORDER:
        assert name in set(desktop.preferred_terminals(""))
    hypr = desktop.preferred_terminals("Hyprland:uwsm")
    assert hypr[0] == "kitty"
    gnome = desktop.preferred_terminals("GNOME")
    assert gnome[0] == "ptyxis"
    kde = desktop.preferred_terminals("KDE")
    assert kde[0] == "konsole"


def test_refresh_desktop_database_ignores_missing_and_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    desktop.refresh_desktop_database(tmp_path)
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/update-desktop-database")

    def boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="update-desktop-database", timeout=10)

    monkeypatch.setattr(desktop.subprocess, "run", boom)
    desktop.refresh_desktop_database(tmp_path)


def test_cli_recipe_output(desktop_home, tmp_path):
    destination = tmp_path / "omarchy.lua"
    result = run_cli("desktop", "recipe", "omarchy", "--output", str(destination))
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == destination
    assert destination.read_text(encoding="utf-8").startswith("-- Jotline")
    missing = run_cli("desktop", "recipe", "--output", str(tmp_path / "all.lua"))
    assert missing.returncode == 1
    assert "Choose a recipe name" in missing.stderr


def test_installed_mode_is_user_private(desktop_home):
    path = desktop.install_desktop_entry()
    assert stat.S_ISREG(path.stat().st_mode)
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
