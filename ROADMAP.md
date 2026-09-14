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
- Install a versioned package without Git and share reproducible bug reports.

## Next priorities

The September 14 quality audit in [docs/quality-backlog.md](docs/quality-backlog.md)
leaves this as documentation. The recommended first implementation slice is
**backlinks quality**: a connections panel with incoming and outgoing notes,
context snippets, cursor-aware follow, fence-aware link parsing, broken-link
state, a default hotkey, and `jotline backlinks`. Do not start a graph, plugin
host, or AI layer to make the connect loop feel finished.

After that audit, the everyday-usability order is:

1. Finish the advertised connect loop (backlinks quality slice above).
2. Validate the release with newcomers on Linux, macOS and Windows. Measure
   whether they can install, capture, find, connect, process and recover a
   note unaided.
3. Establish native terminal and assistive-technology coverage using
   [the terminal checklist](docs/terminal-testing.md). Compact terminals
   (80×24) should still reach search, collections, and backlinks.
4. Improve performance using representative synthetic vault benchmarks before
   introducing indexing or storage complexity. Search and backlinks should
   share any later index.
5. Expand community recipes and migration fixtures based on real user workflows.

External executable actions, regex search, dictation, AI and plugin APIs need
separate designs and evidence of user demand. They are not required to capture
or process notes locally. Unlinked mentions, attachments, and search OR stay
parked until the connect loop and first-hour reports are in place.

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
