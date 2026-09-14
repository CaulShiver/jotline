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

The quality sequence in [docs/quality-backlog.md](docs/quality-backlog.md) is
the current plan:

1. **Backlinks quality** — shipped: connections panel, snippets, cursor-aware
   follow, fence-aware parsing, broken-link create, Alt+K, and
   `jotline backlinks`.
2. **Compact-terminal and empty states** — shipped: 80×24 keeps `←N →N` on
   the status line; locked and broken links have their own copy.
3. **Hands-on terminal and AT reports** — still open as issues
   [#2](https://github.com/CaulShiver/jotline/issues/2) and
   [#3](https://github.com/CaulShiver/jotline/issues/3). Close them only after
   a native report lands under `docs/terminal-reports/`.
4. **Indexing** — design and baseline measurements are in
   [docs/indexing-design.md](docs/indexing-design.md). Search and backlinks
   already share `workspace_notes()`. Do not add an index until a measured
   vault exceeds that budget.
5. **Search OR / attachments / unlinked mentions** — parked until there is
   evidence people need them.

Validate the release with newcomers on Linux, macOS and Windows. Measure
whether they can install, capture, find, connect, process and recover a note
unaided. Expand community recipes and migration fixtures from real workflows.

External executable actions, regex search, dictation, AI and plugin APIs need
separate designs and evidence of user demand. They are not required to capture
or process notes locally.

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
