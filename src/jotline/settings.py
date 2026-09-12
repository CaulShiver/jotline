"""Validated per-vault preferences, stored separately from notes."""
from dataclasses import asdict, dataclass, field, fields
import json
from .filesystem import fs as os
import re
from pathlib import Path
import weakref

from .store import (MAX_SETTINGS_BYTES, create_private_temp, read_regular_at,
                    read_regular_file, validate_workspace, vault_lock)

THEMES = ('jotline', 'nord', 'gruvbox', 'catppuccin-mocha', 'dracula', 'tokyo-night',
          'solarized-dark', 'solarized-light', 'textual-light')


HOTKEY_ACTIONS = {
    "new": ("ctrl+n", "New thought"),
    "tags": ("ctrl+t", "Browse tags"),
    "workspaces": ("ctrl+w", "Switch workspace"),
    "commands": ("ctrl+p", "Command palette"),
    "open_note": ("ctrl+o", "Open note"),
    "daily": ("ctrl+d", "Daily log"),
    "search": ("ctrl+f", "Search notes"),
    "save": ("ctrl+s", "Save note"),
    "focus_mode": ("ctrl+b", "Focus mode"),
    "quit": ("ctrl+q", "Quit"),
    "preview": ("", "Preview Markdown (optional)"),
    "format_bold": ("", "Format bold (optional)"),
    "format_italic": ("", "Format italic (optional)"),
    "format_code": ("", "Format code (optional)"),
    "format_heading": ("", "Format heading (optional)"),
    "format_list": ("", "Format bullet list (optional)"),
    "format_quote": ("", "Format quote (optional)"),
}
# Preserve editing controls and terminal aliases for Tab, Enter and Backspace.
RESERVED_HOTKEYS = {"ctrl+" + letter for letter in "acehijkmuvxyz"}

# Persistence metadata deliberately lives outside the dataclass so it never
# appears in asdict(), preferences controls, or the on-disk format.  Keeping a
# few value snapshots also lets dataclasses.replace() and Preferences' rebuild
# retain their nearest load baseline.
_BASELINES: dict[Path, list[tuple[dict, dict | None]]] = {}
_OBJECT_BASELINES: dict[int, tuple[weakref.ReferenceType, tuple[dict, dict | None]]] = {}


def _settings_values(settings: "Settings") -> dict:
    return asdict(settings)


def _remember(path: Path, settings: "Settings", disk: dict | None) -> None:
    values = _settings_values(settings)
    key = path.absolute()
    entries = _BASELINES.setdefault(key, [])
    entry = (values, disk)
    entries.append(entry)
    del entries[:-16]
    identity = id(settings)
    _OBJECT_BASELINES[identity] = (weakref.ref(
        settings, lambda reference, identity=identity: _OBJECT_BASELINES.pop(identity, None)), entry)


def _nearest_baseline(path: Path, settings: "Settings", desired: dict) -> tuple[dict, dict | None] | object:
    missing = _NO_BASELINE
    exact = _OBJECT_BASELINES.get(id(settings))
    if exact is not None and exact[0]() is settings:
        return exact[1]
    entries = _BASELINES.get(path.absolute(), [])
    if entries and any(values == desired for values, _ in entries[:-1]) and entries[-1][0] != desired:
        # A rebuilt dataclass that exactly returns to an older saved value is a
        # normal explicit reversion; compare it with the most recent baseline.
        return entries[-1]
    best: tuple[int, dict | None] | None = None
    best_entry = None
    for entry in entries:
        values, disk = entry
        distance = sum(values.get(key) != value for key, value in desired.items())
        if best is None or distance < best[0]:
            best = (distance, disk)
            best_entry = entry
    return missing if best_entry is None else best_entry


_NO_BASELINE = object()


