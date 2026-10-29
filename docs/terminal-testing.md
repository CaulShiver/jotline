# Terminal and accessibility testing

Automated Textual Pilot tests verify application behavior, focus, and layout.
They do not establish compatibility with a screen reader, an input method, or a
particular terminal's clipboard. Record those results separately.

## Representative setups

| Platform | Terminal | Assistive/input checks |
| --- | --- | --- |
| Linux | Alacritty and GNOME Terminal | Orca where supported; IBus/Fcitx input; OSC 52 policy |
| macOS | Terminal and iTerm2 | VoiceOver, system input methods, Control shortcuts |

These are coverage targets, not claims that every combination works. Report
terminal, OS, Jotline, and assistive-tool versions with each result.

## Repeatable check

Use a disposable vault: `jotline --vault PATH_TO_EMPTY_TEST_FOLDER`.

1. Start at 100×30, then 80×24 and 60×20. Capture a note without opening help.
   Confirm writing remains visible and dialogs can scroll to every control.
2. Use only Tab, Shift+Tab, arrows, Enter, Space and Escape to navigate
   collections, views, actions, imports and recovery. Confirm visible focus and
   a predictable return to the editor after cancelling.
3. Open **Find within current note** from Ctrl+P. Type `cat` into a note
   containing `cat catalog Cat`, toggle **Match case** and **Whole word** using
   Tab and Space, and read the match count and line context. Reach Next,
   Previous, Replace, Replace all and Done without a pointer, including at
   60×20. Confirm Shift+Tab reverses focus, F3/Shift+F3 navigate matches, and
   Escape returns focus to writing; undo a replacement in the editor.
4. Open **Table of contents** from Ctrl+P and from Markdown preview. Check
   filtering, heading level and line number, arrow/Enter selection, a long
   scrollable list, and Escape. Choosing a heading returns to that editor line
   or preview heading; cancelling the preview contents returns to the preview.
   Include repeated headings, setext headings, and a note with no headings.
5. Preview and export a note containing `A reference[^one].` and
   `[^one]: A footnote.`. Verify reference numbers, definition text, and return
   links. In preview use Ctrl+T → **Footnote 1**, then Ctrl+T → **Return to
   footnote 1 reference**, without a pointer, including a note with no headings.
   Inline links themselves are not Tab stops. Record whether the keyboard route
   and exported links are announced; do not infer support from a mouse click.
   Escape must still return focus to writing.
6. Try a dark and light theme. Check text, selected rows, focused controls, errors
   and disabled controls. Meaning must remain clear without relying on color.
7. Paste `café 日本語 مرحبا 👩🏽‍💻`, then enter composed characters using the
   platform's input method. Save, reopen and export; compare exact text. Check
   selection, cursor movement and undo around combining marks and wide glyphs.
8. Copy a synthetic note, paste into another application, and verify the result.
   On macOS, `pbpaste` should match after Copy (pbcopy), even in Terminal.app.
   When no OS clipboard tool is available, Jotline should describe OSC 52 as a
   request, not claim that the destination clipboard was successfully changed.
9. Enable the screen reader. Check whether editor text, labels, focus, dialog
   changes and save failures are announced. Include find options and match-count
   changes, table-of-contents results and selected headings, and footnote
   references/definitions/backlinks in both preview and exported HTML. Record
   missing announcements as failures, even if the visual workflow works. Do not label the app accessible
   solely because its controls accept keyboard input.
10. Change the note externally while local edits are unsaved. Recover the draft,
   inspect the external version, and confirm both copies remain available.
11. Quit normally and verify saved text. Repeat startup with a non-writable or
   busy vault and verify errors are understandable and no input is lost silently.

## Automated writing qualification

Run the current locked environment with:

```sh
uv sync --locked --extra dev --extra encryption
uv run --locked pytest -q tests/test_accessibility.py tests/test_writing_accessibility.py
```

