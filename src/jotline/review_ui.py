"""Open tasks across notes, and document export, composed into the main app."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from textual.widgets import TextArea

from .export import FORMAT_NAMES, ExportError, export_bytes, suggested_name, write_export
from .tasks import gather


class ReviewMixin:
    def review_commands(self, Command):
        return [Command(key, label, handler) for key, label, handler in [
            ("tasks", "Open tasks across notes", self.show_tasks),
            ("export-html", "Export note as HTML…", lambda: self.prompt_export("html")),
            ("export-docx", "Export note as Word document…", lambda: self.prompt_export("docx")),
            ("export-pdf", "Export note as PDF…", lambda: self.prompt_export("pdf")),
        ]]

    def show_tasks(self) -> None:
        from .app import Palette

        if not self.save_current():
            return
        found = gather(self.vault.search(workspace=self.workspace))
        if not found:
            self.notify("No open tasks in this workspace. Start a line with - [ ] in any note to add one.")
            return
        today = date.today().isoformat()
        choices = []
        for task in found:
            label = "☐ " + task.text
            if task.due:
                label += f" · due {task.due}" + (" (overdue)" if task.due < today else "")
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
        note = self.current
        titles = {other.id: other.title for other in self.vault.search(workspace=self.workspace)}
        target = Path(path).expanduser()
        self.notify(f"Exporting {FORMAT_NAMES[fmt]}…")

        def export() -> None:
            # Converters can take seconds; keep the editor responsive meanwhile.
            try:
                written = write_export(target, export_bytes(note.title, note.body, fmt, titles))
            except (OSError, ExportError) as error:
                self.call_from_thread(self.notify, f"Export failed: {error}", severity="error", timeout=12)
            else:
                self.call_from_thread(self.notify, f"Exported to {written}", timeout=10)

        self.run_worker(export, thread=True, group="export")
