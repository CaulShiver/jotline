"""Open tasks across notes, and document export, composed into the main app."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from textual.widgets import TextArea

from .export import FORMAT_NAMES, ExportError, export_bytes, suggested_name, write_export
from .tasks import gather


class ReviewMixin:
    def review_commands(self, Command):
        return [Command(*item) for item in [
            ("tasks", "Open tasks across notes", self.show_tasks),
            ("process-inbox", "Process next inbox note", self.action_process_inbox, "process_inbox"),
            ("export-html", "Export note as HTML…", lambda: self.prompt_export("html")),
            ("export-docx", "Export note as Word document…", lambda: self.prompt_export("docx")),
            ("export-pdf", "Export note as PDF…", lambda: self.prompt_export("pdf")),
        ]]

    def action_process_inbox(self) -> None:
        if not self.save_current(explicit=True):
            return
        queue = self.vault.inbox_captures(self.workspace)
        if not queue:
            self.notify("Inbox is clear. Captures you file leave the inbox.")
            return
        target = queue[0]
        self.collection = "inbox"
        if self.current.id != target.id:
            self.load_id(target.id)
        remaining = len(self.vault.inbox_captures(self.workspace))
        self.refresh_notes()
        self.notify(f"Process this capture · {remaining} in inbox")

    def open_next_inbox_capture(self) -> None:
        queue = self.vault.inbox_captures(self.workspace)
        if not queue:
            self.notify("Inbox is clear")
            return
        self.collection = "inbox"
        self.load_id(queue[0].id)
        self.refresh_notes()
        self.notify(f"Next inbox capture · {len(queue)} remaining")

    def show_tasks(self) -> None:
        from .app import Palette

        if not self.save_current():
            return
        found = gather(self.vault.search(workspace=self.workspace))
        if not found:
            self.notify("No open tasks in this workspace. Start a line with - [ ] in any note to add one.")
            return
        today = date.today()
        choices = []
        for task in found:
            label = "☐ " + task.text
            if task.due:
                label += f" · due {task.due}" + (" (overdue)" if task.overdue(today) else "")
            choices.append((task.reference(), label + " · " + task.note_title))
        self.push_screen(Palette(choices, f"Open tasks · {len(found)}"), self.open_task)

    def open_task(self, reference: str | None) -> None:
        if not reference:
            return
        note_id, _, line = reference.rpartition(":")
        self.load_id(note_id)
        if self.current.id == note_id:
            editor = self.query_one("#editor", TextArea)
            editor.move_cursor((min(int(line), editor.document.line_count) - 1, 0), center=True)

    def prompt_export(self, fmt: str) -> None:
        from .app import TextPrompt

        self.capture_current_buffer()
        folder = Path.home() / "Documents"
        suggestion = (folder if folder.is_dir() else Path.home()) / suggested_name(self.current.title, fmt)
        self.push_screen(TextPrompt(f"Export as {FORMAT_NAMES[fmt]} · file to write", "Path of the new file",
                                    str(suggestion)),
                         lambda path: self.export_current(fmt, path) if path else None)

    def export_current(self, fmt: str, path: str) -> None:
        if not self.save_current(explicit=True):
            return
        # Snapshot the text now; the worker must not see edits typed while it runs.
        title, body = self.current.title, self.current.body
        titles = self.vault.titles(self.workspace)
        target = Path(path).expanduser()
        self.notify(f"Exporting {FORMAT_NAMES[fmt]}…")

        def export() -> None:
            # Converters can take seconds; keep the editor responsive meanwhile.
            try:
                written = write_export(target, export_bytes(title, body, fmt, titles))
            except (OSError, ExportError) as error:
                self.call_from_thread(self.notify, f"Export failed: {error}", severity="error", timeout=12)
            else:
                self.call_from_thread(self.notify, f"Exported to {written}", timeout=10)

        self.run_worker(export, thread=True, group="export")
