"""Terminal editing and organization workflows, composed into the main app."""
from dataclasses import replace
import json
import re

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from .modal import Modal
from textual.widgets import Input, Label, OptionList, SelectionList, Static, TextArea

from .action_history import run_recorded_action as run_action
from .actions import ActionCommitError
from .store import EDIT_LIMIT_BYTES, tagged_body, validate_workspace
from .templates import Templates

MAX_ARRANGE_ITEMS = 5000
MAX_ARRANGE_BYTES = 256 * 1024


def split_parts(body, paragraphs):
    """Lines, or paragraphs separated by a blank line; CRLF documents split the same way."""
    return re.split(r'(?:\r?\n){2}' if paragraphs else r'\r?\n', body)


def headings(text):
    """(row, title) for ATX and setext headings, excluding fenced code."""
    from .markdown_editor import headings as markdown_headings
    for row, _, title in markdown_headings(text.split('\n')):
        yield row, title


class Arrange(Modal[str | None]):
    BINDINGS = [Binding('escape', 'cancel', 'Cancel'), Binding('ctrl+s', 'apply', 'Apply'),
                Binding('alt+up', 'move(-1)', 'Move up'), Binding('alt+down', 'move(1)', 'Move down'),
                Binding('ctrl+d', 'duplicate', 'Duplicate')]
    CSS = '''
    Arrange { align: center middle; background: $background 80%; }
    #arrange-panel { width: 80; max-width: 96%; height: 85%; border: round $accent; padding: 1 2; background: $surface; }
    #arrange-items { height: 1fr; }
    '''

    def __init__(self, body, paragraphs=False):
        super().__init__()
        self.separator = '\n\n' if paragraphs else '\n'
        # The editor restores its own newline style when the result is applied.
        self.parts = split_parts(body, paragraphs)

    def compose(self) -> ComposeResult:
        with Vertical(id='arrange-panel'):
            yield Label('Arrange paragraphs' if self.separator == '\n\n' else 'Arrange lines')
            yield Static('↑↓ select · Alt+↑↓ move · Ctrl+D duplicate · Ctrl+S apply · Esc cancel')
            yield OptionList(id='arrange-items')

    def on_mount(self):
        self.refresh_items(0)
        self.query_one(OptionList).focus()

    def refresh_items(self, index):
        items = self.query_one(OptionList)
        items.clear_options()
        items.add_options([Text(f'{i + 1}. {part[:180] or "(blank)"}') for i, part in enumerate(self.parts)])
        items.highlighted = index

    def action_move(self, delta):
        index = self.query_one(OptionList).highlighted
        if index is not None and 0 <= index + delta < len(self.parts):
            self.parts[index], self.parts[index + delta] = self.parts[index + delta], self.parts[index]
            self.refresh_items(index + delta)

    def action_duplicate(self):
        index = self.query_one(OptionList).highlighted
        if index is not None:
            if len(self.parts) >= MAX_ARRANGE_ITEMS:
                self.notify(f'Arrange supports up to {MAX_ARRANGE_ITEMS:,} items', severity='warning')
                return
            self.parts.insert(index + 1, self.parts[index])
            self.refresh_items(index + 1)

    def action_apply(self):
        self.dismiss(self.separator.join(self.parts))


class SelectNotes(Modal[list[str] | None]):
    BINDINGS = [Binding('escape', 'cancel', 'Cancel'), Binding('ctrl+s', 'apply', 'Choose operation')]
    CSS = '''
    SelectNotes { align: center middle; background: $background 80%; }
    #bulk-panel { width: 80; max-width: 96%; height: 85%; border: round $accent; padding: 1 2; background: $surface; }
    #bulk-items { height: 1fr; }
    '''

    def __init__(self, choices):
        super().__init__()
        self.choices = choices

    def compose(self):
        with Vertical(id='bulk-panel'):
            yield Label('Select notes · Space toggles · Ctrl+S choose operation · Esc cancel')
            yield Static('0 selected', id='bulk-count')
            yield SelectionList(*[(Text(label), key) for key, label in self.choices], id='bulk-items')

    def on_mount(self):
        self.query_one(SelectionList).focus()

    @on(SelectionList.SelectedChanged)
    def selection_changed(self):
        self.query_one('#bulk-count', Static).update(f'{len(self.query_one(SelectionList).selected)} selected')

    def action_apply(self):
        ids = self.query_one(SelectionList).selected
        if ids:
            self.dismiss(ids)
        else:
            self.notify('Select at least one note first')


