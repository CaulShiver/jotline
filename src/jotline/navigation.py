"""Discoverable navigation and editable saved searches."""
from dataclasses import replace

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Label, Select, Static, TextArea
from rich.text import Text

from .modal import Modal, Palette
from .settings import HOTKEY_ACTIONS, SORT_ORDERS, THEMES, VIEW_COLLECTIONS
from .store import validate_workspace


class ViewEditor(Modal[tuple[str, dict] | None]):
    BINDINGS = [Binding('escape', 'cancel', 'Cancel'), Binding('ctrl+s', 'save_view', 'Apply')]
    CSS = '''
    ViewEditor { align: center middle; background: $background 80%; }
    #view-editor { width: 72; max-width: 96%; height: auto; max-height: 94%;
        padding: 1 2; border: round $accent; background: $surface; }
    #view-buttons { height: 3; }
    #view-error { height: auto; color: $error; }
    '''

    def __init__(self, name, view, settings, original=None, filters=False):
        super().__init__()
        self.view_name, self.view, self.settings = name, view, settings
        self.original, self.filters = original, filters

    def compose(self):
        with VerticalScroll(id='view-editor'):
            yield Label('Filter notes' if self.filters else 'Edit saved view' if self.original else 'Save a view')
            if not self.filters:
                yield Label('Name · lowercase letters, numbers, - or _')
                yield Input(self.view_name, placeholder='weekly-review', id='view-name',
                            tooltip='Saved view name')
            yield Label('Search · words, #tags, -excluded, updated-before:YYYY-MM-DD')
            yield Input(self.view['query'], id='view-query', placeholder='words or #tags',
                        tooltip='Search words, #tags, or date filters')
            yield Label('Collection')
            yield Select([(x.title(), x) for x in VIEW_COLLECTIONS],
                         value=self.view['collection'], allow_blank=False, id='view-collection',
                         tooltip='Collection to show')
            yield Label('Sort')
            yield Select([(x.title(), x) for x in SORT_ORDERS],
                         value=self.view['sort'], allow_blank=False, id='view-sort',
                         tooltip='Sort order')
            yield Label('Theme')
            yield Select([('Use settings theme', '')] + [(x, x) for x in THEMES],
                         value=self.view['theme'], allow_blank=False, id='view-theme',
                         tooltip='Theme for this view')
            yield Static('', id='view-error', markup=False)
            with Horizontal(id='view-buttons'):
                yield Button('Apply' if self.filters else 'Save', variant='primary', id='view-save')
                yield Button('Cancel', id='view-cancel')

    @on(Button.Pressed, '#view-cancel')
    def cancel_button(self):
        self.action_cancel()

    def action_save_view(self):
        self.save()

    @on(Button.Pressed, '#view-save')
    def save(self):
        name = 'filter-preview' if self.filters else self.query_one('#view-name', Input).value.strip()
        view = dict(workspace=self.view['workspace'], query=self.query_one('#view-query', Input).value,
                    collection=self.query_one('#view-collection', Select).value,
                    sort=self.query_one('#view-sort', Select).value,
                    theme=self.query_one('#view-theme', Select).value)
        try:
            validate_workspace(name)
            if not self.filters and name != self.original and name in self.settings.saved_views:
                raise ValueError('That name is already used; choose a different name.')
            views = dict(self.settings.saved_views)
            if self.original:
                views.pop(self.original, None)
            views[name] = view
            replace(self.settings, saved_views={name: view} if self.filters else views).validate()
        except ValueError as error:
            self.query_one('#view-error', Static).update(str(error))
            return
        self.dismiss((name, view))


