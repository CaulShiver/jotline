# Windows Terminal report

Fill this on native Windows (not WSL unless you say so). Use a disposable vault.

- Windows version:
- Windows Terminal version:
- Python / Jotline versions:
- NVDA or Narrator: which, version, on / off
- IME:

Follow [terminal-testing.md](../terminal-testing.md). For each step: pass, fail,
or skipped, with one keyboard sequence for every failure.

| Step | Result | Notes |
| --- | --- | --- |
| 80×24 and 60×20 capture without help | | |
| Tab / Shift+Tab / Esc through collections, views, recovery | | |
| Dark and light theme without relying on color | | |
| Paste `café 日本語 مرحبا 👩🏽‍💻` and IME composition | | |
| Copy with clipboard enabled | | |
| Copy with OSC 52 disabled (request, not success) | | |
| NVDA/Narrator: editor, labels, focus, save errors | | |
| External edit recovery keeps both copies | | |
| Quit; unsaved text not lost silently | | |

Do not claim screen-reader compatibility unless NVDA or Narrator was actually on.
