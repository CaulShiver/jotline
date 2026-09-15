"""Import preview and app integration for safe recovery and migration."""
from pathlib import Path

from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Button, Label, Static

from .importing import preview_import, apply_import
from .modal import Modal, TextPrompt
from .recovery_ui import RecoveryScreen


class ImportPreviewScreen(Modal[bool]):
    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]
    CSS = '''
    ImportPreviewScreen { align: center middle; }
    #import-dialog { width: 90%; height: 90%; border: round $accent; background: $surface; padding: 1; }
    #import-items { height: 1fr; }
    ImportPreviewScreen Button { width: 100%; margin-top: 1; }
    '''

    def __init__(self, plan):
        super().__init__()
        self.plan = plan

    def compose(self):
        with Vertical(id='import-dialog'):
            yield Label('Review import')
            yield Label(self.plan.summary())
            yield Label('Original files remain untouched. Matching bodies or Drafts UUIDs are skipped.')
            with VerticalScroll(id='import-items'):
                for item in self.plan.items:
                    decision = 'Skip duplicate' if item.duplicate and self.plan.duplicates == 'skip' else 'Import'
                    yield Static(Text(f'{decision}: {item.source} → {item.note.collection} / {item.note.title}'))
                for warning in self.plan.warnings:
                    yield Static(Text('Warning: ' + warning))
            yield Button(f'Import {self.plan.ready} notes', id='import-apply', variant='primary',
                         disabled=not self.plan.ready)
            yield Button('Cancel', id='import-cancel')

    @on(Button.Pressed)
    def choose(self, event):
        self.dismiss(event.button.id == 'import-apply')

    def action_cancel(self):
        self.dismiss(False)


class RecoveryImport:
    """Conflict recovery and library import. Bound onto Jotline; not inherited."""
    def show_recovery_dialog(self):
        if self._recovery_dialog_open:
            return
        self.capture_current_buffer()
        try:
            external = self.vault.read(self.current.id).body
            error = ''
        except (OSError, ValueError) as problem:
            external, error = None, str(problem)
        self._recovery_dialog_open = True
        original_id = self.current.id

        def resolve(choice):
            self._recovery_dialog_open = False
            if not choice:
                return
            self.capture_current_buffer()
            try:
                recovered = self.vault.recovery(self.current)
            except (OSError, ValueError) as problem:
                self.notify('Recovery copy could not be saved. Your draft remains on screen. ' + str(problem),
                            severity='error', timeout=12)
                return
            target = recovered
            message = f'Full on-screen draft preserved in inbox recovery copy {recovered.id}.'
            if choice == 'preserve-reload':
                try:
                    target = self.vault.read(original_id)
                    if target.workspace != self.workspace:
                        target = recovered
                        raise ValueError('External note moved to another workspace')
                except (OSError, ValueError) as problem:
                    message += ' External version unavailable; opened your recovery copy. ' + str(problem)
            self.collection = target.collection
            self.query_one('#search', Input).value = ''
            self.load(target)
            self.refresh_notes()
            self.notify(message, timeout=12)
        self.push_screen(RecoveryScreen(self.current.body, external, error), resolve)

    def import_library(self):
        def choose_path(value):
            if not value:
                return
            try:
                plan = preview_import(self.vault, Path(value), self.workspace, self.settings.default_collection,
                                      recursive=True)
            except (OSError, ValueError) as error:
                self.notify(str(error), severity='error')
                return
            def confirmed(accepted):
                if not accepted:
                    return
                try:
                    result = apply_import(self.vault, plan)
                except (OSError, ValueError) as error:
                    self.notify('Import could not start: ' + str(error), severity='error')
                    return
                self.refresh_notes()
                self.notify(result.summary() + ('. ' + ' | '.join(result.errors[:3]) if result.errors else ''),
                            severity='error' if result.errors else 'information', timeout=12)
            self.push_screen(ImportPreviewScreen(plan), confirmed)
        self.push_screen(TextPrompt('Import file, folder, or .draftsExport (subfolders included)', '/path/to/notes'), choose_path)
