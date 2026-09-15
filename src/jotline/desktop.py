"""Packaged Linux desktop capture: snippets, an XDG desktop entry, and a launcher.

Pipe-in remains the integration for launchers that cannot open a terminal.
This does not add dictation, a share sheet, or a network service.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
from typing import Literal

from .filesystem import (
    create_private_temp,
    fs,
    pin_ancestors,
    publish_new,
    replace_at,
    unlink_quietly,
)
from .limits import MAX_SETTINGS_BYTES

APP_ID = "org.jotline.capture"
DESKTOP_FILENAME = f"{APP_ID}.desktop"
WINDOW_TITLE = "Jotline"
CAPTURE_MARKER = "X-Jotline-Capture=1"
DESKTOP_ACTIONS = ("install", "uninstall", "status", "recipe", "launch")
RECIPE_NAMES = ("omarchy", "hyprland", "gnome", "kde", "pipe")
RECIPE_FILES = {
    "omarchy": "omarchy.lua",
    "hyprland": "hyprland.conf",
    "gnome": "gnome.txt",
    "kde": "kde.txt",
    "pipe": "pipe.txt",
}
DATA_PACKAGE = "jotline.desktop_data"
DESKTOP_RESERVED = set(" \t\n\"'\\><~|&;$*?#(){}[]`")
TERMINAL_ORDER = (
    "kitty", "alacritty", "foot", "ghostty", "wezterm",
    "ptyxis", "kgx", "gnome-terminal", "konsole", "xfce4-terminal",
    "xdg-terminal-exec",
)

UNSUPPORTED = {
    "win32": (
        "Desktop capture packaging is for Linux (XDG). On Windows, bind "
        "Windows Terminal to jotline capture, or pipe the clipboard: "
        'powershell -NoProfile -Command "Get-Clipboard" | jotline capture'
    ),
    "darwin": (
        "Desktop capture packaging is for Linux (XDG). On macOS, bind a "
        "terminal hotkey to jotline capture, or pipe the clipboard: "
        "pbpaste | jotline capture"
    ),
}
GENERIC_UNSUPPORTED = (
    "Desktop capture packaging is for Linux (XDG). Bind a terminal to "
    "jotline capture, or pipe text: jotline desktop recipe pipe"
)


def linux_desktop_available() -> bool:
    return sys.platform.startswith("linux")


def unsupported_message() -> str:
    return UNSUPPORTED.get(sys.platform, GENERIC_UNSUPPORTED)


def xdg_data_home() -> Path:
    value = os.environ.get("XDG_DATA_HOME") or ""
    if Path(value).is_absolute():
        return Path(value)
    return Path.home() / ".local/share"


def applications_dir() -> Path:
    return xdg_data_home() / "applications"


def desktop_entry_path() -> Path:
    return applications_dir() / DESKTOP_FILENAME


def jotline_command() -> list[str]:
    """Argv that reinvokes this Jotline CLI."""
    candidate = Path(sys.argv[0]).expanduser()
    if candidate.name.lower() in {"jotline", "jotline.exe"}:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return [str(candidate.resolve())]
        found = shutil.which("jotline")
        if found:
            return [found]
    found = shutil.which("jotline")
    if found:
        return [found]
    return [sys.executable, "-m", "jotline"]


def jotline_shell(command: list[str] | None = None) -> str:
    return " ".join(shlex.quote(part) for part in (command or jotline_command()))


def quote_desktop_arg(value: str) -> str:
    if value and not any(character in DESKTOP_RESERVED or ord(character) < 32 for character in value):
        return value
    escaped = (value.replace("\\", "\\\\").replace("\"", "\\\"").replace("$", "\\$").replace("`", "\\`"))
    return f'"{escaped}"'


def desktop_exec(command: list[str]) -> str:
    return " ".join(quote_desktop_arg(part) for part in command)


def data_text(name: str) -> str:
    return files(DATA_PACKAGE).joinpath(name).read_text(encoding="utf-8")


def render_desktop_entry(command: list[str] | None = None) -> str:
    argv = command or jotline_command()
    template = data_text(DESKTOP_FILENAME)
    return (template.replace("__TRYEXEC__", argv[0])
            .replace("__EXEC__", desktop_exec([*argv, "desktop", "launch"])))


def render_recipe(name: str, command: list[str] | None = None) -> str:
    if name not in RECIPE_FILES:
        raise ValueError("Unknown recipe; use jotline desktop recipe "
                         + "|".join(RECIPE_NAMES))
    return data_text(RECIPE_FILES[name]).replace("__JOTLINE__", jotline_shell(command))


def clipboard_pipe(command: list[str] | None = None) -> str:
    prefix = jotline_shell(command)
    if sys.platform == "win32":
        return f'powershell -NoProfile -Command "Get-Clipboard" | {prefix} capture'
    if sys.platform == "darwin":
        return f"pbpaste | {prefix} capture"
    return f"wl-paste | {prefix} capture"


def existing_desktop_entry() -> Path | None:
    path = desktop_entry_path()
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if CAPTURE_MARKER not in body or "Name=Jotline Capture" not in body:
        return None
    return path


def status_report(command: list[str] | None = None) -> dict[str, object]:
    argv = command or jotline_command()
    installed = existing_desktop_entry()
    return {
        "platform": sys.platform,
        "supported": linux_desktop_available(),
        "installed": installed is not None,
        "path": str(installed) if installed else None,
        "applications": str(applications_dir()),
        "jotline": argv,
        "launch": [*argv, "desktop", "launch"],
        "recipes": list(RECIPE_NAMES),
        "pipe": clipboard_pipe(argv),
    }


def format_status(report: dict[str, object]) -> str:
    argv = report["jotline"]
    assert isinstance(argv, list)
    lines = []
    if not report["supported"]:
        lines.append(unsupported_message())
    elif report["installed"]:
        lines.append("Linux desktop capture is installed")
        lines.append("Launcher: " + str(report["path"]))
    else:
        lines.append("Linux desktop capture is not installed")
        lines.append("Install with: " + jotline_shell(argv) + " desktop install")
    lines.append("Jotline: " + jotline_shell(argv))
    lines.append("Bind a shortcut to: " + jotline_shell([*argv, "desktop", "launch"]))
    lines.append("Recipes: jotline desktop recipe " + "|".join(RECIPE_NAMES))
    lines.append("Clipboard: " + str(report["pipe"]))
    return "\n".join(lines) + "\n"


def _write_applications_file(body: str, *, replace: bool) -> Path:
    if len(body.encode("utf-8")) > MAX_SETTINGS_BYTES:
        raise ValueError("Desktop entry exceeds the size limit")
    path = desktop_entry_path()
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    exists = False
    try:
        info = path.lstat()
        exists = True
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Capture desktop entry path is a symlink; refuse to replace it")
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Capture desktop entry path is not a regular file")
        ours = CAPTURE_MARKER in path.read_text(encoding="utf-8")
        if not replace and not ours:
            raise ValueError(f"Capture desktop entry already exists: {path}; pass --force to replace it")
    except FileNotFoundError:
        exists = False
    directory = pin_ancestors(path)
    try:
        fd, temporary = create_private_temp(directory, ".desktop-")
        try:
            with fs.fdopen(fd, "wb") as stream:
                stream.write(body.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            if exists:
                replace_at(directory, temporary, path.name)
            else:
                publish_new(directory, temporary, path.name)
            fs.fsync(directory)
        finally:
            unlink_quietly(directory, temporary)
    finally:
        fs.close(directory)
    return path


def install_desktop_entry(*, force: bool = False, command: list[str] | None = None) -> Path:
    path = _write_applications_file(render_desktop_entry(command), replace=force)
    refresh_desktop_database(path.parent)
    return path


def uninstall_desktop_entry() -> Path:
    path = existing_desktop_entry()
    if path is None:
        target = desktop_entry_path()
        if target.exists() or target.is_symlink():
            raise ValueError(f"Refusing to remove {target}; it is not a Jotline capture desktop entry")
        raise ValueError("Capture desktop entry is not installed")
    directory = pin_ancestors(path)
    try:
        fs.unlink(path.name, dir_fd=directory)
    finally:
        fs.close(directory)
    refresh_desktop_database(path.parent)
    return path


def refresh_desktop_database(directory: Path) -> None:
    tool = shutil.which("update-desktop-database")
    if tool is None:
        return
    try:
        subprocess.run([tool, str(directory)], check=False, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return


def write_recipe(name: str, destination: Path, *, force: bool = False,
                 command: list[str] | None = None) -> Path:
    body = render_recipe(name, command)
    absolute = destination.expanduser()
    if not absolute.is_absolute():
        absolute = Path.cwd() / absolute
    if len(body.encode("utf-8")) > MAX_SETTINGS_BYTES:
        raise ValueError("Recipe exceeds the size limit")
    exists = False
    try:
        info = absolute.lstat()
        exists = True
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Recipe output is not a regular file: {absolute}")
        if not force:
            raise ValueError(f"Recipe output already exists: {absolute}; pass --force to replace it")
    except FileNotFoundError:
        exists = False
    absolute.parent.mkdir(parents=True, exist_ok=True)
    directory = pin_ancestors(absolute)
    try:
        fd, temporary = create_private_temp(directory, ".recipe-")
        try:
            with fs.fdopen(fd, "wb") as stream:
                stream.write(body.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            if exists:
                replace_at(directory, temporary, absolute.name)
            else:
                publish_new(directory, temporary, absolute.name)
            fs.fsync(directory)
        finally:
            unlink_quietly(directory, temporary)
    finally:
        fs.close(directory)
    return absolute


def capture_command(args) -> list[str]:
    command = [*jotline_command(), "--vault", str(Path(args.vault).expanduser())]
    if args.workspace:
        command.extend(["--workspace", args.workspace])
    command.append("capture")
    if getattr(args, "daily", False):
        command.append("--daily")
    return command


def terminal_argv(kind: str, binary: str, capture: list[str]) -> list[str]:
    builders = {
        "kitty": lambda: [binary, "--class", APP_ID, "-e", *capture],
        "alacritty": lambda: [binary, "--class", APP_ID, "-e", *capture],
        "foot": lambda: [binary, f"--app-id={APP_ID}", *capture],
        "ghostty": lambda: [binary, f"--class={APP_ID}", "-e", *capture],
        "wezterm": lambda: [binary, "start", "--class", APP_ID, "--", *capture],
        "gnome-terminal": lambda: [binary, f"--title={WINDOW_TITLE}", "--", *capture],
        "konsole": lambda: [binary, "--name", APP_ID, "-e", *capture],
        "ptyxis": lambda: [binary, "--new-window", "--", *capture],
        "kgx": lambda: [binary, "--", *capture],
        "xfce4-terminal": lambda: [binary, f"--class={APP_ID}", "-T", WINDOW_TITLE, "-e",
                                   " ".join(shlex.quote(part) for part in capture)],
        "xdg-terminal-exec": lambda: [binary, "--", *capture],
    }
    try:
        return builders[kind]()
    except KeyError as error:
        raise ValueError("Unknown terminal: " + kind) from error


def preferred_terminals(desktop: str) -> list[str]:
    names = list(TERMINAL_ORDER)
    lowered = desktop.casefold()
    if "hyprland" in lowered or "omarchy" in lowered:
        first = ("kitty", "foot", "alacritty", "ghostty", "wezterm", "xdg-terminal-exec")
    elif "gnome" in lowered:
        first = ("ptyxis", "kgx", "gnome-terminal", "xdg-terminal-exec")
    elif "kde" in lowered or "plasma" in lowered:
        first = ("konsole", "xdg-terminal-exec")
    else:
        first = ("xdg-terminal-exec",)
    return list(dict.fromkeys((*first, *names)))


def resolve_terminal(name: str) -> tuple[str, str] | None:
    binary = shutil.which(name)
    if binary is None:
        return None
    kind = Path(binary).name.lower()
    if kind.endswith(".exe"):
        kind = kind[:-4]
    if kind not in TERMINAL_ORDER:
        return None
    return kind, binary


def selected_terminal() -> tuple[str, str] | None:
    override = os.environ.get("JOTLINE_TERMINAL") or ""
    if override:
        path = Path(override).expanduser()
        name = path.name or override
        found = resolve_terminal(str(path) if path.is_absolute() else name)
        if found is None:
            raise ValueError("JOTLINE_TERMINAL must be one of: " + ", ".join(TERMINAL_ORDER))
        return found
    desktop = os.environ.get("XDG_CURRENT_DESKTOP") or ""
    for name in preferred_terminals(desktop):
        found = resolve_terminal(name)
        if found is not None:
            return found
    return None


@dataclass(frozen=True)
class LaunchPlan:
    mode: Literal["spawn", "exec"]
    argv: list[str]


def launch_plan(capture: list[str], *, in_terminal: bool) -> LaunchPlan:
    selected = selected_terminal()
    if selected is not None:
        kind, binary = selected
        return LaunchPlan("spawn", terminal_argv(kind, binary, capture))
    if in_terminal:
        return LaunchPlan("exec", capture)
    raise ValueError(
        "No terminal found to open jotline capture. Install a terminal, set "
        "JOTLINE_TERMINAL, run jotline desktop recipe, or pipe text: "
        + clipboard_pipe()
    )


def execute_launch(plan: LaunchPlan) -> None:
    if plan.mode == "spawn":
        subprocess.Popen(plan.argv, start_new_session=True, close_fds=True)
        return
    if plan.mode == "exec":
        os.execvp(plan.argv[0], plan.argv)
        return
    raise ValueError("Unknown launch mode: " + plan.mode)


def _require_linux() -> None:
    if not linux_desktop_available():
        raise ValueError(unsupported_message())


def run_desktop_command(args) -> None:
    action = args.action or "status"
    if action not in DESKTOP_ACTIONS:
        raise ValueError("Unknown desktop action: " + action)
    if args.recipe is not None and action != "recipe":
        raise ValueError("A recipe name is only used with: jotline desktop recipe NAME")
    if args.json and action != "status":
        raise ValueError("--json is only used with jotline desktop status")
    if args.output is not None and action != "recipe":
        raise ValueError("--output is only used with jotline desktop recipe")
    if args.daily and action != "launch":
        raise ValueError("--daily is only used with jotline desktop launch")
    if args.force and action not in {"install", "recipe"}:
        raise ValueError("--force is only used with install or recipe --output")
    if action == "status":
        report = status_report()
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            sys.stdout.write(format_status(report))
        return
    if action == "recipe":
        names = RECIPE_NAMES if args.recipe is None else (args.recipe,)
        if args.output is not None:
            if args.recipe is None:
                raise ValueError("Choose a recipe name when using --output")
            written = write_recipe(args.recipe, args.output, force=args.force)
            print(written)
            return
        if args.recipe is None:
            for name in names:
                print(name)
            return
        sys.stdout.write(render_recipe(args.recipe))
        return
    _require_linux()
    if action == "install":
        path = install_desktop_entry(force=args.force)
        print(path)
        return
    if action == "uninstall":
        print(uninstall_desktop_entry())
        return
    if action == "launch":
        execute_launch(launch_plan(capture_command(args), in_terminal=_stdin_is_tty()))
        return
    raise ValueError("Unknown desktop action: " + action)


def _stdin_is_tty() -> bool:
    try:
        return bool(sys.stdin and sys.stdin.isatty() and sys.stdout.isatty())
    except ValueError:
        return False