class Walkthrough(Modal[None]):
    BINDINGS = [Binding('escape', 'done', 'Back to writing')]
    CSS = """
    Walkthrough { align: center middle; background: $background 80%; }
    #walkthrough-panel { width: 82; max-width: 96%; height: auto; max-height: 90%;
        border: round $accent; padding: 1 2; background: $surface; }
    #walkthrough-text { height: auto; }
    """

    def __init__(self, body):
        super().__init__()
        self.body = body

    def compose(self):
        with VerticalScroll(id='walkthrough-panel'):
            yield Static(self.body, id='walkthrough-text', markup=False)
            yield Button('Back to writing', id='walkthrough-close')

    @on(Button.Pressed, '#walkthrough-close')
    def action_done(self):
        self.dismiss(None)
        self.app.query_one('#editor', TextArea).focus()


KEY_GROUPS = (
    ('Writing', ('save', 'toggle_task', 'focus_mode', 'preview', 'live_preview', 'extract_note', 'external_editor')),
    ('Finding', ('search', 'open_note', 'recent', 'previous_note', 'follow_link', 'backlinks', 'find_in_note',
                 'outline', 'tags')),
    ('Notes', ('new', 'daily', 'daily_previous', 'daily_next', 'daily_date', 'process_inbox', 'workspaces',
               'outliner')),
    ('App', ('commands', 'keys', 'quit')),
)
EDITOR_KEYS = (('Tab / Shift+Tab', 'Indent / outdent a list item'), ('[[', 'Link to a note'),
               (';;', 'Insert a snippet'), ('Ctrl+click', 'Follow the link under the pointer'),
               ('Esc', 'Back to the editor from the sidebar'))
SEARCH_KEYS = (('Enter', 'Open the top result'), ('Down', 'Move into the note list'),
               ('Esc', 'Clear the search; again to return to writing'))
OUTLINE_LABELS = {'back': 'Leave the block, then back to Markdown', 'commands': 'Outliner commands',
                  'edit_block': 'Edit the block', 'switch_pane': 'Switch between tree and block',
                  'extend(-1)': 'Extend selection up', 'extend(1)': 'Extend selection down'}
NAMES = {'ctrl': 'Ctrl', 'alt': 'Alt', 'shift': 'Shift', 'comma': ',', 'escape': 'Esc', 'enter': 'Enter',
         'tab': 'Tab', 'space': 'Space', 'backspace': 'Backspace', 'up': 'Up', 'down': 'Down',
         'left': 'Left', 'right': 'Right'}


def key_name(key: str) -> str:
    return '+'.join(NAMES.get(part, part.upper()) for part in key.split('+'))


def key_sheet(hotkeys: dict[str, str], outline: dict[str, list[str]]) -> Text:
    """The cheat sheet: every key in effect now, rebinds included."""
    text = Text()

    def section(title):
        text.append('\n' + title + '\n', style='bold')

    def row(keys, label):
        text.append(f'  {keys:<24}  ' if len(keys) <= 24 else f'  {keys}\n' + ' ' * 28)
        text.append(label + '\n')

    text.append('Keyboard shortcuts\n', style='bold')
    text.append('The keys in effect now, including your changes in Settings. Esc closes.\n')
    grouped = {action for _, actions in KEY_GROUPS for action in actions}
    writing = KEY_GROUPS[0][1] + tuple(action for action in HOTKEY_ACTIONS if action not in grouped)
    for title, actions in (('Writing', writing), *KEY_GROUPS[1:]):
        section(title)
        for action in actions:
            if key := hotkeys.get(action):
                row(key_name(key), HOTKEY_ACTIONS[action][1].removesuffix(' (optional)'))
        if title == 'App':
            row('Ctrl+,', 'Settings')
            row('Esc', 'Close a dialog')
    unassigned = sum(1 for action in HOTKEY_ACTIONS if not hotkeys.get(action))
    if unassigned:
        text.append(f'\n{unassigned} more commands have no key; run them from Ctrl+P, '
                    'or assign one in Settings → Keyboard shortcuts.\n')
    section('Editor')
    for keys, label in EDITOR_KEYS:
        row(keys, label)
    section('Search box')
    for keys, label in SEARCH_KEYS:
        row(keys, label)
    section('Outliner')
    from .outline_actions import ACTIONS
    for action, keys in outline.items():
        row(' / '.join(key_name(key) for key in keys), OUTLINE_LABELS.get(action) or ACTIONS.get(action, action))
    row('Tree: Up/Down Left/Right', 'Move · Space fold · Enter edit')
    row('Block: Enter', 'Split · Shift+Enter adds a line · Backspace at start merges')
    text.append('\n')
    if taken := [key for key in ('ctrl+w', 'ctrl+d') if key in hotkeys.values()]:
        lost = {'ctrl+w': 'delete-word-left', 'ctrl+d': 'delete-right'}
        both = len(taken) > 1
        text.append(' and '.join(map(key_name, taken)) + (' are Jotline commands' if both else ' is a Jotline command')
                    + ", so the editor's " + ' and '.join(lost[key] for key in taken) + (' are' if both else ' is')
                    + ' not available there; Alt+Backspace and Delete still work. ')
    text.append('Ctrl+, opens Settings; if your terminal swallows it, use Ctrl+P → Settings.\n')
    return text


