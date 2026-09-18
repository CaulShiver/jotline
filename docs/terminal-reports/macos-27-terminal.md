# macOS 27 Terminal.app report

Filled 2026-09-18 on a disposable vault. No personal notes.

- OS version: macOS 27.0 (Build 26A428), Darwin 27.0.0 arm64
- Terminal.app version: 2.15 (488)
- Python / Jotline versions: CPython 3.13.5 / Jotline 0.9.7 (Textual 8.2.8)
- VoiceOver: off
- Input method: U.S. keyboard layout (Option dead keys). Character Palette and PressAndHold are present. No Japanese IME enabled.

Followed [terminal-testing.md](../terminal-testing.md). Automated companion on this same Mac: `uv run --locked pytest -q` → **681 passed, 19 skipped**; `python -I scripts/smoke_pty.py` against the installed 0.9.7 wheel → POSIX PTY startup, Unicode bracketed paste, autosave, and Ctrl+Q passed.

| Step | Result | Notes |
| --- | --- | --- |
| 80×24 and 60×20 capture without help | pass | `jotline --vault DISPOSABLE` in Terminal.app. Typed `capture 80x24 without help` / `capture 60x20 without help`. Ctrl+Q. Exact text stored as an inbox note. No help screen opened. |
| Tab / Shift+Tab / Esc through collections, views, recovery | pass | Ctrl+P opened the command palette; Tab moved through it; Esc returned to the editor. Ctrl+, opened Settings; Esc closed it. Recovery dialog: see the recovery row. |
| Dark and light theme without relying on color | pass | Relaunched with `theme: textual-light` and `theme: jotline` in `.jotline-settings.json`. Both saved typed text. Meaning does not depend on color alone (labels and focus remain). |
| Paste `café 日本語 مرحبا 👩🏽‍💻` and IME composition | pass | Cmd+V (bracketed paste) stored that string exactly. IME: U.S. Option+e then e stored `é`. PressAndHold automation typed `e2` instead of composing; that is an automation limit, not a Jotline storage bug. |
| Copy with clipboard enabled | fail | Ctrl+P → Copy note. System clipboard (`pbpaste`) stayed on a pre-copy marker. Terminal.app did not apply OSC 52. Jotline still saved the note. |
| Copy with OSC 52 disabled (request, not success) | pass | Same Terminal.app session is the blocked-OSC-52 case. Copy wording is `Copy requested. Your terminal must allow OSC 52 clipboard access.` (`tests/test_accessibility.py::test_copy_describes_osc52_as_a_request` also passed here). No success claim. |
| VoiceOver: editor, labels, focus, save errors | skipped | VoiceOver was off. Not toggled (Cmd+F5) in this session. Accessibility Inspector names for Terminal UI elements were `missing value`; the TUI is a character grid, not Cocoa widgets. Do not treat this row as a screen-reader pass. Issue #3 stays open. |
| External edit recovery keeps both copies | pass | Seeded `local draft before conflict` with `jotline capture`, opened it, typed ` extra unsaved`, overwrote the file with `external rice`, Ctrl+S. Shift+Tab ×3, Return chose a preserve action. Original note kept `external rice`. Inbox recovery copy stored the on-screen draft with `recovery_of` set. `jotline recoveries` listed it. |
| Quit; unsaved text not lost silently | pass | Typed `quit should persist this sentence`, Ctrl+Q. Process exited; note file contained the sentence. |

iTerm2 is not installed on this Mac. Ghostty 1.3.1 is installed; `open -na Ghostty.app --args -e …` did not run Jotline (macOS Ghostty CLI launch limitation). Ghostty OSC 52 was therefore not certified.

Do not claim screen-reader compatibility. VoiceOver was not on.
