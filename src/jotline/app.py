"""Keyboard-first writing UI. No shell commands are executed by the palette."""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Callable

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Footer, Input, Label, Markdown, OptionList, Static, Switch, TextArea
from textual.widgets.option_list import Option
from rich.text import Text

from .store import COLLECTIONS, MAX_NOTE_BYTES, ConflictError, Note, Vault, tagged_body, validate_workspace
from .settings import Settings, HOTKEY_ACTIONS
from .preferences import Preferences
from .templates import Templates
from .workflows import WorkflowMixin
from .navigation import NavigationMixin
from .action_ui import ActionWorkflowMixin
from .import_ui import RecoveryImportMixin
from .note_menu import NoteList, NoteMenu


@dataclass(frozen=True)
class Command:
    """One user-visible palette action.

    Keeping its label and handler together prevents the palette from drifting
    away from the action dispatcher as features are added.
    """

    key: str
    label: str
    handler: Callable[[], None]
    hotkey_action: str | None = None


class Palette(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CSS = """
    Palette { align: center top; background: $background 70%; }
    #palette { width: 76; max-width: 95%; height: 80%; max-height: 80%; margin-top: 3;
        border: round $accent; padding: 1 2; background: $surface; }
    #palette-title { color: $accent; margin-bottom: 1; }
    #palette-help, #command-count { color: $text-muted; }
    #commands { height: 1fr; min-height: 3; border: none; }
    """

    def __init__(self, choices: list[tuple[str, str]], title: str = "Run a command"):
        super().__init__()
        self.choices = choices
        self.heading = title
        self.filtered = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="palette"):
            yield Label(self.heading, id="palette-title")
            yield Input(placeholder="Type to filter…", id="command-query")
            yield Static("Type to filter · ↑↓ choose · Enter run · Esc cancel", id="palette-help")
            yield Static("", id="command-count", markup=False)
            yield OptionList(id="commands")

    def on_mount(self) -> None:
        self.filter("")
        self.query_one(Input).focus()

    def filter(self, query: str) -> None:
        terms = query.casefold().split()
        self.filtered = [(key, label) for key, label in self.choices if all(t in label.casefold() for t in terms)]
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([Option(Text(label), id=key) for key, label in self.filtered])
        count = self.query_one("#command-count", Static)
        count.update(f"{len(self.filtered)} result" + ("" if len(self.filtered) == 1 else "s")
                     if self.filtered else "No matching commands · adjust the filter or press Esc")
        if self.filtered:
            options.highlighted = 0

    @on(Input.Changed)
    def changed(self, event: Input.Changed) -> None:
        self.filter(event.value)

    @on(Input.Submitted)
    def submitted(self) -> None:
        options = self.query_one(OptionList)
        if options.highlighted is not None:
            self.dismiss(self.filtered[options.highlighted][0])

    @on(OptionList.OptionSelected)
    def selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    @on(OptionList.OptionHighlighted)
    def highlighted(self) -> None:
        # Arrow navigation starts in the query field, so keep the selected row
        # in the independently scrollable result region explicitly visible.
        self.query_one(OptionList).scroll_to_highlight()

    def on_key(self, event) -> None:
        if event.key in ("down", "up") and self.query_one(Input).has_focus:
            options = self.query_one(OptionList)
            if event.key == "down":
                options.action_cursor_down()
            else:
                options.action_cursor_up()
            event.prevent_default()
            event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)


class TextPrompt(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CSS = """
    TextPrompt { align: center top; background: $background 70%; }
    #text-prompt { width: 72; max-width: 95%; height: auto; margin-top: 3;
        border: round $accent; padding: 1 2; background: $surface; }
    """

    def __init__(self, title: str, placeholder: str):
        super().__init__()
        self.heading, self.placeholder = title, placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="text-prompt"):
            yield Label(self.heading)
            yield Input(placeholder=self.placeholder, id="prompt-value")
            yield Static("Enter to apply · Esc to cancel")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class MarkdownPreview(ModalScreen[None]):
    BINDINGS = [Binding("escape", "done", "Back to writing")]
    CSS = """
    MarkdownPreview { align: center middle; background: $background 80%; }
    #markdown-panel { width: 100; max-width: 96%; height: 94%;
        border: round $accent; padding: 1 2; background: $surface; }
    #markdown-scroll { height: 1fr; }
    """

    def __init__(self, body: str):
        super().__init__()
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="markdown-panel"):
            yield Label("Markdown preview · Esc to return to writing")
            with VerticalScroll(id="markdown-scroll"):
                # Let Markdown own its initial render during its mount lifecycle.
                # A second update from the parent mount can race its empty render.
                yield Markdown(self.body, open_links=False)
            yield Button("Back to writing", id="close-preview")

    def on_mount(self) -> None:
        self.query_one(VerticalScroll).focus()

    @on(Button.Pressed, "#close-preview")
    def action_done(self) -> None:
        self.dismiss(None)
        self.app.query_one("#editor", TextArea).focus()


