# Native terminal and screen-reader reports

Automated tests and CI smoke checks cover application behavior on Linux, macOS,
and Windows. They do **not** certify a particular terminal emulator, clipboard
policy, input method, or screen reader.

Hands-on reports belong in this folder. Copy
[TEMPLATE.md](TEMPLATE.md), fill every section you actually ran, and open a
pull request. Leave blank or write `not tested` for setups you did not use.
Do not invent results.

Open issues:

- [#2 Document a native macOS or Windows terminal compatibility report](https://github.com/CaulShiver/jotline/issues/2)
- [#3 Record screen-reader behavior in a native terminal](https://github.com/CaulShiver/jotline/issues/3)

The [terminal and accessibility checklist](../terminal-testing.md) is the
procedure. Suggested filenames: `macos-terminal-app.md`,
`windows-terminal-nvda.md`. Use a disposable vault and synthetic notes only.
