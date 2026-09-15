"""Modal screens that ignore a second dismissal.

Input.Submitted and OptionList.OptionSelected arrive through the widget queue,
so a key-repeat Enter or a mouse double-click can deliver two dismiss triggers
before the first pop completes. Textual's Screen.dismiss has no guard: a second
pop with one modal on the stack raises ScreenStackError and ends the app, and
with nested modals it silently pops the parent without its result callback.
"""
from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen, ScreenResultType
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option
from rich.text import Text


class Modal(ModalScreen[ScreenResultType]):
    _dismissed = False

    def dismiss(self, result: ScreenResultType | None = None):
        if self._dismissed or self.app.screen is not self:
            return None
        self._dismissed = True
        return super().dismiss(result)

    def action_cancel(self) -> None:
        """The default Escape binding target: close with no result."""
        self.dismiss(None)


class Palette(Modal[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CSS = """
    Palette { align: center top; background: $background 70%; }
    #palette { width: 76; max-width: 95%; height: 80%; max-height: 80%; margin-top: 3;
        border: round $accent; padding: 1 2; background: $surface; }
    #palette-title { color: $accent; margin-bottom: 1; }
    #palette-help, #command-count { color: $text-muted; }
    #commands { height: 1fr; min-height: 3; border: none; }
    """

    def __init__(self, choices: list[tuple[str, str]], title: str = "Run a command",
                 *, everyday: frozenset[str] | None = None):
        super().__init__()
        self.choices = choices
        self.heading = title
        self.everyday = everyday
        self.filtered = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="palette"):
            yield Label(self.heading, id="palette-title")
            yield Input(placeholder="Type to filter…", id="command-query",
                        tooltip="Filter commands by name")
            yield Static("Type to filter · ↑↓ choose · Enter run · Esc cancel", id="palette-help")
            yield Static("", id="command-count", markup=False)
            yield OptionList(id="commands")

    def on_mount(self) -> None:
        self.filter("")
        self.query_one(Input).focus()

    def filter(self, query: str) -> None:
        terms = query.casefold().split()
        pool = self.choices
        if not terms and self.everyday is not None:
            pool = [(key, label) for key, label in self.choices if key in self.everyday]
        self.filtered = [(key, label) for key, label in pool if all(t in label.casefold() for t in terms)]
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([Option(Text(label), id=key) for key, label in self.filtered])
        count = self.query_one("#command-count", Static)
        hidden = 0 if self.everyday is None else len(self.choices) - len(pool)
        if self.filtered:
            count.update(f"{len(self.filtered)} result" + ("" if len(self.filtered) == 1 else "s")
                         + (f" · type to see {hidden} more" if hidden else ""))
        else:
            count.update("No matching commands · adjust the filter or press Esc")
        help_text = self.query_one("#palette-help", Static)
        if hidden:
            help_text.update("Everyday commands · type to see format, move, export, encryption")
        else:
            help_text.update("Type to filter · ↑↓ choose · Enter run · Esc cancel")
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


class TextPrompt(Modal[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CSS = """
    TextPrompt { align: center top; background: $background 70%; }
    #text-prompt { width: 72; max-width: 95%; height: auto; margin-top: 3;
        border: round $accent; padding: 1 2; background: $surface; }
    """

    def __init__(self, title: str, placeholder: str, value: str = "", *, password: bool = False):
        super().__init__()
        self.heading, self.placeholder, self.value, self.password = title, placeholder, value, password

    def compose(self) -> ComposeResult:
        with Vertical(id="text-prompt"):
            yield Label(self.heading)
            yield Input(self.value, placeholder=self.placeholder, password=self.password, id="prompt-value",
                        tooltip=self.heading)
            yield Static("Enter to apply · Esc to cancel")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        # Spaces are part of a passphrase; trimming them would lock the user out.
        self.dismiss((event.value if self.password else event.value.strip()) or None)
