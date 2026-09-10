"""Keyboard-first writing UI. No shell commands are executed by the palette."""
from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label, OptionList, Static, TextArea
from textual.widgets.option_list import Option
from rich.text import Text

from .store import COLLECTIONS, Note, Vault


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


class Jotline(App):
    TITLE = "jotline"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: #101619; color: #d6ddd8; }
    #brand { height: 3; padding: 1 2 0 2; color: #a8d5a2; text-style: bold; }
    #workspace { height: 1fr; }
    #sidebar { width: 32; min-width: 22; border-right: solid #2c3a3d; padding: 0 1; }
    #collection { height: 2; padding-left: 1; color: #96a8ab; }
    #search { margin-bottom: 1; border: tall #2c3a3d; background: #162024; }
    #notes { border: none; background: #101619; height: 1fr; }
    #notes > .option-list--option-highlighted { background: #233b36; color: #c9ebbf; }
    #writing { width: 1fr; padding: 0 2; }
    #note-heading { height: 2; color: #a8d5a2; }
    #editor { height: 1fr; border: none; background: #101619; }
    #status { height: 2; padding-top: 1; color: #96a8ab; }
    #connections { height: auto; max-height: 5; padding-top: 1; color: #96a8ab; }
    #hint { height: 2; padding: 0 2; color: #96a8ab; }
    Footer { background: #162024; }
    .hidden { display: none; }
    """
    BINDINGS = [
        Binding("ctrl+n", "new", "New", priority=True),
        Binding("ctrl+p", "commands", "Commands", priority=True),
        Binding("ctrl+o", "open_note", "Open", priority=True),
        Binding("ctrl+d", "daily", "Today", priority=True),
        Binding("ctrl+f", "search", "Search", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("ctrl+b", "focus_mode", "Focus", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("escape", "editor_focus", "Write", show=False),
    ]

    def __init__(self, vault: Vault):
        super().__init__()
        self.vault = vault
        self.current = vault.new()
        self.collection = "inbox"
        self.dirty = False
        self.last_error = ""
        self.focused_writing = False

    def compose(self) -> ComposeResult:
        yield Static("›_ jotline     /     a little room to think", id="brand")
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                yield Static("INBOX", id="collection")
                yield Input(placeholder="Search words or #tags", id="search")
                yield OptionList(id="notes")
            with Vertical(id="writing"):
                yield Static("new thought / inbox", id="note-heading")
                yield TextArea("", soft_wrap=True, tab_behavior="focus", show_line_numbers=False, id="editor")
                yield Static("", id="connections", markup=False)
                yield Static("Ready · local Markdown", id="status", markup=False)
        yield Static("Capture first. Make sense of it later.   ctrl+p commands · ctrl+d daily log", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self.theme = "textual-dark"
        self.refresh_notes()
        self.set_interval(0.7, self.autosave)
        self.query_one(TextArea).focus()
        if self.vault.warnings:
            self.notify("Some Markdown files could not be read. Run jotline list to inspect warnings.", severity="warning")

    def refresh_notes(self) -> None:
        notes = self.vault.search(self.query_one("#search", Input).value, self.collection)
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

    @on(Input.Changed, "#search")
    def search_changed(self) -> None:
        self.refresh_notes()

    @on(OptionList.OptionSelected, "#notes")
    def note_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.load_id(event.option.id)

    @on(TextArea.Changed, "#editor")
    def edited(self) -> None:
        text = self.query_one(TextArea).text
        if text != self.current.body:
            self.current.body = text
            self.dirty = True
            self.status("Saving…")

    def status(self, message: str) -> None:
        self.query_one("#status", Static).update(f"{message}  ·  {len(self.current.body.split())} words  ·  {self.current.collection}")
        self.query_one("#note-heading", Static).update(Text(self.current.title + " / " + self.current.collection))

    def save_current(self) -> bool:
        # Capture the buffer synchronously even when its Changed message is pending.
        body = self.query_one(TextArea).text
        if body != self.current.body:
            self.current.body, self.dirty = body, True
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
        self.query_one("#connections", Static).update(f"← {len(backlinks)} backlinks" + (f"  {summary}" if summary else "  ·  ctrl+p → Insert note link"))

    def load(self, note: Note) -> None:
        self.current, self.dirty, self.last_error = note, False, ""
        self.query_one(TextArea).load_text(note.body)
        self.query_one(TextArea).focus()
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
            self.load(self.vault.new())

    def action_daily(self) -> None:
        if self.save_current():
            self.load(self.vault.daily())
            editor = self.query_one(TextArea)
            lines = editor.text.split("\n")
            editor.move_cursor((len(lines) - 1, len(lines[-1])))

    def action_search(self) -> None:
        self.collection = "all"
        self.focused_writing = False
        self.query_one("#sidebar").remove_class("hidden")
        self.refresh_notes()
        self.query_one("#search", Input).focus()

    def action_editor_focus(self) -> None:
        self.query_one(TextArea).focus()

    def action_save(self) -> None:
        self.save_current()

    def action_quit(self) -> None:
        if self.save_current():
            self.exit()

    def action_focus_mode(self) -> None:
        self.focused_writing = not self.focused_writing
        self.query_one("#sidebar").set_class(self.focused_writing, "hidden")
        self.query_one("#hint").set_class(self.focused_writing, "hidden")
        self.query_one(TextArea).focus()

    def action_open_note(self) -> None:
        notes = self.vault.search()
        self.push_screen(Palette([(n.id, n.title + " · " + n.collection) for n in notes], "Open a note"),
                         lambda key: self.load_id(key) if key else None)

    def action_commands(self) -> None:
        choices = [("new", "New thought                    ctrl+n"), ("daily", "Open today's daily log         ctrl+d"),
                   ("open", "Open a note                    ctrl+o"), ("focus", "Toggle focus mode              ctrl+b"),
                   ("star", "Toggle star on this note"), ("link", "Insert note link"), ("follow", "Follow a link in this note"),
                   ("backlinks", "Open a backlink"), ("task", "Toggle task on current line"),
                   ("copy", "Copy note to clipboard (terminal OSC 52)"), ("recovery", "Save recovery copy"),
                   ("review", "Start weekly review"), ("help", "Open writing and workflow guide")]
        choices += [("view:" + c, "Show " + c) for c in ("all", "starred", *COLLECTIONS)]
        choices += [("move:" + c, "Move note to " + c) for c in COLLECTIONS]
        self.push_screen(Palette(choices), self.command)

    def command(self, key: str | None) -> None:
        if not key:
            return
        if key.startswith("view:"):
            self.collection = key[5:]
            self.query_one("#search", Input).value = ""
            self.refresh_notes()
            self.query_one("#sidebar").remove_class("hidden")
            self.focused_writing = False
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
            self.copy_to_clipboard(self.query_one(TextArea).text)
            self.notify("Copy requested. Your terminal must allow OSC 52 clipboard access.")
        elif key == "task":
            editor = self.query_one(TextArea)
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
            self.current.body = self.query_one(TextArea).text
            try:
                self.load(self.vault.recovery(self.current))
                self.refresh_notes()
                self.notify("Saved a separate recovery copy in the inbox.")
            except OSError as error:
                self.notify(str(error), severity="error")
        elif key in {"link", "follow", "backlinks"}:
            self.current.body = self.query_one(TextArea).text
            notes = self.vault.search()
            if key == "follow":
                notes = [n for n in notes if n.id in self.current.links or n.title in self.current.links]
            elif key == "backlinks":
                notes = self.vault.backlinks(self.current)
            else:
                notes = [n for n in notes if n.id != self.current.id]
            if not notes:
                self.notify("No matching notes yet.")
                return
            def picked(note_id):
                if note_id and key == "link":
                    note = next(n for n in notes if n.id == note_id)
                    label = note.title.replace("]", "").replace("|", "")
                    self.query_one(TextArea).insert(f"[[{note.id}|{label}]]")
                    self.query_one(TextArea).focus()
                elif note_id:
                    self.load_id(note_id)
            self.push_screen(Palette([(n.id, n.title) for n in notes], "Choose a note"), picked)
        elif key in {"help", "review"}:
            if self.save_current():
                body = GUIDE if key == "help" else REVIEW
                self.load(self.vault.new(body))
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

## Writing
Use Markdown: # headings, **emphasis**, - lists, and - [ ] tasks.
Add #tags anywhere; search #tag to find exact tag matches.
Ctrl+P → Toggle task checks or unchecks the current line.
Ctrl+B hides the sidebar. Ctrl+O finds a note by title.
Ctrl+F searches all notes (except trash). Multiple words narrow results.
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
