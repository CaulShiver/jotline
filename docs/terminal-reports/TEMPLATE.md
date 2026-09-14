# Terminal compatibility report

Copy this file to a new name in `docs/terminal-reports/` (for example
`macos-iterm2.md`). Fill only what you actually ran. Write `not tested` rather
than guessing. Do not include personal notes, account names, clipboard
contents, or vault paths that identify you.

## Environment

| Item | Value |
| --- | --- |
| Date | YYYY-MM-DD |
| OS and version | |
| Terminal app and version | |
| Python version | `python3 --version` |
| Jotline version | `jotline --version` |
| Install method | GitHub wheel / source / other |
| Assistive technology (if any) | none / VoiceOver / NVDA / Narrator / Orca + version |
| Input method (if exercised) | none / system IME name |

Jotline version must match the build you launched. CI and headless Pilot
results are not a substitute for this report.

## How to run the session

1. Create an empty folder and launch `jotline --vault PATH_TO_EMPTY_TEST_FOLDER`.
2. Follow [docs/terminal-testing.md](../terminal-testing.md) in order.
3. Record pass / fail / not tested for each row below.
4. For every failure, add a synthetic reproduction (smallest keyboard sequence,
   visible result, expected result). No personal text.

## Checklist results

| Check | Result | Notes |
| --- | --- | --- |
| 100×30: capture a note without opening help; writing stays visible | pass / fail / not tested | |
| 80×24: dialogs scroll to every control | pass / fail / not tested | |
| 60×20: dialogs scroll to every control | pass / fail / not tested | |
| Keyboard only (Tab, Shift+Tab, arrows, Enter, Space, Escape) through collections, views, actions, import, recovery | pass / fail / not tested | |
| Visible focus; Escape returns to the editor | pass / fail / not tested | |
| Dark theme: text, selection, focus, errors readable without relying on color | pass / fail / not tested | |
| Light theme: same | pass / fail / not tested | |
| Paste `café 日本語 مرحبا 👩🏽‍💻`, save, reopen, export; text matches | pass / fail / not tested | |
| IME composition; cursor, selection and undo around combining marks | pass / fail / not tested | |
| Copy a synthetic note into another app (OSC 52 enabled) | pass / fail / not tested | |
| Copy with OSC 52 disabled: Jotline describes a request, does not claim success | pass / fail / not tested | |
| External edit while unsaved: both draft and disk copy remain available | pass / fail / not tested | |
| Normal quit saves text | pass / fail / not tested | |
| Non-writable or busy vault: error is understandable; no silent data loss | pass / fail / not tested | |

## Screen reader (issue #3; skip if not tested)

Name the screen reader and terminal pairing. Check note editing, navigation,
action builder, import preview, and recovery dialog.

| Surface | Announced | Missed | Keyboard sequence for the miss |
| --- | --- | --- | --- |
| Editor text | | | |
| Control labels | | | |
| Focus changes | | | |
| Dialog open/close | | | |
| Save or validation errors | | | |

Do not call Jotline accessible solely because keyboard navigation works.
No certification is implied by filing this report.

## Failures

For each fail: synthetic notes only, exact keys, what you saw or heard, what
you expected. Link a bug issue if you open one.

1.

## Not tested

List rows you skipped and why (no hardware, no assistive tool, time).
