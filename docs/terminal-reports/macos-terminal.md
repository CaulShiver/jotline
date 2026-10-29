# macOS Terminal.app report

Fill this on a Mac. Use a disposable vault. Do not paste personal notes.

- OS version:
- Terminal.app version:
- Python / Jotline versions and tested commit:
- VoiceOver: on / off (version if on)
- Input method:

Follow [terminal-testing.md](../terminal-testing.md). For each step: pass, fail,
or skipped, with one keyboard sequence for every failure.

| Step | Result | Notes |
| --- | --- | --- |
| 80×24 and 60×20 capture without help | | |
| Tab / Shift+Tab / Esc through collections, views, recovery | | |
| Find: named options, match counts, Tab/Shift+Tab, replace/undo at 60×20 | | |
| Contents: filter, arrows/Enter, headings and focus return in editor/preview | | |
| Footnotes: references, definitions, backlinks; record keyboard reachability | | |
| Dark and light theme without relying on color | | |
| Paste `café 日本語 مرحبا 👩🏽‍💻` and IME composition | | |
| Copy with clipboard enabled | | |
| Copy with OSC 52 disabled (request, not success) | | |
| VoiceOver: editor, labels, focus, save errors, find counts, contents, footnotes | | |
| External edit recovery keeps both copies | | |
| Quit; unsaved text not lost silently | | |

Do not claim screen-reader compatibility unless VoiceOver was actually on.

For failures include the exact keyboard sequence and missing announcement.
Unavailable environments or disabled assistive tools are **pending/skipped**, never passes.
