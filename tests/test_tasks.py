"""Checkbox tasks gathered across notes, listed and checked off from the shell and the app."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from textual.widgets import TextArea

from jotline.app import Jotline, Palette
from jotline.store import Note, Vault
from jotline.tasks import due_date, gather, note_tasks, parse_reference, set_done, short_ids


def run_cli(vault: Path, *args) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([sys.executable, "-m", "jotline", "--vault", os.fsencode(vault), *args],
                          capture_output=True, check=False, timeout=30)


def saved(vault: Vault, body: str, note_id: str, **fields) -> Note:
    note = vault.new(body, workspace=fields.pop("workspace", "default"))
    note.id = note_id
    for name, value in fields.items():
        setattr(note, name, value)
    vault.save(note)
    return note


def test_tasks_are_found_outside_fenced_code_with_editor_line_numbers():
    body = ("# Plan\r\n- [ ] call Sam due:2026-09-20\n* [x] done thing\n```\n- [ ] not a task\n```\n"
            "1. [ ] numbered\n  - [X] nested\n- [] nope\n-[ ] nope\n- [ ]")
    tasks = note_tasks(Note("n1", body))
    assert [(task.line, task.text, task.done, task.due) for task in tasks] == [
        (2, "call Sam due:2026-09-20", False, "2026-09-20"), (3, "done thing", True, None),
        (7, "numbered", False, None), (8, "nested", True, None)]


def test_due_dates_accept_the_obsidian_marker_and_ignore_invalid_dates():
    assert due_date("pay \U0001F4C5 2026-09-21") == "2026-09-21"
    assert due_date("pay \U0001F4C5️2026-09-22") == "2026-09-22"
    assert due_date("pay due:2026-02-30") is None
    assert due_date("overdue:2026-01-01") is None


def test_gather_puts_dated_tasks_first_and_skips_done_trash_and_locked_notes():
    notes = [Note("a", "- [ ] undated\n- [ ] later due:2026-10-01\n- [x] finished"),
             Note("b", "- [ ] sooner due:2026-09-01"),
             Note("c", "- [ ] binned", collection="trash"),
             Note("d", "", encrypted=True, sealed="jotline-encrypted: 1\nAAAA\n")]
    assert [task.text for task in gather(notes)] == ["sooner due:2026-09-01", "later due:2026-10-01", "undated"]
    assert [task.text for task in gather(notes, include_done=True)][-1] == "finished"
    assert [task.text for task in gather(notes, due_by="2026-09-15")] == ["sooner due:2026-09-01"]


def test_set_done_changes_only_the_checkbox():
    body = "intro\r\n- [ ] ship it due:2026-09-20\r\nend"
    updated, task = set_done(body, 2, True)
    assert updated == "intro\r\n- [x] ship it due:2026-09-20\r\nend"
    assert task.text == "ship it due:2026-09-20"
    assert set_done(updated, 2, False)[0] == body
    with pytest.raises(ValueError, match="Line 1 is not a task"):
        set_done(body, 1, True)


def test_task_references_and_short_ids():
    assert parse_reference("abcd1234:12") == ("abcd1234", 12)
    for bad in ("abcd", "abcd:0", ":3", "abcd:x"):
        with pytest.raises(ValueError, match="NOTE:LINE"):
            parse_reference(bad)
    assert short_ids(["daily-2026-09-12", "daily-2026-09-13", "abcdef0123456789"]) == {
        "daily-2026-09-12": "daily-2026-09-12", "daily-2026-09-13": "daily-2026-09-13",
        "abcdef0123456789": "abcdef01"}


def test_cli_lists_tasks_and_checks_one_off(tmp_path):
    vault = Vault(tmp_path)
    plan = saved(vault, "Plan #work\n- [ ] call Sam due:2026-09-20\n- [x] old", "abcdef0123456789")
    saved(vault, "Other\n- [ ] read", "0123456789abcdef")
    saved(vault, "Gone\n- [ ] hidden", "ffff000011112222", collection="trash")
    saved(vault, "Side\n- [ ] elsewhere", "eeee000011112222", workspace="side")
    result = run_cli(tmp_path, "tasks")
    assert result.returncode == 0, result.stderr
    assert result.stdout.decode().splitlines() == [
        "abcdef01:2\t[ ]\t2026-09-20\tcall Sam due:2026-09-20\tPlan #work",
        "01234567:2\t[ ]\t-\tread\tOther"]
    assert json.loads(run_cli(tmp_path, "tasks", "#work", "--done", "--json").stdout) == [
        {"note": plan.id, "line": 2, "text": "call Sam due:2026-09-20", "done": False, "due": "2026-09-20",
         "title": "Plan #work"},
        {"note": plan.id, "line": 3, "text": "old", "done": True, "due": None, "title": "Plan #work"}]
    assert run_cli(tmp_path, "tasks", "--due", "2026-09-19").stdout == b""

    finished = run_cli(tmp_path, "done", "abcdef01:2")
    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.decode() == "[x]\tcall Sam due:2026-09-20\n"
    assert vault.read(plan.id).body == "Plan #work\n- [x] call Sam due:2026-09-20\n- [x] old"
    assert run_cli(tmp_path, "done", "abcdef01:2", "--undo").returncode == 0
    assert vault.read(plan.id).body == "Plan #work\n- [ ] call Sam due:2026-09-20\n- [x] old"

    not_task = run_cli(tmp_path, "done", "abcdef01:1")
    assert not_task.returncode == 1
    assert "Line 1 is not a task" in not_task.stderr.decode()
    bad_date = run_cli(tmp_path, "tasks", "--due", "someday")
    assert bad_date.returncode == 2
    assert "Use a date like 2026-09-20, or today" in bad_date.stderr.decode()


async def test_app_lists_open_tasks_and_jumps_to_the_line(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Plan\n\n- [ ] first\n- [ ] second due:2026-01-01", "abcdef0123456789")
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.command("tasks")
        await pilot.pause()
        palette = app.screen
        assert isinstance(palette, Palette)
        assert [label for _, label in palette.choices] == [
            "☐ second due:2026-01-01 · due 2026-01-01 (overdue) · Plan", "☐ first · Plan"]
        palette.dismiss(palette.choices[1][0])
        await pilot.pause()
        assert app.current.id == note.id
        assert app.query_one("#editor", TextArea).cursor_location == (2, 0)
