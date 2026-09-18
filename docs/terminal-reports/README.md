# Native terminal and screen-reader reports

Automated Pilot tests cannot certify VoiceOver, Orca, an IME, or
a terminal clipboard. Those reports are a **1.0 ship criterion**, not
help-wanted afterthoughts. Issues
[#2](https://github.com/CaulShiver/jotline/issues/2) (native terminal) and
[#3](https://github.com/CaulShiver/jotline/issues/3) (screen reader) stay open
until a human fills a report from this folder.

## Filled reports

| Report | Covers | Does not cover |
| --- | --- | --- |
| [macos-27-terminal.md](macos-27-terminal.md) | Terminal.app 2.15 on macOS 27: capture, keyboard, themes, Unicode paste, U.S. Option dead-key IME, `pbcopy` copy, recovery, quit | VoiceOver announcements (issue #3); iTerm2; Ghostty |

## Required for 1.0

One filled report for each row. Use a disposable vault. Include versions. Do
not paste personal notes or clipboard contents.

| Target | Template | Assistive / input |
| --- | --- | --- |
| macOS Terminal.app | [macos-terminal.md](macos-terminal.md) | VoiceOver, system IME, clipboard |
| Linux GNOME Terminal or similar | [linux-orca.md](linux-orca.md) | Orca, IBus/Fcitx, OSC 52 |

The checklist lives in [terminal-testing.md](../terminal-testing.md). Copy a
template, rename it to include the OS version (for example
`macos-15-terminal.md`), and open a PR. The macOS 27 Terminal.app report
closes the native-emulator half of issue #2. It does **not** close issue #3.

## What CI already covers

[linux-headless.md](linux-headless.md) records the headless Linux pass: labeled
controls (writing, Settings, views, find, recovery, capture, actions, history,
arrange, bulk select), Unicode round-trip (stand-in for IME), and honest OSC 52
copy wording. That is **toward** 1.0, not a substitute for the two native
reports. Ctrl+P → **Clipboard, IME, and screen-reader notes** repeats those limits
in the app. Windows is out of scope.
