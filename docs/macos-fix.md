# macOS autosave shutdown fix

The main-branch [CI run 34695124674](https://github.com/CaulShiver/jotline/actions/runs/34695124674)
failed on macOS / Python 3.12 in
`test_find_starts_at_cursor_on_later_line_with_unicode`. The recorded exception
was `textual.css.query.NoMatches: No nodes match '#brand' on Screen(id='_default')`.
The call chain was timer tick → autosave → save_current → refresh_notes.

Textual 8.2.8 sets its public `is_running` state to false before asynchronously
pruning widgets during shutdown. App timers can still fire before the message
pump finishes closing. Jotline's autosave callback previously checked only whether
the note was dirty and could attempt to refresh widgets that had been removed.

`autosave` now also checks `is_running`. Normal Ctrl+Q still saves the buffer
before requesting exit; saving while a modal is open continues to work. This is
an app lifecycle fix, not a macOS-only storage workaround.

The deterministic regression test in `tests/test_shutdown.py` inserts a timer
callback into actual Textual shutdown after removal of the brand widget. It
reproduced the same exception before the fix and passes afterward. It also checks
that a live Find dialog does not block autosave. The originally failing Unicode
search test passes locally too.

The reproduction and validation were run on Linux with Textual 8.2.8. A native
macOS run of this new commit is still needed; this workspace has no Mac runtime.
The CI failure alone does not identify any separate installation, terminal-key,
or launch problem on a user's Mac.