The writing qualification uses the actual Ctrl+P keyboard path, Tab/Shift+Tab,
Space, Enter and Escape at 60×20, 80×24 and 100×30. Find is checked in dark and
light themes. Tests check explicit labels/tooltips (not only internal widget
IDs), match-count text, focus containment and return, and compositor visibility
of focused controls after scrolling. A control's coordinates being inside the
screen is insufficient if a parent clips it or a scrollbar covers it. Theme
parameterization checks behavior/layout, **not** measured contrast or spoken
announcements. Unicode insertion is storage coverage, **not** IME composition.
The footnote check uses the preview Contents palette to jump to a definition
and back to its first reference, including a footnotes-only note, and checks
Home/End scrolling and Escape back to the unchanged source. Exported link titles
are checked, but their announcement still needs a native browser/screen reader.
**Known limitation:** Textual's inline footnote links are not individual Tab
stops. The Contents palette is the keyboard alternative; its return entry goes
to the first reference. Pointer backlinks support each repeated occurrence.
Do not claim that the inline links themselves have been keyboard-qualified.

The separate **Latest allowed dependencies** CI workflow executes the whole
suite, including these tests, against installed upgraded dependencies on Linux
with Python 3.11/3.13. It runs weekly and on dependency changes, with a manual
trigger for release qualification; download its version list and generated lock
for reproducibility. The ordinary Linux/macOS/Python 3.11–3.13 CI matrix stays
locked. Neither workflow can satisfy the native checks below.

## Newcomer task study

Give a person the install one-liner from the README (not a wheel filename) and
these tasks, without teaching shortcuts: install, capture an idea, find it,
append it to a project using an action, and recover a conflicted edit. Record
completion, time, help required, and the person's description of any confusion.
Use findings to prioritize UI changes.

Automated coverage of that path:

- Installer: `tests/test_install.py` plus CI smoke through `scripts/install.py`
  on Linux and macOS.
- Open-to-first-keystroke, find, append-to-project, recover:
  `tests/test_newcomer_flow.py`. Jotline still opens on a blank page (`startup`
  defaults to `new`); typing does not require a title or a wizard.

Human runs are still required for PATH/shell, Terminal.app, and clipboard/IME.

## Current verification limits

The release runs automated tests and installed-wheel smoke checks on Linux
and macOS. Local headless and POSIX PTY checks can validate rendering
startup, keyboard input and note persistence, but cannot certify native emulator,
clipboard, screen-reader or IME behavior. Those require the checks above.
Windows is out of scope.

## 1.0 ship criterion

1.0 needs one filled native report for each of Terminal.app (VoiceOver + IME +
clipboard) and a Linux terminal with Orca. Templates live in
[terminal-reports/](terminal-reports/). [macos-27-terminal.md](terminal-reports/macos-27-terminal.md)
covers Terminal.app keyboard, IME, clipboard, and recovery with VoiceOver off;
that does not satisfy the VoiceOver half of this gate. The headless Linux pass
in that folder is **toward** 1.0, not a substitute. Issue
[#2](https://github.com/CaulShiver/jotline/issues/2) is the native-emulator
report; [#3](https://github.com/CaulShiver/jotline/issues/3) stays open until
VoiceOver or Orca is actually on. Do not close them from CI or Pilot tests.

### Evidence still required for this writing upgrade

The existing macOS 27 report predates the find/contents/footnote qualification
above and ran with VoiceOver **off**. It is not evidence for the new controls or
for screen-reader compatibility. A Linux cloud test run cannot certify macOS,
VoiceOver, Orca on a graphical desktop, native clipboard policy, or composition
through a system IME. Those checks remain **pending**, not passed or waived.

Before declaring the native gate satisfied, attach dated reports identifying
the tested commit/version, terminal and OS versions, assistive tool and IME,
and results for all new writing steps. Include spoken output or the exact
missing announcement and reproduction sequence for failures. A test skipped
because the native environment is unavailable stays pending. Keep the native
release gate open until both required platform reports are complete.
