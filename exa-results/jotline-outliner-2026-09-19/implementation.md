**Implementation follow-through — 20 September 2026**

The outliner now edits inline, using one reusable TextArea over a wrapped,
line-rendered ScrollView. The canonical Markdown editor remains responsible
for source history and saving. OutlineSession maintains derived identities and
fold state; identities at recent source revisions support undo/redo.

The Markdown parser uses markdown-it-py's CommonMark block tokens and source
line maps. It skips inline tokenization, which does not affect list ownership.
Each child records a slot among its parent's own source lines. This permits
parent text before and after a nested list without reassigning it to a child.
Untouched Markdown remains byte-preserved, including CRLF. The five concrete
research regressions have tests, alongside 250 generated branch operations
checked for stable block count, parent consistency, and parser agreement.

Ordinary typing patches the active block's contiguous source range. Interleaved
parent content and branch operations use a bounded source diff. Wrapped rows
are cached; ordinary same-height edits refresh only the active block. Structure
changes still rebuild the derived block index and visible-row layout. This is
not a fully incremental CommonMark container parser.

Implemented workflows include boundary-aware split/merge, explicit new child,
continuation-line menu fallback, Unicode/wrapped navigation, separate branch
selection, grouping, duplicate, cycle-safe same-note move-to, two paste modes,
search through folds, focus history, clickable ancestors, optional inspector,
revision-checked per-note view persistence, configurable outline shortcuts,
default writing mode, application commands, daily/note navigation, formatting,
link and snippet completion, permanent anchors, and read-only reference previews.

The extension is `^id` plus `[[note-id#^id]]`. Existing Markdown is not assigned
persistent anchors automatically. Duplicates remove anchors. Preview expands
one referenced branch only; it cannot recurse through cycles. Cross-note branch
transactions and editable mirrors remain outside this implementation, consistent
with the research sequence that places them after reliable same-note operations.

**Measurements.** The opt-in `tests/test_outline_measurements.py` runs a real
Textual application in headless test mode at 110×35, with seven direct flush
samples per size. `implementation-measurements.json` records the results.

| Blocks | Open + headless settling | Median direct edit flush | Maximum of 7 flushes |
| --- | ---: | ---: | ---: |
| 1,000 | 290 ms | 2.3 ms | 3.1 ms |
| 10,000 | 1,212 ms | 20.3 ms | 21.5 ms |

One block editor was mounted at each size; the viewport showed 24 rows.
The opening measurement includes headless event settling. Flush measurements
exclude the next paint, terminal transport, and disk I/O. They are not directly
comparable to the original report's stubbed sync benchmark and are not p95
end-to-end input latency. Opening 10,000 blocks still exceeds the proposed
500 ms target. A screenshot was visually reviewed after fixing a strip-rendering
newline artifact. Real Orca/VoiceOver and terminal-emulator usability testing
has not been performed by this implementation run.

**Validation and installation.** The broad application run completed with 738
passes, 41 skips, and one outdated dependency-list assertion. That assertion
was updated for the declared Markdown parser; all eight packaging tests passed.
The integration rerun passed 174 tests. After the final tab-preservation and
literal-paste refinements, all 57 outliner tests passed. The opt-in measurement
test also passed. New outliner modules and their tests pass Ruff.

An isolated installed-wheel smoke test passed CLI capture/export, writing, tags,
workspaces, shortcuts, Markdown, templates, backups, actions, filters and import.
`scripts/smoke_outline_pty.py` passed against the installed wheel using a real
POSIX pseudo-terminal: palette entry, inline Unicode paste, a continuation-line
menu command, autosave and Ctrl+Q. Its first attempt sent input during mounting;
the harness now waits for the ready status and an editor repaint. This is
terminal-protocol coverage, not a screen-reader or terminal-emulator audit.

The local `jotline` tool was replaced with this development build of 0.9.8. No
release was published and existing unrelated working-tree changes were retained.

**PR branch validation.** Prepared against `origin/main` at `1fe0b95` in a
separate worktree, excluding unrelated hardening changes. The complete suite
on that branch passed: **738 passed, 41 skipped** in 315 seconds. Lock and
whitespace checks passed. A fresh environment installed the branch's wheel
and passed both the CLI/TUI installation smoke and POSIX outliner PTY smoke.
The PTY harness also waits for the continuation command to reach the saved
source before sending subsequent pasted text. The review screenshot uses
synthetic planning blocks. Native macOS and screen-reader validation remains
unperformed locally.
