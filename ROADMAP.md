# Jotline roadmap

Jotline aims to make capture, finding, processing and recovery understandable
without reading the entire README. New integrations remain user-triggered and
the writing core remains offline.

## Current milestone: everyday usability

- Configure and preview useful local actions without writing JSON.
- Discover collections, saved views and basic workflows in the app.
- Edit, rename and duplicate saved configurations.
- Resolve save conflicts while preserving both versions.
- Preview folder and Drafts imports, then report exactly what was imported.
- Install with a one-liner or PyPI (`uv tool install jotline`) without Git or
  hunting a GitHub wheel. Linux and macOS stay in the contract; Windows is
  out of scope.
- Bind `jotline capture` from a desktop hotkey using shipped Hyprland, GNOME,
  KDE, and Omarchy snippets or `jotline desktop install`.

## Next priorities

1. Validate the release with newcomers on Linux and macOS. Measure
   whether they can install, capture, find, connect, process and recover a note
   unaided.
2. Establish native terminal and assistive-technology coverage using
   [the terminal checklist](docs/terminal-testing.md). VoiceOver on
   Terminal.app and Orca on Linux are a **1.0 ship criterion**. The headless
   pass in [docs/terminal-reports/](docs/terminal-reports/) is toward that
   gate, not a substitute. Clipboard copy uses the OS clipboard when a native
   tool is present, and OSC 52 as a fallback request. Windows is out of scope.
3. Measure search with [synthetic vault benchmarks](docs/vault-scale.md) before
   introducing indexing. In-memory scan still meets the bar; doctor, conflicts,
   and backups remain the durability product.
4. Expand community recipes and migration fixtures based on real user workflows.
   Start from `examples/actions/`; do not add a plugin SDK.

Connecting notes is a visible loop (connections panel, follow, and
create-from-broken-`[[link]]`). Attachments, unlinked mentions, and a graph
view stay parked until that panel is used daily.

External executable actions, regex search, dictation, AI and plugin APIs need
separate designs and evidence of user demand. They are not required to capture
or process notes locally.

**Edit this note in $EDITOR** is not one of those. Local actions still run only
built-in steps and evaluate no shell; that boundary is unchanged. This runs one
program, named by the user in their own environment, on an explicit command,
with no scripting surface and nothing configurable inside the app.

## Starter contributions

Each item can be proposed as a focused issue or PR:

| Task | Acceptance criteria |
| --- | --- |
| Document one terminal setup | Record OS/terminal versions, keyboard and clipboard behavior using the checklist; no personal notes. |
| Add an example local action | Include a recipe, synthetic input/output, and a test; use supported built-in steps only. |
| Improve one confusing empty state | Describe the trigger, include before/after screenshots, and verify keyboard navigation. |
| Add a migration fixture | Provide a minimal synthetic export and verify metadata mapping and duplicate behavior. |
| Report a contrast or focus issue | Identify theme/control/terminal and provide a reproducible keyboard path. |

Discuss changes that alter note formats, shortcuts, or public APIs before
implementation. See [CONTRIBUTING.md](CONTRIBUTING.md).
