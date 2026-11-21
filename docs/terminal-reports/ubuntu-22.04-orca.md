# Ubuntu 22.04: Orca capture, find, and file

**Result: not screen-reader qualified.** The keyboard sequence worked visually,
but Orca did not announce selected commands, and save and search speech was
incomplete. This is a scoped native assessment, not human-user sign-off or a
completed 1.0 qualification.

- Date: 2026-11-20. Ubuntu 22.04.5, KDE/X11.
- GNOME Terminal 3.44.0, VTE 0.68.0, AT-SPI 2.44.0.
- Orca 42.0 enabled, Speech Dispatcher 0.11.1. Quotes are Orca debug speech
  output; audible playback was not verified.
- Python 3.12.16, Textual 8.2.8, Jotline 0.9.12 at [`b7d49eb`](https://github.com/CaulShiver/jotline/commit/b7d49eb6cd800120a852ca264796167091c8cbb4)
  ([capture improvements](https://github.com/CaulShiver/jotline/pull/45)).
- The recorded run used a fresh synthetic vault, passed with `--vault` and
  verified before interacting. IBus/Fcitx were not tested.

## Native results

First run `printf 'ORCA CONTROL: alpha bravo terminal output\n'` in the same
terminal. Orca emitted the control text, so silence later in the palette was
not caused by Orca being off.

| Workflow | Keyboard / visual result | Orca speech result |
| --- | --- | --- |
| First capture | Launch in a new vault, type a two-line note titled `Orca orchard capture`, then Ctrl+S. Exact text saved to inbox. | **Fail:** the editor text was available, but visible **Saved** was clipped to `ed · 7 words · 1 inbox · ←0 →0`. |
| Find and open | With another note open, Ctrl+F → `orchard` → Enter opened the correct note intact. | **Fail:** search mixed `ALL / 1`, the query, border characters, and the other note's text instead of identifying the matching result. After opening, Orca emitted the correct note title and body. |
| Process oldest capture | With two captures in inbox, unfiltered Ctrl+P → Down ×4 highlighted **Process next inbox note**; Enter opened the oldest capture. | **Fail:** no selected-command speech on the four Down events. Orca's trace shows those events at 15:04:55–57 and no speech until Enter at 15:05:10. It then emitted `Process this capture · 2 in inbox`. |
| File to projects | With that capture open, Ctrl+P → `move note to` → Down ×2 → Enter filed the note to **projects** and opened the next inbox capture. The stored collection and intact reopened body were verified. | **Fail:** the highlighted move command was not announced. After executing it, Orca emitted `Next inbox capture · 1 remaining`. |
| External capture and refresh | While `shellriver` showed no matches, capture `shellriver external thought` in a second terminal. The open search refreshed without changing the query or draft; processing the next inbox capture cleared the stale filter. | **Not assessed:** the TUI was inactive when the external capture arrived, so this does not establish live announcements in the active window. |
| Shell comparison | `jotline capture "shellriver external thought"` and `jotline search orchard` wrote ordinary terminal output. | **Pass for these outputs:** Orca emitted the full capture confirmation, including the short ID, and a search row containing `projects` and `Orca orchard capture`. |

Orca also logged untimestamped keyboard-event exceptions; the Down events in
the selected-command reproduction were logged and passed through. This run
does not establish whether Orca, VTE, Textual, or app behavior owns each gap.

## Follow-up: shell workaround

The tested TUI revision had no shell command for moving an existing note to
projects. The later `move` command completes the
[plain-text shell workflow](../shell.md#capture-read-and-file-without-opening-the-app)
without changing TUI announcements.

On the same native stack, a separate run on the changed CLI used a new empty
vault, an explicit `--vault`, and the focused terminal speech control. Orca
emitted the following without entering the full-screen app:

| Shell step | Orca speech output |
| --- | --- |
| `capture 'Orchard plan for Orca'` | `Saved to inbox: Orchard plan for Orca (b3b30f0e)` |
| `search orchard` | Full note ID, `inbox`, and `Orchard plan for Orca` |
| `export b3b30f0e` | `Orchard plan for Orca` |
| `move b3b30f0e projects` | `Moved to projects: Orchard plan for Orca` |
| Search and export again | Same full ID and body; search now reports `projects` |
| `move b3b30f0e trash` | `invalid choice: 'trash'` and allowed destinations; exit 2, note unchanged |

## Remaining checks

Other terminal sizes, save errors, the in-note Find dialog, contents, footnotes,
contrast, clipboard, IME, recovery, and quit-loss checks were not covered.
VoiceOver and first-time use by a screen reader user remain unverified.
[The screen reader issue](https://github.com/CaulShiver/jotline/issues/3) and
the [native release gate](../terminal-testing.md#10-ship-criterion) stay open.