class RevisionPreview(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CSS = """
    RevisionPreview { align: center middle; background: $background 80%; }
    #revision-panel { width: 100; max-width: 96%; height: 90%;
        border: round $accent; padding: 1 2; background: $surface; }
    #revision-text { height: 1fr; }
    #revision-buttons { height: 3; }
    """

    def __init__(self, note: Note):
        super().__init__()
        self.note = note

    def compose(self) -> ComposeResult:
        with Vertical(id="revision-panel"):
            yield Static("Saved version · " + self.note.title, markup=False)
            yield Static("Restore creates a separate inbox note and keeps the original.")
            yield TextArea(self.note.body, read_only=True, soft_wrap=False, id="revision-text")
            with Horizontal(id="revision-buttons"):
                yield Button("Restore as new note", variant="primary", id="restore-revision")
                yield Button("Cancel", id="cancel-revision")

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "restore-revision")


class FindInNote(ModalScreen[None]):
    BINDINGS = [Binding("escape", "done", "Done"), Binding("f3", "next", "Next"),
                Binding("shift+f3", "previous", "Previous")]
    CSS = """
    FindInNote { align: center top; background: $background 70%; }
    #find-panel { width: 68; max-width: 95%; height: auto; max-height: 90%; margin-top: 1;
        border: round $accent; padding: 1 2; background: $surface; }
    #find-title { color: $accent; margin-bottom: 1; }
    #find-status { height: 2; padding-top: 1; color: $text-muted; }
    #find-context { height: auto; max-height: 3; color: $foreground; background: $background;
        padding: 0 1; }
    #find-buttons, #replace-buttons { height: 3; margin-top: 1; }
    #find-buttons Button { margin-right: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.anchor = 0
        self.case_sensitive = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="find-panel"):
            yield Label("Find within this note", id="find-title")
            yield Input(placeholder="Type text to find…", id="find-query")
            yield Input(placeholder="Replace with…", id="replace-value")
            yield Label("Match case")
            yield Switch(False, id="find-case")
            with Horizontal(id="replace-buttons"):
                yield Button("Replace", id="replace-one")
                yield Button("Replace all", id="replace-all")
            yield Static("Enter / F3 next · Shift+F3 previous · Esc done", id="find-status")
            yield Static("", id="find-context", markup=False)
            with Horizontal(id="find-buttons"):
                yield Button("Next", variant="primary", id="find-next")
                yield Button("Previous", id="find-previous")
                yield Button("Done", id="find-done")

    def on_mount(self) -> None:
        editor = self.app.query_one("#editor", TextArea)
        self.anchor = self.app.editor_offset(editor.cursor_location, editor.text)
        self.query_one("#find-query", Input).focus()

    def show_match(self, *, reverse: bool = False, initial: bool = False) -> None:
        query = self.query_one("#find-query", Input).value
        status = self.query_one("#find-status", Static)
        if not query:
            status.update("Enter / F3 next · Shift+F3 previous · Esc done")
            self.query_one("#find-context", Static).update("")
            return
        result = self.app.select_editor_match(query, reverse=reverse,
                                              anchor=self.anchor if initial else None, case_sensitive=self.case_sensitive)
        if result is None:
            status.update("No matches · keep typing or Esc to return")
            self.query_one("#find-context", Static).update("")
        else:
            current, total = result
            status.update(f"Match {current} of {total} · Enter / F3 next · Shift+F3 previous")
            self.update_context()

    def update_context(self) -> None:
        editor = self.app.query_one("#editor", TextArea)
        row, start = editor.selection.start
        _, end = editor.selection.end
        line = editor.text.split("\n")[row]
        preview = Text(f"Line {row + 1} · ", style="dim")
        preview.append(line[:start])
        preview.append(line[start:end], style="bold reverse")
        preview.append(line[end:])
        self.query_one("#find-context", Static).update(preview)

    @on(Input.Changed, "#find-query")
    def query_changed(self) -> None:
        self.show_match(initial=True)

    @on(Input.Submitted, "#find-query")
    def query_submitted(self) -> None:
        self.show_match()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in {"replace-one", "replace-all"}:
            self.replace_matches(all_matches=event.button.id == "replace-all")
        elif event.button.id == "find-next":
            self.show_match()
        elif event.button.id == "find-previous":
            self.show_match(reverse=True)
        else:
            self.action_done()

    @on(Switch.Changed, "#find-case")
    def case_changed(self, event: Switch.Changed) -> None:
        self.case_sensitive = event.value
        self.show_match(initial=True)

    def replace_matches(self, *, all_matches=False):
        query = self.query_one('#find-query', Input).value
        if not query:
            return
        editor = self.app.query_one('#editor', TextArea)
        pattern = re.compile(re.escape(query), 0 if self.case_sensitive else re.IGNORECASE)
        replacement = self.query_one('#replace-value', Input).value
        if all_matches:
            replacement_bytes = len(replacement.encode('utf-8'))
            output_bytes = len(editor.text.encode('utf-8')) + sum(
                replacement_bytes - len(match[0].encode('utf-8'))
                for match in pattern.finditer(editor.text))
            if output_bytes > MAX_NOTE_BYTES - 4096:
                self.app.notify('Replacement exceeds the note size limit', severity='error')
                self.query_one('#find-status', Static).update('Not replaced · note size limit exceeded')
                return
            body, count = pattern.subn(lambda match: replacement, editor.text)
            if count and not self.app.replace_editor_text(body):
                self.query_one('#find-status', Static).update('Not replaced · note size limit exceeded')
                return
        else:
            if not pattern.fullmatch(editor.selected_text):
                self.show_match(initial=True)
            if not pattern.fullmatch(editor.selected_text):
                return
            if not self.app.insert_editor_text(replacement):
                self.query_one('#find-status', Static).update('Not replaced · note size limit exceeded')
                return
            count = 1
        self.show_match()
        self.query_one('#find-status', Static).update(f'Replaced {count} match(es) · Undo in editor to reverse')

    def action_next(self) -> None:
        self.show_match()

    def action_previous(self) -> None:
        self.show_match(reverse=True)

    def action_done(self) -> None:
        self.dismiss(None)
        self.app.query_one("#editor", TextArea).focus()


class Jotline(RecoveryImportMixin, ActionWorkflowMixin, NavigationMixin, WorkflowMixin, App):
    TITLE = "jotline"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: $background; color: $foreground; }
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
    #editor { height: 1fr; border: none; background: $background; }
    #status { height: 2; padding-top: 1; color: $text-muted; }
    #connections { height: auto; max-height: 5; padding-top: 1; color: $text-muted; }
    #hint { height: 2; padding: 0 2; color: $text-muted; }
    Footer { background: $surface; }
    .hidden { display: none; }
    .compact-footer { display: none; }
    """
    # Textual requires a nonempty binding key; these placeholders cannot be typed.
    BINDINGS = [Binding(key or "jotline_" + action + "_unassigned",
                        "format_markdown(" + repr(action[7:]) + ")" if action.startswith("format_") else action,
                        label, priority=True, show=bool(key), id="jotline." + action)
                for action, (key, label) in HOTKEY_ACTIONS.items()] + [
        Binding("f1", "settings", "Settings", priority=True),
        Binding("escape", "editor_focus", "Write", show=False),
    ]

    def __init__(self, vault: Vault, workspace: str | None = None, initial_note: Note | None = None):
        super().__init__()
        self.vault = vault
        self.initial_note = initial_note
        self.settings_path = vault.path / '.jotline-settings.json'
        self.settings, self.settings_warning = Settings.load(self.settings_path)
        self.workspace = validate_workspace(self.settings.active_workspace if workspace is None else workspace)
        self.register_theme(Theme(name='jotline', primary='#a8d5a2', accent='#a8d5a2',
                                  foreground='#d6ddd8', background='#101619', surface='#162024', panel='#162024'))
        self.current = vault.new(workspace=self.workspace)
        self.current.collection = self.settings.default_collection
        self.collection = self.settings.default_collection
        self.dirty = False
        self.last_error = ""
        self.focused_writing = False
        self.compact_layout = False
        self.compact_navigation = False
        self._shown_storage_warnings: set[str] = set()
        self.recent_note_ids = []
        self.note_positions = {}
        self.view_sort = None
        self.active_view = None
        self.command_registry = self.build_command_registry()

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
                    yield Button("Actions", id="nav-actions")
                    yield Button("Import", id="nav-import")
                yield Static("INBOX", id="collection", markup=False)
                yield Input(placeholder="Search words or #tags", id="search")
                yield Static("", id="empty-notes", markup=False)
                yield NoteList(id="notes")
            with Vertical(id="writing"):
                yield Static(self.current.title + " / " + self.current.collection, id="note-heading")
                yield TextArea("", soft_wrap=True, tab_behavior="focus", show_line_numbers=False, id="editor")
                yield Static("", id="connections", markup=False)
                yield Static("Ready · local Markdown", id="status", markup=False)
        yield Static("Capture first. Make sense of it later.   ctrl+p commands · ctrl+d daily log", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self.apply_settings(startup=True)
        self.update_responsive_layout()
        self.status("Ready")
        self.refresh_notes()
        self.autosave_timer = self.set_interval(self.settings.autosave_seconds, self.autosave)
        if self.initial_note is not None:
            self.collection = self.initial_note.collection
            self.load(self.initial_note)
            self.refresh_notes()
        elif self.settings.startup == 'daily':
            self.action_daily()
        if self.settings_warning:
            self.notify(self.settings_warning, severity='warning', timeout=10)
        self.query_one("#editor", TextArea).focus()
        self.notify_storage_warnings()

    def on_resize(self, event) -> None:
        self.update_responsive_layout()

    def update_responsive_layout(self) -> None:
        """Keep writing usable before a terminal has room for the full chrome."""
        size = self.size
        self.compact_layout = size.width <= 80 or size.height <= 24
        very_short = size.height <= 24
        sidebar = self.query_one("#sidebar")
        hint = self.query_one("#hint", Static)
        connections = self.query_one("#connections", Static)
        sidebar.set_class(self.focused_writing or (self.compact_layout and not self.compact_navigation), "hidden")
        hint.set_class(self.focused_writing or self.compact_layout or not self.settings.show_hints, "hidden")
        connections.set_class(very_short, "hidden")
        self.query_one(Footer).set_class(very_short, "compact-footer")

    def storage_warnings(self) -> list[str]:
        """Read optional storage safety warnings without coupling the UI to one API."""
        messages: list[str] = []
        for name in ("warnings", "partial_warnings", "budget_warnings"):
            value = getattr(self.vault, name, ())
            if isinstance(value, str):
                messages.append(value)
            elif isinstance(value, (list, tuple, set)):
                messages.extend(item for item in value if isinstance(item, str))
        for name in ("partial_warning", "budget_warning", "cache_warning", "permission_warning"):
            value = getattr(self.vault, name, "")
            if isinstance(value, str) and value:
                messages.append(value)
        return list(dict.fromkeys(message for message in messages if message))

    def notify_storage_warnings(self) -> None:
        for warning in self.storage_warnings():
            if warning not in self._shown_storage_warnings:
                self.notify("Storage warning: " + warning, severity="warning", timeout=10)
                self._shown_storage_warnings.add(warning)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Let modal screens own the keyboard; never run editor shortcuts underneath them.
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
        editor = self.query_one('#editor', TextArea)
        editor.soft_wrap = settings.soft_wrap
        editor.show_line_numbers = settings.line_numbers
        editor.highlight_cursor_line = settings.highlight_line
        self.query_one('#sidebar').styles.width = settings.sidebar_width
        self.set_focus_mode(settings.focus_on_start if startup else self.focused_writing)

    def shortcut_text(self, text: str) -> str:
        effective = self.settings.effective_hotkeys
        keys = {default: effective[action]
                for action, (default, _) in HOTKEY_ACTIONS.items()}
        return re.sub(r"ctrl\+[a-z]", lambda match: keys.get(match[0].lower(), match[0]), text, flags=re.I)

    def action_settings(self) -> None:
        self.push_screen(Preferences(self.settings), self.save_settings)

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
        self.query_one('#editor', TextArea).focus()
        self.notify('Settings saved. Startup choices apply next launch.')

    def refresh_notes(self) -> None:
        try:
            notes = self.vault.search(self.query_one("#search", Input).value, self.collection, self.workspace)
        except ValueError as error:
            self.query_one("#collection", Static).update(str(error))
            self.query_one("#notes", OptionList).clear_options()
            self.query_one("#empty-notes", Static).update("Fix the search above, or use Filters to change it.")
            self.query_one("#empty-notes").remove_class("hidden")
            return
        if (self.view_sort or self.settings.sort_order) == 'title':
            notes.sort(key=lambda n: (not n.starred, n.title.casefold(), n.id))
        elif (self.view_sort or self.settings.sort_order) == 'created':
            notes.sort(key=lambda n: (n.starred, n.created, n.id), reverse=True)
        listing = self.query_one("#notes", OptionList)
        listing.clear_options()
        listing.add_options([Option(Text(("★ " if n.starred else "") + n.title + "\n" +
                                            "  " + (n.updated[:10] or "imported") + " · " + n.collection), id=n.id)
                             for n in notes])
        for index, note in enumerate(notes):
            if note.id == self.current.id:
                listing.highlighted = index
                break
        label = f"{self.collection.upper()} / {len(notes)}"
        if self.active_view and self.active_view in self.settings.saved_views:
            view = self.settings.saved_views[self.active_view]
            current = self.current_view()
            matches = all(current[k] == view[k] for k in current if k != 'theme') and self.theme == (view['theme'] or self.settings.theme)
            label += f" · {self.active_view}" + (" (modified)" if not matches else "")
        self.query_one("#collection", Static).update(label)
        empty = self.query_one("#empty-notes", Static)
        empty.set_class(bool(notes), "hidden")
        empty.update(self.shortcut_text(
            "No matches. Adjust search or use Filters; Clear view and search resets filters."
            if self.query_one("#search", Input).value else
            "Nothing here yet. Ctrl+N captures a new note. Collections shows your other notes."))
        self.query_one("#brand", Static).update(self.shortcut_text(
            f"›_ jotline     /     {self.workspace}     ·     ctrl+w workspaces · ctrl+t tags"))
        self.notify_storage_warnings()

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

    @on(Button.Pressed, "#nav-import")
    def navigation_import(self):
        self.import_library()

    @on(Input.Changed, "#search")
    def search_changed(self) -> None:
        self.refresh_notes()

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
        if not note.id.startswith('daily-'):
            choices.append(('workspace', 'Move to workspace…'))
        choices.append(('restore', 'Restore to Inbox') if note.collection == 'trash'
                       else ('trash', 'Delete · Move to Trash'))
        self.push_screen(NoteMenu(note.title, choices, event.x, event.y),
                         lambda action: self.note_context_action(note, action, event.x, event.y))

    def note_context_action(self, note: Note, action: str | None, x: int, y: int) -> None:
        if action in ('trash', 'restore'):
            self.move_context_note(note, collection='trash' if action == 'trash' else 'inbox')
        elif action == 'move':
            choices = [(name, name.title()) for name in COLLECTIONS
                       if name not in ('trash', note.collection)]
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
        # Keep the menu's read baseline for other notes, so external edits conflict.
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
                if moved.id.startswith('daily-'):
                    raise ValueError('Daily logs belong to their workspace')
                moved.workspace = workspace
            self.vault.save(moved)
        except (OSError, ValueError) as error:
            self.notify(f'Note was not moved: {error}', severity='error', timeout=10)
            return
        if is_current:
            if moved.workspace != self.workspace or moved.collection == 'trash':
                fresh = self.vault.new(workspace=self.workspace)
                fresh.collection = self.settings.default_collection
                self.load(fresh)
            else:
                self.load(moved)
        self.refresh_notes()
        self.connections()
        self.notify_backup_warning()
        self.notify(f'Moved to {workspace or collection}')

    @on(TextArea.Changed, "#editor")
    def edited(self) -> None:
        if self.is_running:
            if self.capture_current_buffer():
                self.offer_completion()

    def capture_current_buffer(self) -> bool:
        """Copy the editor into the note while preserving its unsaved state."""
        body = self.query_one("#editor", TextArea).text
        if body == self.current.body:
            return False
        self.current.body = body
        self.dirty = True
        self.status("Saving…")
        return True

    def status(self, message: str) -> None:
        tags = sorted(self.current.tags)[:5]
        details = f"{message}  ·  {len(self.current.body.split())} words"
        if not self.compact_layout:
            details += f"  ·  {self.current.collection}  ·  {self.workspace}"
            details += "  ·  " + " ".join("#" + tag for tag in tags) if tags else ""
        self.query_one("#status", Static).update(details)
        self.query_one("#note-heading", Static).update(Text(self.current.title + " / " + self.current.collection))

    def save_current(self) -> bool:
        # Capture the buffer synchronously even when its Changed message is pending.
        self.capture_current_buffer()
        if not self.dirty:
            return True
        try:
            self.vault.save(self.current)
        except (OSError, ValueError) as error:
            conflict = isinstance(error, ConflictError) or "changed outside Jotline" in str(error)
            guidance = ("Your on-screen draft is safe. Open Commands → Save recovery copy, then Refresh vault "
                        "to review the external version.") if conflict else str(error)
            message = "NOT SAVED · " + ("External change detected" if conflict else str(error))
            self.status(message)
            if guidance != self.last_error:
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
        self.connections()
        return True

    def autosave(self) -> None:
        # Textual clears is_running before pruning widgets, but timer callbacks
        # may still fire until the message pump closes (observed on macOS).
        if self.is_running and self.dirty:
            self.save_current()

    def connections(self) -> None:
        backlinks = self.vault.backlinks(self.current)
        summary = " · ".join(n.title for n in backlinks[:3])
        self.query_one("#connections", Static).update(f"← {len(backlinks)} backlinks" + (f"  {summary}" if summary else self.shortcut_text("  ·  ctrl+p → Insert note link")))

    def load(self, note: Note) -> None:
        if note.workspace != self.workspace:
            raise ValueError("Note moved to another workspace; save a recovery copy if needed")
        editor = self.query_one("#editor", TextArea)
        self.note_positions[self.current.id] = editor.cursor_location
        if self.current.original is not None and self.current.id != note.id:
            self.recent_note_ids = [self.current.id] + [key for key in self.recent_note_ids if key != self.current.id]
            self.recent_note_ids = self.recent_note_ids[:50]
        self.current, self.dirty, self.last_error = note, False, ""
        self.query_one("#editor", TextArea).load_text(note.body)
        editor.move_cursor(self.note_positions.get(note.id, (0, 0)))
        self.query_one("#editor", TextArea).focus()
        self.status("Saved" if note.original is not None else "Ready")
        self.connections()

    def load_id(self, note_id: str) -> None:
        if not self.save_current():
            return
        try:
            self.load(self.vault.read(note_id))
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")

    def action_new(self) -> None:
        if self.save_current():
            note = self.vault.new(workspace=self.workspace)
            note.collection = self.settings.default_collection
            self.collection = note.collection
            self.load(note)
            self.refresh_notes()

    def action_daily(self) -> None:
        if self.save_current():
            try:
                note = self.vault.daily(self.settings.daily_template, self.workspace)
            except (OSError, ValueError) as error:
                self.notify(f"Could not open today's daily log: {error}", severity="error", timeout=10)
                return
            self.collection = note.collection
            self.load(note)
            self.refresh_notes()
            editor = self.query_one("#editor", TextArea)
            lines = editor.text.split("\n")
            editor.move_cursor((len(lines) - 1, len(lines[-1])))

    def action_search(self) -> None:
        self.collection = "all"
        self.set_focus_mode(False)
        self.refresh_notes()
        self.show_navigation("search")

    def action_editor_focus(self) -> None:
        self.compact_navigation = False
        self.update_responsive_layout()
        self.query_one("#editor", TextArea).focus()

    def action_save(self) -> None:
        self.save_current()

    def action_quit(self) -> None:
        if self.save_current():
            self.exit()

    def action_focus_mode(self) -> None:
        self.set_focus_mode(not self.focused_writing)
        self.query_one("#editor", TextArea).focus()

    def set_focus_mode(self, enabled: bool) -> None:
        self.focused_writing = enabled
        if enabled:
            self.compact_navigation = False
        self.update_responsive_layout()

    def show_navigation(self, target: str = "notes") -> None:
        """Temporarily reveal compact navigation before focusing its controls."""
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
        """Only add noisy metadata when a title alone would be ambiguous."""
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
            if not self.save_current():
                return
            settings = replace(self.settings, active_workspace=name,
                               workspace_names=sorted(set(self.settings.workspace_names) | {name}))
            settings.save(self.settings_path)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")
            return
        self.settings, self.workspace = settings, name
        self.active_view = None
        self.view_sort = None
        self.theme = self.settings.theme
        self.collection = self.settings.default_collection
        self.query_one("#search", Input).value = ""
        self.load(self.vault.new(workspace=name))
        self.current.collection = self.collection
        self.status("Ready")
        self.refresh_notes()
        self.set_focus_mode(False)

    def move_workspace(self, name: str | None) -> None:
        if not name or not self.save_current():
            return
        try:
            validate_workspace(name)
            if self.current.id.startswith("daily-"):
                raise ValueError("Daily logs belong to their workspace; copy their text into a regular note to move it")
            moved = replace(self.current, workspace=name)
            self.vault.save(moved)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")
            return
        self.load(self.vault.new(workspace=self.workspace))
        self.current.collection = self.settings.default_collection
        self.status("Ready")
        self.refresh_notes()
        self.notify(f"Note moved to {name}")

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
        editor = self.query_one("#editor", TextArea)
        try:
            body = tagged_body(editor.text, tags)
        except ValueError as error:
            self.notify(str(error), severity="error")
            return
        # Insert only the suffix, retaining the editor's undo history.
        editor.insert(body[len(editor.text):], self.editor_location(len(editor.text), editor.text))
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
        note = self.vault.new(body, workspace=self.workspace)
        note.collection = self.settings.default_collection
        self.collection = note.collection
        self.query_one("#search", Input).value = ""
        self.load(note)
        self.dirty = True
        self.save_current()

    def save_template(self, name: str | None) -> None:
        if not name:
            return
        try:
            Templates(self.vault.path).save(name, self.query_one("#editor", TextArea).text)
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

    def action_preview(self) -> None:
        self.capture_current_buffer()
        if len(self.current.body.encode("utf-8")) > 256 * 1024:
            self.notify("Preview supports notes up to 256 KiB. You can still edit and save this note.", severity="warning")
            return
        self.push_screen(MarkdownPreview(self.current.body))

    def action_format_markdown(self, style: str) -> None:
        editor = self.query_one("#editor", TextArea)
        start, end = sorted((editor.selection.start, editor.selection.end))
        editor.history.checkpoint()
        if style in {"heading", "list", "quote"}:
            first, last = start[0], end[0]
            if end[1] == 0 and last > first:
                last -= 1
            lines = editor.text.split("\n")
            prefix = {"heading": "## ", "list": "- ", "quote": "> "}[style]
            body = "\n".join(prefix + line for line in lines[first:last + 1])
            editor.replace(body, (first, 0), (last, len(lines[last])))
        else:
            body = editor.selected_text or "text"
            marker = {"bold": "**", "italic": "*", "code": "`"}[style]
            if style == "code":
                marker = "`" * (max((len(m[0]) for m in re.finditer(r"`+", body)), default=0) + 1)
            padding = " " if style == "code" and (body.startswith("`") or body.endswith("`")) else ""
            replacement = marker + padding + body + padding + marker
            offset = self.editor_offset(start, editor.text) + len(marker + padding)
            editor.replace(replacement, start, end)
            editor.move_cursor(self.editor_location(offset, editor.text))
            editor.move_cursor(self.editor_location(offset + len(body), editor.text), select=True)
        editor.history.checkpoint()
        self.capture_current_buffer()
        editor.focus()

    @staticmethod
    def editor_offset(location: tuple[int, int], text: str) -> int:
        row, column = location
        lines = text.split("\n")
        return sum(len(line) + 1 for line in lines[:row]) + column

    @staticmethod
    def editor_location(offset: int, text: str) -> tuple[int, int]:
        before = text[:offset]
        row = before.count("\n")
        return row, len(before.rsplit("\n", 1)[-1])

    def select_editor_match(self, query: str, *, reverse: bool = False,
                            anchor: int | None = None, case_sensitive: bool = False) -> tuple[int, int] | None:
        editor = self.query_one("#editor", TextArea)
        text = editor.text
        if not query:
            return None
        if anchor is None:
            start, end = sorted((editor.selection.start, editor.selection.end))
            location = start if reverse else end
            anchor = self.editor_offset(location, text)
        # Scan once and retain only the candidate, wrap target, and counters.
        # Notes can be large; materialising every match is unnecessary memory use.
        first = last = candidate = None
        first_ordinal = last_ordinal = candidate_ordinal = 0
        total = 0
        for total, match in enumerate(re.finditer(re.escape(query), text, 0 if case_sensitive else re.IGNORECASE), start=1):
            if first is None:
                first, first_ordinal = match, total
            last, last_ordinal = match, total
            if (reverse and match.start() < anchor) or (not reverse and match.start() >= anchor):
                if reverse:
                    candidate, candidate_ordinal = match, total
                elif candidate is None:
                    candidate, candidate_ordinal = match, total
        if first is None:
            return None
        if candidate is None:
            match, ordinal = (last, last_ordinal) if reverse else (first, first_ordinal)
        else:
            match, ordinal = candidate, candidate_ordinal
        start = self.editor_location(match.start(), text)
        end = self.editor_location(match.end(), text)
        editor.move_cursor(start)
        editor.move_cursor(end, select=True, center=True)
        return ordinal, total

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
        self.connections()
        if kept_unsaved and not reload_failed:
            self.status("Refreshed · unsaved changes kept")
        if not self.storage_warnings() and not reload_failed:
            self.notify("Vault refreshed from disk.")

    def action_commands(self) -> None:
        self.push_screen(Palette(self.command_choices(), "Run a command"), self.command)

    def build_command_registry(self) -> dict[str, Command]:
        commands = [
            Command("templates", "New note from template", self.action_templates),
            Command("save-template", "Save this note as a template", self.prompt_save_template),
            Command("template-source", "Copy template source to new note", lambda: self.action_templates(source=True)),
            Command("history", "History of this note", lambda: self.show_history(self.current.id)),
            Command("browse-history", "Browse saved note history", self.browse_history),
            Command("backup", "Back up vault now", self.action_backup),
            Command("preview", "Preview rendered Markdown", self.action_preview, "preview"),
            Command("tags", "Browse tags", self.action_tags, "tags"),
            Command("add-tags", "Add tags to this note", self.prompt_add_tags),
            Command("workspaces", "Switch workspace", self.action_workspaces, "workspaces"),
            Command("new-workspace", "Create workspace", self.prompt_new_workspace),
            Command("move-workspace", "Move note to workspace", self.prompt_move_workspace),
            Command("settings", "Settings · appearance, editor, hotkeys · F1", self.action_settings),
            Command("new", "New thought", self.action_new, "new"),
            Command("daily", "Open today's daily log", self.action_daily, "daily"),
            Command("open", "Open a note", self.action_open_note, "open_note"),
            Command("focus", "Toggle focus mode", self.action_focus_mode, "focus_mode"),
            Command("find", "Find within current note", lambda: self.push_screen(FindInNote())),
            Command("refresh", "Refresh vault from disk", self.refresh_vault),
            Command("star", "Toggle star on this note", self.toggle_star),
            Command("link", "Insert note link", lambda: self.select_related_note("link")),
            Command("follow", "Follow a link in this note", lambda: self.select_related_note("follow")),
            Command("backlinks", "Open a backlink", lambda: self.select_related_note("backlinks")),
            Command("task", "Toggle task on current line", self.toggle_task),
            Command("copy", "Copy note to clipboard (terminal OSC 52)", self.copy_current_note),
            Command("recovery", "Save recovery copy", self.save_recovery_copy),
            Command("review", "Start weekly review", lambda: self.open_generated_note(REVIEW)),
            Command("help", "Open writing and workflow guide", lambda: self.open_generated_note(GUIDE)),
        ]
        commands.extend(Command("format:" + style, "Format " + label,
                                lambda style=style: self.action_format_markdown(style), "format_" + style)
                        for style, label in (("bold", "bold"), ("italic", "italic"), ("code", "inline code"),
                                             ("heading", "heading"), ("list", "bullet list"), ("quote", "blockquote")))
        commands.extend(Command("view:" + collection, "Show " + collection,
                                lambda collection=collection: self.show_collection(collection))
                        for collection in ("all", "starred", *COLLECTIONS))
        commands.extend(Command("move:" + collection, "Move note to " + collection,
                                lambda collection=collection: self.move_to_collection(collection))
                        for collection in COLLECTIONS)
        commands.extend(self.workflow_commands(Command))
        commands.extend(self.navigation_commands(Command))
        commands.extend(Command(key, label, handler) for key, label, handler in self.action_workflow_commands())
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
        if self.save_current():
            self.current.collection = collection
            self.dirty = True
            self.save_current()

    def toggle_star(self) -> None:
        if self.save_current():
            self.current.starred = not self.current.starred
            self.dirty = True
            self.save_current()

    def copy_current_note(self) -> None:
        self.copy_to_clipboard(self.query_one("#editor", TextArea).text)
        self.notify("Copy requested. Your terminal must allow OSC 52 clipboard access.")

    def toggle_task(self) -> None:
        editor = self.query_one("#editor", TextArea)
        row, _ = editor.cursor_location
        line = editor.text.split("\n")[row]
        if line.lstrip().startswith("- [ ] "):
            updated = line.replace("- [ ] ", "- [x] ", 1)
        elif line.lstrip().startswith("- [x] "):
            updated = line.replace("- [x] ", "- [ ] ", 1)
        else:
            updated = "- [ ] " + line
        editor.replace(updated, (row, 0), (row, len(line)))

    def save_recovery_copy(self) -> None:
        self.capture_current_buffer()
        try:
            self.load(self.vault.recovery(self.current))
            self.refresh_notes()
            self.notify("Saved a separate recovery copy in the inbox.")
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error")

    def select_related_note(self, mode: str) -> None:
        self.capture_current_buffer()
        if mode == "backlinks":
            notes = self.vault.backlinks(self.current)
        else:
            notes = self.vault.search(workspace=self.workspace)
            if mode == "follow":
                links = self.current.links
                notes = [note for note in notes if note.id in links or note.title in links]
            else:
                notes = [note for note in notes if note.id != self.current.id]
        if not notes:
            self.notify("No matching notes yet.")
            return

        def picked(note_id: str | None) -> None:
            if note_id and mode == "link":
                note = next(note for note in notes if note.id == note_id)
                label = note.title.replace("[", "").replace("]", "").replace("|", "")
                self.query_one("#editor", TextArea).insert(f"[[{note.id}|{label}]]")
                self.query_one("#editor", TextArea).focus()
            elif note_id:
                self.load_id(note_id)

        self.push_screen(Palette(self.note_choices(notes), "Choose a note"), picked)

    def open_generated_note(self, body: str) -> None:
        if self.save_current():
            self.load(self.vault.new(self.shortcut_text(body), workspace=self.workspace))
            self.dirty = True
            self.save_current()


GUIDE = """# A little room to think

Capture first. Press Ctrl+N and write without choosing a folder or title.
The first line becomes the title. Your words save automatically.

## A simple rhythm
- Capture loose thoughts in the inbox.
- Ctrl+D opens today's log: observations, decisions, and next steps.
- Keep a useful idea in its own note. Ctrl+P → Insert note link connects it.
- Review the inbox regularly. Move useful notes to projects, areas, or resources.
- Archive what is finished. Trash is reversible; move a note back to restore it.

## Make it yours
F1 opens Settings for themes, editor, layout, keyboard shortcuts, and daily templates.
Hotkey changes apply on Save. F1 and Esc stay fixed; Reset hotkeys restores defaults.
Preferences are saved for this vault.

## Writing
Use Markdown: # headings, **emphasis**, - lists, and - [ ] tasks.
Ctrl+P → Preview rendered Markdown displays your current text; Esc returns to editing.
Select text, then Ctrl+P → Format bold, italic, or inline code. Without a selection,
a selected placeholder is inserted. Format heading, bullet list, and blockquote
apply to the current line or selected lines. Undo works normally.
Add #tags anywhere; search #tag to find exact tag matches.
Ctrl+T browses workspace tags and counts. Ctrl+P → Add tags appends tags.
Edit or remove inline tags directly in the note; no separate tag database is needed.

## Workspaces
Ctrl+W switches workspaces or creates one, such as work or personal.
Ctrl+P → Move note to workspace moves a regular note without changing its file ID.
Each workspace has its own daily logs, collections, search results, and links.
Existing notes are in default. Workspace names use lowercase letters, numbers, - or _.
All Markdown stays in the same vault folder; workspace is saved in note metadata.
Appearance and editor settings are shared across this vault.

## Navigation
Ctrl+P → Toggle task checks or unchecks the current line.
Ctrl+B hides the sidebar. Ctrl+O finds a note by title.
Ctrl+F searches this workspace (except trash). Multiple words narrow results.
Ctrl+P → Follow a link or Open a backlink moves between connected notes.
Links inserted by Jotline use stable IDs, so changing titles is safe.

## Templates and history
Ctrl+P → New note from template starts a meeting, project, journal, or saved template.
Save this note as a template keeps a reusable copy; use {{date}}, {{time}}, {{workspace}}.
Copy template source to new note preserves placeholders for customization.
F1 → Keyboard shortcuts includes optional Markdown formatting and preview keys.
Ctrl+P → History of this note lets you inspect and restore a saved version as a new note.
Browse saved note history includes externally deleted notes in this workspace.
Back up vault now saves a local ZIP of notes, settings, and templates.

## Your files
Everything stays in your local vault as readable Markdown.
Use `jotline capture` to send text from the shell, and `jotline export` to
write a note without metadata. No account, telemetry, or cloud service.
Ctrl+Q flushes edits before quitting. Use it before closing the terminal.
"""

REVIEW = """# Weekly review

## Clear the inbox
- [ ] Read unprocessed captures (Ctrl+P → Show inbox).
- [ ] Turn actionable thoughts into a concrete next step.
- [ ] Move active work to projects and ongoing responsibilities to areas.
- [ ] Keep reference material in resources; archive what is finished.

## Connect and reflect
- [ ] Revisit this week's daily logs.
- [ ] Extract useful ideas into their own notes and link them.
- [ ] Review active projects: what is the next small action?
- [ ] Choose what deserves attention next week.

## What I learned

## Next week

"""