class WorkflowMixin:
    def workflow_commands(self, Command):
        return [Command(key, label, handler) for key, label, handler in [
            ('recent', 'Recent notes', self.show_recent),
            ('previous', 'Previous note', self.previous_note),
            ('insert-template', 'Insert template at cursor', self.insert_template),
            ('insert-note', 'Insert note text at cursor', self.insert_note),
            ('arrange-lines', 'Arrange lines', lambda: self.arrange(False)),
            ('arrange-paragraphs', 'Arrange paragraphs', lambda: self.arrange(True)),
            ('save-view', 'Save current search as a view', self.save_view_prompt),
            ('views', 'Open saved view', self.choose_view),
            ('delete-view', 'Delete saved view', lambda: self.choose_view(delete=True)),
            ('clear-view', 'Clear view and search', self.clear_view),
            ('bulk', 'Select notes for bulk operations', self.select_bulk),
            ('actions', 'Run local action', self.choose_action),
            ('save-action', 'Save action recipe from this note', self.save_action_prompt),
            ('delete-action', 'Delete local action', lambda: self.choose_action(delete=True)),
        ]]

    def insert_editor_text(self, body) -> bool:
        """Replace the selection, or insert at the cursor, as one undo step within the size limit."""
        editor = self.query_one('#editor', TextArea)
        text = editor.text
        start, end = sorted((editor.selection.start, editor.selection.end))
        begin, finish = self.editor_offset(start, text), self.editor_offset(end, text)
        # Size the pieces rather than building the whole resulting text only to measure it.
        result_bytes = (len(text[:begin].encode('utf-8')) + len(body.encode('utf-8'))
                        + len(text[finish:].encode('utf-8')))
        if result_bytes > EDIT_LIMIT_BYTES:
            self.notify('Result exceeds the note size limit', severity='error')
            return False
        editor.history.checkpoint()
        editor.replace(body, start, end)
        editor.move_cursor(self.editor_location(begin + len(body), editor.text))
        editor.history.checkpoint()
        self.capture_current_buffer()
        return True

    def replace_whole_text(self, body) -> None:
        """Replace the whole note text as one undo step, keeping the cursor where it was."""
        editor = self.query_one('#editor', TextArea)
        position = editor.cursor_location
        editor.history.checkpoint()
        editor.replace(body, (0, 0), self.editor_location(len(editor.text), editor.text))
        editor.history.checkpoint()
        editor.move_cursor(position)

    def replace_editor_text(self, body) -> bool:
        if body is None:
            return False
        if len(body.encode('utf-8')) > EDIT_LIMIT_BYTES:
            self.notify('Result exceeds the note size limit', severity='error')
            return False
        self.replace_whole_text(body)
        self.capture_current_buffer()
        return True

    def read_in_workspace(self, note_id):
        """Read a note the user picked; it must still belong to this workspace."""
        note = self.vault.read(note_id)
        if note.workspace != self.workspace:
            raise ValueError('Note moved to another workspace')
        return note

    def recent_notes(self):
        notes = {n.id: n for n in self.vault.search(workspace=self.workspace)}
        return [notes[key] for key in self.recent_note_ids if key in notes and key != self.current.id]

    def show_recent(self):
        from .app import Palette
        self.push_screen(Palette(self.note_choices(self.recent_notes()), 'Recent notes'),
                         lambda key: self.load_id(key) if key else None)

    def previous_note(self):
        notes = self.recent_notes()
        if notes:
            self.load_id(notes[0].id)
        else:
            self.notify('No previous note in this workspace')

    def offer_completion(self):
        """Offer keyboard suggestions only after an editor trigger at the cursor."""
        from .app import Palette
        editor = self.query_one('#editor', TextArea)
        if not editor.has_focus or editor.selected_text:
            return
        offset = self.editor_offset(editor.cursor_location, editor.text)
        trigger = editor.text[max(0, offset - 2):offset]
        if trigger not in {'[[', ';;'}:
            return
        original = editor.text
        try:
            if trigger == '[[':
                choices = self.note_choices(self.vault.search(workspace=self.workspace))
            else:
                choices = [(name, name) for name in Templates(self.vault.path).names()]
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')
            return
        def complete(key):
            if not key or editor.text != original:
                editor.focus()
                return
            try:
                if trigger == '[[':
                    note = self.read_in_workspace(key)
                    title = note.title.replace('|', ' ').replace('[', '').replace(']', '')
                    body = f'[[{note.id}|{title}]]'
                else:
                    body = Templates(self.vault.path).render(key, self.workspace,
                                                           title=self.current.title, body=original)
                editor.move_cursor(self.editor_location(offset - 2, original))
                editor.move_cursor(self.editor_location(offset, original), select=True)
                self.insert_editor_text(body)
            except (ValueError, OSError) as error:
                self.notify(str(error), severity='error')
            editor.focus()
        self.push_screen(Palette(choices, 'Complete note link' if trigger == '[[' else 'Insert snippet'), complete)

    def insert_template(self):
        from .app import Palette
        try:
            names = Templates(self.vault.path).names()
            self.push_screen(Palette([(n, n) for n in names], 'Insert template at cursor'), self.insert_template_named)
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')

    def insert_template_named(self, name):
        if name:
            try:
                editor = self.query_one('#editor', TextArea)
                self.capture_current_buffer()
                body = Templates(self.vault.path).render(name, self.workspace, title=self.current.title,
                                                        body=editor.text, selection=editor.selected_text)
                self.insert_editor_text(body)
                editor.focus()
            except (ValueError, OSError) as error:
                self.notify(str(error), severity='error')

    def insert_note(self):
        from .app import Palette
        self.push_screen(Palette(self.note_choices(self.vault.search(workspace=self.workspace)), 'Insert note text'), self.insert_note_id)

    def insert_note_id(self, key):
        if key:
            try:
                self.insert_editor_text(self.read_in_workspace(key).body)
                self.query_one('#editor', TextArea).focus()
            except (ValueError, OSError) as error:
                self.notify(str(error), severity='error')

    def arrange(self, paragraphs):
        body = self.query_one('#editor', TextArea).text
        if len(body.encode('utf-8')) > MAX_ARRANGE_BYTES or len(split_parts(body, paragraphs)) > MAX_ARRANGE_ITEMS:
            self.notify(f'Arrange supports up to {MAX_ARRANGE_BYTES // 1024} KiB and {MAX_ARRANGE_ITEMS:,} items',
                        severity='warning')
            return
        self.push_screen(Arrange(body, paragraphs), self.replace_editor_text)

    def save_view(self, name):
        """Save the current filters under ``name`` without opening the view form."""
        if not name:
            return
        try:
            validate_workspace(name)
            if name in self.settings.saved_views:
                raise ValueError('View already exists; delete it first or choose another name')
            views = {**self.settings.saved_views, name: self.current_view()}
            settings = replace(self.settings, saved_views=views)
            settings.save(self.settings_path)
            self.settings = settings
            self.notify('View saved')
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')

    def choose_view(self, delete=False):
        from .app import Palette
        self.push_screen(Palette([(n, n) for n, view in self.settings.saved_views.items()
                                  if view['workspace'] == self.workspace], 'Delete view' if delete else 'Open saved view'),
                         lambda name: self.apply_view(name, delete=delete))

    def apply_view(self, name, delete=False):
        if not name:
            return
        if delete:
            self.delete_config('saved_views', name)
            return
        view = self.settings.saved_views[name]
        if view['workspace'] != self.workspace:
            return
        self.collection, self.view_sort = view['collection'], view['sort']
        self.theme = view['theme'] or self.settings.theme
        self.query_one('#search', Input).value = view['query']
        self.refresh_notes()
        self.set_focus_mode(False)
        self.show_navigation()

    def clear_view(self):
        self.view_sort = None
        self.theme = self.settings.theme
        self.collection = 'all'
        self.query_one('#search', Input).value = ''
        self.refresh_notes()

    def select_bulk(self):
        if not self.save_current():
            return
        try:
            notes = self.vault.search(self.query_one('#search', Input).value, self.collection, self.workspace)
            self.push_screen(SelectNotes(self.note_choices(notes)), self.bulk_operation)
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')

    def bulk_operation(self, ids):
        from .app import Palette, TextPrompt
        if not ids:
            return
        def chosen(operation):
            if operation == 'tag':
                self.push_screen(TextPrompt('Tags for selected notes', 'e.g. work project/launch'),
                                 lambda tags: self.run_bulk(ids, 'tag', tags) if tags else None)
            elif operation:
                self.run_bulk(ids, operation)
        self.push_screen(Palette([
            ('archive', 'Archive selected'), ('trash', 'Move selected to trash'), ('star', 'Star selected'),
            ('tag', 'Add tags to selected'), ('merge', 'Merge into a new note; keep originals')],
            'Operation for selected notes'), chosen)

    def run_bulk(self, ids, operation, tags=''):
        if not self.save_current():
            return
        success, failures, merge = 0, [], []
        for key in dict.fromkeys(ids):
            try:
                note = self.read_in_workspace(key)
                if operation == 'merge':
                    if sum(len(body.encode('utf-8')) + 7 for body in merge) + len(note.body.encode('utf-8')) > EDIT_LIMIT_BYTES:
                        raise ValueError('Merged note exceeds the note size limit')
                    merge.append(note.body)
                else:
                    if operation == 'tag':
                        note.body = tagged_body(note.body, tags)
                    elif operation == 'star':
                        note.starred = True
                    elif operation in {'archive', 'trash'}:
                        note.collection = operation
                    else:
                        raise ValueError('Unknown bulk operation')
                    self.vault.save(note)
                success += 1
            except (ValueError, OSError) as error:
                failures.append(f'{key}: {error}')
        if operation == 'merge' and not failures:
            try:
                note = self.vault.new('\n\n---\n\n'.join(merge), workspace=self.workspace)
                self.vault.save(note)
                self.load(note)
            except (ValueError, OSError) as error:
                failures.append(str(error))
        elif self.current.id in ids:
            try:
                self.load(self.vault.read(self.current.id))
            except (ValueError, OSError) as error:
                failures.append(str(error))
        self.refresh_notes()
        self.notify(f'{success} processed; {len(failures)} failed' + ('. ' + '; '.join(failures[:3]) if failures else ''),
                    severity='warning' if failures else 'information', timeout=10)

    def save_action_prompt(self):
        from .app import TextPrompt
        self.push_screen(TextPrompt('Save action recipe from note (JSON step list)', 'Unique action name'), self.save_action)

    def save_action(self, name):
        if not name:
            return
        try:
            if name in self.settings.actions:
                raise ValueError('Action already exists; choose another name or delete it first')
            steps = json.loads(self.query_one('#editor', TextArea).text)
            settings = replace(self.settings, actions={**self.settings.actions, name: steps})
            settings.save(self.settings_path)
            self.settings = settings
            self.notify('Action saved; choose Run local action to use it')
        except (ValueError, OSError, RecursionError) as error:
            self.notify(str(error), severity='error')

    def delete_config(self, field, name):
        try:
            values = dict(getattr(self.settings, field))
            values.pop(name, None)
            settings = replace(self.settings, **{field: values})
            settings.save(self.settings_path)
            self.settings = settings
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')

    def choose_action(self, delete=False):
        from .app import Palette
        if not self.settings.actions:
            if delete:
                self.notify('No saved actions to delete.')
            else:
                self.builtin_action_recipe()
            return
        self.push_screen(Palette([(n, n) for n in self.settings.actions], 'Delete action' if delete else 'Run local action'),
                         lambda name: self.delete_config('actions', name) if delete and name else self.run_local_action(name))

    def run_local_action(self, name):
        if not name or not self.save_current():
            return
        try:
            def export(body):
                note = self.vault.new(body, workspace=self.workspace)
                self.vault.save(note)
                self.notify(f'Exported action output to new inbox note {note.id}')
            note = run_action(self.vault, self.current, self.settings.actions[name],
                              name=name, history_warning=lambda message: self.notify(message, severity='warning'),
                              selection=self.query_one('#editor', TextArea).selected_text,
                              copy=self.copy_to_clipboard, export=export)
            self.accept_action_note(note)
            self.status('Saved')
            self.notify('Action completed')
        except ActionCommitError as error:
            self.accept_action_note(error.note)
            self.status('Saved · durability warning')
            self.notify(str(error) + '. Review action history before retrying.', severity='warning', timeout=12)
        except (ValueError, OSError) as error:
            self.notify(f'Action stopped: {error}. Earlier completed steps remain applied.', severity='error', timeout=12)

    def accept_action_note(self, note):
        # The action has already saved via Vault's authoritative byte limit.
        # Do not run the more conservative insertion guard after that commit.
        editor = self.query_one('#editor', TextArea)
        if editor.text != note.body:
            self.replace_whole_text(note.body)
        self._editor_baseline = editor.text
        self.current, self.dirty, self.last_error = note, False, ''
        self.refresh_notes()
        self.connections()
