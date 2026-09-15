"""Review external changes before preserving the on-screen draft."""
from textual import on
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Button, Label, TextArea

from .modal import Modal

# Rendering two huge read-only editors would stall the dialog; the full draft is still preserved.
COMPARE_LIMIT = 100_000


class RecoveryScreen(Modal[str | None]):
    BINDINGS = [Binding('escape', 'cancel', 'Keep editing')]
    CSS = '''
    RecoveryScreen { align: center middle; }
    #recovery-dialog { width: 90%; height: 90%; border: round $accent; background: $surface; padding: 1; }
    #recovery-scroll { height: 1fr; }
    RecoveryScreen TextArea { height: 10; min-height: 5; }
    RecoveryScreen Button { width: 100%; margin-top: 1; }
    '''

    def __init__(self, local_body: str, external_body: str | None, external_error=''):
        super().__init__()
        self.local_body, self.external_body, self.external_error = local_body, external_body, external_error

    def compose(self):
        with Vertical(id='recovery-dialog'):
            yield Label('This note changed outside Jotline')
            with VerticalScroll(id='recovery-scroll'):
                yield Label('Your on-screen draft (unsaved)')
                yield TextArea(self.local_body[:COMPARE_LIMIT], read_only=True, id='recovery-local')
                yield Label('External version on disk' if self.external_body is not None
                            else 'External version unavailable: ' + self.external_error, markup=False)
                yield TextArea((self.external_body or '')[:COMPARE_LIMIT], read_only=True, id='recovery-external')
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
    HealthScreen { align: center middle; }
    #health-dialog { width: 90%; height: 90%; border: round $accent; background: $surface; padding: 1; }
    #health-text { height: 1fr; }
    HealthScreen Button { width: 100%; margin-top: 1; }
    '''

    def __init__(self, report: str):
        super().__init__()
        self.report = report

    def compose(self):
        with Vertical(id='health-dialog'):
            yield Label('Vault health')
            yield TextArea(self.report, read_only=True, id='health-text')
            yield Button('Back to writing', id='health-close')

    @on(Button.Pressed, '#health-close')
    def action_cancel(self) -> None:
        self.dismiss(None)
