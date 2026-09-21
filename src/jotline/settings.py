"""Validated per-vault preferences, stored separately from notes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import json
from pathlib import Path
import re

from .actions import validate_actions
from .filesystem import (
    create_private_temp, fs as os, read_regular_at, read_regular_file, replace_at,
    unlink_quietly, vault_lock,
)
from .history import stamp
from .limits import MAX_SETTINGS_BYTES
from .search import compile_query
from .store import COLLECTIONS, validate_workspace


THEMES = ('jotline', 'nord', 'gruvbox', 'catppuccin-mocha', 'dracula', 'tokyo-night',
          'solarized-dark', 'solarized-light', 'textual-light',
          'monokai', 'flexoki', 'catppuccin-latte', 'catppuccin-frappe',
          'catppuccin-macchiato', 'rose-pine', 'rose-pine-moon', 'rose-pine-dawn',
          'ansi-dark', 'ansi-light', 'atom-one-dark', 'atom-one-light', 'textual-dark', 'omarchy')
SORT_ORDERS = ('updated', 'created', 'title')
# What a view or the sidebar can show; new thoughts can only land somewhere not archived.
VIEW_COLLECTIONS = ('all', 'starred', *COLLECTIONS)
DEFAULT_COLLECTIONS = ('inbox', 'projects', 'areas', 'resources')
BOOLEAN_SETTINGS = ('line_numbers', 'soft_wrap', 'highlight_line', 'markdown_highlighting', 'smart_lists',
                    'focus_on_start', 'show_hints', 'outliner_on_start')


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
    "live_preview": ("", "Side-by-side preview (optional)"),
    "outline": ("", "Jump to heading (optional)"),
    "outliner": ("", "Open outliner (optional)"),
    "daily_previous": ("", "Previous daily log (optional)"),
    "daily_next": ("", "Next daily log (optional)"),
    "daily_date": ("", "Open daily log by date (optional)"),
    "extract_note": ("", "Extract selection to new note (optional)"),
    "process_inbox": ("", "Process next inbox note (optional)"),
    "external_editor": ("", "Edit this note in $EDITOR (optional)"),
    "backlinks": ("alt+k", "Show connections"),
    "format_strike": ("", "Format strikethrough (optional)"),
    "format_numbered": ("", "Format numbered list (optional)"),
    "format_task": ("", "Format task list (optional)"),
    "format_codeblock": ("", "Format code block (optional)"),
    "format_link": ("", "Insert link (optional)"),
    "format_image": ("", "Insert image (optional)"),
    "format_table": ("", "Insert or tidy table (optional)"),
    "format_rule": ("", "Insert horizontal rule (optional)"),
    "format_indent": ("", "Indent lines (optional)"),
    "format_outdent": ("", "Outdent lines (optional)"),
}
# Preserve editing controls and terminal aliases for Tab, Enter and Backspace.
RESERVED_HOTKEYS = {"ctrl+" + letter for letter in "acehijkmuvxyz"}


@dataclass(frozen=True)
class SavedView:
    workspace: str
    query: str
    collection: str
    sort: str
    theme: str

    def __getitem__(self, key: str):
        if key not in {"workspace", "query", "collection", "sort", "theme"}:
            raise KeyError(key)
        return getattr(self, key)

    @classmethod
    def from_raw(cls, value: SavedView | dict) -> SavedView:
        if isinstance(value, SavedView):
            return value
        if not isinstance(value, dict) or set(value) != {"workspace", "query", "collection", "sort", "theme"}:
            raise ValueError("Invalid saved view")
        return cls(**value)


@dataclass(frozen=True)
class ActionStep:
    type: str
    value: str | None = None

    def to_dict(self) -> dict:
        payload = {"type": self.type}
        if self.value is not None:
            payload["value"] = self.value
        return payload

    @classmethod
    def from_raw(cls, value: ActionStep | dict) -> ActionStep:
        if isinstance(value, ActionStep):
            return value
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            raise ValueError("Unknown action step")
        extra = set(value) - {"type", "value"}
        if extra:
            raise ValueError("Invalid action step fields")
        return cls(value["type"], value["value"] if "value" in value else None)


def action_dicts(actions: dict) -> dict[str, list[dict]]:
    return {name: [step.to_dict() if isinstance(step, ActionStep) else dict(step) for step in steps]
            for name, steps in actions.items()}


@dataclass
class Settings:
    theme: str = 'jotline'
    line_numbers: bool = False
    soft_wrap: bool = True
    highlight_line: bool = True
    markdown_highlighting: bool = True
    smart_lists: bool = True
    focus_on_start: bool = False
    show_hints: bool = True
    outliner_on_start: bool = False
    outline_hotkeys: dict[str, str] = field(default_factory=dict)
    sidebar_width: int = 32
    autosave_seconds: float = 0.7
    sort_order: str = 'updated'
    startup: str = 'new'
    default_collection: str = 'inbox'
    daily_template: str = '# {{date}}\n\n'

    active_workspace: str = "default"
    workspace_names: list[str] = field(default_factory=lambda: ["default"])

    hotkeys: dict[str, str] = field(default_factory=dict)
    saved_views: dict[str, SavedView] = field(default_factory=dict)
    actions: dict[str, list[ActionStep]] = field(default_factory=dict)
    # Last known published values for this instance. Copied by dataclasses.replace
    # and Preferences rebuild so concurrent saves merge without a process-global table.
    _baseline: dict | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        views = {}
        for name, view in dict(self.saved_views).items():
            try:
                views[name] = view if isinstance(view, SavedView) else SavedView.from_raw(view)
            except (TypeError, ValueError):
                views[name] = view
        self.saved_views = views
        steps = {}
        for name, raw_steps in dict(self.actions).items():
            converted = []
            try:
                for step in raw_steps:
                    converted.append(step if isinstance(step, ActionStep) else ActionStep.from_raw(step))
            except (TypeError, ValueError):
                converted = list(raw_steps)
            steps[name] = converted
        self.actions = steps

    @property
    def effective_hotkeys(self) -> dict[str, str]:
        return {action: self.hotkeys.get(action, default).strip().lower()
                for action, (default, _) in HOTKEY_ACTIONS.items()}

    def values(self) -> dict:
        data = {}
        for item in fields(self):
            if item.name == "_baseline":
                continue
            value = getattr(self, item.name)
            if item.name == "saved_views":
                data[item.name] = {name: asdict(view) if isinstance(view, SavedView) else view
                                   for name, view in value.items()}
            elif item.name == "actions":
                data[item.name] = action_dicts(value)
            else:
                data[item.name] = value
        return data

    def validate(self):
        validate_actions(action_dicts(self.actions))
        if not isinstance(self.saved_views, dict) or len(self.saved_views) > 128:
            raise ValueError("At most 128 saved views are allowed")
        for name, view in self.saved_views.items():
            validate_workspace(name)
            view = SavedView.from_raw(view)
            validate_workspace(view.workspace)
            if not isinstance(view.query, str) or len(view.query) > 2000:
                raise ValueError("View query must be text under 2,000 characters")
            compile_query(view.query)
            if view.collection not in VIEW_COLLECTIONS:
                raise ValueError("Invalid view collection")
            if view.sort not in SORT_ORDERS or view.theme not in (*THEMES, ''):
                raise ValueError("Invalid view sort or theme")

        if not isinstance(self.hotkeys, dict) or set(self.hotkeys) - HOTKEY_ACTIONS.keys():
            raise ValueError("Hotkeys must map known Jotline actions to keys")
        if any(not isinstance(key, str) for key in self.hotkeys.values()):
            raise ValueError("Each hotkey must be text")
        from .outliner_ui import ACTIONS
        if not isinstance(self.outline_hotkeys, dict) or set(self.outline_hotkeys) - ACTIONS.keys():
            raise ValueError("Outline shortcuts must name known outline commands")
        outline_used = set()
        for key in self.outline_hotkeys.values():
            if not isinstance(key, str) or not re.fullmatch(r"(?:ctrl|alt)\+[a-z]|f(?:[2-9]|1[0-2])", key):
                raise ValueError("Outline shortcuts use ctrl+letter, alt+letter, or f2–f12")
            if key in RESERVED_HOTKEYS or key in outline_used or key in self.effective_hotkeys.values():
                raise ValueError("Outline shortcut is reserved or assigned more than once")
            outline_used.add(key)
        used = {}
        for action, key in self.effective_hotkeys.items():
            label = HOTKEY_ACTIONS[action][1]
            # New Markdown actions start unassigned to preserve existing maps.
            if not key and not HOTKEY_ACTIONS[action][0]:
                continue
            if not re.fullmatch(r"(?:ctrl|alt)\+[a-z]|f(?:[2-9]|1[0-2])", key):
                raise ValueError(f"{label}: use ctrl+letter, alt+letter, or f2–f12; Ctrl+, and Esc stay fixed")
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
        for name in BOOLEAN_SETTINGS:
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be true or false')
        if self.theme not in THEMES:
            raise ValueError('Unknown theme')
        if type(self.sidebar_width) is not int or not 22 <= self.sidebar_width <= 60:
            raise ValueError('Sidebar width must be 22–60 columns')
        if type(self.autosave_seconds) not in (int, float) or not 0.2 <= self.autosave_seconds <= 5:
            raise ValueError('Autosave interval must be 0.2–5 seconds')
        if self.sort_order not in SORT_ORDERS:
            raise ValueError('Unknown sort order')
        if self.startup not in ('new', 'daily'):
            raise ValueError('Unknown startup page')
        if self.default_collection not in DEFAULT_COLLECTIONS:
            raise ValueError('Unknown default collection')
        if not isinstance(self.daily_template, str) or len(self.daily_template) > 20000:
            raise ValueError('Daily template must be text under 20,000 characters')
        self.daily_template.encode('utf-8')
        payload = self.values()
        if len((json.dumps(payload, indent=2, ensure_ascii=False) + '\n').encode('utf-8')) > MAX_SETTINGS_BYTES:
            raise ValueError('Settings exceed the file size limit')

    @classmethod
    def _partial(cls, data: dict) -> tuple[Settings, list[str]]:
        """Keep every field that validates alongside the others; name the rest."""
        kept: dict = {}
        rejected = []
        known = {item.name for item in fields(cls) if item.name != "_baseline"}
        for name in known:
            if name not in data:
                continue
            trial = {**kept, name: data[name]}
            try:
                cls(**trial).validate()
            except (ValueError, TypeError, RecursionError):
                rejected.append(name)
            else:
                kept = trial
        return cls(**kept), rejected

    @classmethod
    def load(cls, path: Path):
        data = None
        try:
            data = json.loads(read_regular_file(path, MAX_SETTINGS_BYTES))
            if not isinstance(data, dict):
                raise ValueError('Settings must be an object')
            known = {item.name for item in fields(cls) if item.name != "_baseline"}
            settings = cls(**{k: v for k, v in data.items() if k in known})
            settings.validate()
            settings._baseline = settings.values()
            return settings, ''
        except FileNotFoundError:
            settings = cls()
            settings._baseline = settings.values()
            return settings, ''
        except (ValueError, TypeError, OSError, RecursionError) as error:
            if isinstance(data, dict):
                # One bad value must not discard every other preference, and
                # the next save must not rewrite the file from defaults.
                settings, rejected = cls._partial(data)
                if rejected:
                    settings._baseline = settings.values()
                    return settings, (f'Could not load settings field(s) {", ".join(rejected)}; '
                                      f'using defaults for them. {error}')
            settings = cls()
            settings._baseline = None
            return settings, f'Could not load settings; using defaults. {error}'

    def save(self, path: Path):
        self.validate()
        with vault_lock(path.parent) as directory:
            current = None
            unreadable = False
            try:
                raw = read_regular_at(directory, path.name, MAX_SETTINGS_BYTES)
                current = json.loads(raw)
                if not isinstance(current, dict):
                    current = None
                    unreadable = True
            except FileNotFoundError:
                pass
            except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
                # The bounded reader has already established that the target is
                # a regular file. Explicit save may repair malformed or oversized
                # regular settings, while links and special files still fail.
                unreadable = True
            if unreadable:
                # Never overwrite bytes that could not be understood; keep them
                # next to the fresh file so nothing hand-written is lost.
                replace_at(directory, path.name, f'{path.name}.invalid-{stamp()}.json')
            desired = self.values()
            baseline = self._baseline
            if current is not None and baseline is not None:
                merged = dict(current)
                defaults = Settings().values()
                # Values that failed validation on disk are replaced, never merged.
                _, rejected = Settings._partial(current)
                for key, value in desired.items():
                    old = baseline.get(key, defaults[key])
                    if value != old or key in rejected:
                        merged[key] = value
                # Validate the effective known settings before publication.
                known = {item.name for item in fields(Settings) if item.name != "_baseline"}
                effective = Settings(**{key: value for key, value in merged.items() if key in known})
                effective.validate()
                desired = effective.values()
                output = {**merged, **desired}
            else:
                output = desired
            self._save_locked(path, output, directory)
            self._baseline = {key: output[key] for key in desired}

    def _save_locked(self, path: Path, data: dict | None = None, directory: int | None = None):
        output = json.dumps(self.values() if data is None else data, indent=2, ensure_ascii=False) + '\n'
        if len(output.encode('utf-8')) > MAX_SETTINGS_BYTES:
            raise ValueError('Settings exceed the file size limit')
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
                stream.write(output)
                stream.flush()
                os.fsync(stream.fileno())
            replace_at(directory, temp, path.name)
            os.fsync(directory)
        finally:
            unlink_quietly(directory, temp)
            if own_directory:
                os.close(directory)
