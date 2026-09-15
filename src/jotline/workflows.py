"""Terminal editing and organization workflows, composed into the main app."""
import re

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, Label, OptionList, SelectionList, Static

from .accessibility import named
from .limits import EDIT_LIMIT_BYTES
from .markdown_editor import MarkdownEditor
from .modal import Modal, Palette, TextPrompt
from .store import tagged_body, wiki_link
from .templates import Templates

MAX_ARRANGE_ITEMS = 5000
MAX_ARRANGE_BYTES = 256 * 1024


def split_parts(body, paragraphs):
    """Lines, or paragraphs separated by a blank line; CRLF documents split the same way."""
    return re.split(r'(?:\r?\n){2}' if paragraphs else r'\r?\n', body)


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
            yield named(OptionList(id='arrange-items'), 'Items to rearrange')

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
            yield named(SelectionList(*[(Text(label), key) for key, label in self.choices], id='bulk-items'),
                        'Notes to include in the bulk operation')

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


class Workflows:
    """Insert, arrange, and bulk-edit notes. Bound onto Jotline; not inherited."""

    def workflow_commands(self, Command):
        return [
            Command('recent', 'Recent notes', self.show_recent, group='everyday'),
            Command('previous', 'Previous note', self.previous_note, group='everyday'),
            Command('extract', 'Extract selection to new note', self.action_extract_note, 'extract_note',
                    group='everyday'),
            Command('insert-template', 'Insert template at cursor', self.insert_template),
            Command('insert-note', 'Insert note text at cursor', self.insert_note),
            Command('arrange-lines', 'Arrange lines', lambda: self.arrange(False)),
            Command('arrange-paragraphs', 'Arrange paragraphs', lambda: self.arrange(True)),
            Command('bulk', 'Select notes for bulk operations', self.select_bulk),
        ]

    def insert_editor_text(self, body) -> bool:
        """Replace the selection, or insert at the cursor, as one undo step within the size limit."""
        editor = self.query_one('#editor', MarkdownEditor)
        if not editor.insert_checked(body, limit=EDIT_LIMIT_BYTES):
            self.notify('Result exceeds the note size limit', severity='error')
            return False
        self.capture_current_buffer()
        return True

    def action_extract_note(self) -> None:
        """Turn the selection into a new inbox note and leave a [[link]] behind."""
        editor = self.query_one('#editor', MarkdownEditor)
        selected = editor.selected_text
        if not selected.strip():
            self.notify('Select the text to extract first')
            return
        if len(selected.encode('utf-8')) > EDIT_LIMIT_BYTES:
            self.notify('Result exceeds the note size limit', severity='error')
            return
        note = self.vault.new(selected, workspace=self.workspace)
        link = wiki_link(note)
        text = editor.text
        start, end = sorted((editor.selection.start, editor.selection.end))
        begin, finish = editor.char_offset(start, text), editor.char_offset(end, text)
        result_bytes = (len(text[:begin].encode('utf-8')) + len(link.encode('utf-8'))
                        + len(text[finish:].encode('utf-8')))
        if result_bytes > EDIT_LIMIT_BYTES:
            self.notify('Result exceeds the note size limit', severity='error')
            return
        try:
            self.vault.save(note)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity='error')
            return
        if not self.insert_editor_text(link):
            return
        self.refresh_notes()
        self.notify(f'Extracted to {note.title}')

    def replace_whole_text(self, body) -> None:
        """Replace the whole note text as one undo step, keeping the cursor where it was."""
        editor = self.query_one('#editor', MarkdownEditor)
        position = editor.cursor_location
        editor.history.checkpoint()
        editor.replace(body, (0, 0), editor.location_at(len(editor.text), editor.text))
        editor.history.checkpoint()
        editor.move_cursor(position)

    def replace_editor_text(self, body) -> bool:
        if body is None:
            return False
        editor = self.query_one('#editor', MarkdownEditor)
        if not editor.replace_checked(body, limit=EDIT_LIMIT_BYTES):
            self.notify('Result exceeds the note size limit', severity='error')
            return False
        self.capture_current_buffer()
        return True

    def read_in_workspace(self, note_id):
        """Read a note the user picked; it must still belong to this workspace."""
        return self.vault.read(note_id, workspace=self.workspace)

    def recent_notes(self):
        notes = {n.id: n for n in self.vault.search(workspace=self.workspace)}
        return [notes[key] for key in self.recent_note_ids if key in notes and key != self.current.id]

    def show_recent(self):
        self.push_screen(Palette(self.note_choices(self.recent_notes()), 'Recent notes'),
                         lambda key: self.load_id(key) if key else None)

    def previous_note(self):
        notes = self.recent_notes()
        if notes:
            self.load_id(notes[0].id)
        else:
            self.notify('No previous note in this workspace')

    def offer_completion(self):
        """Offer keyboard suggestions only after an editor trigger at the cursor.

        TextArea.Changed can be delivered after a palette dismiss, when the
        editor no longer has focus. The trigger at the cursor is the gate.
        """
        editor = self.query_one('#editor', MarkdownEditor)
        if not editor.selection.is_empty:
            return
        offset = editor.char_offset(editor.cursor_location, editor.text)
        trigger = editor.text[max(0, offset - 2):offset]
        if trigger not in {'[[', ';;'}:
            return
        original = editor.text
        try:
            if trigger == '[[':
                notes = [note for note in self.vault.search(workspace=self.workspace)
                         if note.id != self.current.id]
                choices = self.note_choices(notes)
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
                    body = wiki_link(self.read_in_workspace(key))
                else:
                    body = Templates(self.vault.path).render(key, self.workspace,
                                                           title=self.current.title, body=original)
                editor.move_cursor(editor.location_at(offset - 2, original))
                editor.move_cursor(editor.location_at(offset, original), select=True)
                self.insert_editor_text(body)
                editor.move_cursor(editor.cursor_location)
            except (ValueError, OSError) as error:
                self.notify(str(error), severity='error')
            editor.focus()
        self.push_screen(Palette(choices, 'Complete note link' if trigger == '[[' else 'Insert snippet'), complete)

    def insert_template(self):
        try:
            names = Templates(self.vault.path).names()
            self.push_screen(Palette([(n, n) for n in names], 'Insert template at cursor'), self.insert_template_named)
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')

    def insert_template_named(self, name):
        if name:
            try:
                editor = self.query_one('#editor', MarkdownEditor)
                self.capture_current_buffer()
                body = Templates(self.vault.path).render(name, self.workspace, title=self.current.title,
                                                        body=editor.text, selection=editor.selected_text)
                self.insert_editor_text(body)
                editor.focus()
            except (ValueError, OSError) as error:
                self.notify(str(error), severity='error')

    def insert_note(self):
        self.push_screen(Palette(self.note_choices(self.vault.search(workspace=self.workspace)), 'Insert note text'),
                         self.insert_note_id)

    def insert_note_id(self, key):
        if key:
            try:
                self.insert_editor_text(self.read_in_workspace(key).body)
                self.query_one('#editor', MarkdownEditor).focus()
            except (ValueError, OSError) as error:
                self.notify(str(error), severity='error')

    def arrange(self, paragraphs):
        body = self.query_one('#editor', MarkdownEditor).text
        if len(body.encode('utf-8')) > MAX_ARRANGE_BYTES or len(split_parts(body, paragraphs)) > MAX_ARRANGE_ITEMS:
            self.notify(f'Arrange supports up to {MAX_ARRANGE_BYTES // 1024} KiB and {MAX_ARRANGE_ITEMS:,} items',
                        severity='warning')
            return
        self.push_screen(Arrange(body, paragraphs), self.replace_editor_text)

    def select_bulk(self):
        if not self.save_current():
            return
        try:
            notes = self.vault.search(self.query_one('#search', Input).value, self.collection, self.workspace)
            self.push_screen(SelectNotes(self.note_choices(notes)), self.bulk_operation)
        except (ValueError, OSError) as error:
            self.notify(str(error), severity='error')

    def bulk_operation(self, ids):
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
