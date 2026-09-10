"""Keyboard-first writing UI. No shell commands are executed by the palette."""
from __future__ import annotations

from dataclasses import replace
import re

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Footer, Input, Label, OptionList, Static, TextArea
from textual.widgets.option_list import Option
from rich.text import Text

from .store import COLLECTIONS, Note, Vault, tagged_body, validate_workspace
from .settings import Settings, HOTKEY_ACTIONS
from .preferences import Preferences


class Palette(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CSS = """
    Palette { align: center top; background: $background 70%; }
    #palette { width: 76; max-width: 95%; height: auto; max-height: 80%; margin-top: 3;
        border: round $accent; padding: 1 2; background: $surface; }
    #palette-title { color: $accent; margin-bottom: 1; }
    #commands { height: auto; max-height: 18; border: none; }
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


class FindInNote(ModalScreen[None]):
    BINDINGS = [Binding("escape", "done", "Done"), Binding("f3", "next", "Next"),
                Binding("shift+f3", "previous", "Previous")]
    CSS = """
    FindInNote { align: center top; background: $background 70%; }
    #find-panel { width: 68; max-width: 95%; height: auto; margin-top: 3;
        border: round $accent; padding: 1 2; background: $surface; }
    #find-title { color: $accent; margin-bottom: 1; }
    #find-status { height: 2; padding-top: 1; color: $text-muted; }
    #find-context { height: auto; max-height: 3; color: $foreground; background: $background;
        padding: 0 1; }
    #find-buttons { height: 3; margin-top: 1; }
    #find-buttons Button { margin-right: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.anchor = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="find-panel"):
            yield Label("Find within this note", id="find-title")
            yield Input(placeholder="Type text to find…", id="find-query")
            yield Static("Enter / F3 next · Shift+F3 previous · Esc done", id="find-status")
            yield Static("", id="find-context", markup=False)
            with Horizontal(id="find-buttons"):
                yield Button("Next", variant="primary", id="find-next")
                yield Button("Previous", id="find-previous")
                yield Button("Done", id="find-done")

    def on_mount(self) -> None:
        editor = self.app.query_one("#editor", TextArea)
        self.anchor = self.app.editor_offset(editor.cursor_location, editor.text)
        self.query_one(Input).focus()

    def show_match(self, *, reverse: bool = False, initial: bool = False) -> None:
        query = self.query_one("#find-query", Input).value
        status = self.query_one("#find-status", Static)
        if not query:
            status.update("Enter / F3 next · Shift+F3 previous · Esc done")
            self.query_one("#find-context", Static).update("")
            return
        result = self.app.select_editor_match(query, reverse=reverse,
                                              anchor=self.anchor if initial else None)
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
        if event.button.id == "find-next":
            self.show_match()
        elif event.button.id == "find-previous":
            self.show_match(reverse=True)
        else:
            self.action_done()

    def action_next(self) -> None:
        self.show_match()

    def action_previous(self) -> None:
        self.show_match(reverse=True)

    def action_done(self) -> None:
        self.dismiss(None)
        self.app.query_one("#editor", TextArea).focus()


