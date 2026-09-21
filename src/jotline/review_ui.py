"""Open tasks across notes, and document export, composed into the main app."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from textual.containers import VerticalScroll
from textual.widgets import Markdown

from .export import FORMAT_NAMES, ExportError, export_bytes, printable_markdown, suggested_name, write_export
from .markdown_editor import MarkdownEditor, headings
from .modal import Palette, TextPrompt
from .screens import MarkdownPreview
from .tasks import gather, set_done


class Review:
    """Task list and export. Bound onto Jotline; not inherited."""

    def review_commands(self, Command):
        return [
            Command("tasks", "Open tasks across notes", self.show_tasks, group="everyday"),
            Command("tasks-due", "Open tasks due today or overdue", self.show_tasks_due, group="everyday"),
            Command("task-done", "Tick off a task", self.choose_task_to_tick, group="everyday"),
            Command("process-inbox", "Process next inbox note", self.action_process_inbox, "process_inbox",
                    group="everyday"),
            Command("export-html", "Export note as HTML…", lambda: self.prompt_export("html")),
            Command("export-docx", "Export note as Word document…", lambda: self.prompt_export("docx")),
            Command("export-pdf", "Export note as PDF…", lambda: self.prompt_export("pdf")),
        ]

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

    def task_label(self, task, today: date) -> str:
        """One task as the picker shows it, saying plainly when it is due.

        Overdue was already marked; today was not, and a task due today reads
        as just another dated line without it.
        """
        label = "\u2610 " + task.text
        if task.due:
            if task.overdue(today):
                label += f" \u00b7 due {task.due} (overdue)"
            elif task.due == today.isoformat():
                label += " \u00b7 due today"
            else:
                label += f" \u00b7 due {task.due}"
        return label + " \u00b7 " + task.note_title

    def open_tasks(self, due_by: str | None = None):
        return gather(self.vault.search(workspace=self.workspace), due_by=due_by)

    def task_picker(self, title: str, empty: str, due_by: str | None = None) -> list[tuple[str, str]] | None:
        """Choices for a task picker, or None when there is nothing to pick."""
        found = self.open_tasks(due_by)
        if not found:
            self.notify(empty)
            return None
        today = date.today()
        return [(task.reference(), self.task_label(task, today)) for task in found]

    def show_tasks(self) -> None:
        if not self.save_current():
            return
        choices = self.task_picker(
            "tasks", "No open tasks in this workspace. Start a line with - [ ] in any note to add one.")
        if choices is None:
            return
        self.push_screen(Palette(choices, f"Open tasks \u00b7 {len(choices)}"), self.open_task)

    def show_tasks_due(self) -> None:
        """The same list narrowed to what is actually owed, which is the agenda question.

        `jotline tasks --due today` has answered it from the shell since tasks
        arrived; inside the app the only list was everything, at any date.
        """
        if not self.save_current():
            return
        today = date.today()
        choices = self.task_picker("due", f"Nothing is due by {today.isoformat()}. Open tasks lists the rest.",
                                   due_by=today.isoformat())
        if choices is None:
            return
        self.push_screen(Palette(choices, f"Due today or overdue \u00b7 {len(choices)}"), self.open_task)

    def choose_task_to_tick(self) -> None:
        if not self.save_current():
            return
        choices = self.task_picker("tick", "No open tasks in this workspace.")
        if choices is None:
            return
        self.push_screen(Palette(choices, "Tick off a task"), self.tick_task)

    def tick_task(self, reference: str | None) -> None:
        """Check a task off where it lives, without leaving the list to do it.

        The note is rewritten line for line by set_done, the same call the
        `jotline done` command uses, so a task ticked here and one ticked from
        the shell leave the file in the same state.
        """
        if not reference:
            return
        note_id, _, line = reference.rpartition(":")
        try:
            note = self.vault.read(note_id)
            if note.locked:
                self.prompt_unlock(then=lambda: self.tick_task(reference))
                return
            checked = {}

            def check(body: str) -> str:
                updated, checked["task"] = set_done(body, int(line), True)
                return updated

            note = self.vault.update_body(note_id, self.workspace, check)
        except (OSError, ValueError) as error:
            self.notify(str(error), severity="error", timeout=12)
            return
        if self.current.id == note_id:
            # load_id would see the same id and do nothing; the note in hand is
            # the one that changed.
            self.load(note)
        self.refresh_notes()
        self.notify("[x] " + checked["task"].text)

    def open_task(self, reference: str | None) -> None:
        if not reference:
            return
        note_id, _, line = reference.rpartition(":")
        self.load_id(note_id)
        if self.current.id == note_id:
            editor = self.query_one("#editor", MarkdownEditor)
            editor.move_cursor((min(int(line), editor.document.line_count) - 1, 0), center=True)

    def prompt_export(self, fmt: str) -> None:
        self.capture_current_buffer()
        folder = Path.home() / "Documents"
        suggestion = (folder if folder.is_dir() else Path.home()) / suggested_name(self.current.title, fmt)
        self.push_screen(TextPrompt(f"Export as {FORMAT_NAMES[fmt]} · file to write", "Path of the new file",
                                    str(suggestion)),
                         lambda path: self.export_current(fmt, path) if path else None)

    def export_current(self, fmt: str, path: str) -> None:
        if not self.save_current(explicit=True):
            return
        title, body = self.current.title, self.current.body
        titles = self.vault.titles(self.workspace)
        target = Path(path).expanduser()
        self.notify(f"Exporting {FORMAT_NAMES[fmt]}…")

        def export() -> None:
            try:
                written = write_export(target, export_bytes(title, body, fmt, titles))
            except (OSError, ExportError) as error:
                self.call_from_thread(self.notify, f"Export failed: {error}", severity="error", timeout=12)
            else:
                self.call_from_thread(self.notify, f"Exported to {written}", timeout=10)

        self.run_worker(export, thread=True, group="export")

    PREVIEW_MAX_BLOCKS = 600
    PREVIEW_MAX_CELLS = 400
    PREVIEW_MAX_BYTES = 256 * 1024

    def preview_fits(self, body: str) -> bool:
        lines = body.splitlines()
        blocks = sum(1 for line in lines if line.strip())
        cells = sum(line.count("|") for line in lines)
        return (len(body.encode("utf-8")) <= self.PREVIEW_MAX_BYTES and blocks <= self.PREVIEW_MAX_BLOCKS
                and cells <= self.PREVIEW_MAX_CELLS)

    def note_titles(self) -> dict[str, str]:
        try:
            return self.vault.titles(self.workspace)
        except (OSError, ValueError):
            return {}

    def preview_markdown(self, body: str) -> str:
        return printable_markdown(body, self.note_titles() if "[[" in body else {}, followable=True)

    def action_preview(self) -> None:
        self.capture_current_buffer()
        body = self.current.body
        if not self.preview_fits(body):
            self.notify(f"Preview supports notes up to {self.PREVIEW_MAX_BYTES // 1024} KiB and "
                        f"{self.PREVIEW_MAX_BLOCKS} lines of content and {self.PREVIEW_MAX_CELLS} table separators. "
                        "You can still edit and save this note.",
                        severity="warning")
            return
        self.push_screen(MarkdownPreview(self.preview_markdown(body)))

    def action_live_preview(self) -> None:
        if not self.live_preview and self.compact_layout:
            self.notify("Side-by-side preview needs a terminal wider than 80 columns and taller than 24 rows; "
                        "showing the full preview instead.")
            self.action_preview()
            return
        self.live_preview = not self.live_preview
        self._live_preview_text = self._live_preview_ratio = None
        self.update_responsive_layout()
        self.query_one("#editor", MarkdownEditor).focus()

    def schedule_live_preview(self) -> None:
        if not self.live_preview_visible:
            return
        if self._live_preview_timer is not None:
            self._live_preview_timer.stop()
        self._live_preview_timer = self.set_timer(0.3, self.refresh_live_preview)

    def refresh_live_preview(self) -> None:
        self._live_preview_timer = None
        if not self.live_preview_visible or not self.is_running:
            return
        editor = self.query_one("#editor", MarkdownEditor)
        body = editor.text
        text = (self.preview_markdown(body) if self.preview_fits(body) else
                f"*Preview paused: this note is longer than {self.PREVIEW_MAX_BLOCKS} lines of content "
                f"or {self.PREVIEW_MAX_BYTES // 1024} KiB, or has more than {self.PREVIEW_MAX_CELLS} table separators. "
                "Editing and saving still work.*")
        ratio = editor.cursor_location[0] / max(1, editor.document.line_count - 1)
        changed = text != self._live_preview_text
        if not changed and ratio == self._live_preview_ratio:
            return
        self._live_preview_text, self._live_preview_ratio = text, ratio
        self.run_worker(self.render_live_preview(text if changed else None), group="live-preview")

    async def render_live_preview(self, text: str | None) -> None:
        async with self._live_preview_lock:
            if text is not None:
                await self.query_one("#live-markdown", Markdown).update(text)
            pane = self.query_one("#live-preview", VerticalScroll)
            self.call_after_refresh(lambda: pane.scroll_to(
                y=pane.max_scroll_y * (self._live_preview_ratio or 0.0), animate=False))

    def action_outline(self) -> None:
        editor = self.query_one("#editor", MarkdownEditor)
        found = headings(editor.document.lines)
        if not found:
            self.notify("No headings yet. Start a line with # to add one.")
            return
        self.push_screen(Palette([(str(row), "  " * (level - 1) + title + f" · line {row + 1}")
                                  for row, level, title in found], "Jump to heading"), self.jump_to_row)

    def jump_to_row(self, key: str | None) -> None:
        editor = self.query_one("#editor", MarkdownEditor)
        if key and key.isdigit() and int(key) < editor.document.line_count:
            editor.move_cursor((int(key), 0), center=True)
        editor.focus()
