"""Recovery screens for external note changes, vault health, and backup restore."""
from pathlib import Path
from shlex import quote

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Static, TextArea

from .backup_restore import BackupPreview, check_destination, preview_backup, restore_backup
from .history import list_archives
from .messages import failed
from .modal import Modal, Palette, TextPrompt
from .terminal import terminal_text

# Rendering two huge read-only editors would stall the dialog; the full draft is still preserved.
COMPARE_LIMIT = 100_000


class RecoveryScreen(Modal[str | None]):
    BINDINGS = [Binding('escape', 'cancel', 'Keep editing')]
    CSS = '''
    #recovery-dialog { width: 90%; height: 90%; padding: 1; }
    #recovery-scroll { height: 1fr; }
    RecoveryScreen TextArea { height: 10; min-height: 5; }
    RecoveryScreen Button { width: 100%; margin-top: 1; }
    '''

    def __init__(self, local_body: str, external_body: str | None, external_error=''):
        super().__init__()
        self.local_body, self.external_body, self.external_error = local_body, external_body, external_error

    def compose(self):
        with Vertical(id='recovery-dialog', classes='dialog'):
            yield Label('This note changed outside Jotline')
            with VerticalScroll(id='recovery-scroll'):
                yield Label('Your on-screen draft (unsaved)')
                local = TextArea(self.local_body[:COMPARE_LIMIT], read_only=True, id='recovery-local')
                local.tooltip = 'Your unsaved on-screen draft'
                yield local
                yield Label('External version on disk' if self.external_body is not None
                            else 'External version unavailable: ' + self.external_error, markup=False)
                external = TextArea((self.external_body or '')[:COMPARE_LIMIT], read_only=True, id='recovery-external')
                external.tooltip = 'External version of this note on disk'
                yield external
                if len(self.local_body) > COMPARE_LIMIT or len(self.external_body or '') > COMPARE_LIMIT:
                    yield Label(f'Comparison limited to {COMPARE_LIMIT:,} characters. The full draft will be preserved.')
                yield Label('Both save options first create a separate inbox recovery copy of your full draft. '
                            'Open a recovery copy from Commands, or run jotline recoveries.')
                yield Button('Save copy, then review external version', id='preserve-reload',
                             disabled=self.external_body is None, variant='primary')
                yield Button('Save and open recovery copy', id='preserve')
                yield Button('Keep editing', id='cancel')

    @on(Button.Pressed)
    def choose(self, event):
        self.dismiss(None if event.button.id == 'cancel' else event.button.id)


class HealthScreen(Modal[None]):
    BINDINGS = [Binding('escape', 'cancel', 'Back to writing')]
    CSS = '''
    #health-dialog { width: 90%; height: 90%; padding: 1; }
    #health-text { height: 1fr; }
    HealthScreen Button { width: 100%; margin-top: 1; }
    '''

    def __init__(self, report: str):
        super().__init__()
        self.report = report

    def compose(self):
        with Vertical(id='health-dialog', classes='dialog'):
            yield Label('Vault health')
            yield TextArea(self.report, read_only=True, id='health-text')
            yield Button('Back to writing', id='health-close')

    @on(Button.Pressed, '#health-close')
    def action_cancel(self) -> None:
        self.dismiss(None)


class BackupRestorePreview(Modal[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CSS = """
    #restore-dialog { width: 78; max-width: 95%; height: 90%; padding: 1; }
    #restore-summary { height: 1fr; }
    #restore-buttons { height: auto; }
    """

    def __init__(self, preview: BackupPreview, destination: Path):
        super().__init__()
        self.preview, self.destination = preview, destination

    def compose(self):
        with Vertical(id="restore-dialog", classes="dialog"):
            yield Label("Preview backup restore")
            with VerticalScroll(id="restore-summary"):
                yield Static(self.preview.describe(), markup=False)
                yield Static(f"New vault: {terminal_text(self.destination)}", markup=False)
            yield Label("Nothing has been written. Your current vault stays open and unchanged.")
            with Horizontal(id="restore-buttons"):
                yield Button("Cancel", id="restore-cancel")
                yield Button("Restore to new vault", id="restore-apply", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#restore-cancel", Button).focus()

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "restore-apply")


class BackupRecovery:
    def prompt_backup_restore(self) -> None:
        vault = self.vault
        origin = self.screen

        def show_choices(paths: list[tuple[str, str]]) -> None:
            if self.screen is origin:
                self.push_screen(Palette(paths + [("", "Enter another ZIP path…")], "Choose a backup to restore"),
                                 choose)

        def choose(value: str | None) -> None:
            if value is None:
                return
            if value:
                self.preview_backup_restore(value)
            else:
                self.push_screen(TextPrompt("Jotline backup ZIP to preview", "/path/to/backup.zip"),
                                 self.preview_backup_restore)

        def load_choices() -> None:
            paths = [(str(archive.path), f"{archive.name}{'' if archive.valid else ' (invalid)'}")
                     for archive in list_archives(vault)]
            self.call_from_thread(show_choices, paths)

        self.run_worker(load_choices, thread=True, group="backup-restore", exclusive=True)

    def preview_backup_restore(self, value: str | None) -> None:
        if not value:
            return
        active = self.vault.path
        origin = self.screen

        def choose_destination(preview: BackupPreview, initial: Path) -> None:
            if self.screen is not origin:
                return

            def review(path: str | None) -> None:
                if not path:
                    return
                try:
                    target = check_destination(Path(path), active)
                except (OSError, ValueError) as error:
                    self.notify(terminal_text(failed("Choose a different restore folder", error)),
                                severity="error", markup=False)
                    choose_destination(preview, Path(path))
                    return
                self.push_screen(BackupRestorePreview(preview, target),
                                 lambda confirmed: self.apply_backup_restore(preview, target) if confirmed else None)

            self.push_screen(TextPrompt("New folder outside the current vault", "/path/to/restored-vault", str(initial)),
                             review)

        def load_preview() -> None:
            try:
                preview = preview_backup(Path(value))
            except (OSError, ValueError) as error:
                self.call_from_thread(self.notify, terminal_text(failed("Could not preview backup", error)),
                                      severity="error", timeout=12, markup=False)
            else:
                self.call_from_thread(choose_destination, preview, active.parent / f"{active.name}-restored")

        self.notify("Reading backup…")
        self.run_worker(load_preview, thread=True, group="backup-restore", exclusive=True)

    def apply_backup_restore(self, preview: BackupPreview, destination: Path) -> None:
        active = self.vault.path
        self.notify("Restoring backup to a separate vault…")

        def apply() -> None:
            try:
                target = restore_backup(preview, destination, active)
            except (OSError, ValueError) as error:
                message = failed("Restore did not complete", error, "Your current vault was not changed.")
                self.call_from_thread(self.notify, terminal_text(message), severity="error", timeout=12, markup=False)
            else:
                command = terminal_text(quote(str(target)))
                self.call_from_thread(self.notify, f"Restored. Open with: jotline --vault {command}",
                                      timeout=18, markup=False)

        self.run_worker(apply, thread=True, group="backup-restore-write")
