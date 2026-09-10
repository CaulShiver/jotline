"""Keyboard-accessible preferences with explicit Save and Cancel."""
from dataclasses import asdict
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, Switch, TextArea
from .settings import Settings, THEMES


class Preferences(ModalScreen[Settings | None]):
    BINDINGS = [Binding('escape', 'cancel', 'Cancel'), Binding('ctrl+s', 'save', 'Save settings', priority=True)]
    CSS = '''
    Preferences { align: center middle; background: $background 80%; }
    #preferences { width: 78; max-width: 96%; height: 90%; border: round $accent; padding: 1 2; background: $surface; }
    #preferences-title { height: 2; color: $accent; text-style: bold; }
    #preferences-scroll { height: 1fr; }
    .pref-label { margin-top: 1; }
    .pref-toggle { height: 3; align-vertical: middle; }
    .pref-toggle Label { width: 1fr; padding-top: 1; }
    #daily-template { height: 8; border: tall $primary-muted; }
    #preferences-error { height: auto; color: $error; }
    #preferences-buttons { height: 3; margin-top: 1; }
    #preferences-buttons Button { margin-right: 1; }
    '''

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings

    def compose(self) -> ComposeResult:
        s = self.settings
        with Vertical(id='preferences'):
            yield Label('Make Jotline yours', id='preferences-title')
            with VerticalScroll(id='preferences-scroll'):
                yield Label('Theme', classes='pref-label')
                yield Select([(t.replace('-', ' ').title(), t) for t in THEMES], value=s.theme, allow_blank=False, id='pref-theme')
                for name, title, options in (
                    ('sort_order', 'Sort notes (stars stay first)', [('Last edited', 'updated'), ('Newest created', 'created'), ('Title A–Z', 'title')]),
                    ('startup', 'When Jotline opens', [('Blank thought', 'new'), ("Today’s daily log", 'daily')]),
                    ('default_collection', 'New thoughts go to', [(c.title(), c) for c in ('inbox', 'projects', 'areas', 'resources')]),
                ):
                    yield Label(title, classes='pref-label')
                    yield Select(options, value=getattr(s, name), allow_blank=False, id='pref-' + name)
                for name, title in (('line_numbers', 'Line numbers'), ('soft_wrap', 'Wrap long lines'),
                                    ('highlight_line', 'Highlight current line'), ('focus_on_start', 'Start in focus mode'),
                                    ('show_hints', 'Show writing hints')):
                    with Horizontal(classes='pref-toggle'):
                        yield Label(title)
                        yield Switch(getattr(s, name), id='pref-' + name)
                yield Label('Sidebar width · 22–60 columns', classes='pref-label')
                yield Input(str(s.sidebar_width), type='integer', id='pref-sidebar_width')
                yield Label('Autosave interval · 0.2–5 seconds', classes='pref-label')
                yield Input(str(s.autosave_seconds), type='number', id='pref-autosave_seconds')
                yield Label('Daily template · {{date}} becomes today’s date; existing logs stay unchanged', classes='pref-label')
                yield TextArea(s.daily_template, tab_behavior='focus', id='daily-template')
            yield Static('', id='preferences-error', markup=False)
            with Horizontal(id='preferences-buttons'):
                yield Button('Save', variant='primary', id='save-preferences')
                yield Button('Cancel', id='cancel-preferences')
                yield Button('Use defaults', id='default-preferences')

    def action_cancel(self):
        self.dismiss(None)

    def action_save(self):
        try:
            data = asdict(self.settings)
            for name in ('theme', 'sort_order', 'startup', 'default_collection'):
                data[name] = self.query_one('#pref-' + name, Select).value
            for name in ('line_numbers', 'soft_wrap', 'highlight_line', 'focus_on_start', 'show_hints'):
                data[name] = self.query_one('#pref-' + name, Switch).value
            sidebar_width = self.query_one('#pref-sidebar_width', Input).value.strip()
            autosave_seconds = self.query_one('#pref-autosave_seconds', Input).value.strip()
            if not sidebar_width:
                raise ValueError('Sidebar width is required')
            if not autosave_seconds:
                raise ValueError('Autosave interval is required')
            try:
                data['sidebar_width'] = int(sidebar_width)
            except ValueError:
                raise ValueError('Sidebar width must be a whole number') from None
            try:
                data['autosave_seconds'] = float(autosave_seconds)
            except ValueError:
                raise ValueError('Autosave interval must be a number') from None
            data['daily_template'] = self.query_one('#daily-template', TextArea).text
            settings = Settings(**data)
            settings.validate()
        except ValueError as error:
            self.query_one('#preferences-error', Static).update(str(error))
            return
        self.dismiss(settings)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == 'save-preferences':
            self.action_save()
        elif event.button.id == 'cancel-preferences':
            self.action_cancel()
        elif event.button.id == 'default-preferences':
            defaults = Settings()
            for name, value in asdict(defaults).items():
                if name in ('active_workspace', 'workspace_names'):
                    continue
                if name == 'daily_template':
                    self.query_one('#daily-template', TextArea).load_text(value)
                else:
                    widget = self.query_one('#pref-' + name)
                    widget.value = str(value) if isinstance(widget, Input) else value
            self.query_one('#preferences-error', Static).update('Defaults loaded. Save to apply, or Cancel to keep your settings.')
