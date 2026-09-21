"""Keyboard-first writing UI. No shell commands are executed by the palette."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, timedelta
import re
import subprocess
from time import monotonic
from typing import NamedTuple

from textual import events, on
from textual.geometry import Size
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Markdown, OptionList, Static, TextArea
from textual.widgets.option_list import Option
from rich.text import Text

from . import clipboard
from .accessibility import A11Y_NOTES, COPY_NATIVE, COPY_REQUEST
from .action_ui import ActionWorkflows
from .cli_doctor import doctor_report, format_doctor
from .commands import Command
from .connect_ui import Connections, ConnectionsBar
from .encryption_ui import Encryption
from .environment import child_environment
from .external_editor import ENCRYPTED, NO_EDITOR, UNSAVED, configured_editor
from .import_ui import RecoveryImport
from .links import wiki_link_at, wiki_target_from_href
from .markdown_editor import JOTLINE_THEME, MarkdownEditor
from .modal import Palette, TextPrompt
from .navigation import Views, Walkthrough
from .note_menu import NoteList, NoteMenu
from .omarchy import OmarchySync
from .outliner_ui import OutlinerScreen
from .preferences import Preferences
from .recovery_ui import HealthScreen
from .review_ui import Review
from .screens import FindInNote, MarkdownPreview, RevisionPreview
from .search import Match, parse_query, rank, sought
from .settings import HOTKEY_ACTIONS, Settings, VIEW_COLLECTIONS
from .store import (COLLECTIONS, EDIT_LIMIT_BYTES, ConflictError, Note, Vault, daily_date_from_id,
                    is_daily_id, parse_calendar_date, tagged_body, validate_workspace)
from .sync import sync_guide
from .templates import GUIDE, REVIEW, TEMPLATE_ENCRYPTED, Templates
from .terminal import terminal_text
from .workflows import Workflows

class Row(NamedTuple):
    """One line of the note list, and everything that decides how it is drawn.

    Compared whole to tell a redraw from a refresh that changes nothing, so the
    marked spans belong in it: the same quoted line can be marked differently
    as a query grows.
    """
    id: str
    text: str
    marks: tuple[tuple[int, int], ...]


__all__ = ["Command", "FindInNote", "Jotline", "MarkdownPreview", "Palette", "RevisionPreview", "TextPrompt"]

# How long the status line may reuse the previous whole-note scan while typing.
STATUS_SUMMARY_SECONDS = 0.25

# How long the note list waits for a pause in typing before it rebuilds. Rebuilding
# measures the height of every row, so a burst of keys pays for one pass, not one per key.
SEARCH_DEBOUNCE_SECONDS = 0.2


def _bind_capabilities(target, *sources):
    """Copy public methods and constants onto the app class without mixin inheritance or MRO."""
    original = set(target.__dict__)
    bound: dict[str, type] = {}
    for source in sources:
        for name, value in source.__dict__.items():
            if name.startswith("_") or name in original:
                continue
            if not (callable(value) or isinstance(value, (int, float, str, bytes, tuple, frozenset))):
                continue
            if name in bound:
                raise RuntimeError(f"{name} is defined on both {bound[name].__name__} and {source.__name__}")
            bound[name] = source
            setattr(target, name, value)


class Jotline(App):
    TITLE = "jotline"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: $background; color: $foreground; }
    Tooltip { visibility: hidden; }
    #brand { height: 3; padding: 1 2 0 2; color: $accent; text-style: bold; }
    #workspace { height: 1fr; }
    #sidebar { width: 32; min-width: 22; border-right: solid $primary-muted; padding: 0 1; }
    #collection { height: 2; padding-left: 1; color: $text-muted; }
    .navigation-row { height: 1; }
    .navigation-row Button { height: 1; min-height: 1; min-width: 0; width: 1fr; padding: 0; border: none; }
    #empty-notes { height: auto; max-height: 5; color: $text-muted; }
    #search { margin-bottom: 1; border: tall $primary-muted; background: $surface; }
    #notes { border: none; background: $background; height: 1fr; }
    #notes > .option-list--option-highlighted { background: $primary-muted; color: $foreground; }
    #writing { width: 1fr; padding: 0 2; }
    #note-heading { height: 2; color: $accent; }
    #markdown-toolbar { height: 2; scrollbar-size-horizontal: 1; background: $surface; }
    #markdown-toolbar Button { height: 1; min-height: 1; min-width: 0; width: auto;
                               padding: 0 1; border: none; background: $surface; color: $foreground; }
    #markdown-toolbar Button:hover, #markdown-toolbar Button:focus { background: $primary-muted; color: $accent; text-style: bold; }
    #editor { height: 1fr; border: none; background: $background; }
    #live-preview { width: 1fr; border-left: solid $primary-muted; padding: 0 2; }
    #status { height: 2; padding-top: 1; color: $text-muted; }
    #connections { height: auto; max-height: 5; padding-top: 1; color: $text-muted; }
    #hint { height: 2; padding: 0 2; color: $text-muted; }
    Footer { background: $surface; }
    .hidden { display: none; }
    .compact-footer { display: none; }
    """
    BINDINGS = [Binding(key or "jotline_" + action + "_unassigned",
                        "format_markdown(" + repr(action[7:]) + ")" if action.startswith("format_") else action,
                        label, priority=True, show=bool(key), id="jotline." + action)
                for action, (key, label) in HOTKEY_ACTIONS.items()] + [
        Binding("ctrl+comma,f1", "settings", "Settings", priority=True),
        Binding("escape", "editor_focus", "Write", show=False),
    ]

    def __init__(self, vault: Vault, workspace: str | None = None, initial_note: Note | None = None):
        super().__init__()
        self.vault = vault
        self.initial_note = initial_note
        self.settings_path = vault.path / '.jotline-settings.json'
        self.settings, self.settings_warning = Settings.load(self.settings_path)
        self.workspace = validate_workspace(self.settings.active_workspace if workspace is None else workspace)
        self.register_theme(JOTLINE_THEME)
        self.omarchy_sync = OmarchySync(self)
        self.current = self.new_note()
        self.collection = self.settings.default_collection
        self.dirty = False
        self.last_error = ""
        self.focused_writing = False
        self.compact_layout = False
        self.compact_navigation = False
        self._shown_storage_warnings: set[str] = set()
        self._recovery_dialog_open = False
        self._status_message = "Ready"
        self._note_summary: tuple[str, str, int, list[str]] | None = None
        self._note_summary_at = 0.0
        self._note_summary_timer = None
        self._search_timer = None
        self._listed_query: str | None = None
        self._listed_rows: list[Row] | None = None
        self.inbox_capture_count = 0
        self.recent_note_ids = []
        self.note_positions = {}
        self._editor_baseline = ""
        self.view_sort = None
        self.active_view = None
        self.live_preview = False
        self._live_preview_timer = None
        self._live_preview_text: str | None = None
        self._live_preview_ratio: float | None = None
        self._live_preview_lock = asyncio.Lock()
        self._live_preview_cursor_row: int | None = None
        self._link_notes = None
        self._link_workspace = ""
        self._incoming = []
        self._incoming_for = ""
        self.command_registry = self.build_command_registry()

    def editor(self) -> MarkdownEditor:
        return self.query_one("#editor", MarkdownEditor)

    def compose(self) -> ComposeResult:
        yield Static("›_ jotline     /     " + self.workspace, id="brand", markup=False)
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                with Horizontal(classes="navigation-row"):
                    yield Button("Collections", id="nav-collections")
                    yield Button("Views", id="nav-views")
                with Horizontal(classes="navigation-row"):
                    yield Button("Filters", id="nav-filters")
                    yield Button("Quick start", id="nav-help")
                with Horizontal(classes="navigation-row"):
                    yield Button("Format", id="nav-format")
                    yield Button("Actions", id="nav-actions")
                with Horizontal(classes="navigation-row"):
                    yield Button("Import", id="nav-import")
                yield Static("INBOX", id="collection", markup=False)
                yield Input(placeholder="Search words or #tags", id="search",
                            tooltip="Search this workspace by words or #tags")
                yield Static("", id="empty-notes", markup=False)
                notes = NoteList(id="notes")
                notes.tooltip = "Notes in the current collection"
                yield notes
            with Vertical(id="writing"):
                yield Static(terminal_text(self.current.title) + " / " + self.current.collection,
                             id="note-heading")
                with HorizontalScroll(id="markdown-toolbar"):
                    for style, label, hint in (
                        ("bold", "Bold", "Toggle **bold** on selected text"),
                        ("italic", "Italic", "Toggle *italic* on selected text"),
                        ("heading", "H", "Toggle a heading on the current or selected lines"),
                        ("list", "List", "Toggle a bullet list"),
                        ("task", "Task", "Toggle a checkbox list"),
                        ("link", "Link", "Insert a Markdown link"),
                        ("code", "Code", "Toggle inline code"),
                    ):
                        yield Button(label, id="md-" + style, classes="markdown-format", tooltip=hint)
                    yield Button("More", id="md-more", tooltip="All Markdown formats, including tables and code blocks")
                    yield Button("Preview", id="md-preview", tooltip="Preview Markdown; Esc returns to writing")
                    yield Button("Outliner", id="md-outliner", tooltip="Edit collapsible blocks and move whole branches")
                editor = MarkdownEditor("", soft_wrap=True, tab_behavior="indent", show_line_numbers=False, id="editor")
                editor.indent_width = 2
                editor.tooltip = "Note editor. Start typing to capture. Text saves automatically."
                yield editor
                connections = ConnectionsBar("", id="connections", markup=False)
                connections.tooltip = "Incoming and outgoing note links"
                yield connections
                status = Static("Ready · local Markdown", id="status", markup=False)
                status.tooltip = "Save status, word count, and collection"
                yield status
            with VerticalScroll(id="live-preview", classes="hidden"):
                yield Markdown("", open_links=False, id="live-markdown")
        yield Static("Capture first. Make sense of it later.   ctrl+p commands · ctrl+d daily log", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self.apply_settings(startup=True)
        self.omarchy_sync.start()
        self.update_responsive_layout()
        self.refresh_notes()
        self.status("Ready")
        self.autosave_timer = self.set_interval(self.settings.autosave_seconds, self.autosave)
        if self.initial_note is not None:
            self.collection = self.initial_note.collection
            self.load(self.initial_note)
            self.refresh_notes()
        elif self.settings.startup == 'daily':
            self.action_daily()
        if self.settings_warning:
            self.notify(self.settings_warning, severity='warning', timeout=10)
        self.editor().focus()
        self.notify_storage_warnings()
        if self.settings.outliner_on_start:
            self.call_after_refresh(self.action_outliner)

    def on_resize(self, event: events.Resize) -> None:
        self.update_responsive_layout(event.size)

    def update_responsive_layout(self, size: Size | None = None) -> None:
        size = size or self.size
        self.compact_layout = size.width <= 80 or size.height <= 24
        very_short = size.height <= 24
        sidebar = self.query_one("#sidebar")
        hint = self.query_one("#hint", Static)
        connections = self.query_one("#connections", Static)
        sidebar.set_class(self.focused_writing or (self.compact_layout and not self.compact_navigation), "hidden")
        hint.set_class(self.focused_writing or self.compact_layout or not self.settings.show_hints, "hidden")
        connections.set_class(very_short, "hidden")
        self.query_one("#markdown-toolbar").set_class(self.focused_writing, "hidden")
        preview = self.query_one("#live-preview")
        was_visible = not preview.has_class("hidden")
        preview.set_class(not self.live_preview_visible, "hidden")
        self.query_one(Footer).set_class(very_short, "compact-footer")
        if self.live_preview_visible and not was_visible:
            self.refresh_live_preview()
        elif not self.live_preview_visible and self._live_preview_timer is not None:
            self._live_preview_timer.stop()
            self._live_preview_timer = None

    @property
    def live_preview_visible(self) -> bool:
        return self.live_preview and not self.compact_layout

    def storage_warnings(self) -> list[str]:
        return list(dict.fromkeys(message for message in self.vault.warnings if message))

    def notify_storage_warnings(self) -> None:
        for warning in self.storage_warnings():
            if warning not in self._shown_storage_warnings:
                self.notify("Storage warning: " + warning, severity="warning", timeout=10)
                self._shown_storage_warnings.add(warning)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if isinstance(self.screen, OutlinerScreen) and action in {'commands', 'open_note', 'daily', 'daily_previous', 'daily_next', 'new', 'quit', 'settings', 'format_markdown', 'save'}:
            return True
        if isinstance(self.screen, ModalScreen) and action not in {'focus_next', 'focus_previous'}:
            return False
        return super().check_action(action, parameters)

    def apply_settings(self, *, startup: bool = False) -> None:
        settings = self.settings
        self.set_keymap({"jotline." + action: key or "jotline_" + action + "_unassigned"
                         for action, key in settings.effective_hotkeys.items()})
        self.query_one('#hint', Static).update(self.shortcut_text(
            "Capture first. Make sense of it later.   ctrl+p commands · ctrl+d daily log"))
        self.theme = settings.theme
        editor = self.editor()
        editor.soft_wrap = settings.soft_wrap
        editor.show_line_numbers = settings.line_numbers
        editor.highlight_cursor_line = settings.highlight_line
        editor.set_markdown_options(highlighting=settings.markdown_highlighting, smart_lists=settings.smart_lists)
        self.query_one('#sidebar').styles.width = settings.sidebar_width
        self.set_focus_mode(settings.focus_on_start if startup else self.focused_writing)

    def shortcut_text(self, text: str) -> str:
        effective = self.settings.effective_hotkeys
        keys = {default: effective[action] for action, (default, _) in HOTKEY_ACTIONS.items()}
        return re.sub(r"ctrl\+[a-z]", lambda match: keys.get(match[0].lower(), match[0]), text, flags=re.I)

    def action_settings(self) -> None:
        self.push_screen(Preferences(self.settings), self.save_settings)

    def replace_settings(self, **changes):
        settings = replace(self.settings, **changes)
        settings.save(self.settings_path)
        self.settings = settings
        return settings

    def delete_config(self, field, name):
        try:
            values = dict(getattr(self.settings, field))
            values.pop(name, None)
            self.replace_settings(**{field: values})
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')

    def save_settings(self, settings: Settings | None) -> None:
        if settings is None:
            return
        try:
            settings.save(self.settings_path)
        except (OSError, ValueError) as error:
            self.notify(f'Settings were not saved: {error}', severity='error', timeout=10)
            return
        self.settings = settings
        self.apply_settings()
        self.autosave_timer.stop()
        self.autosave_timer = self.set_interval(settings.autosave_seconds, self.autosave)
        self.refresh_notes()
        self.connections()
        self.editor().focus()
        self.notify('Settings saved. Startup choices apply next launch.')

    @staticmethod
    def note_matches(notes: list[Note], query: str) -> dict[str, Match]:
        """Why each note matched, keyed by note id.

        Empty when the query has no words in it. A bare `#tag` or date filter
        matches every result equally well, so there is nothing to rank and no
        line worth quoting back.
        """
        try:
            terms = parse_query(query)
        except ValueError:
            return {}
        if not sought(terms):
            return {}
        return {note.id: found for note in notes if (found := rank(note, terms)) is not None}

    @staticmethod
    def note_row(note: Note, found: Match | None) -> Row:
        """A note as the list draws it: title, then when and where.

        While a search is running a third line quotes the matched text, so the
        list says why a note is in it rather than only that it is. Without a
        query the row stays two lines, which is what fits an 80x24 terminal.
        """
        text = (("★ " if note.starred else "") + ("🔒 " if note.encrypted else "") + terminal_text(note.title)
                + "\n  " + (note.updated[:10] or "imported") + " · " + note.collection)
        if found is None or not found.line:
            return Row(note.id, text, ())
        lead = len(text) + 3  # The newline and the two spaces before the quote.
        return Row(note.id, text + "\n  " + found.line,
                   tuple((lead + start, lead + stop) for start, stop in found.offsets))

    @staticmethod
    def marked_row(row: Row) -> Text:
        """The row as Rich text, with the matched words in bold."""
        marked = Text(row.text)
        for start, stop in row.marks:
            marked.stylize("bold", start, stop)
        return marked

    def refresh_notes(self) -> None:
        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None
        snapshot = self.vault.notes()
        self.inbox_capture_count = len(self.vault.inbox_captures(self.workspace, notes=snapshot))
        self.status(self._status_message)
        self._listed_query = query = self.query_one("#search", Input).value
        try:
            notes = self.vault.search(query, self.collection, self.workspace, notes=snapshot)
        except ValueError as error:
            self.query_one("#collection", Static).update(str(error))
            self.query_one("#notes", OptionList).clear_options()
            self._listed_rows = None
            self.query_one("#empty-notes", Static).update("Fix the search above, or use Filters to change it.")
            self.query_one("#empty-notes").remove_class("hidden")
            return
        order = self.view_sort or self.settings.sort_order
        if order == 'title':
            notes.sort(key=lambda n: (not n.starred, n.title.casefold(), n.id))
        elif order == 'created':
            notes.sort(key=lambda n: (n.starred, n.created, n.id), reverse=True)
        matches = self.note_matches(notes, query)
        if matches:
            # Sorting is stable, so the configured order above still decides
            # between notes the query matched equally well.
            notes.sort(key=lambda n: -matches[n.id].score)
        listing = self.query_one("#notes", OptionList)
        rows = [self.note_row(note, matches.get(note.id)) for note in notes]
        # Rebuilding measures and wraps every row, and a save or a filter that leaves the
        # same rows on screen is common, so redraw only when the rows themselves changed.
        # The marked spans are part of a row: the same line can be highlighted
        # differently as the query grows, and that is a redraw.
        if rows != self._listed_rows:
            self._listed_rows = rows
            listing.clear_options()
            listing.add_options([Option(self.marked_row(row), id=row.id) for row in rows])
        listing.highlighted = next((index for index, note in enumerate(notes)
                                    if note.id == self.current.id), None)
        label = f"{self.collection.upper()} / {len(notes)}"
        if self.active_view and self.active_view in self.settings.saved_views:
            view = self.settings.saved_views[self.active_view]
            current = self.current_view()
            matches = all(current[k] == view[k] for k in current if k != 'theme') and self.theme == (view['theme'] or self.settings.theme)
            label += f" · {self.active_view}" + (" (modified)" if not matches else "")
        self.query_one("#collection", Static).update(label)
        empty = self.query_one("#empty-notes", Static)
        empty.set_class(bool(notes), "hidden")
        empty.update(self.empty_notes_message())
        brand = f"›_ jotline / {self.workspace}"
        if not self.compact_layout:
            brand += "     ·     ctrl+w workspaces · ctrl+t tags"
        self.query_one("#brand", Static).update(self.shortcut_text(brand))
        self.connections(notes=snapshot)
        self.notify_storage_warnings()

    def empty_notes_message(self) -> str:
        query = self.query_one("#search", Input).value
        compact = self.compact_layout
        if query:
            return self.shortcut_text(
                "No matches. Change the search or Filters."
                if compact else
                "No matches. Adjust search or use Filters; Clear view and search resets filters.")
        collection = self.collection
        if collection == "inbox":
            text = "Inbox is empty. Keep typing — this page is already a note."
            if not compact:
                text += " Ctrl+N starts another."
        elif collection == "trash":
            text = "Trash is empty."
            if not compact:
                text += " Deleted notes land here until you restore them."
        elif collection == "starred":
            text = "No starred notes."
            if not compact:
                text += " Star one from Ctrl+P."
        elif collection == "all":
            text = "Nothing in this vault yet. Type to capture."
        elif collection in {"projects", "areas", "resources", "archive"}:
            text = f"No {collection} notes yet."
            if not compact:
                text += f" Move one here from Ctrl+P → Move note to {collection}."
        else:
            text = "Nothing here yet. Ctrl+N captures a new note."
        return self.shortcut_text(text)

    @on(Button.Pressed, "#nav-collections")
    def navigation_collections(self):
        self.browse_collections()

    @on(Button.Pressed, "#nav-views")
    def navigation_views(self):
        self.push_screen(Palette([('views', 'Open saved view'), ('save-view', 'Save current filters'),
                                  ('manage-views', 'Edit, rename or duplicate views'),
                                  ('clear-view', 'Clear view and search')], 'Saved views'), self.command)

    @on(Button.Pressed, "#nav-filters")
    def navigation_filters(self):
        self.edit_filters()

    @on(Button.Pressed, "#nav-help")
    def navigation_help(self):
        self.show_walkthrough()

    @on(Button.Pressed, "#nav-actions")
    def navigation_actions(self):
        self.push_screen(Palette([
            ('actions', 'Run a saved action'), ('action-recipes', 'Start from a recipe'),
            ('action-builder', 'Build an action'), ('manage-actions', 'Edit or share an action'),
            ('import-actions', 'Import recipes'), ('action-history', 'Action history'),
        ], 'Actions'), self.command)

    @on(Button.Pressed, "#nav-format")
    @on(Button.Pressed, "#md-more")
    def navigation_format(self):
        choices = [(command.key, command.label.removeprefix("Format "))
                   for command in self.command_registry.values()
                   if command.key.startswith("format:")]
        self.push_screen(Palette(choices, "Format Markdown"), self.command)

    @on(Button.Pressed, ".markdown-format")
    def toolbar_format(self, event: Button.Pressed) -> None:
        self.action_format_markdown(event.button.id.removeprefix("md-"))

    @on(Button.Pressed, "#md-preview")
    def toolbar_preview(self) -> None:
        self.action_preview()

    @on(Button.Pressed, "#md-outliner")
    def action_outliner(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        self.push_screen(OutlinerScreen(self.editor()))

    @on(Button.Pressed, "#nav-import")
    def navigation_import(self):
        self.import_library()

    @on(Input.Changed, "#search")
    def search_changed(self) -> None:
        """Rebuild the note list once typing pauses, not on every key."""
        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None
        if self.query_one("#search", Input).value == self._listed_query:
            # Code that sets the box and refreshes itself gets its Changed event afterwards.
            return
        self._search_timer = self.set_timer(SEARCH_DEBOUNCE_SECONDS, self.refresh_notes)

    @on(OptionList.OptionSelected, "#notes")
    def note_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.load_id(event.option.id)

    @on(NoteList.ContextRequested)
    def note_context_requested(self, event: NoteList.ContextRequested) -> None:
        event.stop()
        try:
            note = self.vault.read(event.note_id)
            if note.workspace != self.workspace:
                raise ValueError('Note moved to another workspace; refresh the vault')
        except (OSError, ValueError) as error:
            self.notify(str(error), severity='error')
            return
        choices = [('move', 'Move to collection…')]
        if not is_daily_id(note.id):
            choices.append(('workspace', 'Move to workspace…'))
        choices.append(('restore', 'Restore to Inbox') if note.collection == 'trash'
                       else ('trash', 'Delete · Move to Trash'))
        self.push_screen(NoteMenu(note.title, choices, event.x, event.y),
                         lambda action: self.note_context_action(note, action, event.x, event.y))

    def note_context_action(self, note: Note, action: str | None, x: int, y: int) -> None:
        if action in ('trash', 'restore'):
            self.move_context_note(note, collection='trash' if action == 'trash' else 'inbox')
        elif action == 'move':
            choices = [(name, name.title()) for name in COLLECTIONS if name not in ('trash', note.collection)]
            self.push_screen(NoteMenu('Move to collection', choices, x, y),
                             lambda value: self.move_context_note(note, collection=value) if value else None)
        elif action == 'workspace':
            choices = [(name, name) for name in self.workspace_names() if name != self.workspace]
            if not choices:
                self.notify('Create another workspace with Ctrl+W first')
                return
            self.push_screen(NoteMenu('Move to workspace', choices, x, y),
                             lambda value: self.move_context_note(note, workspace=value) if value else None)

    def move_context_note(self, note: Note, *, collection: str | None = None,
                          workspace: str | None = None) -> None:
        if not self.save_current():
            return
        is_current = note.id == self.current.id
        moved = replace(self.current if is_current else note)
        try:
            if moved.workspace != self.workspace:
                raise ValueError('Note moved to another workspace; refresh the vault')
            if collection is not None:
                if collection not in COLLECTIONS:
                    raise ValueError('Unknown collection')
                moved.collection = collection
            if workspace is not None:
                validate_workspace(workspace)
                if is_daily_id(moved.id):
                    raise ValueError('Daily logs belong to their workspace; copy their text into a regular note to move it')
                moved.workspace = workspace
            self.vault.save(moved)
        except (OSError, ValueError) as error:
            self.notify(f'Note was not moved: {error}', severity='error', timeout=10)
            return
        if is_current:
            gone = moved.workspace != self.workspace or moved.collection == 'trash'
            self.load(self.new_note() if gone else moved)
        self.refresh_notes()
        self.notify_backup_warning()
        self.notify(f'Moved to {workspace or collection}')

    @on(TextArea.Changed, "#editor")
    def edited(self) -> None:
        if self.is_running:
            if self.capture_current_buffer():
                self.offer_completion()
                self.connections()
            self.schedule_live_preview()

    @on(TextArea.SelectionChanged, "#editor")
    def cursor_moved(self, event: TextArea.SelectionChanged) -> None:
        row = event.selection.end[0]
        if row != self._live_preview_cursor_row:
            self._live_preview_cursor_row = row
            self.schedule_live_preview()

    def capture_current_buffer(self) -> bool:
        body = self.editor().text
        if body == self._editor_baseline:
            return False
        self.current.body = body
        self._editor_baseline = body
        self.dirty = True
        self.status("Saving…")
        return True

    def note_summary(self) -> tuple[int, list[str]]:
        """Word count and leading tags for the status line.

        Both scan the whole note, and the status line is rewritten on every
        keystroke, so a long note spent more time counting words than editing.
        Reuse the last scan during a burst of typing and catch up once it ends.
        """
        body = self.current.body
        cached = self._note_summary
        if cached is not None and cached[0] is body and cached[1] == self.current.id:
            return cached[2], cached[3]
        now = monotonic()
        if (cached is not None and cached[1] == self.current.id
                and now - self._note_summary_at < STATUS_SUMMARY_SECONDS):
            if self._note_summary_timer is None:
                self._note_summary_timer = self.set_timer(STATUS_SUMMARY_SECONDS, self.refresh_status)
            return cached[2], cached[3]
        summary = (len(body.split()), sorted(self.current.tags)[:5])
        self._note_summary = (body, self.current.id, *summary)
        self._note_summary_at = now
        return summary

    def refresh_status(self) -> None:
        self._note_summary_timer = None
        self._note_summary_at = 0.0
        if self.is_running:
            self.status(self._status_message)

    def status(self, message: str) -> None:
        self._status_message = message
        words, tags = self.note_summary()
        details = f"{message}  ·  {words} words"
        if self.inbox_capture_count:
            details += f"  ·  {self.inbox_capture_count} inbox"
        if self.compact_layout:
            details += f"  ·  {self.connection_counts()}"
        else:
            details += f"  ·  {self.current.collection}  ·  {self.workspace}"
            details += "  ·  encrypted" if self.current.encrypted else ""
            details += "  ·  " + " ".join("#" + tag for tag in tags) if tags else ""

        self.query_one("#status", Static).update(details)
        self.query_one("#note-heading", Static).update(
            Text(terminal_text(self.current.title) + " / " + self.current.collection))

    def save_current(self, *, explicit: bool = False) -> bool:
        # An inline Changed message may still be queued when a navigation or
        # save command runs, including callbacks from a palette above it.
        for screen in reversed(self.screen_stack):
            if isinstance(screen, OutlinerScreen) and screen.note_id == self.current.id:
                if not screen.flush():
                    return False
                break
        self.capture_current_buffer()
        if not self.dirty:
            return True
        try:
            self.vault.save(self.current)
        except (OSError, ValueError) as error:
            conflict = isinstance(error, ConflictError)
            guidance = ("Your on-screen draft is safe. Open Commands → Save recovery copy, then Refresh vault "
                        "to review the external version.") if conflict else str(error)
            message = "NOT SAVED · " + ("External change detected" if conflict else str(error))
            self.status(message)
            if guidance != self.last_error or explicit:
                self.notify(guidance, severity="error", timeout=12)
                self.last_error = guidance
                if conflict and not isinstance(self.screen, ModalScreen):
                    self.show_recovery_dialog()
            return False
        self.dirty, self.last_error = False, ""
        self.status("Saved")
        self.notify_backup_warning()
        self.notify_storage_warnings()
        self.refresh_notes()
        return True

    def autosave(self) -> None:
        if self.is_running and self.dirty:
            self.save_current()

    def new_note(self, body: str = "") -> Note:
        note = self.vault.new(body, workspace=self.workspace)
        note.collection = self.settings.default_collection
        return note

    def load(self, note: Note) -> None:
        outline_screen = self.screen if isinstance(self.screen, OutlinerScreen) else None
        if outline_screen:
            if not outline_screen.flush():
                return
            outline_screen.persist_state()
        if note.workspace != self.workspace:
            raise ValueError("Note moved to another workspace; save a recovery copy if needed")
        editor = self.editor()
        self.note_positions[self.current.id] = editor.cursor_location
        if self.current.original is not None and self.current.id != note.id:
            self.recent_note_ids = [self.current.id] + [key for key in self.recent_note_ids if key != self.current.id]
            self.recent_note_ids = self.recent_note_ids[:50]
        self.current, self.dirty, self.last_error = note, False, ""
        editor.load_text(note.body)
        self._editor_baseline = editor.text
        editor.move_cursor(self.note_positions.get(note.id, (0, 0)))
        editor.focus()
        self.status("Saved" if note.original is not None else "Ready")
        self.connections()
        if outline_screen:
            outline_screen.update_save_status()
        elif self.settings.outliner_on_start and not isinstance(self.screen, ModalScreen):
            self.call_after_refresh(self.action_outliner)

    def load_id(self, note_id: str) -> None:
        if not self.save_current(explicit=True):
            return
        if note_id == self.current.id and self.current.original is not None:
            self.editor().focus()
            return
        try:
            note = self.vault.read(note_id)
            if note.locked:
                self.prompt_unlock(then=lambda: self.load_id(note_id))
                return
            self.load(note)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")

    def action_external_editor(self) -> None:
        """Save, hand the file to $EDITOR, then read back whatever came home."""
        command = configured_editor()
        if not command:
            self.notify(NO_EDITOR, severity="warning", timeout=12)
            return
        if self.current.encrypted:
            self.notify(ENCRYPTED, severity="warning", timeout=12)
            return
        if not self.save_current(explicit=True):
            return
        note_id = self.current.id
        path = self.vault.file(note_id)
        if not path.exists():
            self.notify(UNSAVED, severity="warning", timeout=8)
            return
        if problem := self.hand_to_editor(command, path):
            self.notify(problem, severity="error", timeout=12)
            return
        self.reload_external_edit(note_id)

    def hand_to_editor(self, command: list[str], path) -> str:
        """Give the terminal to the editor until it exits. Empty means it ran.

        Suspending needs a terminal to hand over; a driver without one raises
        rather than leaving the editor drawing into a screen Jotline still
        owns, and that has to be reported instead of looking like a note that
        came back unchanged.
        """
        try:
            with self.suspend():
                subprocess.run([*command, str(path)], check=False, env=child_environment())
        except SuspendNotSupported:
            return ("This terminal cannot hand itself to another program, so "
                    f"{command[0]} was not started.")
        except OSError as error:
            return f"{command[0]} did not start: {error}"
        return ""

    def reload_external_edit(self, note_id: str) -> None:
        """Take the file back after an external editor had it.

        Anything could have happened to it out there, including a broken header
        or a delete, so a failure here has to say so rather than leave a stale
        note on screen looking saved.
        """
        try:
            note = self.vault.read(note_id)
        except FileNotFoundError:
            self.notify("That note is no longer on disk. Nothing was reloaded.", severity="error", timeout=12)
            return
        except (OSError, ValueError) as error:
            self.notify(f"The note could not be read back: {error}", severity="error", timeout=15)
            return
        if note.locked:
            self.prompt_unlock(then=lambda: self.reload_external_edit(note_id))
            return
        try:
            self.load(note)
        except ValueError as error:
            self.notify(str(error), severity="error", timeout=12)
            return
        self.refresh_notes()
        self.notify("Reloaded from disk.")

    def action_new(self) -> None:
        if self.save_current(explicit=True):
            note = self.new_note()
            self.collection = note.collection
            self.load(note)
            self.refresh_notes()

    def action_daily(self) -> None:
        self.open_daily(date.today())

    def action_daily_previous(self) -> None:
        self.open_daily((daily_date_from_id(self.current.id) or date.today()) - timedelta(days=1))

    def action_daily_next(self) -> None:
        self.open_daily((daily_date_from_id(self.current.id) or date.today()) + timedelta(days=1))

    def action_daily_date(self) -> None:
        self.push_screen(TextPrompt("Open daily log by date", "YYYY-MM-DD, today, or yesterday"),
                         self.open_daily_from_prompt)

    def open_daily_from_prompt(self, value: str | None) -> None:
        if not value:
            return
        try:
            self.open_daily(parse_calendar_date(value))
        except ValueError as error:
            self.notify(str(error), severity="error")

    def open_daily(self, when: date) -> None:
        if not self.save_current(explicit=True):
            return
        try:
            note = self.vault.daily(self.settings.daily_template, self.workspace, when=when)
        except (OSError, ValueError) as error:
            self.notify(f"Could not open the {when.isoformat()} daily log: {error}", severity="error", timeout=10)
            return
        self.collection = note.collection
        self.load(note)
        self.refresh_notes()
        editor = self.editor()
        editor.move_cursor(editor.document.end)

    def action_search(self) -> None:
        self.collection = "all"
        self.set_focus_mode(False)
        self.refresh_notes()
        self.show_navigation("search")

    def action_editor_focus(self) -> None:
        self.compact_navigation = False
        self.update_responsive_layout()
        self.editor().focus()

    def action_save(self) -> None:
        if isinstance(self.screen, OutlinerScreen):
            self.screen.action_save()
            return
        self.save_current(explicit=True)

    def action_quit(self) -> None:
        if isinstance(self.screen, OutlinerScreen):
            if not self.screen.flush():
                return
            self.screen.persist_state()
        if self.save_current(explicit=True):
            self.exit()

    def action_focus_mode(self) -> None:
        self.set_focus_mode(not self.focused_writing)
        self.editor().focus()

    def set_focus_mode(self, enabled: bool) -> None:
        self.focused_writing = enabled
        if enabled:
            self.compact_navigation = False
        self.update_responsive_layout()

    def show_navigation(self, target: str = "notes") -> None:
        self.compact_navigation = True
        self.update_responsive_layout()
        self.query_one("#" + target).focus()

    def action_open_note(self) -> None:
        notes = self.vault.search(workspace=self.workspace)
        self.push_screen(Palette(self.note_choices(notes), "Open a note"),
                         lambda key: self.load_id(key) if key else None)

    @staticmethod
    def note_excerpt(note: Note) -> str:
        lines = [line.strip().lstrip("# ") for line in note.body.splitlines() if line.strip()]
        excerpt = next((line for line in lines if line != note.title), "")
        return re.sub(r"\s+", " ", excerpt)[:44]

    def note_choices(self, notes: list[Note]) -> list[tuple[str, str]]:
        titles: dict[str, int] = {}
        for note in notes:
            title = note.title.casefold()
            titles[title] = titles.get(title, 0) + 1
        choices = []
        for note in notes:
            label = note.title
            if titles[note.title.casefold()] > 1:
                context = [note.collection, note.updated[:10] or "imported"]
                if excerpt := self.note_excerpt(note):
                    context.append(excerpt)
                context.append("ID " + note.id[:8])
                label += " · " + " · ".join(context)
            else:
                label += " · " + note.collection
            choices.append((note.id, label))
        return choices

    def workspace_names(self) -> list[str]:
        return sorted(self.vault.workspaces() | set(self.settings.workspace_names) | {self.workspace})

    def action_workspaces(self) -> None:
        self.push_screen(Palette([(name, name + (" · current" if name == self.workspace else ""))
                                  for name in self.workspace_names()] + [("+", "Create workspace…")],
                                 "Switch workspace"), self.pick_workspace)

    def pick_workspace(self, name: str | None) -> None:
        if name == "+":
            self.command("new-workspace")
        else:
            self.switch_workspace(name)

    def switch_workspace(self, name: str | None) -> None:
        if not name:
            return
        try:
            name = validate_workspace(name)
            if not self.save_current(explicit=True):
                return
            self.replace_settings(active_workspace=name,
                                  workspace_names=sorted(set(self.settings.workspace_names) | {name}))
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")
            return
        self.workspace = name
        self.active_view = None
        self.view_sort = None
        self.theme = self.settings.theme
        self.collection = self.settings.default_collection
        self.query_one("#search", Input).value = ""
        self.load(self.new_note())
        self.status("Ready")
        self.refresh_notes()
        self.set_focus_mode(False)

    def move_workspace(self, name: str | None) -> None:
        if name:
            self.move_context_note(self.current, workspace=name)

    def action_tags(self) -> None:
        if not self.save_current():
            return
        counts = self.vault.tags(self.workspace)
        self.push_screen(Palette([(tag, f"#{tag} · {count} notes") for tag, count in sorted(counts.items())]
                                 + [("+", "Add tags to this note…")], "Tags in " + self.workspace), self.pick_tag)

    def pick_tag(self, tag: str | None) -> None:
        if tag == "+":
            self.command("add-tags")
        elif tag:
            self.collection = "all"
            self.query_one("#search", Input).value = "#" + tag
            self.refresh_notes()
            self.set_focus_mode(False)
            self.show_navigation()

    def add_tags(self, tags: str | None) -> None:
        if not tags:
            return
        editor = self.editor()
        try:
            body = tagged_body(editor.text, tags)
        except ValueError as error:
            self.notify(str(error), severity="error")
            return
        if len(body.encode("utf-8")) > EDIT_LIMIT_BYTES:
            self.notify("Result exceeds the note size limit", severity="error")
            return
        editor.insert(body[len(editor.text):], editor.document.end)
        self.save_current()
        editor.focus()

    def action_templates(self, source: bool = False) -> None:
        try:
            names = Templates(self.vault.path).names()
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")
            return
        self.push_screen(Palette([(name, name) for name in names],
                                 "Copy template source" if source else "New note from template"),
                         lambda name: self.use_template(name, source=source))

    def use_template(self, name: str | None, *, source: bool = False) -> None:
        if not name or not self.save_current():
            return
        try:
            templates = Templates(self.vault.path)
            body = templates.read(name) if source else templates.render(name, self.workspace)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")
            return
        note = self.new_note(body)
        self.collection = note.collection
        self.query_one("#search", Input).value = ""
        self.load(note)
        self.dirty = True
        self.save_current()

    def save_template(self, name: str | None) -> None:
        if not name:
            return
        if self.current.encrypted:
            # Templates are never encrypted, and the daily backup archives
            # .jotline-templates as well, so this would put the decrypted note
            # on disk in the clear and then into a retained ZIP.
            self.notify(TEMPLATE_ENCRYPTED, severity="warning", timeout=12)
            return
        try:
            Templates(self.vault.path).save(name, self.editor().text)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")
            return
        self.notify("Template saved locally. Use New note from template to reuse it.")

    def notify_backup_warning(self) -> None:
        if self.vault.backup_warning:
            self.notify(self.vault.backup_warning, severity="warning", timeout=10)
            self.vault.backup_warning = ""

    def action_backup(self) -> None:
        if not self.save_current():
            return
        try:
            path = self.vault.backup()
        except (OSError, ValueError) as error:
            self.notify(f"Backup failed: {error}", severity="error", timeout=10)
            return
        self.notify(f"Backup saved: {path}", timeout=10)
        self.notify_backup_warning()

    def browse_history(self) -> None:
        try:
            notes = self.vault.history_notes(self.workspace)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")
            return
        if not notes:
            self.notify("No saved history in this workspace yet.")
            return
        self.push_screen(Palette(self.note_choices(notes), "Saved note history"), self.show_history)

    def show_history(self, note_id: str | None) -> None:
        if not note_id:
            return
        try:
            revisions = self.vault.history(note_id)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")
            return
        if not revisions:
            self.notify("No saved versions for this note yet.")
            return
        self.push_screen(Palette([(r.id, r.saved_at) for r in revisions], "Choose a saved version"),
                         lambda revision_id: self.preview_revision(note_id, revision_id))

    def preview_revision(self, note_id: str, revision_id: str | None) -> None:
        if not revision_id:
            return
        try:
            note = self.vault.read_revision(note_id, revision_id)
            if note.locked:
                raise ValueError("This version is encrypted; unlock encrypted notes to view it")
            if note.workspace != self.workspace:
                raise ValueError("This version belongs to another workspace; switch workspaces to view it")
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")
            return
        self.push_screen(RevisionPreview(note), lambda restore: self.restore_revision(note) if restore else None)

    def restore_revision(self, note: Note) -> None:
        if note.workspace != self.workspace or not self.save_current():
            return
        try:
            restored = self.vault.recovery(note)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")
            return
        self.collection = "inbox"
        self.query_one("#search", Input).value = ""
        self.load(restored)
        self.refresh_notes()
        self.notify("Saved version restored as a new inbox note.")

    def editing_surface(self) -> MarkdownEditor:
        """Text commands target the visible editor; saving uses editor()."""
        if isinstance(self.screen, OutlinerScreen):
            return self.screen.block_editor()
        return self.editor()

    def action_format_markdown(self, style: str) -> None:
        if isinstance(self.screen, OutlinerScreen):
            self.screen.block_editor().apply_format(style)
            self.screen.flush()
            self.screen.action_edit_block()
            return
        editor = self.editor()
        result = editor.apply_format(style)
        if result == "tidied":
            self.notify("Table tidied.")
        self.capture_current_buffer()
        editor.focus()
        self.call_after_refresh(editor.focus)

    def select_editor_match(self, query: str, *, reverse: bool = False,
                            anchor: int | None = None, case_sensitive: bool = False) -> tuple[int, int] | None:
        return self.editor().select_match(query, reverse=reverse, anchor=anchor, case_sensitive=case_sensitive)

    def refresh_vault(self) -> None:
        self.vault.invalidate_cache()
        self.capture_current_buffer()
        kept_unsaved = self.dirty
        reload_failed = False
        if not kept_unsaved and self.current.original is not None:
            try:
                self.load(self.vault.read(self.current.id))
            except FileNotFoundError:
                self.dirty = kept_unsaved = reload_failed = True
                self.status("File removed outside Jotline · recovery available")
            except (OSError, ValueError) as error:
                self.dirty = kept_unsaved = reload_failed = True
                self.status("Could not reload file · recovery available")
                self.notify(f"Could not reload this note: {error}", severity="error", timeout=10)
        self.refresh_notes()
        if kept_unsaved and not reload_failed:
            self.status("Refreshed · unsaved changes kept")
        if not self.storage_warnings() and not reload_failed:
            self.notify("Vault refreshed from disk.")

    def action_commands(self) -> None:
        if isinstance(self.screen, OutlinerScreen):
            self.screen.action_commands()
            return
        everyday = frozenset(command.key for command in self.command_registry.values()
                             if command.group == "everyday")
        self.push_screen(Palette(self.command_choices(), "Run a command", everyday=everyday), self.command)

    def build_command_registry(self) -> dict[str, Command]:
        commands = [
            Command("outliner", "Outliner · edit collapsible blocks and branches", self.action_outliner,
                    "outliner", group="everyday"),
            Command("templates", "New note from template", self.action_templates),
            Command("save-template", "Save this note as a template", self.prompt_save_template),
            Command("template-source", "Copy template source to new note", lambda: self.action_templates(source=True)),
            Command("history", "History of this note", lambda: self.show_history(self.current.id),
                    group="everyday"),
            Command("browse-history", "Browse saved note history", self.browse_history),
            Command("backup", "Back up vault now", self.action_backup, group="everyday"),
            Command("doctor", "Check vault health", self.action_doctor, group="everyday"),
            Command("recoveries", "Open a recovery copy", self.action_recoveries, group="everyday"),
            Command("preview", "Preview rendered Markdown", self.action_preview, "preview", group="everyday"),
            Command("live-preview", "Toggle side-by-side Markdown preview", self.action_live_preview, "live_preview"),
            Command("outline", "Jump to heading", self.action_outline, "outline"),
            Command("tags", "Browse tags", self.action_tags, "tags", group="everyday"),
            Command("add-tags", "Add tags to this note", self.prompt_add_tags),
            Command("workspaces", "Switch workspace", self.action_workspaces, "workspaces", group="everyday"),
            Command("new-workspace", "Create workspace", self.prompt_new_workspace),
            Command("move-workspace", "Move note to workspace", self.prompt_move_workspace),
            Command("settings", "Settings · appearance, editor, hotkeys · Ctrl+,", self.action_settings,
                    group="everyday"),
            Command("new", "New thought", self.action_new, "new", group="everyday"),
            Command("daily", "Open today's daily log", self.action_daily, "daily", group="everyday"),
            Command("daily-previous", "Previous daily log", self.action_daily_previous, "daily_previous"),
            Command("daily-next", "Next daily log", self.action_daily_next, "daily_next"),
            Command("daily-date", "Open daily log by date", self.action_daily_date, "daily_date"),
            Command("open", "Open a note", self.action_open_note, "open_note", group="everyday"),
            Command("focus", "Toggle focus mode", self.action_focus_mode, "focus_mode", group="everyday"),
            Command("find", "Find within current note", lambda: self.push_screen(FindInNote()),
                    group="everyday"),
            Command("refresh", "Refresh vault from disk", self.refresh_vault, group="everyday"),
            Command("star", "Toggle star on this note", self.toggle_star, group="everyday"),
            Command("task", "Toggle task on current line", self.toggle_task, group="everyday"),
            Command("copy", "Copy note to the clipboard", self.copy_current_note,
                    group="everyday"),
            Command("accessibility", "Clipboard, IME, and screen-reader notes", self.show_accessibility_notes),
            Command("external-editor", "Edit this note in $EDITOR", self.action_external_editor,
                    "external_editor"),
            Command("recovery", "Save recovery copy", self.save_recovery_copy, group="everyday"),
            Command("sync-recipe", "How to sync this vault with Git or Syncthing", self.show_sync_guide,
                    group="everyday"),
            Command("review", "Start weekly review", lambda: self.open_generated_note(REVIEW),
                    group="everyday"),
            Command("help", "Open writing and workflow guide", lambda: self.open_generated_note(GUIDE),
                    group="everyday"),
        ]
        commands.extend(Command("format:" + style, "Format " + label,
                                lambda style=style: self.action_format_markdown(style), "format_" + style)
                        for style, label in (("bold", "bold"), ("italic", "italic"), ("strike", "strikethrough"),
                                             ("code", "inline code"), ("heading", "heading"),
                                             ("list", "bullet list"), ("numbered", "numbered list"),
                                             ("task", "task list"), ("quote", "blockquote"),
                                             ("codeblock", "code block"), ("link", "link"), ("image", "image"),
                                             ("table", "table · insert or tidy"), ("rule", "horizontal rule"),
                                             ("indent", "indent lines"), ("outdent", "outdent lines")))
        commands.extend(Command(f"format:h{level}", f"Format heading level {level}",
                                lambda level=level: self.action_format_markdown(f"h{level}"))
                        for level in range(1, 7))
        commands.extend(Command("view:" + collection, "Show " + collection,
                                lambda collection=collection: self.show_collection(collection))
                        for collection in VIEW_COLLECTIONS)
        commands.extend(Command("move:" + collection, "Move note to " + collection,
                                lambda collection=collection: self.move_to_collection(collection))
                        for collection in COLLECTIONS)
        commands.extend(self.workflow_commands(Command))
        commands.extend(self.navigation_commands(Command))
        commands.extend(self.recipe_commands(Command))
        commands.extend(self.review_commands(Command))
        commands.extend(self.encryption_commands(Command))
        commands.extend(self.connect_commands(Command))
        commands.extend([
            Command('resolve-conflict', 'Review external change and recover draft', self.show_recovery_dialog),
            Command('import-library', 'Import notes from file, folder or Drafts export', self.import_library),
        ])
        return {command.key: command for command in commands}

    def command_choices(self) -> list[tuple[str, str]]:
        hotkeys = self.settings.effective_hotkeys
        choices = []
        for command in self.command_registry.values():
            label = self.shortcut_text(command.label)
            if command.hotkey_action and (key := hotkeys.get(command.hotkey_action)):
                label += " · " + key
            choices.append((command.key, label))
        return choices

    def command(self, key: str | None) -> None:
        if command := self.command_registry.get(key or ""):
            command.handler()

    def prompt_save_template(self) -> None:
        self.push_screen(TextPrompt("Save a new template", "e.g. weekly-planning; placeholders: {{date}}, {{time}}, {{workspace}}"),
                         self.save_template)

    def prompt_add_tags(self) -> None:
        self.push_screen(TextPrompt("Add tags to this note", "#work #ideas or project/topic"), self.add_tags)

    def prompt_new_workspace(self) -> None:
        self.push_screen(TextPrompt("Create a workspace", "e.g. personal, work, research"), self.switch_workspace)

    def prompt_move_workspace(self) -> None:
        self.push_screen(Palette([(name, name) for name in self.workspace_names() if name != self.workspace],
                                 "Move note to workspace"), self.move_workspace)

    def show_collection(self, collection: str) -> None:
        self.active_view = None
        self.collection = collection
        self.query_one("#search", Input).value = ""
        self.refresh_notes()
        self.set_focus_mode(False)
        self.show_navigation()

    def move_to_collection(self, collection: str) -> None:
        filing = (self.current.collection == "inbox" and not is_daily_id(self.current.id)
                  and collection != "inbox")
        if self.save_current():
            self.current.collection = collection
            self.dirty = True
            if self.save_current() and filing:
                self.open_next_inbox_capture()

    def toggle_star(self) -> None:
        if self.save_current():
            self.current.starred = not self.current.starred
            self.dirty = True
            self.save_current()

    def show_accessibility_notes(self) -> None:
        self.push_screen(Walkthrough(self.shortcut_text(A11Y_NOTES)))

    def copy_note_text(self, text: str) -> None:
        self.copy_to_clipboard(text)
        if clipboard.write_system_clipboard(text):
            self.notify(COPY_NATIVE)
        else:
            self.notify(COPY_REQUEST)

    def copy_current_note(self) -> None:
        self.copy_note_text(self.editor().text)

    def toggle_task(self) -> None:
        self.editor().toggle_task_line()
        self.capture_current_buffer()

    def show_sync_guide(self) -> None:
        self.push_screen(Walkthrough(self.shortcut_text(sync_guide(self.vault.path))))

    def save_recovery_copy(self) -> None:
        self.capture_current_buffer()
        try:
            self.load(self.vault.recovery(self.current))
            self.refresh_notes()
            self.notify("Saved a separate recovery copy in the inbox. Open a recovery copy lists them later.")
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")

    def action_doctor(self) -> None:
        report = doctor_report(self.vault, self.settings_warning)
        warnings = report["warnings"]
        body = format_doctor(report)
        if warnings:
            body += "\n\n" + "\n".join(warnings)
        self.push_screen(HealthScreen(body))

    def action_recoveries(self) -> None:
        copies = [note for note in self.vault.recoveries() if note.workspace == self.workspace]
        if not copies:
            self.notify("No recovery copies yet. They appear after an external change or Save recovery copy.")
            return

        def picked(note_id: str | None) -> None:
            if note_id:
                self.load_id(note_id)

        self.push_screen(Palette(self.note_choices(copies), "Recovery copies"), picked)

    @on(Markdown.LinkClicked, "#live-markdown")
    def follow_live_preview_link(self, event: Markdown.LinkClicked) -> None:
        event.stop()
        if target := wiki_target_from_href(event.href):
            self.follow_wiki_target(target)

    @on(events.Click, "#editor")
    def follow_editor_click(self, event: events.Click) -> None:
        if not event.ctrl:
            return
        editor = self.editor()
        if link := wiki_link_at(editor.text, *editor.cursor_location):
            event.stop()
            self.follow_wiki_target(link.target)

    def open_generated_note(self, body: str) -> None:
        if self.save_current():
            self.load(self.vault.new(self.shortcut_text(body), workspace=self.workspace))
            self.dirty = True
            self.save_current()


_bind_capabilities(Jotline, Encryption, Review, RecoveryImport, ActionWorkflows, Views, Workflows, Connections)
