"""Standalone modal screens used by the writing app."""
from __future__ import annotations

import re

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Markdown, Static, Switch, TextArea
from rich.text import Text

from .links import wiki_target_from_href
from .limits import EDIT_LIMIT_BYTES
from .markdown_editor import MarkdownEditor
from .modal import Modal
from .store import Note


class MarkdownPreview(Modal[None]):
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
            yield Label("Markdown preview · Esc to return to writing"
                        + (" · raw HTML blocks are not rendered" if re.search(r"^ {0,3}<[A-Za-z!?/]", self.body, re.M) else ""))
            with VerticalScroll(id="markdown-scroll"):
                # Let Markdown own its initial render during its mount lifecycle.
                # A second update from the parent mount can race its empty render.
                yield Markdown(self.body, open_links=False)
            yield Button("Back to writing", id="close-preview")

    def on_mount(self) -> None:
        self.query_one(VerticalScroll).focus()

    @on(Markdown.LinkClicked)
    def follow_preview_link(self, event: Markdown.LinkClicked) -> None:
        event.stop()
        if target := wiki_target_from_href(event.href):
            self.dismiss(None)
            self.app.follow_wiki_target(target)

    @on(Button.Pressed, "#close-preview")
    def action_done(self) -> None:
        self.dismiss(None)
        self.app.query_one("#editor", TextArea).focus()


class RevisionPreview(Modal[bool]):
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
            yield TextArea(self.note.body, read_only=True, soft_wrap=False, id="revision-text",
                           tooltip="Saved version of this note")
            with Horizontal(id="revision-buttons"):
                yield Button("Restore as new note", variant="primary", id="restore-revision")
                yield Button("Cancel", id="cancel-revision")

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "restore-revision")


class FindInNote(Modal[None]):
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
            yield Input(placeholder="Type text to find…", id="find-query", tooltip="Find text in this note")
            yield Input(placeholder="Replace with…", id="replace-value", tooltip="Replacement text")
            yield Label("Match case")
            yield Switch(False, id="find-case", tooltip="Match case")
            with Horizontal(id="replace-buttons"):
                yield Button("Replace", id="replace-one")
                yield Button("Replace all", id="replace-all")
            yield Static("Enter / F3 next · Shift+F3 previous · Esc done", id="find-status")
            yield Static("", id="find-context", markup=False)
            with Horizontal(id="find-buttons"):
                yield Button("Next", variant="primary", id="find-next")
                yield Button("Previous", id="find-previous")
                yield Button("Done", id="find-done")

    def editor(self) -> MarkdownEditor:
        return self.app.query_one("#editor", MarkdownEditor)

    def on_mount(self) -> None:
        editor = self.editor()
        self.anchor = editor.char_offset(editor.cursor_location, editor.text)
        self.query_one("#find-query", Input).focus()

    def show_match(self, *, reverse: bool = False, initial: bool = False) -> None:
        query = self.query_one("#find-query", Input).value
        status = self.query_one("#find-status", Static)
        if not query:
            status.update("Enter / F3 next · Shift+F3 previous · Esc done")
            self.query_one("#find-context", Static).update("")
            return
        result = self.editor().select_match(
            query, reverse=reverse, anchor=self.anchor if initial else None,
            case_sensitive=self.case_sensitive)
        if result is None:
            status.update("No matches · keep typing or Esc to return")
            self.query_one("#find-context", Static).update("")
        else:
            current, total = result
            status.update(f"Match {current} of {total} · Enter / F3 next · Shift+F3 previous")
            self.update_context()

    def update_context(self) -> None:
        editor = self.editor()
        row, start = editor.selection.start
        _, end = editor.selection.end
        line = editor.document.get_line(row)
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

    def replace_matches(self, *, all_matches: bool = False) -> None:
        query = self.query_one("#find-query", Input).value
        if not query:
            return
        editor = self.editor()
        status = self.query_one("#find-status", Static)
        pattern = re.compile(re.escape(query), 0 if self.case_sensitive else re.IGNORECASE)
        replacement = self.query_one("#replace-value", Input).value
        if all_matches:
            replacement_bytes = len(replacement.encode("utf-8"))
            output_bytes = len(editor.text.encode("utf-8")) + sum(
                replacement_bytes - len(match[0].encode("utf-8"))
                for match in pattern.finditer(editor.text))
            if output_bytes > EDIT_LIMIT_BYTES:
                self.app.notify("Replacement exceeds the note size limit", severity="error")
                status.update("Not replaced · note size limit exceeded")
                return
            body, count = pattern.subn(lambda match: replacement, editor.text)
            if count and not editor.replace_checked(body, limit=EDIT_LIMIT_BYTES):
                status.update("Not replaced · note size limit exceeded")
                return
        else:
            if not pattern.fullmatch(editor.selected_text):
                self.show_match(initial=True)
            if not pattern.fullmatch(editor.selected_text):
                return
            if not editor.insert_checked(replacement, limit=EDIT_LIMIT_BYTES):
                status.update("Not replaced · note size limit exceeded")
                return
            count = 1
        self.show_match()
        status.update(f"Replaced {count} match(es) · Undo in editor to reverse")

    def action_next(self) -> None:
        self.show_match()

    def action_previous(self) -> None:
        self.show_match(reverse=True)

    def action_done(self) -> None:
        self.dismiss(None)
        self.editor().focus()