@dataclass
class Settings:
    theme: str = 'jotline'
    line_numbers: bool = False
    soft_wrap: bool = True
    highlight_line: bool = True
    focus_on_start: bool = False
    show_hints: bool = True
    sidebar_width: int = 32
    autosave_seconds: float = 0.7
    sort_order: str = 'updated'
    startup: str = 'new'
    default_collection: str = 'inbox'
    daily_template: str = '# {{date}}\n\n'

    active_workspace: str = "default"
    workspace_names: list[str] = field(default_factory=lambda: ["default"])

    hotkeys: dict[str, str] = field(default_factory=dict)

    @property
    def effective_hotkeys(self) -> dict[str, str]:
        return {action: self.hotkeys.get(action, default).strip().lower()
                for action, (default, _) in HOTKEY_ACTIONS.items()}

    def validate(self):
        if not isinstance(self.hotkeys, dict) or set(self.hotkeys) - HOTKEY_ACTIONS.keys():
            raise ValueError("Hotkeys must map known Jotline actions to keys")
        if any(not isinstance(key, str) for key in self.hotkeys.values()):
            raise ValueError("Each hotkey must be text")
        used = {}
        for action, key in self.effective_hotkeys.items():
            label = HOTKEY_ACTIONS[action][1]
            # New Markdown actions start unassigned to preserve existing maps.
            if not key and not HOTKEY_ACTIONS[action][0]:
                continue
            if not re.fullmatch(r"(?:ctrl|alt)\+[a-z]|f(?:[2-9]|1[0-2])", key):
                raise ValueError(f"{label}: use ctrl+letter, alt+letter, or f2–f12; F1 and Esc stay fixed")
            if key in RESERVED_HOTKEYS:
                raise ValueError(f"{key} is reserved for editing or terminal navigation")
            if key in used:
                raise ValueError(f"{key} is assigned to both {used[key]} and {label}")
            used[key] = label

        validate_workspace(self.active_workspace)
        if not isinstance(self.workspace_names, list) or len(self.workspace_names) > 256:
            raise ValueError("At most 256 workspace names may be saved")
        for name in self.workspace_names:
            validate_workspace(name)
        for name in ('line_numbers', 'soft_wrap', 'highlight_line', 'focus_on_start', 'show_hints'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be true or false')
        if self.theme not in THEMES:
            raise ValueError('Unknown theme')
        if type(self.sidebar_width) is not int or not 22 <= self.sidebar_width <= 60:
            raise ValueError('Sidebar width must be 22–60 columns')
        if type(self.autosave_seconds) not in (int, float) or not 0.2 <= self.autosave_seconds <= 5:
            raise ValueError('Autosave interval must be 0.2–5 seconds')
        if self.sort_order not in ('updated', 'created', 'title'):
            raise ValueError('Unknown sort order')
        if self.startup not in ('new', 'daily'):
            raise ValueError('Unknown startup page')
        if self.default_collection not in ('inbox', 'projects', 'areas', 'resources'):
            raise ValueError('Unknown default collection')
        if not isinstance(self.daily_template, str) or len(self.daily_template) > 20000:
            raise ValueError('Daily template must be text under 20,000 characters')
        self.daily_template.encode('utf-8')

    @classmethod
    def load(cls, path: Path):
        try:
            data = json.loads(read_regular_file(path, MAX_SETTINGS_BYTES))
            if not isinstance(data, dict):
                raise ValueError('Settings must be an object')
            known = {f.name for f in fields(cls)}
            settings = cls(**{k: v for k, v in data.items() if k in known})
            settings.validate()
            _remember(path, settings, data)
            return settings, ''
        except FileNotFoundError:
            settings = cls()
            _remember(path, settings, {})
            return settings, ''
        except (ValueError, TypeError, OSError, RecursionError) as error:
            settings = cls()
            _remember(path, settings, None)
            return settings, f'Could not load settings; using defaults. {error}'

    def save(self, path: Path):
        self.validate()
        with vault_lock(path.parent) as directory:
            current = None
            try:
                raw = read_regular_at(directory, path.name, MAX_SETTINGS_BYTES)
                current = json.loads(raw)
                if not isinstance(current, dict):
                    current = None
            except FileNotFoundError:
                pass
            except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
                # The bounded reader has already established that the target is
                # a regular file. Explicit save may repair malformed or oversized
                # regular settings, while links and special files still fail.
                pass
            desired = _settings_values(self)
            baseline = _nearest_baseline(path, self, desired)
            if current is not None and baseline is not _NO_BASELINE and baseline[1] is not None:
                merged = dict(current)
                defaults = _settings_values(Settings())
                for key, value in desired.items():
                    old = baseline[0].get(key, defaults[key])
                    if value != old:
                        merged[key] = value
                # Validate the effective known settings before publication.
                known = {field.name for field in fields(Settings)}
                effective = Settings(**{key: value for key, value in merged.items() if key in known})
                effective.validate()
                desired = _settings_values(effective)
                output = {**merged, **desired}
            else:
                output = desired
            self._save_locked(path, output, directory)
            _remember(path, self, output)

    def _save_locked(self, path: Path, data: dict | None = None, directory: int | None = None):
        if directory is None:
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            own_directory = True
        else:
            own_directory = False
        try:
            fd, temp = create_private_temp(directory, '.settings-')
        except BaseException:
            if own_directory:
                os.close(directory)
            raise
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
                json.dump(_settings_values(self) if data is None else data, stream, indent=2, ensure_ascii=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path.name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temp, dir_fd=directory)
            except FileNotFoundError:
                pass
            if own_directory:
                os.close(directory)
