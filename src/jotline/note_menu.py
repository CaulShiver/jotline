"""Mouse and keyboard context menus for notes in the sidebar."""
from rich.text import Text
from textual import events, on
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option, OptionDoesNotExist

from .modal import Modal

TRASH_CONFIRM = "Move to Trash? Enter"


class NoteList(OptionList):
    BINDINGS = [Binding('shift+f10', 'note_menu', 'Note actions', show=False),
                Binding('delete', 'trash_note', 'Move to Trash', show=False)]

    class ContextRequested(Message):
        def __init__(self, note_id: str, x: int, y: int):
            super().__init__()
            self.note_id, self.x, self.y = note_id, x, y

    class TrashRequested(Message):
        def __init__(self, note_id: str):
            super().__init__()
            self.note_id = note_id

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._confirm_id: str | None = None
        self._confirm_prompt = None

    def _on_click(self, event: events.Click) -> None:
        if event.button == 1:
            return  # Let OptionList handle normal selection.
        event.prevent_default()
        event.stop()
        if event.button == 3:
            # Use the rendered row metadata, which includes scrolling and wraps.
            index = event.style.meta.get('option')
            if isinstance(index, int) and 0 <= index < self.option_count:
                option = self.get_option_at_index(index)
                if option.id and not option.disabled:
                    self.highlighted = index
                    self.post_message(self.ContextRequested(option.id, event.screen_x, event.screen_y))

    def action_note_menu(self) -> None:
        if self.highlighted is not None:
            option = self.get_option_at_index(self.highlighted)
            if option.id and not option.disabled:
                self.post_message(self.ContextRequested(option.id, self.region.x + 2, self.region.y))

    def clear_options(self):
        self._confirm_id = None
        self._confirm_prompt = None
        return super().clear_options()

    def on_blur(self) -> None:
        self._clear_confirm(restore=True)

    def on_key(self, event: events.Key) -> None:
        # Enter confirms and Delete keeps the prompt. Any other key drops it
        # so the list goes back to opening notes.
        if self._confirm_id and event.key not in {"enter", "delete"}:
            self._clear_confirm(restore=True)

    def action_select(self) -> None:
        if self._confirm_id and self.highlighted is not None:
            option = self.get_option_at_index(self.highlighted)
            if option.id == self._confirm_id:
                note_id = option.id
                self._clear_confirm(restore=False)
                self.post_message(self.TrashRequested(note_id))
                return
            self._clear_confirm(restore=True)
        super().action_select()

    def action_trash_note(self) -> None:
        if self.highlighted is None:
            return
        option = self.get_option_at_index(self.highlighted)
        if not option.id or option.disabled or option.id == self._confirm_id:
            return
        self._clear_confirm(restore=True)
        self._confirm_id = option.id
        self._confirm_prompt = option.prompt
        self.replace_option_prompt(option.id, Text(TRASH_CONFIRM))

    def _clear_confirm(self, *, restore: bool) -> None:
        option_id = self._confirm_id
        prompt = self._confirm_prompt
        self._confirm_id = None
        self._confirm_prompt = None
        if not restore or option_id is None or prompt is None:
            return
        try:
            self.replace_option_prompt(option_id, prompt)
        except OptionDoesNotExist:
            return


class NoteMenuOptions(OptionList):
    """Keep the menu's selected row aligned with the mouse pointer."""

    def _on_mouse_move(self, event: events.MouseMove) -> None:
        super()._on_mouse_move(event)
        index = event.style.meta.get('option')
        if isinstance(index, int) and 0 <= index < self.option_count:
            option = self.get_option_at_index(index)
            if not option.disabled:
                self.highlighted = index


class NoteMenu(Modal[str | None]):
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]
    CSS = '''
    NoteMenu { align: left top; background: transparent; }
    #note-menu { width: 38; max-width: 100%; height: auto; max-height: 100%;
        border: round $accent; background: $surface; padding: 0 1; }
    #note-menu-title { height: 1; color: $accent; text-style: bold; }
    #note-menu-options { height: auto; max-height: 12; border: none; background: $surface; }
    '''

    def __init__(self, title: str, choices: list[tuple[str, str]], x: int, y: int):
        super().__init__()
        self.title_text, self.choices, self.x, self.y = title, choices, x, y

    def compose(self):
        with Vertical(id='note-menu'):
            yield Label(Text(self.title_text), id='note-menu-title')
            yield NoteMenuOptions(*(Option(Text(label), id=key) for key, label in self.choices), id='note-menu-options')

    def on_mount(self):
        panel = self.query_one('#note-menu')
        panel.styles.offset = (max(0, min(self.x, self.size.width - 38)),
                               max(0, min(self.y, self.size.height - len(self.choices) - 3)))
        options = self.query_one(OptionList)
        options.highlighted = 0
        options.focus()

    @on(OptionList.OptionSelected)
    def selected(self, event: OptionList.OptionSelected):
        event.stop()
        self.dismiss(event.option.id)

    def on_click(self, event: events.Click):
        if not self.query_one('#note-menu').region.contains(event.screen_x, event.screen_y):
            event.stop()
            self.dismiss(None)
