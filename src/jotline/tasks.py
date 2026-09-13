"""Checkbox tasks gathered across notes, with optional due dates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

TASK = re.compile(r"(?P<lead>[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+\[)(?P<mark>[ xX])(?P<gap>\][ \t]+)(?P<text>\S.*)")
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
# `due:2026-09-20`, or the 📅 marker used by Obsidian's Tasks plugin.
DUE = re.compile(r"(?:(?<!\S)due:|\U0001F4C5\uFE0F?[ \t]*)(\d{4}-\d{2}-\d{2})(?!\S)")


@dataclass(frozen=True)
class Task:
    note_id: str
    note_title: str
    line: int
    text: str
    done: bool
    due: str | None

    def reference(self, note_ref: str | None = None) -> str:
        return f"{note_ref or self.note_id}:{self.line}"

    def overdue(self, today: date | None = None) -> bool:
        return not self.done and self.due is not None and self.due < (today or date.today()).isoformat()


def due_date(text: str) -> str | None:
    for match in DUE.finditer(text):
        try:
            if date.fromisoformat(match[1]).isoformat() == match[1]:
                return match[1]
        except ValueError:
            continue
    return None


def task_lines(body: str):
    """(line number, line without its ending, ending, match) for each task outside fenced code.

    Lines follow str.splitlines, the same model as the editor, so line numbers
    match the rows shown in the app.
    """
    fence = None
    for number, line in enumerate(body.splitlines(keepends=True), start=1):
        content = line.splitlines()[0] if line.splitlines() else ""
        ending = line[len(content):]
        marker = FENCE.fullmatch(content)
        if marker:
            run, suffix = marker.groups()
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence) and not suffix.strip():
                fence = None
            continue
        if fence is None and (match := TASK.fullmatch(content)):
            yield number, content, ending, match


def note_tasks(note) -> list[Task]:
    return [Task(note.id, note.title, number, match["text"].strip(), match["mark"] != " ", due_date(match["text"]))
            for number, _, _, match in task_lines(note.body)]


def gather(notes, *, include_done: bool = False, due_by: str | None = None) -> list[Task]:
    """Tasks from the given notes: dated tasks first by due date, then the rest in note order."""
    found = []
    for note in notes:
        if note.collection == "trash" or getattr(note, "locked", False):
            continue
        found.extend(task for task in note_tasks(note)
                     if (include_done or not task.done) and (due_by is None or (task.due and task.due <= due_by)))
    return sorted(found, key=lambda task: (task.due is None, task.due or ""))


def set_done(body: str, line: int, done: bool) -> tuple[str, Task]:
    """Check or uncheck the task on a line, keeping everything else byte for byte."""
    for number, content, ending, match in task_lines(body):
        if number == line:
            mark = "x" if done else " "
            updated = match["lead"] + mark + match["gap"] + match["text"]
            lines = body.splitlines(keepends=True)
            lines[number - 1] = updated + ending
            task = Task("", "", number, match["text"].strip(), done, due_date(match["text"]))
            return "".join(lines), task
    raise ValueError(f"Line {line} is not a task; run jotline tasks to see current line numbers")


def parse_reference(value: str) -> tuple[str, int]:
    note, separator, line = value.rpartition(":")
    if not separator or not note or not line.isdigit() or int(line) < 1:
        raise ValueError("Name a task as NOTE:LINE, as printed by jotline tasks")
    return note, int(line)


def due_limit(value: str) -> str:
    if value == "today":
        return date.today().isoformat()
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except ValueError:
        pass
    raise ValueError("Use a date like 2026-09-20, or today")


def short_ids(ids) -> dict[str, str]:
    """The shortest prefix of each ID (at least 8 characters) that no other ID shares."""
    ordered = sorted(set(ids))
    result = {}
    for index, note_id in enumerate(ordered):
        length = 8
        for neighbour in ordered[max(index - 1, 0):index] + ordered[index + 1:index + 2]:
            common = next((i for i, (a, b) in enumerate(zip(note_id, neighbour)) if a != b),
                          min(len(note_id), len(neighbour)))
            length = max(length, common + 1)
        result[note_id] = note_id[:length]
    return result
