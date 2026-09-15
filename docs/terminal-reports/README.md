# Native terminal and screen-reader reports

Automated Pilot tests cannot certify VoiceOver, NVDA, Narrator, Orca, an IME, or
a terminal clipboard. Those reports are a **1.0 ship criterion**, not
help-wanted afterthoughts. Issues
[#2](https://github.com/CaulShiver/jotline/issues/2) (native terminal) and
[#3](https://github.com/CaulShiver/jotline/issues/3) (screen reader) stay open
until a human fills a report from this folder.

## Required for 1.0

One filled report for each row. Use a disposable vault. Include versions. Do
not paste personal notes or clipboard contents.

| Target | Template | Assistive / input |
| --- | --- | --- |
| macOS Terminal.app | [macos-terminal.md](macos-terminal.md) | VoiceOver, system IME, clipboard |
| Windows Terminal | [windows-terminal.md](windows-terminal.md) | NVDA or Narrator, IME, clipboard |
| Linux GNOME Terminal or similar | [linux-orca.md](linux-orca.md) | Orca, IBus/Fcitx, OSC 52 |

The checklist lives in [terminal-testing.md](../terminal-testing.md). Copy a
template, rename it to include the OS version (for example
`macos-15-terminal.md`), and open a PR.

## What CI already covers

[linux-headless.md](linux-headless.md) records the headless Linux pass: labeled
controls (writing, Settings, views, find, recovery, capture, actions, history,
arrange, bulk select), Unicode round-trip (stand-in for IME), and honest OSC 52
copy wording. That is **toward** 1.0, not a substitute for the three native
reports. Ctrl+P → **Clipboard, IME, and screen-reader notes** repeats those limits
in the app.
