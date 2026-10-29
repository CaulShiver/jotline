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


## Writing upgrade qualification — 2026-10-29

Linux cloud workspace, CPython 3.12.14, Textual 8.2.8; Jotline 0.9.12 working
tree. No graphical terminal, VoiceOver or Orca was involved. These results are
local automated observations, not a native report or a claim about remote CI.

| Check | Result | Evidence |
| --- | --- | --- |
| Explicit names; widget IDs and user-entered values do not count as labels | Pass | `tests/test_accessibility.py`: 17 passed |
| Find options, all buttons, replace-all/undo and focus return by keyboard | Pass at 60×20, 80×24 and 100×30, dark and light themes | `tests/test_writing_accessibility.py` |
| Editor/preview contents filtering, selection, cancellation and focus return | Pass at all three sizes | `tests/test_writing_accessibility.py` |
| Footnotes-only Contents: jump to definition, return to first reference; Home/End scrolling; Escape keeps source unchanged | Pass at all three sizes | `tests/test_writing_accessibility.py` |
| Exported footnote reference/backlink descriptive titles | Pass in generated HTML | `tests/test_writing_accessibility.py` |
| Latest-dependency CI installs upgrades and executes tests; locked baseline retained | Workflow guard tests pass | `tests/test_dependency_ci.py` |
| Individual inline footnote references/backlinks as Tab stops | **Not supported**: use the Contents keyboard route to the definition or first reference; pointer backlinks reach repeated occurrences | Do not claim the inline links are individually keyboard-activated |
| VoiceOver, Orca, native IME/clipboard, measured contrast | **Not tested; native gate remains open** | Updated native templates and `docs/terminal-testing.md` |

`tests/test_writing_accessibility.py tests/test_dependency_ci.py`: **22 passed**.
The compositor checks caught and verified fixes for a scrollbar obscuring Find's
Done button and a clipped last row in the small-window contents palette. Merely
checking that a control's coordinates lie on screen would not catch these.
