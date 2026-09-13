"""Regressions from the 2026-09-12 multi-agent red team (storage, CLI, parsing, UI)."""
from dataclasses import replace
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from textual import events
from textual.widgets import Input, OptionList, TextArea

from jotline import cli as cli_module, history
from jotline.action_history import ActionHistory
from jotline.action_recipes import write_recipes
from jotline.action_ui import ActionEditor
from jotline.app import Jotline, MarkdownPreview, Palette, TextPrompt
from jotline.importing import apply_import, preview_import
from jotline.note_menu import NoteMenu
from jotline.recovery_ui import RecoveryScreen
from jotline.settings import Settings
from jotline.store import Vault
import jotline.store as store
from jotline.templates import Templates
from jotline.markdown_editor import headings, heading_title

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX-only behaviour")


def run_cli(vault: Path, *args: str, input: bytes | None = None, **kwargs):
    return subprocess.run([sys.executable, "-m", "jotline", "--vault", str(vault), *args],
                          input=input, capture_output=True, check=False, **kwargs)


def refuse_links(monkeypatch):
    def link(*args, **kwargs):
        raise OSError(errno.EPERM, "Operation not permitted")
    monkeypatch.setattr(store.os, "link", link)


# --- storage -----------------------------------------------------------------

def test_saves_fall_back_to_rename_where_hard_links_are_refused(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new("important")
    vault.save(note)
    refuse_links(monkeypatch)
    note.body = "important edited"
    vault.save(note)
    assert [item.body for item in vault.notes()] == ["important edited"]
    fresh = vault.new("second")
    vault.save(fresh)
    assert vault.file(fresh.id).exists()
    assert not [path for path in tmp_path.iterdir() if path.name.startswith(".jotline-displaced-")]


def test_displaced_note_warning_survives_sidebar_refresh(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new("important")
    vault.save(note)

    def fail(*args, **kwargs):
        raise OSError(errno.EIO, "boom")
    monkeypatch.setattr(store, "publish_new", fail)
    monkeypatch.setattr(store, "rename_noreplace", fail)
    note.body = "edited"
    with pytest.raises(OSError):
        vault.save(note)
    assert any("displaced" in warning for warning in vault.warnings)
    vault.notes()
    assert any("displaced" in warning for warning in vault.warnings)


def test_backup_failure_does_not_block_note_saves(tmp_path, monkeypatch):
    vault = Vault(tmp_path)

    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(history, "backup", fail)
    note = vault.new("just a few words")
    vault.save(note)
    assert vault.file(note.id).exists()
    assert "Daily backup failed" in vault.backup_warning
    recovered = vault.recovery(note)
    assert vault.file(recovered.id).exists()


def test_bom_added_by_external_editor_keeps_metadata(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("# Plan\n\nbody", workspace="work")
    note.collection, note.starred = "projects", True
    vault.save(note)
    path = vault.file(note.id)
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    back = vault.read(note.id)
    assert (back.workspace, back.collection, back.starred, back.created) == ("work", "projects", True, note.created)
    assert back.body == "# Plan\n\nbody"
    assert back.title == "Plan"


def test_history_orders_revisions_by_write_time_after_clock_step_back(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new("v1")
    stamps = iter(["20260912T013000000000-aaaaaaaa", "20260912T015900000000-bbbbbbbb",
                   "20260912T013005000000-cccccccc"])
    monkeypatch.setattr(history, "stamp", lambda: next(stamps))
    vault.save(note)
    for body in ("v2", "v3"):
        time.sleep(0.01)
        note.body = body
        vault.save(note)
    assert vault.history_notes("default")[0].body == "v3"


def test_stale_temp_files_are_pruned_and_reported(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    vault.save(vault.new("existing"))
    stale = tmp_path / ".jotline-backups" / (".backup-" + "0" * 32)
    stale.write_bytes(b"partial")
    old = time.time() - 2 * history.STALE_TEMP_SECONDS
    os.utime(stale, (old, old))
    report = cli_module.doctor_report(vault, "")
    assert any(".backup-" in warning for warning in report["warnings"])
    vault.backup()
    assert not stale.exists()


def test_corrupt_action_history_is_quarantined_on_append(tmp_path):
    (tmp_path / ".jotline-action-history.json").write_text('{"not": "a list"')
    warning = ActionHistory(tmp_path).append({"time": "t", "name": "x", "note_id": "n", "workspace": "default",
                                              "status": "completed", "steps": []})
    assert "set aside" in warning
    assert len(ActionHistory(tmp_path).read()) == 1
    assert list(tmp_path.glob(".jotline-action-history.invalid-*.json"))


def test_folder_import_of_jotline_notes_keeps_their_metadata(tmp_path):
    old = Vault(tmp_path / "old")
    note = old.new("# Quarterly plan\n\ntext", workspace="work")
    note.collection, note.starred = "projects", True
    old.save(note)
    source = tmp_path / "unzipped-backup"
    source.mkdir()
    (source / f"{note.id}.md").write_bytes(old.file(note.id).read_bytes())
    new = Vault(tmp_path / "new")
    apply_import(new, preview_import(new, source, "work"))
    got = new.notes()[0]
    assert got.title == "Quarterly plan"
    assert (got.collection, got.starred, got.workspace) == ("projects", True, "work")


def test_drafts_uuid_must_be_text(tmp_path):
    vault = Vault(tmp_path)
    source = tmp_path / "x.draftsexport"
    source.write_text(json.dumps([{"content": "a", "uuid": 12}]))
    plan = preview_import(vault, source)
    assert plan.warnings == ["x.draftsexport #1: Draft uuid must be a string"]


@posix_only
def test_symlinked_ancestor_reports_the_link(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    with pytest.raises(OSError, match="passes through a link at link"):
        write_recipes(tmp_path / "link/r.json", {"a": [{"type": "strip"}]})


def test_recipe_export_works_without_hard_links(tmp_path, monkeypatch):
    refuse_links(monkeypatch)
    write_recipes(tmp_path / "r.json", {"a": [{"type": "strip"}]})
    assert (tmp_path / "r.json").exists()
    with pytest.raises(FileExistsError):
        write_recipes(tmp_path / "r.json", {"a": [{"type": "strip"}]})


def test_templates_skip_stray_entries(tmp_path):
    Vault(tmp_path)
    templates = Templates(tmp_path)
    templates.save("good", "x")
    (tmp_path / ".jotline-templates/stray.md").mkdir()
    assert "good" in templates.names()


def test_cli_waits_longer_for_the_vault_lock(tmp_path):
    vault = Vault(tmp_path)
    vault.save(vault.new("seed"))
    with vault.locked():
        started = time.monotonic()
        result = run_cli(tmp_path, "capture", "held", timeout=30)
        elapsed = time.monotonic() - started
    assert result.returncode == 1 and b"busy" in result.stderr
    assert elapsed >= 5


# --- settings ------------------------------------------------------------------

def test_one_invalid_setting_keeps_every_other_preference(tmp_path):
    Vault(tmp_path)
    path = tmp_path / ".jotline-settings.json"
    original = {"theme": "theme-from-a-newer-release", "sidebar_width": 40,
                "actions": {"my-recipe": [{"type": "uppercase"}]},
                "saved_views": {"v": {"workspace": "default", "query": "x", "collection": "all",
                                      "sort": "updated", "theme": ""}},
                "hotkeys": {"new": "f5"}, "workspace_names": ["default", "work"], "future_key": 1}
    path.write_text(json.dumps(original))
    settings, warning = Settings.load(path)
    assert "theme" in warning
    assert settings.sidebar_width == 40 and settings.actions == original["actions"]
    assert settings.theme == "jotline"
    replace(settings, active_workspace="work").save(path)
    after = json.loads(path.read_text())
    assert after["actions"] == original["actions"] and after["saved_views"] == original["saved_views"]
    assert after["hotkeys"] == {"new": "f5"} and after["sidebar_width"] == 40
    assert after["future_key"] == 1 and after["active_workspace"] == "work"
    assert after["theme"] == "jotline"


def test_unreadable_settings_are_set_aside_not_overwritten(tmp_path):
    Vault(tmp_path)
    path = tmp_path / ".jotline-settings.json"
    path.write_text("{not json")
    settings, warning = Settings.load(path)
    assert warning
    settings.save(path)
    assert json.loads(path.read_text())["theme"] == "jotline"
    kept = list(tmp_path.glob(".jotline-settings.json.invalid-*.json"))
    assert len(kept) == 1 and kept[0].read_text() == "{not json"


# --- CLI ------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["a\r\nb\r\n", "family \U0001F468‍\U0001F469", "soft­hyphen", "﻿bom"])
def test_ordinary_text_is_not_a_terminal_control(text):
    assert not cli_module.has_terminal_controls(text)


@pytest.mark.parametrize("text", ["\x1b[31m", "\x07", "‮", "\x9b"])
def test_real_controls_are_still_refused(text):
    assert cli_module.has_terminal_controls(text)
    assert cli_module.terminal_text(text) != text


def test_run_refuses_export_before_any_step_applies(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    source = vault.new("\x1b[31mred")
    vault.save(source)
    target = vault.new("target")
    vault.save(target)
    (tmp_path / ".jotline-settings.json").write_text(json.dumps(
        {"actions": {"send": [{"type": "append", "value": target.id}, {"type": "export"}]}}))
    monkeypatch.setattr(sys, "argv", ["jotline", "--vault", str(tmp_path), "run", "send", source.id])
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    with pytest.raises(SystemExit):
        cli_module.main()
    assert vault.read(target.id).body == "target"


@posix_only
def test_closed_stdin_is_a_diagnostic_not_a_traceback(tmp_path):
    result = subprocess.run([sys.executable, "-m", "jotline", "--vault", str(tmp_path), "capture"],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            preexec_fn=lambda: os.close(0))
    assert "Traceback" not in result.stderr
    assert result.returncode == 2


def test_empty_vault_flag_is_rejected(tmp_path):
    result = run_cli("", "path", cwd=tmp_path)
    assert result.returncode == 2 and b"must not be empty" in result.stderr
    assert not (tmp_path / ".jotline.lock").exists()


def test_relative_xdg_data_home_is_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv("JOTLINE_VAULT", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", "rel")
    monkeypatch.setattr(sys, "platform", "linux")
    assert cli_module.default_vault() == Path.home() / ".local/share/jotline/notes"


@posix_only
def test_broken_pipe_exits_quietly(tmp_path):
    vault = Vault(tmp_path)
    for index in range(200):
        vault.save(vault.new(f"note {index} " + "x" * 200))
    process = subprocess.Popen([sys.executable, "-m", "jotline", "--vault", str(tmp_path), "list"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.stdout.close()
    _, err = process.communicate()
    assert process.returncode == 0 and b"Broken pipe" not in err


# --- parsing and search ---------------------------------------------------------

def test_headings_regex_is_linear():
    title = "x" + " " * 40000 + "x"
    started = time.perf_counter()
    assert headings(["# " + title]) == [(0, 1, title)]
    assert heading_title(title) == title
    assert time.perf_counter() - started < 0.05
    assert headings("## Title ##\n# ##\n#\n# a#b #\n".split("\n")) == [(0, 2, "Title"), (3, 1, "a#b")]


def test_text_query_does_not_match_random_id_digits(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("banana")
    vault.save(note)
    digit = next(character for character in note.id if character.isdigit())
    assert vault.search(digit) == []
    assert [item.id for item in vault.search(note.id[:8])] == [note.id]


def test_links_match_full_first_line_beyond_the_title_limit(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new("x" * 150)
    vault.save(target)
    source = vault.new(f"see [[{'x' * 150}]]")
    vault.save(source)
    assert [item.id for item in vault.backlinks(target)] == [source.id]


# --- UI ---------------------------------------------------------------------------

def burst(app, *keys):
    for key in keys:
        app.post_message(events.Key(key, "\r" if key == "enter" else None))


def double_click(app, widget, x, y):
    for _ in range(2):
        app.post_message(events.MouseDown(widget, x, y, 0, 0, 1, False, False, False, x, y))
        app.post_message(events.MouseUp(widget, x, y, 0, 0, 1, False, False, False, x, y))
        app.post_message(events.Click(widget, x, y, 0, 0, 1, False, False, False, x, y))


async def test_palette_enter_burst_does_not_crash(tmp_path):
    vault = Vault(tmp_path)
    for index in range(3):
        vault.save(vault.new(f"# n{index}"))
    app = Jotline(vault)
    async with app.run_test(size=(100, 30)) as pilot:
        app.autosave_timer.stop()
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        burst(app, "enter", "enter")
        await pilot.pause()
        await pilot.pause()
        assert app.is_running


async def test_palette_double_click_does_not_crash(tmp_path):
    vault = Vault(tmp_path)
    for index in range(3):
        vault.save(vault.new(f"# n{index}"))
    app = Jotline(vault)
    async with app.run_test(size=(100, 40)) as pilot:
        app.autosave_timer.stop()
        await pilot.press("ctrl+o")
        await pilot.pause()
        options = app.screen.query_one(OptionList)
        double_click(app, options, options.region.x + 2, options.region.y)
        await pilot.pause()
        await pilot.pause()
        assert app.is_running


async def test_text_prompt_and_note_menu_double_dismiss(tmp_path):
    vault = Vault(tmp_path)
    vault.save(vault.new("# n"))
    app = Jotline(vault)
    async with app.run_test(size=(100, 40)) as pilot:
        app.autosave_timer.stop()
        results = []
        app.push_screen(TextPrompt("t", "p"), results.append)
        await pilot.pause()
        app.screen.query_one(Input).value = "work"
        burst(app, "enter", "enter")
        await pilot.pause()
        await pilot.pause()
        assert app.is_running and results == ["work"]
        app.push_screen(NoteMenu("n", [("move", "Move"), ("trash", "Trash")], 10, 5), results.append)
        await pilot.pause()
        options = app.screen.query_one(OptionList)
        double_click(app, options, options.region.x + 2, options.region.y)
        await pilot.pause()
        await pilot.pause()
        assert app.is_running and results == ["work", "move"]


async def test_nested_palette_burst_keeps_action_editor(tmp_path):
    vault = Vault(tmp_path)
    vault.save(vault.new("# target"))
    app = Jotline(vault)
    async with app.run_test(size=(100, 40)) as pilot:
        app.autosave_timer.stop()
        app.open_action_editor()
        await pilot.pause()
        await pilot.click("#step-target")
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        burst(app, "enter", "enter")
        await pilot.pause()
        await pilot.pause()
        assert app.is_running and isinstance(app.screen, ActionEditor)


@pytest.mark.parametrize("body", ["alpha beta", "alpha\x0cbeta", "alpha\x85beta",
                                  "alpha\rbeta\nGamma", "alpha\r\nbeta\ngamma"])
async def test_opening_a_note_never_rewrites_it(tmp_path, body):
    vault = Vault(tmp_path)
    note = vault.new(body)
    vault.save(note)
    before = vault.file(note.id).read_bytes()
    app = Jotline(vault)
    async with app.run_test(size=(100, 30)) as pilot:
        app.load_id(note.id)
        await pilot.pause()
        assert not app.dirty
        app.autosave()
        await pilot.pause()
        app.refresh_vault()
        await pilot.pause()
        assert not app.dirty
    assert vault.file(note.id).read_bytes() == before


async def test_untouched_note_gets_no_false_conflict(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("shopping milk")
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100, 30)) as pilot:
        app.autosave_timer.stop()
        await pilot.pause()
        external = vault.read(note.id)
        external.body = "shopping milk eggs"
        vault.save(external)
        app.autosave()
        await pilot.pause()
        assert not isinstance(app.screen, RecoveryScreen)


async def test_line_helpers_respect_crlf_documents(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("one\r\ntwo\r\nthree")
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100, 30)) as pilot:
        app.autosave_timer.stop()
        editor = app.query_one("#editor", TextArea)
        editor.move_cursor((1, 0))
        for _ in range(3):
            app.command("task")
            await pilot.pause()
        assert editor.text == "one\r\n- [ ] two\r\nthree"
        editor.move_cursor((0, 0))
        editor.move_cursor((1, 3), select=True)
        app.action_format_markdown("heading")
        await pilot.pause()
        assert editor.text == "## one\r\n## - [ ] two\r\nthree"
        assert editor.selection.start == (0, 3) and editor.selection.end == (1, 6)
        app.command("arrange-paragraphs")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.press("ctrl+q")
    assert vault.read(note.id).body == "## one\r\n## - [ ] two\r\nthree"


async def test_lone_cr_note_does_not_crash_task_toggle_or_find(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("one\rtwo\r- [ ] three")
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100, 30)) as pilot:
        app.autosave_timer.stop()
        editor = app.query_one("#editor", TextArea)
        editor.move_cursor((2, 0))
        app.toggle_task()
        await pilot.pause()
        assert app.is_running and editor.document.get_line(2) == "- [x] three"
        app.select_editor_match("two")
        assert editor.selected_text == "two"


async def test_arrange_paragraphs_on_crlf_note(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("p1\r\n\r\np2\r\n\r\np3")
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100, 30)) as pilot:
        app.command("arrange-paragraphs")
        await pilot.pause()
        assert len(app.screen.parts) == 3
        await pilot.press("escape")


async def test_explicit_quit_after_cancelled_conflict_reopens_dialog(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("original")
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100, 30)) as pilot:
        app.autosave_timer.stop()
        app.query_one("#editor", TextArea).load_text("my draft")
        external = vault.read(note.id)
        external.body = "theirs"
        vault.save(external)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, RecoveryScreen)
        await pilot.press("escape")
        await pilot.pause()
        app.autosave()
        await pilot.pause()
        assert not isinstance(app.screen, RecoveryScreen)
        await pilot.press("ctrl+q")
        await pilot.pause()
        assert app.is_running and isinstance(app.screen, RecoveryScreen)


async def test_reselecting_open_note_keeps_undo_history(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("base")
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100, 30)) as pilot:
        app.autosave_timer.stop()
        editor = app.query_one("#editor", TextArea)
        await pilot.press(*" typed")
        await pilot.pause()
        app.query_one("#notes", OptionList).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        editor.focus()
        await pilot.pause()
        await pilot.press("ctrl+z")
        await pilot.pause()
        assert editor.text == "base"


async def test_preview_refuses_block_heavy_notes(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("- item\n" * 2000)
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100, 30)) as pilot:
        app.autosave_timer.stop()
        app.action_preview()
        await pilot.pause()
        assert not isinstance(app.screen, MarkdownPreview)
        app.query_one("#editor", TextArea).load_text("|" + "h|" * 3000)
        await pilot.pause()
        app.action_preview()
        await pilot.pause()
        assert not isinstance(app.screen, MarkdownPreview)
        app.query_one("#editor", TextArea).load_text("# fine\n\nsome text")
        await pilot.pause()
        app.action_preview()
        await pilot.pause()
        assert isinstance(app.screen, MarkdownPreview)


def test_read_only_commands_do_not_create_a_vault(tmp_path):
    missing = tmp_path / "typo"
    for command in ("list", "doctor", "workspaces"):
        result = run_cli(missing, command)
        assert result.returncode == 1 and b"Vault does not exist" in result.stderr
        assert not missing.exists()
    result = run_cli(missing, "path")
    assert result.returncode == 0 and result.stdout.strip() == str(missing.resolve()).encode()
    assert not missing.exists()
    result = run_cli(missing, "capture", "first")
    assert result.returncode == 0 and missing.is_dir()


async def test_preview_labels_dropped_html_blocks(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("<div>box</div>\n\ntext")
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100, 30)) as pilot:
        app.autosave_timer.stop()
        app.action_preview()
        await pilot.pause()
        assert isinstance(app.screen, MarkdownPreview)
        assert "raw HTML" in str(app.screen.query_one("Label").content)
