"""Keyboard-accessible preferences with explicit Save and Cancel."""
from dataclasses import asdict
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Select, Static, Switch, TextArea

from .modal import Modal
from .settings import BOOLEAN_SETTINGS, DEFAULT_COLLECTIONS, HOTKEY_ACTIONS, Settings, THEMES


class Preferences(Modal[Settings | None]):
    BINDINGS = [Binding('escape', 'cancel', 'Cancel'), Binding('ctrl+s', 'save', 'Save settings', priority=True),
                Binding('alt+1', 'jump("appearance")', 'Appearance'),
                Binding('alt+2', 'jump("editor")', 'Editor'),
                Binding('alt+3', 'jump("shortcuts")', 'Shortcuts'),
                Binding('alt+4', 'jump("template")', 'Daily template')]
    CSS = '''
    Preferences { align: center middle; background: $background 80%; }
    #preferences { width: 78; max-width: 96%; height: 90%; border: round $accent; padding: 1 2; background: $surface; }
    #preferences-title { height: 2; color: $accent; text-style: bold; }
    #preferences-outline { height: auto; color: $text-muted; margin-bottom: 1; }
    #preferences-scroll { height: 1fr; }
    .pref-section { color: $accent; text-style: bold; margin-top: 2; }
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
            yield Static('Alt+1 Appearance · Alt+2 Editor · Alt+3 Shortcuts · Alt+4 Daily template',
                         id='preferences-outline')
            with VerticalScroll(id='preferences-scroll'):
                yield Label('Appearance', classes='pref-section')
                yield Label('Theme', classes='pref-label')
                yield Select([('Omarchy (follow desktop)' if t == 'omarchy' else t.replace('-', ' ').title(), t)
                              for t in THEMES], value=s.theme, allow_blank=False, id='pref-theme',
                             tooltip='Color theme')
                for name, title, options in (
                    ('sort_order', 'Sort notes (stars stay first)', [('Last edited', 'updated'), ('Newest created', 'created'), ('Title A–Z', 'title')]),
                    ('startup', 'When Jotline opens', [('Blank thought', 'new'), ("Today’s daily log", 'daily')]),
                    ('default_collection', 'New thoughts go to', [(c.title(), c) for c in DEFAULT_COLLECTIONS]),
                ):
                    yield Label(title, classes='pref-label')
                    yield Select(options, value=getattr(s, name), allow_blank=False, id='pref-' + name,
                                 tooltip=title)
                yield Label('Editor and layout', classes='pref-section')
                for name, title in (('line_numbers', 'Line numbers'), ('soft_wrap', 'Wrap long lines'),
                                    ('highlight_line', 'Highlight current line'),
                                    ('markdown_highlighting', 'Highlight Markdown syntax'),
                                    ('smart_lists', 'Continue lists and quotes on Enter'),
                                    ('focus_on_start', 'Start in focus mode'),
                                    ('show_hints', 'Show writing hints'),
                                    ('outliner_on_start', 'Open notes in outliner mode')):
                    with Horizontal(classes='pref-toggle'):
                        yield Label(title)
                        yield Switch(getattr(s, name), id='pref-' + name, tooltip=title)
                yield Label('Sidebar width · 22–60 columns', classes='pref-label')
                yield Input(str(s.sidebar_width), type='integer', id='pref-sidebar_width',
                            tooltip='Sidebar width in columns')
                yield Label('Autosave interval · 0.2–5 seconds', classes='pref-label')
                yield Input(str(s.autosave_seconds), type='number', id='pref-autosave_seconds',
                            tooltip='Autosave interval in seconds')
                yield Label('Keyboard shortcuts', classes='pref-section')
                yield Static('Use ctrl+letter, alt+letter, or f2–f12. Editing keys are reserved. '
                             'Leave optional Markdown shortcuts blank to keep them unassigned. '
                             'Ctrl+, always opens Settings; Esc closes dialogs. Ctrl+S saves this dialog. Changes apply when saved.')
                hotkeys = s.effective_hotkeys
                for action, (default, label) in HOTKEY_ACTIONS.items():
                    yield Label(label, classes='pref-label')
                    yield Input(hotkeys[action], placeholder='Unassigned' if not default else '',
                                id='hotkey-' + action, tooltip=label)
                yield Label('Outliner shortcuts', classes='pref-section')
                yield Static('Optional overrides for outline commands. All commands are also in the outliner menu.')
                from .outliner_ui import ACTIONS
                for action, label in ACTIONS.items():
                    yield Label(label, classes='pref-label')
                    yield Input(s.outline_hotkeys.get(action, ''), id='outline-hotkey-' + action,
                                placeholder='Use default / menu', tooltip=label)
                yield Button('Reset hotkeys', id='reset-hotkeys')
                yield Label('Daily template', classes='pref-section')
                yield Label('Daily template · {{date}} becomes today’s date; existing logs stay unchanged', classes='pref-label')
                yield TextArea(s.daily_template, tab_behavior='focus', id='daily-template',
                               tooltip='Daily log template. {{date}} becomes today’s date.')
            yield Static('', id='preferences-error', markup=False)
            with Horizontal(id='preferences-buttons'):
                yield Button('Save', variant='primary', id='save-preferences')
                yield Button('Cancel', id='cancel-preferences')
                yield Button('Use defaults', id='default-preferences')

    def action_jump(self, section: str):
        targets = {
            'appearance': '#pref-theme',
            'editor': '#pref-sidebar_width',
            'shortcuts': '#hotkey-new',
            'template': '#daily-template',
        }
        if target := targets.get(section):
            self.query_one(target).focus(scroll_visible=True)

    def action_save(self):
        try:
            data = asdict(self.settings)
            for name in ('theme', 'sort_order', 'startup', 'default_collection'):
                data[name] = self.query_one('#pref-' + name, Select).value
            for name in BOOLEAN_SETTINGS:
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
            data['hotkeys'] = {action: self.query_one('#hotkey-' + action, Input).value.strip().lower()
                               for action in HOTKEY_ACTIONS}
            from .outliner_ui import ACTIONS
            data['outline_hotkeys'] = {action: self.query_one('#outline-hotkey-' + action, Input).value.strip().lower()
                                       for action in ACTIONS
                                       if self.query_one('#outline-hotkey-' + action, Input).value.strip()}
            data['daily_template'] = self.query_one('#daily-template', TextArea).text
            settings = Settings(**data)
            settings.validate()
        except ValueError as error:
            self.query_one('#preferences-error', Static).update(str(error))
            return
        self.dismiss(settings)

    def reset_hotkeys(self):
        from .outliner_ui import ACTIONS
        for action in ACTIONS:
            self.query_one('#outline-hotkey-' + action, Input).value = ''
        for action, (key, _) in HOTKEY_ACTIONS.items():
            self.query_one('#hotkey-' + action, Input).value = key

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == 'save-preferences':
            self.action_save()
        elif event.button.id == 'cancel-preferences':
            self.action_cancel()
        elif event.button.id == 'reset-hotkeys':
            self.reset_hotkeys()
            self.query_one('#preferences-error', Static).update('Default hotkeys loaded. Save to apply.')
        elif event.button.id == 'default-preferences':
            defaults = Settings()
            for name, value in asdict(defaults).items():
                if name == 'hotkeys':
                    self.reset_hotkeys()
                    continue
                if name in ('active_workspace', 'workspace_names', 'saved_views', 'actions', '_baseline', 'outline_hotkeys'):
                    continue
                if name == 'daily_template':
                    self.query_one('#daily-template', TextArea).load_text(value)
                else:
                    widget = self.query_one('#pref-' + name)
                    widget.value = str(value) if isinstance(widget, Input) else value
            self.query_one('#preferences-error', Static).update('Defaults loaded. Save to apply, or Cancel to keep your settings.')
