# Headless Linux accessibility pass

**Not a native terminal report.** This file records what automated tests can
prove on Linux without VoiceOver, Orca, or Terminal.app. It does not close
issues #2 or #3.

| Check | Result | Evidence |
| --- | --- | --- |
| Interactive controls have a visible label, placeholder, or tooltip | Pass on the writing screen, Settings, views, find, recovery, capture, action builder, history, arrange, and bulk select | `tests/test_accessibility.py` |
| Keyboard-only capture, search, palette, recovery | Pass in Pilot | existing UI tests plus accessibility tests |
| Unicode NFC / NFD / CJK / Arabic / emoji round-trip | Pass in the editor and on disk | `test_unicode_and_combining_marks_round_trip` |
| Copy wording is a request, not a success claim | Pass when no OS clipboard tool | `test_copy_describes_osc52_when_native_clipboard_is_missing` |
| Native OS clipboard | Not this Linux headless pass | macOS `pbcopy` is covered in `macos-27-terminal.md` |
| VoiceOver / Orca announcements | **Not tested** | needs a native report |
| IME composition (not paste) | **Not tested** | paste of composed text is the stand-in |
| Terminal.app clipboard policy | See macOS 27 report | Terminal.app blocks OSC 52; copy uses `pbcopy` |

Jotline 0.9.4+, Linux, Python 3.12, Textual Pilot, no physical display.