class Jotline(App):
    TITLE = "jotline"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: $background; color: $foreground; }
    #brand { height: 3; padding: 1 2 0 2; color: $accent; text-style: bold; }
    #workspace { height: 1fr; }
    #sidebar { width: 32; min-width: 22; border-right: solid $primary-muted; padding: 0 1; }
    #collection { height: 2; padding-left: 1; color: $text-muted; }
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
    """
    BINDINGS = [Binding(key, action, label, priority=True, id="jotline." + action)
                for action, (key, label) in HOTKEY_ACTIONS.items()] + [
        Binding("f1", "settings", "Settings", priority=True),
        Binding("escape", "editor_focus", "Write", show=False),
    ]

    def __init__(self, vault: Vault, workspace: str | None = None):
        super().__init__()
        self.vault = vault
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

    def compose(self) -> ComposeResult:
        yield Static("›_ jotline     /     " + self.workspace, id="brand", markup=False)
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                yield Static("INBOX", id="collection")
                yield Input(placeholder="Search words or #tags", id="search")
                yield OptionList(id="notes")
            with Vertical(id="writing"):
                yield Static(self.current.title + " / " + self.current.collection, id="note-heading")
                yield TextArea("", soft_wrap=True, tab_behavior="focus", show_line_numbers=False, id="editor")
                yield Static("", id="connections", markup=False)
                yield Static("Ready · local Markdown", id="status", markup=False)
        yield Static("Capture first. Make sense of it later.   ctrl+p commands · ctrl+d daily log", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self.apply_settings(startup=True)
        self.status("Ready")
        self.refresh_notes()
        self.autosave_timer = self.set_interval(self.settings.autosave_seconds, self.autosave)
        if self.settings.startup == 'daily':
            self.action_daily()
        if self.settings_warning:
            self.notify(self.settings_warning, severity='warning', timeout=10)
        self.query_one("#editor", TextArea).focus()
        if self.vault.warnings:
            self.notify("Some Markdown files could not be read. Run jotline list to inspect warnings.", severity="warning")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Let modal screens own the keyboard; never run editor shortcuts underneath them.
        if isinstance(self.screen, ModalScreen):
            return False
        return super().check_action(action, parameters)

    def apply_settings(self, *, startup: bool = False) -> None:
        settings = self.settings
        self.set_keymap({"jotline." + action: key for action, key in settings.effective_hotkeys.items()})
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
        notes = self.vault.search(self.query_one("#search", Input).value, self.collection, self.workspace)
        if self.settings.sort_order == 'title':
            notes.sort(key=lambda n: (not n.starred, n.title.casefold(), n.id))
        elif self.settings.sort_order == 'created':
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
        self.query_one("#collection", Static).update(f"{self.collection.upper()}  /  {len(notes)}")
        self.query_one("#brand", Static).update(self.shortcut_text(
            f"›_ jotline     /     {self.workspace}     ·     ctrl+w workspaces · ctrl+t tags"))

    @on(Input.Changed, "#search")
    def search_changed(self) -> None:
        self.refresh_notes()

    @on(OptionList.OptionSelected, "#notes")
    def note_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.load_id(event.option.id)

    @on(TextArea.Changed, "#editor")
    def edited(self) -> None:
        self.capture_current_buffer()

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
        self.query_one("#status", Static).update(f"{message}  ·  {len(self.current.body.split())} words  ·  {self.current.collection}  ·  {self.workspace}" +
            ("  ·  " + " ".join("#" + tag for tag in tags) if tags else ""))
        self.query_one("#note-heading", Static).update(Text(self.current.title + " / " + self.current.collection))

    def save_current(self) -> bool:
        # Capture the buffer synchronously even when its Changed message is pending.
        self.capture_current_buffer()
        if not self.dirty:
            return True
        try:
            self.vault.save(self.current)
        except (OSError, ValueError) as error:
            self.status("NOT SAVED · " + str(error))
            if str(error) != self.last_error:
                self.notify(str(error), severity="error", timeout=10)
                self.last_error = str(error)
            return False
        self.dirty, self.last_error = False, ""
        self.status("Saved")
        self.refresh_notes()
        self.connections()
        return True

    def autosave(self) -> None:
        if self.dirty:
            self.save_current()

    def connections(self) -> None:
        backlinks = self.vault.backlinks(self.current)
        summary = " · ".join(n.title for n in backlinks[:3])
        self.query_one("#connections", Static).update(f"← {len(backlinks)} backlinks" + (f"  {summary}" if summary else self.shortcut_text("  ·  ctrl+p → Insert note link")))

    def load(self, note: Note) -> None:
        if note.workspace != self.workspace:
            raise ValueError("Note moved to another workspace; save a recovery copy if needed")
        self.current, self.dirty, self.last_error = note, False, ""
        self.query_one("#editor", TextArea).load_text(note.body)
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
        self.query_one("#search", Input).focus()

    def action_editor_focus(self) -> None:
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
        self.query_one("#sidebar").set_class(enabled, "hidden")
        self.query_one("#hint").set_class(enabled or not self.settings.show_hints, "hidden")

    def action_open_note(self) -> None:
        notes = self.vault.search(workspace=self.workspace)
        self.push_screen(Palette([(n.id, n.title + " · " + n.collection) for n in notes], "Open a note"),
                         lambda key: self.load_id(key) if key else None)

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
            self.query_one("#notes").focus()

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
                            anchor: int | None = None) -> tuple[int, int] | None:
        editor = self.query_one("#editor", TextArea)
        text = editor.text
        matches = list(re.finditer(re.escape(query), text, re.IGNORECASE))
        if not matches:
            return None
        if anchor is None:
            location = editor.selection.start if reverse else editor.selection.end
            anchor = self.editor_offset(location, text)
        if reverse:
            match = next((item for item in reversed(matches) if item.start() < anchor), matches[-1])
        else:
            match = next((item for item in matches if item.start() >= anchor), matches[0])
        start = self.editor_location(match.start(), text)
        end = self.editor_location(match.end(), text)
        editor.move_cursor(start)
        editor.move_cursor(end, select=True, center=True)
        return matches.index(match) + 1, len(matches)

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
        if self.vault.warnings:
            self.notify("Some Markdown files could not be read. Run jotline list to inspect warnings.",
                        severity="warning", timeout=10)
        elif not reload_failed:
            self.notify("Vault refreshed from disk.")

    def action_commands(self) -> None:
        choices = [("tags", "Browse tags                     ctrl+t"), ("add-tags", "Add tags to this note"),
                   ("workspaces", "Switch workspace                ctrl+w"), ("new-workspace", "Create workspace"),
                   ("move-workspace", "Move note to workspace"), ("settings", "Settings · appearance, editor, hotkeys · F1"), ("new", "New thought                    ctrl+n"), ("daily", "Open today's daily log         ctrl+d"),
                   ("open", "Open a note                    ctrl+o"), ("focus", "Toggle focus mode              ctrl+b"),
                   ("find", "Find within current note"), ("refresh", "Refresh vault from disk"),
                   ("star", "Toggle star on this note"), ("link", "Insert note link"), ("follow", "Follow a link in this note"),
                   ("backlinks", "Open a backlink"), ("task", "Toggle task on current line"),
                   ("copy", "Copy note to clipboard (terminal OSC 52)"), ("recovery", "Save recovery copy"),
                   ("review", "Start weekly review"), ("help", "Open writing and workflow guide")]
        choices += [("view:" + c, "Show " + c) for c in ("all", "starred", *COLLECTIONS)]
        choices += [("move:" + c, "Move note to " + c) for c in COLLECTIONS]
        self.push_screen(Palette([(key, self.shortcut_text(label)) for key, label in choices]), self.command)

    def command(self, key: str | None) -> None:
        if not key:
            return
        if key == "tags":
            self.action_tags()
        elif key == "add-tags":
            self.push_screen(TextPrompt("Add tags to this note", "#work #ideas or project/topic"), self.add_tags)
        elif key == "workspaces":
            self.action_workspaces()
        elif key == "new-workspace":
            self.push_screen(TextPrompt("Create a workspace", "e.g. personal, work, research"), self.switch_workspace)
        elif key == "move-workspace":
            self.push_screen(Palette([(name, name) for name in self.workspace_names()
                                      if name != self.workspace], "Move note to workspace"), self.move_workspace)
        elif key == 'settings':
            self.action_settings()
        elif key == "find":
            self.push_screen(FindInNote())
        elif key == "refresh":
            self.refresh_vault()
        elif key.startswith("view:"):
            self.collection = key[5:]
            self.query_one("#search", Input).value = ""
            self.refresh_notes()
            self.set_focus_mode(False)
            self.query_one("#notes").focus()
        elif key.startswith("move:") or key == "star":
            if not self.save_current():
                return
            if key == "star":
                self.current.starred = not self.current.starred
            else:
                self.current.collection = key[5:]
            self.dirty = True
            self.save_current()
        elif key in {"new", "daily", "focus", "open"}:
            {"new": self.action_new, "daily": self.action_daily, "focus": self.action_focus_mode,
             "open": self.action_open_note}[key]()
        elif key == "copy":
            self.copy_to_clipboard(self.query_one("#editor", TextArea).text)
            self.notify("Copy requested. Your terminal must allow OSC 52 clipboard access.")
        elif key == "task":
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
        elif key == "recovery":
            self.capture_current_buffer()
            try:
                self.load(self.vault.recovery(self.current))
                self.refresh_notes()
                self.notify("Saved a separate recovery copy in the inbox.")
            except (OSError, ValueError) as error:
                self.notify(str(error), severity="error")
        elif key in {"link", "follow", "backlinks"}:
            self.capture_current_buffer()
            if key == "backlinks":
                notes = self.vault.backlinks(self.current)
            else:
                notes = self.vault.search(workspace=self.workspace)
                if key == "follow":
                    links = self.current.links
                    notes = [n for n in notes if n.id in links or n.title in links]
                else:
                    notes = [n for n in notes if n.id != self.current.id]
            if not notes:
                self.notify("No matching notes yet.")
                return
            def picked(note_id):
                if note_id and key == "link":
                    note = next(n for n in notes if n.id == note_id)
                    label = note.title.replace("[", "").replace("]", "").replace("|", "")
                    self.query_one("#editor", TextArea).insert(f"[[{note.id}|{label}]]")
                    self.query_one("#editor", TextArea).focus()
                elif note_id:
                    self.load_id(note_id)
            self.push_screen(Palette([(n.id, n.title) for n in notes], "Choose a note"), picked)
        elif key in {"help", "review"}:
            if self.save_current():
                body = self.shortcut_text(GUIDE if key == "help" else REVIEW)
                self.load(self.vault.new(body, workspace=self.workspace))
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