class KeySheet(Modal[None]):
    BINDINGS = [Binding('escape', 'done', 'Close')]
    CSS = """
    KeySheet { align: center middle; background: $background 80%; }
    #keys-panel { width: 82; max-width: 96%; height: auto; max-height: 90%;
        border: round $accent; padding: 1 2; background: $surface; }
    #keys-text { height: auto; }
    """

    def __init__(self, body: Text):
        super().__init__()
        self.body = body

    def compose(self):
        with VerticalScroll(id='keys-panel'):
            yield Static(self.body, id='keys-text', markup=False)
            yield Button('Close', id='keys-close')

    def on_mount(self):
        self.query_one('#keys-panel').focus()

    @on(Button.Pressed, '#keys-close')
    def action_done(self):
        self.dismiss(None)


class Views:
    """Saved-view ownership. Bound onto Jotline; not inherited."""

    def navigation_commands(self, Command):
        return [Command('collections', 'Browse collections', self.browse_collections, group='everyday'),
                Command('save-view', 'Save current search as a view', self.save_view_prompt),
                Command('views', 'Open saved view', self.choose_view, group='everyday'),
                Command('delete-view', 'Delete saved view', lambda: self.choose_view(delete=True)),
                Command('clear-view', 'Clear view and search', self.clear_view, group='everyday'),
                Command('manage-views', 'Manage saved views · edit, rename, duplicate', self.manage_views),
                Command('filters', 'Edit search filters and sort', self.edit_filters, group='everyday'),
                Command('update-view', 'Update active saved view from current filters', self.update_active_view),
                Command('walkthrough', 'Quick start walkthrough', self.show_walkthrough, group='everyday'),
                Command('keys', 'Keyboard shortcuts', self.action_keys, 'keys', group='everyday')]

    def action_keys(self):
        from .outliner_ui import outline_keys
        self.push_screen(KeySheet(key_sheet(self.settings.effective_hotkeys,
                                            outline_keys(self.settings.outline_hotkeys))))

    def current_view(self):
        return dict(workspace=self.workspace, query=self.query_one('#search', Input).value,
                    collection=self.collection, sort=self.view_sort or self.settings.sort_order, theme=self.theme)

    def browse_collections(self):
        self.push_screen(Palette([(c, c.title()) for c in VIEW_COLLECTIONS],
                                 'Collections · choose where to look'),
                         lambda c: self.show_collection(c) if c else None)

    def save_view(self, name):
        """Save the current filters under ``name`` without opening the view form."""
        if not name:
            return
        try:
            validate_workspace(name)
            if name in self.settings.saved_views:
                raise ValueError('View already exists; delete it first or choose another name')
            self.replace_settings(saved_views={**self.settings.saved_views, name: self.current_view()})
            self.notify('View saved')
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')

    def save_view_prompt(self):
        self.push_screen(ViewEditor('', self.current_view(), self.settings), self.store_edited_view)

    def store_edited_view(self, result, original=None):
        if result is None:
            return
        name, view = result
        try:
            views = dict(self.settings.saved_views)
            if name != original and name in views:
                raise ValueError('That view name is already used')
            if original:
                views.pop(original, None)
            views[name] = view
            self.replace_settings(saved_views=views)
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')
            return
        self.apply_view(name)
        self.notify('View saved')

    def manage_views(self):
        choices = [(n, n) for n, v in self.settings.saved_views.items() if v['workspace'] == self.workspace]
        if not choices:
            self.save_view_prompt()
            return
        self.push_screen(Palette(choices, 'Choose a view to edit, rename or duplicate'), self.view_operations)

    def view_operations(self, name):
        if name:
            self.push_screen(Palette([('edit', 'Edit or rename'), ('duplicate', 'Duplicate'),
                                      ('update', 'Replace with current filters'), ('delete', 'Delete view')], name),
                             lambda operation: self.edit_saved_view(name, operation))

    def edit_saved_view(self, name, operation):
        if not operation:
            return
        if operation == 'delete':
            self.apply_view(name, delete=True)
            return
        duplicate = operation == 'duplicate'
        view = self.current_view() if operation == 'update' else self.settings.saved_views[name]
        self.push_screen(ViewEditor('' if duplicate else name, view, self.settings,
                                    original=None if duplicate else name),
                         lambda result: self.store_edited_view(result, None if duplicate else name))

    def update_active_view(self):
        if self.active_view in self.settings.saved_views:
            self.edit_saved_view(self.active_view, 'update')
        else:
            self.notify('Open a saved view first, or save your current filters as a new view.')

    def choose_view(self, delete=False):
        self.push_screen(Palette([(n, n) for n, view in self.settings.saved_views.items()
                                  if view['workspace'] == self.workspace],
                                 'Delete view' if delete else 'Open saved view'),
                         lambda name: self.apply_view(name, delete=delete))

    def apply_view(self, name, delete=False):
        if not name:
            return
        if delete:
            if self.active_view == name:
                self.active_view = None
            self.delete_config('saved_views', name)
            return
        view = self.settings.saved_views[name]
        if view['workspace'] != self.workspace:
            return
        self.active_view = name
        self.collection, self.view_sort = view['collection'], view['sort']
        self.theme = view['theme'] or self.settings.theme
        self.query_one('#search', Input).value = view['query']
        self.refresh_notes()
        self.set_focus_mode(False)
        self.show_navigation()

    def clear_view(self):
        self.active_view = None
        self.view_sort = None
        self.theme = self.settings.theme
        self.collection = 'all'
        self.query_one('#search', Input).value = ''
        self.refresh_notes()

    def edit_filters(self):
        self.push_screen(ViewEditor('', self.current_view(), self.settings, filters=True), self.apply_filters)

    def apply_filters(self, result):
        if result:
            _, view = result
            self.collection, self.view_sort = view['collection'], view['sort']
            self.theme = view['theme'] or self.settings.theme
            self.query_one('#search', Input).value = view['query']
            self.refresh_notes()
            self.show_navigation()

    def show_walkthrough(self):
        self.push_screen(Walkthrough(self.shortcut_text('''Capture, find, and use your notes

1. Capture: start typing now. The first line becomes the title; text saves automatically. Ctrl+N starts another note.
2. Find: Ctrl+F opens search. Use words or #tags. Collections and Views above the list help organize your library; Filters changes search and sorting.
3. Process: Ctrl+P opens commands to move, star, link, format, or run actions on a note. Shift+F10 opens a selected note's menu.
4. Reuse: save your search as a view. Manage views lets you edit, rename, duplicate, or update it. Ctrl+D opens today's log.
5. Recover: note history restores a separate copy. Trash keeps removed notes until you move them back. Ctrl+Q saves before quitting. If Git or Syncthing changes a file while you still have unsaved text, the comparison dialog keeps both copies. Ctrl+P → How to sync this vault prints the recipe; there is no Jotline cloud.

Ctrl+, customizes appearance and shortcuts. Esc closes this guide and returns to your text. This walkthrough never creates a note.
''')))
