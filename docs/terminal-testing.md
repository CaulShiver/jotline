# Terminal and accessibility testing

Automated Textual Pilot tests verify application behavior, focus, and layout.
They do not establish compatibility with a screen reader, an input method, or a
particular terminal's clipboard. Record those results separately.

## Representative setups

| Platform | Terminal | Assistive/input checks |
| --- | --- | --- |
| Linux | Alacritty and GNOME Terminal | Orca where supported; IBus/Fcitx input; OSC 52 policy |
| macOS | Terminal and iTerm2 | VoiceOver, system input methods, Control shortcuts |
| Windows | Windows Terminal / PowerShell | NVDA or Narrator, IME composition, paste behavior |

These are coverage targets, not claims that every combination works. Report
terminal, OS, Jotline, and assistive-tool versions with each result.

## Repeatable check

Use a disposable vault: `jotline --vault PATH_TO_EMPTY_TEST_FOLDER`.

1. Start at 100×30, then 80×24 and 60×20. Capture a note without opening help.
   Confirm writing remains visible and dialogs can scroll to every control.
2. Use only Tab, Shift+Tab, arrows, Enter, Space and Escape to navigate
   collections, views, actions, imports and recovery. Confirm visible focus and
   a predictable return to the editor after cancelling.
3. Try a dark and light theme. Check text, selected rows, focused controls, errors
   and disabled controls. Meaning must remain clear without relying on color.
4. Paste `café 日本語 مرحبا 👩🏽‍💻`, then enter composed characters using the
   platform's input method. Save, reopen and export; compare exact text. Check
   selection, cursor movement and undo around combining marks and wide glyphs.
5. Copy a synthetic note, paste into another application, and verify the result.
   Repeat with OSC 52 disabled: Jotline should describe clipboard access as a
   request, not claim that the destination clipboard was successfully changed.
6. Enable the screen reader. Check whether editor text, labels, focus, dialog
   changes and save failures are announced. Record missing announcements as
   failures, even if the visual workflow works. Do not label the app accessible
   solely because its controls accept keyboard input.
7. Change the note externally while local edits are unsaved. Recover the draft,
   inspect the external version, and confirm both copies remain available.
8. Quit normally and verify saved text. Repeat startup with a non-writable or
   busy vault and verify errors are understandable and no input is lost silently.

## Newcomer task study

Give a person the install link and these tasks, without teaching shortcuts:
install, capture an idea, find it, append it to a project using an action, and
recover a conflicted edit. Record completion, time, help required, and the
person's description of any confusion. Use findings to prioritize UI changes.

## Current verification limits

The release runs automated tests and installed-wheel smoke checks on Linux,
macOS and Windows. Local headless and POSIX PTY checks can validate rendering
startup, keyboard input and note persistence, but cannot certify native emulator,
clipboard, screen-reader or IME behavior. Those require the checks above.

## Filing a report

Copy [docs/terminal-reports/TEMPLATE.md](terminal-reports/TEMPLATE.md) into
`docs/terminal-reports/` with a filename that names the OS and terminal.
Fill only checks you ran; write `not tested` for the rest. Open a pull request
and mention [issue #2](https://github.com/CaulShiver/jotline/issues/2) for a
native macOS or Windows terminal report, or
[issue #3](https://github.com/CaulShiver/jotline/issues/3) for screen-reader
behavior. Reports without hardware must not invent results.
