"""A small capture editor, sized for a floating window opened from a global hotkey."""
from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static, TextArea

from .markdown_editor import JOTLINE_THEME

HINT = "Ctrl+S save · Esc cancel"


class QuickCapture(App[str | None]):
    """Returns the typed text on save, or None when cancelled or empty."""

    TITLE = "jotline capture"
    CSS = """
    Screen { background: $background; color: $foreground; }
    #capture-title { height: 2; padding: 1 2 0 2; color: $accent; text-style: bold; }
    #capture-editor { height: 1fr; border: none; background: $background; margin: 0 1; }
    #capture-hint { height: 1; padding: 0 2; color: $text-muted; }
    """
    BINDINGS = [Binding("ctrl+s", "save", "Save", priority=True),
                Binding("escape", "cancel", "Cancel", priority=True)]

    def __init__(self, destination: str, theme: str = "jotline"):
        super().__init__()
        self.destination = destination
        self.preferred_theme = theme
        self.discard_armed = False
        self.register_theme(JOTLINE_THEME)

    def compose(self) -> ComposeResult:
        yield Static("›_ jotline  ·  " + self.destination, id="capture-title", markup=False)
        yield TextArea("", soft_wrap=True, tab_behavior="focus", id="capture-editor")
        yield Static(HINT, id="capture-hint", markup=False)

    def on_mount(self) -> None:
        if self.preferred_theme in self.available_themes:
            self.theme = self.preferred_theme
        self.query_one(TextArea).focus()

    def action_save(self) -> None:
        text = self.query_one(TextArea).text
        self.exit(text if text.strip() else None)

    def action_quit(self) -> None:
        # Ctrl+Q never throws typed text away.
        self.action_save()

    def action_cancel(self) -> None:
        if self.query_one(TextArea).text.strip() and not self.discard_armed:
            self.discard_armed = True
            self.query_one("#capture-hint", Static).update("Press Esc again to discard · Ctrl+S saves")
            return
        self.exit(None)

    @on(TextArea.Changed)
    def edited(self) -> None:
        if self.discard_armed:
            self.discard_armed = False
            self.query_one("#capture-hint", Static).update(HINT)
